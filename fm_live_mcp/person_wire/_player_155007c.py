"""155007C collection in the observed full-loader tagged-reference subset.

F0 forces local2C98=1. Row15505D8 asks11019A0 for mode4, not mode3.
Two TEAM transports are marker0+u32; PERSON1104FB0 is rawu32 in this
full-loader branch. Loader globals remain unbound: no canonical identities.
"""
import struct
PROFILE = 'full_loader_tagged_team_index32_person_index32'

def parse(data, start, *, source_major=3754, minor=9, reference_profile=PROFILE, max_rows=4096, max_items=32768):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported155007C source')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid155007C cursor')
    if reference_profile != PROFILE:
        raise ValueError('Unsupported155007C conditional reference profile')
    if type(max_rows) is not int or not 0 <= max_rows <= 4096 or type(max_items) is not int or (not 0 <= max_items <= 32768):
        raise ValueError('Invalid155007C offline work budget')
    at = start
    work = 0

    def take(n):
        nonlocal at
        if n < 0 or n > len(data) - at:
            raise ValueError(f'Truncated155007C at {at}')
        old = at
        at += n
        return bytes(data[old:at])

    def num(c):
        return struct.unpack('<' + c, take(struct.calcsize('<' + c)))[0]
    count = num('h')
    if count < 0:
        raise ValueError('Negative155007C count reaches native reserve overflow')
    if count > max_rows:
        raise ValueError('155007C offline row budget')
    rows = []
    for index in range(count):
        begin = at
        version = num('B')
        word = take(4)
        refs = []
        for _ in range(2):
            marker = num('B')
            if marker != 0:
                raise ValueError(f'Unsupported15505D8 TEAM transport marker{marker} at {at - 1}')
            refs.append({'marker': marker, 'raw_u32_hex': take(4).hex(), 'identity_resolved': False})
        person = take(4)
        raw34 = num('B')
        raw35 = num('B')
        nested = num('I')
        if nested > max_items - work:
            raise ValueError('155007C offline nested-item budget')
        if nested > (len(data) - at) // 11:
            raise ValueError('Truncated15505D8 fixed11 nested rows')
        work += nested
        items = []
        for _ in range(nested):
            p = at
            v = num('B')
            rawa = take(2)
            rawc = take(2)
            ref = take(4)
            raw8 = take(2)
            items.append({'start': p, 'end': at, 'version': v, 'raw_0a_u16_hex': rawa.hex(), 'raw_0c_u16_hex': rawc.hex(), 'raw_person_reference32_hex': ref.hex(), 'raw_08_u16_hex': raw8.hex(), 'identity_resolved': False})
        rows.append({'start': begin, 'end': at, 'version': version, 'raw_30_33_hex': word.hex(), 'team_references': refs, 'raw_person_reference32_hex': person.hex(), 'raw_34_u8': raw34, 'raw_35_u8': raw35, 'nested_count': nested, 'items': items})
    return {'start': start, 'end': at, 'count': count, 'rows': rows, 'nested_item_count': work, 'native_reader': '0x155007c', 'row_reader': '0x15505d8', 'row_writer': '0x154fdd0', 'reference_profile': reference_profile, 'reference_profile_is_conditional': True, 'native_loader_globals_observed': False, 'identities_resolved': False, 'semantic_fields_resolved': False, 'complete_supported_child_wire': True, 'pending_bytes': 0}
