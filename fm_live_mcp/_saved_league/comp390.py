"""COMP_STATS base wire and concrete GAME dispatch:3BE2048 / paired3BE1E90.

No table values or semantic ranking are inferred. The caller supplies the
concrete factory and explicit typed-reference context.
"""
import struct

CTX = {'stream_bit1': True, 'global_3522': 0, 'global_3523': 1, 'global_2c98': 1}


class Unsupported390(ValueError):
    def __init__(self, native, offset, reason, partial=None):
        self.native, self.offset, self.partial = native, offset, partial
        super().__init__(f'Unsupported COMP_STATS child {hex(native)} at {offset}: {reason}')


def parse(data, start, *, reference_context, owner_factory, embedded_reader,
          row_reader=None, suffix_reader=None, limit=None, max_rows=4096):
    if reference_context != CTX or any(type(reference_context.get(k)) is not type(v) for k, v in CTX.items()):
        raise ValueError('Explicit conditional COMP_STATS reference context required')
    if owner_factory not in ('comp_manager_base', 'game_comp_manager'):
        raise ValueError('Explicit COMP_MANAGER factory required')
    limit = len(data) if limit is None else limit
    if type(start) is not int or type(limit) is not int or not 0 <= start <= limit <= len(data):
        raise ValueError('Invalid bounded COMP_STATS input')
    if type(max_rows) is not int or not 0 <= max_rows <= 4096:
        raise ValueError('Invalid COMP_STATS row work budget')
    if not callable(embedded_reader):
        raise ValueError('Checked48ED3E0 callback required')
    at = start

    def checked_child(value, begin, native):
        if not isinstance(value, dict) or type(value.get('end')) is not int or not begin < value['end'] <= limit:
            raise ValueError('Invalid checked COMP_STATS child cursor')
        if value.get('state') == 'stopped' or any(value.get(key) is False for key in
                                                ('complete', 'full_child_complete', 'complete_row_wire')):
            next_native = value.get('next_native_reader', native)
            if isinstance(next_native, str):
                next_native = int(next_native, 16)
            raise Unsupported390(next_native, value['end'], 'Nested callback returned a partial wire result', value)
        return value

    def take(n):
        nonlocal at
        if n < 0 or n > limit - at:
            raise ValueError(f'Truncated COMP_STATS at {at}')
        old = at
        at += n
        return bytes(data[old:at])

    def number(fmt):
        return struct.unpack('<' + fmt, take(struct.calcsize('<' + fmt)))[0]

    def count(label):
        n = number('I')
        if n > max_rows:
            raise Unsupported390(0x3BE2048, at - 4, label + ' exceeds offline row budget')
        return n

    def team():
        #1101440(mode0) writes marker0 then original+8 index.11019A0(mode4)
        #under supplied flags reads this branch; marker2 would invoke11073A8.
        begin = at
        marker = number('B')
        if marker != 0:
            raise Unsupported390(0x11073A8 if marker == 2 else 0x11019A0, begin,
                                 'Only paired writer mode0 TEAM marker0 is supported')
        index = number('i')
        if index < -1:
            raise ValueError('Negative TEAM original index other than null')
        return {'start': begin, 'end': at, 'marker': marker, 'original_index': index,
                'raw_hex': bytes(data[begin:at]).hex(), 'resolved': False}

    def competition():
        #1101624(mode0) /1101BFC(mode0) uses11031C0 under supplied profile.
        begin = at
        short = number('h')
        index = number('i') if short == -2 else short
        if index < 0 and (short == -2 or index != -1):
            raise ValueError('Invalid compact COMP original index')
        return {'start': begin, 'end': at, 'short_marker': short, 'original_index': index,
                'raw_hex': bytes(data[begin:at]).hex(), 'resolved': False}

    version = number('i')
    if version != 173:
        raise Unsupported390(0x3BE2048, start, 'Only current paired writer version173 is supported')
    n = count('TEAM_COMP_STATS population')
    if n * 38 > limit - at:
        raise ValueError('COMP_STATS rows exceed bounded source extent')
    rows = []
    for ordinal in range(n):
        begin = at
        if owner_factory == 'game_comp_manager':
            if row_reader is None:
                raise Unsupported390(0xF36F0C, at,
                                     'GAME_TEAM_COMP_STATS virtual row reader is not implemented',
                                     {'version': version, 'row_count': n, 'row_ordinal': ordinal})
            value = checked_child(row_reader(data, at, limit=limit, version=version,
                                            reference_context=reference_context), at, 0xF36F0C)
            at = value['end']
            rows.append({'ordinal': ordinal, 'start': begin, 'end': at, 'decoded': value})
            continue
        first, second, comp = team(), team(), competition()
        raw6, raw16, raw4 = take(6), take(16), take(4)
        rows.append({'ordinal': ordinal, 'start': begin, 'end': at,
                     'team18': first, 'team20': second, 'competition28': comp,
                     'raw30_35': raw6.hex(), 'raw08_17': raw16.hex(),
                     'raw39_36_38_37': raw4.hex()})
    raw80b, raw80a = number('B'), number('B')
    embedded = []
    for native_offset in (8, 0x3E0):
        begin = at
        value = checked_child(embedded_reader(data, at, limit), at, 0x48ED3E0)
        at = value['end']
        embedded.append({'native_offset': hex(native_offset), 'start': begin, 'end': at, 'decoded': value})
    tail_count = count('COMP_STATS TEAM tail population')
    if tail_count * 5 > limit - at:
        raise ValueError('COMP_STATS TEAM tail exceeds bounded source extent')
    tail = [team() for _ in range(tail_count)]
    suffix = None
    if owner_factory == 'game_comp_manager':
        if suffix_reader is None:
            raise Unsupported390(0x171AA60, at,
                                 'GAME_COMP_STATS F39FC0 virtual suffix begins with unimplemented171AA60',
                                 {'version': version, 'row_count': n, 'embedded': embedded,
                                  'tail_team_count': tail_count, 'base_wire_end': at})
        suffix = checked_child(suffix_reader(data, at, limit=limit, version=version,
                                            reference_context=reference_context), at, 0xF39FC0)
        at = suffix['end']
    # Only base COMP_STATS VT56705E8+78=3BE234C returns without source reads.
    return {'start': start, 'end': at, 'version': version, 'rows': rows,
            'row_count': n, 'raw80b': raw80b, 'raw80a': raw80a,
            'embedded': embedded, 'tail_team_count': tail_count, 'tail_teams': tail, 'suffix': suffix,
            'native_reader': '0x3be2048', 'native_writer': '0x3be1e90',
            'complete_base_component_wire': True, 'reference_context': reference_context,
            'owner_factory': owner_factory, 'native_reference_profile_is_conditional': True,
            'references_resolved': False, 'standings_meanings_resolved': False}
