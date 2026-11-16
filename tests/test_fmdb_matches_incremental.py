"""Offline tests for the incremental match tables: the append contract additions (replace_key,
layout, check_interval, current_statement), the stable match idx, the selection of what is new,
frame binding, the fingerprint gate, the statement-scoped season rates and the live fm_get_match
shaping (docs/fmdb/MATCH.md)."""
from __future__ import annotations

import sqlite3
import struct
import sys
import types

import pytest

from fm_live_mcp.fmdb import match_season, match_tool, snapshot, sources
from fm_live_mcp.fmdb import match_archive as ma
from fm_live_mcp.fmdb.sources import Column, SourceTable
from fm_live_mcp.fmdb.sources import matches as M


class FakeEngine:
    def game_date(self):
        return '2030-12-13'


def _install(name, fn):
    mod = types.ModuleType(f'fm_live_mcp.fmdb.sources.{name}')
    mod.tables = fn
    sys.modules[mod.__name__] = mod


def _snapshot_file(path, modules, previous=None):
    conn = sqlite3.connect(path)
    snapshot.create_metadata(conn)
    conn.execute("INSERT INTO _snapshot VALUES ('s', 'k', '2030-12-13', 'now', 'b', 0, '[]')")
    summary = sources.build_in_snapshot(FakeEngine(), conn, only=modules, previous=previous, game_date='2030-12-13')
    conn.commit()
    conn.close()
    return summary


