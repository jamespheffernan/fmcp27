"""Opt-in observed candidates: independent player closure, never verified xG rows."""
from collections import defaultdict
import math
import struct

from .saved_match_player_actions import decode_player_actions
from .retained_shot_outcomes import outcome_fields


def _sum32(rows, nonpen=False):
    value=0.
    for row in rows:
        if nonpen and row.get('is_penalty'):
            continue
        value=struct.unpack('<f',struct.pack('<f',value+row['expected_goals']))[0]
    return value


def _ulps(a,b):
    if not all(math.isfinite(v)and v>=0 for v in(a,b)):
        return None
    return abs(struct.unpack('<I',struct.pack('<f',a))[0]-struct.unpack('<I',struct.pack('<f',b))[0])


def verify_observed_side(candidates, roster, actors, team, diagnostic):
    """Require every rostered player, including zero players, to close counts."""
    side=diagnostic['side_index']
    unavailable=lambda reason: ([],{'side_index':side,'state':'unavailable_source_observed_verification',
                                    'unavailable_reason':reason,'observed_shot_count':None})
    if (diagnostic.get('link_errors') or not diagnostic['checks'].get('shot_count_matches')
            or not diagnostic['checks'].get('shots_on_target_matches')):
        return unavailable('native_link_or_team_count_reconciliation_failed')
    rows=[r for r in roster if r['side_index']==side]
    if not rows:
        return unavailable('complete_independent_player_roster_unavailable')
    by_slot=defaultdict(list);event_ids=set()
    for shot in candidates:
        if (shot['side_index']!=side or shot['event_side_index']!=side
                or shot['event_id']in event_ids):
            return unavailable('ambiguous_or_conflicting_attempt_binding')
        event_ids.add(shot['event_id']);by_slot[shot['stored_player_slot']].append(shot)
    seen_slots=set();seen_people=set();controls=[]
    for row in rows:
        slot=row['stored_player_slot'];actor=actors.get((side,slot))
        if slot in seen_slots or not actor:
            return unavailable('ambiguous_or_missing_canonical_actor')
        seen_slots.add(slot)
        pid=actor.get('canonical_person_id')
        if (type(pid)is not int or pid<=0 or pid in seen_people or not actor.get('person_name')
                or actor.get('person_index_word')!=row['person_index_word']
                or actor.get('team_index_word')!=team['team_index']
                or actor.get('canonical_team_id')!=team['team_identity_word']):
            return unavailable('canonical_PERSON_TEAM_identity_not_proved')
        seen_people.add(pid)
        child=bytes.fromhex(row['raw_child_hex']);delta=4 if row['person_reference_tag']<2 else 0
        width=4+delta
        if int.from_bytes(child[1:1+width],'little')!=row['person_index_word']or len(child)<215+delta:
            return unavailable('independent_player_wire_identity_or_profile_differs')
        values=decode_player_actions(child);goals=child[20+delta]
        nonpen=struct.unpack_from('<f',child,211+delta)[0]
        if not math.isfinite(nonpen)or nonpen<0:
            return unavailable('independent_nonpenalty_xg_unavailable')
        observed=by_slot.get(slot,[])
        counts={'shots':len(observed),'shots_on_target':sum(r['native_category_code']in(1,4)for r in observed),
                'goals':sum(r['native_category_code']==1 for r in observed)}
        expected={'shots':values['shots'],'shots_on_target':values['shots_on_target'],'goals':goals}
        if counts!=expected:
            return unavailable('complete_player_shots_targets_goals_do_not_close')
        summed=_sum32(observed);np_sum=_sum32(observed,True)
        controls.append({'stored_player_slot':slot,'actor':actor,'counts':counts,'counts_exact':True,
                         'stored_player_expected_goals':values['expected_goals'],
                         'native_attempt_expected_goals_sum':summed,
                         'player_xg_float32_ulp_distance':_ulps(summed,values['expected_goals']),
                         'stored_player_nonpenalty_expected_goals':nonpen,
                         'native_nonpenalty_expected_goals_sum':np_sum,
                         'player_nonpenalty_xg_float32_ulp_distance':_ulps(np_sum,nonpen)})
    if set(by_slot)-seen_slots:
        return unavailable('attempt_actor_not_in_complete_player_roster')
    control_by_slot={r['stored_player_slot']:r for r in controls};output=[]
    for shot in candidates:
        row=dict(shot);row.update(outcome_fields(row['native_category_code']));value=row.pop('expected_goals');control=control_by_slot[row['stored_player_slot']]
        row.update(native_expected_goals=value,actor=control['actor'],
                   verification_scope='source_observed_counts_actors_verified_xg_unreconciled',
                   field_evidence={'event_link':'unique native event ID and matching side',
                                   'actor':'canonical fixture PERSON/TEAM plus stored slot',
                                   'counts':'all rostered player shots/SOT/goals exact, including zero players',
                                   'native_expected_goals':'stored native value; aggregate reconciliation NOT asserted',
                                   'coordinates':'linked unnormalized native values; units/viewpoint unresolved'},
                   xg_reconciliation={'team_float32_ulp_distance':diagnostic['xg_float32_ulp_distance'],
                                      'player_float32_ulp_distance':control['player_xg_float32_ulp_distance'],
                                      'player_nonpenalty_float32_ulp_distance':control['player_nonpenalty_xg_float32_ulp_distance']})
        output.append(row)
    return output,{'side_index':side,'state':'available_source_observed_counts_verified_xg_unreconciled',
                   'observed_shot_count':len(output),'rostered_players_checked':len(rows),
                   'zero_shot_players_checked':sum(r['counts']['shots']==0 for r in controls),
                   'team_xg_diagnostic':diagnostic,'individual_player_evidence':controls,
                   'verified_shots_promoted':False,'xg_tolerance_widened':False}
