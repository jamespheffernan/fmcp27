"""One caller-owned live ReadSet for editable bench and both tactical phases.

No substitutions, selection changes, role scoring or clearance decisions. Caller
must check the process/save epoch after capture and before publishing the result.
"""
from copy import deepcopy
from collections import Counter

from . import (assessment_people, database, players, player_profile, player_health,
               player_injury_status, world, live_team_sheet_source,
               live_tactical_assignments_source, prepared_tactics_fields)

# Semantic join between independently named tactical slots and general position
# ratings. It is not a native mask-to-rating dispatch; central sides share a scalar.
POSITION_FIELDS = {
    'GK': 'goalkeeper', 'D(R)': 'defender_right', 'D(L)': 'defender_left',
    'D(C)': 'defender_central', 'D(CL)': 'defender_central', 'D(CR)': 'defender_central',
    'WB(R)': 'wing_back_right', 'WB(L)': 'wing_back_left',
    'DM(C)': 'defensive_midfielder', 'DM(CL)': 'defensive_midfielder',
    'DM(CR)': 'defensive_midfielder', 'M(L)': 'midfielder_left',
    'M(R)': 'midfielder_right', 'M(CL)': 'midfielder_central',
    'M(CR)': 'midfielder_central', 'AM(L)': 'attacking_midfielder_left',
    'AM(R)': 'attacking_midfielder_right', 'AM(C)': 'attacking_midfielder_central',
    'AM(CL)': 'attacking_midfielder_central', 'AM(CR)': 'attacking_midfielder_central',
    'ST(C)': 'striker', 'ST(CL)': 'striker', 'ST(CR)': 'striker',
}


def phase_position(assignment):
    """Keep unproved masks/mappings unknown; base role never chooses a rating."""
    if assignment is None:
        return {'state': 'assignment_absent', 'general_position_field': None,
                'position': None, 'assignment': None}
    position = assignment.get('position')
    pairing = assignment.get('pairing_state')
    if pairing not in ('paired_by_native_slot', 'paired_by_native_phase_map'):
        state = 'pairing_unresolved'
        field = None
    elif (not position or position.get('state') != 'named'
          or prepared_tactics_fields.POSITION_NAMES.get(position.get('native_mask')) != position.get('name')):
        state = 'position_unmapped'
        field = None
    else:
        field = POSITION_FIELDS.get(position['name'])
        state = 'semantic_named_position_join' if field else 'position_not_joined'
    return {'state': state, 'general_position_field': field,
            'position': None if not position else position.get('name'),
            'assignment': deepcopy(assignment),
            'side_specific_familiarity': 'not_established',
            'role_aptitude': 'not_evaluated'}


def _candidate(read, base, tables, people, slot, current_raw, sentinel_raw):
    person = slot['person']
    index = person['database_index']
    canonical = world.pointer(read, people['start'] + index * 8)
    primary, _, identity, native, secondary = assessment_people._person(read, base, people, canonical)
    if (identity['native_identity']['database_index'] != index or native != person['native_id']
            or secondary != person['secondary_id'] or identity['record_kind'] != person['record_kind']):
        raise ValueError('Bench-cover selected PERSON identity changed')
    kind = identity['record_kind']
    row = {'person_index': index, 'native_id': native,
           'native_identity': identity['native_identity'], 'record_kind': kind,
           'display_name': person['display_name'], 'positions': None,
           'profile_state': 'unsupported_player_kind', 'health': None, 'clubs': None,
           'injury_status': {'state': 'unsupported', 'flagged': None,
                             'reason': 'unsupported_player_record_kind'}}
    if kind in ('actual', 'player_staff'):
        database.player_membership(read, base, people, index, primary)
        decoded, token = players.decode(read, primary, tables)
        decoded_native = token[1] if kind == 'player_staff' else token[0]
        if decoded_native != native or token[-1] != secondary:
            raise ValueError('Bench-cover player profile identity changed')
        table = world.pointer(read, primary)
        player_profile.verify_getters(read, base, table)
        positions = {name: read(primary + definition[0], 1)[0]
                     for name, definition in player_profile.POSITIONS.items()}
        if any(value > 20 for value in positions.values()):
            raise ValueError('Bench-cover general position outside0–20 range')
        row.update(display_name=decoded['display_name'], positions=positions,
                   profile_state='stored_general_positions',
                   health=player_health.decode(read, base, primary),
                   clubs=world.player_clubs(read, base, primary, {}),
                   injury_status=player_injury_status.project(
                       read, base, primary, kind, current_raw, sentinel_raw))
        for field in ('condition', 'match_sharpness'):
            value = row['health'].get(field)
            row['health'][field + '_percent'] = None if value is None else value / 100
    return row