def _rows(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# --------------------------------------------------------------------------- contract additions
def test_replace_key_supersedes_a_row_whose_detail_rose(tmp_path, monkeypatch):
    store = {1: 'result', 2: 'statistics'}

    def rows():
        return [(k, v) for k, v in sorted(store.items())]

    def new_rows(existing):
        return [r for r in rows() if r not in existing]
    cols = [Column('idx', 'INTEGER', 'id'), Column('detail', 'TEXT', 'd')]
    _install('_supersede', lambda engine: [SourceTable('sup', 'd', cols, rows, invalidation='append',
                                                       identity=('idx', 'detail'), replace_key=('idx',),
                                                       new_rows=new_rows)])
    path = tmp_path / 'snapshot.sqlite'
    _snapshot_file(path, ['_supersede'])
    reads = {('sup', 'detail', None)}
    assert sources.refresh_for_query(FakeEngine(), path, reads)['sup']['built'] == 2
    monkeypatch.setattr(sources, 'CHECK_INTERVAL_S', 0.0)
    store[1] = 'full_events'
    store[3] = 'result'
    done = sources.refresh_for_query(FakeEngine(), path, reads)['sup']
    assert done['added'] == 2 and done['replaced'] == 1
    assert _rows(path, 'SELECT idx, detail FROM sup ORDER BY idx') == [(1, 'full_events'), (2, 'statistics'),
                                                                       (3, 'result')]


def test_layout_change_is_not_carried(tmp_path):
    layout = {'v': 'a'}
    cols = [Column('a', 'INTEGER', 'a')]
    _install('_layout', lambda engine: [SourceTable('lay', 'd', cols, lambda: [(1,)], invalidation='append',
                                                    identity=('a',), layout=layout['v'])])
    path = tmp_path / 'snapshot.sqlite'
    _snapshot_file(path, ['_layout'])
    sources.refresh_for_query(FakeEngine(), path, {('lay', 'a', None)})
    assert _snapshot_file(tmp_path / 'same.sqlite', ['_layout'], previous=path)['carried'] == ['lay']
    layout['v'] = 'b'
    assert _snapshot_file(tmp_path / 'next.sqlite', ['_layout'], previous=path)['lazy'] == ['lay']


def test_check_interval_zero_checks_every_reference_and_sees_the_statement(tmp_path):
    seen = []

    def new_rows(existing):
        seen.append(sources.current_statement())
        return []
    _install('_every', lambda engine: [SourceTable('every', 'd', [Column('a', 'INTEGER', 'a')], lambda: [],
                                                   invalidation='append', identity=('a',), new_rows=new_rows,
                                                   check_interval=0.0)])
    path = tmp_path / 'snapshot.sqlite'
    _snapshot_file(path, ['_every'])
    reads = {('every', 'a', None)}
    sources.refresh_for_query(FakeEngine(), path, reads)              # first reference: full build
    for n in range(2):
        sources.refresh_for_query(FakeEngine(), path, reads, statement=(f'SELECT {n}', [], str(path)))
    assert seen == [('SELECT 0', [], str(path)), ('SELECT 1', [], str(path))]
    assert sources.current_statement() is None


# --------------------------------------------------------------------------- match identity
def test_match_idx_is_date_and_home_team():
    i = M.match_idx('2030-12-10', 1361)
    assert i == 2030121001361 and M.idx_date(i) == '2030-12-10'
    assert M.match_idx('2030-12-10', None) == 2030121099999
    assert M.idx_floor('2030-12-10') < M.match_idx('2030-12-10', 0) + 1 <= i


def test_since_watermark_keeps_recent_unheld_matches():
    a, b, c = M.match_idx('2030-11-01', 1), M.match_idx('2030-12-01', 2), M.match_idx('2030-12-13', 3)
    assert M.since_watermark({a, b, c}, set()) == [a, b, c]
    assert M.since_watermark({a, b, c}, {M.match_idx('2030-12-05', 9)}) == [b, c]
    assert M.since_watermark({a, b, c}, {b, M.match_idx('2030-12-05', 9)}) == [c]


def test_new_match_rows_adds_new_and_raises_detail_only(monkeypatch):
    old, recent, new = (M.match_idx('2030-10-01', 1), M.match_idx('2030-12-11', 2), M.match_idx('2030-12-12', 3))
    detail = {old: 'result', recent: 'statistics', new: 'result_and_goals'}
    asked = []

    def fake_rows(col, idxs):
        asked.append(sorted(idxs))
        return [(i, detail[i]) for i in idxs]
    monkeypatch.setattr(M, 'match_rows', fake_rows)
    col = types.SimpleNamespace(index=lambda: dict.fromkeys(detail))
    # stored: old at a higher level (the game later discarded its frame), recent below its level now
    stored = {old: 'statistics', recent: 'result_and_goals'}
    out = M.new_match_rows(col, stored, '2030-12-13')
    assert asked == [[recent, new]]                       # the old match is not decoded again
    assert out == [(recent, 'statistics'), (new, 'result_and_goals')]
    stored = {old: 'result', recent: 'full_events', new: 'result_and_goals'}
    assert M.new_match_rows(col, stored, '2030-12-13') == []    # never lowered


def test_team_season_view_equals_the_old_python_aggregate():
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE match(idx, competition_idx, season_code, home_team_idx, away_team_idx, home_goals, '
               'away_goals)')
    rows = [(1, 7, 2030, 10, 11, 2, 1), (2, 7, 2030, 11, 10, 0, 0), (3, 7, 2030, 12, 10, 1, 3),
            (4, 7, 2030, 11, 12, None, None), (5, 8, 2029, 10, 12, 0, 1)]
    db.executemany('INSERT INTO match VALUES (?, ?, ?, ?, ?, ?, ?)', rows)
    got = db.execute(M.TEAM_SEASON_SQL).fetchall()
    acc = {}
    for _, comp, season, h, a, hg, ag in rows:
        if hg is None:
            continue
        for team, gf, ga, home in ((h, hg, ag, 1), (a, ag, hg, 0)):
            x = acc.setdefault((team, comp, season), [0] * 8)
            x[0] += 1
            x[1 if gf > ga else 2 if gf == ga else 3] += 1
            x[4] += gf
            x[5] += ga
            x[6 if home else 7] += 1
    want = [(t, c, s, x[0], x[1], x[2], x[3], x[4], x[5], x[4] - x[5], x[1] * 3 + x[2], x[6], x[7])
            for (t, c, s), x in sorted(acc.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][0]))]
    assert got == want


