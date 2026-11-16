"""Pinned, paginated stored form rows from locally corroborated player starts."""
import json
import struct

from . import (
    saved_form_container, saved_form_player, saved_form_rows,
    saved_person_neighbours, saved_person_search, saved_player_wire_prefix,
)
from .saved_form_children import BoundedReader

MAX_LIMIT = 500
MAX_START_GEOMETRIES = 32
MAX_INSPECTED_PACKETS = 4096
MAX_PREFIX_SUMMARIES = 8
MAX_GROUP_SUMMARIES = 255
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_SCOPE = {
    'placement': 'locally_corroborated_typed_start',
    'wire_profile_is_conditional': True,
    'certified_person_record': False,
    'complete_player_body': False,
    'native_loader_acceptance': False,
    'reference_identities_resolved': False,
    'unread_form_suffix': True,
    'played_minutes': 'stored native playing duration in the event-minute clock; no match completion or stoppage-time precision claim',
    'appearance_status': 'not inferred from duration; zero does not establish unused substitute or starter status',
}


def _starts(data, layout, target):
    """Preserve every distinct checked start/common-bound combination."""
    found = {}
    rejected = {}
    exhausted = False
    inspected = 0

    def reject(reason):
        rejected[reason] = rejected.get(reason, 0) + 1

    index = target['person_index']
    for witness in target['candidates']:
        if saved_person_neighbours._common_packet(data, layout, witness, index) is None:
            reject('common_suffix_not_bound_to_source')
            continue
        common = witness['common_start']
        for previous in witness.get('neighbour_evidence', {}).get('preceding', []):
            if inspected >= MAX_INSPECTED_PACKETS:
                exhausted = True
                break
            inspected += 1
            prefix = previous.get('target_prefix')
            if not isinstance(prefix, dict):
                reject('no_checked_target_prefix')
                continue
            start, end = prefix.get('start'), prefix.get('end')
            identity_at = previous.get('identity_offset')
            if (type(previous.get('person_index')) is not int or previous['person_index'] != index - 1
                    or type(start) is not int or type(end) is not int
                    or type(identity_at) is not int or identity_at < 0
                    or identity_at + 12 != start or previous.get('end') != start
                    or not 0 <= start < end <= common <= len(data)
                    or end < start + 127 or data[start] != 2
                    or struct.unpack_from('<I', data, identity_at)[0] != index - 1
                    or prefix.get('state') not in ('typed_prefix_stopped', 'complete')
                    or prefix.get('native_reader') != '0xCFD388'
                    or prefix.get('wire_profile') != saved_player_wire_prefix.WIRE_PROFILE):
                reject('target_boundary_or_profile_unverified')
                continue
            if not any(isinstance(marker, dict) and marker.get('offset') == start
                       and marker.get('kind') == 'ACTUAL_PLAYER_tag' and marker.get('value') == 2
                       for marker in prefix.get('validated_markers', [])):
                reject('target_tag_not_checked')
                continue
            key = (start, common, witness['identity_offset'])
            if key not in found:
                if len(found) >= MAX_START_GEOMETRIES:
                    exhausted = True
                    break
                found[key] = {
                    'record_start': start, 'common_start': common,
                    'identity_offset': witness['identity_offset'], 'end': witness['end'],
                    'identity': witness['identity'], 'name_indices': witness['name_indices'],
                    'checked_prefix_ends': [], 'preceding_person_index': index - 1,
                    'qualification': 'checked_target_prefix_from_preceding_ordinal_boundary',
                    'wire_profile': prefix['wire_profile'],
                    'wire_profile_is_conditional': True,
                    'certified_person_record': False,
                }
            ends = found[key]['checked_prefix_ends']
            if end not in ends:
                if len(ends) >= MAX_PREFIX_SUMMARIES:
                    exhausted = True
                    break
                ends.append(end)
        if exhausted:
            break
    geometries = [found[key] for key in sorted(found)]
    for geometry in geometries:
        geometry['checked_prefix_ends'].sort()
    return geometries, rejected, exhausted


def _range(packet, start, limit):
    end = packet.get('end')
    if packet.get('start', start) != start or type(end) is not int or not start <= end <= limit:
        raise ValueError('Saved form decoder crossed the candidate common-body bound')
    return end


