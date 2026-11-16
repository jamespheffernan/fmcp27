"""CA8220..CA85DC and the proved FECA24 contract subset.

Kinds2/3/4 share FE4904 exactly. Kind5 uses D8B50C directly.
Kinds0/1 require additional derived readers and fail explicitly.
"""
SUPPORTED_CONTEXT = (3754, 3754, 9, 1, 0, 'raw64')
MAX_ROWS = 10000
MAX_SLOTS = 5

class Reader:

    def __init__(self, data, start):
        if type(start) is not int or not 0 <= start <= len(data):
            raise ValueError('invalid optional start')
        self.data = data
        self.pos = start

    def take(self, n):
        if type(n) is not int or not 0 <= n <= len(self.data) - self.pos:
            raise ValueError(f'truncated optional at{self.pos} need{n}')
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def u(self, n):
        return int.from_bytes(self.take(n), 'little')

    def i(self, n):
        return int.from_bytes(self.take(n), 'little', signed=True)

def _context(source_version, global_source_version, minor, body_mode, read_base, reference_mode):
    if (source_version, global_source_version, minor, body_mode, read_base, reference_mode) != SUPPORTED_CONTEXT:
        raise ValueError('unsupported CA8220 inherited context')

def _base(r):
    start = r.pos
    fields = {'0x08_raw': r.u(4), '0x10_reference_raw64_hex': r.take(8).hex(), '0x20_raw': r.u(4), '0x26_raw': r.u(1), '0x24_raw': r.u(2)}
    return {'start': start, 'end': r.pos, 'reader': '0xd8b50c', 'fields': fields}

def _contract(r, kind):
    if kind == 5:
        return _base(r)
    if kind not in (2, 3, 4):
        raise ValueError(f'unproved FECA24 derived reader for kind{kind} at{r.pos}')
    start = r.pos
    prefix = [r.take(n).hex() for n in (12, 8, 6)]
    count = r.u(4)
    if count > MAX_ROWS:
        raise ValueError('contract numeric vector exceeds work bound')
    rows = []
    for _ in range(count):
        at = r.pos
        version = r.u(1)
        raw = r.take(28)
        rows.append({'start': at, 'end': r.pos, 'version': version, 'raw_after_version': raw.hex(), 'tail_encoding': 'u16' if version >= 7 else 'legacy_byte_plus_u8'})
    tail = [r.take(n).hex() for n in (1, 4, 7, 8, 4, 1)]
    base = _base(r)
    return {'start': start, 'end': r.pos, 'reader': '0xfe4904', 'kind': kind, 'prefix_raw': prefix, 'numeric_count': count, 'numeric_rows': rows, 'tail_raw': tail, 'base': base}

def parse_contract(data, start, kind, *, source_version=3754, global_source_version=3754, minor=9, body_mode=1, read_base=0, reference_mode='raw64'):
    _context(source_version, global_source_version, minor, body_mode, read_base, reference_mode)
    if type(kind) is not int or kind not in (2, 3, 4, 5):
        raise ValueError('unsupported FECA24 child kind')
    r = Reader(data, start)
    return _contract(r, kind)

def parse(data, start, *, source_version=3754, global_source_version=3754, minor=9, body_mode=1, read_base=0, reference_mode='raw64'):
    _context(source_version, global_source_version, minor, body_mode, read_base, reference_mode)
    r = Reader(data, start)
    word = r.u(4)
    count = r.u(1)
    if count > MAX_SLOTS:
        raise ValueError('unsupported optional slots beyond native extra pointer capacity')
    slots = []
    for _ in range(count):
        at = r.pos
        kind = r.i(1)
        if kind == -1:
            child = None
            state = 'sentinel_no_child'
        elif kind in (0, 1, 2, 3, 4, 5):
            child = _contract(r, kind)
            state = 'child'
        else:
            child = None
            state = 'native_factory_null_no_payload'
        slots.append({'start': at, 'end': r.pos, 'kind': kind, 'state': state, 'child': child})
    return {'start': start, 'end': r.pos, 'object_b0_raw': word, 'slot_count': count, 'slots': slots, 'next_native': '0xca85dc', 'pending_bytes': 0, 'complete_segment': True, 'complete_person': False}

def parse_fe4904(data, start, *, source_version=3754, global_source_version=3754, minor=9, body_mode=1, read_base=0, reference_mode='raw64'):
    """Shared FE4904 body reached by a separately proved derived reader call."""
    _context(source_version, global_source_version, minor, body_mode, read_base, reference_mode)
    r = Reader(data, start)
    out = _contract(r, 2)
    out.pop('kind', None)
    out['enclosing_subtype'] = None
    out['scope'] = 'shared FE4904 body; outer subtype belongs to caller'
    return out