# --------------------------------------------------------------------------- frames
def _collector_with(index, frames, monkeypatch):
    col = M._Collector(FakeEngine())
    col._index = index
    col._banks = [{'ordinal': 0, 'path': 'x', 'origin': 0, 'segment_length': 0,
                   'entries': [(k, o, 10) for (k, o) in frames]}]
    decoded = []

    def fake_entries(bank_list, entries, level):
        for entry in entries:
            decoded.append((entry, level))
            teams, players = frames[(entry[1], entry[2])]
            yield entry, {'teams': teams, 'official_person_idx': 5}, ({'teams': []} if level != 'header' else None), \
                (players if level != 'header' else None), None
    monkeypatch.setattr(ma, 'decode_entries', fake_entries)
    return col, decoded


def test_frames_bind_by_key_and_teams_unique_over_every_result(monkeypatch):
    a, b, c = M.match_idx('2030-12-01', 1), M.match_idx('2029-12-01', 1), M.match_idx('2030-12-02', 3)
    index = {a: {'native_match_key': 7, 'home_team_idx': 1, 'away_team_idx': 2},
             b: {'native_match_key': 7, 'home_team_idx': 1, 'away_team_idx': 2},     # same key and teams: ambiguous
             c: {'native_match_key': 8, 'home_team_idx': 3, 'away_team_idx': 4}}
    frames = {(7, 0): ([1, 2], []), (8, 100): ([3, 4], [{'p': 1}])}
    col, decoded = _collector_with(index, frames, monkeypatch)
    assert col.frames([a], 'header') == {}                  # unique among the subset only: not bound
    got = col.frames([c], 'header')
    assert list(got) == [c] and got[c][4] is None
    assert [lvl for _, lvl in decoded] == ['header', 'header']
    deeper = col.frames([c], 'full')                        # decoded again, deeper, only for the bound match
    assert deeper[c][4] == [{'p': 1}] and decoded[-1] == ((0, 8, 100, 10), 'full')


def test_fingerprint_gate_skips_when_fixture_or_results_unchanged(monkeypatch):
    engine = FakeEngine()
    state = {'fixture': 'f1', 'result': 'r1', 'runs': 0}
    monkeypatch.setattr(M, 'collector', lambda e: types.SimpleNamespace(result_fingerprint=lambda: state['result']))

    def fn(existing):
        state['runs'] += 1
        return [('row',)]
    run = M.gated(engine, 't', lambda: state['fixture'], fn)
    assert run(set()) == [('row',)] and state['runs'] == 1
    assert run(set()) == [] and state['runs'] == 1           # nothing moved
    state['fixture'] = 'f2'                                  # a fixture record moved, no result was added
    assert run(set()) == [] and state['runs'] == 1
    state.update(fixture='f3', result='r2')                  # a match was played
    assert run(set()) == [('row',)] and state['runs'] == 2


# --------------------------------------------------------------------------- season rates
def _keys_db(tmp_path):
    path = tmp_path / 'snap.sqlite'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE person(idx INTEGER, name TEXT)')
    conn.executemany('INSERT INTO person VALUES (?, ?)', [(1, 'A'), (2, 'B'), (3, 'C')])
    conn.commit()
    conn.close()
    keys = [(7, 2030, 1, 10, 'd1'), (7, 2030, 2, 10, 'd2'), (8, 2030, 3, 11, 'd3')]
    return path, keys


