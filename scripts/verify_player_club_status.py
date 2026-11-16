"""Verify repaired player club reads and loan-filter partitions over public stdio."""
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path

from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root=Path(__file__).resolve().parents[1]
    census=json.loads((root/'evidence/player-club-survey.json').read_text())
    before=json.loads((root/'evidence/player-club-regressions-before.json').read_text())
    assert census['complete_native_table_scan'] and not census['errors']
    result={'verified':False,'observed_at':datetime.now(timezone.utc).isoformat(),'samples':[],'teams':[]}
    try:
        async with stdio_client(StdioServerParameters(command='/bin/sh',args=[str(root/'scripts/run_mcp.sh')])) as (read,write):
            async with ClientSession(read,write) as client:
                await client.initialize()
                async def call(tool,**args):
                    r=await client.call_tool(tool,args)
                    assert not r.isError and r.structuredContent is not None,(tool,r.content)
                    return r.structuredContent
                sid=(await call('fm_attach'))['session_id']
                samples={(r['name'],r['birth_date']):r for r in census['samples'].values()}
                samples.update({(r['name'],r['birth_date']):r for r in before})
                reasons=set()
                for (name,dob),expected in samples.items():
                    rows=(await call('fm_find_save_players',session_id=sid,name=name))['players']
                    row=next(p for p in rows if p['name']==name and p['birth_date']==dob)
                    ref=row['player_ref']
                    plain=(await call('fm_get_player',session_id=sid,player_ref=ref))['player']
                    assert 'clubs' not in plain
                    fresh=await call('fm_get_player',session_id=sid,player_ref=ref,include_clubs=True)
                    again=await call('fm_get_player',session_id=sid,player_ref=ref,include_clubs=True)
                    clubs=fresh['player']['clubs']
                    assert clubs==again['player']['clubs'] and fresh['save_identity']=='native_binding_rechecked'
                    if 'database_index' in expected:assert clubs==expected['clubs']
                    if name=='Stefan Kahlisch':
                        assert expected['clubs']['on_loan'] and not clubs['on_loan']
                        assert clubs['loan_status_reason']=='suppressed_by_affiliation_kind_18'
                    reasons.add(clubs['loan_status_reason'])
                    result['samples'].append({'name':name,'birth_date':dob,'clubs':clubs,'previous_error':expected.get('error')})
                assert reasons=={'no_auxiliary_holder','empty_current_slot','loan_contract','trial_contract','suppressed_by_affiliation_kind_18'}
                listings=[await call('fm_get_club_squads',session_id=sid)]
                clubs=(await call('fm_find_clubs',session_id=sid,name='FC Twente/Heracles Academie',max_matches=100))['clubs']
                academy=next(c for c in clubs if c['name']=='FC Twente/Heracles Academie')
                listings.append(await call('fm_get_club_squads',session_id=sid,club_ref=academy['club_ref']))
                for listing in listings:
                    for team in listing['squads']:
                        roster=await call('fm_get_team_squad',session_id=sid,team_ref=team['team_ref'],include_clubs=True)
                        regular=[p for p in roster['players'] if p.get('record_kind')!='virtual']
                        expected={(p['name'],p['birth_date']):p['clubs']['on_loan'] for p in regular}
                        for selection in ('any','on_loan','not_on_loan'):
                            r=await call('fm_query_team_players',session_id=sid,team_ref=team['team_ref'],loan_status=selection,limit=100)
                            wanted={key for key,flag in expected.items() if selection=='any' or flag==(selection=='on_loan')}
                            assert r['matched_count']==len(wanted)
                            assert not r['unclassified_players']
                            if not r['truncated']:assert {(p['name'],p['birth_date']) for p in r['players']}==wanted
                        result['teams'].append({'label':roster['label'],'club':roster['club'],'regular_players':len(regular),
                            'on_loan':sum(expected.values()),'suppressed':sum(p['clubs'].get('loan_status_reason')=='suppressed_by_affiliation_kind_18' for p in regular)})
                await call('fm_detach')
                assert (await client.call_tool('fm_get_player',{'session_id':sid,'player_ref':ref,'include_clubs':True})).isError
                result.update(verified=True,sample_count=len(samples),native_status_reasons=sorted(reasons),
                    census_counts=census['counts'],foreground_ui_used=False,
                    scope='Fresh identities, repeated readback of census/previous-failure examples, default preservation and native-loan filter partitions across Newcastle and an affiliated academy. No current eligibility or new UI comparison.')
                print(json.dumps({k:result[k] for k in ('verified','sample_count','native_status_reasons','teams')}))
    finally:
        (root/'evidence/live-player-club-status-mcp.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':asyncio.run(verify())
