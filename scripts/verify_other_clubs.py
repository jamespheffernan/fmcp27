"""Exercise club discovery, other rosters and shared player/staff records via MCP."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    evidence = {'observed_at': datetime.now(timezone.utc).isoformat(), 'transport': 'stdio', 'steps': []}
    try:
        async with stdio_client(StdioServerParameters(command='/bin/sh', args=[str(root/'scripts/run_mcp.sh')])) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                async def call(tool, **args):
                    response = await client.call_tool(tool, args)
                    evidence['steps'].append({'tool': tool, 'error': response.isError, 'result': response.structuredContent})
                    if response.isError or response.structuredContent is None: raise RuntimeError(str(response.content))
                    return response.structuredContent
                sid = (await call('fm_attach'))['session_id']
                found = await call('fm_find_clubs', session_id=sid, name='Liverpool', max_matches=100)
                assert found['complete_table_scan'] and found['clubs_examined'] + found['other_club_records'] == found['total_club_records']
                cursor, collected, scanned = None, [], 0
                for _ in range(20):
                    page = await call('fm_find_clubs', session_id=sid, name='Liverpool', max_matches=1, cursor=cursor)
                    collected.extend((c['name'],c['short_name']) for c in page['clubs'])
                    scanned += page['scanned_records'];cursor = page['next_cursor']
                    if not cursor: break
                assert cursor is None and scanned == found['total_club_records']
                assert collected == [(c['name'],c['short_name']) for c in found['clubs']]
                salah = next(p for p in (await call('fm_find_save_players', session_id=sid, name='Mohamed Salah'))['players'] if p['birth_date']=='1992-06-15')
                assert salah['record_kind']=='player_staff'
                fresh = (await call('fm_get_player', session_id=sid, player_ref=salah['player_ref'], include_clubs=True))['player']
                assert fresh['clubs']['current_club']['name']=='Liverpool'
                rosters=[]
                for club in found['clubs']:
                    if club['name']!=club['short_name'] or club['short_name']!='Liverpool':continue
                    listing = await call('fm_get_club_squads', session_id=sid, club_ref=club['club_ref'])
                    senior=next(t for t in listing['squads'] if t['native_type']==0)
                    roster=await call('fm_get_team_squad', session_id=sid, team_ref=senior['team_ref'], include_clubs=True)
                    assert roster['count']==senior['count']==len(roster['players'])
                    rosters.append(roster)
                matching=[p for r in rosters for p in r['players'] if p['name']==salah['name'] and p['birth_date']==salah['birth_date']]
                assert len(matching)==1 and matching[0]['attributes']==salah['attributes']
                assert matching[0]['clubs']==fresh['clubs']
                ceri=next(p for r in rosters for p in r['players'] if p['name']=='Ceri Holland')
                assert ceri['record_kind']=='player_staff'
                global_ceri=await call('fm_find_save_players', session_id=sid, name='Ceri Holland')
                assert any(p['attributes']==ceri['attributes'] and p['birth_date']==ceri['birth_date'] for p in global_ceri['players'])
                newcastle=next(c for c in (await call('fm_find_clubs', session_id=sid, name='Newcastle'))['clubs'] if c['name']=='Newcastle United')
                managed=await call('fm_get_club_squads', session_id=sid)
                selected=await call('fm_get_club_squads', session_id=sid, club_ref=newcastle['club_ref'])
                assert [(t['native_type'],t['count']) for t in managed['squads']]==[(t['native_type'],t['count']) for t in selected['squads']]
                await call('fm_detach')
                assert (await client.call_tool('fm_get_club_squads', {'session_id':sid,'club_ref':newcastle['club_ref']})).isError
                evidence['verified']=True
                evidence['validation_scope']='Player/staff layout validated through shared native getters, runtime types and independent table/roster/contract paths; no new UI profile comparison.'
                print('Verified club search pagination, both Liverpool senior rosters, Salah/Holland global links, Newcastle parity and detach.',flush=True)
    finally:
        output=root/'evidence/live-other-clubs-mcp.json'
        output.write_text(json.dumps(evidence,indent=2)+'\n');print(output)


if __name__=='__main__':asyncio.run(verify())
