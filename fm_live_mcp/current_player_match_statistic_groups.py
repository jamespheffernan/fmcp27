"""Compose proved resident statistic groups on one checked canonical row set.

The caller supplies one ReadSet and performs its final physical verification
after every lifetime callback. Composition establishes no native clock fence,
atomic publication, on-pitch membership or whole-side aggregate.
"""
from copy import deepcopy
import math

from . import current_player_chance_quality_statistics as chance_quality
from . import current_player_defensive_statistics as defensive
from . import current_player_delivery_statistics as delivery
from . import current_player_match_statistics as attacking
from . import current_player_recovery_statistics as recovery
from . import current_player_running_statistics as running
from . import current_player_keeper_incident_statistics as keeper_incident
from . import current_player_aerial_statistics as aerial


GROUPS = (
    ('attacking', attacking, ('shots', 'shots_on_target', 'key_passes', 'chances_created')),
    ('defensive', defensive, ('tackles_attempted', 'tackles_completed', 'interceptions', 'clearances')),
    ('running', running, ('distance_metres', 'sprints')),
    ('recovery', recovery, ('possession_won', 'possession_lost', 'pressures_attempted', 'pressures_completed')),
    ('delivery', delivery, ('crosses_attempted', 'crosses_completed', 'open_play_crosses_attempted', 'open_play_crosses_completed', 'dribbles_made')),
    ('chance_quality', chance_quality, ('expected_goals', 'expected_assists', 'open_play_key_passes', 'progressive_passes', 'open_play_final_third_passes')),
    ('keeper_incident', keeper_incident, ('saves_held','saves_parried','saves_tipped','total_saves','fouls_committed','yellow_cards_received','red_cards_received')),
    ('aerial', aerial, ('aerial_duels_attempted','aerial_duels_completed')),
)
COMMON = ('side_index', 'engine_array_index', 'identity_state', 'person', 'state')
FALSE_FLAGS = ('native_timestamp_association', 'displayed_time_verified', 'counter_publication_fence_verified',
               'atomic_snapshot_verified', 'participation_verified', 'complete_side_total_verified')
AVAILABLE = 'available_native_statistic_observation'
STATES = {AVAILABLE, 'unavailable_identity', 'unavailable_stats', 'unavailable_stats_person_mismatch'}
FLOATS = {'distance_metres', 'expected_goals', 'expected_assists'}
SUMS = {'open_play_crosses_attempted', 'open_play_crosses_completed'}


def _qualifiers():
    fields = {field: {'encoding': 'unsigned native byte', 'range': [0, 255], 'byte_wrap_possible': True}
              for _, _, names in GROUPS for field in names}
    for field in SUMS:
        fields[field] = {'encoding': 'sum of two unsigned native bytes', 'range': [0, 510],
                         'sum_wraps_to_byte': False, 'constituent_byte_wrap_possible': True}
    fields['distance_metres'] = {'encoding': 'native float32', 'unit': 'metres',
                                 'unit_binding': 'DistanceRan raw mode; native mode0 scales by0.001 into UI kilometres formatter',
                                 'native_time_or_effort_or_speed_threshold_verified': False}
    fields['sprints']['sprint_speed_threshold_verified'] = False
    for field in ('expected_goals', 'expected_assists'):
        fields[field] = {'encoding': 'unscaled native float32', 'unit': field,
                         'per_shot_value_or_chance_category_verified': False}
    fields['expected_goals']['source'] = 'same event float addend to named team xG and individual accumulator'
    fields['expected_assists']['source'] = 'official ExpectedAssists individual exporter'
    fields['open_play_final_third_passes'] = {'encoding': 'signed native int16', 'range': [0, 32767],
                                             'negative_policy': 'reject; no special -1 sentinel',
                                             'final_third_entry_interpretation_verified': False}
    fields['progressive_passes']['distance_or_angle_threshold_verified'] = False
    fields['pressures_attempted']['source'] = 'named QME_STAT_MANAGER stat12 writer; no supported individual property getter'
    fields['pressures_completed']['possession_regain_interpretation_verified'] = False
    fields['total_saves']['native_expression'] = '(saves_held+saves_parried+saves_tipped)&255'
    fields['total_saves']['sum_wraps_to_byte'] = True
    for field in ('saves_held','saves_parried','saves_tipped','total_saves'):
        fields[field]['goalkeeper_role_or_shot_difficulty_verified'] = False
    for field in ('fouls_committed','yellow_cards_received','red_cards_received'):
        fields[field]['incident_chronology_or_current_eligibility_verified'] = False
    fields['red_cards_received']['exact_native_consumer_label'] = 'red_cards_recieved'
    for field,label in [('aerial_duels_attempted','AerialDuelsAttempted'),('aerial_duels_completed','AerialDuelsCompleted')]:
        fields[field]['official_property_label'] = label
        fields[field]['aerial_win_equivalence_opponent_or_location_verified'] = False
    return fields


