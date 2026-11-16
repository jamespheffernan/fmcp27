"""Closed-pair structural inventory; source-local owners and opaque fixed rows."""
from dataclasses import dataclass
from hashlib import sha256
import json
import struct
from threading import Lock

from . import saved_fixed_history_index as fixed, snapshot_catalog
from .saved_player_history import _component


@dataclass(frozen=True)
class Family:
    index_path: str
    data_path: str
    width: int
    version: int


FAMILIES = {
    'award_club_hist': Family('award_club_hist_ls.dat', 'award_club_hist_dt.cmt', 37, 1),
    'award_year_hist': Family('award_year_hist_ls.dat', 'award_year_hist_dt.cmt', 82, 1),
    'injury_histories': Family('injury_histories_ls.dat', 'injury_histories_dt.cmt', 16, 2),
    'non_pl_hist': Family('non_pl_hist_ls.dat', 'non_pl_hist_dt.cmt', 20, 3),
    'person_record_history': Family('person_record_history_ls.dat', 'person_record_history_dt.cmt', 42, 2),
    'pl_hist': Family('pl_hist_ls.dat', 'pl_hist_dt.cmt', 40, 3),
    'comp_history': Family('rgman/comp_history_ls.dat', 'comp_history_dt.cmt', 55, 3),
    'extended_comp_records': Family('rgman/extended_comp_records_ls.dat', 'extended_comp_records_dt.cmt', 751, 5),
    'player_stats_hist': Family('rgman/player_stats_hist_ls.dat', 'player_stats_hist_dt.cmt', 168, 7),
    'tc_best_eleven_history': Family('tc_best_eleven_history_ls.dat', 'tc_best_eleven_history_dt.cmt', 509, 2),
    'tc_cup_history': Family('tc_cup_history_ls.dat', 'tc_cup_history_dt.cmt', 18, 1),
    'tc_extended_club_records_history': Family('tc_extended_club_records_history_ls.dat', 'tc_extended_club_records_history_dt.cmt', 848, 5),
    'tc_extended_nation_records_history': Family('tc_extended_nation_records_history_ls.dat', 'tc_extended_nation_records_history_dt.cmt', 707, 5),
    'tc_history': Family('tc_history_ls.dat', 'tc_history_dt.cmt', 21, 1),
    'tc_league_history': Family('tc_league_history_ls.dat', 'tc_league_history_dt.cmt', 24, 1),
    'tc_manager_history': Family('tc_manager_history_ls.dat', 'tc_manager_history_dt.cmt', 31, 2),
}
MAX_FAMILY_ENTRIES = 2_000_000
MAX_OWNERS = 2_000_000
MAX_FAMILY_SLOTS = 5_000_000
MAX_QUERY_WORK = 12_000_000
MAX_INDEX_BYTES = 32 * 1024**2
MAX_QUERY_RAW_BYTES = 512 * 1024**2
MAX_QUERY_PACKED_BYTES = 256 * 1024**2
_LOCK = Lock()


class _Unsupported(ValueError):
    pass


def _words(reader, count):
    if count > (reader.size - reader.offset) // 4:
        raise ValueError('Truncated history inventory vector')
    while count:
        amount = min(count, 4096)
        yield from (value for (value,) in struct.iter_unpack('<i', reader.take(4 * amount)))
        count -= amount


