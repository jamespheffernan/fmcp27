"""Replay the reported shortlist and verify complete, lossless MCP pagination."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
CRITERIA = {'minimum_attributes': {'finishing': 15, 'off_the_ball': 15, 'acceleration': 15},
            'minimum_profile': {'positions.attacking_midfielder_right': 15, 'positions.striker': 15, 'feet.left': 15}}


async def verify():
    receipt = {'observed_at': datetime.now(timezone.utc).isoformat(), 'criteria': CRITERIA, 'steps': []}
    try:
        async with stdio_client(StdioServerParameters(command='/bin/sh', args=[str(ROOT/'scripts/run_mcp.sh')],
                                                     env=dict(os.environ))) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                async def call(name, **args):
                    response = await client.call_tool(name, args)
                    receipt['steps'].append({'tool': name, 'args': args, 'isError': response.isError,
                                             'result': response.structuredContent,
                                             **({'error': str(response.content)} if response.isError else {})})
                    assert not response.isError and response.structuredContent is not None, response.content
                    return response.structuredContent
                sid = (await call('fm_attach'))['session_id']
                async def scan(limit, budget):
                    cursor, rows, scanned, pages = None, [], 0, 0
                    while True:
                        page = await call('fm_query_save_players', session_id=sid, **CRITERIA,
                                          max_matches=limit, record_budget=budget, cursor=cursor)
                        assert page['unclassified_count'] == 0
                        rows.extend(page['players']); scanned += page['scanned_records']; pages += 1
                        assert pages < 100 and page['scanned_records'] > 0
                        cursor = page['next_cursor']
                        if not cursor:
                            assert page['stop_reason'] == 'table_end'
                            assert scanned == page['total_person_records']
                            return rows, scanned, pages
                rows, total, pages = await scan(5, 200000)
                alternative, total2, pages2 = await scan(100, 50000)
                comparable = lambda items: [{k:v for k,v in p.items() if k != 'player_ref'} for p in items]
                assert total2 == total and comparable(rows) == comparable(alternative)
                for row in rows:
                    fresh = (await call('fm_get_player', session_id=sid, player_ref=row['player_ref'], include_profile=True))['player']
                    assert fresh['name'] == row['name'] and fresh['profile'] == row['profile'] and fresh['attributes'] == row['attributes']
                # The formerly failing record must itself be readable, not silently skipped.
                generated = await call('fm_query_save_players', session_id=sid, name_contains='Darwin Maripán', max_matches=100)
                assert generated['complete_table_scan'] and generated['count'] >= 1
                for row in generated['players']:
                    fresh = (await call('fm_get_player', session_id=sid, player_ref=row['player_ref'], include_profile=True))['player']
                    assert fresh['profile'] == row['profile']
                await call('fm_detach')
                receipt.update(verified=True, person_records=total, shortlist_count=len(rows),
                               pagination_pages=pages, alternative_pages=pages2,
                               names=[p['name'] for p in rows], failing_record_readback=True)
                print(json.dumps({k:v for k,v in receipt.items() if k!='steps'}, indent=2))
    finally:
        (ROOT/'evidence/live-recruitment-continuation.json').write_text(json.dumps(receipt, indent=2)+'\n')


if __name__ == '__main__':
    asyncio.run(verify())
