"""Verify health readback, injury links and selection queries over fresh stdio MCP."""
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
                catalog = await call('fm_get_database_catalog', session_id=sid)
                assert catalog['native_table_counts']['injuries'] == 136
                teams = await call('fm_get_club_squads', session_id=sid)
                total, virtuals, injuries, cases = 0, 0, [], 0
                for team in teams['squads']:
                    plain = await call('fm_get_team_squad', session_id=sid, team_ref=team['team_ref'])
                    assert all('health' not in p for p in plain['players'])
                    full = await call('fm_get_team_squad', session_id=sid, team_ref=team['team_ref'], include_health=True, include_profile=True, include_clubs=True)
                    for p in full['players']:
                        fresh = (await call('fm_get_player', session_id=sid, player_ref=p['player_ref'], include_health=True))['player']
                        assert fresh['health'] == p['health']
                        h = p['health']
                        assert h['injury_record_count'] == len(h['injuries'])
                        if p.get('record_kind') == 'virtual':
                            virtuals += 1
                            assert h['condition'] is None and h['match_sharpness'] is None and h['fatigue'] == 0
                            assert h['state'] == 'partial_virtual' and h['injury_record_count'] == 0
                        else:
                            assert h['state'] == 'stored_without_refresh'
                            assert 0 <= h['condition'] <= 10000 and 0 <= h['match_sharpness'] <= 10000
                            injuries.extend({'player': p['name'], **i} for i in h['injuries'])
                    total += full['count']
                    if team['is_managed_team']:
                        managed = await call('fm_get_managed_squad', session_id=sid, include_health=True)
                        assert [(p['name'], p['health']) for p in managed['players']] == [(p['name'], p['health']) for p in full['players']]
                    for mins, maxs, injury_filter, sort, include_virtual, limit in [
                        ({'condition': 9000, 'match_sharpness': 9000}, {'fatigue': 0}, 'without_records', 'health.condition', False, 3),
                        ({}, {}, 'with_records', 'health.match_sharpness', False, 100),
                        ({'condition': 0}, {}, 'any', 'health.condition', True, 100),
                        ({}, {'fatigue': 0}, 'without_records', 'health.fatigue', True, 2),
                        ({}, {}, 'any', 'health.match_sharpness', True, 1),
                    ]:
                        result = await call('fm_query_team_players', session_id=sid, team_ref=team['team_ref'],
                            minimum_health=mins, maximum_health=maxs, injury_records=injury_filter,
                            sort_by=sort, include_virtual=include_virtual, limit=limit, minimum_profile={'ability.current': 0}, loan_status='not_on_loan')
                        expected, unknown = [], []
                        for p in full['players']:
                            if not include_virtual and p.get('record_kind') == 'virtual': continue
                            if p['clubs']['on_loan']: continue
                            h = p['health']
                            if injury_filter != 'any' and bool(h['injury_record_count']) != (injury_filter == 'with_records'): continue
                            if any(h[k] is not None and h[k] < v for k, v in mins.items()): continue
                            if any(h[k] is not None and h[k] > v for k, v in maxs.items()): continue
                            missing = sorted(f'health.{k}' for k in set(mins) | set(maxs) | {sort[7:]} if h[k] is None)
                            if missing: unknown.append((p['name'], missing)); continue
                            expected.append(p)
                        expected.sort(key=lambda p: (-p['health'][sort[7:]], p['display_name'].casefold(), p['birth_date']))
                        assert result['matched_count'] == len(expected) and result['truncated'] == (len(expected) > limit)
                        assert [(p['name'], p['health']) for p in result['players']] == [(p['name'], p['health']) for p in expected[:limit]]
                        assert [(p['player']['name'], p['unavailable_fields']) for p in result['unclassified_players']] == unknown
                        cases += 1
                found = await call('fm_find_save_players', session_id=sid, name='Mohamed Salah')
                salah = next(p for p in found['players'] if p['birth_date'] == '1992-06-15')
                combined = (await call('fm_get_player', session_id=sid, player_ref=salah['player_ref'], include_health=True))['player']
                assert combined['record_kind'] == 'player_staff' and combined['health']['state'] == 'stored_without_refresh'
                for tool, args in [('fm_get_player', {'player_ref': 'invalid'}), ('fm_get_team_squad', {'team_ref': 'invalid'}), ('fm_get_managed_squad', {})]:
                    for value in (None, 1, 'true'):
                        assert (await client.call_tool(tool, {'session_id': sid, **args, 'include_health': value})).isError
                for kwargs in ({'minimum_health': {'condition': True}}, {'maximum_health': {'fatigue': -32769}}, {'injury_records': 'healthy'}):
                    assert (await client.call_tool('fm_query_team_players', {'session_id': sid, 'team_ref': team['team_ref'], **kwargs})).isError
                await call('fm_detach')
                assert total == 79 and virtuals == 13 and len(injuries) == 6
                evidence.update(verified=True, player_entries=total, virtual_entries=virtuals, injury_records=injuries,
                    query_cases=cases, injury_definitions=136, combined_route_verified=True,
                    scope='Stored values without native refresh, typed named injury records, fresh reads, filters/counts/unknowns/truncation; no UI or eligibility verification.')
                print(f'Verified {total} player entries, {virtuals} virtual states, {len(injuries)} injury records and {cases} queries.')
    finally:
        path = root/'evidence/live-player-health-mcp.json'
        path.write_text(json.dumps(evidence, indent=2)+'\n')
        print(path)


if __name__ == '__main__': asyncio.run(verify())
