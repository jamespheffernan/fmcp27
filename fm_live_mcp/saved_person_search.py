"""Look up a bounded set of file-local PERSON references in a pinned FM archive."""
from contextlib import contextmanager
from functools import partial
from io import BytesIO
import struct
import json
from threading import BoundedSemaphore

from . import (
    saved_component_stream, saved_name_vectors, saved_person_candidates,
    saved_person_neighbours, saved_player_wire_prefix, snapshot_catalog,
)

MAX_PERSON_INDICES = 32
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
# A decompressed database can occupy several hundred MiB. Bound concurrent buffers.
_BUFFER_SLOT = BoundedSemaphore(1)


def get_name_candidates(filename, person_indices, expected_snapshot_id, *, include_alternatives=False,
                        candidate_offset=0, candidate_limit=100, include_ability=False, directory=None):
    if type(include_ability) is not bool:
        raise ValueError('include_ability must be a boolean')
    if type(include_alternatives) is not bool:
        raise ValueError('include_alternatives must be a boolean')
    if type(candidate_offset) is not int or candidate_offset < 0 or type(candidate_limit) is not int or not 1 <= candidate_limit <= 100:
        raise ValueError('Supply a nonnegative candidate offset and a candidate limit from 1 to 100')
    with checked_person_context(filename, person_indices, expected_snapshot_id,
                                include_ability=include_ability, directory=directory) as context:
        data, ranked = context['data'], context['ranked']
        by_index = {row['person_index']: _project(
            row, include_alternatives, candidate_offset, candidate_limit,
            include_ability=include_ability, source_data=data) for row in ranked}
        rows = [by_index[index] for index in person_indices]
        sizes = {idx: len(json.dumps(row, ensure_ascii=True).encode('ascii')) for idx, row in by_index.items()}
        if sum(sizes[index] for index in person_indices) > MAX_RESPONSE_BYTES:
            raise ValueError('Saved name result exceeds the response budget. Use fewer indices or a smaller candidate_limit.')
        reply = {
            'source': 'on-disk save snapshot', 'filename': filename, 'snapshot_id': context['snapshot_id'],
            'saved_metadata': context['saved_metadata'], 'declared_person_slots': context['layout'].person_count,
            'people': rows,
            'identity_scope': 'Candidate names from saved common-person fields and same-file name tables. '
                              'A candidate does not establish the complete enclosing PERSON record.',
        }
    return reply


@contextmanager
def checked_person_context(filename, person_indices, expected_snapshot_id, *, include_ability=False, directory=None):
    """Share one pinned, wholly checked component and unprojected local witnesses.

    Consumers must finish source reads and construct their reply inside the
    context. Source identity is rechecked on exit before any reply is returned.
    The same buffer semaphore is shared with the existing public name lookup.
    """
    snapshot_catalog.check_filename(filename)
    if not isinstance(expected_snapshot_id, str) or not expected_snapshot_id:
        raise ValueError('Supply the snapshot ID that issued the PERSON references')
    if not isinstance(person_indices, list) or not 1 <= len(person_indices) <= MAX_PERSON_INDICES:
        raise ValueError('Supply between 1 and 32 saved PERSON indices')
    if any(type(index) is not int or not 0 <= index < 2**31 for index in person_indices):
        raise ValueError('Invalid saved PERSON index')
    with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
        current_id = snapshot_catalog.snapshot_id(identity)
        if expected_snapshot_id != current_id:
            raise ValueError('Snapshot identity changed since these references were read')
        root = entries[0].path.split('/')[0]
        databases = [entry for entry in entries if entry.path == f'{root}/game_db.dat']
        if len(databases) != 1:
            raise ValueError('Saved snapshot requires one root game_db.dat')
        metadata = snapshot_catalog._metadata(handle, entries)
        if not _BUFFER_SLOT.acquire(blocking=False):
            raise ValueError('Another saved PERSON lookup is in progress. Retry this request after it finishes.')
        try:
            with saved_component_stream.open_component(handle, databases[0]) as reader:
                with BytesIO() as buffer:
                    while reader.offset < reader.size:
                        buffer.write(reader.take(min(saved_component_stream.BLOCK_SIZE, reader.size - reader.offset)))
                    if reader.source.read(1) or not reader.source.finished:
                        raise ValueError('Saved database frame did not end at its declared extent')
                    data = buffer.getvalue()
                layout = saved_name_vectors.locate(data)
                unique_indices = list(dict.fromkeys(person_indices))
                witnesses = saved_person_candidates.search_candidates(data, layout, unique_indices)
                prefix_decoder = saved_player_wire_prefix.prefix_probe
                if include_ability:
                    prefix_decoder = partial(prefix_decoder, include_ability=True)
                ranked = saved_person_neighbours.corroborate_candidates(
                    data, layout, witnesses, prefix_probe=prefix_decoder,
                )
                yield {'data': data, 'layout': layout, 'ranked': ranked,
                       'snapshot_id': current_id, 'saved_metadata': metadata}
        finally:
            _BUFFER_SLOT.release()


