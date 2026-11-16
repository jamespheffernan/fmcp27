"""Every pass, cross and shot of a retained match, read from a saved career with the game closed.

The game writes its retained full-detail match records into the save: the human manager's
lists (own team, opponents, other) are serialized in `game_db.dat`, each entry holding the same
event records the live readers take from memory (fmdb/match_pass_decode.py). Layout, measured by
lining up 11 in-memory event vectors captured on 13 Dec 2030 with a save written the next day
(every field of every compared record equal) and by walking all 32 entries of that save and all
36 of a later one from the first byte to the last with nothing left over:

  list    u16 entry count, entries
  entry   u8 record present (1), u32 version (0x12), u32 event count, events,
          u32 shot count + 25-byte shots (home), the same (away), f32 half width, f32 half length,
          u32 clock, u32 clock, i32 clock (-1 without extra time),
          per side: u32 n + n * 4 pass-pair counts, u32 n + n * 11 position sums, u32 n + n * 4 top pairs,
          u8, u32 n + n * (u8 id, u32 first clock, u32 samples, samples * (i16, i16)) tracking paths,
          u32 n + n bytes, u16,
          u16 day word (low 9 bits: day of the year, from 1), u16 year, i32 owner team native id,
          u8 owner side (0 home, 1 away)
  event   f32 x, f32 y, u16 0, u32 n, n * (f32 x, f32 y) path samples, u8 category, u8 actor slot,
          u8 side, u16 clock, u8 time to the linked event, u8 elapsed minute, u8 second,
          u16 flags, u8 linked actor slot (0xFF none), u32 event id, u16 end clock

The date, owner team and owner side follow the record they belong to. The owner side is home for
0 and away for 1 on the five own-team entries of the measured save (Sheffield United at home,
Villarreal, West Ham and Bournemouth away, Crystal Palace at home).

The save names no player in these records: an event holds a side and a slot. The slots are
bound through the match's stored statistics frame (`match_stats_cfg.dat`, read by
saved_match_statistics): a stream is accepted for a fixture key only when its owner team is the
frame's team on the owner side and every stored player's passes attempted and completed equal
the stream's counts for that side and slot. Rows are published only after that closes.

Crosses (categories 12 to 17) and shots (shot-end categories 1 to 5 with the 25-byte shot records)
come from the same entry and are closed on their own stored counters as well: see decode_crosses
and decode_shots.
"""
from __future__ import annotations

import math
import struct
from collections import Counter, defaultdict
from datetime import date, timedelta

from . import saved_component_stream, saved_match_player_actions, snapshot_catalog
from . import saved_match_statistics as stored
from . import saved_match_statistics_wire as wire
from .fmdb import match_pass_decode as mpd
from .live_retained_shots import FEET_SHOT_TYPES, HEADER_SHOT_TYPES, OWN_GOAL
from .retained_cross_events import CROSS_CATEGORIES
from .retained_shot_location import classify_location
from .retained_shot_outcomes import OUTCOMES as SHOT_OUTCOMES
from .saved_fixture_archive_zstd import expand_frame
from .saved_match_player_crosses import decode_player_crosses

ENTRY_VERSION = 0x12
ENTRY_MARK = b'\x01' + struct.pack('<I', ENTRY_VERSION)   # record-present byte, then the version
MAX_EVENTS = 8192
MAX_PATH_POINTS = 512
MAX_SHOTS = 256
MAX_TABLE = 4096
MAX_TRACKED = 128
MAX_SAMPLES = 60000
SHOT_BYTES = 25
MAX_ENTRIES = 512
MAX_PAGE = 500
_CACHE: dict = {}       # snapshot id -> [entry]; two saves at most


def parse_event(buf, at):
    """(fields, end offset) of the serialized event at `at`, or None when the bytes are not one."""
    if at + 31 > len(buf):
        return None
    x, y, pad, n = struct.unpack_from('<ffHI', buf, at)
    if pad or n > MAX_PATH_POINTS or not (abs(x) < 1000 and abs(y) < 1000):     # NaN fails both
        return None
    tail = at + 14 + 8 * n
    if tail + 17 > len(buf):
        return None
    category, slot, side, clock, linked, minute, second, flags, second_slot, event_id, end_clock = (
        struct.unpack_from('<BBBHBBBHBIH', buf, tail))
    if side > 1:
        return None
    return ({'x': x, 'y': y, 'path': bytes(buf[at + 14:tail]), 'category': category, 'slot': slot,
             'side': side, 'clock': clock, 'linked_offset': linked, 'minute': minute, 'second': second,
             'flags': flags, 'second_slot': second_slot, 'event_id': event_id, 'end_clock': end_clock},
            tail + 17)


def _shots(buf, at):
    if at + 4 > len(buf):
        return None
    count = struct.unpack_from('<I', buf, at)[0]
    end = at + 4 + SHOT_BYTES * count
    return (count, end) if count <= MAX_SHOTS and end <= len(buf) else None


def _counted(buf, at, width, maximum):
    """End of a u32 count followed by count * width bytes, or None."""
    if at is None or at + 4 > len(buf):
        return None
    count = struct.unpack_from('<I', buf, at)[0]
    end = at + 4 + width * count
    return end if count <= maximum and end <= len(buf) else None


