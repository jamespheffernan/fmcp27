"""Retained possession won/lost events; never pressure-regain attribution."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import struct

from .saved_match_player_recoveries import decode_player_recoveries

CATEGORIES = {52: 'possession_won', 53: 'possession_lost'}
PERIOD_NAMES = ('first_half', 'second_half', 'extra_time_first_half', 'extra_time_second_half')
THIRDS = ('defensive_third', 'middle_third', 'final_third')
WITNESS_MIN_SAMPLES = 50
# Native units from the centre line. The deepest tracked player of a side (its goalkeeper) averaged
# 36 to 46 in each half of nine retained matches (13 November 2026); an outfield player does not reach 25.
WITNESS_MIN_DEPTH = 25.0
BEYOND_GOAL_LINE_NATIVE = 5.0     # an anchor further than this behind a goal line is left unplaced


def decode_orientation(tracking):
    """Periods and each side's defended end from the retained record's own orientation profile.

    The profile (16 bytes beside the tracking streams) is what the game's average-position and heat
    maps use to turn every side the same way: three tick boundaries at which the sides change ends
    (-1 = none) and the side that starts positive. `tracking_positive_orientation` is that branch;
    a side it calls positive defends the negative native_y end. A period's end is published for a
    side only when an independent witness agrees: the side's deepest tracked player in that period
    (its goalkeeper) must average at least WITNESS_MIN_DEPTH on the predicted end."""
    from .live_average_positions import tracking_positive_orientation
    unavailable = dict(state='unavailable_no_orientation_profile', clock_domain='native_playback_time_slice',
                       ends_change_ticks=None, periods=[])
    if not isinstance(tracking, dict) or not isinstance(tracking.get('orientation_profile'), bytes):
        return unavailable
    profile = tracking['orientation_profile']
    if len(profile) != 16:
        raise ValueError('Unsupported possession orientation profile')
    boundaries = list(struct.unpack_from('<iii', profile))
    tracking_positive_orientation(profile, 0, 0)          # validates boundaries and flags
    cuts = []
    for value in boundaries:
        if value == -1:
            break
        if value <= (cuts[-1] if cuts else 0):
            raise ValueError('Unordered possession orientation boundaries')
        cuts.append(value)
    if not cuts:
        return dict(unavailable, state='unavailable_no_period_boundary', ends_change_ticks=boundaries)
    means = {}
    played = [0] * (len(cuts) + 1)
    for row in tracking.get('players') or []:
        side, start, samples = row.get('side_index'), row.get('start_tick'), row.get('samples')
        if side not in (0, 1) or type(start) is not int or not isinstance(samples, bytes) or len(samples) % 4:
            raise ValueError('Unsupported possession orientation tracking row')
        sums = [[0.0, 0] for _ in range(len(cuts) + 1)]
        for index, pair in enumerate(struct.iter_unpack('<hh', samples)):
            if pair == (0, 0):
                continue
            tick = start + index * 24
            bucket = sums[sum(tick >= cut for cut in cuts)]
            bucket[0] += pair[1] * 0.01
            bucket[1] += 1
        for period, (total, count) in enumerate(sums):
            played[period] += count
            if count >= WITNESS_MIN_SAMPLES:
                mean = total / count
                best = means.get((side, period))
                if best is None or abs(mean) > abs(best['mean_native_y']):
                    means[side, period] = dict(stored_player_slot=row.get('stored_player_slot'),
                                               mean_native_y=round(mean, 2), samples=count)
    # The second boundary is the end of normal time. A period after it is listed only when the record
    # holds tracking there (extra time was played).
    count = len(cuts) + 1
    while count > 2 and not played[count - 1]:
        count -= 1
    periods = []
    for index, name in enumerate(PERIOD_NAMES[:count]):
        start = cuts[index - 1] if index else 0
        end = cuts[index] if index < len(cuts) else None
        sides = []
        for side in (0, 1):
            positive_end = not tracking_positive_orientation(profile, side, start)
            witness = means.get((side, index))
            if witness is None:
                state = 'unverified_no_tracking_witness'
            elif abs(witness['mean_native_y']) < WITNESS_MIN_DEPTH or (witness['mean_native_y'] > 0) != positive_end:
                state = 'unverified_tracking_witness_disagrees'
            else:
                state = 'verified_tracking_witness'
            verified = state == 'verified_tracking_witness'
            sides.append(dict(side_index=side, state=state,
                              defended_end=('positive_native_y' if positive_end else 'negative_native_y') if verified else None,
                              profile_defended_end='positive_native_y' if positive_end else 'negative_native_y',
                              deepest_tracked_player=witness))
        periods.append(dict(period=name, start_tick=start, end_tick_exclusive=end, sides=sides))
    return dict(state='available', clock_domain='native_playback_time_slice', ends_change_ticks=boundaries,
                periods=periods,
                boundary_semantics='Ticks at which the game\'s orientation branch has the sides change ends; the first is '
                                   'the half-time change. Whether it is the first half\'s last tick or the second half\'s '
                                   'first is not established: no event carried a clock inside the interval in nine matches.')


def _place(orientation, side, start, end):
    """(period name, defended end or None) for an event's clocks; (None, None) across a boundary."""
    for period in (orientation or {}).get('periods') or []:
        if period['start_tick'] <= start <= end and (period['end_tick_exclusive'] is None or end < period['end_tick_exclusive']):
            return period['period'], period['sides'][side]['defended_end']
    return None, None


