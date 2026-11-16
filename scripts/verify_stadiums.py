"""Verify stadium records against a raw census and fixture venues against fresh native reads."""
import argparse
import asyncio
import hashlib
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import struct
import sys
import tomllib
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from verify_fixtures import native_clock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp import competition_stages, database, players, world
from fm_live_mcp.bridge import Bridge, BridgeError
from survey_resident_fixtures import managers
NATIVE_PROOF = json.loads((ROOT/'evidence/stadium-layout-verification.json').read_text())
assert NATIVE_PROOF['verified']


def check_stadium(actual, source, details=True):
    raw = bytes.fromhex(source['raw'])
    for field in ('native_id','database_index','name','continental_name'):
        assert actual[field] == source[field], (field,actual[field],source[field])
    assert actual['name_source'] == 'stored_native_strings'
    assert actual['is_extinct'] == bool(raw[0xAB]&1)
    assert actual['is_training_ground'] == bool(raw[0xAB]&4)
    assert actual['stadium_ref']
    if not details:
        return
    for i,key in enumerate(('total','seated','used','all_seater_competitions','expansion')):
        value = struct.unpack_from('<i',raw,0x7C+i*4)[0]
        missing = key in ('used','all_seater_competitions') and value<=0
        assert actual['capacities'][key] == {'value':None if missing else value,'native_value':value,
                                            'state':'not_specified' if missing else 'stored'}
    latitude,longitude = struct.unpack_from('<ff',raw,0x70)
    assert actual['coordinates'] == {'latitude':latitude,'longitude':longitude,'state':'stored'}
    assert actual['pitch']['dimension_unit'] == 'metres'
    for i,key in enumerate(('default','international','minimum','maximum')):
        for j,axis in enumerate(('length','width')):
            n = struct.unpack_from('<h',raw,0x98+i*4+j*2)[0]
            missing = n<1 if key=='international' else n<=-10 if key in ('minimum','maximum') else False
            assert actual['pitch']['dimensions'][key][axis] == {'value':None if missing else n/10,
                'native_tenths':n,'state':'not_specified' if missing else 'stored'}
    assert actual['pitch']['condition'] == struct.unpack_from('<h',raw,0xA8)[0]
    assert actual['pitch']['recovery_rate'] == struct.unpack_from('<b',raw,0xAE)[0]
    assert actual['decay'] == struct.unpack_from('<b',raw,0xAA)[0]
    for key,offset in (('type',0xAD),('deterioration_rate',0xAC)):
        assert actual['pitch'][key]['native_code'] == struct.unpack_from('<b',raw,offset)[0]
    for key,offset in (('stadium_condition',0xAF),('environment',0xB0),('owner_type',0xB4)):
        assert actual[key]['native_code'] == struct.unpack_from('<b',raw,offset)[0]
    for key,offset in (('senior',0xB1),('under21',0xB2),('under19',0xB3)):
        code = struct.unpack_from('<b',raw,offset)[0]
        label = NATIVE_PROOF['national_usage_labels'].get(str(code))
        assert actual['national_team_usage'][key] == {'native_code':code,'name':label,
                                                     'state':'decoded' if label else 'unmapped'}
    assert actual['facilities'] == {'has_digital_advertising':bool(raw[0xAB]&64),
        'has_undersoil_heating':bool(raw[0xB6]&2),'has_retractable_roof':bool(raw[0xB6]&64),'stored_covered':bool(raw[0xB6]&1)}
    for key,offset in (('built',0x30),('rebuilt',0x34),('pitch_relay_required',0x2C)):
        packed = struct.unpack_from('<I',raw,offset)[0]
        year,day = packed>>16,packed&511
        missing = (year,day)==(1900,1)
        assert actual['dates'][key] == {'date':None if missing else (date(year,1,1)+timedelta(days=day-1)).isoformat(),
            'state':'not_specified' if missing else 'stored','native_year':year,'native_day':day}


