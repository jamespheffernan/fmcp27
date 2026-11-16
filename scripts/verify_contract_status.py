"""Exercise current contract status through fresh stdio MCP, without UI actions."""
import asyncio
from collections import Counter
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
                tools = (await client.list_tools()).tools
                assert len(tools) == 28 and all(t.annotations.readOnlyHint for t in tools)
                sid = (await call('fm_attach'))['session_id']
                plain = await call('fm_get_club_staff', session_id=sid)
                full = await call('fm_get_club_staff', session_id=sid, include_contract_status=True)
                assert all('status' not in p['contract'] for p in plain['staff'])
                for person in full['staff']:
                    fresh = (await call('fm_get_staff', session_id=sid, staff_ref=person['staff_ref'], include_contract_status=True))['staff']
                    assert fresh == {k: v for k, v in person.items() if k != 'staff_ref'}
                squad = await call('fm_get_managed_squad', session_id=sid)
                for person in squad['players']:
                    ordinary = (await call('fm_get_player', session_id=sid, player_ref=person['player_ref']))['player']
                    assert 'contract_status' not in ordinary
                    fresh = (await call('fm_get_player', session_id=sid, player_ref=person['player_ref'], include_contract_status=True))['player']
                    assert fresh['name'] == person['name'] and fresh['contract_status']['state'] == 'decoded'
                found = await call('fm_find_staff', session_id=sid, name='Mohamed Salah')
                salah = next(p for p in found['staff'] if p['birth_date'] == '1992-06-15')
                combined = (await call('fm_get_staff', session_id=sid, staff_ref=salah['staff_ref'], include_contract_status=True))['staff']
                found = await call('fm_find_save_players', session_id=sid, name='Mohamed Salah')
                salah = next(p for p in found['players'] if p['birth_date'] == '1992-06-15')
                combined_player = (await call('fm_get_player', session_id=sid, player_ref=salah['player_ref'], include_contract_status=True))['player']
                assert combined_player['contract_status'] == combined['contract']['status']
                # Independently reread observed examples, including the unlabelled native code.
                samples = [('staff', 'Marco Giuliodori', 0), ('staff', 'Eric Assati', 2),
                           ('staff', 'Íñigo Lizarralde', 4), ('player', 'Berna Şengel', 3),
                           ('player', 'Adrian Rapińczuk', 10)]
                for kind, name, code in samples:
                    found = await call('fm_find_staff' if kind == 'staff' else 'fm_find_save_players', session_id=sid, name=name)
                    key = 'staff' if kind == 'staff' else 'players'
                    row = next(p for p in found[key] if p['name'] == name)
                    ref_key = 'staff_ref' if kind == 'staff' else 'player_ref'
                    fresh = await call('fm_get_staff' if kind == 'staff' else 'fm_get_player', session_id=sid,
                                       **{ref_key: row[ref_key], 'include_contract_status': True})
                    status = fresh['staff']['contract']['status'] if kind == 'staff' else fresh['player']['contract_status']
                    assert status['native_code'] == code
                    assert status['state'] == ('unmapped_native_status' if code == 10 else 'decoded')
                    if code == 10: assert status['title'] is None
                for tool, args in [('fm_get_club_staff', {}), ('fm_get_staff', {'staff_ref': 'invalid'}), ('fm_get_player', {'player_ref': 'invalid'})]:
                    for invalid in (1, 'true', None):
                        assert (await client.call_tool(tool, {'session_id': sid, **args, 'include_contract_status': invalid})).isError
                await call('fm_detach')
                evidence.update(verified=True, staff_count=full['count'], player_count=squad['count'], tool_count=len(tools),
                                staff_status_counts=dict(Counter(p['contract']['status']['state'] for p in full['staff'])),
                                scope='Fresh native status reads, all five labels, unmapped code 10, combined routes and strict arguments; no UI comparison.')
                print(f"Verified contract status for {full['count']} staff, {squad['count']} players, combined routes and all observed status codes.")
    finally:
        path = root/'evidence/live-contract-status-mcp.json'
        path.write_text(json.dumps(evidence, indent=2)+'\n')
        print(path)


if __name__ == '__main__': asyncio.run(verify())