def _tail(buf, at):
    """Offset of the date word that closes the entry whose pitch geometry ends at `at`, or None.

    Walks the pass-map tables, the tracking paths and the per-sample bytes; none is read here."""
    at += 12                                            # three clocks
    for _ in range(2):
        at = _counted(buf, at, 4, MAX_TABLE)            # pass-pair counts
        at = _counted(buf, at, 11, MAX_TABLE)           # position sums
        at = _counted(buf, at, 4, MAX_TABLE)            # top pairs
        if at is None:
            return None
    if at + 5 > len(buf):
        return None
    paths = struct.unpack_from('<I', buf, at + 1)[0]
    at += 5
    if paths > MAX_TRACKED:
        return None
    for _ in range(paths):
        at = _counted(buf, at + 5, 4, MAX_SAMPLES)      # u8 id, u32 first clock, then the samples
        if at is None:
            return None
    at = _counted(buf, at, 1, MAX_SAMPLES)
    return None if at is None else at + 2


def parse_entry(buf, start):
    """The retained entry whose record-present byte is at `start`, or None. Nothing is guessed:
    every event, both shot vectors, the pitch geometry, every table after them and the closing
    date, owner team and owner side must parse."""
    if start < 0 or start + 9 > len(buf):
        return None
    present, version, count = struct.unpack_from('<BII', buf, start)
    if present != 1 or version != ENTRY_VERSION or not 1 <= count <= MAX_EVENTS:
        return None
    events, at = [], start + 9
    for _ in range(count):
        got = parse_event(buf, at)
        if got is None:
            return None
        events.append(got[0])
        at = got[1]
    counts, shot_records = [], []
    for _ in range(2):
        got = _shots(buf, at)
        if got is None:
            return None
        counts.append(got[0])
        shot_records.append(bytes(buf[at + 4:got[1]]))
        at = got[1]
    if at + 20 > len(buf):
        return None
    half_width, half_length = struct.unpack_from('<ff', buf, at)
    if not (10 < half_width < 80 and 20 < half_length < 100):
        return None
    at = _tail(buf, at + 8)
    if at is None or at + 9 > len(buf):
        return None
    day_word, year, owner, owner_side = struct.unpack_from('<HHiB', buf, at)
    day = day_word & 511
    if owner_side > 1 or not 1900 <= year <= 2200 or not 1 <= day <= 366:
        return None
    return {'offset': start, 'end': at + 9, 'date': (date(year, 1, 1) + timedelta(days=day - 1)).isoformat(),
            'day_word': day_word, 'owner_team_native_id': owner, 'owner_side_index': owner_side,
            'events': events, 'shot_counts': counts, 'shot_records': shot_records,
            'pitch_geometry': {'half_width_native': half_width, 'half_length_native': half_length}}


def find_entries(buf):
    """Every retained entry in a decompressed game_db.dat, in file order."""
    out, at = [], 0
    while len(out) < MAX_ENTRIES:
        hit = buf.find(ENTRY_MARK, at)
        if hit < 0:
            break
        entry = parse_entry(buf, hit)
        if entry is None:
            at = hit + 1
            continue
        out.append(entry)
        at = entry['end']
    return out


def memory_records(events):
    """The events as the 56-byte records the live readers decode, with their path samples apart.

    The vector header (+0x00..+0x17) is zero: the samples come back as {record index: [(x, y)]}."""
    raw, paths = bytearray(56 * len(events)), {}
    for n, e in enumerate(events):
        base = 56 * n
        struct.pack_into('<ff', raw, base + 0x18, e['x'], e['y'])
        struct.pack_into('<HBBBBBBB', raw, base + 0x22, e['clock'], e['linked_offset'], e['minute'], e['second'],
                         e['slot'], e['side'], e['second_slot'], e['category'])
        struct.pack_into('<IHH', raw, base + 0x2C, e['event_id'], e['flags'], e['end_clock'])
        if e['path']:
            paths[n] = list(struct.iter_unpack('<ff', e['path']))
    return bytes(raw), paths


def frame_players(raw):
    """(teams, players) of one stored statistics frame: the roster and the game's pass counters."""
    prefix = wire.fixture_prefix(raw)
    fixture = wire.continue_fixture(raw, prefix['end'], wire.parse_person, wire.fixture_extra)
    at = wire.stats_prefix(raw, fixture['end'])['end']
    teams = [{'team_index': t['index_word'], 'team_native_id': t['identity_word']}
             for t in prefix['fixture_fields8_10_team_references']]
    players, totals = [], []
    for side_index in range(2):
        side = wire.side(raw, at, version=60, parse_child=wire.player, parse_collection=wire.collection)
        fields = side['fields']
        if fields['0x5c_raw_reference'] != teams[side_index]['team_index']:
            raise ValueError('Stored match side differs from its fixture TEAM reference')
        totals.append({'shots': fields['0x16f'], 'shots_on_target': fields['0x170'],
                       'expected_goals': struct.unpack('<f', bytes.fromhex(fields['0x60_float_raw']))[0]})
        at = side['end']
        for slot, child in enumerate(side['children']):
            stored_child = bytes(raw[child['start']:child['end']])
            counters = saved_match_player_actions.decode_player_actions(stored_child)
            crosses = decode_player_crosses(stored_child)
            players.append({'side_index': side_index, 'stored_player_slot': slot,
                            'person_index_word': int.from_bytes(bytes.fromhex(child['reference']['raw']), 'little'),
                            'passes_attempted': counters['passes_attempted'],
                            'passes_completed': counters['passes_completed'],
                            'key_passes': counters['key_passes'], 'chances_created': counters['chances_created'],
                            'crosses_attempted': crosses['crosses_attempted'],
                            'crosses_completed': crosses['crosses_completed'],
                            'shots': counters['shots'], 'shots_on_target': counters['shots_on_target'],
                            'expected_goals': counters['expected_goals']})
    return {'fixture_key': fixture['fields']['scalar_u32'][0], 'teams': teams, 'players': players,
            'team_totals': totals}


