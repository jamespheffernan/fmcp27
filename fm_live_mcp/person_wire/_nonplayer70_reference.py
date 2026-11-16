"""111988C bounded wire forms; caller selects an explicit supported branch.

Do not infer ambient flags from byte fit. Parsed words are source transport,
never native pointers or resolved identities. Current source-writer-mode
convergence must be checked by the enclosing record's independent continuation.
"""
MODES = frozenset(('raw32', 'raw64', 'compact16', 'tagged16'))

def profile_for_context(context):
    keys = ('stream_flags', 'root_80a', 'root_80b', 'global_3523', 'global_2c98')
    if not isinstance(context, dict) or set(context) != set(keys) or any((type(context[k]) is not int or not 0 <= context[k] <= 255 for k in keys)):
        raise ValueError('Explicit111988C native context bytes required')
    if not context['stream_flags'] & 2:
        return 'tagged16'
    w4 = context['global_2c98'] ^ 1
    if not (context['root_80a'] & 1 or (w4 == 1 and context['root_80b'] & 1)):
        return 'compact16'
    return 'raw64' if context['global_3523'] == 1 and (not context['global_2c98'] & 1) else 'raw32'

def decode(data, start, *, mode):
    if type(mode) is not str or mode not in MODES:
        raise ValueError('Unsupported111988C wire mode')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid111988C cursor')
    at = start

    def take(n):
        nonlocal at
        if n > len(data) - at:
            raise ValueError(f'Truncated111988C at {at}:need{n}')
        out = bytes(data[at:at + n])
        at += n
        return out
    out = {'start': start, 'mode': mode, 'native_reader': '0x111988c', 'namespace': 'NATIONAL_TEAM_CONTAINER', 'references_resolved': False}
    if mode in ('raw32', 'raw64'):
        raw = take(4 if mode == 'raw32' else 8)
        out['raw_unsigned_word'] = int.from_bytes(raw, 'little')
        out['state'] = 'unresolved_direct_transport'
    else:
        tagged = take(1)[0] if mode == 'tagged16' else 0
        if mode == 'tagged16':
            out['tag_byte'] = tagged
        short = int.from_bytes(take(2), 'little', signed=True)
        out['raw_signed16'] = short
        if short == -1:
            out['state'] = 'native_null_sentinel'
        else:
            index = int.from_bytes(take(4), 'little', signed=True) if short == -2 else short
            out['raw_index'] = index
            if tagged:
                out['raw_primary_u32'] = int.from_bytes(take(4), 'little')
                out['raw_secondary_u32'] = int.from_bytes(take(4), 'little')
            if index < 0:
                raise ValueError('111988C rejects negative nonnull reference index')
            out['state'] = 'unresolved_index_transport'
    out['end'] = at
    out['raw_hex'] = bytes(data[start:at]).hex()
    return out

def make_reader(mode):
    if type(mode) is not str or mode not in MODES:
        raise ValueError('Unsupported111988C wire mode')

    def read(data, start, namespace, field):
        if namespace != 'NATIONAL_TEAM_CONTAINER' or field != '0':
            raise ValueError('Wrong111988C source namespace or field')
        return decode(data, start, mode=mode)
    return read

def validate_current_writer(result):
    if result['mode'] == 'tagged16' and result['tag_byte'] not in (0, 4):
        raise ValueError('111E14C current writer tag differs from0or4')

def writer_profile_for_context(context):
    keys = ('stream_flags', 'root_808', 'root_809', 'global_3521', 'global_2af8', 'global_2c98')
    if not isinstance(context, dict) or set(context) != set(keys) or any((type(context[k]) is not int or not 0 <= context[k] <= 255 for k in keys)):
        raise ValueError('Explicit111E14C writer context bytes required')
    if not context['stream_flags'] & 2:
        return 'tagged16'
    w3 = context['global_2c98'] ^ 1
    if not (context['root_808'] & 1 or (w3 == 1 and context['root_809'] & 1)):
        return 'compact16'
    return 'raw64' if context['global_2af8'] == 1 or (context['global_3521'] == 1 and (not context['global_2c98'] & 1)) else 'raw32'

def make_current_writer_reader(mode):
    native_reader = make_reader(mode)

    def read(data, start, namespace, field):
        result = native_reader(data, start, namespace, field)
        validate_current_writer(result)
        return result
    return read
