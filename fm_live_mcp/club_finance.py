"""Stored club finances and the verified native current transfer-budget branch."""
import struct

from . import players, transfer_budget, wage_budget, wages, world


GETTERS = {3: 0xE7DFB8, 20: 0xE86224, 54: 0xE84AC4}
BASE_GETTERS = {3: 0xE7D238, 54: 0xE649F4}
FIELDS = {'balance': 0xC, 'weekly_wage_budget': 0x808, 'stored_transfer_budget': 0x7C4}
LIMITATIONS = (
    'Stored amounts in whole GBP. weekly_wage_budget is a weekly total, not remaining wage room. '
    'remaining_weekly_wage_budget follows the native property using stored spending without refreshing it. '
    'The stored transfer budget precedes native availability rules. current_transfer_budget applies '
    'the verified normal-career property path; unsupported mode/date/manager adjustments return null. '
    'A decoded budget does not establish an affordable complete offer or board approval. Detailed payroll, '
    'commitment breakdowns and UI currency/period formatting are not decoded. Loan records in optional details give original amounts and repayment terms. '
    'Base finance records expose balance only and have no native current-budget property. Reads are non-atomic.'
)


def decode(read, base, club):
    world.typed(read, base, club, 'club')
    club_table = base + world.TYPES['club'][0]
    if players.u64(read(club_table + 3*8, 8)) != base + 0xE476C4:
        raise ValueError('Club finance property route changed')
    address = players.u64(read(club + 0x150, 8))
    result = {'state': 'no_finance_record' if not address else 'stored',
              'currency': None, 'balance': None, 'weekly_wage_budget': None,
              'stored_transfer_budget': None,
              'unavailable_fields': list(FIELDS),
              'evidence': 'null_native_finance_pointer' if not address else 'native_cash_properties_and_base_currency'}
    if not address:
        result['current_transfer_budget'] = transfer_budget.decode(read, base, club, 0, None)
        result['unavailable_fields'].append('current_transfer_budget')
        result['remaining_weekly_wage_budget'] = wage_budget.decode(read, base, 0, None)
        result['unavailable_fields'].append('remaining_weekly_wage_budget')
        return result
    table = world.pointer(read, address)
    basic = table == base + world.TYPES['club_finance_base'][0]
    world.typed(read, base, address, 'club_finance_base' if basic else 'club_finance')
    for slot, getter in (BASE_GETTERS if basic else GETTERS).items():
        if players.u64(read(table + slot*8, 8)) != base + getter:
            raise ValueError('Club finance getter changed')
    for name, offset in FIELDS.items():
        if basic and name != 'balance':
            continue
        result[name] = struct.unpack('<i', read(address + offset, 4))[0]
    if not basic and result['weekly_wage_budget'] < 0:
        raise ValueError('Unsupported negative weekly wage budget')
    result['state'] = 'partial_base_record' if basic else 'stored'
    result['unavailable_fields'] = ['weekly_wage_budget', 'stored_transfer_budget'] if basic else []
    result['currency'] = wages.base_currency(read, base)
    result['current_transfer_budget'] = transfer_budget.decode(read, base, club, address, result['stored_transfer_budget'])
    if result['current_transfer_budget']['amount'] is None:
        result['unavailable_fields'].append('current_transfer_budget')
    result['remaining_weekly_wage_budget'] = wage_budget.decode(read, base, address, result['weekly_wage_budget'])
    if result['remaining_weekly_wage_budget']['amount'] is None:
        result['unavailable_fields'].append('remaining_weekly_wage_budget')
    return result
