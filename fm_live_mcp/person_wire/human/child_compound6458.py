"""Inline HUMAN12C6458..12C702C, paired12CEA90..12CED78.

The caller owns the signed outercount. Four u16-counted raw index-word vectors
and the two fixed raw words are independent of reference-width flags.
"""
import struct

def parse(data, start, *, count, limit=None, source_major=3754, minor=9, reference_context=None, max_items=65536):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported HUMAN compound source profile')
    if type(count) is not int or not -128 <= count <= 127:
        raise ValueError('HUMAN compound outercount must be native signed8')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid HUMAN compound extent')
    if type(max_items) is not int or not 0 <= max_items <= 1000000:
        raise ValueError('Invalid HUMAN compound work bound')
    at = start
    remaining = max_items
    rows = []

    def take(n):
        nonlocal at
        if n < 0 or n > bound - at:
            raise ValueError(f'Truncated HUMAN compound at{at}')
        begin = at
        at += n
        return data[begin:at]

    def number(code):
        return struct.unpack('<' + code, take(struct.calcsize('<' + code)))[0]
    for ordinal in range(max(count, 0)):
        begin = at
        team_word = number('I')
        vectors = []
        for field in (8, 32, 56, 80):
            count_start = at
            n = number('H')
            if n > remaining or n > (bound - at) // 4:
                raise ValueError('HUMAN compound vector exceeds work/input bound')
            remaining -= n
            values_start = at
            raw = take(n * 4)
            words = [value[0] for value in struct.iter_unpack('<I', raw)]
            vectors.append({'native_offset': hex(field), 'count_start': count_start, 'count': n, 'start': values_start, 'end': at, 'stored_words_u32': words, 'identity_namespace_resolved': False})
        tail_start = at
        tail = number('I')
        rows.append({'ordinal': ordinal, 'start': begin, 'end': at, 'team_word_u32': team_word, 'team_word_source_offset': begin, 'team_namespace': 'TEAM_BASE', 'team_identity_resolved': False, 'vectors': vectors, 'native_68_source_offset': tail_start, 'native_68_raw_u32': tail, 'native_68_raw_u16': tail & 65535, 'native_6a_raw_u16': tail >> 16})
    return {'start': start, 'end': at, 'outer_count_signed8': count, 'iterated_count': max(count, 0), 'rows': rows, 'complete_child_wire': True, 'native_continuation': '0x12c702c', 'reference_context_used_for_wire': False, 'native_pending_bytes': 0, 'runtime_globals_observed': False, 'vector_namespaces_resolved': False, 'team_lookup_conditions': 'negative/out-of-range word produces native null; lookup array selected by flag global56D2DB0+730'}
