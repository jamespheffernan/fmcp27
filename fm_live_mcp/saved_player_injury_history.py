"""Portable source-bound saved injury histories; current availability is unassessed."""
from array import array
from dataclasses import replace
from hashlib import sha256
import json
import time

from . import (saved_player_history as transport, saved_fixed_history_index as fixed,
               saved_injury_history_records as codec, saved_population, snapshot_catalog,
               saved_database_header, saved_database_tables, saved_database,
               saved_club_records, saved_competition_records, saved_currency_records,
               saved_name_vectors, saved_injury_labels)
from .saved_component_stream import Reader

MAX_ADVANCE = 10_000
MAX_INJURY_DEFINITIONS = 100_000


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
        row = saved_population._read_record(data, at, index)
        if row['state'] != 'decoded' or row['end'] != ends[index]:
            raise ValueError('Cached history PERSON extent differs from source')
    else:
        at = ends[-1] if ends else layout.person_records_offset
        for ordinal in range(len(ends), min(index + 1, len(ends) + MAX_ADVANCE)):
            if new and time.monotonic() - began >= seconds:
                break
            value = saved_population._read_record(data, at, ordinal)
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


def _definitions(data, wanted):
    if not wanted:
        return {}, {'state': 'not_required_for_selected_rows'}
    reader = Reader(saved_name_vectors._Source(data), len(data))
    saved_database_header.read_header(reader)
    saved_database_tables.reach_clubs(reader)
    for label, decode in [('CLUB', saved_club_records.read_club),
                          ('COMP', saved_competition_records.read_competition),
                          ('CONTINENT', saved_currency_records.skip_continent),
                          ('CURRENCY', saved_currency_records.read_currency)]:
        saved_database.skip_table(reader, label, decode)
    table_start = reader.offset
    selected = {}

    def injury(reader, ordinal, kind):
        if kind != 0:
            raise ValueError('Unsupported saved INJURY subtype')
        start = reader.offset - 1
        reader.skip(35)
        stored, native, secondary = reader.u32(), reader.u32(), reader.u32()
        if stored != ordinal:
            raise ValueError('Saved INJURY canonical ordinal differs')
        if ordinal in wanted:
            selected[ordinal] = {'database_index': ordinal, 'native_id': native,
                                 'secondary_id': secondary, 'display_name': None,
                                 'name_state': 'not_serialized_in_checked_row',
                                 'source_start': start, 'source_end': reader.offset,
                                 'record_sha256': sha256(memoryview(data)[start:reader.offset]).hexdigest()}
        return ordinal

    count = 0
    for _ in saved_database.table(reader, 'INJURY', injury, max_slots=MAX_INJURY_DEFINITIONS):
        count += 1
    return selected, {'state': 'complete_same_snapshot_canonical_table', 'count': count,
                      'start': table_start, 'end': reader.offset,
                      'sha256': sha256(memoryview(data)[table_start:reader.offset]).hexdigest()}


def _injury_ids(values):
    if values is None:
        return None
    if (not isinstance(values, list) or not 1 <= len(values) <= 100 or
            any(type(v) is not int or not 0 <= v < 1 << 32 for v in values)):
        raise ValueError('injury_native_ids must contain 1–100 unsigned native IDs')
    return set(values)


def _components(entries, root):
    selected = {}
    missing = []
    for name in ('injury_histories_ls.dat', 'injury_histories_dt.cmt'):
        found = [entry for entry in entries if entry.path == root + '/' + name]
        if len(found) > 1:
            raise ValueError('Ambiguous saved injury-history component')
        if not found:
            missing.append(name)
        else:
            selected[name] = found[0]
    return selected, missing


