"""Bounded 12B6058 current producer collection under HUMAN-local reference context."""

def parse(data, start, *, limit=None, source_major=3754, minor=9, max_rows=65536, reference_profile='local1_streambit1'):
    if (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported source')
    if reference_profile != 'local1_streambit1':
        raise ValueError('Unsupported explicit PERSON context')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid bounds')
    if type(max_rows) is not int or max_rows < 0:
        raise ValueError('Invalid budget')
    at = start

    def take(n):
        nonlocal at
        if n < 0 or n > bound - at:
            raise ValueError('Truncated12B6058')
        x = data[at:at + n]
        at += n
        return x

    def u(n):
        return int.from_bytes(take(n), 'little')
    version = u(1)
    count = u(4)
    if count > max_rows:
        raise ValueError('Offline row work budget; not native rejection')
    if count > (bound - at) // 43:
        raise ValueError('Truncated current writer rows')
    for _ in range(count):
        take(1)
        take(4)
        take(4)
        n = u(4)
        if n != 15:
            raise ValueError('Unsupported current writer u16 count (paired literal15)')
        take(n * 2)
    take(4)
    return dict(start=start, end=at, complete_child_wire=True, count=count, version=version, reference_profile=reference_profile, runtime_globals_proved=False)
