"""Bounded source3754/9 ACTUAL_PLAYER wire corroboration, never a whole record.

The raw64 direct-reference profile is conditional. This decoder neither binds
native loader globals nor assigns meanings to the skipped raw player values.
Native sources: CFD388/CFEFE4, 1526598, 17F1BB8/17F2FC8, 1576B28/1576D9C,
138E158/138E32C; B34 person_player, B36 player_continue/player_after_ring and
B43 ring_limit. A physical positive ring does not prove native loader acceptance.
"""
import struct

WIRE_PROFILE = 'source3754_global3754_minor9_raw64'
NATIVE_BUILD_SHA256 = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
_MAX_ROWS = 4096  # Offline work budget; not a native cardinality claim.


def prefix_probe(data, record_start, limit, *, include_ability=False, _child_readers=None):
    """Probe at an independently anchored tag, with an exclusive record bound.

    Invalid/truncated current-writer geometry raises ValueError. A positive
    unsupported subtree returns an explicit typed-prefix stop at its first
    unparsed byte. No result certifies a PERSON identity or a record boundary.
    Offsets use the caller's input coordinate system (bytes/mmap supported).
    """
    if type(include_ability) is not bool:
        raise ValueError('include_ability must be a boolean')
    if (type(record_start) is not int or type(limit) is not int or
            not 0 <= record_start < limit <= len(data)):
        raise ValueError('Invalid bounded ACTUAL_PLAYER span')
    at = record_start
    checks = []
    counts = {}

    def take(n):
        nonlocal at
        if n < 0 or n > limit - at:
            raise ValueError('Truncated ACTUAL_PLAYER prefix inside record bound')
        old = at
        at += n
        return old

    def number(code):
        return struct.unpack_from('<' + code, data, take(struct.calcsize('<' + code)))[0]

    def fixed(value, name):
        offset = at
        actual = number('B')
        if actual != value:
            raise ValueError(f'Unsupported current-writer {name} at {offset}')
        checks.append({'offset': offset, 'kind': name, 'value': actual})

    def presence(name):
        offset = at
        value = number('B')
        if value not in (0, 1):
            raise ValueError(f'Invalid current-writer {name} presence at {offset}')
        checks.append({'offset': offset, 'kind': name + '_presence', 'value': value})
        return value

    def stopped(native, reason):
        result = {'start': record_start, 'end': at, 'state': 'typed_prefix_stopped',
                'native_reader': '0xCFD388', 'next_native_reader': native,
                'stop_reason': reason, 'wire_profile': WIRE_PROFILE,
                'wire_profile_is_conditional': True, 'native_build_sha256': NATIVE_BUILD_SHA256,
                'validated_markers': checks, 'counts': counts,
                'complete_player_body': False, 'complete_person': False,
                'native_loader_acceptance': False, 'opaque_values_used_as_validation': False}
        if include_ability:
            # CFD388 reads native+256..25F first. PCAB/PPAB signed16 getters
            # select native+25C/+25E, hence body-relative wire offsets6/8.
            body_start = record_start + 1
            current, potential = struct.unpack_from('<hh', data, body_start + 6)
            result['ability'] = {
                'current_native_signed16': current, 'potential_native_signed16': potential,
                'body_start': body_start, 'current_source_offset': body_start + 6,
                'potential_source_offset': body_start + 8,
                'native_properties': {'current': 'PCAB', 'potential': 'PPAB'},
                'native_offsets': {'current': '0x25C', 'potential': '0x25E'},
                'encoding': 'signed16_little_endian',
            }
        return result

    def child(native, reason):
        nonlocal at
        callback = (_child_readers or {}).get(native)
        if callback is None:
            return stopped(native, reason)
        result = callback(data, at, limit)
        if (not isinstance(result, dict) or type(result.get('end')) is not int or
                not at < result['end'] <= limit):
            raise ValueError('Invalid bounded player prefix child cursor')
        if result.get('state') == 'stopped':
            at = result['end']
            return stopped(result.get('next_native_reader', native), result['stop_reason'])
        at = result['end']
        return None

    fixed(2, 'ACTUAL_PLAYER_tag')
    # 22 fixed bytes, explicit8-byte10FF49C transport,69 raw inputs,27 fixed bytes.
    take(126)
    measurement = number('B')
    # 1526598 selects legacy9B versus modern4B by unsigned marker<=1.
    take(8 if measurement <= 1 else 3)
    take(5)  # raw+244u32 and+265u8
    ring_offset = at
    ring_count = number('I')
    if ring_count > 12:
        raise ValueError('PLAYER ring exceeds native physical capacity12')
    take(ring_count + 4)  # Paired writer's ring bytes and following raw+230u32.
    counts['ring'] = ring_count
    checks.append({'offset': ring_offset, 'kind': 'physical_ring_count', 'value': ring_count})
    fixed(12, '17F1BB8_composite_version')  # writer literal53A25DE
    fixed(7, '17EDD50_parameter_version')  # writer literal53A2476
    take(9)
    if presence('position_history'):
        fixed(2, '15778F4_history_version')  # writer literal539DA95
        count = number('b')
        if count < 0:
            raise ValueError('Negative position-history count reaches native reserve failure')
        counts['position_history'] = count
        for _ in range(count):
            fixed(4, '1576B28_position_row_version')  # writer literal539DA94
            take(23)  # encoding byte and22 bytes of stored fields
    if presence('typed_vector'):
        gap = child('0x17F090C', 'positive_typed_vector_unparsed')
        if gap is not None:
            return gap
    count = number('i')
    if count < 0:
        raise ValueError('Negative pair count differs from current writer geometry')
    counts['pairs'] = count
    if count > _MAX_ROWS:
        return stopped('0x17F1E3C', 'pair_count_exceeds_offline_work_budget')
    take(count * 2)
    if presence('fixed_28'):
        gap = child('0x157E834', 'positive_fixed_28_unparsed')
        if gap is not None:
            return gap
    if presence('individual_training'):
        gap = child('0x1326EC4', 'positive_individual_training_unparsed')
        if gap is not None:
            return gap
    if presence('individual_oop_training'):
        gap = child('0x17F2174', 'positive_individual_oop_training_unparsed')
        if gap is not None:
            return gap
    fixed(2, '138E158_fixed_version')  # paired writer literal5396C4E
    take(16)
    take(30)  # Version12 fixed tail fields, no semantic/range validation.
    return stopped('0x43836A4', 'player_e8_string_and_remaining_body_unparsed')
