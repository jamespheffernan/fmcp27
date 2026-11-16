"""Bounded native wire readers for retained MATCH_STATS60/FIXTURE31.

Fields without a proved meaning are consumed only to validate complete sides.
No completion, playing-time or historical runtime dispatch is inferred.
"""

import struct


# Native wire segment: next-database-tables-and-match-payload-31/match_inner/parser.py

def fixture_prefix(data):
    at = 0

    def take(n):
        nonlocal at
        if n < 0 or at + n > len(data):
            raise ValueError('inner truncated')
        b = data[at:at + n]
        at += n
        return b

    def u(n):
        return int.from_bytes(take(n), 'little')

    def text():
        n = u(4)
        if n > 8192:
            raise ValueError('inner text budget')
        return take(n).decode('utf8')
    outer = u(2)
    entry = u(1)
    version = u(1)
    if (outer, entry, version) != (1, 1, 60):
        raise ValueError('unsupported framing')
    fixture_version = u(1)
    if fixture_version != 31:
        raise ValueError('unsupported fixture header')
    fields = {}
    for name, n in [('36', 2), ('41', 1), ('43', 1), ('42', 1), ('44', 1), ('38_minutes', 4), ('39_minutes', 4), ('30', 2), ('38', 1), ('39', 1), ('3a', 1), ('3b', 1), ('32', 2), ('3c', 1), ('3d', 1), ('3e', 1), ('3f', 1), ('40', 1), ('34', 2), ('45', 1), ('46', 1), ('47', 1)]:
        fields[name] = {'offset': at, 'raw': take(n).hex()}
    header_end = at

    def competition():
        start = at
        v = u(1)
        index = u(4)
        kind = u(1)
        words = [u(4) for _ in range(4)]
        extra = u(1)
        names = [text(), text()] if v >= 2 or kind == 4 else None
        return {'start': start, 'end': at, 'version': v, 'index_word': index, 'kind_byte': kind, 'words': words, 'extra_byte': extra, 'inline_names': names}
    comp = [competition(), competition()]
    start = at
    v = u(1)
    index = u(4)
    identity = u(4)
    name = text() if v >= 2 else None
    stadium = {'start': start, 'end': at, 'version': v, 'index_word': index, 'identity_word': identity, 'inline_name': name}

    def team():
        start = at
        v = u(1)
        mode = u(1)
        if v != 3 or mode != 2:
            raise ValueError('unsupported team reference profile')
        index = u(4)
        mode2 = u(1)
        if mode2 != 2:
            raise ValueError('unsupported second reference mode')
        identity = u(4)
        raw16 = u(2)
        kind = u(1)
        word_a = u(4)
        word_b = u(4)
        tail = u(1)
        return {'start': start, 'end': at, 'version': v, 'index_word': index, 'identity_word': identity, 'raw_u16': raw16, 'raw_byte': kind, 'word_a': word_a, 'word_b': word_b, 'tail_byte': tail}
    teams = [team(), team()]
    return {'outer_u16': outer, 'entry_marker': entry, 'MATCH_STATS_version': version, 'FIXTURE_version': fixture_version, 'header_end': header_end, 'header_fields': fields, 'competition_references': comp, 'fixture_field28_stadium_reference': stadium, 'fixture_fields8_10_team_references': teams, 'end': at, 'unparsed_bytes': len(data) - at}


# Native wire segment: next-database-tables-and-match-payload-31/match_inner/continuation/parser.py

def continue_fixture(data, start, person, extra):
    at = start
    fields = {}

    def take(n):
        nonlocal at
        if n < 0 or at + n > len(data):
            raise ValueError('truncated fixture continuation')
        b = data[at:at + n]
        at += n
        return b

    def u(n):
        return int.from_bytes(take(n), 'little')

    def child(fn):
        nonlocal at
        result = fn(data, at)
        end = result['end']
        if type(end) is not int or not at <= end <= len(data):
            raise ValueError('invalid child boundary')
        at = end
        return result
    fields['first_person'] = child(person)
    refs = []
    for _ in range(3):
        begin = at
        version = u(1)
        words = [u(4), u(4)]
        if version >= 2:
            n = u(4)
            if n > 8192:
                raise ValueError('flat reference name budget')
            name = take(n).decode('utf8')
        else:
            name = None
        refs.append({'start': begin, 'end': at, 'version': version, 'words': words, 'name': name})
    fields['flat_references'] = refs
    fields['second_person'] = child(person)
    flag_at = at
    flag = u(1)
    if flag != 1:
        raise ValueError('unsupported present-side FIXTURE profile')
    fields['side_presence'] = {'offset': flag_at, 'value': flag}
    fields['side_raw4'] = [take(4).hex(), take(4).hex()]
    fields['scalar_u32'] = [u(4) for _ in range(3)]
    fields['scalar_i8_raw'] = [u(1) for _ in range(4)]
    fields['scalar_u64'] = [u(8), u(8)]
    fields['extra'] = child(extra)
    return {'start': start, 'end': at, 'fields': fields, 'object': 'simatchshared::FIXTURE', 'pending_bytes': 0}

