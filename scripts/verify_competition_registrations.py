"""Verify all observed registration lists through a fresh public MCP connection."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root=Path(__file__).resolve().parents[1]
    census=json.loads((root/'evidence/competition-registration-survey.json').read_text())
    assert census['verified']
    assert json.loads((root/'evidence/competition-registration-layout-verification.json').read_text())['verified']
    receipt={'verified':False,'observed_at':datetime.now(timezone.utc).isoformat(),'queries':[]}
    started=time.monotonic()
    try:
        async with stdio_client(StdioServerParameters(command='/bin/sh',args=[str(root/'scripts/run_mcp.sh')])) as (read,write):
            async with ClientSession(read,write) as client:
                await client.initialize();tools=(await client.list_tools()).tools
                assert 'fm_get_competition_registrations' in {t.name for t in tools}
                assert all(t.annotations.readOnlyHint for t in tools)
                async def call(tool,**args):
                    result=await client.call_tool(tool,args)
                    assert not result.isError and result.structuredContent is not None,(tool,result.content)
                    return result.structuredContent
                receipt['server_version']=(await call('fm_status'))['server_version']
                sid=(await call('fm_attach'))['session_id']
                refs={};cursor=None
                while True:
                    page=await call('fm_find_competitions',session_id=sid,max_matches=100,cursor=cursor)
                    refs.update({r['native_id']:r['competition_ref'] for r in page['competitions']})
                    cursor=page['next_cursor']
                    if cursor is None:break
                assert len(refs)==census['competition_count']
                nonempty=[r for r in census['competitions'] if r['total_slots']]
                empty=[next(r for r in census['competitions'] if r['competition_id']==11),
                       next(r for r in reversed(census['competitions']) if not r['total_slots'])]
                roster_samples=[];sampled_kinds=set();total=0
                async def scan(source,year=None):
                    cursor=None;rows=[];next_index=0;pages=empty_pages=nulls=0
                    while True:
                        page=await call('fm_get_competition_registrations',session_id=sid,
                            competition_ref=refs[source['competition_id']],year=year,
                            max_matches=5,record_budget=7,cursor=cursor)
                        assert page['start_index']==next_index
                        assert page['scanned_slots']==page['next_index']-next_index
                        assert page['total_registration_slots']==source['total_slots']
                        next_index=page['next_index'];rows.extend(page['registrations'])
                        pages+=1;empty_pages+=not page['count'];nulls+=page['null_record_slots']
                        cursor=page['next_cursor']
                        if cursor is None:
                            assert next_index==source['total_slots'] and page['stop_reason']=='list_end';break
                    expected=[r for r in source['registrations'] if year is None or r['year']==year]
                    normalized=[{**r,'team':{k:v for k,v in r['team'].items() if k!='team_ref'} if r['team'] else None} for r in rows]
                    assert normalized==expected and nulls==source['null_slots']
                    receipt['queries'].append({'competition_id':source['competition_id'],'year':year,
                        'count':len(rows),'pages':pages,'empty_pages':empty_pages})
                    print(f'{source["competition_id"]}, year={year}: {len(rows)} registrations / {pages} pages',flush=True)
                    return rows
                for source in nonempty+empty:
                    rows=await scan(source);total+=len(rows)
                    for row in rows:
                        if not row['team']:continue
                        kind=row['team']['kind']
                        if kind in sampled_kinds:continue
                        sampled_kinds.add(kind)
                        roster=await call('fm_get_team_squad',session_id=sid,team_ref=row['team']['team_ref'])
                        query=await call('fm_query_team_players',session_id=sid,team_ref=row['team']['team_ref'],limit=5)
                        assert roster['team']['native_id']==row['team']['native_id']
                        assert query['roster_count']==roster['count'] and query['team']==roster['team']
                        roster_samples.append({'team':roster['team'],'roster_count':roster['count']})
                assert total==census['record_count'] and sampled_kinds=={'team','national_team'}
                dated=next(r for r in nonempty if any(x['year'] is not None for x in r['registrations']))
                for year in (2025,2030):await scan(dated,year)
                for changes in ({'year':0},{'year':65535},{'year':True},{'max_matches':True},{'cursor':'invented'}):
                    result=await client.call_tool('fm_get_competition_registrations',
                        {'session_id':sid,'competition_ref':refs[11],**changes})
                    assert result.isError
                await call('fm_detach')
                result=await client.call_tool('fm_get_competition_registrations',{'session_id':sid,'competition_ref':refs[11]})
                assert result.isError
                receipt.update(verified=True,tool_count=len(tools),registration_count=total,
                    nonempty_competitions=len(nonempty),roster_samples=roster_samples,foreground_ui_used=False)
    finally:
        receipt['elapsed_seconds']=round(time.monotonic()-started,2)
        (root/'evidence/live-competition-registrations-mcp.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='roster_samples'},indent=2))


if __name__=='__main__':asyncio.run(verify())
