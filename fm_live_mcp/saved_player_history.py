"""Pinned saved PLAYER history: original PERSON owner key and streamed archive rows."""
from array import array
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import struct
import time

from . import archived_player_statistics, archive_stat_references, saved_component_stream, saved_population, snapshot_catalog
from .current_player_statistics import CATEGORY_LABELS

LIST_HEADER = bytes.fromhex('03017461642e0400')
DATA_HEADER = bytes.fromhex('0301746d632e0700')
WIDTH = 168
MAX_OWNERS = 2_000_000
MAX_OWNER_ENTRIES = 4096
MAX_LIST_ENTRIES = 2_000_000
MAX_LIST_BYTES = 32 * 1024**2
MAX_ADVANCE = 10_000


class _Packed:
    def __init__(self, handle, entry):
        self.handle, self.entry = handle, entry
        self.digest = sha256()
        self.count = 0

    def seek(self, *args):
        return self.handle.seek(*args)

    def read(self, n):
        expected = 26 + self.entry.start + self.count
        if self.handle.tell() != expected:
            raise ValueError('History component packed reads are not sequential')
        raw = self.handle.read(n)
        self.digest.update(raw)
        self.count += len(raw)
        return raw


class _Stream:
    def __init__(self, reader):
        self.reader = reader
        self.digest = sha256()

    @property
    def offset(self):
        return self.reader.offset

    @property
    def size(self):
        return self.reader.size

    def take(self, n):
        raw = self.reader.take(n)
        self.digest.update(raw)
        return raw

    def skip(self, n):
        if n < 0 or n > self.size - self.offset:
            raise ValueError('History skip exceeds declared component')
        while n:
            amount = min(n, saved_component_stream.BLOCK_SIZE)
            self.take(amount)
            n -= amount

    def u32(self):
        return struct.unpack('<I', self.take(4))[0]


@contextmanager
def _component(handle, entry, receipts):
    packed = _Packed(handle, entry)
    with saved_component_stream.open_component(packed, entry) as reader:
        stream = _Stream(reader)
        yield stream
        if stream.offset != stream.size:
            raise ValueError('History component was not completely consumed')
        if reader.source.read(1) or not reader.source.finished:
            raise ValueError('History component frame did not end at declared extent')
    if packed.count != entry.compressed_size:
        raise ValueError('History packed component extent differs')
    expected = packed.digest.digest()
    handle.seek(26 + entry.start)
    check = sha256()
    left = entry.compressed_size
    while left:
        raw = handle.read(min(left, saved_component_stream.BLOCK_SIZE))
        if not raw:
            raise ValueError('Truncated history packed component recheck')
        check.update(raw)
        left -= len(raw)
    if check.digest() != expected:
        raise ValueError('History component changed during request')
    receipts[entry.path.rsplit('/', 1)[-1]] = {
        'state': 'complete_frame_and_packed_bytes_rechecked',
        'archive_path': entry.path, 'raw_bytes': entry.uncompressed_size,
        'packed_bytes': entry.compressed_size,
        'raw_sha256': stream.digest.hexdigest(), 'packed_sha256': expected.hex(),
    }


def _filters(values, maximum, label):
    if values is None:
        return None
    if (not isinstance(values, list) or not 1 <= len(values) <= 100
            or any(type(v) is not int or not 0 <= v <= maximum for v in values)):
        raise ValueError(f'{label} must be a nonempty list of at most100 supported integer codes')
    return set(values)


def _entry(entries, root, path):
    selected = [e for e in entries if e.path == root + '/' + path]
    if len(selected) != 1:
        raise ValueError('Missing or ambiguous saved history component: ' + path)
    return selected[0]


def _load_database(handle, entry, receipts):
    with _component(handle, entry, receipts) as reader, BytesIO() as buffer:
        while reader.offset < reader.size:
            buffer.write(reader.take(min(saved_component_stream.BLOCK_SIZE, reader.size - reader.offset)))
        return buffer.getvalue()


