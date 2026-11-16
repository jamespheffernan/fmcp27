"""Read exact records from a contiguous, conditionally placed PERSON table.

Only exclusive end offsets survive between calls. Each request reopens the
checked archive, verifies the complete component digest and reparses any
requested cached row. The cache is private to this process.
"""
from array import array
from collections import OrderedDict
from dataclasses import replace
from hashlib import sha256
import json
import struct
from threading import Lock

from . import saved_name_vectors
from .saved_person_name_search import _source as checked_name_source

_MAX_ADVANCE = 10_000
_MAX_INDICES = 32
_MAX_CACHES = 4
_PREFIXES = OrderedDict()
_LAST_LAYOUT = None
_LOCK = Lock()


def _indexed_name(layout, namespace, index):
    field = {'namespace': namespace, 'stored_index': index, 'text': None}
    if index == -1:
        return {**field, 'state': 'null_reference'}
    if not 0 <= index < layout.name_counts[namespace]:
        return {**field, 'state': 'out_of_range'}
    raw = layout.lookup_raw(namespace, index)
    try:
        return {**field, 'state': 'decoded', 'text': raw.decode('utf-8')}
    except UnicodeDecodeError:
        return {**field, 'state': 'unsupported_encoding', 'raw_hex': raw.hex()}


def _project(data, layout, row):
    start, end = row['tag_offset'], row['end']
    output = {key: row[key] for key in
              ('ordinal', 'signed_tag', 'source_record_kind', 'tag_offset', 'body_offset', 'end', 'identity')}
    output['state'] = 'available'
    output['record_sha256'] = sha256(memoryview(data)[start:end]).hexdigest()
    output['name_fields'] = []
    if row.get('names') is not None:
        for namespace, ref in zip(('first', 'second', 'common'), row['names'], strict=True):
            if ref['inline_marker'] == 0:
                field = _indexed_name(layout, namespace, ref['original_reference_index'])
            else:
                field = {'namespace': namespace, 'state': 'stored_inline_reference',
                         'stored_index': ref['original_reference_index'], 'inline_record': ref['inline_record']}
            output['name_fields'].append(field)
    for key in ('stored_name_strings', 'retired_name_references', 'retired_pointer_raw',
                'native_fields', 'optional_0c', 'nation_reference', 'reference_conditions',
                'person_vector_summary', 'date_word_vector_summary', 'human_wire_summary'):
        if row.get(key) is not None:
            output[key] = row[key]
    if row.get('retired_name_references') is not None:
        for field in row['retired_name_references']:
            index, namespace = field['raw_index'], field['namespace']
            if index & (1 << 31) or index >= layout.name_counts[namespace]:
                name = {'namespace': namespace, 'stored_index': index, 'text': None,
                        'state': 'native_null_reference',
                        'reason': 'signed_index_guard' if index & (1 << 31) else 'vector_bound_guard'}
            else:
                name = _indexed_name(layout, namespace, index)
            output['name_fields'].append(name)
    return output


def _read_record(data, at, index, *, include_scouting=False, include_history=False):
    from .person_wire import parse_record
    row = parse_record(data, at, index, limit=len(data), _include_scouting=include_scouting, _include_history=include_history)
    if row['state'] == 'unsupported':
        return row
    if (row['state'] != 'decoded' or row['ordinal'] != index or row['tag_offset'] != at
            or row['body_offset'] != at + 1 or not at + 13 <= row['end'] <= len(data)):
        raise ValueError('Invalid decoded PERSON record extent')
    end = row['end']
    identity = row['identity']
    if (row['signed_tag'] != struct.unpack_from('<b', data, at)[0]
            or identity['stored_index'] != index or identity['offset'] != end - 12
            or struct.unpack_from('<III', data, end - 12) != (
                index, identity['native_id_word'], identity['secondary_word'])):
        raise ValueError('Decoded PERSON identity or tag differs from its source bytes')
    return row


def _footer(data, at):
    if at + 9 > len(data):
        raise ValueError('Truncated PERSON table footer')
    count, = struct.unpack_from('<I', data, at)
    end = at + 9 + 12 * count
    if count > 2_000_000 or end > len(data):
        raise ValueError('Unsupported PERSON footer extent')
    last_byte, last_word = struct.unpack_from('<BI', data, end - 5)
    return {'state': 'source_footer_read', 'start': at, 'end': end, 'auxiliary_rows': count,
            'final_byte': last_byte, 'final_word': last_word,
            'sha256': sha256(memoryview(data)[at:end]).hexdigest()}


