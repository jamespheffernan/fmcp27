"""Stored weekly main-contract wages in the native base currency."""
import struct

from . import database, players, world


def base_currency(read, base):
    # Native currency enum zero maps to database ID 86 (United Kingdom Pound).
    if int.from_bytes(read(base + 0x538EF50, 4), 'little') != 86:
        raise ValueError('Native base currency mapping changed')
    info = database.table(read, base, 'currencies')
    if not 1 <= info['count'] <= 512:
        raise ValueError('Currency table exceeds verified bound')
    pointers = struct.unpack(f"<{info['count']}Q", read(info['start'], info['count'] * 8))
    found = []
    for index, address in enumerate(pointers):
        raw = read(address, 20)
        if struct.unpack_from('<I', raw, 12)[0] != 86:
            continue
        world.typed(read, base, address, 'currency')
        record_index, identity, secondary = struct.unpack_from('<III', raw, 8)
        if record_index != index:
            raise ValueError('Base currency identity changed')
        name = world.string(read, players.u64(read(address + 0x18, 8)))
        rate = struct.unpack('<f', read(address + 0x38, 4))[0]
        if name != 'United Kingdom Pound' or rate != 1.0:
            raise ValueError('Unsupported native base currency')
        found.append(address)
    if len(found) != 1:
        raise ValueError('Base currency must have one live record')
    return 'GBP'


def decode(read, base, person, currency=None):
    table = world.pointer(read, person)
    if (players.u64(read(table + 121 * 8, 8)) != base + 0xCB3724
            or struct.unpack('<q', read(table - 0x3D8, 8))[0] != -0x110):
        raise ValueError('Contract pointer getter changed')
    contract = players.u64(read(person - 0x98, 8))
    if not contract:
        return {'amount': None, 'currency': None, 'period': 'week', 'state': 'no_contract',
                'evidence': 'null_native_contract'}
    vtable = world.pointer(read, contract)
    kind = next((k for k in ('full_contract', 'basic_contract')
                 if vtable == base + world.TYPES[k][0]), None)
    if kind is None:
        raise ValueError('Unsupported wage contract type')
    world.typed(read, base, contract, kind)
    if world.pointer(read, contract + 8) != person:
        raise ValueError('Wage contract owner changed')
    if players.u64(read(vtable + 9 * 8, 8)) != base + 0xD8C3C0:
        raise ValueError('Weekly wage getter changed')
    amount = struct.unpack('<i', read(contract + 0x20, 4))[0]
    if amount < 0:
        raise ValueError('Unsupported negative weekly wage')
    return {'amount': amount, 'currency': currency or base_currency(read, base), 'period': 'week',
            'state': 'decoded', 'evidence': 'native_weekly_cash_field_and_base_currency'}
