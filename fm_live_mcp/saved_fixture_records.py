"""Current retained FIX_MAN wire, under an explicitly conditional reference profile.

The ordered sides are not assigned home/away labels. RESULT presence and score
channels do not establish completion, actual played date, winner or venue.
"""
import hashlib
import struct

from . import world

REFERENCE_PROFILE = 'conditional_streambit1_fixture_name_stadium32_team_tagged32_person32'
MAX_RECORDS = 250_000
MAX_GROUPS = 4096
MAX_DETAIL_ROWS = 1024
CHANNELS = ('normal_time', 'extra_time', 'penalties', 'aggregate')


def score_cell(raw):
    signed = raw if raw < 128 else raw - 256
    return {'raw_u8': raw, 'signed_i8': signed, 'value': signed if signed >= 0 else None,
            'state': 'unset_ff' if raw == 255 else 'unmapped_negative_code' if signed < 0 else 'stored_score_value'}


def _date(raw, offset):
    try:
        value = world.packed_date(raw)
    except ValueError:
        value = None
    return {'value': value, 'raw_hex': raw.hex(), 'source_offset': offset,
            'state': 'stored_kickoff_date' if value is not None else 'unmapped_packed_value',
            'unmapped_low_word_flags': int.from_bytes(raw, 'little') & 0xfe00}


def _team(reader):
    start = reader.offset
    marker = reader.take(1)[0]
    if marker not in (0, 1):
        raise ValueError('Unsupported conditional saved fixture TEAM transport')
    index = int.from_bytes(reader.take(4), 'little', signed=True)
    identity = int.from_bytes(reader.take(4), 'little') if marker == 1 and index != -1 else None
    if index < -1:
        raise ValueError('Invalid source-profile saved fixture TEAM index')
    return {'database_index': None if index == -1 else index, 'transport_marker': marker,
            'identity_word': identity, 'start': start, 'end': reader.offset, 'table': 'TEAM_BASE'}


def read_fixture(reader):
    start = reader.offset
    if reader.take(1) != b'\x1f':
        raise ValueError('Unsupported saved FIXTURE version; expected31')
    name, stadium = struct.unpack('<ii', reader.take(8))
    if min(name, stadium) < -1:
        raise ValueError('Invalid source-profile FIXTURE_NAME/STADIUM index')
    reader.take(2)
    teams = []
    for _ in range(2):
        teams.append(_team(reader))
        reader.take(2)
    date_offset = reader.offset
    date_raw, other_raw = reader.take(4), reader.take(4)
    reader.take(28)  # +54,+30,+50,+18,+38..3A,+32,+3C..40,+34,+46..45.
    date = _date(date_raw, date_offset)
    return {'start': start, 'end': reader.offset, 'source_class': 'FIXTURE',
            'has_result_record': False, 'source_offset_space': 'fix_man_component_decompressed',
            'fixture_name_index': None if name == -1 else name,
            'stored_stadium_index': None if stadium == -1 else stadium,
            'team_references': teams, 'stored_kickoff_date': date['value'], 'date4c': date,
            'raw_fixture_date48': int.from_bytes(other_raw, 'little'),
            'date48_source_offset': date_offset + 4, 'date48_semantics': 'unresolved',
            'score_channels': None, 'source_score_offsets': None, 'archive_key': None}


def read_result(reader):
    start = reader.offset
    header = reader.take(29)
    if header[0] != 31:
        raise ValueError('Unsupported saved FIXTURE_RESULT version; expected31')
    count, = struct.unpack_from('<I', header, 25)
    if count > MAX_DETAIL_ROWS:
        raise ValueError('Saved RESULT detail row work budget exceeded')
    reader.take(count * 16)
    common = read_fixture(reader)
    return {**common, 'start': start, 'source_class': 'FIXTURE_RESULT', 'has_result_record': True,
            'archive_key': struct.unpack_from('<i', header, 1)[0],
            'score_channels': {key: [score_cell(header[5 + i]), score_cell(header[9 + i])]
                               for i, key in enumerate(CHANNELS)},
            'source_score_offsets': [start + 5, start + 9], 'result_detail_count': count}


class _Capture:
    def __init__(self, reader):
        self.reader = reader
        self.digest = hashlib.sha256()
    @property
    def offset(self):
        return self.reader.offset
    @property
    def size(self):
        return self.reader.size
    def take(self, count):
        raw = self.reader.take(count)
        self.digest.update(raw)
        return raw


def read_record(reader, has_result):
    """One body, with source hash; excludes preceding bucket/presence framing."""
    capture = _Capture(reader)
    row = read_result(capture) if has_result else read_fixture(capture)
    row['record_sha256'] = capture.digest.hexdigest()
    return row


def read_retained(reader, on_record):
    """Walk all base/initial/declared outer groups, stop before final delegate.

    A callback sees every serialized row exactly once. No historical inner
    frames are read here. Failure raises instead of publishing an empty result.
    """
    if reader.offset != 0 or reader.take(8) != bytes.fromhex('03017461642e0500'):
        raise ValueError('Unsupported FIX_MAN component envelope/version')
    reader.take(10)
    base_count = int.from_bytes(reader.take(4), 'little')
    if base_count > MAX_RECORDS:
        raise ValueError('Saved fixture base work budget exceeded')
    total = 0
    classes = {'FIXTURE': 0, 'FIXTURE_RESULT': 0}
    def consume(container, ordinal, bucket, has_result):
        nonlocal total
        if total >= MAX_RECORDS:
            raise ValueError('Saved retained fixture work budget exceeded')
        row = read_record(reader, has_result)
        classes[row['source_class']] += 1
        on_record({'container': container, 'original_group_row': ordinal,
                   'bucket_key': bucket, **row})
        total += 1
    for i in range(base_count):
        consume('base', i, None, False)
    groups = []
    def group(container):
        begin = reader.offset
        year, present = struct.unpack('<HB', reader.take(3))
        if present not in (0, 1):
            raise ValueError('Unsupported saved fixture group presence')
        count = 0
        if present:
            reader.take(8)
            while True:
                bucket = int.from_bytes(reader.take(4), 'little', signed=True)
                if bucket == -1:
                    stored = int.from_bytes(reader.take(4), 'little')
                    if stored != count:
                        raise ValueError('Saved fixture group original row count mismatch')
                    break
                marker = reader.take(1)[0]
                if marker not in (0, 1):
                    raise ValueError('Unsupported saved fixture RESULT presence')
                consume(container, count, bucket, bool(marker))
                count += 1
        groups.append({'container': container, 'start': begin, 'end': reader.offset,
                       'native_u16_40': year, 'presence': present, 'row_count': count})
    group('initial')
    outer = int.from_bytes(reader.take(4), 'little')
    if outer > MAX_GROUPS or outer > (reader.size - reader.offset) // 3:
        raise ValueError('Saved fixture outer group budget/bounds exceeded')
    for i in range(outer):
        group(f'outer_{i}')
    return {'end': reader.offset, 'base_fixture_count': base_count, 'outer_group_count': outer,
            'groups': groups, 'scanned_records': total, 'scanned_classes': classes,
            'scope': 'retained base, initial and declared outer FIX_MAN groups',
            'reference_profile': REFERENCE_PROFILE, 'native_runtime_globals_proved': False,
            'historical_indexed_frames_searched': False, 'completion_state': 'unresolved',
            'actual_venue_state': 'unresolved'}
