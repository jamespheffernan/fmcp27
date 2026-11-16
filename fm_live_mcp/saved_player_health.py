"""Pinned stored player fitness and injury-vector records, without recalculation.

D09BB0 tests PLAYER+F0's first vector. 11E7C4C/11E9F30 transport it
through 154E184/154DD68. The separate F0+58 form history and indexed
injury histories are not sources for this current vector.
"""
import json
from hashlib import sha256

from . import (saved_form_player, saved_injury_history_records, saved_injury_labels,
               saved_person_search, saved_player_fitness, saved_player_form_query,
               saved_player_injury_history, saved_player_profile_query)
from .person_wire import _bindings, _player_154e184

MAX_PEOPLE = 32
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SCOPE = {
    'placement': 'locally_corroborated_typed_start',
    'wire_profile_is_conditional': True,
    'certified_person_record': False,
    'native_loader_acceptance': False,
    'native_refresh_executed': False,
    'medical_clearance': 'not_assessed',
    'match_eligibility': 'not_assessed',
    'recovery_forecast': 'not_assessed',
}


def read_injury_vector(data, start, *, limit):
    """Read only the first PLAYER+F0 vector, stopping before its siblings.

    The caller owns source identity, the F0 handoff and its exclusive bound.
    Version3 and optional version1 are pinned current-writer layouts. Unknown
    or malformed input raises and must never be projected as an empty vector.
    """
    if (type(start) is not int or type(limit) is not int
            or not 0 <= start < limit <= len(data)):
        raise ValueError('Invalid bounded current injury-vector cursor')
    view = memoryview(data)[:limit]
    count = view[start]
    at = start + 1
    rows = []
    for ordinal in range(count):
        if at >= limit or view[at] != 3:
            raise ValueError('Unsupported current injury row version; expected3')
        child = _player_154e184.parse(
            view, at, native_reference_context=_bindings.NESTED_REFERENCE_CONTEXT)
        end = child['end']
        if not at < end <= limit:
            raise ValueError('Current injury row crossed its exclusive source bound')
        fields = child['fields']
        if fields['optional_presence'] not in (0, 1):
            raise ValueError('Invalid current injury optional presence')
        optional = fields.get('optional_3f94fc0')
        if optional is not None and optional['version'] != 1:
            raise ValueError('Unsupported current injury optional row version')
        groups = [fields['group18']]
        if optional is not None:
            groups.extend([optional['group08'], optional['group10']])
        if any(group.get('marker') not in (0, 1) for group in groups):
            raise ValueError('Unsupported current injury TEAM reference marker')
        ref = fields['root40']
        stored = ref['escape_u32'] if ref['index_i16'] == -2 else ref['index_i16']
        if stored < -1:
            raise ValueError('Invalid negative current INJURY reference')
        raw = bytes(view[at:end])
        rows.append({
            'entry_index': ordinal, 'source_start': at, 'source_end': end,
            'record_sha256': sha256(raw).hexdigest(), 'raw_record_hex': raw.hex(),
            'injury_reference': {'table': 'INJURY', 'stored_index': stored,
                                 'state': 'native_null_reference' if stored == -1 else 'unresolved_index',
                                 'identity': None},
            'stored_injury_date': saved_injury_history_records.stored_date(bytes.fromhex(fields['raw20'])),
            'date_role': 'stored_instance_0x20; onset_or_recovery_role_unproved',
            'unmapped_native_fields': {
                '0x28_signed16': int.from_bytes(fields['28'].to_bytes(2, 'little'), 'little', signed=True),
                '0x2A_signed16': int.from_bytes(fields['2a'].to_bytes(2, 'little'), 'little', signed=True),
            },
        })
        at = end
    return {'state': 'decoded', 'source_start': start, 'source_end': at,
            'count_source_offset': start, 'stored_record_count': count,
            'has_stored_injury_records': bool(count), 'records': rows,
            'native_reader': '0x11E7C4C / 0x154E184',
            'native_writer': '0x11E9F30 / 0x154DD68',
            'reference_profile_is_conditional': True,
            'unread_sibling_fields': True}


def _injuries(data, geometry):
    start, limit = geometry['record_start'], geometry['common_start']
    result = {'state': 'stopped', 'stored_record_count': None,
              'has_stored_injury_records': None, 'records': None,
              'reason': None, 'recovery_forecast': 'not_assessed'}
    try:
        front = saved_form_player.locate_f0(data, start, limit)
        end = saved_player_form_query._range(front, start, limit)
        if front['state'] == 'absent':
            result.update(state='decoded', stored_record_count=0,
                          has_stored_injury_records=False, records=[],
                          source_state='PLAYER_F0_not_stored', source_end=end)
        elif front['state'] == 'present':
            if front.get('f0_start') != end:
                raise ValueError('Current injury F0 handoff mismatch')
            result.update(read_injury_vector(data, end, limit=limit))
        else:
            result.update(reason=front.get('stop_reason'), next_native_reader=front.get('next_native_reader'))
    except ValueError as error:
        result.update(reason=str(error))
    return result


