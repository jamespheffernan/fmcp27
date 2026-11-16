"""Compare public stage/table queries with the independently captured native census."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    census = json.loads((root/'evidence/runtime-stage-survey.json').read_text())
    assert census['verified']
    assert json.loads((root/'evidence/league-stage-layout-verification.json').read_text())['verified']
    receipt = dict(verified=False, observed_at=datetime.now(timezone.utc).isoformat(),
                   catalogs=0, tables=0, rows=0, unassigned=0, shared_runtimes=0, roster_samples=[])
    started = time.monotonic()
    try:
        async with stdio_client(StdioServerParameters(command='/bin/sh', args=[str(root/'scripts/run_mcp.sh')])) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                assert {'fm_get_competition_stages', 'fm_get_standings'} <= {t.name for t in tools}
                assert all(t.annotations.readOnlyHint for t in tools)
                async def call(tool, **args):
                    result = await client.call_tool(tool, args)
                    assert not result.isError and result.structuredContent is not None, (tool, args, result.content)
                    return result.structuredContent
                receipt['server_version'] = (await call('fm_status'))['server_version']
                sid = (await call('fm_attach'))['session_id']
                receipt['save'] = await call('fm_get_save', session_id=sid)
                refs = {}; cursor = None
                while True:
                    page = await call('fm_find_competitions', session_id=sid, max_matches=100, cursor=cursor)
                    refs.update({r['database_index']: r for r in page['competitions']})
                    cursor = page['next_cursor']
                    if cursor is None: break
                receipt['competition_count'] = len(refs)
                assert len(refs) == census['competition_count']
                seen = set(); kinds = set(); last_ref = None
                names = {'0x56759f8':'league', '0x5673fe0':'group', '0x5671128':'cup',
                         '0x567a6a0':'empty', '0x5670d60':'cup_group'}
                for source in census['competitions']:
                    competition = refs[source['competition_index']]
                    result = await call('fm_get_competition_stages', session_id=sid,
                                        competition_ref=competition['competition_ref'])
                    assert result['competition']['native_id'] == source['native_id']
                    assert result['runtime_competition']['database_index'] == source['runtime_competition_index']
                    assert result['runtime_state'] == 'decoded'
                    assert result['native_season_code'] == source['native_season_code']
                    assert result['shared_runtime'] == (source['competition_index'] != source['runtime_competition_index'])
                    receipt['shared_runtimes'] += result['shared_runtime']
                    assert result['count'] == len(source['stages'])
                    by_path = {tuple(s['path']): s for s in result['stages']}
                    for expected in source['stages']:
                        path = tuple(map(int, expected['stage_index'].split('/')))
                        stage = by_path[path]
                        if expected.get('null'):
                            assert stage['state'] == 'null_slot' and stage['stage_ref'] is None
                            continue
                        assert stage['kind'] == names[expected['vtable']]
                        if 'group_count' in expected: assert stage['child_slots'] == expected['group_count']
                        if 'rows' not in expected or expected['address'] in seen: continue
                        seen.add(expected['address']); last_ref = stage['stage_ref']
                        table = await call('fm_get_standings', session_id=sid, stage_ref=last_ref)
                        assert table['count'] == expected['native_count'] == len(expected['rows'])
                        assert table['native_order_view_code'] == expected['native_view_code']
                        assert list(table['point_rules'].values()) == expected['point_rules']
                        for row, raw in zip(table['rows'], expected['rows']):
                            assert row['row_index'] == raw['index']
                            assert row['position'] == (bytes.fromhex(raw['tail'])[-1]+1 if expected['native_view_code'] == 0 else None)
                            assert (row['team']['native_id'] if row['team'] else None) == raw['native_id']
                            assert (row['team']['database_index'] if row['team'] else None) == raw['team_index']
                            stats = bytes.fromhex(raw['stats'])
                            for name, offset in (('overall', 0), ('home', 24), ('away', 48)):
                                gf, ga, pts, played = struct.unpack_from('<hhhb', stats, offset+8)
                                win, draw, loss, pens = struct.unpack_from('<bbbb', stats, offset+16)
                                assert row[name] == dict(goals_for=gf, goals_against=ga, points=pts, played=played,
                                    wins=win, draws_or_penalty_wins=draw, losses=loss, penalty_losses=pens,
                                    goal_difference=(gf-ga+32768)%65536-32768)
                            if row['team'] and row['team']['kind'] not in kinds:
                                team = row['team']; kinds.add(team['kind'])
                                roster = await call('fm_get_team_squad', session_id=sid, team_ref=team['team_ref'])
                                query = await call('fm_query_team_players', session_id=sid, team_ref=team['team_ref'], limit=5)
                                assert roster['team']['native_id'] == team['native_id']
                                assert query['roster_count'] == roster['count']
                                receipt['roster_samples'].append(dict(team=team, roster_count=roster['count']))
                        receipt['tables'] += 1; receipt['rows'] += table['count']
                        receipt['unassigned'] += table['unassigned_team_rows']
                    receipt['catalogs'] += 1
                    if receipt['catalogs'] % 100 == 0:
                        print({k: receipt[k] for k in ('catalogs', 'tables', 'rows', 'shared_runtimes')}, flush=True)
                runtime_indexes = {s['competition_index'] for s in census['competitions']}
                absent = next(r for i, r in refs.items() if i not in runtime_indexes)
                result = await call('fm_get_competition_stages', session_id=sid, competition_ref=absent['competition_ref'])
                assert result['runtime_state'] == 'absent' and result['stages'] == []
                for tool, args in [('fm_get_standings', {'stage_ref':'invented'}),
                                   ('fm_get_competition_stages', {'competition_ref':'invented'})]:
                    assert (await client.call_tool(tool, dict(session_id=sid, **args))).isError
                await call('fm_detach')
                assert (await client.call_tool('fm_get_standings', dict(session_id=sid, stage_ref=last_ref))).isError
                receipt.update(verified=True, tool_count=len(tools), foreground_ui_used=False)
    finally:
        receipt['elapsed_seconds'] = round(time.monotonic()-started, 2)
        (root/'evidence/live-competition-stages-mcp.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('save', 'roster_samples')}, indent=2))


if __name__ == '__main__': asyncio.run(verify())