def decode_possession_events(events, players, fixture, *, native_match_key, pitch_geometry=None, orientation=None):
    if not isinstance(events, bytes) or len(events) % 56 or len(events) > 30000 * 56:
        raise ValueError('Invalid complete possession event vector')
    records = [events[i:i+56] for i in range(0, len(events), 56)]
    ids = [struct.unpack_from('<I', e, 44)[0] for e in records]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate possession source event ID')
    if not isinstance(players, list) or len(players) > 52:
        raise ValueError('Invalid possession roster extent')
    roster = {}; people = set()
    for p in players:
        side, slot = p.get('side_index'), p.get('stored_player_slot')
        if type(side) is not int or side not in (0, 1) or type(slot) is not int or not 0 <= slot < 26 or (side, slot) in roster:
            raise ValueError('Ambiguous possession actor side/slot')
        team = fixture['home_team' if side == 0 else 'away_team']
        if (p.get('fixture_key', p.get('native_match_key')) != native_match_key or p.get('team_index_word') != team['database_index']
                or p.get('canonical_team_id') != team['native_id']):
            raise ValueError('Possession actor fixture/TEAM differs')
        child = bytes.fromhex(p['raw_child_hex'])
        values = decode_player_recoveries(child); delta = 4 if child[0] < 2 else 0
        if (child[0] != p['person_reference_tag'] or int.from_bytes(child[1:5+delta], 'little') != p['person_index_word']
                or hashlib.sha256(child).hexdigest() != p['row_sha256']
                or any(p.get(k) != values[k] for k in CATEGORIES.values())):
            raise ValueError('Possession native player byte identity/counter differs')
        person, name = p.get('canonical_person_id'), p.get('person_name')
        if type(person) is not int or person <= 0 or person in people or not isinstance(name, str) or not name:
            raise ValueError('Unresolved or duplicate canonical possession actor')
        people.add(person); roster[side, slot] = p
    selected = [(i, e) for i, e in enumerate(records) if e[42] in CATEGORIES]
    if any(e[40] not in (0, 1) for _, e in selected):
        raise ValueError('Invalid possession event side')
    counts = Counter((e[40], e[39], e[42]) for _, e in selected)
    sides = []; rows = []
    for side in (0, 1):
        own = [p for (s, _), p in roster.items() if s == side]
        missing = sorted({e[39] for _, e in selected if e[40] == side and (side, e[39]) not in roster})
        checks = []
        for p in own:
            slot = p['stored_player_slot']
            checks.append(dict(person_native_id=p['canonical_person_id'], person_name=p['person_name'], stored_player_slot=slot,
                **{field: p[field] for field in CATEGORIES.values()},
                source_possession_won_events=counts[side, slot, 52], source_possession_lost_events=counts[side, slot, 53],
                counts_match=all(counts[side, slot, code] == p[field] for code, field in CATEGORIES.items())))
        available = bool(own) and not missing and all(c['counts_match'] for c in checks)
        sides.append(dict(side_index=side, team_native_id=fixture['home_team' if side == 0 else 'away_team']['native_id'],
            state='available_complete_player_counter_closure' if available else 'unavailable_possession_counter_closure',
            captured_player_counter_checks=len(checks), player_checks=checks, missing_actor_slots=missing,
            possession_won=sum(p['possession_won'] for p in own) if available else None,
            possession_lost=sum(p['possession_lost'] for p in own) if available else None,
            source_possession_won_event_count=sum(n for (s, _, c), n in counts.items() if s == side and c == 52),
            source_possession_lost_event_count=sum(n for (s, _, c), n in counts.items() if s == side and c == 53)))
        if not available:
            continue
        for index, e in selected:
            if e[40] != side:
                continue
            p = roster[side, e[39]]; x, y = struct.unpack_from('<ff', e, 24)
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError('Nonfinite native possession event anchor')
            inside = None
            if pitch_geometry is not None:
                width, length = (pitch_geometry.get(k) for k in ('half_width_native', 'half_length_native'))
                if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 1000 for v in (width, length)):
                    raise ValueError('Invalid native possession pitch geometry')
                inside = abs(x) <= width and abs(y) <= length
            start_clock, end_clock = struct.unpack_from('<H', e, 34)[0], struct.unpack_from('<H', e, 50)[0]
            period, defended = _place(orientation, side, start_clock, end_clock)
            fraction = None
            if defended is not None and pitch_geometry is not None and abs(y) <= length + BEYOND_GOAL_LINE_NATIVE:
                # Only the length axis places an event: one over a touchline keeps its place along the
                # pitch, and one just over a goal line (the ball went out there) counts at that end.
                forward = y if defended == 'negative_native_y' else -y
                fraction = round(min(1.0, max(0.0, (forward + length) / (2 * length))), 4)
            rows.append(dict(record_index=index, event_id=struct.unpack_from('<I', e, 44)[0], side_index=side,
                period=period, defended_end=defended, length_fraction_from_own_goal=fraction,
                stored_player_slot=e[39], person_native_id=p['canonical_person_id'], person_name=p['person_name'],
                event_kind=CATEGORIES[e[42]], native_category_code=e[42], native_flags_word=struct.unpack_from('<H', e, 48)[0],
                source_native_anchor={'native_x': x, 'native_y': y, 'inside_native_pitch_extents': inside},
                anchor_semantics='native event source-ancestry position; exact possession-transition location not independently proved',
                transition_location=None, pressure_regain=None, press_played_through=None,
                other_player_native_id=None, pressure_event_id=None,
                native_start_clock_word=start_clock, native_end_clock_word=end_clock,
                displayed_time=None))
    rows.sort(key=lambda r: r['record_index'])
    for side in sides:
        own_rows = [r for r in rows if r['side_index'] == side['side_index']]
        verified = side['state'] == 'available_complete_player_counter_closure'
        side['source_native_anchor_count'] = len(own_rows) if verified else None
        side['outside_pitch_native_anchor_count'] = (sum(r['source_native_anchor']['inside_native_pitch_extents'] is False for r in own_rows)
            if verified and pitch_geometry is not None else None)
        side['defended_end_by_period'] = ([dict(period=p['period'], **{k: p['sides'][side['side_index']][k]
                                                                       for k in ('defended_end', 'state')})
                                           for p in orientation['periods']] if orientation and verified else None)
        thirds = None
        if verified and orientation and orientation.get('periods'):
            thirds = {kind: dict.fromkeys(THIRDS + ('unplaced',), 0) for kind in CATEGORIES.values()}
            for r in own_rows:
                fraction = r['length_fraction_from_own_goal']
                thirds[r['event_kind']]['unplaced' if fraction is None else THIRDS[min(2, int(fraction * 3))]] += 1
        side['anchor_thirds'] = thirds
    return dict(state='available' if all(s['state'].startswith('available_') for s in sides) else 'partial',
        sides=sides, events=rows, native_event_count=len(records), pitch_geometry=pitch_geometry,
        orientation=orientation if orientation is not None else dict(state='not_read', periods=[]),
        policy='All rostered player PossessionWon/D7 and PossessionLost/D8 counters, including zero players, must close per side before rows publish.',
        limits=['Possession won/lost totals are not completed-pressure regains, tackles or the press being played through.',
                'Native event anchors are stored source-ancestry positions, not independently verified transition points; no human left/right or metres are inferred.',
                'defended_end comes from the game\'s own orientation profile and is published per side and period only when the side\'s deepest tracked player agrees. length_fraction_from_own_goal (0 = own goal line, 1 = the opposition\'s) and anchor_thirds (equal thirds of the length) place the anchor along the length only, with the anchor\'s caveat: an anchor over a touchline keeps its place, one just over a goal line counts at that end, and an event across a period boundary or in an unverified period stays unplaced.',
                'No paired opposing loser/winner, pressure linkage or tactical cause is inferred from proximity.',
                'Pressure action28 loses its type in generic retained category0; absent pressure attribution is unknown, not zero.'])


