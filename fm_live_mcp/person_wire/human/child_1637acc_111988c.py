"""Nested SCOUTED_PERSON_TAG child+30 reference wire; no resolved identity.

163ADB4 supplies literal w4=1, independent of the inherited context's previous
call argument. Under the fixed HUMAN-local witness this selects direct32.
Runtime descriptor/switch values remain unobserved; context is caller evidence.
"""
CONTEXT = {'stream_flags': 2, 'root80a': 0, 'root80b': 1, 'switch3523': 1, 'local_c98': 1, 'w4': 0}

def effective_context(context):
    if not isinstance(context, dict) or set(context) != set(CONTEXT) or any((type(v) is not int or not 0 <= v <= 255 for v in context.values())):
        raise ValueError('Explicit native reference context bytes required')
    if context['local_c98'] != 1:
        raise ValueError('HUMAN parent forces local C98=1')
    return dict(context, w4=1)

def profile(context):
    c = effective_context(context)
    if not c['stream_flags'] & 2:
        return 'tagged16'
    if c['root80a'] & 1 or c['root80b'] & 1:
        return 'direct32'
    return 'compact16'

def parse(data, start, *, limit=None, source_major=3754, minor=9, reference_context=None):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Explicit3754/9 source profile required')
    mode = profile(reference_context)
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid bounded reference cursor')
    at = start

    def take(n):
        nonlocal at
        if n > bound - at:
            raise ValueError(f'Truncated111988C reference at{at}')
        raw = bytes(data[at:at + n])
        at += n
        return raw
    result = {'start': start, 'native_reader': '0x111988c', 'native_writer': '0x111e14c', 'descriptor_global': '0x56d2d18', 'descriptor_table_offset': '0x60', 'native_output_offset': 'child+0x30', 'inherited_context': dict(reference_context), 'effective_context': effective_context(reference_context), 'callsite_w4_override': 1, 'profile': mode, 'reference_identity_resolved': False, 'runtime_globals_observed': False}
    if mode == 'direct32':
        result.update(raw_unsigned_word=int.from_bytes(take(4), 'little'), state='unresolved_direct_transport')
    else:
        marker = take(1)[0] if mode == 'tagged16' else 0
        if mode == 'tagged16':
            result['marker'] = marker
            if marker not in (0, 4):
                raise ValueError('Current111E14C writer marker domain0/4')
        value = int.from_bytes(take(2), 'little', signed=True)
        result['raw_signed16'] = value
        if value == -1:
            result['state'] = 'native_null_sentinel'
        else:
            index = int.from_bytes(take(4), 'little', signed=True) if value == -2 else value
            if index < 0:
                raise ValueError('Native nonnull reference index is negative')
            result['raw_index'] = index
            result['state'] = 'unresolved_index_transport'
            if marker:
                result.update(raw_primary_word=int.from_bytes(take(4), 'little'), raw_secondary_word=int.from_bytes(take(4), 'little'))
    result.update(end=at, raw_hex=bytes(data[start:at]).hex())
    return result
