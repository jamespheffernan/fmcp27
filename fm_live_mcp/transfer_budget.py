"""Read the verified normal-career branch of the native current-budget property.

The native functions are traced offline, never called. Unsupported game-mode
branches stay explicit rather than falling back to the unadjusted stored value.
"""
from . import players, world


GAME_CLUB_ROOT = 0x56D2CE8
GAME_FINANCE_ROOT = 0x56D2B10


def _result(amount=None, state='unavailable', reason='unsupported_finance_type'):
    return {'amount': amount, 'state': state, 'reason': reason,
            'evidence': 'native_current_transfer_budget_property'}


def _service(read, base, root, kind, getters):
    address = world.pointer(read, base + root)
    world.typed(read, base, address, kind)
    table = world.pointer(read, address)
    for slot, getter in getters.items():
        if players.u64(read(table + slot*8, 8)) != base + getter:
            raise ValueError('Current transfer budget service getter changed')


def decode(read, base, club, finance, stored):
    if not read(base + 0x56D34E0, 1)[0] & 1:
        return _result(reason='inactive_game_property_route')
    _service(read, base, GAME_CLUB_ROOT, 'game_club', {7: 0x1FC7914, 22: 0x1FAF4D8})
    if read(base + 0x56D4951, 1)[0] == 1:
        return _result(reason='alternate_game_mode')
    # This branch precedes the finance null/type test in the native property.
    if read(club + 0x161, 1)[0] & 64 or int.from_bytes(read(club + 12, 4), 'little') == 0xD70DD0:
        return _result(state='not_applicable', reason='native_unavailable_sentinel')
    if not finance:
        return _result(reason='no_finance_record')
    if world.pointer(read, finance) != base + world.TYPES['club_finance'][0]:
        table = base + world.TYPES['club_finance_base'][0]
        if players.u64(read(table + 8*8, 8)) != base + 0xE648D4:
            raise ValueError('Current transfer budget base discriminator changed')
        return _result(state='not_applicable', reason='native_base_finance_no_current_budget')
    table = base + world.TYPES['club_finance'][0]
    if players.u64(read(table + 8*8, 8)) != base + 0xEB8174:
        raise ValueError('Current transfer budget finance discriminator changed')
    _service(read, base, GAME_FINANCE_ROOT, 'game_club_finance', {9: 0x1FFD5F0})
    if not read(base + 0x56D4972, 1)[0] & 1:
        if read(base + 0x56D4987, 1)[0] == 1:
            return _result(reason='dated_global_rule_not_decoded')
        return _result(0, 'decoded', 'native_global_rule_zero')
    if not read(club + 0x163, 1)[0] & 16:
        for record in world.vector(read, club + 0x118, 256):
            # Native nonpolymorphic club relationship record: +8 is the child.
            if players.u64(read(record + 8, 8)) != club:
                continue
            code = read(record + 0x30, 1)[0]
            if code <= 20 and (1 << code) & 0x1001F0 and players.u64(read(record, 8)):
                return _result(0, 'decoded', 'native_club_relationship_rule_zero')
    if read(base + 0x56D4999, 1)[0] == 1:
        return _result(reason='manager_budget_adjustment_not_decoded')
    # Unsigned (stored - 1) < 499 maps exactly 1..499 to zero.
    if 1 <= stored <= 499:
        return _result(0, 'decoded', 'native_small_budget_zero')
    return _result(stored, 'decoded', 'native_current_budget')
