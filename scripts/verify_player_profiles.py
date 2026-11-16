"""Verify fresh player profiles and squad selection queries over stdio; no UI actions."""
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
                tools = (await client.list_tools()).tools
                assert len(tools) == 28 and all(t.annotations.readOnlyHint for t in tools)
                sid = (await call('fm_attach'))['session_id']
                managed = await call('fm_get_managed_squad', session_id=sid, include_profile=True)
                assert managed['count'] == 28
                squads = await call('fm_get_club_squads', session_id=sid)
                counts, virtuals, summaries = [], 0, []
                for team in squads['squads']:
                    plain = await call('fm_get_team_squad', session_id=sid, team_ref=team['team_ref'])
                    assert all('profile' not in p for p in plain['players'])
                    full = await call('fm_get_team_squad', session_id=sid, team_ref=team['team_ref'], include_profile=True, include_clubs=True)
                    counts.append(full['count']); virtuals += full['virtual_player_count']
                    assert full['count'] == team['count']
                    for row in full['players']:
                        fresh = (await call('fm_get_player', session_id=sid, player_ref=row['player_ref'], include_profile=True))['player']
                        assert fresh['profile'] == row['profile'] and fresh['attributes'] == row['attributes']
                        assert len(row['profile']['positions']) == 14 and len(row['profile']['goalkeeping']) == 11
                    if team['is_managed_team']:
                        assert [(p['name'], p['profile']) for p in full['players']] == [(p['name'], p['profile']) for p in managed['players']]
                    def value(row, path):
                        group, field = path.split('.')
                        return row['profile'][group][field]
                    for minima, sort, limit, include_virtual, loan in [
                        ({'positions.goalkeeper': 15, 'goalkeeping.reflexes': 14}, 'ability.current', 2, False, 'not_on_loan'),
                        ({'ability.potential': 150}, 'ability.potential', 5, False, 'any'),
                        ({'positions.midfielder_central': 15, 'feet.left': 10}, 'hidden_attributes.consistency', 3, True, 'any'),
                        ({'ability.current': 0}, 'ability.current', 100, True, 'any'),
                    ]:
                        result = await call('fm_query_team_players', session_id=sid, team_ref=team['team_ref'], minimum_profile=minima,
                                            sort_by=sort, limit=limit, include_virtual=include_virtual, loan_status=loan)
                        expected, unknown = [], []
                        for row in full['players']:
                            if not include_virtual and row.get('record_kind') == 'virtual': continue
                            if loan != 'any' and row['clubs']['on_loan'] != (loan == 'on_loan'): continue
                            if any(value(row, k) is None for k in set(minima) | {sort}): unknown.append(row); continue
                            if all(value(row, k) >= minimum for k, minimum in minima.items()): expected.append(row)
                        expected.sort(key=lambda p: (-value(p, sort), p['display_name'].casefold(), p['birth_date']))
                        assert result['matched_count'] == len(expected) and result['unclassified_count'] == len(unknown)
                        assert result['truncated'] == (len(expected) > limit)
                        assert [(p['name'], p['profile']) for p in result['players']] == [(p['name'], p['profile']) for p in expected[:limit]]
                        summaries.append({'squad': full['label'], 'minima': minima, 'sort': sort, 'matches': len(expected)})
                assert counts == [28, 23, 24, 4] and virtuals == 13
                found = await call('fm_find_save_players', session_id=sid, name='Mohamed Salah')
                salah = next(p for p in found['players'] if p['birth_date'] == '1992-06-15')
                combined = (await call('fm_get_player', session_id=sid, player_ref=salah['player_ref'], include_profile=True))['player']
                assert combined['record_kind'] == 'player_staff' and combined['profile']['ability']['potential'] >= 0
                for tool, args in [('fm_get_player', {'player_ref': 'bad'}), ('fm_get_team_squad', {'team_ref': 'bad'}), ('fm_get_managed_squad', {})]:
                    for invalid in (1, 'true', None):
                        assert (await client.call_tool(tool, {'session_id': sid, **args, 'include_profile': invalid})).isError
                for minima in ({'goalkeeping.reflexes': 21}, {'ability.current': True}, {'ability.current': 201}, {'unknown': 1}):
                    assert (await client.call_tool('fm_query_team_players', {'session_id': sid, 'team_ref': team['team_ref'], 'minimum_profile': minima})).isError
                await call('fm_detach')
                evidence.update(verified=True, squad_counts=counts, roster_entries=sum(counts), virtual_entries=virtuals,
                                query_cases=summaries, tool_count=len(tools),
                                scope='Native getter/label-backed values, fresh profile readback, filters/sorting/truncation; no UI comparison.')
                print(f'Verified {sum(counts)} roster entries, {virtuals} cached virtual profiles, combined player/staff and {len(summaries)} selection queries.')
    finally:
        path = root/'evidence/live-player-profiles-mcp.json'
        path.write_text(json.dumps(evidence, indent=2)+'\n')
        print(path)


if __name__ == '__main__': asyncio.run(verify())
