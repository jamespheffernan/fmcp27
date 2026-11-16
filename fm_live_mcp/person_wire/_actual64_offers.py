'CA85DC→CA8B3C CONTRACT_OFFER collection, explicit modern context.\n\nCDCA60 andCE1BCC manage vector ownership only; they add no wire fields.\nThe shared contract leaf is the real sibling optional/parser.py implementation.\nUnsupported positive children raise at their exact source edge, never skip.\n'
from . import _actual64_contracts
import struct
SUPPORTED = (3754, 3754, 9, 1, 0, 'raw64')
CONTRACT_READERS = {0: 19371812, 1: 20394128, 2: 16664836, 3: 16664836, 4: 16664836}

class UnsupportedChild(ValueError):

    def __init__(self, reader, offset, partial):
        self.reader = reader
        self.offset = offset
        self.partial = partial
        super().__init__(f'Unproved positive child0x{reader:x} at{offset}')

class Reader:

    def __init__(self, data, start):
        if not isinstance(data, (bytes, bytearray, memoryview)) or type(start) is not int or (not 0 <= start <= len(data)):
            raise ValueError('Invalid collection source cursor')
        self.data, self.pos = (data, start)

    def take(self, size):
        if size < 0 or size > len(self.data) - self.pos:
            raise ValueError(f'Truncated offer collection at{self.pos}, need{size}')
        value = bytes(self.data[self.pos:self.pos + size])
        self.pos += size
        return value

    def u8(self):
        return self.take(1)[0]

    def raw(self, size):
        at = self.pos
        value = self.take(size)
        return {'offset': at, 'size': size, 'raw_hex': value.hex()}

def _context(source_version, global_source_version, minor, body_mode, read_base, reference_mode):
    if any((type(v) is not int for v in (source_version, global_source_version, minor, body_mode, read_base))) or (source_version, global_source_version, minor, body_mode, read_base, reference_mode) != SUPPORTED:
        raise ValueError('Unsupported CONTRACT_OFFER inherited context')
    return dict(source_version=source_version, global_source_version=global_source_version, minor=minor, body_mode=body_mode, read_base=read_base, reference_mode=reference_mode)

def _shared_contract(data, at, *, kind, **context):
    return _actual64_contracts.parse_contract(data, at, kind, **context)

def _delegate(reader, function, native, partial, **kwargs):
    if function is None:
        raise UnsupportedChild(native, reader.pos, partial)
    start = reader.pos
    result = function(reader.data, start, **kwargs)
    if not isinstance(result, dict) or type(result.get('end')) is not int or (not start < result['end'] <= len(reader.data)):
        raise ValueError('Invalid child cursor handoff')
    reader.pos = result['end']
    return result

def _prefix(reader):
    start = reader.pos
    kind = struct.unpack('<b', reader.take(1))[0]
    fields = {'0x3e_0x40': reader.raw(3), '0x28_0x2f': reader.raw(8), '0x08_0x0f': reader.raw(8)}
    if kind == 5:
        raise ValueError('Native1007F6C rejects CONTRACT_OFFER kind5')
    return {'start': start, 'prefix_end': reader.pos, 'kind': kind, 'native_fields': fields, 'contract_state': 'requires_typed_child' if kind in CONTRACT_READERS else 'native_factory_null'}

def parse_offer_prefix(data, start, *, source_version=3754, global_source_version=3754, minor=9, body_mode=1, read_base=0, reference_mode='raw64'):
    """Only20B modern offer framing; not a completed offer or collection."""
    _context(source_version, global_source_version, minor, body_mode, read_base, reference_mode)
    reader = Reader(data, start)
    result = _prefix(reader)
    result.update(end=reader.pos, complete_offer=False, next_reader=hex(CONTRACT_READERS[result['kind']]) if result['kind'] in CONTRACT_READERS else None)
    return result

def parse(data, start, *, source_version=3754, global_source_version=3754, minor=9, body_mode=1, read_base=0, reference_mode='raw64', contract_reader=None, option_reader=None, array_reader=None):
    context = _context(source_version, global_source_version, minor, body_mode, read_base, reference_mode)
    reader = Reader(data, start)
    count = reader.u8()
    rows = []
    for native_index in range(count):
        row = _prefix(reader)
        row['native_index'] = native_index
        kind = row['kind']
        if kind in CONTRACT_READERS:
            selected = contract_reader
            if selected is None and kind in (2, 3, 4):
                selected = _shared_contract
            row['contract'] = _delegate(reader, selected, CONTRACT_READERS[kind], row, kind=kind, **context)
        else:
            row['contract'] = None
        row['native_fields'].update({'0x38_0x3d': reader.raw(6), '0x41': reader.raw(1), '0x30_0x37': reader.raw(8)})
        row['option_marker'] = reader.u8()
        row['option_child'] = _delegate(reader, option_reader, 22528776, row, **context) if row['option_marker'] == 1 else None
        row['array_marker'] = reader.u8()
        row['arrays'] = []
        if row['array_marker'] & 1:
            for group in range(2):
                version = reader.u8()
                for inner in range(2):
                    index = group * 2 + inner
                    row['arrays'].append(_delegate(reader, array_reader, 16814464, row, version=version, native_index=index, **context))
        row['end'] = reader.pos
        rows.append(row)
    return {'start': start, 'end': reader.pos, 'count': count, 'rows': rows, 'native_target': 'ACTUAL_PERSON+0x70', 'pool_name': 'CONTRACT_OFFER', 'source_context': context, 'complete_segment': True, 'complete_person': False, 'pending_bytes': 0, 'next_native': '0xca8b3c'}