def _scan(reader, spec, data_size, owner, offset, limit, work):
    """Validate all offsets with bounded slot/owner bitsets, retaining one page."""
    if reader.size > MAX_INDEX_BYTES:
        raise _Unsupported('History index exceeds offline byte budget')
    if reader.take(8) != fixed.LIST_HEADER:
        raise _Unsupported('Unsupported history list header')
    slots, remainder = divmod(data_size - 8, spec.width)
    if data_size < 8 or slots > MAX_FAMILY_SLOTS:
        raise _Unsupported('History data extent exceeds offline slot budget')
    marked = bytearray(slots)
    geometry_error = 'History data fixed-row extent mismatch' if remainder else None

    def count():
        value = reader.u32()
        if value > MAX_FAMILY_ENTRIES:
            raise ValueError('History inventory count exceeds offline family budget')
        work[0] += value
        if work[0] > MAX_QUERY_WORK:
            raise ValueError('History inventory aggregate work budget exceeded')
        return value

    def mark(value, kind):
        nonlocal geometry_error
        if value < 0 or value % spec.width or value // spec.width >= slots:
            geometry_error = 'History offset is outside aligned component slots'
            return
        marked[value // spec.width] |= kind

    free_count = count()
    for value in _words(reader, free_count):
        mark(value, 1)
    owners = reader.u32()
    work[0] += owners
    if (owners > MAX_OWNERS or owners > max(0, (reader.size - reader.offset - 10) // 4)
            or work[0] > MAX_QUERY_WORK):
        raise ValueError('History inventory owner count exceeds bounded source/work')
    empty = bytearray(owners)
    entries = 0
    negative = 0
    selected = []
    owner_count = None
    for ordinal in range(owners):
        n = count()
        entries += n
        if entries > MAX_FAMILY_ENTRIES:
            raise ValueError('History inventory entries exceed offline family budget')
        if n == 0:
            empty[ordinal] = 1
        if ordinal == owner:
            owner_count = n
        previous = 0
        for entry_index, encoded in enumerate(_words(reader, n)):
            value = (encoded + previous) & 0xffffffff
            previous = encoded
            if value >= 0x80000000:
                value -= 0x100000000
                negative += 1
            else:
                mark(value, 2)
            if ordinal == owner and offset <= entry_index < offset + limit:
                selected.append((entry_index, value))
    listed_empty = count()
    if listed_empty > owners:
        raise ValueError('History empty-owner count exceeds owner table')
    for value in _words(reader, listed_empty):
        if not 0 <= value < owners or empty[value] != 1:
            raise ValueError('Invalid or duplicate history empty-owner entry')
        empty[value] = 2
    width, version = struct.unpack('<IH', reader.take(6))
    if reader.offset != reader.size:
        raise ValueError('Trailing bytes after history inventory index')
    if (width, version) != (spec.width, spec.version):
        raise _Unsupported(f'Unsupported history profile width={width}, version={version}')
    if geometry_error:
        raise ValueError(geometry_error)
    overlap = marked.count(3)
    indexed_slots = marked.count(2) + overlap
    free_slots = marked.count(1) + overlap
    summary = {
        'owner_count': owners, 'empty_owner_count': empty.count(1) + listed_empty,
        'listed_empty_owner_count': listed_empty,
        'indexed_entry_count': entries, 'negative_indexed_entries': negative,
        'indexed_record_reference_count': entries - negative,
        'indexed_record_count': indexed_slots,
        'duplicate_indexed_references': entries - negative - indexed_slots,
        'free_offset_count': free_count, 'free_record_count': free_slots,
        'duplicate_free_offsets': free_count - free_slots,
        'physical_record_count': slots, 'unaccounted_record_count': marked.count(0),
        'free_indexed_overlap_count': overlap,
        'partition_complete_and_disjoint': overlap == 0 and marked.count(0) == 0,
        'all_offsets_validated': True,
    }
    return summary, selected, owner_count


def _one(handle, by_path, root, name, spec, owner, offset, limit, work):
    paths = (root + '/' + spec.index_path, root + '/' + spec.data_path)
    entries = [by_path.get(path, []) for path in paths]
    row = {'family': name, 'index_path': spec.index_path, 'data_path': spec.data_path,
           'expected_record_width': spec.width, 'expected_data_version': spec.version,
           'owner_namespace': 'source_local_family_ordinal; no_PERSON_or_entity_mapping',
           'row_semantics': 'opaque_fixed_width_source_bytes', 'counts': None,
           'components': {}, 'selected_owner': None}
    if any(len(found) != 1 for found in entries):
        row.update(state='missing_components', missing=[path for path, found in zip(paths, entries) if not found],
                   ambiguous=[path for path, found in zip(paths, entries) if len(found) > 1])
        return row
    index_entry, data_entry = (found[0] for found in entries)
    selected = []
    owner_count = None
    unsupported = None
    with _component(handle, index_entry, row['components']) as reader:
        try:
            summary, selected, owner_count = _scan(reader, spec, data_entry.uncompressed_size,
                                                   owner, offset, limit, work)
        except _Unsupported as error:
            unsupported = str(error)
            reader.skip(reader.size - reader.offset)
    with _component(handle, data_entry, row['components']) as reader:
        if unsupported is not None:
            reader.skip(reader.size - reader.offset)
            raw = {}
        else:
            try:
                raw = fixed.read_rows(reader, [value for _, value in selected],
                                      width=spec.width, data_version=spec.version)
            except ValueError as error:
                if not str(error).startswith('Unsupported history data header'):
                    raise
                unsupported = str(error)
                reader.skip(reader.size - reader.offset)
                raw = {}
    if unsupported is not None:
        row.update(state='unsupported', reason=unsupported)
        return row
    row['counts'] = summary
    row['state'] = ('inconsistent_partition' if not summary['partition_complete_and_disjoint'] else
                    'empty_data' if summary['physical_record_count'] == 0 else
                    'all_slots_free' if summary['indexed_record_count'] == 0
                    and summary['free_record_count'] else 'indexed')
    if owner is not None:
        values = []
        for entry_index, value in selected:
            entry = {'entry_index': entry_index, 'stored_offset': value}
            if value < 0:
                entry.update(state='negative_offset_no_record', raw_hex=None)
            else:
                content = raw[value]
                entry.update(state='opaque_source_record', raw_hex=content.hex(),
                             source_component=spec.data_path, data_start=8 + value,
                             data_end=8 + value + spec.width,
                             record_sha256=sha256(content).hexdigest())
            values.append(entry)
        row['selected_owner'] = {
            'owner_index': owner,
            'state': 'outside_owner_table' if owner_count is None else 'empty_owner' if owner_count == 0 else 'indexed_owner',
            'total_entry_count': owner_count, 'offset': offset, 'limit': limit,
            'entries': values,
            'next_offset': offset + limit if owner_count is not None and offset + limit < owner_count else None,
        }
    return row


def get_inventory(filename, expected_snapshot_id, *, family=None, owner_index=None,
                  offset=0, limit=20, directory=None):
    if (family is not None and (type(family) is not str or family not in FAMILIES)):
        raise ValueError('Unknown allowlisted history family')
    if (owner_index is not None and (type(owner_index) is not int or not 0 <= owner_index < 2**31)):
        raise ValueError('Expected a nonnegative source-local owner index')
    if owner_index is not None and family is None:
        raise ValueError('A source-local owner index requires its history family')
    if (type(offset) is not int or not 0 <= offset < 2**31
            or type(limit) is not int or not 1 <= limit <= 200
            or offset and owner_index is None):
        raise ValueError('Invalid raw history page; offset requires an owner')
    if type(expected_snapshot_id) is not str or not expected_snapshot_id:
        raise ValueError('Supply expected snapshot ID')
    if not _LOCK.acquire(blocking=False):
        raise ValueError('Another saved history inventory is in progress; retry')
    try:
        with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
            pin = snapshot_catalog.snapshot_id(identity)
            if pin != expected_snapshot_id:
                raise ValueError('Snapshot identity changed before history inventory')
            root = entries[0].path.split('/')[0]
            by_path = {}
            for entry in entries:
                by_path.setdefault(entry.path, []).append(entry)
            names = list(FAMILIES) if family is None else [family]
            selected_entries = [by_path.get(root + '/' + path, [])
                                for name in names
                                for path in (FAMILIES[name].index_path, FAMILIES[name].data_path)]
            if (sum(found[0].uncompressed_size for found in selected_entries if len(found) == 1) > MAX_QUERY_RAW_BYTES
                    or sum(found[0].compressed_size for found in selected_entries if len(found) == 1) > MAX_QUERY_PACKED_BYTES):
                raise ValueError('History inventory aggregate component byte budget exceeded')
            work = [0]
            families = [_one(handle, by_path, root, name, FAMILIES[name], owner_index,
                             offset, limit, work) for name in names]
            supported = {'indexed', 'empty_data', 'all_slots_free'}
            result = {
                'filename': filename, 'snapshot_id': pin,
                'saved_metadata': snapshot_catalog._metadata(handle, entries),
                'families': families, 'allowlisted_family_count': len(FAMILIES),
                'requested_family_count': len(names),
                'all_requested_pairs_validated': all(row['state'] in supported for row in families),
                'coverage': 'closed16_family_allowlist_only; other_components_not_surveyed',
                'owner_scope': 'source_local_history_owner_ordinal_not_PERSON_or_native_ID',
                'semantics': 'structural_counts_and_opaque_bytes; domain_queries_preserve_football_meaning',
                'native_loader_globals_proved': False,
            }
            if len(json.dumps(result, ensure_ascii=True)) > 2 * 1024**2:
                raise ValueError('History inventory response exceeds byte budget; lower raw page limit')
        return result
    finally:
        _LOCK.release()