def get_retained_possession_events(bridge,session_id,fixture_ref,*,team_native_id=None,person_native_id=None,
                                      offset=0,limit=100,expected_source_id=None,coach_index=None):
    """One current-session retained fixture; full counter coverage before paging."""
    from . import players as layout
    from .match_data_query import capture_epoch
    from .live_match_backing import read_selected_matches
    from .live_match_team_totals import decode_team_totals
    from .live_match_players import project_frame
    from .live_retained_shots import capture_source,_validate_team_oracle,_actor_rows
    if not isinstance(fixture_ref,str)or not fixture_ref:raise ValueError('Select one retained RESULT fixture reference')
    for value in(team_native_id,person_native_id):
        if value is not None and(type(value)is not int or value<=0):raise ValueError('Invalid canonical possession selector')
    if person_native_id is not None and team_native_id is None:raise ValueError('A selected possession player requires its team')
    if type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=500:raise ValueError('Invalid possession page')
    if expected_source_id is not None and(not isinstance(expected_source_id,str)or len(expected_source_id)!=64 or any(c not in'0123456789abcdef'for c in expected_source_id)):
        raise ValueError('Invalid possession source pin')
    if offset and expected_source_id is None:raise ValueError('Possession continuation requires the first source_id')
    epoch=capture_epoch(bridge,session_id)
    observed_first=bridge.get_save(session_id)['save']
    with bridge.lock,bridge._read_scope(session_id):
        process=bridge._current(session_id);tables=bridge._player_layout(process);read,_,_=bridge._world_state(process,tables)
        verify_native(read,tables[0]-layout.RVA[0]);read.verify();bridge._current(session_id)
    backing=read_selected_matches(bridge,session_id,[fixture_ref],include_players=True)
    records=backing['records']
    if len(records)!=1 or records[0]['fixture_ref']!=fixture_ref:raise ValueError('Possession backing fixture scope differs')
    record=records[0];fixture=record['fixture_native'];key=record['key']
    selected_sides=[side for side,k in enumerate(('home_team','away_team'))if team_native_id is None or fixture[k]['native_id']==team_native_id]
    if not selected_sides:raise ValueError('Selected team is not in the retained fixture')
    base=dict(fixture_ref=fixture_ref,fixture=fixture,native_match_key=key,source_kind='active_human_retained_cbe_possession_events',
              saved_file_fallback=False,atomic=False,observed_save_first=observed_first,source_id=None,events=[],sides=[],offset=offset,limit=limit,
              total_count=None,available_row_count=None,next_offset=None,team_native_id=team_native_id,person_native_id=person_native_id)
    if record['state']!='available':return {**base,'state':record['state']}
    raw=record['raw'];totals=decode_team_totals(raw)
    if totals['result_key']!=key:raise ValueError('Possession raw frame result key differs')
    _validate_team_oracle(fixture,totals['teams'])
    complete=project_frame(raw,key)
    if not complete['coverage']['complete_side_sections']:raise ValueError('Incomplete native possession player side sections')
    roster=[{**p,**decode_player_recoveries(bytes.fromhex(p['raw_child_hex']))}for p in _actor_rows(record,None)]
    if len(roster)!=sum(complete['coverage']['stored_rows_per_side']):raise ValueError('Possession full roster count differs')
    # include_tracking also verifies the native guards of the orientation branch (TRACKING_NATIVE_SPANS)
    source=capture_source(bridge,session_id,fixture_ref,key,fixture,coach_index,include_tracking=True)
    if source['state']!='available':return {**base,'state':source['state']}
    orientation=decode_orientation(source.get('tracking'))
    decoded=decode_possession_events(source['events'],roster,fixture,native_match_key=key,pitch_geometry=source.get('pitch_geometry'),orientation=orientation)
    if capture_epoch(bridge,session_id)!=epoch:raise ValueError('Possession career epoch changed during capture')
    observed_last=bridge.get_save(session_id)['save']
    if capture_epoch(bridge,session_id)!=epoch:raise ValueError('Possession career epoch changed before publication')
    digest=hashlib.sha256(repr(epoch).encode()+raw+source['events']+json.dumps({'fixture':fixture,'players':roster,'pitch_geometry':source.get('pitch_geometry'),'team':team_native_id,'person':person_native_id,'orientation':orientation},sort_keys=True).encode()).hexdigest()
    if expected_source_id is not None and expected_source_id!=digest:raise ValueError('Possession source or selectors changed; restart paging')
    sides=[r for r in decoded['sides']if r['side_index']in selected_sides]
    events=[r for r in decoded['events']if r['side_index']in selected_sides and(person_native_id is None or r['person_native_id']==person_native_id)]
    checks=[r for side in sides for r in side['player_checks']if person_native_id is None or r['person_native_id']==person_native_id]
    available=(bool(checks)and all(c['counts_match']for c in checks)
               and all(s['state']=='available_complete_player_counter_closure'for s in sides))
    if person_native_id is not None and not checks:
        return {**base,'state':'unavailable_selected_possession_actor','source_id':digest,'sides':sides}
    end=min(offset+limit,len(events))
    return {**base,**{k:v for k,v in decoded.items()if k not in('sides','events','state')},
            'state':'available'if available else'available_partial','sides':sides,'events':events[offset:end],
            'available_row_count':len(events),'total_count':len(events)if available else None,
            'source_id':digest,'observed_save_last':observed_last,'observed_at':datetime.now(timezone.utc).isoformat(),'next_offset':end if end<len(events)else None,
            'complete_native_roster_rows_per_side':complete['coverage']['stored_rows_per_side'],
            'raw_frame_sha256':hashlib.sha256(raw).hexdigest(),
            'selected_counter_checks':checks if person_native_id is not None else None}



