"""Bounded physical151A5B4 vector /15154E8 row grammar.

The caller owns the u32 count. Buffered stream registration/flush changes
physical read grouping but not row order. No reference/global mode is used.
Opaque native payloads and post-read normalization are not interpreted.
"""

class BudgetExceeded(ValueError):
    pass

def parse_vector(data, start, count, *, limit=None, source_major=3754, minor=9, max_rows=65536):
    if (type(source_major), type(minor)) != (int, int) or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported151A5B4 source')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid151A5B4 extent')
    if type(count) is not int or count < 0:
        raise ValueError('Invalid151A5B4 count')
    if type(max_rows) is not int or max_rows < 0:
        raise ValueError('Invalid151A5B4 work bound')
    if count > max_rows:
        raise BudgetExceeded('Offline151A5B4 row budget; not native rejection')
    if count > (bound - start) // 29:
        raise ValueError('Truncated151A5B4 minimum row extent')
    at = start
    versions = {}
    formats = {}
    extra_count = 0

    def take(n):
        nonlocal at
        if n > bound - at:
            raise ValueError('Truncated15154E8 row')
        before = at
        at += n
        return before
    for _ in range(count):
        version = data[take(1)]
        versions[version] = versions.get(version, 0) + 1
        take(16)
        fmt = data[take(1)]
        formats[fmt] = formats.get(fmt, 0) + 1
        take(2)
        take(9)
        if version == 3:
            take(1)
            extra_count += 1
    return {'start': start, 'end': at, 'count': count, 'row_versions': versions, 'packed_format_bytes': formats, 'legacy_extra_byte_rows': extra_count, 'complete_child_wire': True, 'pending_bytes': 0, 'native_reader': '0x151a5b4', 'native_row_reader': '0x15154e8', 'native_row_writer': '0x15157e4', 'reference_transport_used': False, 'native_normalization_applied': False}
parse = parse_vector
