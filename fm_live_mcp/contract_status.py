"""Current contract status through the native Pcst/Csts property path."""
import struct

from . import players, world

LABELS = {0: 'Part Time', 1: 'Full Time', 2: 'Amateur', 3: 'Youth', 4: 'Non-Contract'}


def decode(read, base, person):
    table = world.pointer(read, person)
    if (players.u64(read(table + 121 * 8, 8)) != base + 0xCB3724
            or struct.unpack('<q', read(table - 0x3D8, 8))[0] != -0x110):
        raise ValueError('Contract pointer getter changed')
    contract = players.u64(read(person - 0x98, 8))
    result = {'title': None, 'native_code': None}
    if not contract:
        return {**result, 'state': 'no_contract', 'evidence': 'null_native_contract'}
    vtable = world.pointer(read, contract)
    kind = next((k for k in ('full_contract', 'basic_contract')
                 if vtable == base + world.TYPES[k][0]), None)
    if kind is None:
        raise ValueError('Unsupported contract status type')
    world.typed(read, base, contract, kind)
    if world.pointer(read, contract + 8) != person:
        raise ValueError('Contract status owner changed')
    if kind == 'basic_contract':
        return {**result, 'state': 'basic_contract_status_unavailable',
                'evidence': 'native_basic_contract_status_sentinel'}
    if players.u64(read(vtable + 27 * 8, 8)) != base + 0x127BE34:
        raise ValueError('Contract status getter changed')
    code = struct.unpack('<b', read(contract + 0xC3, 1))[0]
    return {'title': LABELS.get(code), 'native_code': code,
            'state': 'decoded' if code in LABELS else 'unmapped_native_status',
            'evidence': 'native_contract_status_getter_and_editor_labels'}