def verify_native(read, base):
    for at, expected in NATIVE_SPANS:
        if read(base + at, len(expected)) != expected:
            raise ValueError('Retained possession native binding changed')


NATIVE_SPANS = (
    (0x493c2e0, bytes.fromhex('48a98139e00300f909a00191e81700f9e91f00f9367968f8565b01b44bad813928008052e91740f90801094b081d4093eba301a9c92e41f9c82a41f9290108cb7f0d89eb6200005417796bf802000014170080d2')),
    (0x493c430, bytes.fromhex('286540b929a14139480118363f550071')),
    (0x493c4d8, bytes.fromhex('3f750071481e01544b5600b06bb10b918c0000106d7969788c090d8b80011fd6')),
    (0x5405308, bytes.fromhex('a9008d00')),
    (0x493c72c, bytes.fromhex('e00318aae10319aacf500094c84a208b093942b929050011093902b9f70a01b4e862433908050011e862033953080014')),
    (0x493c79c, bytes.fromhex('e00318aae10319aab3500094c84a208b092142b929050011092102b9770701b4e85e433908050011e85e033937080014')),
    (0x48930ac, bytes.fromhex('090400513f71007188050054280380526a5b00f04a110f918b0000104c6969386b090c8b60011fd6')),
    (0x54023d1, bytes.fromhex('0b09')),
    (0x48930f8, bytes.fromhex('a8068052fbffff1788068052f9ffff17')),
    (0x488a730, bytes.fromhex('89a241393f5500710009407ae0500054201d0013011d00135922009460aa0039772e00b97f62007976660079ea0314aa891240f9693f00b5400140fd600e00fd')),
    (0x488af50, bytes.fromhex('080080922b0540f96a2d40a96c010aeb800100548dfd44932c0540b9aefd41d34f110e8bf00541b811054dcaad01118b1f020c6badb18e9aeab18a9a0dffffb55f010beb401a0054290540b94c0140b93f010c6bcb1900544a0540f9491140f9c9bdffb4e8ffff17')),
    (0x488ab3c, bytes.fromhex('88da40796852027888ae4139689e0039e00314aae73f0394c000003768aa40391f1d0071600000541f31007161000054951a40f9950400b588aa413968a20039')),
    (0x48d8f18, bytes.fromhex('801e42f9e103009182020591c88c0194')),
    (0x48d8f6c, bytes.fromhex('826644b9e0030091e10315aae30313aa8ac5fe97886644b9')),
    (0x205570, bytes.fromhex('e15e4339')),
    (0x205598, bytes.fromhex('e1624339')),
)