def stats_prefix(data, start):
    at = start
    fields = {}

    def u(n):
        nonlocal at
        if at + n > len(data):
            raise ValueError('truncated MATCH_STATS scalar prefix')
        value = int.from_bytes(data[at:at + n], 'little')
        at += n
        return value
    fields['stats_8_18_u32'] = [u(4) for _ in range(4)]
    fields['stats_20_byte'] = u(1)
    blocks = []
    for destination in (36, 40, 44, 48, 52):
        begin = at
        words = [u(4) for _ in range(4)]
        blocks.append({'offset': begin, 'native_destination': hex(destination), 'discarded_source_words': words[:3], 'stored_source_word': words[3]})
    fields['aggregate_blocks'] = blocks
    fields['stats_a8_u32'] = u(4)
    mode = u(1)
    if mode < 2:
        raise ValueError('unsupported legacy MATCH_STATS reference transport')
    fields['stats_a0_reference'] = {'mode': mode, 'word': u(4)}
    for destination, n in [('b6', 1), ('bb', 1), ('ac', 2), ('ae', 2), ('b0', 2), ('c9', 1)]:
        fields[destination] = u(n)
    return {'start': start, 'end': at, 'fields': fields, 'next_helper': '4943C40', 'next_destination': 'MATCH_STATS+68', 'MATCH_STATS_version': 60}


# Native wire segment: next-database-tables-and-match-payload-31/match_inner/person_helper/parser.py

def read_person(reader):
    """Consume one person reference; report only wire names/raw identity words.

    Reader provides offset and exact take(n). All native reads are immediate,
    so successful return has zero deferred bytes. Does not assign a match role.
    """
    start = reader.offset

    def take(n):
        value = reader.take(n)
        if len(value) != n:
            raise ValueError('Truncated person helper')
        return value

    def uint(n):
        return int.from_bytes(take(n), 'little')

    def text():
        length = uint(4)
        if length > 8192:
            raise ValueError('Person string exceeds bounded budget')
        return take(length).decode('utf-8', errors='strict')
    version = uint(1)
    if version != 11:
        raise ValueError('Unsupported person-reference version')
    references = []
    for _ in range(3):
        at = reader.offset
        mode = uint(1)
        if mode >= 2:
            value = uint(4)
        else:
            legacy = uint(8)
            if legacy == (1 << 64) - 1:
                value = (1 << 32) - 1
            elif legacy <= (1 << 32) - 2:
                value = legacy
            else:
                raise ValueError('Person legacy reference exceeds native uint32 domain')
        references.append({'offset': at, 'mode': mode, 'raw_word': value})
    payload_start = reader.offset
    names = [text() for _ in range(3)]
    fields = {}
    for field, width in (('41', 1), ('42', 1), ('20', 8), ('34', 4), ('scaled_source_word', 4), ('43', 1), ('28', 4), ('2c', 4), ('30', 4), ('38', 4), ('3c', 2), ('3e', 2), ('40', 1)):
        fields[field] = uint(width)
    return {'start': start, 'end': reader.offset, 'version': version, 'references_in_wire_order': references, 'payload_start': payload_start, 'stored_strings_in_wire_order': names, 'raw_fields': fields, 'pending_bytes': 0, 'next_native': 'return48F1F7C then48F1F24 to caller'}

def parse_person(data, start):
    if not isinstance(data, (bytes, bytearray, memoryview)) or type(start) is not int or (not 0 <= start <= len(data)):
        raise ValueError('Invalid person input/cursor')

    class Reader:
        offset = start

        def take(self, n):
            if type(n) is not int or n < 0 or n > len(data) - self.offset:
                raise ValueError('Truncated person helper')
            result = data[self.offset:self.offset + n]
            self.offset += n
            return result
    return read_person(Reader())