def test_statement_rows_are_the_rows_a_statement_reads_a_rate_of(tmp_path):
    path, keys = _keys_db(tmp_path)
    names = ['goals_per_90', 'pass_pct']

    def rows_of(sql):
        return match_season.statement_rows((sql, [], str(path)), keys, names)
    assert rows_of('SELECT goals_per_90 FROM player_season_rates WHERE person_idx = 2') == {1}
    assert rows_of('SELECT r.pass_pct FROM player_season_rates r JOIN person p ON p.idx = r.person_idx '
                   "WHERE p.name = 'C'") == {2}
    assert rows_of('SELECT person_idx FROM player_season_rates ORDER BY goals_per_90 DESC LIMIT 1') == {0, 1, 2}
    assert rows_of('SELECT person_idx, competition_idx FROM player_season_rates') == set()
    assert match_season.statement_rows(('SELECT nonsense FROM', [], str(path)), keys, names) is None


def test_rates_rows_compute_once_per_digest(monkeypatch):
    raws = {1: b'\x01\x00\x00\x00\x0a\x00\x00\x00' + bytes(164), 2: b'\x02\x00\x00\x00\x0a\x00\x00\x00' + bytes(164)}
    monkeypatch.setattr(match_season, 'current_rows', lambda e, fp: [(7, 2030, 0, p, raws[p]) for p in sorted(raws)])
    monkeypatch.setattr(match_season, 'labels', lambda e: {13: 'Pass Completion (%)'})
    monkeypatch.setattr(match_season, 'competition_words', lambda e, fp, rows: {0: b'w'})
    computed = []

    def fake_collect(engine, **kw):
        out = []
        for comp, season, _, _, raw in kw['all_rows']:
            person = struct.unpack_from('<I', raw)[0]
            digest = match_season.mc.row_digest(raw)
            if kw['want'](comp, season, person, digest):
                computed.append(person)
                out.append({'competition_idx': comp, 'season': season, 'person_idx': person, 'team_idx': 10,
                            'row_digest': digest, 'pass_completion_pct': 50.0 + person})
        return {'rows': out}
    monkeypatch.setattr(match_season.mc, 'collect', fake_collect)
    monkeypatch.setattr(match_season, 'statement_rows', lambda st, keys, names, engine=None: {0})
    out = match_season.rates_rows(None, None, set(), statement=('S', [], 'p'))
    assert computed == [1]
    d1, d2 = (match_season.mc.row_digest(raws[1] + b'w'), match_season.mc.row_digest(raws[2] + b'w'))
    assert sorted(out) == [(7, 2030, 1, 10, 51.0, d1, 'computed'), (7, 2030, 2, 10, None, d2, 'not_computed')]
    existing = {(7, 2030, 1, d1, 'computed'), (7, 2030, 2, d2, 'not_computed')}
    assert match_season.rates_rows(None, None, existing, statement=('S', [], 'p')) == [] and computed == [1]
    raws[1] = raws[1][:20] + b'\x05' + raws[1][21:]           # player 1 played: his stored row changed
    out = match_season.rates_rows(None, None, existing, statement=('S', [], 'p'))
    assert computed == [1, 1] and out[0][-1] == 'computed' and out[0][-2] != d1


# --------------------------------------------------------------------------- live fm_get_match shaping
def test_live_shaping_uses_get_match_over_the_decoded_rows():
    tables = {t.name: t for t in M._tables(None) if t.name in match_tool.LIVE_TABLES}
    i = M.match_idx('2030-12-10', 1361)
    width = len(M.MATCH_COLUMNS)
    m = [None] * width
    m[:9] = [i, '2030-12-10', '20:00', 7, 2030, 3, 1361, 545, 4]
    m[9:11] = [0, 2]
    m[19:21] = [0, 1]
    m[23], m[24], m[25], m[26] = 99, 5, 'present', 'statistics'
    rows = {'match': [tuple(m)],
            'match_event': [(i, 'result_vector', 0, 0, 'goal (inferred)', 1, 2, None, 30, 0)],
            'match_team_stats': [(i, 0, 1361, 9, 3, 1.1, 400, 300, 5, 10, 2, 1000, 45),
                                 (i, 1, 545, 12, 6, 2.0, 500, 420, 6, 12, 4, 1200, 55)]}
    names = {('team', 1361): 'Villarreal C.F.', ('team', 545): 'Newcastle United', ('competition', 7): 'UCL',
             ('stadium', 4): 'La Ceramica', ('person', 99): 'Ref Eree', ('person', 2): 'Scorer'}
    out = match_tool.get_match(match_tool._memory_db(tables, rows, names), i)
    assert out['state'] == 'found' and out['score'] == '0-2' and out['half_time'] == '0-1'
    assert out['match']['home_team'] == 'Villarreal C.F.' and out['match']['referee'] == 'Ref Eree'
    assert out['goals'][0]['person'] == 'Scorer' and out['goals'][0]['team'] == 'Newcastle United'
    assert [t['team'] for t in out['team_stats']] == ['Villarreal C.F.', 'Newcastle United']
    assert out['coverage']['statistics'] == 'present'


