"""138EEE4 bounded signed-count vector; inherited conditional full-loader references."""
import struct
RAW64 = {'stream_bit1': True, 'global_3522': 0, 'global_3523': 1, 'global_2c98': 0}
RAW32 = {**RAW64, 'global_2c98': 1}

def parse(data, start, *, source_major=3754, minor=9, limit=None, reference_context=RAW64, max_rows=32767):
    if (source_major, minor) != (3754, 9) or reference_context not in (RAW64, RAW32):
        raise ValueError('Unsupported explicit source/reference context')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid child bounds')
    if type(max_rows) is not int or not 0 <= max_rows <= 32767:
        raise ValueError('Invalid count bound')
    at = start

    def take(n):
        nonlocal at
        if n > bound - at:
            raise ValueError('Truncated138EEE4')
        old = at
        at += n
        return bytes(data[old:at])
    count = struct.unpack('<h', take(2))[0]
    population = max(count, 0)
    width = 8 if reference_context == RAW64 else 4
    if population > max_rows or population > (bound - at) // (1 + width + 2):
        raise ValueError('138EEE4count exceeds bound')
    rows = None
    stride = 1 + width + 2
    for _ in range(population):
        # Keep every paired-writer marker check; only opaque payloads are skipped.
        if data[at] != 1:
            raise ValueError('Unsupported current writer row marker')
        at += stride
    return {'start': start, 'end': at, 'signed_count': count, 'rows': rows, 'native_reader': '0x138eee4', 'native_writer': '0x138ed9c', 'reference_context': dict(reference_context), 'runtime_globals_proved': False, 'complete_child_wire': True, 'negative_count_native_empty': count < 0}