parse = parse_person


# Native wire segment: next-database-tables-and-match-payload-31/match_inner/fixture_extra/parser.py

def fixture_extra(data, offset, *, fixture_version=31, max_records=4096, destination_empty=True):
    if type(offset) is not int or offset < 0 or type(fixture_version) is not int or (not 0 <= fixture_version <= 255):
        raise ValueError('Invalid fixture-extra cursor/version')
    if type(max_records) is not int or max_records < 0:
        raise ValueError('Invalid fixture-extra implementation budget')
    if destination_empty is not True:
        raise ValueError('Native fixture-extra reader requires an empty destination vector')
    start = offset

    def take(n):
        nonlocal offset
        if n < 0 or offset + n > len(data):
            raise ValueError('Truncated fixture-extra vector')
        raw = bytes(data[offset:offset + n])
        offset += n
        return raw
    count = struct.unpack('<I', take(4))[0]
    signed_version = fixture_version - 256 if fixture_version >= 128 else fixture_version
    width = 8 if signed_version < 26 else 12 if signed_version == 26 else 16
    if count >= 134217728:
        raise ValueError('Pinned native fixture-extra count guard rejected')
    if count > max_records:
        raise ValueError('Fixture-extra record implementation budget exceeded')
    if count * width > len(data) - offset:
        raise ValueError('Truncated fixture-extra records')
    records = []
    for index in range(count):
        at = offset
        native = bytearray(b'\xff' * 13 + b'\x00' * 3)
        if signed_version < 26:
            native[0:4] = take(4)
            native[12:16] = take(4)
            fields = (0, 12)
        elif signed_version == 26:
            native[0:8] = take(8)
            native[12:16] = take(4)
            fields = (0, 4, 12)
        else:
            native[:] = take(16)
            fields = (0, 4, 8, 12)
        records.append({'index': index, 'start': at, 'end': offset, 'wire_hex': bytes(data[at:offset]).hex(), 'native_16_hex': native.hex(), 'raw_u32_words': list(struct.unpack('<4I', native)), 'source_field_offsets': list(fields), 'native_default_field_offsets': [i for i in (0, 4, 8, 12) if i not in fields]})
    return {'start': start, 'end': offset, 'count': count, 'fixture_version': fixture_version, 'native_signed_version': signed_version, 'wire_record_width': width, 'native_record_width': 16, 'records': records, 'native_callback_return': '0x4acc654', 'native_continuation': '0x4acc680', 'state': 'decoded_opaque_fixture_extra_vector', 'field_meanings': None, 'max_records_implementation_budget': max_records}


# Native wire segment: next-database-tables-and-match-payload-31/match_inner/side_stats/parser.py

