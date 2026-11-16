"""Native F2F2D4 modern173 fixed row; values remain opaque native fields."""
from .errors import UnsupportedLayout


def parse(data, start, *, limit=None, version=173, reference_context=None):
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid competition statistics row cursor')
    if limit is None:
        limit = len(data)
    if type(limit) is not int or not start <= limit <= len(data):
        raise ValueError('Invalid competition statistics row limit')
    if type(version) is not int or version != 173:
        raise UnsupportedLayout('Unsupported F2F2D4 inherited version; only173 proved')
    at = start
    chunks = []

    def take(size, field):
        nonlocal at
        if size > limit - at:
            raise ValueError(f'Truncated F2F2D4 at {at}')
        raw = bytes(data[at:at + size])
        chunks.append({'start': at, 'end': at + size, 'native_field': field,
                       'raw_hex': raw.hex()})
        at += size
        return raw

    # Both leading marker bytes are native-discarded, not reference codecs.
    take(1, 'discarded_marker_10')
    take(4, '0x10')
    take(1, 'discarded_marker_14')
    take(4, '0x14')
    for field in ('0x18', '0x1c', '0x28', '0x2c', '0x30', '0x20', '0x24'):
        take(4, field)
    for field, size in (('0x34',30), ('0x58',20), ('0x6e',16),
                        ('0x88',28), ('0xa5',3), ('0x7e',10),
                        ('0x52',6), ('0x6c',2), ('0xa4',1), ('0x0',14)):
        take(size, field)
    return {'start': start, 'end': at, 'version': version,
            'chunks': chunks, 'consumed_bytes': at - start,
            'native_reader': '0xf2f2d4', 'native_writer': '0xf2e77c',
            'references_consumed': False, 'semantic_fields_resolved': False,
            'complete_supported_row': True}


def rebuild(result):
    return b''.join(bytes.fromhex(c['raw_hex']) for c in result['chunks'])