def _enrich_installed_names(result):
    """Keep optional installed text separate from every saved identity field."""
    resource = saved_injury_labels.load_english_injury_labels()
    result['installed_injury_labels'] = {key: value for key, value in resource.items() if key != 'labels'}
    for row in result['rows']:
        identity = row['injury_reference']['identity']
        label = resource['labels'].get(identity['native_id']) if identity is not None else None
        if identity is None:
            state = 'unresolved_saved_reference'
        elif resource['status'] != 'available':
            state = 'resource_' + resource['status']
        else:
            state = 'available' if label is not None else 'native_id_not_in_resource'
        row['installed_injury_label'] = {
            'state': state, 'source': 'installed_database_baseline',
            'name': label['name'] if label is not None else None,
            'sentence_name': label['sentence_name'] if label is not None else None,
            'name_flag': label['name_flag'] if label is not None else None,
            'sentence_name_flag': label['sentence_name_flag'] if label is not None else None,
        }
    result['limitations'][1] = 'Saved injury names, raw value units and flags remain unverified.'
    result['limitations'].append('Installed English injury labels are separate database 2600 baseline text; career locale and overrides are unverified.')


def get_injury_history(filename, person_index, expected_snapshot_id, *, date_from=None,
                       date_to=None, injury_native_ids=None, offset=0, limit=50,
                       include_installed_names=False, directory=None):
    """Read one same-save original PERSON's retained injury-history vector.

    Dates filter the stored DATE projection inclusively. Unknown dates/references
    remain explicit; they are counted separately when a requested filter cannot
    classify them. Retained history does not report current injury/availability.
    Optional English labels are attributed to the installed database baseline.
    """
    if type(include_installed_names) is not bool:
        raise ValueError('include_installed_names must be a Boolean')
    date_from = codec.date_filter(date_from, 'date_from')
    date_to = codec.date_filter(date_to, 'date_to')
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValueError('date_from must not follow date_to')
    ids = _injury_ids(injury_native_ids)
    if (type(person_index) is not int or not 0 <= person_index < 1 << 31 or
            type(offset) is not int or not 0 <= offset < 1 << 31 or
            type(limit) is not int or not 1 <= limit <= 200):
        raise ValueError('Invalid saved injury-history PERSON index or page')
    if type(expected_snapshot_id) is not str or not expected_snapshot_id:
        raise ValueError('Supply the same-save snapshot ID')
    if not saved_population._LOCK.acquire(blocking=False):
        raise ValueError('Another saved population lookup is in progress; retry')
    try:
        with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
            pin = snapshot_catalog.snapshot_id(identity)
            if pin != expected_snapshot_id:
                raise ValueError('Snapshot identity changed since injury-history query')
            root = entries[0].path.split('/')[0]
            receipts = {}
            data = transport._load_database(handle, transport._entry(entries, root, 'game_db.dat'), receipts)
            digest = bytes.fromhex(receipts['game_db.dat']['raw_sha256'])
            cached = saved_population._LAST_LAYOUT
            layout = (replace(cached[1], _data=data) if cached is not None and cached[0] == digest
                      else saved_population.saved_name_vectors.locate(data))
            key = (pin, digest, layout.person_offset, layout.person_count)
            ends = saved_population._PREFIXES.get(key, array('I'))
            person, new, coverage = _person(data, layout, ends, person_index)
            result = {'filename': filename, 'snapshot_id': pin, 'person_index': person_index,
                      'saved_metadata': snapshot_catalog._metadata(handle, entries),
                      'PERSON_coverage': coverage, 'components': receipts, 'person': None,
                      'owner': None, 'rows': [], 'offset': offset, 'limit': limit, 'next_offset': None,
                      'total_indexed_entries': None, 'decoded_row_count': None, 'selected_row_count': None,
                      'filters': {'date_from': date_from, 'date_to': date_to,
                                  'injury_native_ids': None if ids is None else sorted(ids)},
                      'date_scope': codec.DATE_SCOPE,
                      'coverage': 'selected_same_save_indexed_injury_history_only',
                      'wire_profile_is_conditional': True, 'native_loader_globals_proved': False,
                      'current_availability': {'state': 'not_assessed_by_history_source', 'value': None},
                      'limitations': ['Retained rows do not establish complete injury history, current injury or medical clearance.',
                                      'Injury names and raw value/flag meanings remain unverified.',
                                      'Only the proved regular PLAYER owner route is supported.']}
            if person is None:
                result.update(state='unavailable' if coverage['state'] == 'outside_declared_PERSON_table' else 'stopped',
                              reason=coverage['state'])
            elif person['signed_tag'] != 2:
                result.update(state='unavailable', reason='unsupported_PERSON_class_for_injury_owner',
                              person=saved_population._project(data, layout, person))
            else:
                result['person'] = saved_population._project(data, layout, person)
                owner = codec.owner(data, person)
                result['owner'] = owner
                components, missing = _components(entries, root)
                if missing:
                    result.update(state='unavailable', reason='injury_history_components_missing', missing_components=missing)
                else:
                    with transport._component(handle, components['injury_histories_ls.dat'], receipts) as reader:
                        offsets, summary = fixed.read_index(reader, owner['owner_index'], width=codec.WIDTH, data_version=codec.VERSION)
                    with transport._component(handle, components['injury_histories_dt.cmt'], receipts) as reader:
                        raw_rows = fixed.read_rows(reader, offsets, width=codec.WIDTH, data_version=codec.VERSION)
                    result['index_summary'] = summary
                    if summary['state'] == 'outside_owner_table':
                        result.update(state='unavailable', reason='owner_key_outside_saved_index')
                    else:
                        decoded = {at: codec.decode(raw) for at, raw in raw_rows.items()}
                        wanted = {row['injury_reference']['stored_index'] for row in decoded.values()
                                  if row['injury_reference']['stored_index'] >= 0}
                        definitions, table = _definitions(data, wanted)
                        skipped, rows = [], []
                        matched = unknown = known_excluded = 0
                        for entry_index, at in enumerate(offsets):
                            if at < 0:
                                skipped.append({'entry_index': entry_index, 'native_offset': at,
                                                'reason': 'native_negative_offset_skipped'})
                                continue
                            row = decoded[at]
                            injury_index = row['injury_reference']['stored_index']
                            definition = definitions.get(injury_index)
                            ref = {**row['injury_reference'],
                                   'state': 'same_snapshot_canonical' if definition is not None else
                                            'native_null_reference' if injury_index < 0 else 'outside_same_snapshot_table',
                                   'identity': definition}
                            day = row['stored_date']['value']
                            known_fail = ((day is not None and ((date_from is not None and day < date_from) or
                                                               (date_to is not None and day > date_to))) or
                                          (ids is not None and definition is not None and definition['native_id'] not in ids))
                            unavailable = ((day is None and (date_from is not None or date_to is not None)) or
                                           (ids is not None and definition is None))
                            if known_fail:
                                known_excluded += 1
                                continue
                            if unavailable:
                                unknown += 1
                                continue
                            if offset <= matched < offset + limit:
                                rows.append({**row, 'injury_reference': ref, 'entry_index': entry_index,
                                             'native_offset': at, 'data_start': at + 8, 'data_end': at + 8 + codec.WIDTH,
                                             'record_sha256': sha256(raw_rows[at]).hexdigest()})
                            matched += 1
                        result.update(state='no_history_index' if owner['owner_index'] < 0 else 'available_empty' if not offsets else 'available',
                                      reason='native_negative_owner_index' if owner['owner_index'] < 0 else None,
                                      rows=rows, total_indexed_entries=len(offsets), skipped_entries=skipped,
                                      decoded_row_count=len(offsets) - len(skipped), selected_row_count=matched,
                                      filter_unknown_count=unknown, known_excluded_count=known_excluded,
                                      injury_definition_table=table,
                                      next_offset=offset + limit if offset + limit < matched else None)
            if include_installed_names:
                _enrich_installed_names(result)
            if len(json.dumps(result, ensure_ascii=True)) > 2 * 1024**2:
                raise ValueError('Saved injury-history response exceeds budget; lower limit')
        saved_population._LAST_LAYOUT = (digest, replace(layout, _data=None))
        ends.extend(new)
        saved_population._PREFIXES[key] = ends
        saved_population._PREFIXES.move_to_end(key)
        while len(saved_population._PREFIXES) > saved_population._MAX_CACHES:
            saved_population._PREFIXES.popitem(last=False)
        return result
    finally:
        saved_population._LOCK.release()
