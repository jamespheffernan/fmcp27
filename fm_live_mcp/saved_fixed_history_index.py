"""Native v4 owner lists and fixed-width history frames, streamed and bounded.

Encoded words use adjacent original encoded values, not cumulative deltas.
No owner namespace, row semantics or component ownership is inferred here.
"""
import struct

LIST_HEADER = bytes.fromhex('03017461642e0400')
MAX_OWNERS = 2_000_000
MAX_OWNER_ENTRIES = 4096
MAX_LIST_ENTRIES = 2_000_000
MAX_LIST_BYTES = 32 * 1024**2


def _profile(width, data_version):
    if (type(width) is not int or not 1 <= width <= 65536 or
            type(data_version) is not int or not 0 <= data_version <= 65535):
        raise ValueError('Invalid fixed-history profile')


def _signed(value):
    return value if value < 0x80000000 else value - 0x100000000


def read_index(reader, owner, *, width, data_version):
    """Consume the complete list and retain one owner's ordered offsets."""
    _profile(width, data_version)
    if type(owner) is not int or not -(1 << 31) <= owner < 1 << 31:
        raise ValueError('Expected signed history owner key')
    if reader.size > MAX_LIST_BYTES or reader.take(8) != LIST_HEADER:
        raise ValueError('Unsupported or excessive fixed-history list')
    free = reader.u32()
    if free > MAX_LIST_ENTRIES:
        raise ValueError('History free-offset count exceeds offline budget')
    reader.skip(free * 4)
    owners = reader.u32()
    if owners > MAX_OWNERS or owners > (reader.size - reader.offset) // 4:
        raise ValueError('History owner count exceeds bounded list')
    offsets = []
    total = 0
    for ordinal in range(owners):
        count = reader.u32()
        total += count
        if count > MAX_OWNER_ENTRIES or total > MAX_LIST_ENTRIES:
            raise ValueError('History entries exceed offline work budget')
        if ordinal != owner:
            reader.skip(count * 4)
            continue
        previous = 0
        for _ in range(count):
            encoded = reader.u32()
            offsets.append(_signed((encoded + previous) & 0xffffffff))
            previous = encoded
    empty = reader.u32()
    if empty > owners:
        raise ValueError('Invalid history empty-owner count')
    for _ in range(empty):
        if reader.u32() >= owners:
            raise ValueError('History empty-owner key is outside list')
    actual_width, actual_version = struct.unpack('<IH', reader.take(6))
    if reader.offset != reader.size or (actual_width, actual_version) != (width, data_version):
        raise ValueError('Unsupported history width/version or trailing list bytes')
    state = ('no_history_index' if owner < 0 else
             'outside_owner_table' if owner >= owners else 'selected_owner')
    return offsets, {'state': state, 'owner_count': owners, 'free_offset_count': free,
                     'empty_owner_count': empty, 'all_owner_entry_count': total,
                     'version': 4, 'record_width': width, 'data_version': data_version,
                     'structure_complete': True, 'other_owner_offsets_validated': False}


def read_rows(reader, offsets, *, width, data_version):
    """Drain one complete data frame; read each selected physical row once."""
    _profile(width, data_version)
    header = b'\x03\x01tmc.' + struct.pack('<H', data_version)
    if reader.take(8) != header or (reader.size - 8) % width:
        raise ValueError('Unsupported history data header or fixed-row extent')
    if len(offsets) > MAX_OWNER_ENTRIES or any(type(v) is not int or not -(1 << 31) <= v < 1 << 31 for v in offsets):
        raise ValueError('Invalid or excessive selected history offsets')
    wanted = sorted(set(v for v in offsets if v >= 0))
    for value in wanted:
        if value % width or value + 8 + width > reader.size:
            raise ValueError('History offset is misaligned or outside data')
    selected = {}
    for value in wanted:
        reader.skip(value + 8 - reader.offset)
        selected[value] = reader.take(width)
    reader.skip(reader.size - reader.offset)
    return selected
