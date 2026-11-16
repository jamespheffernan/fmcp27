"""Conditional F9AE54 scalar leaf; no factory-profile inference."""
from .errors import UnsupportedLayout
import struct

CTX = dict(stream_bit1=True, global_3522=0, global_3523=1, global_2c98=1)


class UnsupportedChild(ValueError):
    def __init__(self, native, offset):
        self.native, self.offset = native, offset
        super().__init__(f'Unsupported {native} at {offset}')


def parse(data, start, *, limit=None, reference_context):
    if (type(reference_context) is not dict or reference_context != CTX or
            any(type(reference_context.get(k)) is not type(v) for k, v in CTX.items())):
        raise UnsupportedLayout('Unsupported explicit F9AE54 reference context')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid F9AE54 start')
    if limit is None:
        limit = len(data)
    if type(limit) is not int or not start <= limit <= len(data):
        raise ValueError('Invalid F9AE54 limit')
    at = start

    def take(size):
        nonlocal at
        if size > limit - at:
            raise ValueError(f'Truncated F9AE54 at {at}')
        raw = bytes(data[at:at + size])
        at += size
        return raw

    flag = take(1)[0]
    ref_start = at
    marker = take(1)[0]
    if marker == 2:
        raise UnsupportedChild('0x11073a8 inline reference', at)
    index = struct.unpack('<i', take(4))[0]
    secondary = None
    if index != -1 and marker == 1:
        secondary = int.from_bytes(take(4), 'little')
    ref_end = at
    raw18 = take(4)
    raw1c = take(2)
    return {'start': start, 'end': at, 'raw_flag_u8': flag,
            'object_reference': {'start': ref_start, 'end': ref_end,
                                 'marker': marker, 'stored_index_i32': index,
                                 'secondary_word': secondary},
            'native18_raw_u32': int.from_bytes(raw18, 'little'),
            'native1c_raw_u16': int.from_bytes(raw1c, 'little'),
            'raw_hex': bytes(data[start:at]).hex(),
            'native_reader': '0xf9ae54', 'native_writer': '0xf9ad84',
            'reference_context': dict(reference_context),
            'source_runtime_profile_proved': False,
            'complete_supported_child': True, 'semantic_fields_resolved': False}
