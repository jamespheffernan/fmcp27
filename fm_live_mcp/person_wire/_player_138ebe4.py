"""138EBE4 wrapper and modern generic47FD68C wire; raw values only."""
import struct

def parse(data, start, *, source_major=3754, minor=9, max_rows=4096):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported138EBE4 source')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid138EBE4 cursor')
    if type(max_rows) is not int or not 0 <= max_rows <= 4096:
        raise ValueError('Invalid138EBE4 offline row budget')
    at = start
    work = 0

    def take(n):
        nonlocal at
        if n < 0 or n > len(data) - at:
            raise ValueError(f'Truncated138EBE4 at {at}')
        p = at
        at += n
        return bytes(data[p:at])

    def num(code):
        return struct.unpack('<' + code, take(struct.calcsize('<' + code)))[0]

    def count():
        nonlocal work
        n = num('I')
        if n > max_rows - work:
            raise ValueError('138EBE4 offline aggregate row budget')
        work += n
        return n
    version = num('B')
    generic_version = num('B')
    if generic_version != 4:
        raise ValueError('Unsupported47FD68C generic version outside proved modern4 profile')
    n = count()
    rows = []
    if n > (len(data) - at) // 19:
        raise ValueError('Truncated47FD68C fixed19 rows')
    for i in range(n):
        p = at
        v = num('B')
        word = take(2)
        v2 = num('B')
        raw = take(11)
        value = take(4)
        rows.append({'start': p, 'end': at, 'version': v, 'raw_object00_u16_hex': word.hex(), 'second_version': v2, 'raw_object02_0c_hex': raw.hex(), 'raw_value_i32_hex': value.hex()})
    vectors = []
    for slot in range(6):
        p = at
        n = count()
        items = []
        if n > (len(data) - at) // 5:
            raise ValueError('Truncated47FD098 fixed5 rows')
        for i in range(n):
            q = at
            raw_byte = num('B')
            raw_word = take(4)
            items.append({'start': q, 'end': at, 'raw_u8': raw_byte, 'raw_u32_hex': raw_word.hex()})
        vectors.append({'native_offset': hex(slot * 32), 'start': p, 'end': at, 'count': n, 'items': items})
    date = take(4)
    flag = num('B') if version >= 2 else None
    return {'start': start, 'end': at, 'version': version, 'generic_version': generic_version, 'rows': rows, 'vectors': vectors, 'raw_d8_db_hex': date.hex(), 'raw_dc_u8': flag, 'aggregate_rows': work, 'native_reader': '0x138ebe4', 'generic_reader': '0x47fd68c', 'generic_writer': '0x4a7cc00', 'references_consumed': False, 'semantic_fields_resolved': False, 'complete_supported_child_wire': True, 'pending_bytes': 0}