def _query(data, layout, ends, indices, max_advance):
    original_count = len(ends)
    new_ends = array('I')
    reached = {}
    frontier_error = None
    requested = {i for i in indices if i < layout.person_count}
    at = ends[-1] if ends else layout.person_records_offset
    stop = min(original_count + max_advance, max(requested, default=-1) + 1)
    for index in range(original_count, stop):
        row = _read_record(data, at, index)
        if row['state'] == 'unsupported':
            frontier_error = {'ordinal': index, 'tag_offset': at, 'signed_tag': row['signed_tag'],
                              'reason': row.get('reason'), 'native_reader': row.get('native_reader')}
            break
        at = row['end']
        new_ends.append(at)
        if index in requested:
            reached[index] = _project(data, layout, row)

    for index in sorted(requested):
        if index < original_count:
            start = ends[index - 1] if index else layout.person_records_offset
            row = _read_record(data, start, index)
            if row['state'] != 'decoded' or row['end'] != ends[index]:
                raise ValueError('Cached PERSON extent disagrees with the checked source')
            reached[index] = _project(data, layout, row)

    checked = original_count + len(new_ends)
    footer = _footer(data, at) if checked == layout.person_count else {'state': 'not_reached'}
    people = []
    for index in indices:
        if index in reached:
            people.append(reached[index])
        else:
            state = ('outside_declared_table' if index >= layout.person_count else
                     'unreached_source_frontier' if frontier_error else 'more_work_required')
            people.append({'ordinal': index, 'state': state})
    return {
        'people': people, 'checked_prefix_count': checked, 'new_records_checked': len(new_ends),
        'declared_person_slots': layout.person_count, 'source_frontier': frontier_error,
        'footer': footer, 'next_unread_ordinal': checked if checked < layout.person_count else None,
        'retry_same_query_to_advance': any(p['state'] == 'more_work_required' for p in people),
    }, new_ends


def get_person_records(filename, expected_snapshot_id, *, person_indices=None, offset=0, limit=20,
                       directory=None, _max_advance=_MAX_ADVANCE):
    global _LAST_LAYOUT
    if (type(offset) is not int or not 0 <= offset < 2**31
            or type(limit) is not int or not 1 <= limit <= _MAX_INDICES
            or type(_max_advance) is not int or not 1 <= _max_advance <= _MAX_ADVANCE):
        raise ValueError('Invalid saved PERSON page or work budget')
    if person_indices is not None:
        if (not isinstance(person_indices, list) or not 1 <= len(person_indices) <= _MAX_INDICES
                or any(type(i) is not int or not 0 <= i < 2**31 for i in person_indices)
                or offset or limit != 20):
            raise ValueError('Supply 1 to 32 original PERSON indices or use offset and limit')
    if not _LOCK.acquire(blocking=False):
        raise ValueError('Another saved population query is in progress; retry when it finishes')
    try:
        digest = None
        def locate(data):
            nonlocal digest
            digest = sha256(data).digest()
            if _LAST_LAYOUT is not None and _LAST_LAYOUT[0] == digest:
                return replace(_LAST_LAYOUT[1], _data=data)
            return saved_name_vectors.locate(data)

        with checked_name_source(filename, expected_snapshot_id, directory, locate=locate) as (data, layout, pin, metadata):
            key = (pin, digest, layout.person_offset, layout.person_count)
            ends = _PREFIXES.get(key)
            if ends is None:
                ends = array('I')
            if person_indices is None:
                indices = range(offset, min(layout.person_count, offset + limit))
            else:
                indices = person_indices
            result, new_ends = _query(data, layout, ends, indices, _max_advance)
            next_page = None
            if person_indices is None and offset + limit < layout.person_count:
                if all(p['state'] == 'available' for p in result['people']):
                    next_page = offset + limit
            result.update(filename=filename, snapshot_id=pin, saved_metadata=metadata,
                          source='on-disk save snapshot', next_offset=next_page,
                          header_offset=layout.person_offset, component_sha256=digest.hex(),
                          layout_provenance=layout.provenance, wire_profile_is_conditional=True,
                          native_loader_globals_proved=False)
            if len(json.dumps(result, ensure_ascii=True)) > 2 * 1024**2:
                raise ValueError('Saved population response too large; request fewer records')
        # The checked snapshot has now passed its final file-identity check.
        # Retain only vector offsets. The next request revalidates and decompresses
        # its own frame, then rebinds those offsets only on a full digest match.
        _LAST_LAYOUT = (digest, replace(layout, _data=None))
        ends.extend(new_ends)
        _PREFIXES[key] = ends
        _PREFIXES.move_to_end(key)
        if len(_PREFIXES) > _MAX_CACHES:
            _PREFIXES.popitem(last=False)
        return result
    finally:
        _LOCK.release()