def _markers(entry, pass_rows, side_index):
    """Key-pass and chance-created markers of one side: on its pass rows, and on all its events
    (the game also marks crosses and other events, which are not pass rows)."""
    events = [e for e in entry['events'] if e['side'] == side_index]
    return {'key_pass_markers_on_pass_rows': sum(r['key_pass'] for r in pass_rows),
            'key_pass_markers_on_all_events': sum(bool(e['flags'] & mpd.FLAG_KEY_PASS) for e in events),
            'chance_created_markers_on_pass_rows': sum(r['chance_created'] for r in pass_rows),
            'chance_created_markers_on_all_events': sum(bool(e['flags'] & mpd.FLAG_CHANCE_CREATED) for e in events)}


def decode_passes(entry, frame):
    """Pass rows of one entry bound to one frame, or the reason the two do not belong together."""
    if frame['teams'][entry['owner_side_index']]['team_native_id'] != entry['owner_team_native_id']:
        return {'state': 'unavailable_owner_team_not_in_fixture', 'rows': []}
    raw, paths = memory_records(entry['events'])
    players = frame['players']
    roster = {(p['side_index'], p['stored_player_slot']): p['person_index_word'] for p in players}
    rows = mpd.decode(raw, paths, roster, include_uncounted=True)
    checks = mpd.reconcile(rows, players)
    unknown = sorted({(r['side'], r['slot']) for r in rows if (r['side'], r['slot']) not in roster})
    if unknown or not all(c['ok'] for c in checks):
        return {'state': 'unavailable_player_counter_reconciliation', 'rows': [],
                'players_checked': len(checks), 'players_equal': sum(c['ok'] for c in checks),
                'actor_slots_without_a_stored_player': unknown}
    sides = []
    for side_index in (0, 1):
        own = [r for r in rows if r['side'] == side_index]
        counted = [r for r in own if r['counted']]
        mine = [p for p in players if p['side_index'] == side_index]
        sides.append({'side_index': side_index, **frame['teams'][side_index],
                      'pass_attempts': len(counted), 'passes_completed': sum(r['completed'] for r in counted),
                      'stored_pass_attempts': sum(p['passes_attempted'] for p in mine),
                      'stored_passes_completed': sum(p['passes_completed'] for p in mine),
                      'players_checked': len(mine), 'all_player_counters_equal': True,
                      'throw_ins': len(own) - len(counted), **_markers(entry, own, side_index),
                      'stored_key_passes': sum(p['key_passes'] for p in mine),
                      'stored_chances_created': sum(p['chances_created'] for p in mine)})
    return {'state': 'available', 'rows': rows, 'side_coverage': sides}


def decode_unbound(entry):
    """Pass rows of an entry whose match has no stored statistics frame in the save: players are
    a side and a slot, and nothing is checked against the game's counters (there are none)."""
    raw, paths = memory_records(entry['events'])
    rows = mpd.decode(raw, paths, {}, include_uncounted=True)
    sides = []
    for side_index in (0, 1):
        own = [r for r in rows if r['side'] == side_index]
        counted = [r for r in own if r['counted']]
        sides.append({'side_index': side_index, 'team_index': None, 'team_native_id': None,
                      'pass_attempts': len(counted), 'passes_completed': sum(r['completed'] for r in counted),
                      'stored_pass_attempts': None, 'stored_passes_completed': None,
                      'players_checked': 0, 'all_player_counters_equal': None,
                      'throw_ins': len(own) - len(counted), **_markers(entry, own, side_index),
                      'stored_key_passes': None, 'stored_chances_created': None})
    return {'state': 'available_without_stored_player_counters', 'rows': rows, 'side_coverage': sides}


def _point(value):
    return None if value is None else round(value, 3)


def _roster(frame):
    return {} if frame is None else {(p['side_index'], p['stored_player_slot']): p['person_index_word']
                                     for p in frame['players']}


def _owner_in_fixture(entry, frame):
    return frame['teams'][entry['owner_side_index']]['team_native_id'] == entry['owner_team_native_id']


def _when(e):
    return {'displayed_minute': e['minute'] + 1, 'second': e['second'], 'clock_raw': e['clock']}


def _team(frame, side_index):
    return {'team_index': None, 'team_native_id': None} if frame is None else frame['teams'][side_index]


# Crosses. Category 12 is the completed cross: it is the one the game counts in CrossesCompleted and
# the one whose record holds the receiver's slot (match_pass_decode docstring, +0x29). The other
# categories are named here from where the stored ball path ends, measured on the 36 entries of
# the 14 Nov 2026 save (2,159 crosses): 13 ends at an opposing
# player's event on 162 of 162, 14 at an opposing category-54 event on 103 of 104, 16 outside the
# pitch on 48 of 48, 15 at no stored event on 1,463 of 1,463. These are the signs of the pass
# categories 8, 9, 11 and 10. Category 17 was not seen.
CROSS_COMPLETED = 12
CROSS_FAILURE = {13: 'intercepted', 14: 'blocked', 15: 'not_completed_other', 16: 'out_of_play',
                 17: 'not_completed_unnamed'}


