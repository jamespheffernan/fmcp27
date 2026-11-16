"""Offline tests for the match tables (fm_live_mcp/fmdb/sources/matches.py and helpers)."""
import sqlite3
import struct

from fm_live_mcp.fmdb import match_archive as ma
from fm_live_mcp.fmdb import match_compstats as mc
from fm_live_mcp.fmdb.match_tool import get_match, match_filter


class _FakeEngine:
    """read_many over a dict of address -> bytes."""

    def __init__(self, memory):
        self.memory = memory

    def read_many(self, requests):
        return [self.memory[a][:n] for a, n in requests]


def test_goal_events_decode_vector_records():
    records = struct.pack('<iiIBBBB', 101, 202, 0, 0, 0, 12, 0) + struct.pack('<iiIBBBB', 303, -1, 0, 1, 4, 120, 0)
    memory = {0x5000: struct.pack('<QQQ', 0x6000, 0x6000 + len(records), 0x6000 + 64), 0x6000: records,
              0x7000: struct.pack('<QQQ', 0x8000, 0x8000, 0x8000)}
    rows = [{'events_pointer': 0x5000}, {'events_pointer': 0}, {'events_pointer': 0x7000}]
    out = ma.goal_events(_FakeEngine(memory), rows)
    assert out[1] == ('absent', [])
    assert out[2] == ('empty', [])
    state, events = out[0]
    assert state == 'present'
    assert [(e['person_idx'], e['second_person_idx'], e['side'], e['kind'], e['minute']) for e in events] == [
        (101, 202, 0, 0, 12), (303, -1, 1, 4, 120)]


def test_event_kind_labels_say_inferred():
    assert set(ma.EVENT_KINDS) == {0, 1, 2, 3, 4, 5}
    assert all('inferred' in label for label in ma.EVENT_KINDS.values())


def test_bind_frame_requires_key_and_teams():
    rows = [{'native_match_key': 7, 'home_team_idx': 1, 'away_team_idx': 2},
            {'native_match_key': 7, 'home_team_idx': 3, 'away_team_idx': 4}]
    by_key = ma.match_keys(rows)
    assert ma.bind_frame(rows, by_key, 7, {'teams': [3, 4]}) == 1
    assert ma.bind_frame(rows, by_key, 7, {'teams': [4, 3]}) is None
    assert ma.bind_frame(rows, by_key, 8, {'teams': [1, 2]}) is None


def test_competition_columns_use_game_labels_and_dedupe():
    labels = {code: None for code in range(1, 158)}
    labels.update({1: 'Appearances', 2: 'Goals', 40: 'Goals', 56: 'Minutes ', 13: 'Pass Completion (%)',
                   14: 'Tackles/90 Minutes', 27: 'Average Rating'})
    cols = mc.column_names(labels)
    names = {code: name for code, name, _ in cols}
    assert names[1] == 'appearances' and names[2] == 'goals' and names[56] == 'minutes'
    assert names[13] == 'pass_completion_pct' and names[14] == 'tackles_per_90_minutes'
    assert 40 not in names            # alias of code 2, never a column
    assert names[27] == 'average_rating'
    assert not set(mc.DIRECT) & set(mc.DERIVED)


def test_direct_plan_reads_row_fields():
    raw = bytearray(mc.ROW_BYTES)
    struct.pack_into('<II', raw, 0, 4242, 545)
    raw[10], raw[12] = 15, 9
    struct.pack_into('<h', raw, 52, 1309)
    struct.pack_into('<f', raw, 24, 7.5)
    raw = bytes(raw)
    assert mc.direct_value(raw, 1) == 15 and mc.direct_value(raw, 2) == 9
    assert mc.direct_value(raw, 56) == 1309
    assert abs(mc.direct_value(raw, 68) - 7.5) < 1e-6


