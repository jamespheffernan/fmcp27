"""Compare public fixture queries with independent resident-bucket census evidence."""
import argparse
import asyncio
from datetime import date, timedelta, datetime, timezone
import json
from pathlib import Path
import struct
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


def native_clock(packed):
    """Independent arithmetic transcription of 0x42EF454..0x42EF514."""
    code = (packed & 0xFFFF) >> 9
    if packed >> 16 == 1900 and packed & 511 == 1:
        clock, state = None, 'unset_date'
    elif code == 0:
        clock, state = None, 'no_time_code'
    elif code == 127:
        milliseconds = 0x3A5D680 + 0x325AA0
        clock, state = f'{milliseconds//3600000:02d}:{milliseconds//60000%60:02d}', 'decoded'
    elif code > 72:
        clock, state = None, 'unmapped_time_code'
    else:
        w11 = code-1
        w13 = w11 + ((w11 >> 13) & 3)
        w14 = ((w13 >> 2) & 255)*100
        w13 = w11 - (w13 & 252)
        w13 = (w14 + w13*15 + 600) >> 2
        hour = (w13*0x147B) >> 17
        w16 = ((w11 >> 2) & 63)*100 - (w11 & 3)
        hhmm = w16 + ((w11 & 3) << 4) + 600
        minute = (hhmm - ((hhmm*0x147B) >> 19)*100) & 65535
        clock, state = f'{hour:02d}:{minute:02d}', 'decoded'
    return {'time': clock, 'state': state, 'native_code': code, 'timezone': None}


def expected(year):
    census = json.loads((ROOT/f'evidence/resident-fixtures-{year}.json').read_text())
    rows = []
    for group in census['groups']:
        for slot, record in enumerate(group['records']):
            raw = bytes.fromhex(record['raw'])
            row = {'day': record['day'], 'group': group['index'], 'slot': slot,
                   'season_code': struct.unpack_from('<H', raw, 0x30)[0],
                   'stage_index': struct.unpack_from('<b', raw, 0x38)[0],
                   'kickoff_time': native_clock(struct.unpack_from('<I', raw, 0x4C)[0]),
                   'date': (date(year, 1, 1)+timedelta(days=record['day']-1)).isoformat(),
                   'home': record['team_8'][1] if record['team_8'] else None,
                   'away': record['team_10'][1] if record['team_10'] else None,
                   'kind': 'result_record' if record['vtable']=='0x5672e00' else 'fixture_record',
                   'competition': record['competition'][1] if record['competition'] else None, 'scores': None}
            if row['kind']=='result_record':
                scores = {}
                for i,label in enumerate(('normal_time','extra_time','penalties','aggregate')):
                    scores[label] = {side: None if raw[offset+i]==255 else raw[offset+i]
                                     for side,offset in (('home',0x64),('away',0x69))}
                scores['final_score'] = {side: scores['extra_time'][side] if scores['extra_time'][side] is not None
                                        else scores['normal_time'][side] for side in ('home','away')}
                row['scores']=scores
            rows.append(row)
    return census, sorted(rows,key=lambda r:(r['day'],r['group'],r['slot']))


