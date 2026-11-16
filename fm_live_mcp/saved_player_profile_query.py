"""Pinned plural player ratings, retaining local-placement and partial evidence."""
import json
import struct

from . import (
    saved_form_container, saved_form_player, saved_form_rows, saved_form_tail,
    saved_person_search, saved_player_form_query, saved_player_ratings, saved_primary_contract,
    saved_player_tail, saved_player_wire_prefix,
)
from .saved_form_children import BoundedReader

MAX_PEOPLE = 32
MAX_SELECTORS = 128
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_FIELD_NAMES = {
    'ability': ('current', 'potential'),
    'attributes': tuple(saved_player_ratings.ATTRIBUTES),
    'positions': tuple(saved_player_ratings.POSITIONS),
    **{group: tuple(fields) for group, fields in saved_player_ratings.EXTRAS.items()},
}
_SCOPE = {
    'placement': 'locally_corroborated_typed_start',
    'wire_profile_is_conditional': True,
    'certified_person_record': False,
    'native_loader_acceptance': False,
    'complete_person_body': False,
    'reference_identities_resolved': False,
    'ratings_evidence': 'native_getters_for_stored_PLAYER_148_block_and_270_scale',
}


class _Reader(BoundedReader):
    def i8(self):
        return struct.unpack('<b', self.take(1))[0]


def _projection(fields):
    if fields is None:
        return {group: set(names) for group, names in _FIELD_NAMES.items()}
    if not isinstance(fields, list) or not 1 <= len(fields) <= MAX_SELECTORS:
        raise ValueError('Supply1 to128 field/group selectors, or omit fields for all groups')
    selected = {}
    for selector in fields:
        if type(selector) is not str or not 1 <= len(selector) <= 80:
            raise ValueError('Invalid saved player profile field selector')
        if selector in _FIELD_NAMES:
            selected.setdefault(selector, set()).update(_FIELD_NAMES[selector])
            continue
        group, separator, name = selector.partition('.')
        if not separator or group not in _FIELD_NAMES or name not in _FIELD_NAMES[group]:
            raise ValueError(f'Unknown saved player profile field/group: {selector}')
        selected.setdefault(group, set()).add(name)
    return selected


def _initial(data, geometry):
    start, limit = geometry.get('record_start'), geometry.get('common_start')
    if (type(start) is not int or type(limit) is not int
            or not 0 <= start < limit <= len(data)
            or geometry.get('wire_profile') != saved_player_wire_prefix.WIRE_PROFILE
            or data[start] != 2):
        raise ValueError('Invalid conditional raw64 player profile geometry')
    body = start + 1
    # CFD388:22 fixed bytes,8B10FF49C,69B native+148..18C.
    raw_start, raw_end = body + 30, body + 99
    if raw_end > limit or body + 126 > limit:
        raise ValueError('Stored player rating block crosses common-body bound')
    current, potential = struct.unpack_from('<hh', data, body + 6)
    return {
        'body_start': body, 'raw69': bytes(data[raw_start:raw_end]),
        'raw69_start': raw_start, 'raw69_end': raw_end,
        'current': current, 'potential': potential,
        'current_source_offset': body + 6, 'potential_source_offset': body + 8,
    }


def traverse_player(data, geometry):
    """Walk one already-qualified regular-player start to ACTUAL_PERSON.

    No scan or identity selection occurs here. The caller must obtain geometry
    through the same checked PERSON context/B47 qualification. Returned raw69
    bytes are internal, not a public response. ACTUAL_PERSON is exposed only
    after the complete player-specific tail; the PERSON body is left unread.
    """
    initial = _initial(data, geometry)
    start, bound = geometry['record_start'], geometry['common_start']
    result = {
        'state': 'partial', 'record_start': start, 'common_start': bound,
        'initial': initial, 'actual_person_start': None,
        'scale_byte': None, 'scale_offset': None, 'checked_ranges': {},
        'f0_state': None, 'form_state': None, 'stop_reason': None,
        'next_native_reader': None, 'wire_profile': geometry['wire_profile'],
        'wire_profile_is_conditional': True, 'complete_person_body': False,
    }

    def checked(name, packet, at):
        end = saved_player_form_query._range(packet, at, bound)
        result['checked_ranges'][name] = {'start': at, 'end': end}
        return end

    def stopped(packet):
        result.update(stop_reason=packet.get('stop_reason'),
                      next_native_reader=packet.get('next_native_reader'))
        return result

    try:
        front = saved_form_player.locate_f0(data, start, bound)
        at = checked('player_front', front, start)
        result['f0_state'] = front['state']
        if front['state'] == 'stopped':
            return stopped(front)
        if front['state'] == 'present':
            if front.get('f0_start') != at:
                raise ValueError('Player profile F0 handoff mismatch')
            container = saved_form_container.locate_form_groups(data, at, bound)
            at = checked('F0_container', container, at)
            result['form_state'] = container['state']
            if container['state'] == 'stopped':
                return stopped(container)
            if container['state'] == 'present':
                if container.get('form_start') != at:
                    raise ValueError('Player profile form-group handoff mismatch')
                reader = _Reader(data, at, bound)
                groups = saved_form_rows.read_groups(reader)
                end = checked('form_groups', groups, at)
                if end != reader.offset:
                    raise ValueError('Player profile form-group reader end mismatch')
                result['form_group_count'] = groups['group_count']
                result['form_row_count'] = groups['total_row_count']
                del groups  # Profiles expose no form rows; do not retain their materialization.
                siblings = saved_form_tail.read_tail(data, end, bound)
                at = checked('form_siblings', siblings, end)
                if siblings['state'] != 'complete' or not siblings.get('siblings_complete'):
                    return stopped(siblings)
            elif container['state'] != 'absent':
                raise ValueError('Unknown saved form-container state')
        elif front['state'] == 'absent':
            result['form_state'] = 'not_stored_F0_absent'
        else:
            raise ValueError('Unknown saved player-front state')
        reader = _Reader(data, at, bound)
        tail = saved_player_tail.read_tail(reader)
        end = checked('player_tail', tail, at)
        scale_at, scale = tail.get('scale_offset'), tail.get('scale_byte')
        if (reader.offset != end or tail.get('actual_person_start') != end
                or not tail.get('complete_player_specific_tail')
                or type(scale_at) is not int or not at <= scale_at < end
                or type(scale) is not int or not 0 <= scale <= 255 or data[scale_at] != scale):
            raise ValueError('Player profile scale/ACTUAL_PERSON handoff is not source-bound')
        result.update(state='complete', scale_byte=scale, scale_offset=scale_at,
                      actual_person_start=end)
    except ValueError as error:
        result.update(stop_reason=str(error), next_native_reader=getattr(error, 'native', None))
    return result


