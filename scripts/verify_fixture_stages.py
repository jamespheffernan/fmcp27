"""Compare optional fixture-stage links with independent fixture and runtime censuses."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import tomllib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from verify_fixtures import expected

ROOT = Path(__file__).resolve().parents[1]
KINDS = {'0x56759f8': 'league', '0x5673fe0': 'group', '0x5671128': 'cup',
         '0x567a6a0': 'empty', '0x5670d60': 'cup_group'}


def check_link(actual, fixture, runtimes):
    assert actual['fixture_season_code'] == fixture['season_code']
    assert actual['native_stage_index'] == fixture['stage_index']
    runtime = runtimes.get(fixture['competition'])
    stage = None
    if fixture['competition'] is None:
        state = 'no_competition'
    elif runtime is None:
        state = 'runtime_absent'
    elif runtime['native_season_code'] != fixture['season_code']:
        state = 'different_season'
    elif fixture['stage_index'] < 0:
        state = 'unassigned_stage'
    else:
        stage = next((s for s in runtime['stages'] if s['stage_index'] == str(fixture['stage_index'])), None)
        state = ('stage_index_out_of_range' if stage is None else 'null_stage_slot' if stage.get('null')
                 else 'empty_stage' if KINDS[stage['vtable']] == 'empty' else 'decoded')
    assert actual['state'] == state, (actual, fixture, runtime)
    assert actual['runtime_season_code'] == (runtime['native_season_code'] if runtime else None)
    if runtime:
        assert actual['runtime_competition']['database_index'] == runtime['runtime_competition_index']
        assert actual['shared_runtime'] == (runtime['competition_index'] != runtime['runtime_competition_index'])
    else:
        assert actual['runtime_competition'] is None and not actual['shared_runtime']
    if state == 'decoded':
        assert actual['stage']['path'] == [fixture['stage_index']]
        assert actual['stage']['kind'] == KINDS[stage['vtable']]
        assert actual['stage']['standings_available'] == ('rows' in stage)
        assert actual['stage']['stage_ref']
    else:
        assert actual['stage'] is None
        stage = None
    return stage


async def verify():
    census = json.loads((ROOT/'evidence/runtime-stage-survey.json').read_text())
    assert census['verified']
    runtimes = {c['native_id']: c for c in census['competitions']}
    assert len(runtimes) == len(census['competitions'])
    config = tomllib.loads((Path.home()/'.codex/config.toml').read_text())['mcp_servers']['fm-live']
    receipt = {'verified': False, 'observed_at': datetime.now(timezone.utc).isoformat(),
               'years': [], 'readbacks': [], 'linked_tables_checked': 0, 'linked_table_rows_checked': 0}
    tables_seen, states_seen = set(), set()
    params = StdioServerParameters(command=config['command'], args=config['args'])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            async def call(tool, **arguments):
                result = await client.call_tool(tool, arguments)
                assert not result.isError and result.structuredContent is not None, (tool, result.content)
                return result.structuredContent
            receipt['server_version'] = (await call('fm_status'))['server_version']
            sid = (await call('fm_attach'))['session_id']
            try:
                for year in (2030, 2025):
                    source, baseline = expected(year)
                    found, pages, cursor = 0, 0, None
                    states = Counter()
                    while True:
                        page = await call('fm_find_fixtures', session_id=sid, year=year,
                                          max_matches=100, include_stage=True, cursor=cursor)
                        assert page['coverage']['loaded_group_count'] == sum(g['loaded'] for g in source['groups'])
                        for row in page['fixtures']:
                            raw = baseline[found]
                            assert row['date'] == raw['date'] and row['record_kind'] == raw['kind']
                            assert row['scores'] == raw['scores'] and row['kickoff_time'] == raw['kickoff_time']
                            assert (row['competition']['native_id'] if row['competition'] else None) == raw['competition']
                            for field, key in (('home_team', 'home'), ('away_team', 'away')):
                                assert (row[field]['native_id'] if row[field] else None) == raw[key]
                            stage = check_link(row['stage_link'], raw, runtimes)
                            state = row['stage_link']['state']
                            states[state] += 1
                            sample = (state, stage['vtable'] if stage else None, row['stage_link']['shared_runtime'])
                            if sample not in states_seen:
                                fresh = (await call('fm_get_fixture', session_id=sid, fixture_ref=row['fixture_ref'],
                                                    include_stage=True))['fixture']
                                check_link(fresh['stage_link'], raw, runtimes)
                                states_seen.add(sample)
                                receipt['readbacks'].append({'year': year, 'date': row['date'], 'case': sample})
                            if stage and 'rows' in stage and stage['address'] not in tables_seen:
                                table = await call('fm_get_standings', session_id=sid,
                                                   stage_ref=row['stage_link']['stage']['stage_ref'])
                                assert table['count'] == len(stage['rows'])
                                assert table['native_season_code'] == raw['season_code']
                                for actual, expected_row in zip(table['rows'], stage['rows']):
                                    assert (actual['team']['native_id'] if actual['team'] else None) == expected_row['native_id']
                                    stats = bytes.fromhex(expected_row['stats'])
                                    for name, offset in (('overall', 0), ('home', 24), ('away', 48)):
                                        gf, ga, points = struct.unpack_from('<hhh', stats, offset+8)
                                        assert actual[name]['goals_for'] == gf and actual[name]['goals_against'] == ga
                                        assert actual[name]['points'] == points
                                tables_seen.add(stage['address'])
                                receipt['linked_tables_checked'] += 1
                                receipt['linked_table_rows_checked'] += table['count']
                            found += 1
                        pages += 1
                        cursor = page['next_cursor']
                        if pages % 25 == 0:
                            print(f'{year}: {found}/{len(baseline)}, states={dict(states)}', flush=True)
                        if cursor is None:
                            break
                    assert found == len(baseline)
                    receipt['years'].append({'year': year, 'fixtures_checked': found, 'states': dict(states),
                                             'pages': pages, 'unavailable_groups': len(page['coverage']['unavailable_group_indices'])})
            finally:
                await call('fm_detach')
    receipt.update(verified=True, foreground_ui_used=False, native_execution=False,
                   scope='Stored matching-season top-level runtime stages; no historic-stage reconstruction or round-name claim')
    (ROOT/'evidence/live-fixture-stages-mcp.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    asyncio.run(verify())