def capture(read, base, coach, tables, *, expected_current_date=None):
    """Bounded26-slot capture. ReadSet.verify runs; caller still owns epoch check."""
    if tuple(tables) != tuple(base + rva for rva in players.RVA):
        raise ValueError('Bench-cover runtime layout disagrees')
    sheet = live_team_sheet_source.inspect(read, base, coach)
    tactical = live_tactical_assignments_source.inspect(read, base, coach, 'both')
    current_raw = read(base + world.CURRENT_DATE, 4)
    source_date = player_injury_status.calendar(current_raw)[0].isoformat()
    if expected_current_date is not None and expected_current_date != source_date:
        raise ValueError('Bench-cover current date differs from checked save')
    result = {'source_date': source_date, 'source_state': 'unavailable',
              'unavailable_reason': sheet.get('unavailable_reason'), 'sheet': sheet,
              'tactical_assignments': tactical, 'targets': None, 'bench': None,
              'coverage': {'selected_slot_count': None, 'unique_person_count': None},
              'semantics': 'Named tactical-slot to general-position semantic join; '
                  'central sides share a scalar. No native mask-to-rating dispatch, role aptitude, '
                  'simultaneous cover solution, medical clearance, eligibility or submission is evaluated.'}
    if not live_team_sheet_source.bench_known(sheet):
        result['unavailable_reason'] = result['unavailable_reason'] or 'selection_boundary_unresolved'
        read.verify()
        return result
    if sheet['team'] != tactical['team']:
        raise ValueError('Bench-cover tactical and selection TEAM disagree')
    if sheet.get('slot_count') != 26 or len(sheet['slots']) != 26:
        raise ValueError('Bench-cover editable slot extent changed')
    assessment_people.verify_native(read, base)
    player_injury_status.verify_native(read, base)
    sentinel = read(base + player_injury_status.SENTINEL_DATE, 4)
    people = database.table(read, base, 'people')
    selected = [slot for slot in sheet['slots']
                if slot['category'] in ('starting_position', 'bench') and slot['person'] is not None]
    identities = {}
    for slot in selected:
        index = slot['person']['database_index']
        if index not in identities:
            identities[index] = _candidate(read, base, tables, people, slot, current_raw, sentinel)
    targets, bench = [], []
    phase_maps = {}
    for phase in live_tactical_assignments_source.PHASES:
        assignments = tactical.get('phases', {}).get(phase, {}).get('assignments')
        phase_maps[phase] = {} if assignments is None else {row['slot_index']: row for row in assignments}
        if assignments is not None and len(phase_maps[phase]) != len(assignments):
            raise ValueError('Bench-cover phase slot duplicated')
    for slot in selected:
        row = {**deepcopy(identities[slot['person']['database_index']]),
               'slot_index': slot['slot_index'], 'category': slot['category'],
               'bench_ordinal': slot['bench_ordinal']}
        if slot['category'] == 'starting_position':
            row['phases'] = {}
            for phase, assignments in phase_maps.items():
                assignment = assignments.get(slot['slot_index'])
                if assignment is not None and assignment.get('person') != slot['person']:
                    raise ValueError('Bench-cover phase PERSON disagrees with current sheet')
                row['phases'][phase] = phase_position(assignment)
            targets.append(row)
        else:
            bench.append(row)
    counts = Counter(slot['person']['database_index'] for slot in selected)
    result.update(source_state='available' if tactical['source_state'] == 'available' else 'partial',
                  unavailable_reason=None if tactical['source_state'] == 'available' else 'phase_source_partial',
                  targets=targets, bench=bench,
                  coverage={'selected_slot_count': len(selected), 'unique_person_count': len(identities),
                            'starting_count': len(targets), 'bench_count': len(bench),
                            'empty_starting_slot_indices': [s['slot_index'] for s in sheet['slots']
                                if s['category'] == 'starting_position' and s['person'] is None],
                            'empty_bench_slot_indices': [s['slot_index'] for s in sheet['slots']
                                if s['category'] == 'bench' and s['person'] is None],
                            'complete_starting_identities': len(targets) == 11,
                            'duplicate_person_indices': sorted(i for i,n in counts.items() if n > 1),
                            'general_profiles_available': sum(row['positions'] is not None for row in identities.values()),
                            'current_injury_status_checked': sum(row['injury_status']['state'] == 'checked' for row in identities.values()),
                            'complete_both_phase_position_joins': len(targets) == 11 and all(
                                value['general_position_field'] is not None
                                for row in targets for value in row['phases'].values())})
    read.verify()
    return result