def _name_context(target, geometry):
    witness = next(w for w in target['candidates']
                   if w['common_start'] == geometry['common_start']
                   and w['identity_offset'] == geometry['identity_offset'])
    names, states = {}, {}
    for namespace, index, record in zip(('first', 'second', 'common'), witness['name_indices'], witness['names'], strict=True):
        names[namespace] = None if record is None else record.get('text')
        if index == -1:
            states[namespace] = 'null_reference'
        elif record is None or record.get('state') == 'budget':
            states[namespace] = 'unavailable'
        else:
            states[namespace] = 'decoded' if record.get('text') is not None else 'unmapped_utf8'
    return {'names': names, 'name_indices': witness['name_indices'], 'states': states,
            'scope': 'same_snapshot_original_name_vectors'}


def _values(decoded, initial, selected):
    profile, unavailable = {}, {}
    for group, names in _FIELD_NAMES.items():
        if group not in selected:
            continue
        values = {}
        for name in names:
            if name not in selected[group]:
                continue
            if group == 'ability':
                values[name] = initial[name]
                continue
            rating = decoded[group][name]
            values[name] = rating['value']
            if rating['state'] != 'decoded':
                unavailable[f'{group}.{name}'] = {
                    key: rating[key] for key in ('state', 'raw_u8', 'native_getter_value')}
        profile[group] = values
    return profile, unavailable