def decode_crosses(entry, frame=None):
    """Cross rows of one entry. With a frame, rows are bound to its players and returned only when
    every stored player's crosses attempted and completed equal the record's counts for that side
    and slot; without one, rows carry a side and a slot and nothing is checked."""
    if frame is not None and not _owner_in_fixture(entry, frame):
        return {'state': 'unavailable_owner_team_not_in_fixture', 'rows': []}
    roster = _roster(frame)
    by_clock = defaultdict(list)
    for e in entry['events']:
        by_clock[e['clock']].append(e)
    half_width, half_length = (entry['pitch_geometry'][k] for k in ('half_width_native', 'half_length_native'))
    rows = []
    for e in entry['events']:
        if e['category'] not in CROSS_CATEGORIES:
            continue
        side, completed = e['side'], e['category'] == CROSS_COMPLETED
        points = list(struct.iter_unpack('<ff', e['path']))
        end = points[-1] if points else None
        there = [o for o in by_clock[e['clock'] + e['linked_offset']]
                 if o is not e and (o['x'], o['y']) == end]
        opponents = {o['slot'] for o in there if o['side'] != side}
        won = opponents.pop() if not completed and len(opponents) == 1 else None
        recipient = e['second_slot'] if completed and e['second_slot'] != mpd.NO_SLOT else None
        marks = mpd.pass_type(e['flags'])
        rows.append({
            'event_id': e['event_id'], 'side_index': side, 'stored_player_slot': e['slot'],
            'person_index': roster.get((side, e['slot'])), 'completed': completed,
            'outcome': 'completed' if completed else CROSS_FAILURE[e['category']],
            'restart': marks['restart'], 'key_pass': marks['key_pass'],
            'chance_created': marks['chance_created'], 'assist_marked': marks['assist_marked'],
            'recipient_stored_player_slot': recipient,
            'recipient_person_index': None if recipient is None else roster.get((side, recipient)),
            'won_by_stored_player_slot': won,
            'won_by_person_index': None if won is None else roster.get((1 - side, won)),
            **_when(e), 'origin_x': _point(e['x']), 'origin_y': _point(e['y']),
            'end_x': _point(end[0]) if end else None, 'end_y': _point(end[1]) if end else None,
            'end_state': (None if end is None else 'linked_event_location' if there else
                          'outside_pitch_sample' if abs(end[0]) > half_width or abs(end[1]) > half_length
                          else 'unlinked_end_sample'),
            'attacks_positive_y': bool(e['flags'] & 0x100),
            'native_category_code': e['category'], 'native_flags_word': e['flags']})
    attempts = Counter((r['side_index'], r['stored_player_slot']) for r in rows)
    done = Counter((r['side_index'], r['stored_player_slot']) for r in rows if r['completed'])
    players = [] if frame is None else frame['players']
    if frame is not None:
        equal = [attempts[k] == p['crosses_attempted'] and done[k] == p['crosses_completed']
                 for p in players for k in [(p['side_index'], p['stored_player_slot'])]]
        unknown = sorted(set(attempts) - set(roster))
        if unknown or not all(equal):
            return {'state': 'unavailable_cross_counter_reconciliation', 'rows': [],
                    'players_checked': len(equal), 'players_equal': sum(equal),
                    'actor_slots_without_a_stored_player': unknown}
    sides = []
    for side_index in (0, 1):
        own = [r for r in rows if r['side_index'] == side_index]
        mine = [p for p in players if p['side_index'] == side_index]
        outcomes = Counter(r['outcome'] for r in own)
        sides.append({'side_index': side_index, **_team(frame, side_index),
                      'cross_attempts': len(own), 'crosses_completed': outcomes['completed'],
                      'stored_cross_attempts': sum(p['crosses_attempted'] for p in mine) if frame else None,
                      'stored_crosses_completed': sum(p['crosses_completed'] for p in mine) if frame else None,
                      'players_checked': len(mine), 'all_player_counters_equal': True if frame else None,
                      'outcome_counts': {name: outcomes[name] for name in ('completed', *CROSS_FAILURE.values())},
                      'from_corners': sum(r['restart'] == 'corner' for r in own),
                      'from_free_kicks': sum(r['restart'] == 'free_kick' for r in own)})
    return {'state': 'available' if frame else 'available_without_stored_player_counters',
            'rows': rows, 'side_coverage': sides}


# Shots. A 25-byte shot record is the stored form of the 48-byte record live_retained_shots reads
# (+32 expected goals, +36 event id, +44 shot type):
#   u32 event id, 8 zero bytes, f32 expected goals, u32 event id again, u32 clock of the event,
#   u8 shot type
# Measured on the 972 records of the 36 entries of the 14 Nov 2026 save: the two ids are equal and
# the clock is the linked event's on all 972; the linked event is a shot-end event (categories 1 to
# 5) of the vector's side, or the other side's own goal (49, twice); type 4 is on five shots, all
# taken from the penalty spot; type 3 is on the 12 shots whose event carries a free-kick flag and
# on no other.
# The stored counters add each shot's value rounded to 1/2**24, in float32, in event-id order: on the
# 25 entries that have a statistics frame that sum equals the stored value on 898 of 899 players and
# 49 of 50 sides. The exception is a shot with no shot record (the last event of a match that went
# to extra time, minute 122). Why the record holds more digits than the counters add is not known.
XG_STEPS = 2 ** 24
SHOT_RECORD = struct.Struct('<I8sfIIB')
SHOTS_ON_TARGET = (1, 4)        # goal, saved


def _f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def stored_expected_goals_sum(values):
    """The sum as the game's counters hold it: each value rounded to 1/2**24, added in float32."""
    total = 0.0
    for value in values:
        total = _f32(total + round(value * XG_STEPS) / XG_STEPS)
    return total


