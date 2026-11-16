"""Bounded typed PERSON name search, independent of suffix-candidate discovery.

The process-private index retains normalized stored fields and canonical ends,
not source buffers. Every request reacquires the complete checked source; cached
matches are decoded again before publication. Effective inline-name resolution,
unprojected names and native loader globals remain explicitly unproved.
"""
from array import array
from collections import OrderedDict
from dataclasses import dataclass, replace
from hashlib import sha256
import json
import struct
import time

from . import saved_population as population, saved_person_name_search as names
from .saved_scouting_query import _token, _restore

_MAX_CACHES = 2
_MAX_INDEX_BYTES = 128 * 1024**2
_MAX_RESPONSE_BYTES = 2 * 1024**2
_INDEXES = OrderedDict()
_CATEGORIES = ('matched', 'predicate_excluded', 'name_unavailable', 'unsupported')
_FIELD_STATES = ('decoded', 'known_null', 'out_of_range', 'unsupported_encoding',
                 'inline_effective_unresolved', 'unprojected_name')
_UNKNOWN = frozenset(_FIELD_STATES[2:])
_SELECTORS = {'first_name':'first', 'surname':'second', 'common_name':'common', 'any_name':'any'}
_SCOPE = ('Canonical typed original PERSON records under the supported conditional wire profile. '
          'Search decoded stored parts and retained literal/pointer fields; no synthesized display '
          'name, effective inline deduplication, unprojected virtual name or complete alias set is inferred. '
          'A full record scan does not establish absence across all possible PERSON names.')


@dataclass(frozen=True, slots=True)
class _Entry:
    end: int
    tag: int
    native: int
    secondary: int
    fields: tuple


@dataclass(slots=True)
class _Index:
    entries: list
    accounted_bytes: int = 0


def _query(first_name, surname, common_name, any_name, mode):
    if mode not in ('exact', 'prefix', 'substring'):
        raise ValueError('match_mode must be exact, prefix or substring')
    original, normalized = {}, {}
    for key, value in zip(_SELECTORS, (first_name,surname,common_name,any_name), strict=True):
        if value is None:
            continue
        if type(value) is not str or not 1 <= len(value) <= 256 or not names.normalize(value):
            raise ValueError('Supply nonempty name selectors of at most256 characters')
        original[key] = value
        normalized[_SELECTORS[key]] = names.normalize(value)
    if not normalized:
        raise ValueError('Supply at least one name selector')
    return original, normalized


def _details(projected):
    """Normalize availability, without promoting unresolved inline text."""
    result = []
    for field in projected['name_fields']:
        state = field['state']
        if state == 'decoded':
            status = 'decoded'
        elif state in ('null_reference', 'native_null_reference'):
            status = 'known_null'
        elif state in ('out_of_range', 'unsupported_encoding'):
            status = state
        elif state == 'stored_inline_reference':
            status = 'inline_effective_unresolved'
        else:
            raise ValueError('Unsupported typed name availability state')
        text = field.get('text') if status == 'decoded' else None
        if status == 'decoded' and type(text) is not str:
            raise ValueError('Decoded typed name has no text')
        result.append({'namespace':field['namespace'], 'state':status, 'text':text,
                       'source':'retained_pointer' if projected['signed_tag']==16 else 'indexed_name',
                       'stored_index':field.get('stored_index')})
    for field in projected.get('stored_name_strings', ()):
        text = field['text']
        status = 'decoded' if field['text_state']=='utf8' and type(text) is str else 'unsupported_encoding'
        result.append({'namespace':None, 'state':status, 'text':text if status=='decoded' else None,
                       'source':'stored_literal', 'native_offset':field['native_offset']})
    if not result:
        result.append({'namespace':None, 'state':'unprojected_name', 'text':None,
                       'source':'no_projected_name'})
    return result


def _fields(projected):
    return tuple((f['namespace'], f['state'], names.normalize(f['text']) if f['state']=='decoded' else None,
                  f['source']) for f in _details(projected))


