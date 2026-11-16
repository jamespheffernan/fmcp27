"""Check current/contract clubs and loan status against the captured live UI."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    oracle = json.loads((root / 'tests/fixtures/player_club_oracle.json').read_text())
    evidence = {'observed_at': datetime.now(timezone.utc).isoformat(), 'transport': 'stdio', 'steps': []}
    params = StdioServerParameters(command='/bin/sh', args=[str(root / 'scripts/run_mcp.sh')])
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                async def call(name, args):
                    response = await client.call_tool(name, args)
                    evidence['steps'].append({'tool': name, 'error': response.isError, 'result': response.structuredContent})
                    if response.isError or response.structuredContent is None:
                        raise RuntimeError(str(response.content))
                    return response.structuredContent
                schemas = {tool.name: tool.inputSchema for tool in (await client.list_tools()).tools}
                for name in ('fm_get_player', 'fm_get_managed_squad'):
                    assert schemas[name]['properties']['include_clubs']['default'] is False
                session = (await call('fm_attach', {}))['session_id']
                squad = await call('fm_get_managed_squad', {'session_id': session, 'include_clubs': True})
                assert squad['save']['name'] == oracle['save_name']
                assert squad['count'] == oracle['managed_roster_count']
                found = {p['name']: p for p in squad['players']}
                loans = {p['name'] for p in squad['players'] if p['clubs']['on_loan']}
                assert loans == set(oracle['managed_roster_loans'])
                for player in squad['players']:
                    assert player['clubs']['contract_club']['name'] == oracle['contract_club']
                    if not player['clubs']['on_loan']:
                        assert player['clubs']['current_club']['name'] == oracle['contract_club']
                for expected in oracle['loans']:
                    name = expected['name']
                    if name not in found:
                        cursor = None
                        for _ in range(16):
                            page = await call('fm_find_players', {'session_id': session, 'name': name,
                                                                 'max_mib': 512, 'cursor': cursor})
                            exact = [p for p in page['players'] if p['name'] == name]
                            if exact:
                                assert len(exact) == 1
                                found[name] = exact[0]
                                break
                            cursor = page['next_cursor']
                            if not cursor: break
                        assert name in found, f'Bounded search did not find {name}'
                    fresh = await call('fm_get_player', {'session_id': session,
                                       'player_ref': found[name]['player_ref'], 'include_clubs': True})
                    assert fresh['player']['name'] == name
                    clubs = fresh['player']['clubs']
                    assert clubs['on_loan'] is True
                    assert clubs['contract_club']['name'] == oracle['contract_club']
                    assert clubs['current_club']['short_name'] == expected['current_club_short_name']
                    print(f"Verified {name}: {clubs['contract_club']['short_name']} → {clubs['current_club']['short_name']}", flush=True)
                await call('fm_detach', {})
                assert (await client.call_tool('fm_get_player', {'session_id': session,
                        'player_ref': next(iter(found.values()))['player_ref'], 'include_clubs': True})).isError
                evidence['verified'] = True
                print(f"Verified {squad['count']} roster club links and all four UI loan destinations.")
    finally:
        path = root / 'evidence/live-clubs-mcp.json'
        path.write_text(json.dumps(evidence, indent=2) + '\n')
        print(path)


if __name__ == '__main__':
    asyncio.run(verify())
