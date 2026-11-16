"""Proved conditional HUMAN11182BC NATION compact-index transport.

The caller's local C98=1 makes w4=0. Under stream bit1/root80A0, root80B
cannot select direct transport. These context bytes are a coherent source
profile, not observed runtime globals or canonical NATION membership.
"""
import struct
FIXED_CONTEXT = {'stream_flags': 2, 'root80a': 0, 'root80b': 1, 'switch3523': 1, 'local_c98': 1, 'w4': 0}

def parse(data, start, *, context):
    if not isinstance(context, dict) or set(context) != set(FIXED_CONTEXT) or any((type(v) is not int for v in context.values())):
        raise ValueError('Explicit native context bytes required')
    if not context['stream_flags'] & 2 or context['root80a'] & 1 or context['local_c98'] != 1 or (context['w4'] != 0):
        raise ValueError('Only proved Human compact16 context is accepted')
    if any((not 0 <= context[k] <= 255 for k in ('stream_flags', 'root80a', 'root80b', 'switch3523'))):
        raise ValueError('Invalid context byte')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid reference cursor')
    if len(data) - start < 2:
        raise ValueError('Truncated compact NATION marker')
    marker = struct.unpack_from('<h', data, start)[0]
    end = start + 2
    index = marker
    if marker == -2:
        if len(data) - end < 4:
            raise ValueError('Truncated extended compact NATION index')
        index = struct.unpack_from('<i', data, end)[0]
        end += 4
    if marker != -1 and index < 0:
        raise ValueError('Native negative nonnull NATION index failure')
    return {'start': start, 'end': end, 'namespace': 'NATION', 'native_reader': '0x11182bc', 'native_writer': '0x111d318', 'transport': 'compact16', 'initial_marker': marker, 'stored_index': None if marker == -1 else index, 'state': 'native_null' if marker == -1 else 'unresolved_original_index', 'canonical_membership_verified': False, 'raw_hex': bytes(data[start:end]).hex(), 'runtime_globals_observed': False, 'context': dict(context)}

def read(data, start):
    return parse(data, start, context=FIXED_CONTEXT)
