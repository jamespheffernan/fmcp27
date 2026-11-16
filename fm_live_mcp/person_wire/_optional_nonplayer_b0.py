"""NON_PLAYER+B0 child1363EA4; references require an explicit owning callback."""

def parse(data, start, *, source_major=3754, minor=9, reference_reader=None, max_rows=4096):
    if (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported NON_PLAYER+B0 source')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid NON_PLAYER+B0 cursor')
    if type(max_rows) is not int or not 0 <= max_rows <= 32767:
        raise ValueError('Invalid NON_PLAYER+B0 budget')
    at = start

    def take(n):
        nonlocal at
        if n < 0 or n > len(data) - at:
            raise ValueError('Truncated NON_PLAYER+B0')
        raw = data[at:at + n]
        at += n
        return raw

    def u(n):
        return int.from_bytes(take(n), 'little')

    def reference(namespace, field):
        nonlocal at
        if reference_reader is None:
            raise ValueError(f'Unsupported13644BC {namespace} reference at {at}: explicit transport context required')
        r = reference_reader(data, at, namespace, field)
        if not isinstance(r, dict) or type(r.get('end')) is not int or (not at < r['end'] <= len(data)):
            raise ValueError('Invalid13644BC reference callback cursor')
        at = r['end']
        return r
    version = u(1)
    count = int.from_bytes(take(2), 'little', signed=True)
    if not 0 <= count <= max_rows:
        raise ValueError('NON_PLAYER+B0 signed count budget')
    rows = []
    for ordinal in range(count):
        row_start = at
        marker = u(1)
        refs = [reference(namespace, field) for namespace, field in [('NATIONAL_TEAM_CONTAINER', '0'), ('PERSON', '8'), ('CLUB', '10')]]
        field24 = u(1)
        date_raw = take(4).hex()
        refs.append(reference('PERSON', '18'))
        field25 = u(1)
        rows.append({'start': row_start, 'end': at, 'ordinal': ordinal, 'marker': marker, 'references': refs, 'field24': field24, 'date_raw': date_raw, 'field25': field25})
    return {'start': start, 'end': at, 'version': version, 'count': count, 'rows': rows, 'native_reader': '0x1363ea4', 'references_resolved': False}

def validate_current_writer(parsed):
    """Reject wire versions that the pinned paired NON_PLAYER writer cannot emit."""
    if parsed['version'] != 1:
        raise ValueError('Current NON_PLAYER+B0 writer emits container version1')
    if any((row['marker'] != 4 for row in parsed['rows'])):
        raise ValueError('Current NON_PLAYER+B0 writer emits entry marker4')
    return parsed
