"""Pinned FIXTURE_NAME identity joins from a complete structural conjunction.

This establishes a unique whole-table source grammar, not a sequential loader
cursor through PERSON or observed runtime reference globals. No IDs or names
select the anchor. The supported current-writer table has at least four rows.

Build3754/9 native12629F0 reads five direct references and the12-byte
identity;1262EA4 writes tag0. COMP fixup1262C44..1262C5C resolves
through root+18. STAGE_NAME uses factory type23 and its stored flagbit0
name. Original ordinals are checked before any native repair can apply.
"""
from contextlib import contextmanager
from functools import partial
from io import BytesIO
from mmap import mmap
import struct
from threading import BoundedSemaphore

from . import (
    saved_club_records, saved_competition_records, saved_component_stream,
    saved_currency_records, saved_database, saved_database_header,
    saved_database_tables, saved_national_containers, saved_nations,
    saved_region_tables, saved_squad_tables, saved_team_records, snapshot_catalog,
)

MAX_REQUESTS = 500
MAX_TABLE_ROWS = 250_000
MAX_SCAN_BYTES = saved_component_stream.MAX_RAW_SIZE
MAX_ANCHOR_HITS = 2_000_000
MAX_ROW_WORK = 2_000_000
MAX_CONTEXT_TEXT_BYTES = 64 * 1024**2
_ROW = struct.Struct('<b5i3I')
_U32 = struct.Struct('<I')
_BUFFER_SLOT = BoundedSemaphore(1)
SCOPE = ('Unique complete structural FIXTURE_NAME table in the checked source; '
         'current-writer tag0, at least4 rows, original ordinal order and direct '
         'same-file COMP/STAGE_NAME indices. No sequential PERSON-loader anchor, '
         'runtime reference-global proof, localized display composition or '
         'fixed stage/round/leg meanings are claimed.')


def _indices(values):
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_REQUESTS:
        raise ValueError('Supply between 1 and 500 FIXTURE_NAME indices')
    if any(type(value) is not int or not 0 <= value < 2**31 for value in values):
        raise ValueError('Invalid saved FIXTURE_NAME index')
    return list(dict.fromkeys(values))


def locate_fixture_name_table(data, *, competition_count, stage_name_count):
    """Search the entire bounded source; incomplete/ambiguous scans fail closed.

    A literal original ordinal3 proposes headers; every row and footer must then
    validate. Requested indices, native IDs and string contents never participate
    in anchor selection. Small tables cannot provide this conjunction and remain
    unsupported rather than being reported empty.
    """
    if not isinstance(data, (bytes, bytearray, mmap)) or len(data) > MAX_SCAN_BYTES:
        raise ValueError('Unsupported complete saved database scan buffer')
    if any(type(n) is not int or not 0 <= n <= MAX_TABLE_ROWS
           for n in (competition_count, stage_name_count)):
        raise ValueError('Invalid canonical table bounds')
    found = []
    hits = work = cursor = 0
    needle = _U32.pack(3)
    while True:
        hit = data.find(needle, cursor)
        if hit < 0:
            break
        cursor = hit + 1
        hits += 1
        if hits > MAX_ANCHOR_HITS:
            raise ValueError('FIXTURE_NAME structural search exceeded anchor budget; search incomplete')
        header = hit - 3 * _ROW.size - 21 - 5
        if header < 0 or header + 5 > len(data):
            continue
        count, flags = struct.unpack_from('<IB', data, header)
        first = header + 5
        footer = first + count * _ROW.size
        if not 4 <= count <= MAX_TABLE_ROWS or flags != 0 or footer + 9 > len(data):
            continue
        if any(data[first+i*_ROW.size] != 0 or
               _U32.unpack_from(data, first+i*_ROW.size+21)[0] != i
               for i in range(4)):
            continue
        invalid_reference = False
        for ordinal in range(count):
            work += 1
            if work > MAX_ROW_WORK:
                raise ValueError('FIXTURE_NAME structural search exceeded row budget; search incomplete')
            tag, *refs, stored, _, _ = _ROW.unpack_from(data, first+ordinal*_ROW.size)
            if tag != 0 or stored != ordinal:
                break
            bounds = (competition_count, stage_name_count, stage_name_count,
                      stage_name_count, competition_count)
            invalid_reference |= any(value != -1 and not 0 <= value < bound
                                     for value, bound in zip(refs, bounds, strict=True))
        else:
            auxiliary = _U32.unpack_from(data, footer)[0]
            end = footer + 9 + auxiliary * 12
            if auxiliary > MAX_TABLE_ROWS or end > len(data):
                continue
            tail_byte, tail_word = struct.unpack_from('<BI', data, end-5)
            found.append({'start': header, 'first_record': first, 'count': count,
                          'flags': flags, 'footer_start': footer, 'end': end,
                          'footer': {'count': auxiliary, 'byte': tail_byte, 'word': tail_word},
                          'invalid_direct_reference': invalid_reference})
    if not found:
        raise ValueError('No complete FIXTURE_NAME structural anchor; source unavailable or unsupported')
    if len(found) != 1:
        raise ValueError('Ambiguous complete FIXTURE_NAME structural anchors')
    table = found[0]
    if table.pop('invalid_direct_reference'):
        raise ValueError('FIXTURE_NAME references require unsupported repair or exceed canonical tables')
    return {**table, 'search_complete': True, 'anchor_hits': hits,
            'validated_row_work': work, 'scope': SCOPE}


