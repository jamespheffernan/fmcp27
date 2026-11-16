"""Bounded name-first discovery in one pinned save; no witness-index dependency.

Names filter source references, never certify a whole PERSON. The ordinary
CE96F0 suffix subset is shared with saved_person_candidates. Other transports,
repair/reordering and unparsed bodies remain outside the search's claim.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
import json
import re
import struct
import unicodedata

from . import (saved_component_stream, saved_name_vectors, saved_person_candidates,
               saved_person_neighbours, saved_person_search, saved_source_cache, snapshot_catalog)

NAMESPACES = {'first_name': 'first', 'surname': 'second', 'common_name': 'common'}
NORMALIZATION = 'NFKD_casefold_remove_combining_marks_strip_outer_whitespace'


@dataclass(frozen=True)
class Budget:
    max_name_rows: int = 2_000_000
    max_name_bytes: int = 64 * 1024**2
    max_name_ids: int = 4096
    max_scan_bytes: int = 512 * 1024**2
    max_byte_work: int = 2 * 1024**3
    max_reference_hits: int = 200_000
    max_prefix_hits: int = 200_000
    max_candidates: int = 4096
    max_candidate_name_bytes: int = 4 * 1024**2
    max_text_bytes: int = 8192
    common_span: int = 8192


def normalize(text):
    """Fold case/combining accents; keep internal spaces and punctuation."""
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(c)).strip()


def _queries(first_name, surname, common_name, match_mode):
    if match_mode not in ('exact', 'prefix', 'substring'):
        raise ValueError('match_mode must be exact, prefix or substring')
    query = {}
    for key, value in zip(NAMESPACES, (first_name, surname, common_name), strict=True):
        if value is None:
            continue
        if not isinstance(value, str) or not 1 <= len(value) <= 256 or not normalize(value):
            raise ValueError('Supply nonempty name parts of at most256 characters')
        query[NAMESPACES[key]] = normalize(value)
    if not query:
        raise ValueError('Supply at least one first_name, surname or common_name')
    return query


def _matches(text, query, mode):
    value = normalize(text)
    return value == query if mode == 'exact' else value.startswith(query) if mode == 'prefix' else query in value


def search_buffer(data, layout, query, match_mode, *, budget=None):
    """Reusable pure bounded discovery; data/layout must share a checked source."""
    budget = Budget() if budget is None else budget
    if not isinstance(budget, Budget) or any(type(getattr(budget, k)) is not int or
                                           getattr(budget, k) < 0 for k in budget.__dataclass_fields__):
        raise ValueError('Invalid saved name-search budget')
    if (not query or any(ns not in NAMESPACES.values() or not isinstance(value, str) or not value
                         for ns, value in query.items()) or match_mode not in ('exact', 'prefix', 'substring')):
        raise ValueError('Invalid normalized saved name query')
    reasons = set()
    work = {'name_rows': 0, 'name_bytes': 0, 'reference_hits': 0, 'prefix_hits': 0,
            'byte_work': 0, 'unrecognized_or_outside_span_hits': 0, 'candidate_name_bytes': 0}
    sets, dictionary = {}, {}
    for namespace, term in query.items():
        ids = set(); matched = 0; complete = True
        for index in range(layout.name_counts[namespace]):
            if work['name_rows'] >= budget.max_name_rows:
                reasons.add('name_rows'); complete = False; break
            raw = layout.lookup_raw(namespace, index)
            work['name_rows'] += 1
            if len(raw) > budget.max_name_bytes - work['name_bytes']:
                reasons.add('name_bytes'); complete = False; break
            work['name_bytes'] += len(raw)
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                reasons.add('unreadable_name_text'); complete = False; continue
            if _matches(text, term, match_mode):
                matched += 1
                if len(ids) < budget.max_name_ids:
                    ids.add(index)
        dictionary[namespace] = {'matching_name_ids': matched, 'complete': complete,
                                 'retained_name_ids': len(ids)}
        if complete and matched <= budget.max_name_ids:
            sets[namespace] = ids
    result = {'candidates': [], 'budget_reasons': [], 'search_complete': False,
              'name_dictionary': dictionary, 'work': work, 'strategy': None}

    def finish():
        result['budget_reasons'] = sorted(reasons)
        result['search_complete'] = not reasons
        return result

    if any(not ids for ids in sets.values()):
        return finish()
    if not sets:
        reasons.add('name_reference_set_budget')
        return finish()
    namespace = min(sets, key=lambda ns: (len(sets[ns]), ns))
    ids = sets[namespace]
    result['anchor_namespace'] = namespace
    lower = layout.person_records_offset + 1
    upper = min(len(data), lower + budget.max_scan_bytes)
    if upper < len(data):
        reasons.add('scan_bytes')
    slot = ('first', 'second', 'common').index(namespace)
    counts = tuple(layout.name_counts[n] for n in ('first', 'second', 'common'))
    wire_budget = saved_person_candidates.SearchBudget(max_text_bytes=budget.max_text_bytes)

    def positions():
        if len(ids) > 16:
            result['strategy'] = 'bounded_common_prefix_pass'
            stop = min(upper, lower + budget.max_byte_work)
            if stop < upper:
                reasons.add('byte_work')
            pieces = []
            for count in counts:
                if count == 0:
                    pieces.append(rb'\xff{4}\x00')
                elif count <= 1 << 24:
                    # Escaped endpoints make every possible byte safe in a class.
                    high = ('%02x' % ((count - 1) >> 16)).encode('ascii')
                    pieces.append(rb'(?:.{2}[\x00-\x' + high + rb']\x00|\xff{4})\x00')
                else:
                    pieces.append(rb'.{4}\x00')
            pattern = re.compile(b'(?=' + b''.join(pieces) + b')', re.DOTALL)
            for match in pattern.finditer(data, lower, stop):
                work['prefix_hits'] += 1
                work['byte_work'] = min(stop - lower, match.start() - lower + 15)
                if work['prefix_hits'] > budget.max_prefix_hits:
                    reasons.add('prefix_hits'); return
                position = match.start() + 5 * slot
                if struct.unpack_from('<I', data, position)[0] in ids:
                    yield position
            work['byte_work'] = stop - lower
            return
        result['strategy'] = 'bounded_literal_name_reference_scans'
        for index in sorted(ids):
            needle = struct.pack('<IB', index, 0)
            position = lower
            while position < upper:
                remaining = budget.max_byte_work - work['byte_work']
                if remaining < 5:
                    reasons.add('byte_work'); return
                stop = min(upper, position + remaining)
                found = data.find(needle, position, stop)
                work['byte_work'] += stop - position if found < 0 else found - position + 5
                if found < 0:
                    if stop < upper:
                        reasons.add('byte_work'); return
                    break
                yield found
                position = found + 1

    seen = set()
    for position in positions():
        if work['reference_hits'] >= budget.max_reference_hits:
            reasons.add('reference_hits'); break
        work['reference_hits'] += 1
        start = position - 5 * slot
        if start < lower or start + 15 > upper:
            continue
        values = struct.unpack_from('<iBiBiB', data, start)
        indices = values[::2]
        if values[1::2] != (0, 0, 0) or any(i < -1 or i >= count for i, count in zip(indices, counts, strict=True)):
            work['unrecognized_or_outside_span_hits'] += 1; continue
        names = []
        matched = True
        for ns, index in zip(('first', 'second', 'common'), indices, strict=True):
            raw = None if index == -1 else layout.lookup_raw(ns, index)
            if raw is not None and len(raw) > budget.max_text_bytes:
                reasons.add('name_text_bytes'); matched = False; break
            try:
                text = None if raw is None else raw.decode('utf-8')
            except UnicodeDecodeError:
                text = None
            if ns in query and (text is None or not _matches(text, query[ns], match_mode)):
                matched = False; break
            names.append(None if raw is None else {'text': text, 'raw_hex': raw.hex()})
        if not matched:
            continue
        try:
            end = saved_person_candidates._common_end(data, start, min(upper, start + budget.common_span), wire_budget)
        except saved_person_candidates._BudgetStop:
            reasons.add('common_text_bytes'); continue
        except saved_person_candidates._Incomplete:
            work['unrecognized_or_outside_span_hits'] += 1; continue
        if end + 20 > upper or (start, end) in seen:
            continue
        if len(result['candidates']) >= budget.max_candidates:
            reasons.add('candidates'); break
        name_bytes = sum(len(name['raw_hex']) // 2 for name in names if name is not None)
        if name_bytes > budget.max_candidate_name_bytes - work['candidate_name_bytes']:
            reasons.add('candidate_name_bytes'); break
        work['candidate_name_bytes'] += name_bytes
        seen.add((start, end))
        index, primary, secondary = struct.unpack_from('<III', data, end + 8)
        result['candidates'].append({
            'common_start': start, 'common_end': end, 'identity_offset': end + 8,
            'end': end + 20, 'identity': {'stored_index': index, 'native_id_word': primary, 'secondary_word': secondary},
            'stored_index_inside_declared_population': index < layout.person_count,
            'name_indices': list(indices), 'names': names,
            'next_tag': struct.unpack_from('<b', data, end + 20)[0] if end + 20 < len(data) else None,
            'certified_person_record': False,
        })
    return finish()


@contextmanager
def _source(filename, expected_snapshot_id, directory, *, locate=None):
    snapshot_catalog.check_filename(filename)
    if not isinstance(expected_snapshot_id, str) or not expected_snapshot_id:
        raise ValueError('Supply expected_snapshot_id from fm_list_saved_careers')
    with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
        pin = snapshot_catalog.snapshot_id(identity)
        if pin != expected_snapshot_id:
            raise ValueError('Snapshot identity changed since the name search was requested')
        root = entries[0].path.split('/')[0]
        selected = [e for e in entries if e.path == root + '/game_db.dat']
        if len(selected) != 1:
            raise ValueError('Saved snapshot requires one root game_db.dat')
        if selected[0].uncompressed_size > 512 * 1024**2:
            raise ValueError('Saved database exceeds the bounded name-search buffer')
        if not saved_person_search._BUFFER_SLOT.acquire(blocking=False):
            raise ValueError('Another saved PERSON lookup is in progress; retry after it finishes')
        try:
            with saved_source_cache.source(handle, selected[0], pin) as cached:
                if cached is not None:
                    layout = (locate or saved_name_vectors.locate)(cached)
                    yield cached, layout, pin, snapshot_catalog._metadata(handle, entries)
                else:
                    with saved_component_stream.open_component(handle, selected[0]) as reader:
                        with BytesIO() as buffer:
                            while reader.offset < reader.size:
                                buffer.write(reader.take(min(saved_component_stream.BLOCK_SIZE, reader.size - reader.offset)))
                            if reader.source.read(1) or not reader.source.finished:
                                raise ValueError('Saved database frame did not end at its declared extent')
                            data = buffer.getvalue()
                        layout = (locate or saved_name_vectors.locate)(data)
                        yield data, layout, pin, snapshot_catalog._metadata(handle, entries)
        finally:
            saved_person_search._BUFFER_SLOT.release()


def find_people(filename, expected_snapshot_id, *, first_name=None, surname=None, common_name=None,
                match_mode='exact', offset=0, limit=20, directory=None, _budget=None):
    """Find matching name-reference candidates, never claim whole-population nil."""
    query = _queries(first_name, surname, common_name, match_mode)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('Supply a nonnegative offset and limit from1 to50')
    with _source(filename, expected_snapshot_id, directory) as (data, layout, pin, metadata):
        found = search_buffer(data, layout, query, match_mode, budget=_budget)
        groups = {}
        for witness in found['candidates']:
            groups.setdefault(witness['identity']['stored_index'], []).append(witness)
        keys = sorted(groups)
        page_keys = keys[offset:offset + limit]
        inputs = [{'person_index': index, 'candidates': groups[index],
                   'search_complete': found['search_complete'], 'budget_reasons': found['budget_reasons'],
                   'state': 'matching_name_candidates', 'evidence_scope': dict(saved_person_candidates.SCOPE)}
                  for index in page_keys if index < layout.person_count]
        ranked = saved_person_neighbours.corroborate_candidates(data, layout, inputs) if inputs else []
        by_index = {r['person_index']: r for r in ranked}
        people = []
        for index in page_keys:
            if index in by_index:
                row = by_index[index]
                projected = saved_person_search._project(row, True, 0, 100)
                projected['matching_name_witnesses_only'] = True
                projected['state'] = 'ambiguous_name_witnesses' if projected['candidate_count'] > 1 else 'matching_name_candidate'
                projected['candidate_projection_complete'] = projected['alternatives_omitted'] == 0
                projected['candidate_projection_limit'] = 100
                projected['alternative_lookup'] = {'tool': 'fm_get_saved_person_name_candidates', 'person_index': index, 'include_alternatives': True, 'same_snapshot_required': True, 'scope': 'Independent per-index search; may also expose witnesses outside this name conjunction'}
                projected['certified_person_record'] = False
                projected['profile_lookup_requires_independent_revalidation'] = True
                people.append(projected)
            else:
                people.append({'person_index': None, 'raw_stored_index': index,
                               'state': 'unplaced_or_repair_candidate', 'candidates': groups[index],
                               'certified_person_record': False})
        complete = found['search_complete']
        result = {
            'source': 'on-disk save snapshot', 'filename': filename, 'snapshot_id': pin,
            'saved_metadata': metadata, 'query': {'parts': {k:v for k,v in zip(NAMESPACES, (first_name,surname,common_name), strict=True) if v is not None}, 'normalized_parts': query, 'match_mode': match_mode, 'normalization': NORMALIZATION},
            'state': 'stopped' if not complete else 'no_matches_in_supported_scope' if not keys else
                     'ambiguous_candidates' if len(keys) > 1 or any(len(v) > 1 for v in groups.values()) else 'matched_candidates',
            'search_complete_in_supported_scope': complete, 'whole_population_complete': False,
            'budget_reasons': found['budget_reasons'], 'work': found['work'],
            'budgets': {k:getattr(_budget or Budget(), k) for k in Budget.__dataclass_fields__},
            'name_dictionary': found['name_dictionary'], 'strategy': found['strategy'],
            'matching_stored_index_groups': len(keys), 'matching_suffix_witnesses': len(found['candidates']),
            'offset': offset, 'limit': limit, 'next_offset': offset + len(page_keys) if offset + len(page_keys) < len(keys) else None,
            'people': people,
            'candidate_projections_complete_for_page': all(p.get('candidate_projection_complete', True) for p in people),
            'coverage': {**saved_person_candidates.SCOPE, 'layout_provenance': layout.provenance,
                         'identity_scope': 'stored suffix words, not certified continuous PERSON membership',
                         'common_body_span_limit_bytes': (_budget or Budget()).common_span,
                         'common_body_inline_text_limit_bytes': (_budget or Budget()).max_text_bytes,
                         'larger_common_bodies': 'outside_supported_scope; an unrecognized hit may be a valid longer body',
                         'unique_stored_index_is_not_unique_name_or_identity': True,
                         'certification': 'continuous_population_decoder_not_applied',
                         'absence_means': 'no matching UTF8 ordinary-zero-marker suffix within the declared span/text bounds in the completed supported scan only',
                         'other_name_transports_and_unparsed_record_types': 'outside_supported_scope'},
        }
        if len(json.dumps(result, ensure_ascii=True).encode('ascii')) > 2 * 1024**2:
            raise ValueError('Saved name-search response exceeds output budget; use a smaller limit')
    return result
