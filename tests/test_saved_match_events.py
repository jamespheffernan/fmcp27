"""Per-pass records read from a saved career (saved_match_events) and the pass-type flags.

Captured bytes: `saved_match_events_98754.json.gz` is one retained match entry cut from game_db.dat of
a real save with the bytes around it, and the same match's stored statistics frame from
match_stats_cfg.dat. The Lille v Newcastle and Newcastle v Southampton fixtures are event records
read from the running game.
"""
import asyncio
import copy
import gzip
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

import pytest

from fm_live_mcp import saved_match_events as sme
from fm_live_mcp.fmdb import match_pass_decode as mpd

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture(scope='module')
def saved():
    doc = json.load(gzip.open(FIXTURES / 'saved_match_events_98754.json.gz', 'rt'))
    doc['window'] = bytes.fromhex(doc['window_hex'])
    doc['frame'] = bytes.fromhex(doc['frame_hex'])
    assert hashlib.sha256(doc['window']).hexdigest() == doc['window_sha256']
    assert hashlib.sha256(doc['frame']).hexdigest() == doc['frame_sha256']
    return doc


def _event(category, side, slot, clock, *, second_slot=0xFF, linked=0, minute=0, second=0, xy=(0.0, 0.0),
           event_id=0, flags=0, path=()):
    return (struct.pack('<ffHI', xy[0], xy[1], 0, len(path)) + b''.join(struct.pack('<ff', *p) for p in path)
            + struct.pack('<BBBHBBBHBIH', category, slot, side, clock, linked, minute, second, flags, second_slot,
                          event_id, clock + linked))


def _shot(event_id, expected_goals, clock, shot_type):
    return struct.pack('<I8sfIIB', event_id, bytes(8), expected_goals, event_id, clock, shot_type)


def _entry(events, *, day=120, year=2030, owner=688, owner_side=0, shots=(0, 0), geometry=(34.0, 52.5),
           tracked=(), samples=0):
    """One serialized retained entry: record, tables, tracking paths, then date, owner and owner side.

    shots: per side, a count of zero-filled shot records or a list of records from _shot."""
    body = struct.pack('<BII', 1, sme.ENTRY_VERSION, len(events)) + b''.join(events)
    for side in shots:
        records = [bytes(sme.SHOT_BYTES)] * side if isinstance(side, int) else side
        body += struct.pack('<I', len(records)) + b''.join(records)
    body += struct.pack('<ff', *geometry) + struct.pack('<IIi', 11122, 22662, -1)
    for side in range(2):
        body += struct.pack('<I', 2) + struct.pack('<HHHH', 1, 4, 0xFFFF, 2)          # pass-pair counts
        body += struct.pack('<I', 1) + struct.pack('<BffH', side, 10.0, -20.0, 3)       # position sums
        body += struct.pack('<I', 1) + bytes([4, 0, 0, 1])                              # top pairs
    body += b'\x00' + struct.pack('<I', len(tracked))
    for ident, count in tracked:
        body += struct.pack('<BII', ident, 24, count) + bytes(4 * count)
    body += struct.pack('<I', samples) + bytes(samples) + b'\x00\x00'
    return body + struct.pack('<HHiB', 0x7200 | day, year, owner, owner_side)


def test_entry_of_a_real_save_parses_whole_and_is_found_among_other_bytes(saved):
    start = saved['entry_offset_in_window']
    entry = sme.parse_entry(saved['window'], start)
    assert entry['date'] == saved['match_date'] == '2029-05-06'
    assert entry['owner_team_native_id'] == saved['owner_team_native_id'] == 2000779776
    assert entry['owner_side_index'] == saved['owner_side_index'] == 1
    assert len(entry['events']) == 1779 and entry['shot_counts'] == [3, 26]
    assert entry['pitch_geometry'] == {'half_width_native': 35.0, 'half_length_native': 52.5}
    # the record is walked from its first byte to the owner side with nothing left over
    assert entry['end'] - entry['offset'] == saved['entry_length'] == 83047
    # the window also holds the previous entry's last 600 bytes and the next entry's first 300;
    # the scan returns this entry alone and is not misled by stray markers placed in front
    found = sme.find_entries(sme.ENTRY_MARK * 3 + saved['window'])
    assert [(e['date'], len(e['events'])) for e in found] == [('2029-05-06', 1779)]
    assert found[0]['offset'] == start + 3 * len(sme.ENTRY_MARK)
    # a cut-off entry is refused, never returned short
    assert sme.parse_entry(saved['window'][:entry['end'] - 1], start) is None
    assert sme.parse_entry(saved['window'], start + 1) is None


