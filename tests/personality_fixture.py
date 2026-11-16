"""Native person-rating fixture values and dispatch, independent of production constants."""
import struct


def populate(m, address, person_offset=0x388):
    table = int.from_bytes(m['read'](address + person_offset, 8), 'little')
    for slot, getter in ((176, 0xCF615C), (177, 0xCF617C), (178, 0xCF619C), (180, 0xCF61BC),
                         (181, 0xCF61DC), (182, 0xCF61FC), (183, 0xCF621C), (184, 0xCF623C)):
        m['q'](table + slot*8, m['base'] + getter)
        m['put'](table - (slot*8 + 16), struct.pack('<q', -0x110))
    m['put'](address + person_offset - 0xD0, bytes(range(11, 19)))


def populate_virtual(m):
    from fm_live_mcp import players, virtual
    table = m['base'] + virtual.PERSON_RVA
    for slot, getter in ((176, 0x18A6D10), (177, 0x18A6D94), (178, 0xD5C35C), (180, 0x18A6E8C),
                         (181, 0x18A6F14), (182, 0x18A6F60), (183, 0x18A6FE4), (184, 0x18A7068)):
        m['q'](table + slot*8, m['base'] + getter)
        m['put'](table - (slot*8 + 16), struct.pack('<q', -0x20 if slot != 178 else 0))
    m['put'](m['base'] + players.RVA[0] - 32, struct.pack('<q', 0x278))
    m['q'](0x1278, m['base'] + 0x5589A90)
    m['q'](m['base'] + 0x5589A90 + 75*8, m['base'] + 0xCF61D4)
