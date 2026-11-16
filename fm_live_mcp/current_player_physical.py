"""Lifetime-safe, spoiler-bounded adapter for official in-client physical fields."""
from datetime import datetime, timezone
import struct
from . import (players, active_match_source, active_match_playback, active_player_physical,
               live_team_sheet_source, active_match_shot_timeline)
from .current_match_report import ReportReadSet


def _project_selected(source, sheet, managed_side):
    """Only already manager-bound selected people; never engine-only entrants."""
    if (sheet.get('source_state') != 'available' or sheet.get('selected_count') is None
            or sheet.get('duplicate_person_indices')):
        return None
    wanted = {}
    for slot in sheet['slots']:
        if slot['category'] not in ('starting_position', 'bench') or slot['person'] is None:
            continue
        person = slot['person']
        key = person['database_index'], person['native_id']
        wanted[key] = {'selected_slot_index': slot['slot_index'],
                       'selected_category': slot['category']}
    result = []
    for actor in source['rows']:
        if actor['side_index'] != managed_side or actor['person'] is None:
            continue
        identity = actor['person']['native_identity']
        key = identity['database_index'], identity['native_id']
        if key not in wanted:
            continue
        result.append({'person': actor['person'], **wanted[key], 'physical': actor['physical']})
    return result


def _inspect(read, base, current_date, coach):
    context, binding = active_match_source.inspect_context(read, base, expected_current_date=current_date)
    out = {'state': 'unavailable', 'reason': context.get('reason'), 'fixture': None,
           'players': None, 'displayed_time_verified': False, 'active_XI_verified': False,
           'fixture_eligibility': 'not_evaluated', 'medical_minutes_recommendation': None}
    if binding is None:
        return out
    fixture = context['bound_active_fixture']
    out['fixture'] = {key: fixture[key] for key in ('date','competition','home_team','away_team')}
    captured = active_match_playback.capture(read, base, client=binding['client'])
    if captured['state'] != 'bound_playback_cursor':
        out.update(reason='matching_playback_unavailable')
        return out
    bound = captured['bound_playback']
    # The unused float is not a field or input of this projection.
    if isinstance(read, ReportReadSet):
        read.observed.pop((bound['playback_address'] + 0x1DDC, 4), None)
    # Native UI client and playback provider may hold distinct GAME_MATCH copies.
    # Bind both through official match identity and the checked cursor, never by
    # assuming their addresses are equal.
    active_match_shot_timeline._verify_bound(read,base,binding['client'],binding['engine'],bound)
    for rva, expected in FRONTIER_SPANS:
        if read(base+rva,len(expected)) != expected:
            raise ValueError('Physical frontier native binding changed')
    frontier = struct.unpack('<I',read(binding['engine']+0x154DC,4))[0]
    if not 0 <= frontier < 65536 or frontier != bound['current_time_slice']:
        out.update(state='withheld',reason='engine_and_playback_frontiers_not_equal')
        return out
    side_indices = list(binding['team_indices'])
    team_index = struct.unpack('<I',read(coach['team_address']+8,4))[0]
    if side_indices.count(team_index) != 1:
        out.update(reason='managed_team_not_in_bound_match')
        return out
    sheet = live_team_sheet_source.inspect(read,base,coach)
    if sheet.get('team',{}).get('database_index') != team_index:
        raise ValueError('Physical selected-squad TEAM changed')
    if sheet.get('source_state') != 'available' or sheet.get('selected_count') is None:
        out.update(reason='current_selected_squad_boundary_unavailable')
        return out
    source = active_player_physical.inspect(read,base,binding['engine'],
                  expected_match_unique_id=bound['official_match_unique_id'])
    selected = _project_selected(source,sheet,side_indices.index(team_index))
    if selected is None:
        out.update(reason='current_selected_squad_ambiguous')
        return out
    out.update(state='available',reason=None,players=selected,
               scope='official_in_client_condition_at_observed_equal_engine_playback_frontiers',
               current_time_slice=bound['current_time_slice'],
               selected_person_count=sheet['selected_count'],
               returned_person_count=len(selected),
               selected_people_without_physical_row=sheet['selected_count']-len(selected),
               publication_at_exact_display_instant_verified=False,
               pixel_parity_verified=False,
               selection_scope='existing_manager_editable_XI_and_bench_identity_intersection',
               limits='Official in-client physical getter source with observed equal frontiers; '
                      'not exact displayed publication, active XI, medical clearance or future-match eligibility. '
                      'Fractional percentages are derived; native integer percentages are separate. '
                      'Engine-only identities and unsynchronized values are withheld.')
    return out


def current_player_physical(bridge, session_id, coach_name=None):
    for attempt in range(2):
        try:
            with bridge.lock, bridge._read_scope(session_id, final_verify=lambda: read.verify()):
                process=bridge._current(session_id);tables=bridge._player_layout(process)
                original,save,_=bridge._world_state(process,tables)
                read=ReportReadSet(original.read,original.observed)
                coach=bridge._select_coach(save,coach_name)
                result=_inspect(read,tables[0]-players.RVA[0],save['current_date'],coach)
                read.verify();bridge._current(session_id)
                packet={**result,'save':bridge._public_save(save),
                        'observed_at':datetime.now(timezone.utc).isoformat(),
                        'saved_file_fallback':False,'atomic_snapshot_verified':False}
                read.verify()
                return packet
        except ValueError as error:
            if str(error) != 'Game state changed during read; retry':
                raise
            if attempt:
                # A moving physical snapshot can change on both bounded attempts.
                # Publish no source facts from either rejected observation.
                bridge._current(session_id)
                return {'state':'withheld','reason':'physical_snapshot_changed_during_read',
                        'fixture':None,'players':None,'save':None,
                        'observed_at':datetime.now(timezone.utc).isoformat(),
                        'source_observation_verified':False,
                        'displayed_time_verified':False,'active_XI_verified':False,
                        'fixture_eligibility':'not_evaluated',
                        'medical_minutes_recommendation':None,
                        'saved_file_fallback':False,'atomic_snapshot_verified':False}


FRONTIER_SPANS = (
    (0x2675e8,bytes.fromhex('b66640f9f68300a9b60500b4e00316aa09fd1995f50300aa')),
    (0x267650,bytes.fromhex('e17e4093e00315aa743e0995400200b4f60700b9e1130091c2431595000300f9600000b408404cf9686200f9')),
    (0x48e6a1c,bytes.fromhex('087c40f9680000b4000d40f9c0035fd6000080d2c0035fd6')),
    (0x44b7028,bytes.fromhex('080c018b096e8a522900a072006969f8c0035fd6')),
    (0x47b8570,bytes.fromhex('290040b908a040f90a4940b95f01096ba00c0054')),
    (0x73adc4,bytes.fromhex('69020039680600b9e832399108fddf086800003688c65db90200001408008052680a00b980de5dbd')),
)