def shot_records(entry):
    """({event id: (expected goals, shot type)}, [problem]) from the two shot vectors of an entry."""
    by_id = defaultdict(list)
    for e in entry['events']:
        by_id[e['event_id']].append(e)
    found, problems = {}, []
    for side, raw in enumerate(entry['shot_records']):
        for at in range(0, len(raw), SHOT_BYTES):
            event_id, zero, xg, again, clock, shot_type = SHOT_RECORD.unpack_from(raw, at)
            linked = by_id.get(event_id, [])
            reason = None
            if zero != bytes(8) or again != event_id:
                reason = 'record_layout_differs'
            elif not (math.isfinite(xg) and 0 <= xg <= 1):
                reason = 'invalid_expected_goals'
            elif len(linked) != 1 or event_id in found:
                reason = 'missing_or_ambiguous_linked_event'
            elif linked[0]['clock'] != clock:
                reason = 'clock_differs_from_linked_event'
            elif linked[0]['side'] != (1 - side if linked[0]['category'] == OWN_GOAL else side) or (
                    linked[0]['category'] != OWN_GOAL and linked[0]['category'] not in SHOT_OUTCOMES):
                reason = 'side_or_category_differs'
            if reason:
                problems.append({'side_index': side, 'event_id': event_id, 'reason': reason})
            else:
                found[event_id] = (xg, shot_type)
    return found, problems


def decode_shots(entry, frame=None):
    """Shot rows of one entry: the shot-end events, each with its shot record when one is stored.

    With a frame, rows are bound to its players and returned only when every stored player's shots
    and shots on target, and both stored team totals, equal the record's counts. Expected goals are
    compared with the stored values and reported per side; a shot without a record has none."""
    if frame is not None and not _owner_in_fixture(entry, frame):
        return {'state': 'unavailable_owner_team_not_in_fixture', 'rows': []}
    records, problems = shot_records(entry)
    if problems:
        return {'state': 'unavailable_shot_record_link', 'rows': [], 'shot_record_problems': problems[:20]}
    roster = _roster(frame)
    half_length = entry['pitch_geometry']['half_length_native']
    rows, own_goals = [], []
    for e in entry['events']:
        side, slot = e['side'], e['slot']
        if e['category'] == OWN_GOAL:
            own_goals.append({'event_id': e['event_id'], 'side_index': side, 'stored_player_slot': slot,
                              'person_index': roster.get((side, slot)), 'beneficiary_side_index': 1 - side,
                              **_when(e)})
        if e['category'] not in SHOT_OUTCOMES:
            continue
        xg, shot_type = records.get(e['event_id'], (None, None))
        points = list(struct.iter_unpack('<ff', e['path']))
        towards_positive_y = bool(e['flags'] & 0x100)
        place = classify_location(e['x'], e['y'], towards_positive_y, half_length)
        rows.append({
            'event_id': e['event_id'], 'side_index': side, 'stored_player_slot': slot,
            'person_index': roster.get((side, slot)), 'outcome': SHOT_OUTCOMES[e['category']][0],
            'on_target': e['category'] in SHOTS_ON_TARGET,
            'expected_goals': None if xg is None else round(xg, 6),
            'expected_goals_state': 'no_stored_shot_record' if xg is None else 'stored_shot_record',
            'native_shot_type': shot_type,
            'body_part': ('head' if shot_type in HEADER_SHOT_TYPES else
                          'feet' if shot_type in FEET_SHOT_TYPES else None),
            'is_penalty': None if shot_type is None else shot_type == 4,
            'restart': mpd.pass_type(e['flags'])['restart'], **_when(e),
            'x': _point(e['x']), 'y': _point(e['y']),
            'end_x': _point(points[-1][0]) if points else None,
            'end_y': _point(points[-1][1]) if points else None,
            'attacks_positive_y': towards_positive_y, 'location': place['official_location'],
            'location_group': place['location_group'],
            'native_category_code': e['category'], 'native_flags_word': e['flags']})
    count = Counter((r['side_index'], r['stored_player_slot']) for r in rows)
    target = Counter((r['side_index'], r['stored_player_slot']) for r in rows if r['on_target'])
    players = [] if frame is None else frame['players']
    if frame is not None:
        equal = [count[k] == p['shots'] and target[k] == p['shots_on_target']
                 for p in players for k in [(p['side_index'], p['stored_player_slot'])]]
        unknown = sorted(set(count) - set(roster))
        teams_equal = all(sum(n for k, n in found.items() if k[0] == side) == frame['team_totals'][side][name]
                          for side in (0, 1) for found, name in ((count, 'shots'), (target, 'shots_on_target')))
        if unknown or not all(equal) or not teams_equal:
            return {'state': 'unavailable_shot_counter_reconciliation', 'rows': [],
                    'players_checked': len(equal), 'players_equal': sum(equal), 'team_totals_equal': teams_equal,
                    'actor_slots_without_a_stored_player': unknown}
    values = defaultdict(list)          # the counters were added to in event-id order, not list order
    for r in sorted(rows, key=lambda r: r['event_id']):
        if r['event_id'] in records:
            values[r['side_index'], r['stored_player_slot']].append(records[r['event_id']][0])
            values[r['side_index']].append(records[r['event_id']][0])
    sides = []
    for side_index in (0, 1):
        own = [r for r in rows if r['side_index'] == side_index]
        mine = [p for p in players if p['side_index'] == side_index]
        outcomes = Counter(r['outcome'] for r in own)
        total = stored_expected_goals_sum(values[side_index])
        stored_total = frame['team_totals'][side_index] if frame else None
        sides.append({
            'side_index': side_index, **_team(frame, side_index),
            'shots': len(own), 'shots_on_target': sum(r['on_target'] for r in own),
            'stored_shots': stored_total['shots'] if frame else None,
            'stored_shots_on_target': stored_total['shots_on_target'] if frame else None,
            'players_checked': len(mine), 'all_player_counters_equal': True if frame else None,
            'outcome_counts': {name: outcomes[name] for name, _ in SHOT_OUTCOMES.values()},
            'shots_without_a_shot_record': sum(r['expected_goals'] is None for r in own),
            'own_goals_conceded': sum(o['side_index'] == side_index for o in own_goals),
            'expected_goals': total,
            'stored_expected_goals': stored_total['expected_goals'] if frame else None,
            'expected_goals_equal_to_stored': total == stored_total['expected_goals'] if frame else None,
            'players_expected_goals_equal': sum(
                stored_expected_goals_sum(values[side_index, p['stored_player_slot']]) == p['expected_goals']
                for p in mine) if frame else None})
    return {'state': 'available' if frame else 'available_without_stored_player_counters',
            'rows': rows, 'own_goals': own_goals, 'side_coverage': sides}