def test_every_stored_player_closes_and_totals_equal_the_games_counters(saved):
    entry = sme.parse_entry(saved['window'], saved['entry_offset_in_window'])
    frame = sme.frame_players(saved['frame'])
    assert frame['fixture_key'] == saved['fixture_key'] == 98754
    got = sme.decode_passes(entry, frame)
    assert got['state'] == 'available'
    home, away = got['side_coverage']
    assert (home['pass_attempts'], home['passes_completed']) == (456, 372)
    assert (away['pass_attempts'], away['passes_completed']) == (396, 325)
    for side in got['side_coverage']:
        assert side['pass_attempts'] == side['stored_pass_attempts']
        assert side['passes_completed'] == side['stored_passes_completed']
        assert side['players_checked'] == 16 and side['all_player_counters_equal'] is True
    rows = got['rows']
    counted = [r for r in rows if r['counted']]
    assert Counter(r['outcome'] for r in counted) == {'completed': 697, 'not_completed_other': 71, 'intercepted': 68,
                                                      'out_of_play': 15, 'blocked': 1}
    # per player, from the rows alone: attempts and completions equal the stored bytes
    by = Counter((r['side'], r['slot']) for r in counted)
    done = Counter((r['side'], r['slot']) for r in counted if r['completed'])
    for p in frame['players']:
        key = (p['side_index'], p['stored_player_slot'])
        assert (by[key], done[key]) == (p['passes_attempted'], p['passes_completed'])
    # completed passes name a receiver of the same side; failed passes have none
    people = {p['person_index_word']: p['side_index'] for p in frame['players']}
    for r in counted:
        assert people[r['person_idx']] == r['side']
        if r['completed']:
            assert people[r['recipient_person_idx']] == r['side']
        else:
            assert r['recipient_person_idx'] is None and r['recipient_state'] == 'not_stored_by_game'
        assert r['origin_x'] == r['x'] and r['origin_y'] == r['y']      # the path starts at the pass
        assert 1 <= r['displayed_minute'] <= 100 and 0 <= r['second'] < 60
    first = sme._row(rows[0])
    assert (first['event_id'], first['side_index'], first['person_index'], first['outcome'], first['displayed_minute'],
            first['second']) == (0, 0, 151371, 'completed', 1, 1)


def test_throw_ins_are_returned_uncounted_and_start_on_the_touchline(saved):
    entry = sme.parse_entry(saved['window'], saved['entry_offset_in_window'])
    got = sme.decode_passes(entry, sme.frame_players(saved['frame']))
    throws = [r for r in got['rows'] if not r['counted']]
    assert [s['throw_ins'] for s in got['side_coverage']] == [11, 5] and len(throws) == 16
    half_width = entry['pitch_geometry']['half_width_native']
    assert all(r['restart'] == 'throw_in' and abs(r['x']) >= half_width for r in throws)
    assert Counter(r['restart'] for r in got['rows'] if r['counted']) == {None: 833, 'free_kick': 19}
    # the game marks key passes and created chances on some events only; the stored totals are larger
    away = got['side_coverage'][1]
    assert (away['key_pass_markers_on_pass_rows'], away['key_pass_markers_on_all_events'], away['stored_key_passes']) == (8, 19, 27)
    assert (away['chance_created_markers_on_all_events'], away['stored_chances_created']) == (11, 12)


def test_a_stream_is_refused_for_another_match_or_changed_counters(saved):
    entry = sme.parse_entry(saved['window'], saved['entry_offset_in_window'])
    frame = sme.frame_players(saved['frame'])
    wrong = copy.deepcopy(frame)
    wrong['players'][3]['passes_attempted'] += 1
    got = sme.decode_passes(entry, wrong)
    assert got['state'] == 'unavailable_player_counter_reconciliation' and got['rows'] == []
    assert (got['players_checked'], got['players_equal']) == (32, 31)
    refused = {'state': 'unavailable_owner_team_not_in_fixture', 'rows': []}
    other = copy.deepcopy(frame)
    other['teams'][1]['team_native_id'] += 1
    assert sme.decode_passes(entry, other) == refused
    swapped = copy.deepcopy(frame)               # the owner is in the fixture, on the other side
    swapped['teams'].reverse()
    assert sme.decode_passes(entry, swapped) == refused
    short = copy.deepcopy(frame)                 # an actor the frame has no player for
    short['players'] = [p for p in short['players'] if (p['side_index'], p['stored_player_slot']) != (0, 9)]
    assert sme.decode_passes(entry, short)['actor_slots_without_a_stored_player'] == [(0, 9)]


def test_stream_without_a_statistics_frame_gives_slots_and_no_player(saved):
    entry = sme.parse_entry(saved['window'], saved['entry_offset_in_window'])
    got = sme.decode_unbound(entry)
    assert got['state'] == 'available_without_stored_player_counters'
    assert [(s['pass_attempts'], s['passes_completed'], s['stored_pass_attempts']) for s in got['side_coverage']] == [
        (456, 372, None), (396, 325, None)]
    assert all(r['person_idx'] is None and r['recipient_person_idx'] is None for r in got['rows'])
    assert {sme._row(r)['stored_player_slot'] for r in got['rows'] if r['side'] == 0} <= set(range(16))