SPEC = [{'native': '0x49440e4', 'offset': '0x1f0', 'width': 4}, {'native': '0x49440fc', 'offset': '0x1f4', 'width': 4}, {'native': '0x4944114', 'offset': '0x1f8', 'width': 4}, {'native': '0x494412c', 'offset': '0x1fc', 'width': 4}, {'native': '0x4944144', 'offset': '0x200', 'width': 4}, {'native': '0x494415c', 'offset': '0x204', 'width': 4}, {'native': '0x4944174', 'offset': '0x208', 'width': 4}, {'native': '0x494418c', 'offset': '0x20c', 'width': 4}, {'native': '0x49441a4', 'offset': '0x210', 'width': 4}, {'native': '0x49441bc', 'offset': '0x214', 'width': 4}, {'native': '0x49441d4', 'offset': '0x218', 'width': 4}, {'native': '0x49441ec', 'offset': '0x21c', 'width': 4}, {'native': '0x4944204', 'offset': '0x220', 'width': 4}, {'native': '0x494421c', 'offset': '0x224', 'width': 4}, {'native': '0x4944234', 'offset': '0x228', 'width': 4}, {'native': '0x494424c', 'offset': '0x22c', 'width': 4}, {'native': '0x4944264', 'offset': '0x230', 'width': 4}, {'native': '0x494427c', 'offset': '0x234', 'width': 4}, {'native': '0x4944294', 'offset': '0x238', 'width': 4}, {'native': '0x49442ac', 'offset': '0x23c', 'width': 4}, {'native': '0x49442c4', 'offset': '0x240', 'width': 4}, {'native': '0x49442dc', 'offset': '0x244', 'width': 4}, {'native': '0x49442f4', 'offset': '0x248', 'width': 4}, {'native': '0x494430c', 'offset': '0x24c', 'width': 4}, {'native': '0x4944324', 'offset': '0x171', 'width': 1}, {'native': '0x494433c', 'offset': '0x172', 'width': 1}, {'native': '0x4944354', 'offset': '0x173', 'width': 1}, {'native': '0x494436c', 'offset': '0x174', 'width': 1}, {'native': '0x4944384', 'offset': '0x175', 'width': 1}, {'native': '0x494439c', 'offset': '0x176', 'width': 1}, {'native': '0x49443b4', 'offset': '0x177', 'width': 1}, {'native': '0x49443cc', 'offset': '0x17a', 'width': 1}, {'native': '0x49443e4', 'offset': '0x17b', 'width': 1}, {'native': '0x49443fc', 'offset': '0x17c', 'width': 1}, {'native': '0x4944414', 'offset': '0x17d', 'width': 1}, {'native': '0x494442c', 'offset': '0x17e', 'width': 1}, {'native': '0x4944444', 'offset': '0x17f', 'width': 1}, {'native': '0x494445c', 'offset': '0x180', 'width': 1}, {'native': '0x4944474', 'offset': '0x181', 'width': 1}, {'native': '0x494448c', 'offset': '0x182', 'width': 1}, {'native': '0x49444a4', 'offset': '0x19c', 'width': 1}, {'native': '0x49444bc', 'offset': '0x19d', 'width': 1}, {'native': '0x49444d4', 'offset': '0x19e', 'width': 1}, {'native': '0x49444ec', 'offset': '0x19f', 'width': 1}, {'native': '0x4944504', 'offset': '0x1a0', 'width': 1}, {'native': '0x494451c', 'offset': '0x1a1', 'width': 1}, {'native': '0x4944534', 'offset': '0x1a2', 'width': 1}, {'native': '0x494454c', 'offset': '0x1a3', 'width': 1}, {'native': '0x4944564', 'offset': '0x190', 'width': 1}, {'native': '0x494457c', 'offset': '0x191', 'width': 1}, {'native': '0x4944594', 'offset': '0x192', 'width': 1}, {'native': '0x49445ac', 'offset': '0x193', 'width': 1}, {'native': '0x49445c4', 'offset': '0x194', 'width': 1}, {'native': '0x49445dc', 'offset': '0x195', 'width': 1}, {'native': '0x49445f4', 'offset': '0x196', 'width': 1}, {'native': '0x494460c', 'offset': '0x197', 'width': 1}, {'native': '0x4944624', 'offset': '0x198', 'width': 1}, {'native': '0x494463c', 'offset': '0x199', 'width': 1}, {'native': '0x4944654', 'offset': '0x19a', 'width': 1}, {'native': '0x494466c', 'offset': '0x19b', 'width': 1}, {'native': '0x4944684', 'offset': '0xd8', 'width': 2}, {'native': '0x494469c', 'offset': '0xda', 'width': 2}, {'native': '0x49446b4', 'offset': '0xdc', 'width': 2}, {'native': '0x49446cc', 'offset': '0xde', 'width': 2}, {'native': '0x49446e4', 'offset': '0xe0', 'width': 2}, {'native': '0x49446fc', 'offset': '0xe4', 'width': 2}, {'native': '0x4944714', 'offset': '0xe6', 'width': 2}, {'native': '0x494472c', 'offset': '0xea', 'width': 2}, {'native': '0x4944744', 'offset': '0x7c', 'width': 4}, {'native': '0x494475c', 'offset': '0x90', 'width': 4}, {'native': '0x4944774', 'offset': '0xa4', 'width': 4}, {'native': '0x494478c', 'offset': '0xb8', 'width': 4}, {'native': '0x49447a4', 'offset': '0x80', 'width': 4}, {'native': '0x49447bc', 'offset': '0x94', 'width': 4}, {'native': '0x49447d4', 'offset': '0xa8', 'width': 4}, {'native': '0x49447ec', 'offset': '0xbc', 'width': 4}, {'native': '0x4944804', 'offset': '0x84', 'width': 4}, {'native': '0x494481c', 'offset': '0x98', 'width': 4}, {'native': '0x4944834', 'offset': '0xac', 'width': 4}, {'native': '0x494484c', 'offset': '0xc0', 'width': 4}, {'native': '0x4944864', 'offset': '0x88', 'width': 4}, {'native': '0x494487c', 'offset': '0x9c', 'width': 4}, {'native': '0x4944894', 'offset': '0xb0', 'width': 4}, {'native': '0x49448ac', 'offset': '0xc4', 'width': 4}, {'native': '0x49448c4', 'offset': '0x8c', 'width': 4}, {'native': '0x49448dc', 'offset': '0xa0', 'width': 4}, {'native': '0x49448f4', 'offset': '0xb4', 'width': 4}, {'native': '0x494490c', 'offset': '0xc8', 'width': 4}, {'native': '0x4944924', 'offset': '0x184', 'width': 2}, {'native': '0x494493c', 'offset': '0x18a', 'width': 2}, {'native': '0x4944954', 'offset': '0x186', 'width': 2}, {'native': '0x494496c', 'offset': '0x18c', 'width': 2}, {'native': '0x4944984', 'offset': '0x188', 'width': 2}, {'native': '0x494499c', 'offset': '0x18e', 'width': 2}, {'native': '0x49449b4', 'offset': '0x14e', 'width': 1}, {'native': '0x49449d4', 'offset': '0x151', 'width': 1}, {'native': '0x49449ec', 'offset': '0x14f', 'width': 1}, {'native': '0x4944a10', 'offset': '0x152', 'width': 1}, {'native': '0x4944a28', 'offset': '0x150', 'width': 1}, {'native': '0x4944a48', 'offset': '0x153', 'width': 1}, {'native': '0x4944a60', 'offset': '0x4', 'width': 4}, {'native': '0x4944a9c', 'offset': '0xc', 'width': 4}, {'native': '0x4944ad8', 'offset': '0x28', 'width': 4}, {'native': '0x4944b14', 'offset': '0x30', 'width': 4}, {'native': '0x4944b50', 'offset': '0x34', 'width': 4}, {'native': '0x4944b8c', 'offset': '0x38', 'width': 4}, {'native': '0x4944bc8', 'offset': '0x3c', 'width': 4}, {'native': '0x4944c04', 'offset': '0x40', 'width': 4}, {'native': '0x4944c40', 'offset': '0x8', 'width': 4}, {'native': '0x4944c7c', 'offset': '0x2c', 'width': 4}, {'native': '0x4944cb8', 'offset': '0x10', 'width': 4}, {'native': '0x4944cf4', 'offset': '0x14', 'width': 4}, {'native': '0x4944d30', 'offset': '0x18', 'width': 4}, {'native': '0x4944d6c', 'offset': '0x1c', 'width': 4}, {'native': '0x4944da8', 'offset': '0x20', 'width': 4}, {'native': '0x4944de4', 'offset': '0x44', 'width': 4}, {'native': '0x4944e20', 'offset': '0x24', 'width': 4}, {'native': '0x4944e5c', 'offset': '0x48', 'width': 4}, {'native': '0x4944e98', 'offset': '0x4c', 'width': 4}, {'native': '0x4944ed4', 'offset': '0x50', 'width': 4}, {'native': '0x4944f10', 'offset': '0x54', 'width': 4}, {'native': '0x4944f4c', 'offset': '0x58', 'width': 4}, {'native': '0x4944f88', 'offset': '0x1a9', 'width': 1}, {'native': '0x4944fa0', 'offset': '0xec', 'width': 2}, {'native': '0x4944fb8', 'offset': '0x102', 'width': 2}, {'native': '0x4944fd0', 'offset': '0xee', 'width': 2}, {'native': '0x4944fe8', 'offset': '0x104', 'width': 2}, {'native': '0x4945000', 'offset': '0xf0', 'width': 2}, {'native': '0x4945018', 'offset': '0x106', 'width': 2}, {'native': '0x4945030', 'offset': '0xf2', 'width': 2}, {'native': '0x4945048', 'offset': '0x108', 'width': 2}, {'native': '0x4945060', 'offset': '0xf4', 'width': 2}, {'native': '0x4945078', 'offset': '0x10a', 'width': 2}, {'native': '0x4945090', 'offset': '0xf6', 'width': 2}, {'native': '0x49450a8', 'offset': '0x10c', 'width': 2}, {'native': '0x49450c0', 'offset': '0xf8', 'width': 2}, {'native': '0x49450d8', 'offset': '0x10e', 'width': 2}, {'native': '0x49450f0', 'offset': '0xfa', 'width': 2}, {'native': '0x4945108', 'offset': '0x110', 'width': 2}, {'native': '0x4945120', 'offset': '0xfc', 'width': 2}, {'native': '0x4945138', 'offset': '0x112', 'width': 2}, {'native': '0x4945150', 'offset': '0xfe', 'width': 2}, {'native': '0x4945168', 'offset': '0x114', 'width': 2}, {'native': '0x4945180', 'offset': '0x100', 'width': 2}, {'native': '0x4945198', 'offset': '0x116', 'width': 2}, {'native': '0x49451b0', 'offset': '0xcc', 'width': 4}]