def _row(r):
    return {'event_id': r['event_id'], 'side_index': r['side'], 'stored_player_slot': r['slot'],
            'person_index': r['person_idx'], 'counted': r['counted'], 'completed': r['completed'],
            'outcome': r['outcome'], 'restart': r['restart'], 'key_pass': r['key_pass'],
            'chance_created': r['chance_created'], 'assist_marked': r['assist_marked'],
            'recipient_person_index': r['recipient_person_idx'], 'recipient_state': r['recipient_state'],
            'won_by_person_index': r['won_by_person_idx'], 'displayed_minute': r['displayed_minute'],
            'second': r['second'], 'clock_raw': r['clock_raw'],
            'origin_x': _point(r['origin_x']), 'origin_y': _point(r['origin_y']),
            'end_x': _point(r['end_x']), 'end_y': _point(r['end_y']), 'end_state': r['end_state'],
            'target_x': _point(r['target_x']), 'target_y': _point(r['target_y']), 'native_category_code': r['category'],
            'native_flags_word': r['flags']}


LIMITS = [
    'Rows come from a saved file: they describe the match as it was stored when the save was written.',
    'A throw-in is returned with counted false; the game leaves throw-ins out of its pass counters.',
    'key_pass, chance_created and assist_marked are markers the game sets on some records; a false value '
    'does not show the pass was none of these. side_coverage gives the markers found on pass rows and on '
    'all events beside the stored totals; the game also marks crosses, which are not pass rows.',
    'A failed pass has no stored intended recipient. Coordinates are native pitch units about the centre spot, '
    'rounded to 0.001; '
    'x is across the pitch, y along it, and which goal a side attacks is not decoded here.',
    'person_index values belong to this save only; name them with fm_get_saved_person_name_candidates.',
]


def _member(handle, entries, name):
    root = entries[0].path.split('/')[0]
    found = [e for e in entries if e.path == f'{root}/{name}']
    if len(found) != 1:
        raise ValueError(f'Saved career requires exactly one root {name}')
    return found[0]


def _entries(handle, entries, pin):
    if pin in _CACHE:
        return _CACHE[pin]
    member = _member(handle, entries, 'game_db.dat')
    if not 0 < member.uncompressed_size <= saved_component_stream.MAX_RAW_SIZE:
        raise ValueError('Saved database component size budget exceeded')
    parts = []
    with saved_component_stream.open_component(handle, member) as reader:
        left = reader.size
        while left:
            take = min(saved_component_stream.MAX_TAKE, left)
            parts.append(reader.take(take))
            left -= take
    found = find_entries(b''.join(parts))
    while len(_CACHE) >= 2:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[pin] = found
    return found


def _frame(handle, entries, fixture_key):
    member = _member(handle, entries, 'match_stats_cfg.dat')
    if not (0 < member.uncompressed_size <= stored.MAX_COMPONENT_BYTES
            and 0 < member.compressed_size <= stored.MAX_COMPONENT_BYTES):
        raise ValueError('Saved match component size budget exceeded')
    index = stored._index(handle, member)
    matches = [(c, r) for c in index['containers'] for r in c['indices'] if r['key_i32'] == fixture_key]
    if len(matches) > 1:
        raise ValueError('Retained match key has multiple physical storage entries')
    if not matches:
        return None
    container, row = matches[0]
    if not 1 <= row['length'] <= stored.MAX_SELECTED_FRAME_BYTES:
        raise ValueError('Saved match selected compressed-frame budget exceeded')
    with saved_component_stream.open_component(handle, member) as reader:
        reader.skip(container['payload_start'] + row['offset'])
        packed = reader.take(row['length'])
    frame = frame_players(expand_frame(packed))
    if frame['fixture_key'] != fixture_key:
        raise ValueError('Retained match inner key differs from requested storage key')
    return frame


def _summary(entry):
    passes = [e for e in entry['events'] if e['category'] in mpd.PASS_CATEGORIES]
    return {'date': entry['date'], 'owner_team_native_id': entry['owner_team_native_id'],
            'owner_side_index': entry['owner_side_index'], 'event_count': len(entry['events']),
            'counted_pass_attempts': sum(not e['flags'] & mpd.MASK_EXCLUDED for e in passes),
            'throw_ins': sum(bool(e['flags'] & mpd.MASK_EXCLUDED) for e in passes),
            'cross_attempts': sum(e['category'] in CROSS_CATEGORIES for e in entry['events']),
            'shots': sum(e['category'] in SHOT_OUTCOMES for e in entry['events']),
            'last_displayed_minute': max(e['minute'] for e in entry['events']) + 1,
            'pitch_geometry': entry['pitch_geometry'], 'component_offset': entry['offset']}


def _check_pin(expected_snapshot_id):
    if (not isinstance(expected_snapshot_id, str) or len(expected_snapshot_id) != 64
            or any(c not in '0123456789abcdef' for c in expected_snapshot_id)):
        raise ValueError('Supply the exact expected_snapshot_id of the saved career')