def test_serialized_events_become_the_records_the_live_decoder_reads():
    events = [
        _event(7, 0, 3, 100, second_slot=5, linked=2, minute=7, second=10, xy=(1, 1), event_id=1,
               path=((1, 1), (3, 3), (4, 4))),
        _event(52, 0, 5, 102, xy=(4, 4), event_id=2),
        _event(8, 0, 5, 200, linked=3, minute=8, second=28, event_id=3, flags=0x003, path=((0, 0), (-11, -15))),
        _event(52, 1, 9, 203, xy=(-11, -15), event_id=4),
        _event(7, 1, 9, 300, second_slot=4, minute=9, xy=(34.2, 10), event_id=5, flags=0x009),
        _event(7, 1, 4, 310, second_slot=9, minute=9, xy=(33.5, 52.8), event_id=6, flags=0x441),
        _event(10, 0, 3, 400, minute=10, event_id=7, flags=0x021),
    ]
    one = _entry(events, day=347, year=2030, owner=688, owner_side=1, shots=(2, 1),
                 tracked=((0, 40), (1, 40), (17, 3)), samples=41)
    two = _entry(events[:2], day=352, year=2030, owner=688)
    buf = b'\x00' * 40 + struct.pack('<H', 2) + one + two + b'\xff' * 30
    entry, second = sme.find_entries(buf)
    assert (entry['date'], entry['owner_team_native_id'], entry['owner_side_index'], entry['shot_counts']) == (
        '2030-12-13', 688, 1, [2, 1])
    assert (entry['offset'], entry['end'] - entry['offset']) == (42, len(one))
    assert (second['date'], second['owner_side_index'], len(second['events']), second['offset']) == (
        '2030-12-18', 0, 2, 42 + len(one))
    raw, paths = sme.memory_records(entry['events'])
    assert len(raw) == 56 * 7 and paths == {0: [(1, 1), (3, 3), (4, 4)], 2: [(0, 0), (-11, -15)]}
    record = raw[2 * 56:3 * 56]
    assert record[:0x18] == bytes(0x18)
    assert struct.unpack_from('<H', record, 0x22)[0] == 200 and record[0x24:0x2B] == bytes([3, 8, 28, 5, 0, 0xFF, 8])
    assert struct.unpack_from('<IHH', record, 0x2C) == (3, 0x003, 203)
    roster = {(0, 3): 300, (0, 5): 500, (1, 9): 900, (1, 4): 400}
    rows = {r['event_id']: r for r in mpd.decode(raw, paths, roster, include_uncounted=True)}
    assert set(rows) == {1, 3, 5, 6, 7}
    assert rows[1]['recipient_person_idx'] == 500 and rows[1]['end_state'] == 'linked_event_location'
    assert rows[3]['outcome'] == 'intercepted' and rows[3]['won_by_person_idx'] == 900 and rows[3]['key_pass']
    assert (rows[5]['counted'], rows[5]['restart']) == (False, 'throw_in')
    assert (rows[6]['restart'], rows[6]['chance_created'], rows[6]['counted']) == ('corner', True, True)
    assert rows[7]['restart'] == 'free_kick' and not rows[7]['key_pass']
    # the default call is the counted attempts only, as before; reconcile ignores throw-ins
    assert {r['event_id'] for r in mpd.decode(raw, paths, roster)} == {1, 3, 6, 7}
    players = [{'side_index': 0, 'stored_player_slot': 3, 'passes_attempted': 2, 'passes_completed': 1},
               {'side_index': 0, 'stored_player_slot': 5, 'passes_attempted': 1, 'passes_completed': 0},
               {'side_index': 1, 'stored_player_slot': 9, 'passes_attempted': 0, 'passes_completed': 0},
               {'side_index': 1, 'stored_player_slot': 4, 'passes_attempted': 1, 'passes_completed': 1}]
    assert all(c['ok'] for c in mpd.reconcile(list(rows.values()), players))


def test_malformed_entries_are_not_returned():
    good = _entry([_event(7, 0, 1, 10, event_id=1)], tracked=((0, 5),), samples=6)
    assert len(sme.find_entries(good)) == 1
    for at, value in ((0, b'\x00'),                              # record not present
                      (1, b'\x13'),                              # another version
                      (len(good) - 1, b'\x02'),                  # owner side above 1
                      (len(good) - 7, struct.pack('<H', 1700)),   # impossible year
                      (len(good) - 9, struct.pack('<H', 0x7200 | 400))):   # day 400
        bad = bytearray(good)
        bad[at:at + len(value)] = value
        assert sme.find_entries(bytes(bad)) == []
    assert sme.find_entries(_entry([_event(7, 2, 1, 10)])) == []                        # side 2
    assert sme.find_entries(_entry([_event(7, 0, 1, 10)], geometry=(0.0, 52.5))) == []  # no pitch
    assert sme.find_entries(_entry([_event(7, 0, 1, 10, xy=(float('nan'), 0.0))])) == []
    assert sme.find_entries(good[:-1]) == []
    # a tracking path that claims more samples than the file holds
    huge = bytearray(good)
    at = good.index(struct.pack('<BII', 0, 24, 5))
    huge[at + 5:at + 9] = struct.pack('<I', 60000)
    assert sme.find_entries(bytes(huge)) == []