def _project(row, include_alternatives, offset, limit, *, include_ability=False, source_data=None):
    summary = row['neighbour_corroboration']
    preferred = {(entry['common_start'], entry['identity_offset'])
                 for entry in summary['preferred_geometries']}
    can_filter = row['search_complete'] and summary.get('search_complete', False)
    selected = []
    projected_count = 0
    for witness in row['candidates']:
        is_preferred = (witness['common_start'], witness['identity_offset']) in preferred
        if can_filter and preferred and not is_preferred and not include_alternatives:
            continue
        projected_count += 1
        if not offset < projected_count <= offset + limit:
            continue
        geometry = witness['neighbour_evidence']
        selected.append({
            'identity': witness['identity'], 'name_indices': witness['name_indices'],
            'names': witness['names'], 'common_start': witness['common_start'],
            'common_end': witness['common_end'], 'identity_offset': witness['identity_offset'],
            'end': witness['end'], 'next_tag': witness['next_tag'],
            'preferred_local_witness': is_preferred, 'neighbour_tier': geometry['tier'],
            'preceding_packets': len(geometry['preceding']), 'following_packets': len(geometry['following']),
            'certified_person_record': False,
        })
        if include_ability:
            selected[-1]['ability'] = ability_from_preceding(source_data, witness, row['person_index'])
            selected[-1]['ability']['candidate_search_complete'] = can_filter
    return {
        'person_index': row['person_index'], 'state': row['state'],
        'search_complete': row['search_complete'], 'budget_reasons': row['budget_reasons'],
        'evidence_scope': row['evidence_scope'], 'neighbour_corroboration': summary,
        'candidate_count': len(row['candidates']), 'alternatives_omitted': len(row['candidates']) - len(selected),
        'candidate_offset': offset, 'candidate_limit': limit,
        'next_candidate_offset': offset + limit if offset + limit < projected_count else None,
        'candidates': selected,
    }


def ability_from_preceding(data, witness, person_index):
    """Expose signed fields only from checked target prefixes at prior boundaries.

    Following-player prefixes, names, native-ID equality and unprobed starts
    never qualify. Placement remains local and conditional; this is not a full
    PLAYER/PERSON decoder or a native loader acceptance assertion.
    """
    geometries = {}
    rejected = {}
    preceding = witness.get('neighbour_evidence', {}).get('preceding', [])

    def reject(reason):
        rejected[reason] = rejected.get(reason, 0) + 1

    for previous in preceding:
        prefix = previous.get('target_prefix')
        if not isinstance(prefix, dict):
            reject('preceding_boundary_has_no_checked_target_prefix')
            continue
        start, end = prefix.get('start'), prefix.get('end')
        if (type(person_index) is not int or type(previous.get('person_index')) is not int or
                previous.get('person_index') != person_index - 1 or
                type(start) is not int or type(end) is not int or
                previous.get('end') != start or prefix.get('state') != 'typed_prefix_stopped' or
                prefix.get('native_reader') != '0xCFD388' or
                prefix.get('wire_profile') != saved_player_wire_prefix.WIRE_PROFILE):
            reject('target_prefix_boundary_or_profile_unverified')
            continue
        identity_at = previous.get('identity_offset')
        common_start = witness.get('common_start')
        if (data is None or type(common_start) is not int or
                type(identity_at) is not int or identity_at < 0 or identity_at + 12 != start or
                not 0 <= start < end <= len(data) or
                end > common_start or end < start + 127 or data[start] != 2):
            reject('target_prefix_outside_checked_candidate_span')
            continue
        if struct.unpack_from('<I', data, identity_at)[0] != person_index - 1:
            reject('preceding_source_ordinal_mismatch')
            continue
        markers = prefix.get('validated_markers', [])
        if not any(isinstance(m, dict) and m.get('offset') == start and m.get('kind') == 'ACTUAL_PLAYER_tag' and
                   m.get('value') == 2 for m in markers):
            reject('target_tag2_marker_unverified')
            continue
        fields = prefix.get('ability')
        body_start = start + 1
        if (not isinstance(fields, dict) or fields.get('body_start') != body_start or
                fields.get('current_source_offset') != body_start + 6 or
                fields.get('potential_source_offset') != body_start + 8):
            reject('ability_source_offsets_unverified')
            continue
        current, potential = struct.unpack_from('<hh', data, body_start + 6)
        if (type(fields.get('current_native_signed16')) is not int or
                type(fields.get('potential_native_signed16')) is not int or
                fields['current_native_signed16'] != current or
                fields['potential_native_signed16'] != potential):
            reject('ability_values_do_not_match_checked_source')
            continue
        entry = geometries.setdefault(start, {
            'record_start': start, 'body_start': body_start, 'checked_prefix_ends': [],
            'preceding_person_index': person_index - 1,
            'current_native_signed16': current, 'potential_native_signed16': potential,
            'current_source_offset': body_start + 6, 'potential_source_offset': body_start + 8,
        })
        if end not in entry['checked_prefix_ends']:
            entry['checked_prefix_ends'].append(end)
    starts = [geometries[start] for start in sorted(geometries)]
    for entry in starts:
        entry['checked_prefix_ends'].sort()
    state = ('available' if len(starts) == 1 else
             'ambiguous_start_geometries' if starts else 'unavailable')
    return {
        'state': state, 'start_geometries': starts,
        'reason': ('no_checked_target_prefix_from_preceding_ordinal_boundary' if not starts else
                   'multiple_checked_start_geometries_no_single_value_selected' if len(starts) > 1 else None),
        'qualification': 'checked_target_prefix_from_preceding_ordinal_boundary',
        'native_properties': {'current': 'PCAB', 'potential': 'PPAB'},
        'encoding': 'signed16_little_endian', 'ability_fields_complete': bool(starts),
        'placement_complete': False, 'complete_player_body': False,
        'certified_person_record': False, 'native_loader_acceptance': False,
        'wire_profile': saved_player_wire_prefix.WIRE_PROFILE,
        'wire_profile_is_conditional': True,
        'rejected_preceding_packet_reasons': rejected,
    }
