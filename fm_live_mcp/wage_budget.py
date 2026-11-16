"""Read the native Cwrb property from stored finance totals without refreshing them."""
import struct

from . import players, transfer_budget, world


SPENDING_OFFSET = 0x814


def decode(read, base, finance, weekly_budget):
    result = {'amount': None, 'state': 'unavailable', 'reason': 'inactive_game_property_route',
              'weekly_spending_used': None, 'evidence': 'native_remaining_wage_budget_property',
              'freshness': 'stored_without_refresh'}
    if not read(base + 0x56D34E0, 1)[0] & 1:
        return result
    transfer_budget._service(read, base, transfer_budget.GAME_CLUB_ROOT,
                             'game_club', {7: 0x1FC7914, 22: 0x1FAF4D8})
    if not finance:
        result['reason'] = 'no_finance_record'
        return result
    table = world.pointer(read, finance)
    basic = table == base + world.TYPES['club_finance_base'][0]
    world.typed(read, base, finance, 'club_finance_base' if basic else 'club_finance')
    if players.u64(read(table + 8*8, 8)) != base + (0xE648D4 if basic else 0xEB8174):
        raise ValueError('Wage budget finance discriminator changed')
    if basic:
        result.update(state='not_applicable', reason='native_base_finance_no_wage_budget')
        return result
    # Cwrb returns zero before reading spending when the weekly budget is zero.
    if weekly_budget == 0:
        result.update(amount=0, state='stored', reason='native_zero_wage_budget')
        return result
    if type(weekly_budget) is not int or not 0 < weekly_budget <= 2147483647:
        raise ValueError('Unsupported weekly wage budget')
    if players.u64(read(table + 40*8, 8)) != base + 0xE83ED0:
        raise ValueError('Wage spending getter changed')
    spending = struct.unpack('<i', read(finance + SPENDING_OFFSET, 4))[0]
    # The spending getter requests recalculation for <= -1001. Never run it or
    # turn that refresh marker into apparent spare budget.
    if spending <= -1001:
        result['reason'] = 'native_spending_requires_refresh'
        return result
    result['weekly_spending_used'] = spending
    amount = weekly_budget - spending
    if not -2147483648 <= amount <= 2147483647:
        result['reason'] = 'native_arithmetic_overflow'
        return result
    result.update(amount=amount, state='stored', reason='native_budget_less_stored_spending')
    return result