def test_pass_type_flags_on_events_read_from_the_running_game():
    lille = json.load(gzip.open(FIXTURES / 'retained_key_passes_lille_136941.json.gz', 'rt'))
    raw = bytes.fromhex(lille['events_hex'])
    half_width = lille['pitch_geometry']['half_width_native']
    rows = mpd.decode(raw, include_uncounted=True)
    throws = [r for r in rows if not r['counted']]
    assert len(throws) == 21 and all(r['restart'] == 'throw_in' and abs(r['x']) >= half_width for r in throws)
    assert len(mpd.decode(raw)) == len(rows) - 21
    # free kicks taken by a side equal the fouls stored against the other side (10 and 8)
    fouls = Counter()
    for player in lille['players']:
        child = bytes.fromhex(player['raw_child_hex'])
        fouls[player['side_index']] += child[60 + (0 if child[0] >= 2 else 4)]
    records = mpd.records(raw)
    taken = Counter(e[0x28] for e in records
                    if struct.unpack_from('<H', e, 0x30)[0] & (mpd.FLAG_FREE_KICK | mpd.FLAG_FREE_KICK_BIT6))
    assert (fouls[0], fouls[1]) == (10, 8) and (taken[1], taken[0]) == (10, 8)
    # every corner-flagged event starts at a corner flag
    corners = [struct.unpack_from('<ff', e, 0x18) for e in records if struct.unpack_from('<H', e, 0x30)[0] & mpd.FLAG_CORNER]
    assert len(corners) == 12 and all(abs(x) > 33 and abs(y) > 52 for x, y in corners)
    # key-pass and chance-created markers per player never exceed the stored counters
    for mask, offset in ((mpd.FLAG_KEY_PASS, 88), (mpd.FLAG_CHANCE_CREATED, 57)):
        marks = Counter((e[0x28], e[0x27]) for e in records if struct.unpack_from('<H', e, 0x30)[0] & mask)
        for player in lille['players']:
            child = bytes.fromhex(player['raw_child_hex'])
            assert marks[(player['side_index'], player['stored_player_slot'])] <= child[offset + (0 if child[0] >= 2 else 4)]
    assert mpd.pass_type(0x443) == {'flags': 0x443, 'restart': 'corner', 'key_pass': True, 'chance_created': True,
                                    'assist_marked': False}
    assert mpd.pass_type(0x105)['assist_marked'] and mpd.pass_type(0x105)['restart'] is None

    with gzip.open(FIXTURES / 'retained_pass_network_136523.json.gz', 'rt') as f:
        other = bytes.fromhex(json.load(f)['events'])
    throws = [r for r in mpd.decode(other, include_uncounted=True) if not r['counted']]
    assert len(throws) == 33 and all(34.0 <= abs(r['x']) <= 36.0 for r in throws)