def side_prefix(data, start, *, version=60):
    if version != 60:
        raise ValueError('Unsupported side statistics version')
    c = start
    fields = {}

    def take(n):
        nonlocal c
        if not isinstance(c, int) or c < 0 or c + n > len(data):
            raise ValueError('Truncated side statistics')
        b = data[c:c + n]
        c += n
        return b

    def u(n):
        return int.from_bytes(take(n), 'little')
    mode = u(1)
    if mode not in (0, 1, 2):
        raise ValueError('Unsupported reference mode')
    if mode < 2:
        raw = u(8)
        if raw not in (18446744073709551615,) and raw > 4294967294:
            raise ValueError('Wide reference overflow')
    else:
        raw = u(4)
    fields['0x5c_raw_reference'] = raw
    children = u(1)
    for off in range(352, 366):
        fields[hex(off)] = u(1)
    fields['0x60_float_raw'] = take(4).hex()
    for off in (351, 367, 368):
        fields[hex(off)] = u(1)
    for off in ('0x1c0', '0x1d8'):
        fields[off] = [{'key': u(2), 'value': u(1)} for _ in range(u(1))]
    for item in SPEC:
        fields[item['offset']] = take(item['width']).hex()
    mode2 = u(1)
    if mode2 not in (0, 1, 2):
        raise ValueError('Unsupported reference mode')
    if mode2 < 2:
        raw = u(8)
        if raw != 18446744073709551615 and raw > 4294967294:
            raise ValueError('Wide reference overflow')
    else:
        raw = u(4)
    fields['0xd0_raw_reference'] = raw
    for off in (280, 282, 284, 286):
        fields[hex(off)] = u(2)
    return {'start': start, 'end': c, 'fields': fields, 'child_count': children, 'native_stop': '0x49452c0', 'complete': False}
