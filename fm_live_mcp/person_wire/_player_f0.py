'Additive F0 dispatcher with bounded, strictly progressing child callbacks.\n\nChild callbacks are called as callback(data,start); bind extra contexts with\nfunctools.partial. Parent raw64 is not passed as a nested reference-width proof.\nLocal+40 supports the explicit stream-bit1 profile only, preserving raw indices.\n'
from . import _player_f0_legacy
_base = _player_f0_legacy
CHUNKS_38 = _base.CHUNKS_38
UnsupportedChild = _base.UnsupportedChild

def parse_40(data, start, *, stream_bit1=True, source_major=3754, minor=9):
    """Actual native+40 payload11E8EFC..11E9250; currentwriter11EA670..944."""
    if type(start) is not int or not 0 <= start < len(data):
        raise ValueError('Invalid/truncated F0+40 cursor')
    if type(stream_bit1) is not bool:
        raise ValueError('Explicit F0 local stream-bit1 profile required')
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported F0+40 source profile')
    version = data[start]
    at = start + 1
    chunks = []

    def take(n, label):
        nonlocal at
        if n > len(data) - at:
            raise ValueError(f'Truncated F0+40 {label} at{at}: need{n}')
        raw = bytes(data[at:at + n])
        chunks.append({'label': label, 'start': at, 'end': at + n, 'raw_hex': raw.hex()})
        at += n
        return raw
    for native in (16, 20, 24, 28):
        take(4, hex(native))
    if not stream_bit1:
        raise UnsupportedChild(17922080, at, {'version': version, 'chunks': chunks}, 'Local stream-bit1clear reference transport is unsupported')
    for native in (32, 40):
        take(4, f'raw_reference_{native:x}')
    for native, n in ((8, 4), (12, 4), (48, 8), (56, 4), (0, 8 if version >= 2 else 4), (77, 1), (76, 1), (78, 1), (79, 1)):
        take(n, hex(native))
    if version >= 4:
        take(8, '0x40')
        take(4, '0x48')
    return {'start': start, 'end': at, 'version': version, 'chunks': chunks, 'raw_hex': bytes(data[start:at]).hex(), 'native_payload_entry': '0x11e8efc', 'historical_stop_alias': '0x11e8e40', 'native_writer_span': '0x11ea670..0x11ea944', 'stream_bit1': True, 'local_global56D2C98': 1, 'raw_reference_width': 4, 'references_resolved': False, 'legacy_native_conversion_applied': False, 'raw_wire_only': True}

def parse(data, start, *, reference_mode='raw64', source_major=3754, minor=9, child_readers=None, stream_bit1=True, max_rows=512):
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid PLAYER+F0 cursor')
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported F0 source profile')
    if reference_mode not in ('raw32', 'raw64'):
        raise ValueError('Unsupported parent reference mode')
    if type(max_rows) is not int or not 0 <= max_rows <= 65535:
        raise ValueError('Invalid F0 row budget')
    if child_readers is None:
        child_readers = {}
    if not isinstance(child_readers, dict) or any((type(k) is not int or not callable(v) for k, v in child_readers.items())):
        raise ValueError('Invalid F0 child registry')
    at = start
    parts = {}
    remaining = max_rows

    def take(n):
        nonlocal at
        if n > len(data) - at:
            raise ValueError(f'Truncated F0 at{at}: need{n}')
        raw = bytes(data[at:at + n])
        at += n
        return raw

    def child(native):
        nonlocal at
        callback = child_readers.get(native)
        if callback is None:
            raise UnsupportedChild(native, at, parts, 'Explicit child codec/context required')
        result = callback(data, at)
        if not isinstance(result, dict) or type(result.get('end')) is not int or (not at < result['end'] <= len(data)):
            raise ValueError(f'Invalid progressing F0 callback{native:#x} at{at}')
        at = result['end']
        return result
    for name, native in (('vector_00', 22339972), ('vector_18', 67491224)):
        count_at = at
        count = take(1)[0]
        remaining -= count
        if remaining < 0:
            raise ValueError('F0 cumulative row budget exceeded')
        item = {'count': count, 'count_offset': count_at, 'rows': []}
        parts[name] = item
        for _ in range(count):
            item['rows'].append(child(native))
    for name, native, bit0 in (('optional_30', 18777664, False), ('optional_38', None, False), ('optional_40', 18779900, True), ('optional_48', 18781012, True), ('optional_50', 18781476, True), ('optional_58', 22275436, False)):
        marker_at = at
        marker = take(1)[0]
        present = bool(marker & 1) if bit0 else marker == 1
        item = {'marker': marker, 'marker_offset': marker_at, 'present': present, 'predicate': 'bit0' if bit0 else 'equality1'}
        parts[name] = item
        if not present:
            continue
        if name == 'optional_38':
            item['start'] = at
            item['version'] = take(1)[0]
            chunks = []
            for offset, n in CHUNKS_38:
                begin = at
                raw = take(n)
                chunks.append({'native_offset': hex(offset), 'start': begin, 'end': at, 'raw_hex': raw.hex()})
            item.update(end=at, chunks=chunks)
        elif name == 'optional_40' and native not in child_readers:
            if 18779712 in child_readers:
                item['child'] = child(18779712)
            else:
                result = parse_40(data, at, stream_bit1=stream_bit1, source_major=source_major, minor=minor)
                at = result['end']
                item['child'] = result
        else:
            item['child'] = child(native)
    return {'start': start, 'end': at, 'consumed_bytes': at - start, 'parts': parts, 'native_reader': '0x11e7c4c', 'native_writer': '0x11e9f30', 'parent_reference_mode': reference_mode, 'local_native_global56D2C98': 1, 'complete_exercised_child_wire': True, 'complete_player_body': False, 'source_major': source_major, 'minor': minor, 'all_optional_children_are_single': True}