def test_crosses_close_on_every_stored_player_and_a_completed_cross_names_its_receiver(saved):
    entry = sme.parse_entry(saved['window'], saved['entry_offset_in_window'])
    frame = sme.frame_players(saved['frame'])
    got = sme.decode_crosses(entry, frame)
    assert got['state'] == 'available'
    home, away = got['side_coverage']
    assert (home['cross_attempts'], home['crosses_completed']) == (15, 0)
    assert (away['cross_attempts'], away['crosses_completed']) == (51, 15)
    assert home['outcome_counts'] == {'completed': 0, 'intercepted': 4, 'blocked': 0, 'not_completed_other': 11,
                                      'out_of_play': 0, 'not_completed_unnamed': 0}
    assert away['outcome_counts'] == {'completed': 15, 'intercepted': 4, 'blocked': 0, 'not_completed_other': 31,
                                      'out_of_play': 1, 'not_completed_unnamed': 0}
    assert (home['from_corners'], away['from_corners'], away['from_free_kicks']) == (1, 7, 0)
    for side in got['side_coverage']:
        assert side['cross_attempts'] == side['stored_cross_attempts']
        assert side['crosses_completed'] == side['stored_crosses_completed']
        assert side['players_checked'] == 16 and side['all_player_counters_equal'] is True
    rows = got['rows']
    # per player, from the rows alone: attempts and completions equal the stored bytes 89 and 90
    by = Counter((r['side_index'], r['stored_player_slot']) for r in rows)
    done = Counter((r['side_index'], r['stored_player_slot']) for r in rows if r['completed'])
    assert sum(p['crosses_attempted'] for p in frame['players']) == 66
    for p in frame['players']:
        key = (p['side_index'], p['stored_player_slot'])
        assert (by[key], done[key]) == (p['crosses_attempted'], p['crosses_completed'])
    # the same events the live reader takes from the 56-byte records (category +42, side +40, slot +39)
    from fm_live_mcp.retained_cross_events import CROSS_CATEGORIES
    raw, _ = sme.memory_records(entry['events'])
    live = Counter((raw[at + 40], raw[at + 39], raw[at + 42] == 12) for at in range(0, len(raw), 56)
                   if raw[at + 42] in CROSS_CATEGORIES)
    assert live == Counter((r['side_index'], r['stored_player_slot'], r['completed']) for r in rows)
    # only a completed cross stores a receiver, a team-mate; an opponent is named where the path ends at one
    people = {p['person_index_word']: p['side_index'] for p in frame['players']}
    for r in rows:
        assert people[r['person_index']] == r['side_index']
        assert (r['recipient_person_index'] is not None) == r['completed']
        if r['completed']:
            assert people[r['recipient_person_index']] == r['side_index'] and r['won_by_person_index'] is None
        if r['won_by_person_index'] is not None:
            assert people[r['won_by_person_index']] != r['side_index'] and r['end_state'] == 'linked_event_location'
        assert 1 <= r['displayed_minute'] <= 100 and 0 <= r['second'] < 60
    assert Counter((r['outcome'], r['end_state']) for r in rows) == {
        ('not_completed_other', 'unlinked_end_sample'): 42, ('completed', 'linked_event_location'): 12,
        ('intercepted', 'linked_event_location'): 8, ('completed', 'unlinked_end_sample'): 3,
        ('out_of_play', 'outside_pitch_sample'): 1}
    assert all(r['won_by_person_index'] is not None for r in rows if r['outcome'] == 'intercepted')
    # every cross flagged as a corner is played from a corner flag
    corners = [r for r in rows if r['restart'] == 'corner']
    assert len(corners) == 8 and all(abs(r['origin_x']) > 33 and abs(r['origin_y']) > 50.5 for r in corners)
    # the first completed cross is a corner; its receiver heads at goal from where the cross ended
    first = next(r for r in rows if r['completed'])
    assert (first['event_id'], first['restart'], first['person_index'], first['recipient_person_index'],
            first['displayed_minute'], first['second'], first['key_pass'], first['chance_created']) == (
        115, 'corner', 140371, 140373, 8, 21, True, True)
    header = sme.decode_shots(entry, frame)['rows'][0]
    assert (header['person_index'], header['body_part'], header['second']) == (140373, 'head', 23)
    assert (header['x'], header['y']) == (first['end_x'], first['end_y']) == (-2.222, -47.111)


def test_crosses_are_refused_for_changed_counters_and_given_by_slot_without_a_frame(saved):
    entry = sme.parse_entry(saved['window'], saved['entry_offset_in_window'])
    frame = sme.frame_players(saved['frame'])
    wrong = copy.deepcopy(frame)
    crosser = next(p for p in wrong['players'] if p['crosses_completed'])
    crosser['crosses_completed'] -= 1
    got = sme.decode_crosses(entry, wrong)
    assert got['state'] == 'unavailable_cross_counter_reconciliation' and got['rows'] == []
    assert (got['players_checked'], got['players_equal']) == (32, 31)
    other = copy.deepcopy(frame)
    other['teams'][1]['team_native_id'] += 1
    assert sme.decode_crosses(entry, other) == {'state': 'unavailable_owner_team_not_in_fixture', 'rows': []}
    short = copy.deepcopy(frame)
    slot = (crosser['side_index'], crosser['stored_player_slot'])
    short['players'] = [p for p in short['players'] if (p['side_index'], p['stored_player_slot']) != slot]
    assert sme.decode_crosses(entry, short)['actor_slots_without_a_stored_player'] == [slot]
    free = sme.decode_crosses(entry)
    assert free['state'] == 'available_without_stored_player_counters'
    assert [(s['cross_attempts'], s['crosses_completed'], s['stored_cross_attempts'], s['team_native_id'])
            for s in free['side_coverage']] == [(15, 0, None, None), (51, 15, None, None)]
    assert all(r['person_index'] is None and r['recipient_person_index'] is None for r in free['rows'])
    assert sum(r['recipient_stored_player_slot'] is not None for r in free['rows']) == 15


