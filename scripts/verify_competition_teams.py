"""Check public team assignments against an independently read team-table census."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    survey = json.loads((root/'evidence/team-assignment-survey.json').read_text())['rows']
    assert all(r['native_index'] == r['index'] for r in survey)
    receipt = {'verified': False, 'observed_at': datetime.now(timezone.utc).isoformat(), 'queries': []}
    started = time.monotonic()
    try:
        async with stdio_client(StdioServerParameters(command='/bin/sh', args=[str(root/'scripts/run_mcp.sh')])) as (read,write):
            async with ClientSession(read,write) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                assert 'fm_get_competition_teams' in {t.name for t in tools}
                assert all(t.annotations.readOnlyHint for t in tools)
                async def call(tool,**args):
                    result=await client.call_tool(tool,args)
                    assert not result.isError and result.structuredContent is not None,(tool,result.content)
                    return result.structuredContent
                receipt['server_version']=(await call('fm_status'))['server_version']
                sid=(await call('fm_attach'))['session_id']
                refs={}
                for native_id in (11,147032,14188247,157097,309682):
                    cursor=None
                    while True:
                        page=await call('fm_find_competitions',session_id=sid,native_id=native_id,cursor=cursor)
                        if page['count']:
                            assert page['count']==1
                            refs[native_id]=page['competitions'][0]['competition_ref'];break
                        cursor=page['next_cursor'];assert cursor
                roster_samples=[]
                for native_id,assignment,maximum,budget in (
                    (11,'current',7,200000),(11,'next',100,200000),
                    (147032,'current',100,200000),(14188247,'current',100,200000),
                    (157097,'next',100,200000),(309682,'secondary',100,200000),
                    (309682,'next_secondary',100,200000),(11,'secondary',100,20000)):
                    offset={'current':0,'next':1,'secondary':2,'next_secondary':3}[assignment]
                    expected=[]
                    for row in survey:
                        link=row['links'][offset]
                        if offset in (1,3) and link is None:link=row['links'][offset-1]
                        if link and link['native_id']==native_id and (assignment!='current' or row['has_club']):
                            expected.append(row)
                    cursor=None;actual=[];pages=0;next_index=0;empty=0
                    while True:
                        page=await call('fm_get_competition_teams',session_id=sid,competition_ref=refs[native_id],
                            assignment=assignment,max_matches=maximum,record_budget=budget,cursor=cursor)
                        assert page['total_team_records']==len(survey) and page['start_index']==next_index
                        assert page['scanned_records']==page['next_index']-next_index
                        next_index=page['next_index'];actual+=page['teams'];pages+=1;empty+=page['count']==0
                        cursor=page['next_cursor']
                        if cursor is None:
                            assert next_index==len(survey) and page['stop_reason']=='table_end';break
                    assert [r['database_index'] for r in actual]==[r['index'] for r in expected]
                    for row,source in zip(actual,expected):
                        assert row['native_id']==source['native_id']
                        assert row['random_id']==(None if source['native_id']==source['raw_random_id'] else source['raw_random_id'])
                        assert row['owner']['native_id']==source['club_id']
                        assert row['used_current_assignment_fallback']==(offset in (1,3) and source['links'][offset] is None)
                    if actual:
                        sample=next((r for r in actual if r['random_id'] is not None),actual[0])
                        roster=await call('fm_get_team_squad',session_id=sid,team_ref=sample['team_ref'])
                        assert roster['team']['native_id']==sample['native_id'] and roster['complete_native_roster']
                        query=await call('fm_query_team_players',session_id=sid,team_ref=sample['team_ref'],limit=5)
                        assert query['roster_count']==roster['count'] and query['team']==roster['team']
                        roster_samples.append({'team':roster['team'],'roster_count':roster['count']})
                    receipt['queries'].append({'native_id':native_id,'assignment':assignment,'count':len(actual),
                                               'pages':pages,'empty_pages':empty})
                    print(f'{native_id} {assignment}: {len(actual)} teams, {pages} pages',flush=True)
                for changes in ({'assignment':'invalid'},{'max_matches':True},{'record_budget':200001},{'cursor':'invented'}):
                    result=await client.call_tool('fm_get_competition_teams',{'session_id':sid,'competition_ref':refs[11],**changes})
                    assert result.isError
                await call('fm_detach')
                result=await client.call_tool('fm_get_competition_teams',{'session_id':sid,'competition_ref':refs[11]})
                assert result.isError
                receipt.update(verified=True,tool_count=len(tools),roster_samples=roster_samples,foreground_ui_used=False)
    finally:
        receipt['elapsed_seconds']=round(time.monotonic()-started,2)
        (root/'evidence/live-competition-teams-mcp.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='roster_samples'},indent=2))


if __name__=='__main__':asyncio.run(verify())
