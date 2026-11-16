"""Eight person ratings mapped through installed editor fields and PERSON getters."""
import struct

# PERSON_DATA byte offset, PERSON slot, getter RVA, editor property.
FIELDS = {
    'adaptability': (0x40, 176, 0xCF615C, 'Pada'),
    'ambition': (0x41, 177, 0xCF617C, 'Pamb'),
    'controversy': (0x47, 178, 0xCF619C, 'Pcvy'),
    'loyalty': (0x42, 180, 0xCF61BC, 'Ploy'),
    'pressure': (0x43, 181, 0xCF61DC, 'Ppre'),
    'professionalism': (0x44, 182, 0xCF61FC, 'Ppro'),
    'sportsmanship': (0x45, 183, 0xCF621C, 'Pspo'),
    'temperament': (0x46, 184, 0xCF623C, 'Ptem'),
}
VIRTUAL_GETTERS = {176: 0x18A6D10, 177: 0x18A6D94, 178: 0xD5C35C, 180: 0x18A6E8C,
                   181: 0x18A6F14, 182: 0x18A6F60, 183: 0x18A6FE4, 184: 0x18A7068}


def verify_getters(read, base, table, virtual=False):
    for _, slot, getter, _ in FIELDS.values():
        expected = VIRTUAL_GETTERS[slot] if virtual else getter
        if int.from_bytes(read(table + slot*8, 8), 'little') != base + expected:
            raise ValueError('Personality getter changed')
        if virtual and slot == 178:
            continue  # This getter returns constant zero without a data adjustment.
        adjustment = struct.unpack('<q', read(table - (slot*8 + 16), 8))[0]
        if adjustment != (-0x20 if virtual else -0x110):
            raise ValueError('Personality person-data adjustment changed')


def decode(read, base, raw, person_offset, virtual=False):
    table = int.from_bytes(raw[person_offset:person_offset + 8], 'little')
    verify_getters(read, base, table)
    result = {}
    for name, (offset, _, _, _) in FIELDS.items():
        # Virtual PERSON controversy is a native constant, not cached profile data.
        value = 0 if virtual and name == 'controversy' else raw[person_offset - 0x110 + offset]
        if value > 20:
            raise ValueError(f'Personality rating outside verified range: {name}')
        result[name] = value
    return result


def verify_virtual_cache(read, base, compact_table, cached):
    verify_getters(read, base, compact_table, virtual=True)
    primary = int.from_bytes(read(cached, 8), 'little')
    if struct.unpack('<q', read(primary - 32, 8))[0] != 0x278:
        raise ValueError('Virtual personality cache adjustment changed')
    data_table = int.from_bytes(read(cached + 0x278, 8), 'little')
    if int.from_bytes(read(data_table + 75*8, 8), 'little') != base + 0xCF61D4:
        raise ValueError('Virtual personality pressure getter changed')
