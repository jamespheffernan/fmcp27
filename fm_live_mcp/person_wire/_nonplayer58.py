"""14618A8 NON_PLAYER+58 fixed scalar transport, without field meanings."""
import struct

def parse(data, start, *, source_major=3754, minor=9):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported NON_PLAYER+58 source')
    try:
        view = memoryview(data).cast('B')
    except TypeError as error:
        raise ValueError('NON_PLAYER+58 needs a byte buffer') from error
    if type(start) is not int or not 0 <= start <= len(view):
        raise ValueError('Invalid NON_PLAYER+58 cursor')
    at = start

    def take(size):
        nonlocal at
        if size > len(view) - at:
            raise ValueError(f'Truncated NON_PLAYER+58 at {at}, need {size}')
        raw = view[at:at + size]
        at += size
        return raw

    def number(fmt):
        return struct.unpack('<' + fmt, take(struct.calcsize('<' + fmt)))[0]
    version = number('B')
    raw_first = take(4)
    field04 = number('H')
    legacy = None
    if version <= 1:
        legacy_start = at
        words = [number('H') for _ in range(13)]
        bytes_ = [number('B') for _ in range(2)]
        final_word = number('I')
        legacy = {'start': legacy_start, 'end': at, 'discarded_u16': words, 'discarded_u8': bytes_, 'discarded_u32': final_word, 'native_destination': 'Temporary stack fields; no retained meaning assigned'}
    field06 = number('B')
    first, second = struct.unpack('<HH', raw_first)
    return {'start': start, 'end': at, 'version': version, 'native_reader': '0x14618a8', 'native_writer_block': '0xc8acc4..0xc8ad8c', 'native_owner_field': 'NON_PLAYER+0x58', 'fields': {'00_raw_u32': int.from_bytes(raw_first, 'little'), '00_raw_u16': first, '02_raw_u16': second, '04_raw_u16': field04, '06_raw_u8': field06}, 'legacy_discarded': legacy, 'pending_bytes': 0, 'complete_child_wire': True, 'semantic_fields_resolved': False, 'reference_context_required': False}

def validate_current_writer(result):
    if result['version'] != 2:
        raise ValueError('NON_PLAYER+58 differs from paired current writer literal2')
