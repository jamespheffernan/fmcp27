"""Retained crossing events, qualified by every independent player counter."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import struct

from . import address_book
from .saved_match_player_crosses import decode_player_crosses

CROSS_CATEGORIES = frozenset(range(12, 18))
MAX_EVENTS = 30000


def decode_cross_events(events, players, fixture, native_match_key, pitch_geometry=None):
    if not isinstance(events, bytes) or len(events) % 56 or len(events) // 56 > MAX_EVENTS:
        raise ValueError('Unsupported crossing event extent')
    if type(native_match_key) is not int or native_match_key <= 0 or not isinstance(players, list) or len(players) > 52:
        raise ValueError('Unsupported crossing fixture or roster')
    records = [events[i:i + 56] for i in range(0, len(events), 56)]
    ids = [struct.unpack_from('<I', e, 44)[0] for e in records]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate crossing source event ID')
    roster = {}
    people = set()
    for p in players:
        side, slot = p.get('side_index'), p.get('stored_player_slot')
        if type(side) is not int or side not in (0, 1) or type(slot) is not int or not 0 <= slot < 26 or (side, slot) in roster:
            raise ValueError('Ambiguous crossing roster slot')
        team = fixture['home_team' if side == 0 else 'away_team']
        if (p.get('fixture_key', p.get('native_match_key')) != native_match_key
                or p.get('team_index_word') != team['database_index'] or p.get('canonical_team_id') != team['native_id']):
            raise ValueError('Crossing actor fixture or team differs')
        raw = bytes.fromhex(p['raw_child_hex'])
        delta = 4 if raw[0] < 2 else 0
        if (raw[0] != p['person_reference_tag'] or int.from_bytes(raw[1:5 + delta], 'little') != p['person_index_word']
                or hashlib.sha256(raw).hexdigest() != p['row_sha256']):
            raise ValueError('Crossing player wire identity differs')
        counters = decode_player_crosses(raw)
        if any(type(p.get(k)) is not int or p[k] != counters[k] for k in ('crosses_attempted', 'crosses_completed')):
            raise ValueError('Crossing counters differ from independent wire')
        person, name = p.get('canonical_person_id'), p.get('person_name')
        known = type(person) is int and person > 0 and isinstance(name, str) and bool(name)
        if known:
            if person in people:
                raise ValueError('Duplicate crossing canonical person')
            people.add(person)
        roster[side, slot] = {**p, 'canonical_actor': known}
    selected = [(i, e) for i, e in enumerate(records) if e[42] in CROSS_CATEGORIES]
    if any(e[40] not in (0, 1) for _, e in selected):
        raise ValueError('Invalid crossing event side')
    attempts = Counter((e[40], e[39]) for _, e in selected)
    completed = Counter((e[40], e[39]) for _, e in selected if e[42] == 12)
    sides, output = [], []
    for side in (0, 1):
        own = [p for (s, _), p in roster.items() if s == side]
        missing = sorted({e[39] for _, e in selected if e[40] == side and (side, e[39]) not in roster})
        checks = []
        for p in sorted(own, key=lambda x: x['stored_player_slot']):
            key = side, p['stored_player_slot']
            match = attempts[key] == p['crosses_attempted'] and completed[key] == p['crosses_completed']
            checks.append(dict(person_native_id=p.get('canonical_person_id'), person_name=p.get('person_name'),
                               stored_player_slot=key[1], official_attempted=p['crosses_attempted'],
                               official_completed=p['crosses_completed'], event_attempted=attempts[key],
                               event_completed=completed[key], counters_match=match, canonical_actor=p['canonical_actor']))
        available = bool(own) and not missing and all(c['counters_match'] and c['canonical_actor'] for c in checks)
        side_rows = []
        if available:
            for index, e in selected:
                if e[40] != side:
                    continue
                actor = roster[side, e[39]]
                x, y = struct.unpack_from('<ff', e, 24)
                if not all(math.isfinite(v) for v in (x, y)):
                    raise ValueError('Nonfinite crossing event point')
                direction = bool(struct.unpack_from('<H', e, 48)[0] & 256)
                position = None
                if pitch_geometry is not None:
                    width, length = (pitch_geometry.get(k) for k in ('half_width_native', 'half_length_native'))
                    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 1000 for v in (width, length)):
                        raise ValueError('Invalid crossing pitch geometry')
                    forward = y if direction else -y
                    inside = abs(x) <= width and abs(y) <= length
                    position = dict(attack_relative_longitudinal_coordinate=forward,
                                    inside_native_pitch_extents=inside,
                                    analytical_pitch_third=('defensive' if forward < -length / 3 else 'middle' if forward < length / 3 else 'attacking') if inside else None,
                                    analytical_lateral_channel=('central' if abs(x) <= width / 3 else 'outer') if inside else None)
                side_rows.append(dict(record_index=index, event_id=struct.unpack_from('<I', e, 44)[0], side_index=side,
                                      stored_player_slot=e[39], person_native_id=actor['canonical_person_id'], person_name=actor['person_name'],
                                      native_category_code=e[42], completed=e[42] == 12,
                                      outcome='completed' if e[42] == 12 else 'not_completed',
                                      native_clock_start_raw=struct.unpack_from('<H', e, 34)[0],
                                      native_clock_end_raw=struct.unpack_from('<H', e, 50)[0],
                                      native_event_x=x, native_event_y=y, attacked_goal_positive_native_y=direction,
                                      analytical_event_position=position, recipient_name=None, recipient_person_native_id=None,
                                      shot_event_id=None, goal_event_id=None, specific_failure_reason=None,
                                      ball_release_location=None, intended_destination=None, displayed_time=None))
        categories = Counter(str(e[42]) for _, e in selected if e[40] == side)
        bands = Counter()
        band_completed = Counter()
        for row in side_rows:
            pos = row['analytical_event_position'] or {}
            band = (pos.get('analytical_pitch_third'), pos.get('analytical_lateral_channel'))
            bands[band] += 1
            band_completed[band] += row['completed']
        position_counts = [dict(analytical_pitch_third=t, analytical_lateral_channel=c,
                                attempts=n, completed=band_completed[t, c], not_completed=n - band_completed[t, c])
                           for (t, c), n in sorted(bands.items(), key=lambda x: repr(x[0]))]
        sides.append(dict(side_index=side, team_native_id=fixture['home_team' if side == 0 else 'away_team']['native_id'],
                          state='available' if available else 'unavailable_cross_counter_reconciliation',
                          all_player_counters_match=available, captured_player_counter_checks=len(own),
                          zero_counter_players_checked=sum(c['official_attempted'] == c['official_completed'] == 0 for c in checks),
                          unresolved_actor_slots=missing, player_checks=checks, source_category_counts=dict(categories),
                          attempt_count=len(side_rows) if available else None,
                          completed_count=sum(r['completed'] for r in side_rows) if available else None,
                          not_completed_count=sum(not r['completed'] for r in side_rows) if available else None,
                          event_position_counts=position_counts if available else None,
                          event_position_counts_scope='whole selected side before pagination; null bands preserve missing geometry or outside-pitch points'))
        output += side_rows
    output.sort(key=lambda r: r['record_index'])
    return dict(state='available' if all(s['state'] == 'available' for s in sides) else 'available_partial',
                sides=sides, cross_events=output, native_event_count=len(records),
                event_policy='Native engine kind3 maps uniquely to CBE categories12..17; category12 is its outcome0. Every player crossing attempt/completion counter, including zeros, must close before publishing a side.',
                location_policy='Raw CBE event point and optional analytical equal pitch thirds/central width third, using the shared event attacked-goal flag; not a proved cross release or destination, official cross map or tracking occupancy.',
                unknown_fields=['cross recipient', 'specific failure reason', 'open-play/set-piece event split', 'shot/goal provider link', 'ball release/destination', 'physical units', 'human left/right', 'displayed minute', 'box occupation'])


def verify_native(read, base):
    for rva, size, expected in NATIVE_SPANS:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != expected:
            raise ValueError('Native crossing event binding changed')
    for rva, expected in DEPENDENCY_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError('Native crossing event binding changed')
    _whole_function_hashes(read, base)


def _not_checked_on_this_build(reasons):
    return None


@address_book.optional_section('whole_function_hashes', _not_checked_on_this_build, check=True)
def _whole_function_hashes(read, base):
    """The pinned build's hashes of the whole CBE builder and match-engine regions. A patch that
    rewrites either function changes them; on such a build DEPENDENCY_SPANS carry the check."""
    for rva, size, expected in WHOLE_FUNCTION_SPANS:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != expected:
            raise ValueError('Native crossing event binding changed')


def get_retained_cross_events(bridge, session_id, fixture_ref, *, team_native_id=None, person_native_id=None,
                              offset=0, limit=100, expected_source_id=None, coach_index=None):
    from . import players
    from .match_data_query import capture_epoch, capture_live
    from .live_match_players import project_frame
    from .live_retained_shots import capture_source, _validate_team_oracle, _validated_actors
    if not isinstance(fixture_ref, str) or not fixture_ref:
        raise ValueError('Select one retained fixture reference')
    for value in (team_native_id, person_native_id):
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError('Invalid crossing actor or team selector')
    if person_native_id is not None and team_native_id is None:
        raise ValueError('A crossing player requires its team')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('Invalid crossing page')
    if expected_source_id is not None and (not isinstance(expected_source_id, str) or len(expected_source_id) != 64 or any(c not in '0123456789abcdef' for c in expected_source_id)):
        raise ValueError('Invalid crossing source pin')
    if offset and expected_source_id is None:
        raise ValueError('Crossing continuation requires the first source_id')
    if coach_index is not None and (type(coach_index) is not int or not 0 <= coach_index < 64):
        raise ValueError('Invalid crossing coach selector')
    epoch = capture_epoch(bridge, session_id)
    first = bridge.get_save(session_id)['save']
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        read, _, _ = bridge._world_state(process, tables)
        verify_native(read, tables[0] - players.RVA[0])
        read.verify()
        bridge._current(session_id)
    packet = capture_live(bridge, session_id, [fixture_ref], include_players=True)
    item, = packet['capture']['fixtures']
    fixture, key = item['fixture'], item['native_match_key']
    if fixture['fixture_ref'] != fixture_ref or packet.get('_live_capture_epoch') != epoch:
        raise ValueError('Crossing capture fixture or epoch differs')
    selected_sides = [s for s, k in enumerate(('home_team', 'away_team')) if team_native_id is None or fixture[k]['native_id'] == team_native_id]
    if not selected_sides:
        raise ValueError('Crossing team is not in selected fixture')
    base = dict(fixture=fixture, native_match_key=key, source_kind='active_human_retained_cbe_cross_events',
                saved_file_fallback=False, atomic=False, observed_save_first=first, source_id=None,
                cross_events=[], sides=[], offset=offset, limit=limit, total_count=None, available_row_count=None, next_offset=None)
    totals = [t for t in packet['team_totals']['records'] if key is not None and t['result_key'] == key]
    if len(totals) != 1:
        return dict(base, state='unavailable_team_oracle')
    _validate_team_oracle(fixture, totals[0]['teams'])
    roster = [p for p in packet['retained_players'] if p.get('fixture_key', p.get('native_match_key')) == key]
    frame, = packet['raw_frames']
    if frame['key'] != key or frame['fixture_ref'] != fixture_ref:
        raise ValueError('Crossing raw frame fixture differs')
    wire = project_frame(frame['raw'], key)
    identity = lambda r: (r['side_index'], r['stored_player_slot'], r['person_index_word'], r['row_sha256'])
    if not wire['coverage']['complete_side_sections'] or sorted(map(identity, roster)) != sorted(map(identity, wire['rows'])):
        raise ValueError('Crossing full native roster differs')
    if not roster or len(_validated_actors(roster, totals[0]['teams'])) != len(roster):
        return dict(base, state='unavailable_actor_identity')
    source = capture_source(bridge, session_id, fixture_ref, key, fixture, coach_index)
    if source['state'] != 'available':
        return dict(base, state=source['state'])
    decoded = decode_cross_events(source['events'], roster, fixture, key, source.get('pitch_geometry'))
    last = bridge.get_save(session_id)['save']
    if capture_epoch(bridge, session_id) != epoch or last != first:
        raise ValueError('Crossing career or save changed during capture')
    digest = hashlib.sha256(repr(epoch).encode() + source['events'] + json.dumps(dict(fixture=fixture, players=roster, geometry=source.get('pitch_geometry'), team=team_native_id, person=person_native_id), sort_keys=True).encode()).hexdigest()
    if expected_source_id is not None and expected_source_id != digest:
        raise ValueError('Crossing source or selectors changed; restart pagination')
    sides = [s for s in decoded['sides'] if s['side_index'] in selected_sides]
    known = person_native_id is None or any(c['person_native_id'] == person_native_id for s in sides for c in s['player_checks'])
    available = known and all(s['state'] == 'available' for s in sides)
    rows = [r for r in decoded['cross_events'] if r['side_index'] in selected_sides and (person_native_id is None or r['person_native_id'] == person_native_id)]
    end = min(len(rows), offset + limit)
    return dict(base, **{k: v for k, v in decoded.items() if k not in ('sides', 'cross_events', 'state')},
                state='available' if available else 'unavailable_selected_cross_actor' if not known else 'available_partial',
                sides=sides, cross_events=rows[offset:end], source_id=digest,
                pitch_geometry=source.get('pitch_geometry'), total_count=len(rows) if available else None,
                available_row_count=len(rows), next_offset=end if end < len(rows) else None,
                team_native_id=team_native_id, person_native_id=person_native_id,
                observed_save_last=last, observed_at=datetime.now(timezone.utc).isoformat())


# sha256 guards: the event converter 0x48930AC (kind, outcome) -> CBE category and its byte switch
# tables, the engine's event-kind switch table, and the two player-statistics sites.
NATIVE_SPANS = ((76099756, 380, 'f3da4c4acba32aae51f4288224897adb60ca0fb4bf2385254578bb6d5858dac5'), (88089540, 47, 'b5d5adb7792039d7b8daac2eb4f6e02701eef18b3d0a3bcf5f2ee9bb5fe8f253'), (88101612, 60, '2003d9293cc39c867c6e34b3fa9b39e08fcd7f306980a58c97a82abdd095d55d'), (2117400, 208, 'd7f3c80c4e6148a9b25e3a4234422077430ad6aa6a61c0e301d8140e4fa4c06c'), (76110420, 12, '303a920fce0b3178b6310c5ac2e32368a96355027ac245e87dca6dd3a37c1565'))
# The pinned build's whole-region hashes of the CBE builder (0x488A72C, 2,464 bytes) and the match
# engine (0x493C244, 13,116 bytes): checked only where their code is unchanged (`_whole_function_hashes`).
WHOLE_FUNCTION_SPANS = ((76064556, 2464, '5fe0b06562933e267a31cac70d889166f2ddb540839fac7c0458295f97a4ed44'), (76792388, 13116, 'af8523f1a44e8f040c01cf2d45f9c23b552e3b699b4e9f99eeda326dea0c8ea7'))
# What the decoder depends on in those two functions, checked on every build:
# CBE builder: the record offsets it reads (+0x18 xy, +0x22 clock start, +0x27 slot, +0x28 side,
# +0x2A category from the converter, +0x2C event id, +0x30 flags with 0x100 = attacked goal from
# event flag bit 7, +0x32 clock end) and the outcome it passes the converter for a linked event.
# Match engine, event-kind case 3: CrossAttempts (stats +0xB5) on every kind-3 event, the
# set-piece split, and CrossesCompleted (+0xB6) for an unlinked outcome 0 or the linked kinds that
# count, which is what makes category 12 the completed crosses the player counters close against.
DEPENDENCY_SPANS = (
    (0x488a5f0, bytes.fromhex('7f0e00f97f420079884640b9684600798a1a40f9')),
    (0x488a6dc, bytes.fromhex('49a14139291d00123f75007108fdff54080080523f510071e80100542a0080524a21c91a5f090e72014200545f051f72414b00542a0080524921c91a0a4088523f010a6a80000054080180520802001448a5413989a241393f5500710009407ae0500054201d0013011d00135922009460aa0039772e00b97f62007976660079ea0314aa891240f9693f00b5400140fd600e00fd')),
    (0x488a724, bytes.fromhex('0801805208020014')),
    (0x488af44, bytes.fromhex('a800805289a24139fdfdff17')),
    (0x488b074, bytes.fromhex('c8008052b4ffff17')),
    (0x488ab3c, bytes.fromhex('88da40796852027888ae4139689e0039')),
    (0x488ab74, bytes.fromhex('88aa413968a20039')),
    (0x488abc4, bytes.fromhex('88003836696240792901183269620079')),
    (0x493c4d8, bytes.fromhex('3f750071481e01544b5600b06bb10b918c0000106d7969788c090d8b80011fd6')),
    (0x493c7cc, bytes.fromhex('c9aa417929050011c9aa0179974b00b4e9d6423929050011e9d60239')),
    (0x493c7e8, bytes.fromhex('094380521f01096aed1b40f9404d0054')),
    (0x493e6e0, bytes.fromhex('8c0540f98ba141396b1d00127f750071')),
    (0x493e7bc, bytes.fromhex('7f51007188faff542a0080524a21cb1a0b4088528b03a0725f010b6a610600545f051f7280f9ff54')),
    (0x493e700, bytes.fromhex('8aa541395f190071e0060054ca0c0035')),
    (0x493e710, bytes.fromhex('caae41794a050011caae0179970000b4eada42394a050011eada0239')),
)
