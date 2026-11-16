"""Bounded pure wire mirror of4AD0C70/4AD106C/4AD0514.

No allocation or native calls. Unknown56C1628 remains explicit unless supplied.
Field names are object offsets only; no football meaning is inferred.
"""
import struct

class UnsupportedChild(ValueError):

    def __init__(self, native, offset):
        self.native = native
        self.offset = offset
        super().__init__(f'Unsupported native child{native} at{offset}')

def parse(data, start, *, source_major=3754, minor=9, limit=None, collection_limit=None, max_rows=4096, property_reader=None):
    if (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported source profile')
    if type(start) is not int or type(max_rows) is not int or max_rows < 0:
        raise ValueError('Invalid bounds')
    end_limit = len(data) if limit is None else limit
    if type(end_limit) is not int or not 0 <= start <= end_limit <= len(data):
        raise ValueError('Invalid bounds')
    if collection_limit is not None and (type(collection_limit) is not int or not 0 < collection_limit < 1 << 64):
        raise ValueError('Invalid explicit native collection limit')
    at = start
    reads = []

    def take(n, label):
        nonlocal at
        if type(n) is not int or n < 0 or n > end_limit - at:
            raise ValueError(f'Truncated{label} at{at}')
        b = bytes(data[at:at + n])
        reads.append(dict(start=at, end=at + n, label=label, raw_hex=b.hex()))
        at += n
        return b

    def u(n, label):
        return int.from_bytes(take(n, label), 'little')
    version = u(1, 'outer_version')
    count = u(4, 'pointer_vector_count')
    if count > max_rows:
        raise ValueError('Implementation pointer-vector budget')
    if collection_limit is not None and count >= collection_limit:
        raise ValueError('Native pointer-vector limit predicate')
    rows = []
    for index in range(count):
        begin = at
        rv = u(1, 'row_version')
        field = u(2, 'row+1C')
        marker = u(1, 'row_kind_or_marker')
        kind = marker
        payload = None
        if marker == 101:
            kind = u(1, 'row+1E')
            if property_reader is None:
                raise UnsupportedChild('0x43fd1e0', at)
            out = property_reader(data, at)
            if not isinstance(out, dict) or out.get('state') == 'stopped' or out.get('complete_child_wire') is False or (type(out.get('end')) is not int) or (not at < out['end'] <= end_limit):
                raise ValueError('Invalid property callback end')
            payload = out
            at = out['end']
        elif marker == 102:
            kind = u(1, 'row+1E')
            if rv < 2:
                payload = {'legacy_raw8': take(8, 'legacy_row_pair').hex()}
            else:
                nested_version = u(1, 'value_pairs_version')
                signed = nested_version - 256 if nested_version >= 128 else nested_version
                if signed < 2:
                    payload = {'version': nested_version, 'legacy_raw8': take(8, 'legacy_value_pair').hex()}
                else:
                    pairs = []
                    for pair_index in range(3):
                        key = u(4, f'value_pair{pair_index}_key')
                        if key == 0:
                            break
                        value = u(4, f'value_pair{pair_index}_value')
                        pairs.append({'key': key, 'value': value})
                    else:
                        if u(4, 'value_pair_terminal') != 0:
                            raise ValueError('Native fourth-key rejection')
                    payload = {'version': nested_version, 'pairs': pairs}
        raw18 = u(4, 'row+18')
        rows.append(dict(index=index, start=begin, end=at, version=rv, raw_field1c=field, marker=marker, raw_kind1e=kind, value_payload=payload, raw_field18=raw18))
    tail_start = at
    tail_version = u(1, 'tail_version')
    tail_count = u(4, 'tail_byte_count')
    if tail_count > 7:
        raise ValueError('Native tail-byte count exceeds7')
    if collection_limit is not None and tail_count >= collection_limit:
        raise ValueError('Native tail limit predicate')
    tail = take(tail_count, 'tail_bytes').hex()
    return dict(start=start, end=at, complete_child_wire=True, version=version, count=count, rows=rows, tail={'start': tail_start, 'version': tail_version, 'count': tail_count, 'raw_hex': tail}, reads=reads, native_collection_limit=collection_limit, native_limit_guard_proven=collection_limit is not None, condition='56C1628 must exceed both stored counts' if collection_limit is None else None, builtin_reference_transport='none; marker101 delegates an opaque property map')