def _person(data, layout, target, selected, *, include_current_contract=False):
    geometries, rejected, exhausted = saved_player_form_query._starts(data, layout, target)
    neighbour = target.get('neighbour_corroboration', {})
    complete = target.get('search_complete', False) and neighbour.get('search_complete', False) and not exhausted
    state = ('incomplete_candidates' if not complete else
             'competing_candidates' if len(geometries) > 1 else
             'unavailable' if not geometries else 'ready')
    result = {
        'person_index': target['person_index'], 'state': state,
        'identity': None, 'name_context': None, 'profile': None,
        'unavailable_fields': {}, 'scale_context': None, 'source_context': None,
        'typed_start_candidates': geometries,
        'candidate_search': {
            'state': target['state'], 'search_complete': target['search_complete'],
            'neighbour_search_complete': neighbour.get('search_complete', False),
            'budget_reasons': target.get('budget_reasons', []),
            'witness_count': len(target['candidates']),
            'typed_start_summary_complete': not exhausted,
            'rejected_packet_counts': rejected,
        },
        'evidence_scope': dict(_SCOPE),
    }
    if include_current_contract:
        result['current_contract'] = {
            'state': 'unavailable', 'reason': 'no_unique_complete_player_boundary', 'weekly_wage': None,
            'primary_contract_wire_complete': False, 'complete_actual_person': False,
            'wire_profile_is_conditional': True, 'native_loader_acceptance_proved': False}
    if state != 'ready':
        return result
    geometry = geometries[0]
    result['identity'] = geometry['identity']
    result['name_context'] = _name_context(target, geometry)
    try:
        traversal = traverse_player(data, geometry)
    except ValueError as error:
        result.update(state='unavailable', reason=str(error))
        return result
    initial = traversal['initial']
    decoded = saved_player_ratings.decode(initial['raw69'], traversal['scale_byte'])
    result['profile'], result['unavailable_fields'] = _values(decoded, initial, selected)
    bad_values = any(value['state'] != 'decoded'
                     for group in _FIELD_NAMES if group != 'ability'
                     for value in decoded[group].values())
    result['state'] = 'available' if traversal['state'] == 'complete' and not bad_values else 'partial'
    result['scale_context'] = {
        key: decoded[key] for key in ('stored_scale_byte', 'scale_flag_bit7', 'attribute_scale', 'position_scale')}
    result['scale_context']['ability_encoding'] = 'signed16_little_endian_native_PCAB_PPAB'
    result['source_context'] = {
        'wire_profile': traversal['wire_profile'], 'wire_profile_is_conditional': True,
        'raw69_start': initial['raw69_start'], 'raw69_end': initial['raw69_end'],
        'current_ability_offset': initial['current_source_offset'],
        'potential_ability_offset': initial['potential_source_offset'],
        'scale_offset': traversal['scale_offset'],
        'traversal_state': traversal['state'],
        'stop_reason': traversal['stop_reason'], 'next_native_reader': traversal['next_native_reader'],
        'checked_ranges': traversal['checked_ranges'],
        'player_specific_tail_complete': traversal['state'] == 'complete',
        'actual_person_body_unread': True,
        'ability_values_are_signed_native_codes': True,
    }
    if result['state'] == 'partial':
        result['reason'] = traversal['stop_reason'] or 'stored_ratings_outside_supported_domain'
    if include_current_contract and traversal['state'] == 'complete':
        actual = traversal['actual_person_start']
        common = geometry['common_start']
        if type(actual) is int and actual < common:
            try:
                contract = saved_primary_contract.read_primary_contract(
                    data, actual, common, person_index=target['person_index'],
                    base_currency_code=getattr(layout, 'base_currency_code', None))
                if (contract.get('actual_person_start') != actual
                        or contract.get('exclusive_common_start') != common
                        or any(type(span.get('start')) is not int or type(span.get('end')) is not int
                               or not actual <= span['start'] <= span['end'] <= common
                               for span in contract.get('checked_ranges', []))):
                    raise ValueError('Primary contract crossed verified ACTUAL_PERSON/common bounds')
                if contract['state'] in ('available', 'dynamic_expiry') and (
                        contract.get('owner_person_index') != target['person_index']
                        or contract.get('source_kind') != 0
                        or not contract.get('primary_contract_wire_complete')
                        or type(contract.get('source_start')) is not int
                        or type(contract.get('source_end')) is not int
                        or not actual <= contract['source_start'] < contract['source_end'] <= common):
                    raise ValueError('Primary contract owner or typed payload is not source-qualified')
                wage = contract.get('weekly_wage')
                if wage is not None and (
                        contract.get('owner_person_index') != target['person_index']
                        or contract.get('source_kind') not in (0, 5)
                        or not contract.get('primary_contract_wire_complete')
                        or not actual <= contract['source_start'] <= wage['source_offset']
                        or not wage['source_offset'] + 4 <= contract['source_end'] <= common):
                    raise ValueError('Weekly wage has no owner-checked primary contract extent')
                result['current_contract'] = contract
            except ValueError as error:
                result['current_contract'].update(state='unsupported', reason=str(error))
    return result


def get_player_profiles(filename, person_indices, expected_snapshot_id, *, fields=None, include_current_contract=False, directory=None):
    """Return ordered, per-index profile states using one deduplicated source context."""
    if (not isinstance(person_indices, list) or not 1 <= len(person_indices) <= MAX_PEOPLE
            or any(type(index) is not int or not 0 <= index < 2**31 for index in person_indices)):
        raise ValueError('Supply1 to32 exact saved PERSON indices')
    if type(include_current_contract) is not bool:
        raise ValueError('include_current_contract must be a boolean')
    selected = _projection(fields)
    unique = list(dict.fromkeys(person_indices))
    with saved_person_search.checked_person_context(
            filename, unique, expected_snapshot_id, directory=directory) as context:
        targets = {row['person_index']: row for row in context['ranked']}
        if len(targets) != len(context['ranked']) or set(targets) != set(unique):
            raise ValueError('Saved profile search did not return the requested unique indices')
        by_index = {index: _person(context['data'], context['layout'], targets[index], selected,
                                  include_current_contract=include_current_contract)
                    for index in unique}
        people = [by_index[index] for index in person_indices]
        reply = {
            'source': 'on-disk save snapshot', 'filename': filename,
            'snapshot_id': context['snapshot_id'], 'saved_metadata': context['saved_metadata'],
            'declared_person_slots': context['layout'].person_count,
            'fields': {group: [name for name in _FIELD_NAMES[group] if name in names]
                       for group, names in selected.items()},
            'people': people, 'evidence_scope': dict(_SCOPE),
        }
        if len(json.dumps(reply, ensure_ascii=True).encode('ascii')) > MAX_RESPONSE_BYTES:
            raise ValueError('Saved player profile response exceeds output budget; request fewer indices or fields')
    return reply