def _person(data, layout, ends, index, *, seconds=2.0):
    """Advance only original typed slots; return one requested record and new ends."""
    new = array('I')
    row = None
    frontier = None
    began = time.monotonic()
    if index >= layout.person_count:
        return row, new, {'state': 'outside_declared_PERSON_table', 'checked_prefix_count': len(ends),
                          'declared_person_slots': layout.person_count, 'retry_same_query_to_advance': False}
    if index < len(ends):
        at = ends[index - 1] if index else layout.person_records_offset
        row = saved_population._read_record(data, at, index, include_history=True)
        if row['state'] != 'decoded' or row['end'] != ends[index]:
            raise ValueError('Cached history PERSON extent differs from source')
    else:
        at = ends[-1] if ends else layout.person_records_offset
        for ordinal in range(len(ends), min(index + 1, len(ends) + MAX_ADVANCE)):
            if new and time.monotonic() - began >= seconds:
                break
            value = saved_population._read_record(data, at, ordinal, include_history=ordinal == index)
            if value['state'] == 'unsupported':
                frontier = {'ordinal': ordinal, 'tag_offset': at, 'reason': value.get('reason')}
                break
            at = value['end']
            new.append(at)
            if ordinal == index:
                row = value
    checked = len(ends) + len(new)
    footer = (saved_population._footer(data, new[-1] if new else ends[-1])
              if checked == layout.person_count else {'state': 'not_reached'})
    return row, new, {
        'state': 'requested_original_record_decoded' if row else 'unsupported_frontier' if frontier else 'more_work_required',
        'checked_prefix_count': checked, 'new_records_checked': len(new),
        'declared_person_slots': layout.person_count, 'source_frontier': frontier,
        'retry_same_query_to_advance': row is None and frontier is None,
        'footer': footer,
    }


def _signed(value):
    return value if value < 0x80000000 else value - 0x100000000


def _index(reader, owner):
    if reader.take(8) != LIST_HEADER:
        raise ValueError('Unsupported saved player history list header')
    free = reader.u32()
    if free > MAX_LIST_ENTRIES:
        raise ValueError('History free-offset count exceeds offline budget')
    reader.skip(4 * free)
    owners = reader.u32()
    if owners > MAX_OWNERS or owners > (reader.size - reader.offset) // 4:
        raise ValueError('History owner count exceeds bounded list extent')
    if owner >= owners:
        raise ValueError('Saved PERSON history owner index is outside list')
    selected = []
    total = 0
    for ordinal in range(owners):
        count = reader.u32()
        total += count
        if count > MAX_OWNER_ENTRIES or total > MAX_LIST_ENTRIES:
            raise ValueError('History vector count exceeds offline work budget')
        if ordinal != owner:
            reader.skip(4 * count)
            continue
        previous = 0
        for _ in range(count):
            encoded = reader.u32()
            selected.append(_signed((encoded + previous) & 0xffffffff))
            previous = encoded
    empty_count = reader.u32()
    if empty_count > owners:
        raise ValueError('Invalid saved history empty-owner count')
    for _ in range(empty_count):
        if reader.u32() >= owners:
            raise ValueError('Saved history empty-owner key is outside list')
    width, version = struct.unpack('<IH', reader.take(6))
    if reader.offset != reader.size or (width, version) != (WIDTH, 7):
        raise ValueError('Unsupported saved history list tail or trailing bytes')
    return selected, {'owner_count': owners, 'free_offset_count': free,
                      'empty_owner_count': empty_count, 'all_owner_entry_count': total,
                      'version': 4, 'record_width': width, 'data_version': version,
                      'structure_complete': True, 'other_owner_offsets_validated': False}


def _rows(reader, offsets):
    if reader.take(8) != DATA_HEADER or (reader.size - 8) % WIDTH:
        raise ValueError('Unsupported saved history data header or fixed row extent')
    wanted = sorted(set(value for value in offsets if value >= 0))
    for value in wanted:
        if value % WIDTH or value + 8 + WIDTH > reader.size:
            raise ValueError('Selected history offset is misaligned or outside data component')
    selected = {}
    for value in wanted:
        start = value + 8
        reader.skip(start - reader.offset)
        selected[value] = reader.take(WIDTH)
    reader.skip(reader.size - reader.offset)
    return selected


def _decode(raw):
    prefix = archive_stat_references.decode_prefix(raw)
    if prefix['consumed_bytes'] != 7:
        raise ValueError('Unsupported saved history reference transport for fixed168 row')
    team = prefix['team_reference']['index']
    competition = prefix['competition_reference']['index']
    return {
        **archived_player_statistics.decode_record(raw, prefix),
        'team_reference': {'table': 'TEAM_BASE', 'stored_index': team,
                           'state': 'null_reference' if team is None else 'unresolved_same_snapshot_index'},
        'competition_reference': {'table': 'COMP', 'stored_index': competition,
                                  'state': 'null_reference' if competition is None else 'unresolved_same_snapshot_index'},
    }