TAIL_SPEC = [{'native': '0x49453e4', 'width': 1}, {'native': '0x49453fc', 'width': 1}, {'native': '0x4945414', 'width': 1}, {'native': '0x494542c', 'width': 1}, {'native': '0x4945444', 'width': 1}, {'native': '0x494545c', 'width': 1}, {'native': '0x4945474', 'width': 1}, {'native': '0x494548c', 'width': 1}, {'native': '0x49454a4', 'width': 1}, {'native': '0x49454bc', 'width': 1}, {'native': '0x49454d4', 'width': 1}, {'native': '0x49454ec', 'width': 1}, {'native': '0x4945504', 'width': 1}, {'native': '0x494551c', 'width': 1}, {'native': '0x4945534', 'width': 1}, {'native': '0x494554c', 'width': 1}, {'native': '0x4945564', 'width': 1}, {'native': '0x494557c', 'width': 1}, {'native': '0x4945594', 'width': 1}, {'native': '0x49455ac', 'width': 1}, {'native': '0x49455c4', 'width': 1}, {'native': '0x49455dc', 'width': 1}, {'native': '0x49455f4', 'width': 1}, {'native': '0x494560c', 'width': 2}, {'native': '0x4945624', 'width': 2}, {'native': '0x494563c', 'width': 2}, {'native': '0x4945654', 'width': 2}, {'native': '0x494566c', 'width': 2}, {'native': '0x4945684', 'width': 2}, {'native': '0x494569c', 'width': 2}, {'native': '0x49456b4', 'width': 2}, {'native': '0x49456cc', 'width': 2}, {'native': '0x49456e4', 'width': 2}, {'native': '0x49456fc', 'width': 2}, {'native': '0x4945714', 'width': 2}, {'native': '0x494572c', 'width': 2}, {'native': '0x4945744', 'width': 2}, {'native': '0x494575c', 'width': 2}, {'native': '0x4945774', 'width': 2}, {'native': '0x494578c', 'width': 2}, {'native': '0x49457a4', 'width': 2}, {'native': '0x49457bc', 'width': 2}, {'native': '0x49457d4', 'width': 2}, {'native': '0x49457ec', 'width': 4}, {'native': '0x494580c', 'width': 2}, {'native': '0x4945824', 'width': 2}, {'native': '0x494583c', 'width': 2}, {'native': '0x4945854', 'width': 4}, {'native': '0x4945874', 'width': 4}, {'native': '0x49458b4', 'width': 2}, {'native': '0x49458d4', 'width': 2}, {'native': '0x49458f4', 'width': 4}, {'native': '0x4945914', 'width': 4}, {'native': '0x494593c', 'width': 4}]

