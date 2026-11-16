"""Compare public city fields and stadium links against independent raw censuses."""
import argparse
import asyncio
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import struct
import tomllib

from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]


def verify_city(row,source,linked,population):
    raw=bytes.fromhex(source['raw'])
    for field in ('database_index','native_id','name'):assert row[field]==source[field],(field,row[field],source[field])
    assert row['city_ref'] and row['name_source']=='stored_native_strings'
    assert row['is_deleted']==bool(raw[0x55]&1)
    latitude,longitude=struct.unpack_from('<ff',raw,0x48)
    assert row['coordinates']=={'latitude':latitude,'longitude':longitude,'state':'stored'}
    assert row['altitude']=={'native_value':struct.unpack_from('<h',raw,0x50)[0],'unit':None,'state':'unit_unverified'}
    code=struct.unpack_from('<b',raw,0x52)[0];label=population.get(str(code))
    assert row['population']=={'native_code':code,'name':label,'state':'not_specified' if code==0 else 'decoded' if label else 'unmapped'}
    assert row['attraction']==struct.unpack_from('<b',raw,0x54)[0]
    for kind,offset in (('nation',0x20),('weather',0x28),('language',0x30),('local_region',0x38)):
        pointer=struct.unpack_from('<Q',raw,offset)[0]
        if not pointer:
            assert row[kind] is None
            continue
        expected=linked[kind][pointer]
        assert row[kind]=={k:v for k,v in expected.items() if k not in ('address','identity_raw')}|{'kind':kind,'name_source':'stored_native_strings'}


def checkpoint(path,receipt,identity):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps({**receipt,'source_identity':identity},indent=2)+'\n')
    temporary.replace(path)