def _person(data, layout, target):
    geometries, rejected, exhausted = saved_player_form_query._starts(data, layout, target)
    complete = (target.get('search_complete', False)
                and target.get('neighbour_corroboration', {}).get('search_complete', False)
                and not exhausted)
    state = ('incomplete_candidates' if not complete else
             'competing_candidates' if len(geometries) > 1 else
             'unavailable' if not geometries else 'ready')
    result = {'person_index': target['person_index'], 'state': state,
              'identity': None, 'name_context': None,
              'fitness': {'state': 'unavailable', 'fields': None, 'reason': state},
              'injuries': {'state': 'unavailable', 'stored_record_count': None,
                           'has_stored_injury_records': None, 'records': None, 'reason': state},
              'typed_start_candidates': geometries,
              'candidate_search': {'search_complete': complete,
                                   'rejected_packet_counts': rejected,
                                   'budget_reasons': target.get('budget_reasons', [])},
              'evidence_scope': dict(SCOPE)}
    if state != 'ready':
        return result
    geometry = geometries[0]
    result['identity'] = geometry['identity']
    result['name_context'] = saved_player_profile_query._name_context(target, geometry)
    try:
        result['fitness'] = saved_player_fitness.read_fitness(
            data, geometry['record_start'] + 1, limit=geometry['common_start'])
    except ValueError as error:
        result['fitness']['reason'] = str(error)
    result['injuries'] = _injuries(data, geometry)
    result['state'] = ('decoded' if result['fitness']['state'] == result['injuries']['state'] == 'decoded'
                       else 'partial')
    return result


def _definitions(data, people):
    wanted = {row['injury_reference']['stored_index'] for p in people
              for row in p['injuries']['records'] or []
              if row['injury_reference']['stored_index'] >= 0}
    try:
        # This helper reads only the canonical INJURY table, not history rows.
        identities, coverage = saved_player_injury_history._definitions(data, wanted)
    except ValueError as error:
        identities, coverage = {}, {'state': 'unavailable', 'reason': str(error)}
    for person in people:
        for row in person['injuries']['records'] or []:
            ref = row['injury_reference']
            if ref['stored_index'] < 0:
                continue
            identity = identities.get(ref['stored_index'])
            ref.update(identity=identity,
                       state='same_snapshot_canonical' if identity is not None else 'unresolved_index')
    return coverage


def _labels(people):
    resource = saved_injury_labels.load_english_injury_labels()
    labels = resource.pop('labels')
    for person in people:
        for row in person['injuries']['records'] or []:
            identity = row['injury_reference']['identity']
            label = labels.get(identity['native_id']) if identity else None
            row['installed_injury_label'] = {
                'state': ('resource_' + resource['status'] if resource['status'] != 'available' else
                          'unresolved_saved_reference' if identity is None else
                          'available' if label is not None else 'native_id_not_in_resource'),
                'source': 'installed_database_baseline',
                'name': label['name'] if label is not None else None,
                'sentence_name': label['sentence_name'] if label is not None else None,
            }
    return resource


def get_player_health(filename, person_indices, expected_snapshot_id, *,
                      include_installed_names=False, directory=None):
    """Read ordered roster indices once, preserving partial sections and duplicates."""
    if (not isinstance(person_indices, list) or not 1 <= len(person_indices) <= MAX_PEOPLE
            or any(type(index) is not int or not 0 <= index < 2**31 for index in person_indices)):
        raise ValueError('Supply1 to32 exact saved PERSON indices')
    if type(include_installed_names) is not bool:
        raise ValueError('include_installed_names must be a Boolean')
    unique = list(dict.fromkeys(person_indices))
    with saved_person_search.checked_person_context(
            filename, unique, expected_snapshot_id, directory=directory) as context:
        targets = {row['person_index']: row for row in context['ranked']}
        if len(targets) != len(context['ranked']) or set(targets) != set(unique):
            raise ValueError('Health PERSON search omitted or duplicated requested indices')
        by_index = {index: _person(context['data'], context['layout'], targets[index]) for index in unique}
        distinct = list(by_index.values())
        definitions = _definitions(context['data'], distinct)
        resource = _labels(distinct) if include_installed_names else None
        reply = {'source': 'on-disk save snapshot', 'filename': filename,
                 'snapshot_id': context['snapshot_id'], 'saved_metadata': context['saved_metadata'],
                 'declared_person_slots': context['layout'].person_count,
                 'people': [by_index[index] for index in person_indices],
                 'injury_definition_coverage': definitions,
                 'evidence_scope': dict(SCOPE),
                 'limitations': ['Stored values without native refresh; an injury record can permit participation.',
                                 'Empty stored injury vector is not medical clearance or match eligibility.',
                                 'Stored injury date role, raw duration units and recovery forecasts remain unproved.']}
        if include_installed_names:
            reply['installed_injury_labels'] = resource
        if len(json.dumps(reply, ensure_ascii=True).encode('ascii')) > MAX_RESPONSE_BYTES:
            raise ValueError('Saved player health response exceeds output budget; request fewer indices')
    return reply
