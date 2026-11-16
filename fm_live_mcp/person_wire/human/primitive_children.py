"""Native D895E0/D8984C geometry. Runtime capacity guard remains unobserved."""

def parse(data, start, *, native, limit=None, max_rows=4096):
    end = len(data) if limit is None else limit
    c = start

    def take(n):
        nonlocal c
        if not 0 <= c <= end <= len(data) or n > end - c:
            raise ValueError('truncated primitive child')
        b = data[c:c + n]
        c += n
        return b
    n = int.from_bytes(take(4), 'little')
    if n > max_rows:
        raise ValueError('offline row budget')
    if native == 18627648:
        take(n * 4)
    elif native == 14194144:
        take(n * 3)
    elif native == 20006292:
        for _ in range(n):
            length = int.from_bytes(take(4), 'little')
            take(length)
    elif native == 14194764:
        if n > 4:
            raise ValueError('native D8984C count exceeds4')
        for _ in range(n):
            version = take(1)[0]
            take(4)
            if version <= 2:
                take(1)
    else:
        raise ValueError('unsupported native')
    return {'end': c, 'count': n, 'runtime_capacity_guard_observed': False, 'complete_wire': True}