async def verify(resume=False):
    sources={name:json.loads((ROOT/'evidence'/name).read_text()) for name in
             ('city-survey.json','city-linked-record-survey.json','stadium-links-survey.json','stadium-survey.json','city-layout-verification.json')}
    assert all(d['verified'] for d in sources.values())
    cities=sources['city-survey.json']['cities'];by_address={int(r['address'],16):r for r in cities}
    stadiums=sources['stadium-links-survey.json']['stadiums']
    stadium_names={r['native_id']:r['name'] for r in sources['stadium-survey.json']['stadiums']}
    linked={kind:{int(r['address'],16):r for r in table['records']} for kind,table in sources['city-linked-record-survey.json']['tables'].items()}
    population=sources['city-layout-verification.json']['editor_definitions']['Cinh']['enum_values']
    files=list(sorted((ROOT/'fm_live_mcp').glob('*.py')))+[ROOT/'evidence'/name for name in sources]
    identity={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    saved=ROOT/'evidence/city-verification-checkpoint.json'
    receipt={'verified':False,'server_version':'0.30.0','started_at':datetime.now(timezone.utc).isoformat(),
             'city_enumeration_complete':False,'stadium_links_complete':False}
    if resume:
        receipt=json.loads(saved.read_text())
        assert receipt.pop('source_identity')==identity
    config=tomllib.loads((Path.home()/'.codex/config.toml').read_text())['mcp_servers']['fm-live']
    async with stdio_client(StdioServerParameters(command=config['command'],args=config['args'])) as (read,write):
        async with ClientSession(read,write) as client:
            await client.initialize()
            async def call(tool,**args):
                for attempt in range(5):
                    result=await client.call_tool(tool,args)
                    if not result.isError or 'changed during read' not in str(result.content) or attempt==4:break
                    await asyncio.sleep(.2)
                assert not result.isError and result.structuredContent is not None,(tool,args,result.content)
                return result.structuredContent
            status=await call('fm_status')
            assert status['server_version']=='0.30.0' and status['capabilities']['city_query'] and status['capabilities']['stadium_links']
            tools=(await client.list_tools()).tools
            assert len(tools)==41 and all(t.annotations.readOnlyHint for t in tools)
            sid=(await call('fm_attach'))['session_id']
            try:
                if not receipt['city_enumeration_complete']:
                    cursor=None;count=0;cases=set();dates=set()
                    while True:
                        page=await call('fm_find_cities',session_id=sid,max_matches=100,cursor=cursor)
                        assert page['start_index']==count
                        for row in page['cities']:
                            source=cities[count]
                            verify_city(row,source,linked,population)
                            case=(row['population']['native_code'],row['language'] is None,row['local_region'] is None,
                                  row['altitude']['native_value']<-1000,row['altitude']['native_value']>8000,row['is_deleted'])
                            if case not in cases:
                                fresh=(await call('fm_get_city',session_id=sid,city_ref=row['city_ref']))['city']
                                verify_city(fresh,source,linked,population);cases.add(case)
                            count+=1
                        dates.add(page['save']['current_date']);cursor=page['next_cursor']
                        if count%4000==0:print(f'Cities: {count}/{len(cities)}',flush=True)
                        if not cursor:break
                    assert count==len(cities)
                    receipt.update(city_enumeration_complete=True,cities_checked=count,city_readback_cases=len(cases),city_save_dates=sorted(dates))
                    checkpoint(saved,receipt,identity)
                if 'filters' not in receipt:
                    filters=[]
                    selectors=[{'name':'Newcastle','nation':'England','is_deleted':False},
                               {'native_id':cities[0]['native_id']},{'nation_native_id':cities[0]['nation']['native_id']},
                               {'minimum_attraction':20},{'is_deleted':True},{'name':'FUSS'}]
                    def matches(row,args):
                        raw=bytes.fromhex(row['raw'])
                        nation_pointer=struct.unpack_from('<Q',raw,0x20)[0]
                        country=linked['nation'].get(nation_pointer)
                        return (('name' not in args or args['name'].casefold() in (row['name'] or '').casefold()) and
                            ('native_id' not in args or args['native_id']==row['native_id']) and
                            ('nation_native_id' not in args or country is not None and country['native_id']==args['nation_native_id']) and
                            ('nation' not in args or country is not None and any(args['nation'].casefold() in (country[k] or '').casefold() for k in ('short_name','abbreviation'))) and
                            ('minimum_attraction' not in args or struct.unpack_from('<b',raw,0x54)[0]>=args['minimum_attraction']) and
                            ('is_deleted' not in args or bool(raw[0x55]&1)==args['is_deleted']))
                    for number,args in enumerate(selectors):
                        cursor=None;ids=[];end=0;pages=0;empty=0
                        while True:
                            page=await call('fm_find_cities',session_id=sid,max_matches=100,cursor=cursor,**args)
                            assert page['start_index']==end
                            ids.extend(r['native_id'] for r in page['cities']);end=page['next_index'];pages+=1;empty+=page['count']==0
                            cursor=page['next_cursor']
                            if not cursor or number>0 and pages==3:break
                        assert ids==[r['native_id'] for r in cities[:end] if matches(r,args)],args
                        filters.append({'criteria':args,'matches':len(ids),'records_checked':end,'complete_scan':cursor is None,'empty_pages':empty})
                        print(f'City filter {args}: {len(ids)} matches through {end} records',flush=True)
                    receipt['filters']=filters;checkpoint(saved,receipt,identity)
                if not receipt['stadium_links_complete']:
                    cursor=None;count=0;cases=set();totals=Counter();dates=set()
                    while True:
                        page=await call('fm_find_stadiums',session_id=sid,max_matches=100,cursor=cursor)
                        assert page['start_index']==count
                        for row in page['stadiums']:
                            source=stadiums[count]
                            assert row['database_index']==source['database_index'] and row['native_id']==source['native_id']
                            for field in ('city','owner_club','nearby_stadium'):
                                expected=source[field];actual=row[field]
                                if expected is None:assert actual is None;continue
                                totals[field]+=1
                                assert actual['native_id']==expected['native_id'] and actual['database_index']==expected['database_index']
                                if field=='city':assert actual['name']==by_address[int(expected['address'],16)]['name']
                                elif field=='owner_club':assert all(actual[k]==expected[k] for k in ('name','short_name'))
                                else:assert actual['name']==stadium_names[expected['native_id']] and 'nearby_stadium' not in actual
                            case=(row['city'] is None,row['owner_club'] is None,row['nearby_stadium'] is None,
                                  row['nearby_stadium'] is not None and row['nearby_stadium']['native_id']==row['native_id'])
                            if case not in cases:
                                fresh=(await call('fm_get_stadium',session_id=sid,stadium_ref=row['stadium_ref']))['stadium']
                                for field,refkey,tool,resultkey in (('city','city_ref','fm_get_city','city'),('nearby_stadium','stadium_ref','fm_get_stadium','stadium')):
                                    if row[field]:
                                        assert fresh[field]['native_id']==row[field]['native_id']
                                        detail=(await call(tool,session_id=sid,**{refkey:fresh[field][refkey]}))[resultkey]
                                        assert detail['native_id']==row[field]['native_id']
                                if row['owner_club']:
                                    owner=await call('fm_get_club_squads',session_id=sid,club_ref=fresh['owner_club']['club_ref'])
                                    assert owner['club']['name']==row['owner_club']['name']
                                cases.add(case)
                            count+=1
                        dates.add(page['save']['current_date']);cursor=page['next_cursor']
                        if count%4000==0:print(f'Stadium links: {count}/{len(stadiums)}',flush=True)
                        if not cursor:break
                    assert count==len(stadiums) and dict(totals)==sources['stadium-links-survey.json']['linked_counts']
                    receipt.update(stadium_links_complete=True,stadiums_checked=count,linked_counts=dict(totals),
                                   stadium_link_readback_cases=len(cases),stadium_save_dates=sorted(dates))
                    checkpoint(saved,receipt,identity)
                coverage=await call('fm_get_fixture_coverage',session_id=sid)
                cursor=None
                while True:
                    page=await call('fm_find_fixtures',session_id=sid,year=coverage['main_year'],team_native_id=688,max_matches=1,cursor=cursor)
                    if page['fixtures']:break
                    cursor=page['next_cursor'];assert cursor,'No Newcastle fixture available for traversal check'
                fixture=page['fixtures'][0]
                venue=(await call('fm_get_stadium',session_id=sid,stadium_ref=fixture['stadium']['stadium_ref']))['stadium']
                city=(await call('fm_get_city',session_id=sid,city_ref=venue['city']['city_ref']))['city']
                assert city['native_id']==venue['city']['native_id']
                receipt['fixture_city_traversal']={'fixture_date':fixture['date'],'stadium':venue['name'],'city':city['name']}
            finally:await call('fm_detach')
    assert identity=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    receipt.update(verified=True,completed_at=datetime.now(timezone.utc).isoformat(),foreground_ui_used=False,native_execution=False)
    (ROOT/'evidence/live-cities-mcp.json').write_text(json.dumps({**receipt,'source_identity':identity},indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume',action='store_true')
    asyncio.run(verify(parser.parse_args().resume))