def list_saved_match_event_streams(filename, *, expected_snapshot_id, directory=None):
    """The matches whose full event record this save holds: date, owner team, pass, cross and shot totals."""
    snapshot_catalog.check_filename(filename)
    _check_pin(expected_snapshot_id)
    with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
        pin = snapshot_catalog.snapshot_id(identity)
        if pin != expected_snapshot_id:
            raise ValueError('Saved career identity differs from expected_snapshot_id')
        streams = [_summary(e) for e in _entries(handle, entries, pin)]
    return {'filename': filename, 'snapshot_id': pin, 'state': 'available', 'stream_count': len(streams),
            'streams': sorted(streams, key=lambda s: (s['date'], s['owner_team_native_id'])),
            'owner_side_index': '0: the owner team is the home side (side_index 0 of the rows); 1: the away side',
            'source': {'component': 'game_db.dat', 'record': 'human manager retained match lists',
                       'players_named': False},
            'limits': ['A stream is filed under one team (the owner) and a date; the same match can be held twice, '
                       'once for each list that keeps it.',
                       'Use fm_find_saved_fixture_results for that team and date to get the fixture key, then '
                       'fm_get_saved_match_passes, fm_get_saved_match_crosses or fm_get_saved_match_shots; they '
                       "name players only when the save still holds the match's statistics frame. Without "
                       'one, select the stream by match_date and owner_team_native_id: rows then carry a side '
                       'and a slot.']}


def get_saved_match_passes(filename, fixture_key=None, *, expected_snapshot_id, match_date=None,
                           owner_team_native_id=None, offset=0, limit=100, include_throw_ins=True,
                           directory=None):
    """Every pass of one stored match from a saved career, game closed.

    Select the match by its fixture key (rows are then bound to players and closed against the
    stored counters), or, for a stream the save holds no statistics frame for, by the stream's
    date and owner team as fm_list_saved_match_event_streams gives them (rows then carry a side
    and a slot and no player)."""
    _check_selectors(filename, fixture_key, expected_snapshot_id, match_date, owner_team_native_id, offset, limit)
    if type(include_throw_ins) is not bool:
        raise ValueError('include_throw_ins must be boolean')
    chosen = _choose(filename, fixture_key, expected_snapshot_id, match_date, owner_team_native_id, directory)
    base = {'filename': filename, 'snapshot_id': chosen['snapshot_id'], 'fixture_key': fixture_key,
            'offset': offset, 'limit': limit, 'total_count': None, 'next_offset': None, 'passes': [],
            'limits': LIMITS}
    if chosen['state'] is not None:
        return {**base, **chosen['unavailable']}
    entry, frame = chosen['entry'], chosen['frame']
    got = decode_unbound(entry) if frame is None else chosen['passes']
    rows = [_row(r) for r in got['rows'] if include_throw_ins or r['counted']]
    return {**base, 'state': got['state'], 'match_date': entry['date'],
            'teams': None if frame is None else frame['teams'],
            'side_coverage': got['side_coverage'], 'pitch_geometry': entry['pitch_geometry'],
            'total_count': len(rows), 'passes': rows[offset:offset + limit],
            'next_offset': offset + limit if offset + limit < len(rows) else None,
            'source': _source(entry, frame, fixture_key, 'passes attempted and completed')}


def _check_selectors(filename, fixture_key, expected_snapshot_id, match_date, owner_team_native_id, offset, limit):
    snapshot_catalog.check_filename(filename)
    _check_pin(expected_snapshot_id)
    if fixture_key is None:
        if (not isinstance(match_date, str) or type(owner_team_native_id) is not int
                or not -2**31 <= owner_team_native_id < 2**31):
            raise ValueError('Supply fixture_key, or match_date and owner_team_native_id of a listed stream')
        date.fromisoformat(match_date)
    elif type(fixture_key) is not int or not 0 <= fixture_key < 2**31:
        raise ValueError('Invalid saved match fixture key')
    elif match_date is not None or owner_team_native_id is not None:
        raise ValueError('Select by fixture_key or by match_date and owner_team_native_id, not both')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= MAX_PAGE:
        raise ValueError(f'offset must be nonnegative and limit 1..{MAX_PAGE}')


def _choose(filename, fixture_key, expected_snapshot_id, match_date, owner_team_native_id, directory):
    """The one stored entry the selectors name, with its frame when selected by fixture key.

    By fixture key the entry is the one whose owner team is the frame's team on the owner side and
    whose pass counts close on every stored player (decode_passes); `passes` is that result.
    `state` is None when an entry was chosen, else `unavailable` holds the fields to return."""
    with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
        pin = snapshot_catalog.snapshot_id(identity)
        if pin != expected_snapshot_id:
            raise ValueError('Saved career identity differs from expected_snapshot_id')
        frame = None if fixture_key is None else _frame(handle, entries, fixture_key)
        if frame is None and fixture_key is not None:
            return {'snapshot_id': pin, 'state': 'unavailable_no_stored_statistics_frame',
                    'unavailable': {'state': 'unavailable_no_stored_statistics_frame'}}
        streams = _entries(handle, entries, pin)
    chosen, passes, tried = None, None, []
    if frame is None:
        for entry in streams:
            if entry['date'] == match_date and entry['owner_team_native_id'] == owner_team_native_id:
                if chosen is not None and chosen['events'] != entry['events']:
                    raise ValueError('Two different stored event streams share this date and owner team')
                chosen = chosen or entry
        state = None if chosen else 'unavailable_no_event_stream_for_this_date_and_team'
        unavailable = {'state': state}
    else:
        for entry in streams:
            if not _owner_in_fixture(entry, frame):
                continue
            got = decode_passes(entry, frame)
            tried.append({'date': entry['date'], 'owner_team_native_id': entry['owner_team_native_id'],
                          'state': got['state'], 'players_equal': got.get('players_equal')})
            if got['state'] == 'available':
                if chosen is not None and chosen['events'] != entry['events']:
                    raise ValueError('Two different stored event streams close against this match')
                if chosen is None:
                    chosen, passes = entry, got
        state = None if chosen else 'unavailable_no_event_stream_for_this_match'
        unavailable = {'state': state, 'teams': frame['teams'], 'streams_of_these_teams': tried}
    return {'snapshot_id': pin, 'state': state, 'unavailable': unavailable, 'entry': chosen, 'frame': frame,
            'passes': passes}