def _decode(data, geometry, offset, limit):
    record_start, common = geometry['record_start'], geometry['common_start']
    result = {'state': 'stopped', 'form_section_present': None,
              'form_groups_complete': False, 'group_count': None,
              'total_row_count': None, 'groups': [], 'rows': [],
              'offset': offset, 'limit': limit, 'next_offset': None,
              'reason': None, 'checked_ranges': {}}
    try:
        front = saved_form_player.locate_f0(data, record_start, common)
        front_end = _range(front, record_start, common)
        result['checked_ranges']['player_prefix'] = {'start': record_start, 'end': front_end}
        if front['state'] == 'absent':
            result.update(state='absent', form_section_present=False,
                          reason='PLAYER_F0_not_stored')
            return result
        if front['state'] != 'present':
            result.update(reason=front.get('stop_reason'), next_native_reader=front.get('next_native_reader'))
            return result
        f0_start = front.get('f0_start')
        if type(f0_start) is not int or f0_start != front_end:
            raise ValueError('Saved form F0 handoff differs from checked prefix end')
        container = saved_form_container.locate_form_groups(data, f0_start, common)
        container_end = _range(container, f0_start, common)
        result['checked_ranges']['F0_container'] = {'start': f0_start, 'end': container_end}
        if container['state'] == 'absent':
            result.update(state='absent', form_section_present=False,
                          reason='PLAYER_F0_58_not_stored')
            return result
        if container['state'] != 'present':
            result.update(reason=container.get('stop_reason'), next_native_reader=container.get('next_native_reader'))
            return result
        form_start = container.get('form_start')
        if type(form_start) is not int or form_start != container_end:
            raise ValueError('Saved form rows handoff differs from checked container end')
        result['form_section_present'] = True
        reader = BoundedReader(data, form_start, common)
        decoded = saved_form_rows.read_groups(reader)
        end = _range(decoded, form_start, common)
        if reader.offset != end:
            raise ValueError('Saved form reader end mismatch')
        if decoded['group_count'] != len(decoded['groups']) or len(decoded['groups']) > MAX_GROUP_SUMMARIES:
            raise ValueError('Saved form group summary budget or count mismatch')
        summaries = []
        page = []
        ordinal = 0
        previous_group_end = form_start + 1
        for group_index, group in enumerate(decoded['groups']):
            if (group['group_index'] != group_index or group['start'] != previous_group_end
                    or not form_start <= group['start'] <= group['end'] <= end):
                raise ValueError('Saved form group crossed its checked serialized span')
            if group['serialized_row_count'] != len(group['rows']):
                raise ValueError('Saved form original row count mismatch')
            summaries.append({key: group[key] for key in
                              ('kind_code', 'owner_reference_word', 'serialized_row_count')})
            summaries[-1].update(
                group_ordinal=group['group_index'],
                stored_group_team_index=None if group['owner_reference_word'] == 0xFFFFFFFF else group['owner_reference_word'],
                owner_reference_table='TEAM_BASE',
                owner_reference_scope='original_same_snapshot_table_index_unresolved_team_identity')
            previous_row_end = group['start'] + 10
            for row_index, row in enumerate(group['rows']):
                if (row['row_index'] != row_index or row['start'] != previous_row_end
                        or not group['start'] <= row['start'] < row['end'] <= group['end']):
                    raise ValueError('Saved form row crossed its checked serialized span')
                previous_row_end = row['end']
                if offset <= ordinal < offset + limit:
                    page.append({**row, 'form_row_index': ordinal,
                                 'group_ordinal': group['group_index']})
                ordinal += 1
            if previous_row_end != group['end']:
                raise ValueError('Saved form group end differs from its original rows')
            previous_group_end = group['end']
        if previous_group_end != end:
            raise ValueError('Saved form collection end differs from original groups')
        if ordinal != decoded['total_row_count']:
            raise ValueError('Saved form total original row count mismatch')
        result['checked_ranges']['form_groups'] = {'start': form_start, 'end': end}
        result.update(state='available', form_groups_complete=True,
                      group_count=decoded['group_count'], total_row_count=ordinal,
                      groups=summaries, rows=page,
                      next_offset=offset + len(page) if offset + len(page) < ordinal else None,
                      reference_profile=decoded['reference_profile'],
                      reference_profile_is_conditional=True)
    except ValueError as error:
        # A failed candidate decoder never becomes an empty/absent form section.
        result.update(state='stopped', reason=str(error), groups=[], rows=[],
                      group_count=None, total_row_count=None, next_offset=None)
    return result


def get_player_form(filename, person_index, expected_snapshot_id, *, offset=0, limit=50, directory=None):
    """Read one source-pinned PERSON's form page; no ranking or fixture inference."""
    if type(person_index) is not int or not 0 <= person_index < 2**31:
        raise ValueError('Invalid saved PERSON index')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise ValueError('Supply a nonnegative form offset and a form limit from1 to500')
    with saved_person_search.checked_person_context(
            filename, [person_index], expected_snapshot_id, directory=directory) as context:
        rows = [row for row in context['ranked'] if row['person_index'] == person_index]
        if len(rows) != 1:
            raise ValueError('Saved PERSON search did not return the requested index')
        target = rows[0]
        geometries, rejected, exhausted = _starts(context['data'], context['layout'], target)
        neighbours = target.get('neighbour_corroboration', {})
        complete = target.get('search_complete', False) and neighbours.get('search_complete', False) and not exhausted
        state = ('incomplete_candidates' if not complete else
                 'competing_candidates' if len(geometries) > 1 else
                 'unavailable' if not geometries else 'ready')
        form = {'state': state, 'form_section_present': None, 'form_groups_complete': False,
                'group_count': None, 'total_row_count': None, 'groups': [], 'rows': [],
                'offset': offset, 'limit': limit, 'next_offset': None}
        if state == 'ready':
            form = _decode(context['data'], geometries[0], offset, limit)
        reply = {
            'source': 'on-disk save snapshot', 'filename': filename,
            'snapshot_id': context['snapshot_id'], 'saved_metadata': context['saved_metadata'],
            'person_index': person_index, 'declared_person_slots': context['layout'].person_count,
            'form': form, 'typed_start_candidates': geometries,
            'candidate_search': {
                'state': target['state'], 'search_complete': target['search_complete'],
                'neighbour_search_complete': neighbours.get('search_complete', False),
                'budget_reasons': target.get('budget_reasons', []),
                'witness_count': len(target['candidates']),
                'typed_start_summary_complete': not exhausted,
                'typed_start_summary_budget': MAX_START_GEOMETRIES,
                'preceding_packet_work_budget': MAX_INSPECTED_PACKETS,
                'prefix_summary_budget': MAX_PREFIX_SUMMARIES,
                'rejected_packet_counts': rejected,
                'evidence_scope': target['evidence_scope'],
            },
            'evidence_scope': {**_SCOPE, 'form_groups_complete': form['form_groups_complete']},
        }
        if len(json.dumps(reply, ensure_ascii=True).encode('ascii')) > MAX_RESPONSE_BYTES:
            raise ValueError('Saved form response exceeds output budget; request a smaller row limit')
    return reply