class _Source:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def read(self, size):
        start = self.offset
        self.offset = min(len(self.data), start + size)
        return self.data[start:self.offset]


def _stage_name(reader, ordinal, kind):
    # Factory type23 ignores the signed subtype argument.
    flags = reader.u8()
    name = reader.text(max_bytes=8192) if flags & 1 else None
    stored, native, secondary = reader.u32(), reader.u32(), reader.u32()
    if stored != ordinal:
        raise ValueError('Saved STAGE_NAME database ordinal mismatch')
    return {'database_index': ordinal, 'native_id': native, 'secondary_id': secondary,
            'name': name, 'stored_name_state': ('serialized_flag_bit0' if flags & 1
                                               else 'not_serialized_by_this_record')}


def _canonical_context(data, *, on_club=None, on_competition=None, on_team=None):
    reader = saved_component_stream.Reader(_Source(data), len(data))
    header = saved_database_header.read_header(reader)
    saved_database_tables.reach_clubs(reader)
    def observed(decoder, callback):
        def decode(reader, ordinal, kind):
            start = reader.offset
            row = decoder(reader, ordinal, kind)
            if callback is not None:
                callback(row, kind, start, reader.offset)
            return row
        return decode

    saved_database.skip_table(reader, 'CLUB', observed(
        partial(saved_club_records.read_club, include_team_indices=on_club is not None), on_club))
    text_bytes = 0

    def collect(label, decoder):
        nonlocal text_bytes
        rows = []
        for row in saved_database.table(reader, label, decoder):
            text_bytes += sum(len(value.encode('utf-8'))
                              for value in (row.get('name'), row.get('short_name'))
                              if value is not None)
            if text_bytes > MAX_CONTEXT_TEXT_BYTES:
                raise ValueError('Saved fixture identity context exceeds text budget')
            rows.append(row)
        return rows

    competitions = collect('COMP', observed(saved_competition_records.read_competition, on_competition))
    for label, decoder in (
        ('CONTINENT', saved_currency_records.skip_continent),
        ('CURRENCY', saved_currency_records.read_currency),
        ('INJURY', saved_squad_tables.skip_injury),
        ('MEDIA_SOURCE', saved_squad_tables.skip_media_source),
        ('LANGUAGE', saved_squad_tables.skip_language),
        ('NATION', saved_nations.skip_nation),
        ('NATIONAL_TEAM_CONTAINER', saved_national_containers.skip_national_container),
    ):
        saved_database.skip_table(reader, label, decoder)
    saved_region_tables.skip_name_tables(reader)
    for label, decoder in (
        ('REGION', saved_region_tables.skip_region),
        ('LOCAL_REGION', saved_region_tables.skip_local_region),
        ('STADIUM', saved_squad_tables.skip_stadium),
        ('STADIUM_CHANGE', saved_squad_tables.skip_stadium_change),
    ):
        saved_database.skip_table(reader, label, decoder)
    stages = collect('STAGE_NAME', _stage_name)
    team_count = 0
    decode_team = partial(saved_team_records.read_team, include_roster=False)
    for _ in saved_database.table(reader, 'TEAM_BASE', observed(decode_team, on_team)):
        team_count += 1
    return header, competitions, stages, team_count