def _evaluate(fields, query, mode):
    unavailable = False
    for namespace, term in query.items():
        relevant = fields if namespace=='any' else [f for f in fields if f[0]==namespace]
        if any(f[1]=='decoded' and (f[2]==term if mode=='exact' else f[2].startswith(term) if mode=='prefix' else term in f[2]) for f in relevant):
            continue
        if not relevant or any(f[1] in _UNKNOWN for f in relevant):
            unavailable = True
        else:
            # A known failure takes precedence over another unavailable field.
            return 'predicate_excluded'
    return 'name_unavailable' if unavailable else 'matched'


def _entry(row, projected):
    identity = row['identity']
    return _Entry(row['end'], row['signed_tag'], identity['native_id_word'],
                  identity['secondary_word'], _fields(projected))


def _cost(entry):
    # Conservative structural accounting, not a measured Python RSS claim.
    return 160 + sum(112 + (4*len(f[2].encode('utf8')) if f[2] is not None else 0) for f in entry.fields)


def _check_cached(data, start, ordinal, entry, ends):
    if (type(entry.end) is not int or not start+13 <= entry.end <= len(data)
            or struct.unpack_from('<b',data,start)[0] != entry.tag
            or struct.unpack_from('<III',data,entry.end-12) != (ordinal,entry.native,entry.secondary)
            or ordinal < len(ends) and ends[ordinal] != entry.end):
        raise ValueError('Cached typed-name geometry or identity differs from source')


def _counts(value, keys):
    if type(value) is not dict or set(value) != set(keys) or any(type(n) is not int or not 0 <= n <= 6_000_000 for n in value.values()):
        raise ValueError('Invalid canonical name cursor counters')
    return dict(value)