def side(data, start, *, version=60, parse_child=None, parse_collection=None):
    result = side_prefix(data, start, version=version)
    c = result['end']
    children = []

    def checked(callback, label):
        nonlocal c
        if callback is None:
            raise ValueError('Unsupported ' + label + ' at ' + str(c))
        r = callback(data, c, version=version)
        if not isinstance(r, dict) or not isinstance(r.get('end'), int) or (not c < r['end'] <= len(data)):
            raise ValueError('Invalid ' + label + ' cursor')
        c = r['end']
        return r
    for _ in range(result['child_count']):
        children.append(checked(parse_child, 'side child'))
    if c + 5 > len(data):
        raise ValueError('Truncated side post-child bytes')
    post_child = data[c:c + 5].hex()
    c += 5
    collection = checked(parse_collection, 'side collection')
    tail = []
    for item in TAIL_SPEC:
        n = item['width']
        if c + n > len(data):
            raise ValueError('Truncated side tail')
        tail.append({'native': item['native'], 'raw': data[c:c + n].hex()})
        c += n
    result.update({'end': c, 'complete': True, 'children': children, 'post_child_raw': post_child, 'collection': collection, 'tail': tail, 'native_stop': '0x4945958'})
    return result


# Native wire segment: next-database-tables-and-match-payload-31/match_inner/side_children/parser.py

class PlayerReader:

    def __init__(self, data, start):
        if not isinstance(start, int) or start < 0 or start > len(data):
            raise ValueError('start')
        self.data = data
        self.pos = start

    def take(self, n):
        if n < 0 or n > len(self.data) - self.pos:
            raise ValueError(f'truncated at {self.pos}: {n}')
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def u8(self):
        return self.take(1)[0]

    def ref(self):
        tag = self.u8()
        raw = self.take(4 if tag >= 2 else 8)
        value = int.from_bytes(raw, 'little')
        if tag < 2 and value != 18446744073709551615 and (value > 4294967294):
            raise ValueError(f'native reference overflow at {self.pos - len(raw) - 1}')
        return {'tag': tag, 'raw': raw.hex()}

def player_base(data, start, *, version=60):
    if version != 60:
        raise ValueError('unsupported parent version')
    r = PlayerReader(data, start)
    ref = r.ref()
    widths = (2, 5, 5, 8, 4, 4, 4, 4, 12, 2, 1, 15, 5, 4, 6, 3, 3, 3, 2, 2, 1, 1, 8, 5, 8, 5, 8)
    for n in widths:
        r.take(n)
    for n in (1, 4, 4, 16, 4, 12, 9, 6, 4, 4, 2, 2, 2, 2, 2, 2, 4, 1):
        r.take(n)
    groups = r.u8()
    nested = 0
    for _ in range(groups):
        r.take(2)
        count = r.u8()
        nested += count
        if nested > 10000:
            raise ValueError('nested work bound')
        r.take(15 * count)
    r.take(1 + 2 + 1)
    return {'accepted_source_boundary': False, 'start': start, 'end': r.pos, 'version': version, 'reference': ref, 'group_count': groups, 'nested_count': nested, 'native_reader': '0x4ad2910', 'dispatch': 'default 0x56a23a8; runtime override not asserted'}