class NativeFixtureReader:
    """Independent sequential raw reader; refresh bytes beside every MCP page."""
    def __init__(self, year):
        self.bridge = Bridge()
        self.sid = self.bridge.attach()['session_id']
        self.year = year
        self.day, self.group, self.slot = 1, 0, 0
        self.inventory = None
        self.save_dates = set()
        self.end_day = 366

    def reset_day(self, day):
        self.day,self.group,self.slot = day,0,0
        self.end_day = day
        self.inventory = None

    def close(self):
        self.bridge.detach()

    def take(self, count):
        for attempt in range(5):
            position = self.day,self.group,self.slot
            try:
                return self._take(count)
            except (ValueError,BridgeError) as exc:
                self.day,self.group,self.slot = position
                if 'changed during read' not in str(exc) or attempt==4:raise
                time.sleep(0.2)

    def _take(self, count):
        b = self.bridge
        rows = []
        with b.lock,b._read_scope(self.sid):
            process = b._current(self.sid)
            layout = b._player_layout(process)
            base = layout[0]-players.RVA[0]
            read,save,_ = b._world_state(process,layout)
            inventory = managers(read,base)
            assert self.inventory is None or inventory==self.inventory, 'Native fixture inventory changed'
            self.inventory = inventory
            selected = [r for r in inventory if r[2]==self.year]
            assert len(selected)==1
            groups = selected[0][4]
            teams = database.table(read,base,'teams')
            names = database.table(read,base,'fixture_names')
            competitions = database.table(read,base,'competitions')
            self.save_dates.add(save['current_date'])
            def native_id(pointer,table):
                if not pointer:return None
                index,identifier = struct.unpack('<II',read(pointer+8,8))
                assert index<table['count'] and world.pointer(read,table['start']+index*8)==pointer
                return identifier
            while self.day<=self.end_day and len(rows)<count:
                if self.group>=len(groups):
                    self.day,self.group,self.slot = self.day+1,0,0
                    continue
                group = groups[self.group]
                header = players.u64(read(group+(self.day-1)*8,8)) if read(group+0xB70,1)[0]&1 else 0
                entries = world.vector(read,header,2000) if header else ()
                assert self.slot<=len(entries), 'Native fixture bucket changed'
                while self.slot<len(entries) and len(rows)<count:
                    address = entries[self.slot]
                    vtable = world.pointer(read,address)-base
                    assert vtable in (0x5672C88,0x5672E00), f'Unsupported independent fixture record type: {vtable:#x}'
                    type_name = b'N7sicomps7FIXTUREE' if vtable==0x5672C88 else b'N7sicomps14FIXTURE_RESULTE'
                    competition_stages.typed(read,base,address,(vtable,type_name))
                    raw = read(address,0x58 if vtable==0x5672C88 else 0x80)
                    packed = struct.unpack_from('<I',raw,0x4C)[0]
                    assert packed>>16==self.year and packed&511==self.day
                    competition = None
                    name = players.u64(raw,0x20)
                    if name:
                        competition_stages.typed(read,base,name,(0x55AB970,b'N2db12FIXTURE_NAMEE'))
                        native_id(name,names)
                        competition = native_id(players.u64(read(name+0x18,8)),competitions)
                    scores = None
                    if vtable==0x5672E00:
                        scores = {label:{side:None if raw[at+i]==255 else raw[at+i]
                                        for side,at in (('home',0x64),('away',0x69))}
                                  for i,label in enumerate(('normal_time','extra_time','penalties','aggregate'))}
                        scores['final_score'] = {side:scores['extra_time'][side] if scores['extra_time'][side] is not None
                                                else scores['normal_time'][side] for side in ('home','away')}
                    rows.append({'date':(date(self.year,1,1)+timedelta(days=self.day-1)).isoformat(),
                        'kind':'fixture_record' if vtable==0x5672C88 else 'result_record',
                        'home':native_id(players.u64(raw,8),teams),'away':native_id(players.u64(raw,16),teams),
                        'competition':competition,'scores':scores,'kickoff_time':native_clock(packed),
                        'stadium_address':players.u64(raw,0x28)})
                    self.slot+=1
                if self.slot==len(entries):self.group,self.slot=self.group+1,0
            read.verify()
            b._current(self.sid)
        return rows


def save_checkpoint(path, receipt, identity):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({**receipt,'source_identity':identity},indent=2)+'\n')
    temporary.replace(path)


