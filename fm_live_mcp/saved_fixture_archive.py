"""Indexed GAME_COMP_MANAGER historical groups, with explicit source coverage.

Frame group/year keys are storage metadata, never kickoff-date predicates.
Fixture occurrences remain ordered and distinct. No completion or venue claim
is established by RESULT membership or successful decompression.
"""
import hashlib
import io
import struct

from .saved_component_stream import Reader
from .saved_fixture_archive_zstd import expand_frame
from .saved_fixture_records import REFERENCE_PROFILE, read_record

MAX_ENTRIES = 4096
MAX_PAYLOAD = 64 * 1024 * 1024
MAX_FRAME_ROWS = 10000
MAX_SCAN_FRAMES = 512
MAX_SCAN_ROWS = 250000


def _integer(value, minimum, maximum, name):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'Invalid historical fixture {name}')
    return value


def _optional(value, maximum, name):
    return None if value is None else _integer(value, 0, maximum, name)


def _read_archive(reader):
    start = reader.offset
    if start == reader.size:
        return None
    if reader.take(1) != b'\x01':
        raise ValueError('Unsupported historical fixture archive envelope version')
    count, = struct.unpack('<I', reader.take(4))
    if count > MAX_ENTRIES or count > (reader.size - reader.offset) // 14:
        raise ValueError('Historical fixture index budget or truncated rows')
    entries = []
    key_counts = {}
    for ordinal in range(count):
        at = reader.offset
        group, year, position, size = struct.unpack('<IHii', reader.take(14))
        key = group, year
        occurrence = key_counts.get(key, 0)
        key_counts[key] = occurrence + 1
        entries.append({'frame_index': ordinal, 'index_source_offset': at,
                        'stored_group_index': group, 'stored_group_year': year,
                        'payload_position': position, 'compressed_size': size,
                        'native_key_occurrence': occurrence,
                        'native_first_key_match': occurrence == 0})
    header_at = reader.offset
    raw08, raw0c, mode, length = struct.unpack('<iiBi', reader.take(13))
    if mode != 3:
        raise ValueError('Unsupported historical fixture archive compression mode')
    if length < 0 or length > MAX_PAYLOAD or length > reader.size - reader.offset - 1:
        raise ValueError('Historical fixture payload budget or truncated extent')
    payload_start = reader.offset
    pieces = []
    left = length
    while left:
        amount = min(left, 128 * 1024)
        pieces.append(reader.take(amount))
        left -= amount
    payload = b''.join(pieces)
    flag = reader.take(1)[0]
    if flag not in (0, 1) or reader.offset != reader.size:
        raise ValueError('Invalid historical fixture archive flag or component suffix')
    for entry in entries:
        position, size = entry['payload_position'], entry['compressed_size']
        if position < 0 or size <= 0 or position > length or size > length - position:
            raise ValueError('Historical fixture index points outside stored payload')
        entry['compressed_frame_start'] = payload_start + position
    return {'start': start, 'end': reader.offset, 'entries': entries, 'payload': payload,
            'payload_start': payload_start, 'payload_sha256': hashlib.sha256(payload).hexdigest(),
            'buffer_header': {'source_offset': header_at, 'native08_i32': raw08,
                              'native0c_i32': raw0c, 'mode_u8': mode,
                              'length_i32': length, 'trailing_flag_u8': flag}}


def _read_group(raw):
    reader = Reader(io.BytesIO(raw), len(raw))
    if reader.take(2) != b'\x02\x00':
        raise ValueError('Unsupported historical fixture group header')
    present = reader.take(1)[0]
    if present not in (0, 1):
        raise ValueError('Unsupported historical fixture group presence')
    rows = []
    if present:
        while True:
            delimiter = reader.take(1)[0]
            if delimiter == 0:
                break
            if delimiter != 1:
                raise ValueError('Unsupported historical fixture row delimiter')
            if len(rows) >= MAX_FRAME_ROWS:
                raise ValueError('Historical fixture frame row work budget exceeded')
            kind = reader.take(1)[0]
            if kind not in (0, 1):
                raise ValueError('Unsupported historical fixture row type')
            # Both native cache-hit and allocation paths map1 to RESULT,0 to FIXTURE.
            row = read_record(reader, kind == 1)
            row['native_type_u8'] = kind
            rows.append(row)
        count, = struct.unpack('<I', reader.take(4))
        if count != len(rows):
            raise ValueError('Historical fixture group stored row count mismatch')
    else:
        count = None
    if reader.offset != reader.size:
        raise ValueError('Unconsumed historical fixture group bytes')
    return present, count, rows


