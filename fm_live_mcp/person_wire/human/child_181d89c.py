"""181D89C count+rows collection; HUMAN consumes its separate outerversion first.
181D694 is the paired per-row writer, not the outer collection header writer.
"""

class UnsupportedChild(ValueError):

    def __init__(self, partial):
        self.partial = partial
        self.offset = partial['end']
        self.native = partial['next_native_reader']
        super().__init__(f'Unparsed181D89C child {self.native} at {self.offset}')

def parse(data, start, *, source_major=3754, minor=9, limit=None, max_items=4096, nested_reader=None):
    if (type(source_major), type(minor), source_major, minor) != (int, int, 3754, 9):
        raise ValueError('Unsupported181D89C source context')
    if type(max_items) is not int or not 0 <= max_items <= 4096:
        raise ValueError('Invalid181D89C implementation budget')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid181D89C bounds')
    at = start
    rows = []

    def take(n):
        nonlocal at
        if n < 0 or n > bound - at:
            raise ValueError('Truncated181D89C collection')
        begin = at
        at += n
        return bytes(data[begin:at])

    def u32():
        return int.from_bytes(take(4), 'little')
    count = u32()
    if count > max_items:
        raise ValueError('181D89C outer implementation budget')
    for ordinal in range(count):
        begin = at
        version = u32()
        inner_count = u32()
        if inner_count > max_items:
            raise ValueError('181D89C nested implementation budget')
        row = dict(ordinal=ordinal, start=begin, row_version=version, nested_count=inner_count, nested=[])
        rows.append(row)
        if inner_count and nested_reader is None:
            raise UnsupportedChild(dict(start=start, end=at, outer_count=count, rows=rows, complete_child_wire=False, next_native_reader='0x1819F70', reason='Positive nested row not decoded; no guessed skip'))
        for inner in range(inner_count):
            child = nested_reader(data, at, limit=bound, source_major=source_major, minor=minor)
            end = child.get('end')
            if child.get('complete_child_wire') is not True or type(end) is not int or (not at <= end <= bound):
                raise ValueError('Invalid nested1819F70 endpoint')
            at = end
            row['nested'].append(child)
        row['legacy_discarded_u32'] = u32() if version <= 3 else None
        row['native20_raw_u8'] = take(1)[0]
        size = u32()
        if size > 8192:
            raise ValueError('181D89C text implementation budget')
        raw = take(size)
        row['native00_text_raw_hex'] = raw.hex()
        try:
            row['native00_text_utf8'] = raw.decode('utf8')
        except UnicodeDecodeError:
            row['native00_text_utf8'] = None
        row['native21_raw_u8'] = take(1)[0]
        row['end'] = at
    return dict(start=start, end=at, complete_child_wire=True, complete_collection_wire=True, pending_bytes=0, native_reader='0x181D89C', per_row_writer='0x181D694', outer_count=count, rows=rows, native_success_status=0, source_major=source_major, minor=minor, semantic_fields_resolved=False, full_human_record_complete=False)
