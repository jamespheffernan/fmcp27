"""Read native contract dates, preserving fixed versus computed expiry semantics."""
import struct

from . import players, world


def dynamic_expiry(raw):
    """Reproduce slot 30's packed-date calculation without executing game code."""
    world.packed_date(raw)  # Reject invalid inputs before applying native arithmetic.
    packed = int.from_bytes(raw, 'little')
    year = (packed >> 16) + 1
    mask = 15 if (year * 0x5C29 & 0xFFFF) < 0xA3E else 3
    days = 366 if year & mask == 0 else 365
    low = (packed & 0xFE00) | days if days == (packed & 511) - 1 else packed
    return world.packed_date(((low & 0xFFFF) | (year << 16)).to_bytes(4, 'little'))


def decode(read, base, person):
    """PERSON points to the shared subobject, not the primary player/staff object."""
    table = world.pointer(read, person)
    if (players.u64(read(table + 121 * 8, 8)) != base + 0xCB3724
            or struct.unpack('<q', read(table - 0x3D8, 8))[0] != -0x110):
        raise ValueError('Contract pointer getter changed')
    contract = players.u64(read(person - 0x98, 8))
    result = {'joined': None, 'last_signed': None, 'expires': None}
    if not contract:
        return {**result, 'state': 'no_contract', 'evidence': 'null_native_contract'}
    vtable = world.pointer(read, contract)
    kind = next((k for k in ('full_contract', 'basic_contract')
                 if vtable == base + world.TYPES[k][0]), None)
    if kind is None:
        raise ValueError('Unsupported contract date type')
    world.typed(read, base, contract, kind)
    if world.pointer(read, contract + 8) != person:
        raise ValueError('Contract date owner changed')
    if (players.u64(read(table + 73 * 8, 8)) != base + 0xCA4764
            or struct.unpack('<q', read(table - 0x258, 8))[0] != -0x110):
        raise ValueError('Date joined getter changed')
    result['joined'] = world.packed_date(read(person - 0x24, 4))
    if kind == 'basic_contract':
        return {**result, 'state': 'basic_contract_fields_unavailable',
                'evidence': 'native_person_joined_date_basic_contract'}
    for slot, getter in ((29, 0x1005C68), (30, 0x12920F8)):
        if players.u64(read(vtable + slot * 8, 8)) != base + getter:
            raise ValueError('Contract date getter changed')
    result['last_signed'] = world.packed_date(read(contract + 0x44, 4))
    dynamic = bool(read(contract + 0x2B, 1)[0] & 8)
    if dynamic:
        anchor = read(base + world.CURRENT_DATE, 4)
        result['expiry_anchor_date'] = world.packed_date(anchor)
        result['expires'] = dynamic_expiry(anchor)
    else:
        result['expires'] = world.packed_date(read(contract + 0x48, 4))
    return {**result, 'state': 'dynamic_expiry' if dynamic else 'fixed_expiry',
            'evidence': 'native_person_and_full_contract_date_getters'}
