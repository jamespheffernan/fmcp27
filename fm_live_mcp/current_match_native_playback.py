"""Opt-in native playback commentary rows, typed player changes and removal requests.

These blocks read the already bound playback and engine storage, reselect the
consumed bytes immediately, and return unavailable states instead of raising for
an advancing or unsupported optional source. They are source facts, not a
participation history: no active XI, execution order, substitution role or
displayed minute is inferred. Canonical person labels join only through the
same fixture's original side/roster-slot identities.
"""
from . import (active_match_entity_identity, address_book, native_player_removal_source,
               playback_event_actor_identity, playback_event_source)

RETRY_MESSAGE = 'Game state changed during read; retry'
MAX_EVENT_ROWS_RETURNED = 500


def unavailable(reason):
    return {'state': 'unavailable', 'reason': reason, 'rows': None}


def _attempt(operation):
    """Run a physical capture/reselect pair; one retry for changed bytes only."""
    last = None
    for _ in range(2):
        try:
            return operation(), None
        except ValueError as error:
            if str(error) == RETRY_MESSAGE:
                raise
            last = str(error)
            if 'changed' not in last:
                break
    return None, last


def _identity(index, side, slot):
    if side is None or slot is None:
        return None
    actor = index.get((side, slot))
    return {'side_index': side, 'original_slot': slot,
            'canonical_person_id': actor['canonical_person_id'] if actor else None,
            'person_name': actor.get('person_name') if actor else None,
            'identity_state': 'same_match_canonical_original_slot' if actor
                else 'unavailable_canonical_actor_for_original_slot'}


def _unavailable_on_build(reasons):
    return {'state': 'unavailable', 'reason': 'native_decoders_unavailable_on_this_build',
            'build': address_book.build_label(), 'native_sites': reasons[:6], 'rows': None}


@address_book.optional_section('playback_events', _unavailable_on_build)
def _events(raw, base, bound, actors, limit):
    def operation():
        captured = playback_event_source.capture(raw, base, bound)
        verified = playback_event_source.verify_capture(raw, base, captured, bound)
        source = playback_event_source.project(verified)
        rows = source.get('rows')
        result = {k: v for k, v in source.items() if k != 'rows'}
        if rows is None:
            return result | {'rows': None}
        tail = rows[-limit:]
        result |= {'rows_total': len(rows), 'rows_returned': len(tail),
                   'rows_omitted_earliest': len(rows) - len(tail),
                   'row_order': 'native_event_index_ascending',
                   'actor_identity': {'state': 'unavailable', 'reason': actors['reason']}
                       if 'reason' in actors else None}
        if 'reason' in actors:
            return result | {'rows': [row | {'event_players': None} for row in tail]}
        identity = playback_event_actor_identity.capture(raw, base, bound, tail, actors['actors'])
        identity = playback_event_actor_identity.verify_capture(raw, base, bound, identity)
        return result | {'rows': identity['rows'], 'actor_identity': {
            'state': identity['state'], 'source_namespace': identity['source_namespace'],
            'unresolved_canonical_actor_setup': identity['unresolved_canonical_actor_setup'],
            'substitution_actor_roles_verified': False, 'historical_on_pitch_verified': False,
            'native_actor_uid_setup_physically_reselected': True}}
    result, reason = _attempt(operation)
    if result is None:
        return {'state': 'unavailable_native_source_changed_or_unsupported', 'reason': reason, 'rows': None}
    return result | {'time_slice_vs_playback_cursor_verified': False,
        'interpretation': 'Native commentary rows in storage order with raw IDs, flags, importances and '
            'simulation slices; the latest rows are returned when the list exceeds the limit. Actor labels '
            'are same-match canonical original-slot joins only. Role of each PlayerID field, substitution '
            'direction, history completeness, active participation and the relation of TimeSlice to the '
            'playback cursor or a displayed minute are not established. Rows read while the match advances '
            'can be unavailable; unknown is not zero.'}


@address_book.optional_section('player_changes', _unavailable_on_build)
def _changes(raw, base, bound, actors):
    def operation():
        captured = native_player_removal_source.capture(raw, base, bound)
        verified = native_player_removal_source.verify_capture(raw, base, bound, captured)
        return verified, native_player_removal_source.project(verified)
    outcome, reason = _attempt(operation)
    if outcome is None:
        return {'state': 'unavailable_native_source_changed_or_unsupported', 'reason': reason, 'rows': None}
    verified, removal = outcome
    index = {} if 'reason' in actors else {
        (a['side_index'], a['stored_player_slot']): a for a in actors['binding']['players']}
    change_rows = verified['_changes']['rows']
    if change_rows is not None:
        change_rows = [row | {'player_on': _identity(index, row['side_index'], row['player_on_original_slot']),
                              'player_off': _identity(index, row['side_index'], row['player_off_original_slot'])}
                       for row in change_rows]
    removals = removal['rows']
    if removals is not None:
        removals = [row | {'player': _identity(index, row['side_index'], row['player_original_slot'])}
                    for row in removals]
    return {'state': removal['state'], 'official_match_unique_id': removal['official_match_unique_id'],
        'changes': change_rows, 'removal_requests': removals,
        'history_complete': None, 'pending_vs_executed_verified': False,
        'fixed_frame_participation_verified': False,
        'native_change_source_physically_reselected': True,
        'actor_identity_state': 'unavailable' if 'reason' in actors else 'same_match_canonical_original_slot',
        'interpretation': 'Typed native SUBSTITUTION and PLAYER_PUT_ON rows plus removal requests '
            '(PLAYER_TAKEN_OFF, SEND_OFF_PLAYER, INJURE_PLAYER) from the engine change vector, with original '
            'side/roster slots and the native change clock when present. The vector can hold pending or '
            'archived changes: no execution, order, completeness, fixed-frame playing interval or active XI '
            'is inferred. PLAYER_PUT_ON is not a formal starting-XI label; INJURE_PLAYER has a no-op native '
            'apply body. Rows not of these types are reported as unclassified, never dropped silently.'}


def inspect(read, base, binding, bound, *, include_events, event_limit, include_changes):
    raw = getattr(read, 'read', read)
    result = {}
    actors = None
    if include_events or include_changes:
        try:
            actors = active_match_entity_identity.capture_actor_source(
                read, base, binding['engine'], bound['source_match_address'],
                bound['official_match_unique_id'])
        except ValueError as error:
            if str(error) == RETRY_MESSAGE:
                raise
            actors = {'reason': 'canonical_actor_source_unavailable: ' + str(error)}
    if include_events:
        result['playback_events'] = _events(raw, base, bound, actors, event_limit)
    if include_changes:
        result['player_changes'] = _changes(raw, base, bound, actors)
    return result
