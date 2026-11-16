"""Read contract dates and exercise expiry filtering through a fresh MCP process."""
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
                    if response.isError or response.structuredContent is None:
                        raise RuntimeError(str(response.content))
                    return response.structuredContent
                tools = (await client.list_tools()).tools
                assert len(tools) == 28 and all(t.annotations.readOnlyHint for t in tools)
                sid = (await call('fm_attach'))['session_id']
                plain = await call('fm_get_club_staff', session_id=sid)
                full = await call('fm_get_club_staff', session_id=sid, include_contract_dates=True)
                assert all('dates' not in p['contract'] for p in plain['staff'])
                assert [p['name'] for p in plain['staff']] == [p['name'] for p in full['staff']]
                for person in full['staff']:
                    fresh = (await call('fm_get_staff', session_id=sid, staff_ref=person['staff_ref'], include_contract_dates=True))['staff']
                    assert fresh == {k: v for k, v in person.items() if k != 'staff_ref'}
                for cutoff, limit in [('2031-06-30', 100), ('2031-06-29', 5), ('2033-06-30', 3)]:
                    result = await call('fm_query_club_staff_contracts', session_id=sid, expires_on_or_before=cutoff, limit=limit)
                    fixed = [p for p in full['staff'] if p['contract']['dates']['state'] == 'fixed_expiry']
                    expected = [p for p in fixed if p['contract']['dates']['expires'] <= cutoff]
                    expected.sort(key=lambda p: (p['contract']['dates']['expires'], p['display_name'].casefold(), p['birth_date']))
                    assert result['matched_count'] == len(expected)
                    assert result['fixed_expiry_count'] == len(fixed)
                    assert result['unclassified_count'] == full['count'] - len(fixed)
                    assert result['truncated'] == (len(expected) > limit)
                    assert [(p['name'], p['contract']['dates']) for p in result['staff']] == [(p['name'], p['contract']['dates']) for p in expected[:limit]]
                squad = await call('fm_get_managed_squad', session_id=sid)
                for person in squad['players']:
                    plain = (await call('fm_get_player', session_id=sid, player_ref=person['player_ref']))['player']
                    assert 'contract_dates' not in plain
                    fresh = (await call('fm_get_player', session_id=sid, player_ref=person['player_ref'], include_contract_dates=True))['player']
                    assert fresh['name'] == person['name']
                    assert fresh['contract_dates']['state'] == 'fixed_expiry'
                found = await call('fm_find_staff', session_id=sid, name='Mohamed Salah')
                salah = next(p for p in found['staff'] if p['birth_date'] == '1992-06-15')
                combined = (await call('fm_get_staff', session_id=sid, staff_ref=salah['staff_ref'], include_contract_dates=True))['staff']
                assert combined['record_kind'] == 'player_staff'
                assert combined['contract']['dates']['state'] == 'fixed_expiry'
                # Independent clubs exercise the shared PERSON_DATA fields outside the managed club.
                found = await call('fm_find_clubs', session_id=sid, name='Liverpool', max_matches=100)
                other_counts = []
                for club in found['clubs']:
                    if club['name'] == club['short_name'] == 'Liverpool':
                        other = await call('fm_get_club_staff', session_id=sid, club_ref=club['club_ref'], include_contract_dates=True)
                        other_counts.append(other['count'])
                for args in ({'expires_on_or_before': '2033-02-30'}, {'expires_on_or_before': '2033-06-30', 'limit': 0}):
                    assert (await client.call_tool('fm_query_club_staff_contracts', {'session_id': sid, **args})).isError
                await call('fm_detach')
                evidence.update(verified=True, staff_count=full['count'], player_count=squad['count'],
                                other_club_counts=other_counts, tool_count=len(tools),
                                scope='Native date getters, fresh readback, fixed-expiry filters. No foreground UI comparison.')
                print(f"Verified dates for {full['count']} staff, {squad['count']} players, combined record, other clubs {other_counts}, and expiry filters.")
    finally:
        output = root/'evidence/live-contract-dates-mcp.json'
        output.write_text(json.dumps(evidence, indent=2)+'\n')
        print(output)


if __name__ == '__main__': asyncio.run(verify())