def test_shot_records_decode_and_close_on_counts_and_expected_goals(saved):
    entry = sme.parse_entry(saved['window'], saved['entry_offset_in_window'])
    frame = sme.frame_players(saved['frame'])
    assert [len(raw) // sme.SHOT_BYTES for raw in entry['shot_records']] == entry['shot_counts'] == [3, 26]
    # one record: event id, eight zero bytes, expected goals, the id again, the event's clock, shot type
    assert entry['shot_records'][0][:25].hex() == 'b80500000000000000000000e505133cb8050000503d000001'
    records, problems = sme.shot_records(entry)
    assert problems == [] and len(records) == 29
    assert records[1464] == (pytest.approx(0.00897357, abs=1e-8), 1)
    assert next(e['clock'] for e in entry['events'] if e['event_id'] == 1464) == 0x3D50
    assert frame['team_totals'] == [
        {'shots': 3, 'shots_on_target': 0, 'expected_goals': pytest.approx(0.0342146754)},
        {'shots': 26, 'shots_on_target': 9, 'expected_goals': pytest.approx(3.7742686272)}]
    got = sme.decode_shots(entry, frame)
    assert got['state'] == 'available' and got['own_goals'] == []
    home, away = got['side_coverage']
    assert home['outcome_counts'] == {'goal': 0, 'missed_target': 3, 'hit_woodwork': 0, 'saved': 0, 'blocked': 0}
    assert away['outcome_counts'] == {'goal': 3, 'missed_target': 13, 'hit_woodwork': 2, 'saved': 6, 'blocked': 2}
    for side, team in zip(got['side_coverage'], frame['team_totals']):
        assert (side['shots'], side['shots_on_target']) == (team['shots'], team['shots_on_target'])
        assert (side['stored_shots'], side['stored_shots_on_target']) == (team['shots'], team['shots_on_target'])
        assert side['players_checked'] == 16 and side['all_player_counters_equal'] is True
        # summed the way the game's counters add, the shot values equal the stored team and player values
        assert side['expected_goals'] == side['stored_expected_goals'] == team['expected_goals']
        assert side['expected_goals_equal_to_stored'] is True and side['players_expected_goals_equal'] == 16
        assert side['shots_without_a_shot_record'] == 0
    rows = got['rows']
    by = Counter((r['side_index'], r['stored_player_slot']) for r in rows)
    target = Counter((r['side_index'], r['stored_player_slot']) for r in rows if r['on_target'])
    for p in frame['players']:
        key = (p['side_index'], p['stored_player_slot'])
        assert (by[key], target[key]) == (p['shots'], p['shots_on_target'])
        mine = [records[r['event_id']][0] for r in rows if (r['side_index'], r['stored_player_slot']) == key]
        assert sme.stored_expected_goals_sum(mine) == p['expected_goals']
    # a plain float32 sum of the record values is not the stored value: the game rounds each first
    plain = 0.0
    for r in rows:
        if r['side_index'] == 0:
            plain = sme._f32(plain + records[r['event_id']][0])
    assert plain != home['stored_expected_goals'] and plain == pytest.approx(home['stored_expected_goals'], abs=1e-7)
    assert [(r['event_id'], r['person_index'], r['displayed_minute'], r['second'], r['expected_goals'], r['body_part'],
             r['location']) for r in rows if r['outcome'] == 'goal'] == [
        (327, 147826, 18, 58, 0.469811, 'feet', 'LocationPenaltyBoxNearSpot'),
        (1123, 147826, 49, 38, 0.364821, 'feet', 'LocationPenaltyBoxNearSpot'),
        (1271, 140367, 57, 3, 0.102476, 'head', 'LocationPenaltyBoxNearSpot')]
    assert Counter(r['body_part'] for r in rows) == {'feet': 18, 'head': 11}
    assert Counter(r['location_group'] for r in rows) == {'inside_area': 18, 'outside_area': 11}
    assert not any(r['is_penalty'] or r['restart'] for r in rows)
    assert all(r['on_target'] == (r['outcome'] in ('goal', 'saved')) and r['expected_goals_state'] == 'stored_shot_record'
               for r in rows)
    people = {p['person_index_word']: p['side_index'] for p in frame['players']}
    assert all(people[r['person_index']] == r['side_index'] for r in rows)
    free = sme.decode_shots(entry)
    assert free['state'] == 'available_without_stored_player_counters'
    assert [(s['shots'], s['stored_shots'], s['expected_goals_equal_to_stored']) for s in free['side_coverage']] == [
        (3, None, None), (26, None, None)]
    assert all(r['person_index'] is None for r in free['rows']) and len(free['rows']) == 29


def test_shots_are_refused_for_changed_counters_or_a_shot_record_that_links_nowhere(saved):
    entry = sme.parse_entry(saved['window'], saved['entry_offset_in_window'])
    frame = sme.frame_players(saved['frame'])
    wrong = copy.deepcopy(frame)
    shooter = next(p for p in wrong['players'] if p['shots_on_target'])
    shooter['shots_on_target'] -= 1
    got = sme.decode_shots(entry, wrong)
    assert got['state'] == 'unavailable_shot_counter_reconciliation' and got['rows'] == []
    assert (got['players_checked'], got['players_equal'], got['team_totals_equal']) == (32, 31, True)
    team = copy.deepcopy(frame)
    team['team_totals'][1]['shots'] += 1
    got = sme.decode_shots(entry, team)
    assert (got['state'], got['players_equal'], got['team_totals_equal']) == (
        'unavailable_shot_counter_reconciliation', 32, False)
    other = copy.deepcopy(frame)
    other['teams'][1]['team_native_id'] += 1
    assert sme.decode_shots(entry, other) == {'state': 'unavailable_owner_team_not_in_fixture', 'rows': []}
    home, away = entry['shot_records']
    for at, value, reason in ((0, struct.pack('<I', 1463), 'record_layout_differs'),          # the two ids differ
                              (5, b'\x01', 'record_layout_differs'),
                              (12, struct.pack('<f', 1.5), 'invalid_expected_goals'),
                              (12, struct.pack('<f', float('nan')), 'invalid_expected_goals'),
                              (20, struct.pack('<I', 0x3D51), 'clock_differs_from_linked_event')):
        bad = bytearray(home)
        bad[at:at + len(value)] = value
        got = sme.decode_shots({**entry, 'shot_records': [bytes(bad), away]}, frame)
        assert got['state'] == 'unavailable_shot_record_link' and got['rows'] == []
        assert [p['reason'] for p in got['shot_record_problems']] == [reason]
    # the same record twice, a record in the other side's vector, a record of an event that is not a shot
    for vectors, reason in (([home + home[:25], away], 'missing_or_ambiguous_linked_event'),
                            ([home[25:], away + home[:25]], 'side_or_category_differs'),
                            ([sme.SHOT_RECORD.pack(0, bytes(8), 0.1, 0, entry['events'][0]['clock'], 0) + home, away],
                             'side_or_category_differs')):
        got = sme.decode_shots({**entry, 'shot_records': vectors}, frame)
        assert [p['reason'] for p in got['shot_record_problems']] == [reason]
    assert entry['events'][0]['event_id'] == 0 and entry['events'][0]['side'] == 0
    # a shot the save holds no shot record for is still a row: no expected goals, and the side says so
    got = sme.decode_shots({**entry, 'shot_records': [home[25:], away]}, frame)
    assert got['state'] == 'available'
    bare = [r for r in got['rows'] if r['expected_goals'] is None]
    assert [(r['event_id'], r['expected_goals_state'], r['native_shot_type'], r['body_part'], r['is_penalty'],
             r['outcome']) for r in bare] == [(1464, 'no_stored_shot_record', None, None, None, 'missed_target')]
    side = got['side_coverage'][0]
    assert (side['shots'], side['shots_without_a_shot_record'], side['expected_goals_equal_to_stored'],
            side['players_expected_goals_equal']) == (3, 1, False, 15)
    assert got['side_coverage'][1]['expected_goals_equal_to_stored'] is True


def test_penalty_direct_free_kick_and_own_goal_in_a_built_entry():
    events = [
        _event(1, 0, 3, 500, minute=20, second=4, xy=(0.2, 41.5), event_id=10, flags=0x101,
               path=((0.2, 41.5), (1.5, 52.6))),
        _event(49, 1, 2, 900, minute=37, second=30, xy=(3.0, 50.0), event_id=11),
        _event(5, 1, 7, 1500, minute=61, xy=(-4.0, -30.0), event_id=12, flags=0x011),
        _event(4, 0, 9, 2000, minute=80, xy=(20.0, 20.0), event_id=13, flags=0x101),
        _event(15, 0, 9, 2100, minute=84, xy=(30.0, 40.0), event_id=14, flags=0x101, path=((30.0, 40.0), (2.0, 46.0))),
        _event(16, 1, 2, 2200, minute=88, xy=(-30.0, -40.0), event_id=15, path=((-30.0, -40.0), (5.0, -53.5))),
        _event(13, 1, 2, 2300, linked=4, minute=92, xy=(-30.0, -41.0), event_id=16, path=((-30.0, -41.0), (1.0, -47.0))),
        _event(52, 0, 4, 2304, minute=92, xy=(1.0, -47.0), event_id=17),
    ]
    vectors = ([_shot(10, 0.79, 500, 4), _shot(11, 0.0, 900, 0), _shot(13, 0.05, 2000, 0)], [_shot(12, 0.06, 1500, 3)])
    entry, = sme.find_entries(_entry(events, shots=vectors))
    assert entry['shot_counts'] == [3, 1] and sme.shot_records(entry)[1] == []
    got = sme.decode_shots(entry)
    penalty, free_kick, saved_shot = got['rows']
    assert (penalty['outcome'], penalty['is_penalty'], penalty['expected_goals'], penalty['body_part'],
            penalty['location'], penalty['end_x'], penalty['end_y'], penalty['displayed_minute']) == (
        'goal', True, 0.79, None, 'LocationPenaltyBoxNearSpot', 1.5, 52.6, 21)
    assert (free_kick['outcome'], free_kick['restart'], free_kick['native_shot_type'], free_kick['is_penalty'],
            free_kick['on_target'], free_kick['attacks_positive_y']) == ('blocked', 'free_kick', 3, False, False, False)
    assert (saved_shot['outcome'], saved_shot['on_target'], saved_shot['body_part']) == ('saved', True, 'feet')
    # the own goal is in the scoring side's shot vector and is no shot of either side
    assert got['own_goals'] == [{'event_id': 11, 'side_index': 1, 'stored_player_slot': 2, 'person_index': None,
                                 'beneficiary_side_index': 0, 'displayed_minute': 38, 'second': 30, 'clock_raw': 900}]
    assert [(s['shots'], s['shots_on_target'], s['own_goals_conceded']) for s in got['side_coverage']] == [
        (2, 2, 0), (1, 0, 1)]
    assert got['side_coverage'][0]['expected_goals'] == sme.stored_expected_goals_sum([0.79, 0.05])
    # an own goal filed in its scorer's own vector is refused
    turned, = sme.find_entries(_entry(events, shots=(vectors[0][::2], [vectors[0][1]] + vectors[1])))
    assert sme.decode_shots(turned)['shot_record_problems'] == [
        {'side_index': 1, 'event_id': 11, 'reason': 'side_or_category_differs'}]
    crosses = sme.decode_crosses(entry)['rows']
    assert [(r['outcome'], r['end_state'], r['won_by_stored_player_slot']) for r in crosses] == [
        ('not_completed_other', 'unlinked_end_sample', None), ('out_of_play', 'outside_pitch_sample', None),
        ('intercepted', 'linked_event_location', 4)]
    summary = sme._summary(entry)
    assert (summary['cross_attempts'], summary['shots']) == (3, 3)


def test_expected_goals_are_summed_as_the_stored_counters_hold_them():
    # one shot of the 14 Nov 2026 save: the record holds 0.01233467087, the player's stored value is the
    # nearest multiple of 1/2**24
    record = struct.unpack('<f', struct.pack('<f', 0.0123346708714962))[0]
    stored = sme.stored_expected_goals_sum([record])
    assert stored == 0.012334644794464111 and stored != record
    assert stored * 2 ** 24 == round(record * 2 ** 24) and record * 2 ** 24 != round(record * 2 ** 24)
    assert sme.stored_expected_goals_sum([]) == 0.0 and sme.stored_expected_goals_sum([0.5, 0.25]) == 0.75
    # each value is rounded before it is added, so three values of 0.4 steps add to nothing
    small = [0.4 * 2 ** -24] * 3
    assert sme.stored_expected_goals_sum(small) == 0.0 and round(sum(small) * 2 ** 24) == 1


def test_selectors_are_validated_before_any_file_is_opened():
    pin = 'a' * 64
    for kwargs in ({}, {'match_date': '2030-12-13'}, {'owner_team_native_id': 688},
                   {'fixture_key': 1, 'match_date': '2030-12-13', 'owner_team_native_id': 688},
                   {'fixture_key': -1}, {'fixture_key': True}, {'fixture_key': 1, 'limit': 0},
                   {'fixture_key': 1, 'limit': 501}, {'fixture_key': 1, 'offset': -1},
                   {'fixture_key': 1, 'include_throw_ins': 1},
                   {'match_date': '13 Dec', 'owner_team_native_id': 688}):
        with pytest.raises(ValueError):
            sme.get_saved_match_passes('career.fm', expected_snapshot_id=pin, **kwargs)
        if 'include_throw_ins' not in kwargs:
            for call in (sme.get_saved_match_crosses, sme.get_saved_match_shots):
                with pytest.raises(ValueError):
                    call('career.fm', expected_snapshot_id=pin, **kwargs)
    for bad in ('', 'A' * 64, 'a' * 63, None):
        for call in (sme.get_saved_match_passes, sme.get_saved_match_crosses, sme.get_saved_match_shots):
            with pytest.raises(ValueError):
                call('career.fm', 1, expected_snapshot_id=bad)
        with pytest.raises(ValueError):
            sme.list_saved_match_event_streams('career.fm', expected_snapshot_id=bad)


def test_the_tools_are_registered_read_only_with_bounded_inputs():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def check():
        root = Path(__file__).resolve().parents[1]
        params = StdioServerParameters(command=sys.executable, args=['-m', 'fm_live_mcp.server'], cwd=str(root))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = {t.name: t for t in (await client.list_tools()).tools}
                listing, passes = tools['fm_list_saved_match_event_streams'], tools['fm_get_saved_match_passes']
                crosses, shots = tools['fm_get_saved_match_crosses'], tools['fm_get_saved_match_shots']
                for tool in (listing, passes, crosses, shots):
                    assert tool.annotations.readOnlyHint is True and tool.annotations.destructiveHint is False
                    assert set(tool.inputSchema['required']) == {'filename', 'expected_snapshot_id'}
                selectors = {'filename', 'expected_snapshot_id', 'fixture_key', 'match_date', 'owner_team_native_id',
                             'offset', 'limit'}
                assert set(passes.inputSchema['properties']) == selectors | {'include_throw_ins'}
                assert set(crosses.inputSchema['properties']) == set(shots.inputSchema['properties']) == selectors
                for tool in (passes, crosses, shots):
                    for arguments in ({'fixture_key': '1'}, {'fixture_key': 1, 'limit': 501},
                                      {'fixture_key': 1, 'offset': -1}, {'fixture_key': 1, 'include_throw_ins': 'yes'}, {}):
                        result = await client.call_tool(tool.name, {'filename': 'missing.fm',
                                                                    'expected_snapshot_id': 'a' * 64, **arguments})
                        assert result.isError

    asyncio.run(check())
