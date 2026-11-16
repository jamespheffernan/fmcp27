"""Check club finances over the real stdio MCP, with no foreground UI."""
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
                managed = await call('fm_get_club_finances', session_id=sid)
                assert managed['finances']['state'] == 'stored' and managed['finances']['currency'] == 'GBP'
                checked, selected_refs = [], []
                for name in ('Newcastle', 'Liverpool', 'Barcelona'):
                    found = await call('fm_find_clubs', session_id=sid, name=name, max_matches=100)
                    assert found['next_cursor'] is None and found['clubs']
                    for club in found['clubs']:
                        result = await call('fm_get_club_finances', session_id=sid, club_ref=club['club_ref'])
                        fresh = await call('fm_get_club_finances', session_id=sid, club_ref=club['club_ref'])
                        assert result['finances'] == fresh['finances']
                        finance = result['finances']
                        assert finance['state'] in ('stored', 'partial_base_record', 'no_finance_record')
                        if finance['state'] == 'stored':
                            assert finance['currency'] == 'GBP' and finance['weekly_wage_budget'] >= 0
                            assert all(type(finance[k]) is int for k in ('balance', 'weekly_wage_budget', 'stored_transfer_budget'))
                        elif finance['state'] == 'partial_base_record':
                            assert type(finance['balance']) is int and finance['currency'] == 'GBP'
                            assert finance['weekly_wage_budget'] is None and finance['stored_transfer_budget'] is None
                            assert finance['unavailable_fields'] == ['weekly_wage_budget', 'stored_transfer_budget', 'current_transfer_budget', 'remaining_weekly_wage_budget']
                            assert finance['current_transfer_budget']['state'] == 'not_applicable'
                        else:
                            assert all(finance[k] is None for k in ('balance', 'weekly_wage_budget', 'stored_transfer_budget', 'currency'))
                        budget = finance['current_transfer_budget']
                        if finance['state'] == 'stored':
                            assert budget['state'] == 'decoded' and type(budget['amount']) is int
                        check = await call('fm_check_transfer_budget', session_id=sid,
                                           club_ref=club['club_ref'], upfront_fee_gbp=1000000)
                        assert check['current_transfer_budget'] == budget
                        assert check['fits_current_transfer_budget'] == (None if budget['amount'] is None else budget['amount'] >= 1000000)
                        assert check['budget_after_upfront_fee'] == (None if budget['amount'] is None else budget['amount'] - 1000000)
                        wage = finance['remaining_weekly_wage_budget']
                        if wage['amount'] is not None:
                            assert wage['state'] == 'stored' and wage['freshness'] == 'stored_without_refresh'
                            expected = 0 if finance['weekly_wage_budget'] == 0 else finance['weekly_wage_budget'] - wage['weekly_spending_used']
                            assert wage['amount'] == expected
                        wage_check = await call('fm_check_wage_budget', session_id=sid,
                            club_ref=club['club_ref'], additional_weekly_wage_gbp=100000)
                        assert wage_check['remaining_weekly_wage_budget'] == wage
                        assert wage_check['fits_remaining_wage_budget'] == (None if wage['amount'] is None else wage['amount'] >= 100000)
                        assert wage_check['budget_after_additional_wage'] == (None if wage['amount'] is None else wage['amount'] - 100000)
                        if result['club'] == managed['club']:
                            squads = await call('fm_get_club_squads', session_id=sid, club_ref=club['club_ref'])
                            if any(s['is_managed_team'] for s in squads['squads']):
                                assert finance == managed['finances']
                                evidence['managed_and_selected_agree'] = True
                        checked.append({'club': result['club'], 'finances': finance})
                        selected_refs.append(club['club_ref'])
                assert evidence['managed_and_selected_agree']
                amount = managed['finances']['current_transfer_budget']['amount']
                for fee in (0, amount, amount + 1):
                    check = await call('fm_check_transfer_budget', session_id=sid, upfront_fee_gbp=fee)
                    assert check['fits_current_transfer_budget'] is (fee <= amount)
                    assert check['budget_after_upfront_fee'] == amount - fee
                wage_amount = managed['finances']['remaining_weekly_wage_budget']['amount']
                assert wage_amount is not None
                for additional in (0, max(0, wage_amount), max(0, wage_amount) + 1):
                    check = await call('fm_check_wage_budget', session_id=sid, additional_weekly_wage_gbp=additional)
                    assert check['fits_remaining_wage_budget'] is (additional <= wage_amount)
                    assert check['budget_after_additional_wage'] == wage_amount - additional
                for invalid in (True, -1, 2147483648, 1.1, '1'):
                    assert (await client.call_tool('fm_check_wage_budget', {'session_id': sid, 'additional_weekly_wage_gbp': invalid})).isError
                assert (await client.call_tool('fm_check_wage_budget', {'session_id': sid, 'additional_weekly_wage_gbp': 0, 'club_ref': selected_refs[0], 'coach_name': 'test'})).isError
                assert (await client.call_tool('fm_get_club_finances', {'session_id': sid, 'club_ref': selected_refs[0], 'coach_name': 'test'})).isError
                await call('fm_detach')
                assert (await client.call_tool('fm_get_club_finances', {'session_id': sid, 'club_ref': selected_refs[0]})).isError
                assert (await client.call_tool('fm_check_wage_budget', {'session_id': sid, 'additional_weekly_wage_gbp': 0})).isError
                evidence.update(verified=True, clubs=checked, club_count=len(checked), tool_count=len(tools), foreground_ui_used=False,
                    fee_comparison_cases=len(checked)+3,
                    wage_comparison_cases=len(checked)+3,
                    scope='Managed/selected club routes, typed finance records, current-budget rules, repeated readback, fee comparisons, selector and detached-session rejection. No UI comparison.')
                print(f'Verified stored club finances for {len(checked)} clubs through {len(tools)} read-only MCP tools.')
    finally:
        path = root/'evidence/live-club-finances-mcp.json'
        path.write_text(json.dumps(evidence, indent=2)+'\n')
        print(path)


if __name__ == '__main__': asyncio.run(verify())
