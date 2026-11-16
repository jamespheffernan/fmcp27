"""Verify stored wages and filters over fresh stdio MCP; no UI interaction."""
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
                plain = await call('fm_get_club_staff', session_id=sid)
                full = await call('fm_get_club_staff', session_id=sid, include_wage=True)
                assert all('wage' not in p['contract'] for p in plain['staff'])
                for person in full['staff']:
                    fresh = (await call('fm_get_staff', session_id=sid, staff_ref=person['staff_ref'], include_wage=True))['staff']
                    assert fresh == {k: v for k, v in person.items() if k != 'staff_ref'}
                for lower, upper, limit in [(0, None, 100), (3000, 3000, 5), (5000, 14000, 3), (1000000, None, 20)]:
                    result = await call('fm_query_club_staff_wages', session_id=sid, minimum=lower, maximum=upper, limit=limit)
                    expected = [p for p in full['staff'] if p['contract']['wage']['amount'] >= lower
                                and (upper is None or p['contract']['wage']['amount'] <= upper)]
                    expected.sort(key=lambda p: (-p['contract']['wage']['amount'], p['display_name'].casefold(), p['birth_date']))
                    assert result['matched_count'] == len(expected) and result['truncated'] == (len(expected) > limit)
                    assert result['matched_contract_wage_sum'] == sum(p['contract']['wage']['amount'] for p in expected)
                    assert result['roster_contract_wage_sum'] == sum(p['contract']['wage']['amount'] for p in full['staff'])
                    assert [(p['name'], p['contract']['wage']) for p in result['staff']] == [(p['name'], p['contract']['wage']) for p in expected[:limit]]
                squad = await call('fm_get_managed_squad', session_id=sid)
                for person in squad['players']:
                    fresh = (await call('fm_get_player', session_id=sid, player_ref=person['player_ref'], include_wage=True))['player']
                    assert fresh['name'] == person['name'] and fresh['wage']['state'] == 'decoded'
                    assert fresh['wage']['currency'] == 'GBP' and fresh['wage']['period'] == 'week'
                found = await call('fm_find_staff', session_id=sid, name='Mohamed Salah')
                salah = next(p for p in found['staff'] if p['birth_date'] == '1992-06-15')
                combined = (await call('fm_get_staff', session_id=sid, staff_ref=salah['staff_ref'], include_wage=True))['staff']
                found = await call('fm_find_save_players', session_id=sid, name='Mohamed Salah')
                salah = next(p for p in found['players'] if p['birth_date'] == '1992-06-15')
                combined_player = (await call('fm_get_player', session_id=sid, player_ref=salah['player_ref'], include_wage=True))['player']
                assert combined_player['wage'] == combined['contract']['wage']
                catalog = await call('fm_get_database_catalog', session_id=sid)
                assert catalog['native_table_counts']['currencies'] == 173
                await call('fm_detach')
                evidence.update(verified=True, staff_count=full['count'], player_count=squad['count'], tool_count=len(tools),
                                weekly_staff_contract_sum=sum(p['contract']['wage']['amount'] for p in full['staff']),
                                currency='GBP', scope='Native wages, fresh readback, inclusive thresholds, sums and truncation; no UI comparison.')
                print(f"Verified wages for {full['count']} staff, {squad['count']} players, both combined-record routes, and wage queries.")
    finally:
        path = root/'evidence/live-wages-mcp.json'
        path.write_text(json.dumps(evidence, indent=2)+'\n')
        print(path)


if __name__ == '__main__': asyncio.run(verify())
