"""Verify contract bonus queries through fresh stdio MCP, using background reads."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    evidence = {'observed_at': datetime.now(timezone.utc).isoformat(), 'transport': 'stdio', 'verified': False, 'players': [], 'staff': []}
    try:
        async with stdio_client(StdioServerParameters(command='/bin/sh', args=[str(root/'scripts/run_mcp.sh')])) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                async def call(tool, **args):
                    response = await client.call_tool(tool, args)
                    if response.isError or response.structuredContent is None: raise RuntimeError(str(response.content))
                    return response.structuredContent
                tools = (await client.list_tools()).tools
                assert len(tools) == 28 and all(t.annotations.readOnlyHint for t in tools)
                for name in ('fm_get_player', 'fm_get_staff', 'fm_get_club_staff'):
                    tool = next(t for t in tools if t.name == name)
                    assert tool.inputSchema['properties']['include_contract_bonuses']['default'] is False
                sid = (await call('fm_attach'))['session_id']
                assert (await call('fm_status'))['capabilities']['contract_cash_bonuses']
                staff = await call('fm_get_club_staff', session_id=sid, include_contract_bonuses=True)
                for row in staff['staff']:
                    fresh = (await call('fm_get_staff', session_id=sid, staff_ref=row['staff_ref'], include_contract_bonuses=True))['staff']
                    assert fresh['contract'] == row['contract']
                    evidence['staff'].append({'name': row['name'], 'kind': row['record_kind'], 'bonuses': fresh['contract']['bonuses']})
                plain = await call('fm_get_club_staff', session_id=sid)
                assert all('bonuses' not in p['contract'] for p in plain['staff'])
                squads = await call('fm_get_club_squads', session_id=sid)
                seen, virtual_count = set(), 0
                for team in squads['squads']:
                    roster = await call('fm_get_team_squad', session_id=sid, team_ref=team['team_ref'])
                    for row in roster['players']:
                        if row.get('record_kind') == 'virtual':
                            rejected = await client.call_tool('fm_get_player', {'session_id': sid, 'player_ref': row['player_ref'], 'include_contract_bonuses': True})
                            assert rejected.isError
                            virtual_count += 1
                            continue
                        key = (row['name'], row['birth_date'])
                        if key in seen: continue
                        seen.add(key)
                        args = {'session_id': sid, 'player_ref': row['player_ref'], 'include_contract_bonuses': True}
                        fresh = (await call('fm_get_player', **args))['player']
                        again = (await call('fm_get_player', **args))['player']
                        assert fresh == again
                        bonus = fresh['contract_bonuses']
                        assert bonus['state'] in ('decoded', 'basic_contract_bonuses_unavailable', 'no_contract')
                        if bonus['state'] == 'decoded':
                            assert bonus['currency'] == 'GBP' and len(bonus['bonuses']) == 6
                            assert bonus['native_entry_count'] == bonus['other_entry_count'] + sum(b['matching_entry_count'] for b in bonus['bonuses'].values())
                            for value in bonus['bonuses'].values():
                                if value['state'] == 'not_present': assert value['amount'] is None and value['matching_entry_count'] == 0
                                else: assert value['amount'] >= 0 and value['matching_entry_count'] >= 1
                        evidence['players'].append({'name': row['name'], 'bonuses': bonus})
                # The same combined record must decode identically through both routes.
                found = await call('fm_find_staff', session_id=sid, name='Mohamed Salah')
                salah = next(p for p in found['staff'] if p['birth_date'] == '1992-06-15')
                as_staff = (await call('fm_get_staff', session_id=sid, staff_ref=salah['staff_ref'], include_contract_bonuses=True))['staff']
                found = await call('fm_find_save_players', session_id=sid, name='Mohamed Salah')
                salah = next(p for p in found['players'] if p['birth_date'] == '1992-06-15')
                as_player = (await call('fm_get_player', session_id=sid, player_ref=salah['player_ref'], include_contract_bonuses=True))['player']
                assert as_player['contract_bonuses'] == as_staff['contract']['bonuses']
                evidence['combined_record'] = {'name': as_player['name'], 'bonuses': as_player['contract_bonuses']}
                for tool, extra in [('fm_get_player', {'player_ref': 'invalid'}), ('fm_get_staff', {'staff_ref': 'invalid'}), ('fm_get_club_staff', {})]:
                    for bad in (1, 'true', None):
                        response = await client.call_tool(tool, {'session_id': sid, **extra, 'include_contract_bonuses': bad})
                        assert response.isError
                await call('fm_detach')
                stale = await client.call_tool('fm_get_player', {'session_id': sid, 'player_ref': salah['player_ref'], 'include_contract_bonuses': True})
                assert stale.isError
                evidence.update(verified=True, player_count=len(seen), staff_count=staff['count'], virtual_rejections=virtual_count,
                                tool_count=len(tools), states=dict(Counter(row['bonuses']['state'] for row in evidence['players']+evidence['staff'])),
                                scope='Stored bonuses, absent/basic states, repeated readback, three staff layouts, combined player/staff parity, strict arguments and expired session. No UI comparison or payment simulation.')
                print(json.dumps({k: evidence[k] for k in ('verified', 'player_count', 'staff_count', 'virtual_rejections', 'states')}, indent=2))
    finally:
        path = root/'evidence/live-contract-bonuses-mcp.json'
        path.write_text(json.dumps(evidence, indent=2)+'\n')
        print(path)


if __name__ == '__main__': asyncio.run(verify())