def get_history(filename, person_index, expected_snapshot_id, *, years=None, category_codes=None,
                offset=0, limit=50, directory=None):
    years = _filters(years, 65535, 'years')
    categories = _filters(category_codes, len(CATEGORY_LABELS) - 1, 'category_codes')
    if (type(person_index) is not int or not 0 <= person_index < 2**31
            or type(offset) is not int or not 0 <= offset < 2**31
            or type(limit) is not int or not 1 <= limit <= 200):
        raise ValueError('Invalid saved player history index or page')
    if type(expected_snapshot_id) is not str or not expected_snapshot_id:
        raise ValueError('Supply the saved snapshot ID')
    if not saved_population._LOCK.acquire(blocking=False):
        raise ValueError('Another saved population lookup is in progress; retry')
    try:
        with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
            pin = snapshot_catalog.snapshot_id(identity)
            if pin != expected_snapshot_id:
                raise ValueError('Snapshot identity changed since history query was requested')
            root = entries[0].path.split('/')[0]
            receipts = {}
            database_entry = _entry(entries, root, 'game_db.dat')
            data = _load_database(handle, database_entry, receipts)
            digest = bytes.fromhex(receipts['game_db.dat']['raw_sha256'])
            cached = saved_population._LAST_LAYOUT
            layout = replace(cached[1], _data=data) if cached is not None and cached[0] == digest else saved_population.saved_name_vectors.locate(data)
            key = (pin, digest, layout.person_offset, layout.person_count)
            ends = saved_population._PREFIXES.get(key, array('I'))
            row, new, coverage = _person(data, layout, ends, person_index)
            result = {'filename': filename, 'snapshot_id': pin, 'person_index': person_index,
                      'saved_metadata': snapshot_catalog._metadata(handle, entries),
                      'PERSON_coverage': coverage, 'components': receipts,
                      'rows': [], 'offset': offset, 'limit': limit, 'next_offset': None,
                      'owner': None, 'total_indexed_entries': None, 'selected_row_count': None,
                      'filters': {'native_years': None if years is None else sorted(years),
                                  'native_category_codes': None if categories is None else sorted(categories)},
                      'wire_profile_is_conditional': True, 'native_loader_globals_proved': False,
                      'reference_profile': 'conditional_B03_flags2_mode0_switches00_fixed168_prefix7; ambient_settings_unobserved',
                      'year_scope': 'exact_stored_native_year; season_start_or_end_convention_unproved',
                      'coverage': 'indexed_saved_stats_archive_only; no_current_form_or_starting_history_merge'}
            if row is None:
                result.update(state='stopped' if coverage['state'] != 'outside_declared_PERSON_table' else 'unavailable',
                              reason=coverage['state'])
            elif row['signed_tag'] != 2:
                result.update(state='unavailable', reason='unsupported_PERSON_class_for_history_owner',
                              person=saved_population._project(data, layout, row))
            else:
                result['person'] = saved_population._project(data, layout, row)
                owner = row['_history']
                result['owner'] = owner
                list_entry = _entry(entries, root, 'rgman/player_stats_hist_ls.dat')
                data_entry = _entry(entries, root, 'player_stats_hist_dt.cmt')
                if list_entry.uncompressed_size > MAX_LIST_BYTES:
                    raise ValueError('Saved history index exceeds offline byte budget')
                with _component(handle, list_entry, receipts) as reader:
                    offsets, summary = _index(reader, owner['owner_index'])
                with _component(handle, data_entry, receipts) as reader:
                    raw_rows = _rows(reader, offsets)
                rows = []
                matched = 0
                skipped = []
                for entry_index, value in enumerate(offsets):
                    if value < 0:
                        skipped.append({'entry_index': entry_index, 'native_offset': value,
                                        'reason': 'native_negative_offset_skipped'})
                        continue
                    raw = raw_rows[value]
                    decoded = _decode(raw)
                    if years is not None and decoded['native_year'] not in years:
                        continue
                    if categories is not None and decoded['native_category_code'] not in categories:
                        continue
                    if offset <= matched < offset + limit:
                        rows.append({**decoded, 'entry_index': entry_index, 'native_offset': value,
                                     'data_start': value + 8, 'data_end': value + 8 + WIDTH,
                                     'record_sha256': sha256(raw).hexdigest()})
                    matched += 1
                result.update(state='no_history_index' if owner['owner_index'] < 0 else 'available_empty' if not offsets else 'available',
                              reason='native_negative_owner_index' if owner['owner_index'] < 0 else None,
                              rows=rows, index_summary=summary, total_indexed_entries=len(offsets),
                              skipped_entries=skipped, decoded_row_count=len(offsets) - len(skipped),
                              selected_row_count=matched,
                              next_offset=offset + limit if offset + limit < matched else None)
            if len(json.dumps(result, ensure_ascii=True)) > 2 * 1024**2:
                raise ValueError('Saved history response exceeds budget; lower limit')
        # Publish no new prefix/layout until every used component and archive identity passed.
        saved_population._LAST_LAYOUT = (digest, replace(layout, _data=None))
        ends.extend(new)
        saved_population._PREFIXES[key] = ends
        saved_population._PREFIXES.move_to_end(key)
        while len(saved_population._PREFIXES) > saved_population._MAX_CACHES:
            saved_population._PREFIXES.popitem(last=False)
        return result
    finally:
        saved_population._LOCK.release()