def find_people(filename, expected_snapshot_id, *, first_name=None, surname=None, common_name=None,
                any_name=None, match_mode='exact', cursor=None, limit=20, scan_limit=10000,
                directory=None, _seconds=2.0):
    original, query = _query(first_name,surname,common_name,any_name,match_mode)
    if (type(limit) is not int or not 1 <= limit <= 50 or type(scan_limit) is not int
            or not 1 <= scan_limit <= 10000):
        raise ValueError('Invalid canonical name match or scan limit')
    query_hash = sha256(json.dumps({'kind':'typed_names_v1','parts':query,'mode':match_mode},sort_keys=True).encode()).hexdigest()
    restored = None if cursor is None else _restore(cursor)
    if restored is not None and (type(restored) is not dict or set(restored) != {'pin','digest','query','next','counts','fields','kinds','unresolved'}):
        raise ValueError('Invalid canonical name cursor; restart without cursor')
    if not population._LOCK.acquire(blocking=False):
        raise ValueError('Another saved population query is in progress; retry')
    try:
        digest = None
        def locate(data):
            nonlocal digest
            digest = sha256(data).digest()
            if population._LAST_LAYOUT is not None and population._LAST_LAYOUT[0]==digest:
                return replace(population._LAST_LAYOUT[1],_data=data)
            return population.saved_name_vectors.locate(data)

        with population.checked_name_source(filename,expected_snapshot_id,directory,locate=locate) as (data,layout,pin,metadata):
            key = (pin,digest,layout.person_offset,layout.person_count)
            ends = population._PREFIXES.get(key,array('I'))
            index = _INDEXES.get(key)
            if index is None:
                index = _Index([])
            if len(ends) < len(index.entries):
                # Other population users can evict the shared prefix cache.
                # Rebuild its source-bound ends from this typed index without
                # reparsing or publishing an incomplete ordinal vector.
                ends = array('I', (entry.end for entry in index.entries))
            first = 0
            prior = {k:0 for k in _CATEGORIES}
            prior_fields = {k:0 for k in _FIELD_STATES}
            prior_kinds, prior_unresolved = {}, 0
            if restored is not None:
                if (restored['pin']!=pin or restored['digest']!=digest.hex() or restored['query']!=query_hash):
                    raise ValueError('Canonical name cursor source or selectors changed')
                first = restored['next']
                if type(first) is not int or not 0 <= first <= len(index.entries):
                    raise ValueError('Canonical name index expired; restart without cursor')
                prior = _counts(restored['counts'],_CATEGORIES)
                prior_fields = _counts(restored['fields'],_FIELD_STATES)
                prior_kinds = restored['kinds']
                if (type(prior_kinds) is not dict or any(type(k) is not str or not k.lstrip('-').isdigit() or type(v) is not int or v<0 for k,v in prior_kinds.items())
                        or type(restored['unresolved']) is not int or not 0 <= restored['unresolved'] <= first
                        or sum(prior.values()) != first):
                    raise ValueError('Invalid canonical name cursor coverage')
                prior_unresolved = restored['unresolved']
            at = index.entries[first-1].end if first else layout.person_records_offset
            staged, new_ends, additional_bytes = [], array('I'), 0
            counts = {k:0 for k in _CATEGORIES}
            field_counts = {k:0 for k in _FIELD_STATES}
            kind_counts, unresolved_records = {}, 0
            matched, ordinal, cache_hits, matched_reparsed = [], first, 0, 0
            source_frontier = None
            stop_reason = None
            started = time.monotonic()
            while ordinal < layout.person_count and ordinal-first < scan_limit:
                if ordinal > first and time.monotonic()-started >= _seconds:
                    stop_reason = 'elapsed_work_budget'
                    break
                projected = None
                if ordinal < len(index.entries):
                    entry = index.entries[ordinal]
                    _check_cached(data,at,ordinal,entry,ends)
                    cache_hits += 1
                else:
                    if ordinal != len(index.entries)+len(staged):
                        raise ValueError('Canonical name index is not contiguous')
                    row = population._read_record(data,at,ordinal)
                    if row['state']=='unsupported':
                        counts['unsupported'] += 1
                        source_frontier = {'ordinal':ordinal,'tag_offset':at,'signed_tag':row['signed_tag'],
                                           'reason':row.get('reason'),'native_reader':row.get('native_reader')}
                        stop_reason = 'unsupported_source_frontier'
                        break
                    projected = population._project(data,layout,row)
                    entry = _entry(row,projected)
                    _check_cached(data,at,ordinal,entry,ends)
                    additional_bytes += _cost(entry)
                    if index.accounted_bytes+additional_bytes > _MAX_INDEX_BYTES:
                        raise ValueError('Canonical name index exceeds its bounded memory budget')
                    staged.append(entry)
                    if ordinal >= len(ends):
                        new_ends.append(entry.end)
                category = _evaluate(entry.fields,query,match_mode)
                counts[category] += 1
                kind = str(entry.tag)
                kind_counts[kind] = kind_counts.get(kind,0)+1
                for field in entry.fields:
                    field_counts[field[1]] += 1
                unresolved_records += any(field[1] in _UNKNOWN for field in entry.fields)
                if category=='matched':
                    if projected is None:
                        row = population._read_record(data,at,ordinal)
                        if row['state']!='decoded':
                            raise ValueError('Cached canonical name match is no longer decoded')
                        projected = population._project(data,layout,row)
                        if _entry(row,projected) != entry:
                            raise ValueError('Cached canonical name fields differ from source')
                        matched_reparsed += 1
                    projected.update(person_index=ordinal,database_index=ordinal,
                                     native_identity={'database_index':ordinal,'native_id':entry.native,'secondary_id':entry.secondary},
                                     search_name_fields=_details(projected),matching_source='decoded_stored_typed_fields')
                    matched.append(projected)
                at = entry.end
                ordinal += 1
                if len(matched)>=limit:
                    stop_reason = 'match_page_limit'
                    break
            complete = ordinal == layout.person_count
            footer = population._footer(data,at) if complete else {'state':'not_reached'}
            if complete:
                stop_reason = 'declared_table_end'
            elif stop_reason is None:
                stop_reason = 'slot_work_budget'
            cumulative = {k:prior[k]+counts[k] for k in _CATEGORIES}
            cumulative_fields = {k:prior_fields[k]+field_counts[k] for k in _FIELD_STATES}
            cumulative_kinds = dict(prior_kinds)
            for k,v in kind_counts.items():
                cumulative_kinds[k] = cumulative_kinds.get(k,0)+v
            cumulative_unresolved = prior_unresolved+unresolved_records
            next_cursor = None if complete or source_frontier else _token({'pin':pin,'digest':digest.hex(),'query':query_hash,
                'next':ordinal,'counts':cumulative,'fields':cumulative_fields,'kinds':cumulative_kinds,'unresolved':cumulative_unresolved})
            response = {'source':'on-disk save snapshot','filename':filename,'snapshot_id':pin,'saved_metadata':metadata,
                        'component_sha256':digest.hex(),'header_offset':layout.person_offset,
                        'query':{'parts':original,'normalized_parts':query,'match_mode':match_mode,'normalization':names.NORMALIZATION},
                        'matches':matched,'match_count':len(matched),'counts':counts,'cumulative_counts':cumulative,
                        'field_counts':field_counts,'cumulative_field_counts':cumulative_fields,
                        'kind_counts':kind_counts,'cumulative_kind_counts':cumulative_kinds,
                        'records_with_unresolved_name_fields':unresolved_records,
                        'cumulative_records_with_unresolved_name_fields':cumulative_unresolved,
                        'state':'complete_declared_table' if complete else 'stopped' if source_frontier else 'partial',
                        'stop_reason':stop_reason,'source_frontier':source_frontier,'next_cursor':next_cursor,
                        'first_scanned_ordinal':first,'next_original_ordinal':ordinal,
                        'attempted_slot_count':sum(counts.values()),'decoded_slot_count':ordinal-first,
                        'cumulative_decoded_slot_count':ordinal,'declared_person_slots':layout.person_count,
                        'footer':footer,'all_declared_slots_decoded':complete,
                        'cumulative_declared_table_scanned':complete,
                        'whole_declared_table_scanned':complete and first==0,
                        'all_possible_person_names_covered':False,'whole_population_complete':False,
                        'all_projected_name_fields_decodable':complete and cumulative_unresolved==0,
                        'index':{'previous_records':len(index.entries),'new_records':len(staged),'cache_hits':cache_hits,
                                 'matched_records_reparsed':matched_reparsed,'indexed_records':len(index.entries)+len(staged),
                                 'accounted_bytes':index.accounted_bytes+additional_bytes},
                        'scope':_SCOPE,'layout_provenance':layout.provenance,
                        'wire_profile_is_conditional':True,'native_loader_globals_proved':False,
                        'work_bounds':{'original_slots':scan_limit,'matches':limit,'target_decode_seconds':_seconds,
                                       'minimum_remaining_scan_pages':(layout.person_count-ordinal+scan_limit-1)//scan_limit,
                                       'each_request_rechecks_complete_source':True},
                        'elapsed_decode_seconds':time.monotonic()-started}
            if len(json.dumps(response,ensure_ascii=True).encode('ascii')) > _MAX_RESPONSE_BYTES:
                raise ValueError('Canonical name response exceeds budget; lower limit')
        # Nothing derived from a failing original source enters either cache.
        population._LAST_LAYOUT = (digest,replace(layout,_data=None))
        ends.extend(new_ends)
        population._PREFIXES[key] = ends
        population._PREFIXES.move_to_end(key)
        while len(population._PREFIXES)>population._MAX_CACHES:
            population._PREFIXES.popitem(last=False)
        index.entries.extend(staged)
        index.accounted_bytes += additional_bytes
        _INDEXES[key] = index
        _INDEXES.move_to_end(key)
        while len(_INDEXES)>_MAX_CACHES or sum(i.accounted_bytes for i in _INDEXES.values())>_MAX_INDEX_BYTES:
            _INDEXES.popitem(last=False)
        return response
    finally:
        population._LOCK.release()