def lookup_from_buffer(data, requested_indices, *, competitions, stage_names):
    """Pure batch projection; supplied canonical contexts must share this source."""
    unique = _indices(requested_indices)
    for label, rows in (('COMP', competitions), ('STAGE_NAME', stage_names)):
        if not isinstance(rows, list) or len(rows) > MAX_TABLE_ROWS:
            raise ValueError(f'Invalid canonical {label} context')
        if any(not isinstance(row, dict) or type(row.get('database_index')) is not int
               or row['database_index'] != index for index, row in enumerate(rows)):
            raise ValueError(f'Canonical {label} context requires original ordinal order')
    table = locate_fixture_name_table(data, competition_count=len(competitions),
                                     stage_name_count=len(stage_names))
    selected = {}
    def resolve(index, rows):
        return None if index == -1 else dict(rows[index])
    for index in unique:
        if index >= table['count']:
            selected[index] = {'database_index': index, 'state': 'out_of_range'}
            continue
        at = table['first_record'] + index*_ROW.size
        _, primary, first, second, third, secondary, stored, native_id, secondary_id = _ROW.unpack_from(data, at)
        selected[index] = {
            'database_index': stored, 'native_id': native_id, 'secondary_id': secondary_id,
            'state': 'resolved_structural_source', 'source_offset': at,
            'primary_competition': resolve(primary, competitions),
            'stage_names': [resolve(value, stage_names) for value in (first, second, third)],
            'secondary_competition': resolve(secondary, competitions),
        }
    return {'table': table, 'rows': [selected[index] for index in requested_indices]}


@contextmanager
def _checked_buffer(filename, expected_snapshot_id, directory):
    snapshot_catalog.check_filename(filename)
    if not isinstance(expected_snapshot_id, str) or not expected_snapshot_id:
        raise ValueError('Supply the exact snapshot ID that issued the FIXTURE_NAME indices')
    if not _BUFFER_SLOT.acquire(blocking=False):
        raise ValueError('Another saved fixture identity lookup is in progress; retry later')
    try:
        with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
            current = snapshot_catalog.snapshot_id(identity)
            if current != expected_snapshot_id:
                raise ValueError('Snapshot identity changed since fixture references were read')
            if not entries:
                raise ValueError('Saved snapshot contains no archive entries')
            root = entries[0].path.split('/')[0]
            databases = [entry for entry in entries if entry.path == f'{root}/game_db.dat']
            if len(databases) != 1:
                raise ValueError('Saved snapshot requires one root game_db.dat')
            with saved_component_stream.open_component(handle, databases[0]) as reader:
                with BytesIO() as buffer:
                    while reader.offset < reader.size:
                        buffer.write(reader.take(min(saved_component_stream.BLOCK_SIZE,
                                                     reader.size-reader.offset)))
                    if reader.source.read(1) or not reader.source.finished:
                        raise ValueError('Saved database frame did not end at its declared extent')
                    data = buffer.getvalue()
                yield data, {'source': 'on-disk save snapshot', 'filename': filename,
                             'snapshot_id': current,
                             'saved_metadata': snapshot_catalog._metadata(handle, entries)}
    finally:
        _BUFFER_SLOT.release()


def load_fixture_name_lookup(filename, requested_indices, *, expected_snapshot_id, directory=None):
    """Read one pinned database and locate the table once for the entire batch."""
    _indices(requested_indices)
    with _checked_buffer(filename, expected_snapshot_id, directory) as (data, source):
        header, competitions, stages, team_count = _canonical_context(data)
        result = lookup_from_buffer(data, requested_indices, competitions=competitions, stage_names=stages)
        result.update(source, database_format=header,
                      canonical_tables={'competition_count': len(competitions),
                                        'stage_name_count': len(stages), 'team_count': team_count})
    return result