async def verify(years=(2030,2025)):
    params=StdioServerParameters(command=sys.executable,args=['-m','fm_live_mcp.server'],cwd=str(ROOT))
    receipt={'verified':False,'observed_at':datetime.now(timezone.utc).isoformat(),'years':[],'readbacks':[]}
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as client:
            await client.initialize()
            async def call(name,**kwargs):
                result=await client.call_tool(name,kwargs)
                assert not result.isError,(name,result.content)
                return result.structuredContent
            receipt['server_version']=(await call('fm_status'))['server_version']
            sid=(await call('fm_attach'))['session_id']
            try:
                coverage=await call('fm_get_fixture_coverage',session_id=sid)
                receipt['coverage']=coverage['years']
                samples=set()
                for year in years:
                    census,baseline=expected(year)
                    found=[];cursor=None;pages=0;empty=0
                    while True:
                        result=await call('fm_find_fixtures',session_id=sid,year=year,max_matches=100,cursor=cursor)
                        assert result['coverage']['loaded_group_count']==sum(g['loaded'] for g in census['groups'])
                        for row in result['fixtures']:
                            e=baseline[len(found)]
                            assert row['date']==e['date'] and row['record_kind']==e['kind']
                            for field,key in (('home_team','home'),('away_team','away')):
                                assert (row[field]['native_id'] if row[field] else None)==e[key]
                            assert row['scores']==e['scores']
                            assert row['kickoff_time']==e['kickoff_time']
                            assert (row['competition']['native_id'] if row['competition'] else None)==e['competition']
                            found.append(row)
                            cases=['base'] if row['scores'] is None else [k for k in ('normal_time','extra_time','penalties','aggregate')
                                if row['scores'][k]['home'] is not None]
                            new=set(cases)-samples
                            if new:
                                fresh=(await call('fm_get_fixture',session_id=sid,fixture_ref=row['fixture_ref']))['fixture']
                                assert fresh['scores']==row['scores'] and fresh['date']==row['date']
                                assert fresh['kickoff_time']==row['kickoff_time']
                                samples.update(new);receipt['readbacks'].append({'year':year,'date':row['date'],'categories':sorted(new)})
                            if 'roster' not in samples and row['home_team'] and row['competition']:
                                team=row['home_team'];comp=row['competition']
                                roster=await call('fm_get_team_squad',session_id=sid,team_ref=team['team_ref'])
                                assert roster['team']['native_id']==team['native_id']
                                linked=await call('fm_get_competition',session_id=sid,competition_ref=comp['competition_ref'])
                                assert linked['competition']['native_id']==comp['native_id']
                                samples.add('roster');receipt['roster_count']=roster['count']
                        pages+=1;empty+=not result['fixtures'];cursor=result['next_cursor']
                        if pages%25==0:print(f'{year}: {len(found)}/{len(baseline)}, {pages} pages',flush=True)
                        if not cursor:break
                    assert len(found)==len(baseline)
                    receipt['years'].append({'year':year,'records':len(found),'pages':pages,'empty_pages':empty,
                                             'kickoff_times_compared':len(found),
                                             'kickoff_codes':sorted({r['kickoff_time']['native_code'] for r in found}),
                                             'loaded_groups':result['coverage']['loaded_group_count'],
                                             'unavailable_groups':len(result['coverage']['unavailable_group_indices'])})
                    if year==2030:
                        for filters in ({'team_native_id':688},{'competition_native_id':11},
                                        {'team_native_id':688,'date_from':'2030-09-01','date_to':'2030-09-30'}):
                            wanted=[r for r in found if ('team_native_id' not in filters or any(
                                r[k] and r[k]['native_id']==688 for k in ('home_team','away_team')))
                                and ('competition_native_id' not in filters or r['competition'] and r['competition']['native_id']==11)
                                and ('date_from' not in filters or filters['date_from']<=r['date']<=filters['date_to'])]
                            filtered=[];cursor=None
                            while True:
                                page=await call('fm_find_fixtures',session_id=sid,year=year,max_matches=100,cursor=cursor,**filters)
                                filtered.extend(page['fixtures']);cursor=page['next_cursor']
                                if not cursor:break
                            key=lambda r:(r['date'],r['home_team']['native_id'] if r['home_team'] else None,
                                          r['away_team']['native_id'] if r['away_team'] else None,r['scores'])
                            assert list(map(key,filtered))==list(map(key,wanted))
                            receipt.setdefault('filters',[]).append({'criteria':filters,'records':len(filtered)})
                invalid=await client.call_tool('fm_get_fixture',{'session_id':sid,'fixture_ref':'invalid'})
                assert invalid.isError
            finally:await call('fm_detach')
            detached=await client.call_tool('fm_get_fixture',{'session_id':sid,'fixture_ref':row['fixture_ref']})
            assert detached.isError
    receipt.update(verified=True,foreground_ui_used=False,native_execution=False)
    (ROOT/('evidence/live-fixtures-mcp.json' if tuple(years)==(2030,2025) else 'evidence/live-fixtures-'+ '-'.join(map(str,years))+'-mcp.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year',type=int,action='append')
    args=parser.parse_args()
    asyncio.run(verify(args.year or (2030,2025)))
