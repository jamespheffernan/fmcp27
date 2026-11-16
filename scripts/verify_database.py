"""Verify global table searches through the configured MCP launcher."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    oracle = json.loads((root / 'tests/fixtures/player_profile_oracles.json').read_text())
    evidence = {'observed_at': datetime.now(timezone.utc).isoformat(), 'transport': 'stdio', 'steps': []}
    params = StdioServerParameters(command='/bin/sh', args=[str(root / 'scripts/run_mcp.sh')])
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                async def call(tool, **args):
                    started = time.monotonic()
                    response = await client.call_tool(tool, args)
                    evidence['steps'].append({'tool': tool, 'seconds': time.monotonic() - started,
                                              'error': response.isError, 'result': response.structuredContent})
                    if response.isError or response.structuredContent is None:
                        raise RuntimeError(str(response.content))
                    return response.structuredContent
                sid = (await call('fm_attach'))['session_id']
                catalog = await call('fm_get_database_catalog', session_id=sid)
                count = catalog['native_table_counts']['people']
                for expected in oracle['players']:
                    found = await call('fm_find_save_players', session_id=sid, name=expected['name'])
                    assert found['total_person_records'] == found['scanned_records'] == count
                    assert found['complete_table_scan']
                    player = next(p for p in found['players'] if p['name'] == expected['name'])
                    fresh = (await call('fm_get_player', session_id=sid, player_ref=player['player_ref']))['player']
                    assert fresh['birth_date'] == expected['birth_date']
                    assert fresh['attributes'] == expected['attributes']
                    print('Verified global UI oracle:', player['name'], flush=True)
                roster = await call('fm_get_managed_squad', session_id=sid)
                chema = next(p for p in roster['players'] if p['display_name'] == 'Chema Andrés')
                common = await call('fm_find_save_players', session_id=sid, name='Chema Andrés')
                assert any(p['name'] == chema['name'] and p['attributes'] == chema['attributes'] for p in common['players'])
                full = await call('fm_find_save_players', session_id=sid, name='Wharton', max_matches=100)
                assert full['complete_table_scan']
                cursor, names, scanned = None, [], 0
                for _ in range(10):
                    page = await call('fm_find_save_players', session_id=sid, name='Wharton', max_matches=1, cursor=cursor)
                    names.extend(p['name'] for p in page['players'])
                    scanned += page['scanned_records']
                    cursor = page['next_cursor']
                    if not cursor: break
                assert cursor is None and scanned == count
                assert names == [p['name'] for p in full['players']]
                limited = await call('fm_find_save_players', session_id=sid, name='Nick Woltemade', record_budget=1)
                assert limited['scanned_records'] == 1 and limited['next_cursor']
                resumed = await call('fm_find_save_players', session_id=sid, name='Nick Woltemade', cursor=limited['next_cursor'])
                assert resumed['next_cursor'] is None
                assert any(p['name'] == 'Nick Woltemade' for p in limited['players'] + resumed['players'])
                single = await call('fm_find_save_players', session_id=sid, name='Fassine')
                assert any(p['name'] == 'Sheku' and p['display_name'] == 'Sheku Fassine Fofana' for p in single['players'])
                await call('fm_detach')
                assert (await client.call_tool('fm_find_save_players', {'session_id': sid, 'name': 'Wharton'})).isError
                evidence['verified'] = True
                evidence['note'] = 'Single-component name checked against native strings; no new foreground UI interaction.'
                print('Verified catalog, common names, exact pagination, record budget, membership reread and detach.', flush=True)
    finally:
        output = root / 'evidence/live-database-mcp.json'
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print(output)


if __name__ == '__main__':
    asyncio.run(verify())
