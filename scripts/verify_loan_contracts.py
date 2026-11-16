"""Read back loan survey samples through the public stdio MCP; no UI interaction."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    survey = json.loads((root/'evidence/loan-contract-survey.json').read_text())
    assert not survey['errors'] and survey['complete_native_table_scan']
    result = {'verified': False, 'observed_at': datetime.now(timezone.utc).isoformat(), 'samples': []}
    try:
        async with stdio_client(StdioServerParameters(command='/bin/sh', args=[str(root/'scripts/run_mcp.sh')])) as (read,write):
            async with ClientSession(read,write) as client:
                await client.initialize()
                async def call(tool, **args):
                    r = await client.call_tool(tool,args)
                    if r.isError or r.structuredContent is None:
                        raise RuntimeError((tool,r.content))
                    return r.structuredContent
                tools = (await client.list_tools()).tools
                assert len(tools) == 28 and all(t.annotations.readOnlyHint for t in tools)
                assert (await call('fm_status'))['capabilities']['loan_contracts']
                sid = (await call('fm_attach'))['session_id']
                samples = {r['database_index']:r for r in survey['samples'].values()}
                samples.update({r['database_index']:r for r in survey['competition_conditions']})
                triggers, observed_clauses = set(), set()
                for sample in samples.values():
                    found = await call('fm_find_save_players',session_id=sid,name=sample['name'])
                    matches = [p for p in found['players'] if p['name']==sample['name'] and p['birth_date']==sample['birth_date']]
                    assert len(matches)==1,sample['name']
                    ref = matches[0]['player_ref']
                    one = await call('fm_get_loan_contract',session_id=sid,player_ref=ref)
                    two = await call('fm_get_loan_contract',session_id=sid,player_ref=ref)
                    assert one['loan_contract'] == two['loan_contract'] == sample['loan_contract'],sample['name']
                    assert one['save_identity']=='native_binding_rechecked'
                    assert one['loan_contract']['purchase']['trigger_satisfied'] is None
                    triggers.add(one['loan_contract']['purchase']['trigger'])
                    assert len(one['loan_contract']['clauses']) == 13
                    observed_clauses.update(name for name,present in one['loan_contract']['clauses'].items() if present)
                    result['samples'].append({'name':sample['name'],'birth_date':sample['birth_date'],'loan_contract':one['loan_contract']})
                assert triggers == {'optional_future_fee','mandatory_future_fee','after_matches','no_future_fee_specified','competition_condition'}
                expected_clauses = {name for sample in samples.values()
                                    for name,present in sample['loan_contract']['clauses'].items() if present}
                assert observed_clauses == expected_clauses
                # Cover each native managed-club team, including loans in youth/reserve vectors.
                squads = await call('fm_get_club_squads',session_id=sid)
                seen,loans,virtual_count,player_count = set(),[],0,0
                for team in squads['squads']:
                    rows = (await call('fm_get_team_squad',session_id=sid,team_ref=team['team_ref']))['players']
                    for row in rows:
                        key = (row['name'],row['birth_date'])
                        if key in seen:continue
                        seen.add(key)
                        if row.get('record_kind')=='virtual':
                            assert (await client.call_tool('fm_get_loan_contract',{'session_id':sid,'player_ref':row['player_ref']})).isError
                            virtual_count += 1
                            continue
                        response = await call('fm_get_loan_contract',session_id=sid,player_ref=row['player_ref'])
                        if response['loan_contract']['state']=='decoded':
                            loans.append(response)
                        else:assert response['loan_contract']['state']=='no_current_loan'
                        player_count += 1
                assert {p['player']['name'] for p in loans} == {'Trevan Sanusi','Leo Shahar','Mason Miley','Matthew Cox'}
                for row in loans:
                    old = (await call('fm_get_player',session_id=sid,player_ref=row['player_ref'],include_clubs=True))['player']['clubs']
                    assert old['contract_club']==row['loan_contract']['parent_club']
                    assert old['current_club']==row['loan_contract']['borrowing_club']
                for args in ({},{'player_ref':''},{'player_ref':True},{'player_ref':'expired'}):
                    assert (await client.call_tool('fm_get_loan_contract',{'session_id':sid,**args})).isError
                await call('fm_detach')
                assert (await client.call_tool('fm_get_loan_contract',{'session_id':sid,'player_ref':ref})).isError
                result.update(verified=True,tool_count=len(tools),sample_count=len(samples),triggers=sorted(triggers),
                    managed_club_players=player_count,virtual_rejections=virtual_count,newcastle_loans=loans,
                    observed_clause_names=sorted(observed_clauses),
                    competition_condition_count=len(survey['competition_conditions']),
                    surveyed_loans=survey['counts']['decoded'],surveyed_people=survey['seen'],
                    foreground_ui_used=False,scope='Fresh public identities, repeated loan readback, all observed purchase branches, combined players, missing-parent/different-current-club states, Newcastle squad coverage and invalid/detached references.')
                print(json.dumps({k:result[k] for k in ('verified','sample_count','triggers','managed_club_players','virtual_rejections','surveyed_loans')}))
    finally:
        path = root/'evidence/live-loan-contracts-mcp.json'
        path.write_text(json.dumps(result,indent=2)+'\n')
        print(path)


if __name__=='__main__':asyncio.run(verify())