async def verify(resume_stadiums=False, fixture_years=(2030,2025)):
    census = json.loads((ROOT/'evidence/stadium-survey.json').read_text())
    assert census['verified']
    stadiums = census['stadiums']
    by_address = {int(r['address'],16):r for r in stadiums}
    config = tomllib.loads((Path.home()/'.codex/config.toml').read_text())['mcp_servers']['fm-live']
    checkpoint = ROOT/'evidence/stadium-verification-checkpoint.json'
    identity = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'fm_live_mcp').glob('*.py'))}
    identity['stadium_census'] = hashlib.sha256((ROOT/'evidence/stadium-survey.json').read_bytes()).hexdigest()
    receipt = {'verified':False,'observed_at':datetime.now(timezone.utc).isoformat(),'filters':[], 'fixture_years':[]}
    if resume_stadiums:
        receipt = json.loads(checkpoint.read_text())
        assert receipt.pop('source_identity')==identity and receipt['stadium_verification_complete']
        assert isinstance(receipt['fixture_years'],list)
    async with stdio_client(StdioServerParameters(command=config['command'],args=config['args'])) as (read,write):
        async with ClientSession(read,write) as client:
            await client.initialize()
            async def call(tool,**args):
                for attempt in range(5):
                    result = await client.call_tool(tool,args)
                    if not result.isError:break
                    if 'changed during read' not in str(result.content) or attempt==4:break
                    await asyncio.sleep(0.2)
                assert not result.isError and result.structuredContent is not None,(tool,args,result.content)
                return result.structuredContent
            status = await call('fm_status')
            receipt['server_version'] = status['server_version']
            assert status['capabilities']['stadium_query'] and status['capabilities']['fixture_venues']
            sid = (await call('fm_attach'))['session_id']
            try:
                if not resume_stadiums:
                    cursor,count,pages = None,0,0
                    samples = set()
                    while True:
                        page = await call('fm_find_stadiums',session_id=sid,max_matches=100,cursor=cursor)
                        assert page['start_index']==count
                        for row in page['stadiums']:
                            source = stadiums[count]
                            check_stadium(row,source)
                            case = (bool(row['continental_name']),row['is_extinct'],row['is_training_ground'],row['dates']['built']['native_year']>2100)
                            if case not in samples:
                                fresh = (await call('fm_get_stadium',session_id=sid,stadium_ref=row['stadium_ref']))['stadium']
                                check_stadium(fresh,source)
                                samples.add(case)
                            count += 1
                        pages += 1
                        cursor = page['next_cursor']
                        if pages%50==0:print(f'Stadiums: {count}/{len(stadiums)}',flush=True)
                        if not cursor:break
                    assert count==len(stadiums)==25891
                    receipt.update(stadiums_checked=count,stadium_readback_cases=len(samples))
                    # Each selector is evaluated independently against the raw census.
                    filters = [({'native_id':688},lambda r:r['native_id']==688),
                        ({'name':'FUSSBALL'},lambda r:any('fussball' in (r[k] or '').casefold() for k in ('name','continental_name'))),
                        ({'name':'Arsenal Stadium'},lambda r:any('arsenal stadium' in (r[k] or '').casefold() for k in ('name','continental_name'))),
                        ({'minimum_capacity':100000},lambda r:r['capacity']['capacity']>=100000),
                        ({'is_training_ground':True,'is_extinct':False,'minimum_capacity':10000},
                         lambda r:bool(r['flags']['ab']&4) and not r['flags']['ab']&1 and r['capacity']['capacity']>=10000)]
                    for args,predicate in filters:
                        cursor,ids,empty = None,[],0
                        while True:
                            page = await call('fm_find_stadiums',session_id=sid,max_matches=100,cursor=cursor,**args)
                            ids.extend(r['native_id'] for r in page['stadiums'])
                            empty += page['count']==0
                            cursor = page['next_cursor']
                            if not cursor:break
                        assert ids==[r['native_id'] for r in stadiums if predicate(r)],args
                        receipt['filters'].append({'criteria':args,'matches':len(ids),'empty_pages':empty})
                        print(f'Stadium filter: {args}: {len(ids)}',flush=True)
                    receipt['stadium_verification_complete']=True
                    save_checkpoint(checkpoint,receipt,identity)
                coverage = await call('fm_get_fixture_coverage',session_id=sid)
                resident_years = {r['year'] for r in coverage['years']}
                assert set(fixture_years)<=resident_years, (fixture_years,sorted(resident_years))
                progress = receipt.get('fixture_progress')
                if progress and progress['year'] not in fixture_years:
                    assert progress['year'] not in resident_years, 'Do not discard progress for a resident archive'
                    receipt.setdefault('deferred_fixture_scans',[]).append({**receipt.pop('fixture_progress'),
                        'reason':'year_no_longer_resident','coverage_observed_at':coverage['observed_at'],
                        'coverage_save_date':coverage['save']['current_date']})
                    save_checkpoint(checkpoint,receipt,identity)
                for year in fixture_years:
                    if any(item['year']==year for item in receipt['fixture_years']):
                        print(f'Reusing completed fixture-year verification: {year}',flush=True)
                        continue
                    native_reader = NativeFixtureReader(year)
                    progress = receipt.get('fixture_progress', {})
                    assert not progress or progress['year']==year
                    last_day = progress.get('last_day',0)
                    assert type(last_day) is int and 0<=last_day<366
                    count,pages,readbacks = progress.get('fixtures_checked',0),0,progress.get('readback_cases',0)
                    cases = Counter(progress.get('venue_states',{})); unique=set(progress.get('stadium_ids',[]))
                    retries = progress.get('restarted_days',[])
                    native_reader.save_dates.update(progress.get('native_save_dates_observed',[]))
                    assert sum(cases.values())==count
                    if last_day:print(f'Resuming {year} after {last_day} completed days: {count} fixtures',flush=True)
                    try:
                        total_days = (date(year+1,1,1)-date(year,1,1)).days
                        for day in range(last_day+1,total_days+1):
                            calendar_date = (date(year,1,1)+timedelta(days=day-1)).isoformat()
                            for attempt in range(5):
                                native_reader.reset_day(day)
                                cursor,day_count,day_readbacks = None,0,0
                                day_cases = Counter(); day_unique=set()
                                try:
                                    while True:
                                        page = await call('fm_find_fixtures',session_id=sid,year=year,max_matches=100,
                                            cursor=cursor,date_from=calendar_date,date_to=calendar_date)
                                        baseline = native_reader.take(page['count'])
                                        assert len(baseline)==page['count']
                                        for row,prior in zip(page['fixtures'],baseline):
                                            address = prior['stadium_address']
                                            venue = row['stadium']
                                            if address:
                                                check_stadium(venue,by_address[address],details=False)
                                                day_unique.add(venue['native_id'])
                                            else:assert venue is None
                                            assert row['date']==prior['date'] and row['scores']==prior['scores'] and row['kickoff_time']==prior['kickoff_time'], (year,calendar_date,day_count,row['date'],prior)
                                            assert row['record_kind']==prior['kind']
                                            assert row['days_from_current_date']==(date.fromisoformat(row['date'])-date.fromisoformat(page['save']['current_date'])).days
                                            for field,key in (('home_team','home'),('away_team','away'),('competition','competition')):
                                                assert (row[field]['native_id'] if row[field] else None)==prior[key]
                                            case = 'stored' if address else 'null'
                                            if not cases[case] and not day_cases[case]:
                                                fresh = (await call('fm_get_fixture',session_id=sid,fixture_ref=row['fixture_ref']))['fixture']
                                                if address:
                                                    check_stadium(fresh['stadium'],by_address[address],details=False)
                                                    detail = (await call('fm_get_stadium',session_id=sid,stadium_ref=fresh['stadium']['stadium_ref']))['stadium']
                                                    check_stadium(detail,by_address[address])
                                                else:assert fresh['stadium'] is None
                                                day_readbacks+=1
                                            day_cases[case]+=1;day_count+=1
                                        pages+=1;cursor=page['next_cursor']
                                        if not cursor:break
                                    assert not native_reader.take(1), 'Public query ended before native day data'
                                    break
                                except (AssertionError,ValueError,BridgeError) as exc:
                                    if attempt==4 or not any(reason in str(exc) for reason in
                                        ('cursor expired','inventory changed','bucket changed','changed during read','Fixture reference rejected','fixture record type','Invalid or ambiguous resident fixture year')):raise
                                    retries.append({'date':calendar_date,'reason':str(exc)[:500]})
                                    await asyncio.sleep(0.2)
                            count+=day_count;cases.update(day_cases);unique.update(day_unique);readbacks+=day_readbacks
                            receipt['fixture_progress']={'year':year,'last_day':day,'fixtures_checked':count,
                                'venue_states':dict(cases),'stadium_ids':sorted(unique),'readback_cases':readbacks,
                                'native_save_dates_observed':sorted(native_reader.save_dates),'restarted_days':retries,
                                'unavailable_groups':len(page['coverage']['unavailable_group_indices'])}
                            save_checkpoint(checkpoint,receipt,identity)
                            if day%30==0:print(f'Fixture venues {year}: {day}/{total_days} days, {count} independently checked',flush=True)
                        receipt['fixture_years'].append({'year':year,'fixtures_checked':count,'calendar_days_checked':total_days,
                            'venue_states':dict(cases),'distinct_stadiums':len(unique),'readback_cases':readbacks,
                            'native_save_dates_observed':sorted(native_reader.save_dates),'restarted_days':retries,
                            'unavailable_groups':receipt['fixture_progress']['unavailable_groups']})
                        receipt.pop('fixture_progress',None)
                        save_checkpoint(checkpoint,receipt,identity)
                        print(f'Completed {year}: {count} fixtures',flush=True)
                    finally:native_reader.close()
            finally:await call('fm_detach')
    assert set(fixture_years)<={r['year'] for r in receipt['fixture_years']}
    receipt.update(verified=True,foreground_ui_used=False,native_execution=False,requested_fixture_years=list(fixture_years))
    (ROOT/'evidence/live-stadiums-mcp.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume-stadiums',action='store_true',help='Reuse a completed stadium checkpoint with identical production sources and census')
    parser.add_argument('--fixture-years',type=int,nargs='+',default=[2030,2025],help='Resident calendar years to verify completely')
    args=parser.parse_args()
    asyncio.run(verify(args.resume_stadiums,tuple(args.fixture_years)))