def test_average_rating_zero_from_the_getter_is_null(monkeypatch):
    """The game's statistic getter returns 0 for average rating when it has no rating for the
    row (24,015 of 54,515 rows, every competition): stored NULL, not a rating of 0. Other
    derived zeros (starting appearances) stay 0."""
    labels = {code: None for code in range(1, 158)}
    labels.update({1: 'Appearances', 27: 'Average Rating', 45: 'Starting Appearances'})
    rows = []
    for person, rating in ((1, 0.0), (2, 6.75)):
        raw = bytearray(mc.ROW_BYTES)
        struct.pack_into('<II', raw, 0, person, 545)
        raw[10] = 3
        rows.append((7, 2030, 0x1000, 0x2000 + person, bytes(raw)))
    ratings = {0x2001: 0.0, 0x2002: 6.75}
    monkeypatch.setattr(mc, 'emulate', lambda engine, stats, row, code: ratings[row] if code == 27 else 0.0)
    monkeypatch.setattr(mc, 'verify_plans', lambda engine, picked: (set(mc.DIRECT), {}))
    got = mc.collect(object(), all_rows=rows, label_map=labels)
    by_person = {r['person_idx']: r for r in got['rows']}
    assert by_person[1]['average_rating'] is None and by_person[2]['average_rating'] == 6.75
    assert by_person[1]['starting_appearances'] == 0.0 and by_person[1]['appearances'] == 3


def _fixture_db():
    db = sqlite3.connect(':memory:')
    db.executescript("""
    CREATE TABLE team(idx INTEGER, name TEXT); CREATE TABLE competition(idx INTEGER, name TEXT);
    CREATE TABLE stadium(idx INTEGER, name TEXT);
    CREATE TABLE person(idx INTEGER, common_name TEXT, first_name TEXT, second_name TEXT);
    CREATE TABLE match(idx INTEGER, date TEXT, competition_idx INTEGER, home_team_idx INTEGER, away_team_idx INTEGER,
      stadium_idx INTEGER, referee_person_idx INTEGER, home_goals INTEGER, away_goals INTEGER, home_penalties INTEGER,
      away_penalties INTEGER, home_goals_half_time INTEGER, away_goals_half_time INTEGER, attendance INTEGER,
      detail_level TEXT, goal_events_state TEXT);
    CREATE TABLE match_event(match_idx INTEGER, source TEXT, seq INTEGER, kind INTEGER, kind_label TEXT, side INTEGER,
      person_idx INTEGER, second_person_idx INTEGER, minute INTEGER, added_minute INTEGER);
    CREATE TABLE match_team_stats(match_idx INTEGER, side INTEGER, shots INTEGER);
    CREATE TABLE match_player_stats(match_idx INTEGER, side INTEGER, person_idx INTEGER, slot INTEGER, started INTEGER,
      rating REAL);
    CREATE TABLE match_shot(match_idx INTEGER, side INTEGER, person_idx INTEGER, clock_raw INTEGER);
    CREATE TABLE match_pass(match_idx INTEGER, side INTEGER, person_idx INTEGER, completed INTEGER, outcome TEXT,
      won_by_person_idx INTEGER, displayed_minute INTEGER, second INTEGER, clock_raw INTEGER, end_state TEXT,
      origin_x REAL, origin_y REAL, end_x REAL, end_y REAL);
    INSERT INTO match_pass VALUES (10, 0, 2, 0, 'intercepted', 1, 8, 28, 500, 'linked_event_location', 0, 0, -11, -15),
                                  (10, 0, 2, 1, 'completed', NULL, 9, 2, 600, 'linked_event_location', 0, 0, 1, 1);
    INSERT INTO team VALUES (545, 'Newcastle United'), (29941, 'Newcastle United Under 21s'), (7, 'Sheffield United');
    INSERT INTO competition VALUES (7, 'Premier League'); INSERT INTO stadium VALUES (1, 'St. James'' Park');
    INSERT INTO person VALUES (1, '', 'Michael', 'Salisbury'), (2, 'Luiz Henrique', '', '');
    INSERT INTO match VALUES (10, '2030-12-07', 7, 545, 7, 1, 1, 0, 0, NULL, NULL, 0, 0, 52015, 'full_events', 'absent'),
                             (11, '2030-12-07', 7, 29941, 7, 1, 1, 1, 0, NULL, NULL, 1, 0, 300, 'result', 'present'),
                             (9, '2030-11-30', 7, 545, 7, 1, 1, 1, 2, NULL, NULL, 1, 0, 52305, 'statistics', 'present');
    INSERT INTO match_event VALUES (9, 'result_vector', 0, 0, 'goal (inferred)', 0, 2, NULL, 30, 0);
    INSERT INTO match_team_stats VALUES (10, 0, 12), (10, 1, 5);
    INSERT INTO match_player_stats VALUES (10, 0, 2, 3, 1, 6.52);
    INSERT INTO match_shot VALUES (10, 0, 2, 100);
    """)

    def query(sql, params, max_rows):
        cur = db.execute(sql, params)
        return {'columns': [d[0] for d in cur.description], 'rows': cur.fetchmany(max_rows)}
    return query


