"""Verify contribution queries and reusable entity references over live stdio MCP."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def signature(row):
    return (row['person']['name'], row['payer']['unique_id'], row['recipient']['unique_id'],
            row['weekly_amount'], row['paid_until'])


async def verify():
    root = Path(__file__).resolve().parents[1]
    evidence = {'observed_at': datetime.now(timezone.utc).isoformat(), 'steps': [], 'foreground_ui_used': False}
    try:
        async with stdio_client(StdioServerParameters(command='/bin/sh', args=[str(root/'scripts/run_mcp.sh')])) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                async def call(name, **args):
                    result = await client.call_tool(name, args)
                    evidence['steps'].append({'tool': name, 'error': result.isError, 'result': result.structuredContent})
                    assert not result.isError and result.structuredContent is not None, (name, result.content)
                    return result.structuredContent
                tools = (await client.list_tools()).tools
                assert len(tools) == 28 and all(t.annotations.readOnlyHint for t in tools)
                sid = (await call('fm_attach'))['session_id']
                all_rows = await call('fm_get_wage_contributions', session_id=sid, all_clubs=True)
                fresh = await call('fm_get_wage_contributions', session_id=sid, all_clubs=True)
                assert all_rows['complete_native_list'] and all_rows['count'] > 0
                assert [signature(row) for row in all_rows['contributions']] == [signature(row) for row in fresh['contributions']]
                assert all_rows['total_weekly_contributions'] == sum(row['weekly_amount'] for row in all_rows['contributions'])
                assert all_rows['unresolved_person_count'] == 0
                assert all_rows['currency'] == 'GBP' and all_rows['period'] == 'week'
                refs, person_kinds = {}, {}
                for row in all_rows['contributions']:
                    person = row['person']
                    if 'staff_ref' in person:
                        observed = (await call('fm_get_staff', session_id=sid, staff_ref=person['staff_ref']))['staff']
                        kind = 'staff'
                    else:
                        observed = (await call('fm_get_player', session_id=sid, player_ref=person['player_ref']))['player']
                        kind = 'player'
                    for key in ('name', 'display_name', 'birth_date'): assert person[key] == observed[key]
                    person_kinds[kind] = person_kinds.get(kind, 0) + 1
                    for key in ('payer', 'recipient'):
                        refs[row[key]['unique_id']] = row[key]['club_ref']
                assert person_kinds.get('staff', 0) > 0 and person_kinds.get('player', 0) > 0
                for identity, ref in refs.items():
                    selected = await call('fm_get_wage_contributions', session_id=sid, club_ref=ref)
                    expected = [row for row in all_rows['contributions'] if identity in (row['payer']['unique_id'], row['recipient']['unique_id'])]
                    assert [signature(row) for row in selected['contributions']] == [signature(row) for row in expected]
                    outgoing = sum(row['weekly_amount'] for row in expected if row['payer']['unique_id'] == identity)
                    incoming = sum(row['weekly_amount'] for row in expected if row['recipient']['unique_id'] == identity)
                    assert selected['outgoing_weekly_total'] == outgoing and selected['incoming_weekly_total'] == incoming
                    assert selected['net_outgoing_weekly_total'] == outgoing - incoming
                    for row in selected['contributions']:
                        direction = 'both' if row['payer']['unique_id'] == row['recipient']['unique_id'] else 'outgoing' if row['payer']['unique_id'] == identity else 'incoming'
                        assert row['direction'] == direction
                managed = await call('fm_get_wage_contributions', session_id=sid)
                managed_id = (await call('fm_get_save', session_id=sid))['save']['coaches'][0]['club']
                assert managed['club'] == managed_id
                for args in ({'all_clubs': 1}, {'all_clubs': 'true'}, {'all_clubs': True, 'club_ref': next(iter(refs.values()))},
                             {'all_clubs': True, 'coach_name': 'x'}, {'club_ref': next(iter(refs.values())), 'coach_name': 'x'}):
                    assert (await client.call_tool('fm_get_wage_contributions', {'session_id': sid, **args})).isError
                await call('fm_detach')
                assert (await client.call_tool('fm_get_wage_contributions', {'session_id': sid, 'all_clubs': True})).isError
                evidence.update(verified=True, native_record_count=all_rows['native_records_examined'],
                    total_weekly_contributions=all_rows['total_weekly_contributions'], selected_clubs_checked=len(refs),
                    person_kinds=person_kinds, managed_club=managed['club'], managed_count=managed['count'], tool_count=len(tools),
                    scope='Complete native contribution list, repeated readback, payer/recipient filters and totals, player/staff/club references, strict selectors and detach. No UI comparison.')
                print(f'Verified {all_rows["count"]} live contributions and {len(refs)} club filters through {len(tools)} read-only tools.')
    finally:
        path = root/'evidence/live-wage-contributions-mcp.json'
        path.write_text(json.dumps(evidence, indent=2)+'\n')
        print(path)


if __name__ == '__main__': asyncio.run(verify())