def test_live_selection_orders_latest_first_and_filters():
    index = {M.match_idx('2030-12-10', 1): {'date': '2030-12-10', 'home_team_idx': 1, 'away_team_idx': 545},
             M.match_idx('2030-12-07', 545): {'date': '2030-12-07', 'home_team_idx': 545, 'away_team_idx': 7},
             M.match_idx('2030-12-07', 8): {'date': '2030-12-07', 'home_team_idx': 8, 'away_team_idx': 9}}
    got = match_tool._select(index, None, {545}, None, None)
    assert got == [M.match_idx('2030-12-10', 1), M.match_idx('2030-12-07', 545)]
    assert match_tool._select(index, None, {545}, '2030-12-07', None) == [M.match_idx('2030-12-07', 545)]
    assert match_tool._select(index, None, {545}, None, {7}) == [M.match_idx('2030-12-07', 545)]
    assert match_tool._select(index, M.match_idx('2030-12-07', 8), None, None, None) == [M.match_idx('2030-12-07', 8)]


def test_result_index_reads_keys_teams_and_vectors():
    rec = bytearray(ma.RECORD_BYTES)
    struct.pack_into('<QQ', rec, 8, 0x9000, 0xA000)
    struct.pack_into('<i', rec, 0x58, 77)
    struct.pack_into('<Q', rec, 0x78, 0xB000)
    memory = {0x5000: bytes(rec), 0x9000: struct.pack('<QII', 0, 545, 1001), 0xA000: struct.pack('<QII', 0, 7, 1002)}

    class E:
        def read_many(self, reqs):
            return [memory.get(a, b'')[:n] or None for a, n in reqs]
    got = ma.result_index(E(), [(2030, 344, 0, 1, 0x5000)])
    assert got == [{'address': 0x5000, 'year_bucket': 2030, 'day': 344, 'group': 0, 'slot': 1, 'date': '2030-12-10',
                    'native_match_key': 77, 'home_team_address': 0x9000, 'away_team_address': 0xA000,
                    'home_team_idx': 545, 'home_team_id': 1001, 'away_team_idx': 7, 'away_team_id': 1002,
                    'events_pointer': 0xB000}]


@pytest.mark.parametrize('level,parts', [('header', (True, False, False)), ('players', (True, False, True)),
                                         ('totals', (True, True, True))])
def test_decode_levels_stop_early(monkeypatch, level, parts):
    import fm_live_mcp.live_match_players as lmp
    import fm_live_mcp.live_match_team_totals as lmt
    monkeypatch.setattr(ma, 'decode_header', lambda raw: {'h': 1})
    monkeypatch.setattr(lmp, 'decode_retained_players', lambda raw, key: [{'raw_child_hex': ''}])
    monkeypatch.setattr(lmt, 'decode_team_totals', lambda raw: {'teams': []})
    header, totals, rows = ma.decode_frame(b'', 1, level)
    assert (header is not None, totals is not None, rows is not None) == parts