def test_get_match_by_team_and_date_prefers_exact_name():
    query = _fixture_db()
    out = get_match(query, team='Newcastle United', date='2030-12-07')
    assert out['state'] == 'found'
    assert out['match']['idx'] == 10 and out['score'] == '0-0' and out['half_time'] == '0-0'
    assert out['match']['referee'] == 'Michael Salisbury' and out['match']['competition'] == 'Premier League'
    assert out['team_stats'][0]['team'] == 'Newcastle United' and out['team_stats'][0]['shots'] == 12
    assert out['players'][0]['person'] == 'Luiz Henrique' and len(out['shots']) == 1
    assert [(f['displayed_minute'], f['passer'], f['outcome'], f['won_by']) for f in out['failed_passes']] == [
        (8, 'Luiz Henrique', 'intercepted', 'Michael Salisbury')]
    assert {(r['outcome'], r['passes']) for r in out['pass_outcomes']} == {('intercepted', 1), ('completed', 1)}


def test_get_match_team_alone_gives_latest_and_substring_fallback():
    query = _fixture_db()
    assert get_match(query, team='Newcastle United')['match']['idx'] == 10
    out = get_match(query, team='Newcastle', date='2030-12-07')
    assert out['state'] == 'ambiguous' and {c['idx'] for c in out['candidates']} == {10, 11}
    assert get_match(query, match_idx=9)['goals'][0]['person'] == 'Luiz Henrique'


def test_match_filter_accepts_a_team_idx():
    where, params = match_filter(team='545', opponent='591')
    assert where.count('m.home_team_idx = ?') == 2 and params == [545, 545, 591, 591]


def test_team_ids_chunk_candidates_and_prefer_the_users_club():
    """A partial name with thousands of candidate teams never builds a statement that grows with
    them (query.MAX_SQL), and of several substring matches the user's team is preferred."""
    from fm_live_mcp.fmdb import match_tool as mt
    from fm_live_mcp.fmdb.query import MAX_SQL
    db = sqlite3.connect(':memory:')
    db.executescript("""
        CREATE TABLE club(idx INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE team(idx INTEGER PRIMARY KEY, club_idx INTEGER, name TEXT);
        CREATE TABLE _managed(team_idx INTEGER, club_idx INTEGER, coach TEXT);
        INSERT INTO club VALUES (414, 'Newcastle United'), (7, 'Newcastle Jets');
        INSERT INTO team VALUES (545, 414, 'Newcastle United'), (546, 414, 'Newcastle United U21'),
                                (9, 7, 'Newcastle Jets');
        INSERT INTO _managed VALUES (545, 414, 'Coach');
    """)
    db.executemany('INSERT INTO team VALUES (?, NULL, ?)', [(10_000 + i, f'Nation {i}') for i in range(5000)])
    seen = []

    def sq(sql, params):
        assert len(sql) <= MAX_SQL
        seen.append(sql)
        cur = db.execute(sql, params)
        return {'columns': [d[0] for d in cur.description], 'rows': cur.fetchall()}

    class Engine:
        pass
    index = {i: {'home_team_idx': 10_000 + i, 'away_team_idx': 545, 'date': '2030-01-01'} for i in range(5000)}
    eng = Engine()
    assert mt._team_ids(eng, sq, index, 'Newcastle', True) == set()          # names the 5,000 clubless teams
    assert mt._team_ids(eng, sq, index, 'Newcastle', False) == {545}         # the user's team
    assert mt._team_ids(eng, sq, index, 'Jets', False) == {9}
    assert mt._team_ids(eng, sq, index, 'Newcastle United U21', True) == {546}
    assert mt._team_ids(eng, sq, index, '591', True) == {591}
    assert max(len(s) for s in seen) < 10_000


def test_get_match_reports_unbuilt_snapshot():
    out = get_match(lambda sql, params, n: {'state': 'building'}, team='Newcastle United')
    assert out['state'] == 'snapshot_not_ready'


def test_match_filter_needs_a_selector():
    try:
        match_filter()
    except ValueError:
        pass
    else:
        raise AssertionError('expected ValueError')


