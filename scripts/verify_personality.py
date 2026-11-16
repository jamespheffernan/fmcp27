"""Verify live personality readback and selection queries through a fresh MCP process."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    evidence = {'observed_at': datetime.now(timezone.utc).isoformat(), 'steps': [], 'transport': 'stdio'}
    def check(ratings):
        assert set(ratings) == {'adaptability', 'ambition', 'controversy', 'loyalty', 'pressure', 'professionalism', 'sportsmanship', 'temperament'}
        assert all(type(value) is int and 0 <= value <= 20 for value in ratings.values())
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
                assert 'minimum_personality' in next(t for t in tools if t.name == 'fm_query_club_staff').inputSchema['properties']
                sid = (await call('fm_attach'))['session_id']
                squads = await call('fm_get_club_squads', session_id=sid)
                players, virtuals, query_cases = 0, 0, 0
                for team in squads['squads']:
                    full = await call('fm_get_team_squad', session_id=sid, team_ref=team['team_ref'], include_profile=True)
                    for row in full['players']:
                        check(row['profile']['personality'])
                        fresh = (await call('fm_get_player', session_id=sid, player_ref=row['player_ref'], include_profile=True))['player']
                        assert fresh['profile']['personality'] == row['profile']['personality']
                        if row.get('record_kind') == 'virtual':
                            virtuals += 1
                            assert fresh['profile']['personality']['controversy'] == 0
                            assert fresh['profile']['personality_native_defaults'] == ['controversy']
                        else: assert fresh['profile']['personality_native_defaults'] == []
                    players += full['count']
                    for minimum, limit, include_virtual in ((15, 3, False), (0, 100, True), (20, 1, True)):
                        result = await call('fm_query_team_players', session_id=sid, team_ref=team['team_ref'],
                            minimum_profile={'personality.professionalism': minimum}, sort_by='personality.ambition', limit=limit, include_virtual=include_virtual)
                        expected = [p for p in full['players'] if (include_virtual or p.get('record_kind') != 'virtual')
                                    and p['profile']['personality']['professionalism'] >= minimum]
                        expected.sort(key=lambda p: (-p['profile']['personality']['ambition'], p['display_name'].casefold(), p['birth_date']))
                        assert result['matched_count'] == len(expected) and result['unclassified_count'] == 0
                        assert result['truncated'] == (len(expected) > limit)
                        assert [(p['name'], p['profile']['personality']) for p in result['players']] == [(p['name'], p['profile']['personality']) for p in expected[:limit]]
                        query_cases += 1
                staff = await call('fm_get_club_staff', session_id=sid, include_attributes=True, include_job=True)
                for row in staff['staff']:
                    check(row['personality'])
                    assert row['personality']['adaptability'] == row['attributes']['adaptability']
                    fresh = (await call('fm_get_staff', session_id=sid, staff_ref=row['staff_ref'], include_attributes=True))['staff']
                    assert fresh['personality'] == row['personality']
                for minima, job, limit in (({'professionalism': 15}, None, 3), ({'ambition': 0}, 'coach', 100), ({'professionalism': 20, 'pressure': 15}, None, 1)):
                    result = await call('fm_query_club_staff', session_id=sid, minimum_personality=minima,
                        sort_by='personality.professionalism', job_contains=job, limit=limit)
                    expected = [p for p in staff['staff'] if all(p['personality'][k] >= v for k, v in minima.items())
                                and (job is None or job in p['contract']['job']['title'].casefold())]
                    expected.sort(key=lambda p: (-p['personality']['professionalism'], p['display_name'].casefold(), p['birth_date']))
                    assert result['matched_count'] == len(expected) and result['truncated'] == (len(expected) > limit)
                    assert [(p['name'], p['personality']) for p in result['staff']] == [(p['name'], p['personality']) for p in expected[:limit]]
                    query_cases += 1
                found = await call('fm_find_staff', session_id=sid, name='Mohamed Salah')
                salah = next(p for p in found['staff'] if p['birth_date'] == '1992-06-15')
                s = (await call('fm_get_staff', session_id=sid, staff_ref=salah['staff_ref'], include_attributes=True))['staff']
                found = await call('fm_find_save_players', session_id=sid, name='Mohamed Salah')
                salah = next(p for p in found['players'] if p['birth_date'] == '1992-06-15')
                p = (await call('fm_get_player', session_id=sid, player_ref=salah['player_ref'], include_profile=True))['player']
                assert s['personality'] == p['profile']['personality'] and s['record_kind'] == 'player_staff'
                for minima in ({'professionalism': True}, {'ambition': -1}, {'loyalty': 21}, {'unknown': 10}):
                    assert (await client.call_tool('fm_query_club_staff', {'session_id': sid, 'minimum_personality': minima})).isError
                await call('fm_detach')
                assert players == 79 and virtuals == 13 and staff['count'] == 93
                evidence.update(verified=True, player_entries=players, virtual_entries=virtuals, staff_entries=staff['count'],
                    staff_kinds=sorted({p['record_kind'] for p in staff['staff']}), combined_routes_verified=True,
                    query_cases=query_cases, scope='Native values, fresh readback, virtual default, filters/sort/counts/truncation; no UI comparison.')
                print(f'Verified {players} player entries, {virtuals} virtual players, {staff["count"]} staff and {query_cases} queries.')
    finally:
        path = root/'evidence/live-personality-mcp.json'
        path.write_text(json.dumps(evidence, indent=2)+'\n')
        print(path)


if __name__ == '__main__': asyncio.run(verify())