def _indexed(projection, fields, expected_match_unique_id):
    if projection['official_match_unique_id'] != expected_match_unique_id:
        raise ValueError('Resident statistic group match identity differs')
    if any(projection[flag] is not False for flag in FALSE_FLAGS):
        raise ValueError('Resident statistic group makes an unsupported timing or population claim')
    indexed = {}
    for row in projection['rows']:
        side, slot = row['side_index'], row['engine_array_index']
        if type(side) is not int or type(slot) is not int or side not in (0, 1) or not 0 <= slot < 26:
            raise ValueError('Invalid resident statistic row key')
        key = side, slot
        if key in indexed or row['state'] not in STATES:
            raise ValueError('Duplicate resident statistic row key or invalid state')
        for field in fields:
            value = row[field]
            if row['state'] != AVAILABLE:
                if value is not None:
                    raise ValueError('Unavailable resident statistic became a numeric value')
            elif field in FLOATS:
                if type(value) is not float or not math.isfinite(value) or value < 0:
                    raise ValueError('Invalid composed native float statistic')
            else:
                maximum = 510 if field in SUMS else 32767 if field == 'open_play_final_third_passes' else 255
                if type(value) is not int or not 0 <= value <= maximum:
                    raise ValueError('Invalid composed native integer statistic')
        indexed[key] = row
    if set(indexed) != {(side, slot) for side in (0, 1) for slot in range(26)}:
        raise ValueError('Resident statistic group must contain all52 canonical slots')
    available = sum(row['state'] == AVAILABLE for row in indexed.values())
    coverage = {'resident_slots': 52, 'available_statistic_rows': available,
                'unavailable_rows': 52-available, 'complete_on_pitch_population_verified': False}
    state = 'available' if available == 52 else 'available_partial' if available else 'unavailable'
    if projection['coverage'] != coverage or projection['state'] != state:
        raise ValueError('Resident statistic group coverage differs from its rows')
    return indexed


def inspect(read, base, engine, *, expected_match_unique_id):
    """Append proved fields to the existing attacking row identity/state/fields.

    Every group uses this same read object. No public caller can supply groups
    from separate historical captures through this API. Caller still owns the
    final physical verification after its actual scope-exit lifetime callback.
    """
    projections = [(name, fields, module.inspect(read, base, engine,
                    expected_match_unique_id=expected_match_unique_id)) for name, module, fields in GROUPS]
    _, attack_fields, attack = projections[0]
    baseline = _indexed(attack, attack_fields, expected_match_unique_id)
    rows = deepcopy(attack['rows'])
    output = {(row['side_index'], row['engine_array_index']): row for row in rows}
    for _, fields, projection in projections[1:]:
        current = _indexed(projection, fields, expected_match_unique_id)
        for key, first in baseline.items():
            if any(current[key][field] != first[field] for field in COMMON):
                raise ValueError('Resident statistic groups disagree on canonical identity or availability')
            output[key].update({field: current[key][field] for field in fields})
    return {'state': attack['state'], 'source': 'typed_owned_resident_GAME_MATCH_PLAYER_STATS_composed',
            'official_match_unique_id': expected_match_unique_id, 'rows': rows,
            'coverage': deepcopy(attack['coverage']), 'field_qualifiers': _qualifiers(),
            **{flag: False for flag in FALSE_FLAGS},
            'scope': 'One canonical resident row set with matched identity and availability across all groups. '
                     'Requires caller final recheck. No native time, displayed minute, on-pitch membership, '
                     'atomic publication, completed-match or complete-side-total claim. Field labels and '
                     'qualifiers do not establish location, opportunity denominators or tactical cause.'}