def read_historical(reader, on_record, *, frame_offset=0, row_offset=0,
                    frame_limit=MAX_SCAN_FRAMES, row_limit=MAX_SCAN_ROWS,
                    stored_group_index=None, stored_group_year=None):
    """Consume the terminal envelope, then examine a bounded ordered row range.

    The caller validates the original archive/component and publishes only after
    its final byte/identity checks. Frame decoding finishes before callbacks.
    A continuation is a physical frame/row cursor, separate from match filters.
    """
    _integer(frame_offset, 0, MAX_ENTRIES, 'frame offset')
    _integer(row_offset, 0, MAX_FRAME_ROWS, 'row offset')
    _integer(frame_limit, 1, MAX_SCAN_FRAMES, 'frame limit')
    _integer(row_limit, 1, MAX_SCAN_ROWS, 'row limit')
    _optional(stored_group_index, 0xffffffff, 'stored group index')
    _optional(stored_group_year, 0xffff, 'stored group year')
    if not callable(on_record):
        raise ValueError('Historical fixture row callback required')
    archive = _read_archive(reader)
    common = {'scope': 'indexed historical GAME_COMP_MANAGER fixture groups',
              'reference_profile': REFERENCE_PROFILE, 'native_runtime_globals_proved': False,
              'completion_state': 'unresolved', 'actual_venue_state': 'unresolved',
              'frame_offset': frame_offset, 'row_offset': row_offset,
              'frame_limit': frame_limit, 'row_limit': row_limit,
              'index_filters': {'stored_group_index': stored_group_index,
                                'stored_group_year': stored_group_year},
              'index_year_is_kickoff_filter': False}
    if archive is None:
        if frame_offset or row_offset:
            raise ValueError('Historical fixture cursor has no serialized archive')
        return {**common, 'state': 'unavailable',
                'unavailable_reason': 'no_serialized_archive_tail', 'entry_count': None,
                'scanned_frames': 0, 'scanned_records': 0, 'frames': [],
                'scanned_classes': {'FIXTURE': 0, 'FIXTURE_RESULT': 0},
                'next_cursor': None, 'reached_end': False,
                'complete_source': False, 'complete_filtered_scope': False,
                'historical_indexed_frames_searched': False}
    entries = archive['entries']
    if frame_offset > len(entries) or frame_offset == len(entries) and row_offset:
        raise ValueError('Historical fixture cursor outside native index')
    selected = [entry for entry in entries
                if (stored_group_index is None or entry['stored_group_index'] == stored_group_index)
                and (stored_group_year is None or entry['stored_group_year'] == stored_group_year)]
    if row_offset and not any(e['frame_index'] == frame_offset for e in selected):
        raise ValueError('Historical fixture row cursor excluded by index filter')
    remaining = [entry for entry in selected if entry['frame_index'] >= frame_offset]
    frames = []
    scanned = 0
    classes = {'FIXTURE': 0, 'FIXTURE_RESULT': 0}
    next_cursor = None
    for entry in remaining:
        index = entry['frame_index']
        offset = row_offset if index == frame_offset else 0
        if len(frames) == frame_limit or scanned == row_limit:
            next_cursor = {'frame_offset': index, 'row_offset': offset}
            break
        position = entry['payload_position']
        compressed = archive['payload'][position:position + entry['compressed_size']]
        raw = expand_frame(compressed)
        present, count, rows = _read_group(raw)
        if offset > len(rows):
            raise ValueError('Historical fixture row cursor outside decoded frame')
        amount = min(len(rows) - offset, row_limit - scanned)
        frame = {**entry, 'compressed_sha256': hashlib.sha256(compressed).hexdigest(),
                 'raw_sha256': hashlib.sha256(raw).hexdigest(), 'raw_bytes': len(raw),
                 'native_b71_u8': present, 'stored_row_count': count,
                 'decoded_row_count': len(rows), 'row_offset': offset,
                 'scanned_row_count': amount}
        frames.append(frame)
        for ordinal in range(offset, offset + amount):
            row = rows[ordinal]
            classes[row['source_class']] += 1
            on_record({**row, 'container': f'historical_{index}',
                       'historical_frame_index': index,
                       'stored_group_index': entry['stored_group_index'],
                       'stored_group_year': entry['stored_group_year'],
                       'native_key_occurrence': entry['native_key_occurrence'],
                       'native_first_key_match': entry['native_first_key_match'],
                       'original_group_row': ordinal, 'bucket_key': None,
                       'source_offset_space': 'historical_frame_decompressed',
                       'compressed_frame_start': entry['compressed_frame_start'],
                       'compressed_frame_size': entry['compressed_size'],
                       'compressed_frame_sha256': frame['compressed_sha256'],
                       'decompressed_frame_sha256': frame['raw_sha256']})
        scanned += amount
        if offset + amount < len(rows):
            next_cursor = {'frame_offset': index, 'row_offset': offset + amount}
            break
    from_start = frame_offset == row_offset == 0
    reached_end = next_cursor is None
    no_filter = stored_group_index is None and stored_group_year is None
    return {**common, 'state': 'available', 'unavailable_reason': None,
            'start': archive['start'], 'end': archive['end'], 'entry_count': len(entries),
            'selected_entry_count': len(selected), 'payload_start': archive['payload_start'],
            'payload_bytes': len(archive['payload']), 'payload_sha256': archive['payload_sha256'],
            'buffer_header': archive['buffer_header'], 'frames': frames,
            'scanned_frames': len(frames), 'scanned_records': scanned,
            'scanned_classes': classes, 'next_cursor': next_cursor, 'reached_end': reached_end,
            'complete_source': from_start and reached_end and no_filter,
            'complete_filtered_scope': from_start and reached_end,
            'historical_indexed_frames_searched': True}
