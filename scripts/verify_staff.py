"""Validate staff search and club employment via the real stdio MCP transport."""
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
                found = await call('fm_find_staff', session_id=sid, name='Cesar', max_matches=100)
                assert found['complete_table_scan']
                assert found['staff_examined'] + found['other_person_records'] == found['total_person_records']
                coach = next(person for person in found['staff'] if person['record_kind'] == 'human_manager')
                fresh = (await call('fm_get_staff', session_id=sid, staff_ref=coach['staff_ref'], include_club=True))['staff']
                assert fresh['name'] == found['save']['coaches'][0]['name']
                assert fresh['contract']['club'] == found['save']['coaches'][0]['club']
                cursor, collected, scanned, unavailable = None, [], 0, 0
                for _ in range(30):
                    page = await call('fm_find_staff', session_id=sid, name='Cesar', max_matches=1, cursor=cursor)
                    collected.extend((p['name'], p['birth_date'], p['record_kind']) for p in page['staff'])
                    scanned += page['scanned_records']; unavailable += page['unavailable_name_records']
                    cursor = page['next_cursor']
                    if not cursor: break
                assert cursor is None and scanned == found['total_person_records']
                assert collected == [(p['name'], p['birth_date'], p['record_kind']) for p in found['staff']]
                assert unavailable == found['unavailable_name_records']
                limited = await call('fm_find_staff', session_id=sid, name='Cesar', record_budget=1)
                assert limited['scanned_records'] == 1 and limited['next_cursor']
                rest = await call('fm_find_staff', session_id=sid, name='Cesar', cursor=limited['next_cursor'], max_matches=100)
                assert limited['count'] + rest['count'] == found['count']
                salah = next(p for p in (await call('fm_find_staff', session_id=sid, name='Mohamed Salah'))['staff'] if p['birth_date'] == '1992-06-15')
                player = next(p for p in (await call('fm_find_save_players', session_id=sid, name='Mohamed Salah'))['players'] if p['birth_date'] == salah['birth_date'])
                staff_read = (await call('fm_get_staff', session_id=sid, staff_ref=salah['staff_ref'], include_club=True))['staff']
                player_read = (await call('fm_get_player', session_id=sid, player_ref=player['player_ref'], include_clubs=True))['player']
                assert staff_read['record_kind'] == 'player_staff' and staff_read['name'] == player_read['name']
                assert staff_read['contract']['club'] == player_read['clubs']['contract_club']
                roster = await call('fm_get_club_staff', session_id=sid)
                assert roster['count'] == len(roster['staff']) and roster['count'] > 80
                assert any(p['name'] == coach['name'] for p in roster['staff'])
                assert any(p['contract']['state'] == 'basic_contract' for p in roster['staff'])
                assert all(p['contract']['club'] == roster['club'] for p in roster['staff'])
                assert len({p['staff_ref'] for p in roster['staff']}) == roster['count']
                for person in roster['staff']:
                    fresh = (await call('fm_get_staff', session_id=sid, staff_ref=person['staff_ref'], include_club=True))['staff']
                    assert fresh == {k: v for k, v in person.items() if k != 'staff_ref'}
                clubs = await call('fm_find_clubs', session_id=sid, name='Liverpool', max_matches=100)
                checked = 0
                for club in clubs['clubs']:
                    if club['name'] != 'Liverpool' or club['short_name'] != 'Liverpool': continue
                    other = await call('fm_get_club_staff', session_id=sid, club_ref=club['club_ref'])
                    assert other['count'] == len(other['staff'])
                    assert all(p['contract']['club'] == other['club'] for p in other['staff'])
                    checked += 1
                assert checked == 2
                await call('fm_detach')
                assert (await client.call_tool('fm_get_staff', {'session_id': sid, 'staff_ref': coach['staff_ref']})).isError
                evidence['verified'] = True
                evidence['validation_scope'] = 'Shared native PERSON_DATA getters, RTTI, table membership, contract ownership and club/team backlinks; no foreground UI comparison.'
                print(f"Verified {found['staff_examined']} staff records, search pagination, player/staff parity, {roster['count']} managed club staff, other club lists and fresh readback.", flush=True)
    finally:
        output = root/'evidence/live-staff-mcp.json'
        output.write_text(json.dumps(evidence, indent=2)+'\n')
        print(output)


if __name__ == '__main__': asyncio.run(verify())