def _source(entry, frame, fixture_key, closed_on):
    return {'events': 'game_db.dat, human manager retained match entry', 'stream': _summary(entry),
            'roster_and_counters': None if frame is None else f'match_stats_cfg.dat frame {fixture_key}',
            'binding': ('none: selected by date and owner team; no stored counters to close against'
                        if frame is None else
                        f'owner team is one of the two teams and every stored player closes on {closed_on}')}


CROSS_LIMITS = [
    LIMITS[0],
    'completed is the game\'s own category and is what the stored cross counters close on. The failure types '
    '(intercepted, blocked, out_of_play, not_completed_other) are named from where the stored ball path ends: '
    'at an opposing player\'s event, at an opposing block, outside the pitch, or at no stored event. Those are '
    'the signs of the same pass outcomes; the game\'s code was not read for the cross categories.',
    'recipient_person_index is stored for a completed cross only. won_by_person_index is the opposing player '
    'whose event is stored where the cross ended, when there is exactly one.',
    'origin is where the cross was played from and end is the last stored sample of the ball path. Coordinates '
    'are native pitch units about the centre spot, rounded to 0.001; x is across the pitch, y along it, and '
    'attacks_positive_y says which goal the crossing side attacked.',
    'key_pass, chance_created and assist_marked are markers the game sets on some records; a false value does '
    'not show the cross was none of these.',
    LIMITS[-1],
]
SHOT_LIMITS = [
    LIMITS[0],
    'A row is a shot-end event of the match record: goal, missed_target, hit_woodwork, saved or blocked. '
    'on_target is goal or saved, which is what the stored shots-on-target counters close on. An own goal is not '
    'a shot; own_goals lists them with the player who scored it and the side it counted for.',
    'expected_goals, native_shot_type, body_part and is_penalty come from the shot record stored beside the '
    'events. A shot can lack one (expected_goals_state no_stored_shot_record). side_coverage counts those and '
    'says whether the summed values equal the stored team value; the game adds each value rounded to 1/2**24.',
    'body_part is head or feet for the shot types the game\'s shot map groups that way, otherwise null. restart '
    'free_kick is a direct free kick. location is the game\'s shot-map zone; Left and Right in it are the '
    'game\'s labels, not a viewer\'s.',
    'x and y are where the shot was taken and end_x, end_y the last stored sample of the ball path, in native '
    'pitch units about the centre spot, rounded to 0.001; attacks_positive_y says which goal the side attacked.',
    LIMITS[-1],
]


def _saved_match_rows(decode, name, closed_on, limits, filename, fixture_key, expected_snapshot_id, match_date,
                      owner_team_native_id, offset, limit, directory):
    _check_selectors(filename, fixture_key, expected_snapshot_id, match_date, owner_team_native_id, offset, limit)
    chosen = _choose(filename, fixture_key, expected_snapshot_id, match_date, owner_team_native_id, directory)
    base = {'filename': filename, 'snapshot_id': chosen['snapshot_id'], 'fixture_key': fixture_key,
            'offset': offset, 'limit': limit, 'total_count': None, 'next_offset': None, name: [], 'limits': limits}
    if chosen['state'] is not None:
        return {**base, **chosen['unavailable']}
    entry, frame = chosen['entry'], chosen['frame']
    got = decode(entry, frame)
    rows = got.pop('rows')
    teams = None if frame is None else frame['teams']
    if not got['state'].startswith('available'):
        return {**base, **got, 'match_date': entry['date'], 'teams': teams}
    return {**base, **got, 'match_date': entry['date'], 'teams': teams,
            'pitch_geometry': entry['pitch_geometry'], 'total_count': len(rows), name: rows[offset:offset + limit],
            'next_offset': offset + limit if offset + limit < len(rows) else None,
            'source': _source(entry, frame, fixture_key, closed_on)}


def get_saved_match_crosses(filename, fixture_key=None, *, expected_snapshot_id, match_date=None,
                            owner_team_native_id=None, offset=0, limit=100, directory=None):
    """Every cross of one stored match from a saved career, game closed. Selected as
    get_saved_match_passes selects; by fixture key the rows are returned only when every stored
    player also closes on crosses attempted and completed."""
    return _saved_match_rows(
        decode_crosses, 'crosses', 'passes attempted and completed, and on crosses attempted and completed',
        CROSS_LIMITS, filename, fixture_key, expected_snapshot_id, match_date, owner_team_native_id, offset, limit,
        directory)


def get_saved_match_shots(filename, fixture_key=None, *, expected_snapshot_id, match_date=None,
                          owner_team_native_id=None, offset=0, limit=100, directory=None):
    """Every shot of one stored match from a saved career, game closed. Selected as
    get_saved_match_passes selects; by fixture key the rows are returned only when every stored
    player also closes on shots and shots on target and both team totals are equal."""
    return _saved_match_rows(
        decode_shots, 'shots', 'passes attempted and completed, and on shots and shots on target',
        SHOT_LIMITS, filename, fixture_key, expected_snapshot_id, match_date, owner_team_native_id, offset, limit,
        directory)
