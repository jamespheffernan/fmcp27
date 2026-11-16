"""Six stored main-contract cash bonuses, without executing native getters."""
import struct

# name: native entry kind, contract property, person/editor property, label
BONUSES = {
    'appearance_fee': (32, 'Cabo', 'Pcap', 'Appearance Fee'),
    'goal_bonus': (33, 'Cgbo', 'Pcgb', 'Goal Bonus'),
    'assist_bonus': (39, 'Csbo', 'PcAb', 'Assist Bonus'),
    'clean_sheet_bonus': (34, 'Ccsb', 'Pccb', 'Clean Sheet Bonus'),
    'unused_substitute_fee': (38, 'Cusb', 'Pusb', 'Unused Substitute Fee'),
    'international_cap_bonus': (37, 'Cicb', 'Picb', 'International Cap Bonus'),
}
GETTERS = {3: 0x128670C, 52: 0x1288F28}
MAX_ENTRIES = 256

# After the tables: importing this module first reaches staff -> contract_terms, which reads
# BONUSES while this module is still initialising.
from . import players, wages, world  # noqa: E402


def read_entries(read, base, person):
    table = world.pointer(read, person)
    if (players.u64(read(table + 121 * 8, 8)) != base + 0xCB3724
            or struct.unpack('<q', read(table - 0x3D8, 8))[0] != -0x110):
        raise ValueError('Contract pointer getter changed')
    contract = players.u64(read(person - 0x98, 8))
    if not contract:
        return 'no_contract', None, ()
    vtable = world.pointer(read, contract)
    kind = next((k for k in ('full_contract', 'basic_contract')
                 if vtable == base + world.TYPES[k][0]), None)
    if kind is None:
        raise ValueError('Unsupported contract entry type')
    world.typed(read, base, contract, kind)
    if world.pointer(read, contract + 8) != person:
        raise ValueError('Contract entry owner changed')
    if kind == 'basic_contract':
        return 'basic_contract', contract, ()
    for slot, getter in GETTERS.items():
        if players.u64(read(vtable + slot * 8, 8)) != base + getter:
            raise ValueError('Contract bonus getter changed')
    start, end, capacity = struct.unpack('<QQQ', read(contract + 0x68, 24))
    if start == end == capacity == 0:
        raw = b''
    else:
        if start < 4096 or any(p % 8 for p in (start, end, capacity)) or not start <= end <= capacity:
            raise ValueError('Invalid contract bonus vector')
        if capacity - start > MAX_ENTRIES * 8:
            raise ValueError('Contract bonus vector exceeds bound')
        raw = read(start, end - start) if start != end else b''
    return 'full_contract', contract, tuple(struct.iter_unpack('<ihBB', raw))


def decode(read, base, person, currency=None):
    state, _, entries = read_entries(read, base, person)
    result = {'currency': None, 'bonuses': None, 'native_entry_count': None,
              'other_entry_count': None,
              'scope': 'Six stored main-contract cash bonuses. No payment totals, weekly projection, '
                       'eligibility, remaining clauses, loan terms or UI visibility filtering.'}
    if state == 'no_contract':
        return {**result, 'state': 'no_contract', 'evidence': 'null_native_contract'}
    if state == 'basic_contract':
        return {**result, 'state': 'basic_contract_bonuses_unavailable',
                'evidence': 'basic_contract_has_no_verified_bonus_vector'}

    bonuses = {}
    known_count = 0
    for name, (code, _, _, _) in BONUSES.items():
        matching = [entry for entry in entries if entry[2] == code]
        if any(entry[0] < 0 for entry in matching):
            raise ValueError('Unsupported negative contract bonus')
        # These six kinds are outside the native 0x3002778EF38 parameter mask.
        # The cash getter selects the first match, even when there are duplicates.
        bonuses[name] = {'amount': matching[0][0] if matching else None,
                         'state': 'stored' if matching else 'not_present',
                         'matching_entry_count': len(matching)}
        known_count += len(matching)
    return {**result, 'state': 'decoded', 'currency': currency or wages.base_currency(read, base),
            'bonuses': bonuses, 'native_entry_count': len(entries),
            'other_entry_count': len(entries) - known_count,
            'evidence': 'native_contract_cash_bonus_getter_and_editor_labels'}