def _cbe(cat, side, slot, clock, *, second_slot=0xFF, offset=0, minute=0, sec=0, xy=(0.0, 0.0), eid=0, flags=0):
    e = bytearray(56)
    struct.pack_into('<ff', e, 0x18, *xy)
    struct.pack_into('<H', e, 0x22, clock)
    e[0x24], e[0x25], e[0x26], e[0x27], e[0x28], e[0x29], e[0x2A] = offset, minute, sec, slot, side, second_slot, cat
    struct.pack_into('<I', e, 0x2C, eid)
    struct.pack_into('<H', e, 0x30, flags)
    return bytes(e)


def test_pass_decode_outcomes_winner_minute_and_path():
    from fm_live_mcp.fmdb import match_pass_decode as mpd
    events = b''.join([
        _cbe(7, 0, 3, 100, second_slot=5, offset=2, minute=7, sec=10, xy=(1, 1), eid=1),
        _cbe(52, 0, 5, 102, xy=(4, 4), eid=2),                       # receiver touch (unrelated to check)
        _cbe(8, 0, 5, 200, offset=3, minute=8, sec=28, xy=(0, 0), eid=3),
        _cbe(52, 1, 9, 203, xy=(-11, -15), eid=4),                  # opponent wins the ball
        _cbe(11, 1, 9, 300, offset=6, minute=9, xy=(2, 2), eid=5),
        _cbe(10, 0, 3, 400, minute=10, eid=6),
        _cbe(9, 0, 3, 500, minute=11, xy=(5, 5), eid=7),
        _cbe(25, 1, 4, 500, xy=(6, 6), eid=8),                      # opponent block, same time unit
        _cbe(8, 0, 3, 600, flags=8, eid=9),                         # mask 8: not a counted attempt
    ])
    paths = {0: [(1, 1), (3, 3), (4, 4)], 2: [(0, 0), (-5, -7), (-11, -15)], 4: [(2, 2), (20, 30), (40, 60)]}
    roster = {(0, 3): 300, (0, 5): 500, (1, 9): 900, (1, 4): 400}
    rows = {r['event_id']: r for r in mpd.decode(events, paths, roster)}
    assert set(rows) == {1, 3, 5, 6, 7}
    assert rows[1]['recipient_person_idx'] == 500 and rows[1]['end_state'] == 'linked_event_location'
    assert rows[3]['outcome'] == 'intercepted' and rows[3]['won_by_person_idx'] == 900
    assert rows[3]['recipient_person_idx'] is None and rows[3]['recipient_state'] == 'not_stored_by_game'
    assert (rows[3]['displayed_minute'], rows[3]['second']) == (9, 28)
    assert rows[3]['origin_x'] == 0 and rows[3]['end_state'] == 'linked_event_location'
    assert rows[5]['outcome'] == 'out_of_play' and rows[5]['end_state'] == 'outside_pitch_sample'
    assert rows[6]['outcome'] == 'not_completed_other' and rows[6]['won_by_person_idx'] is None
    assert rows[7]['outcome'] == 'blocked' and rows[7]['won_by_person_idx'] == 400
    players = [{'side_index': 0, 'stored_player_slot': 3, 'passes_attempted': 3, 'passes_completed': 1},
               {'side_index': 0, 'stored_player_slot': 5, 'passes_attempted': 1, 'passes_completed': 0},
               {'side_index': 1, 'stored_player_slot': 9, 'passes_attempted': 1, 'passes_completed': 0}]
    checks = mpd.reconcile(list(rows.values()), players)
    assert all(c['ok'] for c in checks)
    assert checks[0]['failed_by_type'] == {'not_completed_other': 1, 'blocked': 1}


def test_one_unreadable_frame_does_not_fail_the_bank(tmp_path, monkeypatch):
    """On 27.0.1 the newest of 4,605 archived frames failed zstd ("Data corruption detected") while
    the game was still writing it; the bulk reader raised and every match table became unavailable."""
    from fm_live_mcp import snapshot_catalog

    path = tmp_path / 'pks_0.obs'
    good, bad = bytes.fromhex('28b52ffd') + b'good', bytes.fromhex('28b52ffd') + b'bad!'
    path.write_bytes(good + bad)

    def fake(data, capacity):
        if data.endswith(b'bad!'):
            raise ValueError('Invalid or oversized compressed frame')
        return b'RAW'
    monkeypatch.setattr(snapshot_catalog, '_decompress', fake)
    bank = {'path': str(path), 'origin': 0, 'ordinal': 0, 'entries': [(1, 0, len(good)), (2, len(good), len(bad))]}
    assert list(ma.read_frames(bank)) == [(1, b'RAW'), (2, None)]