def player(data, start, *, version=60, stream_bit1=True):
    if stream_bit1 is not True:
        raise ValueError('unsupported concrete child stream flag: preceding1104FB0 transport')
    base = player_base(data, start, version=version)
    r = PlayerReader(data, base['end'])
    presence = r.u8()
    extra = r.take(11).hex() if presence == 1 else None
    return {**base, 'accepted_source_boundary': True, 'base_end': base['end'], 'end': r.pos, 'native_reader': '0x2e8c990', 'presence': presence, 'optional_raw': extra, 'dispatch': 'registered concrete vtable0x55fa800, stream bit1 set'}


# Native wire segment: saved-person-and-match-decoding-34/match_collections/parser.py

class CollectionReader:

    def __init__(self, data, start):
        if not isinstance(start, int) or start < 0 or start > len(data):
            raise ValueError('invalid start')
        self.data = data
        self.pos = start
        self.work = 0

    def take(self, n):
        if n < 0 or n > len(self.data) - self.pos:
            raise ValueError(f'truncated at{self.pos} need{n}')
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def u(self, n):
        return int.from_bytes(self.take(n), 'little')

    def i(self, n):
        return int.from_bytes(self.take(n), 'little', signed=True)

    def count(self, n, signed=False):
        v = self.i(n) if signed else self.u(n)
        self.work += max(v, 0)
        if self.work > 10000:
            raise ValueError('collection work bound')
        return v

    def ref(self):
        marker = self.u(1)
        raw = self.u(4 if marker >= 2 else 8)
        if marker < 2 and raw != 18446744073709551615 and (raw > 4294967294):
            raise ValueError('native reference overflow')
        return {'marker': marker, 'raw': raw}

def member(r, version):
    if version != 9:
        raise ValueError('unsupported nested member parent version')
    start = r.pos
    reference = r.ref()
    fields = {}
    for offset, width in ((0, 4), (4, 4), (8, 8), (16, 8), (36, 4)):
        fields[hex(offset)] = r.take(width).hex()
    reference2 = r.ref()
    fields['0x28'] = r.take(4).hex()
    fields['0x2d'] = r.take(1).hex()
    marker = r.u(1)
    fields['0x20'] = r.take(4).hex()
    fields['0x2e'] = r.take(1).hex()
    fields['0x2f'] = r.take(1).hex()
    return {'start': start, 'end': r.pos, 'reference18': reference, 'reference1c': reference2, 'marker20': marker, 'fields': fields}

def metadata(r):
    start = r.pos
    version = r.u(1)
    refs = [r.ref() for _ in range(4)]
    legacy = r.u(1) if version <= 1 else None
    count = r.count(4, True)
    groups = []
    for _ in range(max(count, 0)):
        key = r.u(1)
        n = r.count(4, True)
        words = [r.u(4) for _ in range(max(n, 0))]
        groups.append({'key': key, 'count': n, 'words': words})
    return {'start': start, 'end': r.pos, 'version': version, 'references': refs, 'legacy_byte': legacy, 'count': count, 'groups': groups}

def item(r):
    start = r.pos
    version = r.u(1)
    if version != 9:
        raise ValueError(f'unsupported item saved version{version} at{start}')
    count = r.count(1, True)
    if count < 0:
        raise ValueError('negative native member count rejects item')
    members = [member(r, version) for _ in range(count)]
    raw_i32 = r.i(4)
    refs = [r.ref() for _ in range(3)]
    raw74 = r.u(1)
    raw70 = r.u(2)
    meta = metadata(r)
    raw73 = r.u(1)
    raw6c = r.u(4)
    marker = r.u(1)
    tail = [r.take(n).hex() for n in (8, 8, 4, 1)]
    return {'start': start, 'end': r.pos, 'saved_version': version, 'member_count': count, 'members': members, 'raw_i32': raw_i32, 'native_scaled_i64': raw_i32 * 60000, 'references': refs, 'raw74': raw74, 'raw70': raw70, 'metadata': meta, 'raw73': raw73, 'raw6c': raw6c, 'tail_marker': marker, 'tail': tail}

def collection(data, start, *, version=60):
    if version != 60:
        raise ValueError('unsupported enclosing side version')
    r = CollectionReader(data, start)
    marker = r.u(1)
    count = r.count(4)
    rows = [item(r) for _ in range(count)]
    return {'start': start, 'end': r.pos, 'marker': marker, 'count': count, 'rows': rows, 'native_reader': '0x4984780', 'native_item_reader': '0x4ae32d8'}
