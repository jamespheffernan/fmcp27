"""Exercise club-wide native rosters, virtual profiles and a practical attribute query."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    oracle = json.loads((root / 'tests/fixtures/virtual_profile_oracles.json').read_text())
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
                session = (await call('fm_attach', {}))['session_id']
                listing = await call('fm_get_club_squads', {'session_id': session})
                squads = {}
                for team in listing['squads']:
                    roster = await call('fm_get_team_squad', {'session_id': session, 'team_ref': team['team_ref']})
                    assert roster['count'] == team['count'] == len(roster['players'])
                    assert roster['complete_native_roster'] is True
                    if team['label'] in oracle['squad_counts']:
                        assert roster['count'] == oracle['squad_counts'][team['label']]
                    squads[team['label']] = roster
                    print(f"Verified {team['label']}: {roster['count']} records, {roster['virtual_player_count']} virtual", flush=True)
                youth = squads['U18']
                virtual_names = {p['name'] for p in youth['players'] if p.get('record_kind') == 'virtual'}
                assert virtual_names == set(oracle['u18_visible_virtual_names'])
                for expected in oracle['players']:
                    player = next(p for p in youth['players'] if p['name'] == expected['name'])
                    fresh = await call('fm_get_player', {'session_id': session, 'player_ref': player['player_ref'], 'include_clubs': True})
                    actual = fresh['player']
                    assert actual['name'] == expected['name']
                    assert actual['birth_date'] == expected['birth_date']
                    for field, value in expected['attributes'].items():
                        assert actual['attributes'][field] == value, (actual['name'], field)
                    assert actual['clubs']['contract_state'] == 'virtual_uncontracted'
                    assert actual['clubs']['contract_club'] is None
                    print(f"Verified UI profile {actual['name']}: {len(expected['attributes'])} attributes", flush=True)
                senior = squads['Senior']
                query = await call('fm_query_team_players', {'session_id': session, 'team_ref': senior['team_ref'],
                                   'minimum_attributes': {'passing': 15, 'vision': 15}, 'sort_by': 'decisions', 'limit': 5})
                expected = [p for p in senior['players'] if p['attributes']['passing'] >= 15 and p['attributes']['vision'] >= 15]
                expected.sort(key=lambda p: (-p['attributes']['decisions'], p['display_name'].casefold(), p['birth_date']))
                assert [p['name'] for p in query['players']] == [p['name'] for p in expected[:5]]
                assert query['matched_count'] == len(expected)
                evidence['query_names'] = [p['display_name'] for p in query['players']]
                print('Passing/vision shortlist:', ', '.join(evidence['query_names']), flush=True)
                await call('fm_detach', {})
                assert (await client.call_tool('fm_get_team_squad', {'session_id': session, 'team_ref': senior['team_ref']})).isError
                evidence['verified'] = True
                evidence['native_roster_entries'] = sum(s['count'] for s in squads.values())
    finally:
        path = root / 'evidence/live-squads-mcp.json'
        path.write_text(json.dumps(evidence, indent=2) + '\n')
        print(path)


if __name__ == '__main__':
    asyncio.run(verify())
