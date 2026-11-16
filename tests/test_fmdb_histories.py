"""Offline tests of the history tables: statement narrowing and row shaping (no game needed)."""
import sqlite3

import pytest

from fm_live_mcp.fmdb import history_read as H
from fm_live_mcp.fmdb.sources import histories as S
from fm_live_mcp.fmdb.variant import RecordRef, SiDate
from fm_live_mcp.fmdb.vm import Unavailable


@pytest.fixture()
def snapshot(tmp_path):
    path = tmp_path / 'snap.sqlite'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE person(idx INTEGER PRIMARY KEY, club_idx INTEGER, name TEXT)')
    conn.executemany('INSERT INTO person VALUES (?, ?, ?)', [(i, 545 if i % 100 == 0 else 7, f'p{i}')
                                                              for i in range(5000)])
    conn.execute('CREATE INDEX ix_person_club ON person(club_idx)')
    conn.execute('CREATE TABLE club(idx INTEGER PRIMARY KEY, name TEXT)')
    conn.executemany('INSERT INTO club VALUES (?, ?)', [(i, f'c{i}') for i in range(600)])
    conn.commit()
    conn.close()
    return str(path)


def keys(path, sql, table='person_playing_history', key='person_idx', cands=S.PEOPLE_SQL):
    return S.statement_keys((sql, None, path), table, key, ['year', 'apps', 'goals', 'read_date'], cands)


def test_named_people_only(snapshot):
    assert keys(snapshot, 'SELECT * FROM person_playing_history WHERE person_idx = 13') == {13}
    assert keys(snapshot, 'SELECT year FROM person_playing_history WHERE person_idx IN (1, 2, 3)') == {1, 2, 3}
    assert keys(snapshot, 'SELECT count(*) FROM person_playing_history WHERE person_idx = 9') == {9}


def test_join_through_person_filter(snapshot):
    got = keys(snapshot, 'SELECT h.apps FROM person_playing_history h JOIN person p ON p.idx = h.person_idx '
                         'WHERE p.club_idx = 545')
    assert got == {i for i in range(0, 5000, 100)}
    got = keys(snapshot, 'SELECT count(*) FROM person_playing_history WHERE person_idx IN '
                         '(SELECT idx FROM person WHERE club_idx = 545)')
    assert got == {i for i in range(0, 5000, 100)}


def test_unrestricted_statements_visit_everyone(snapshot):
    assert len(keys(snapshot, 'SELECT * FROM person_playing_history')) > S.MAX_KEYS
    assert len(keys(snapshot, 'SELECT count(*) FROM person_playing_history')) > S.MAX_KEYS
    assert len(keys(snapshot, 'SELECT * FROM person_playing_history WHERE year = 2020')) > S.MAX_KEYS


def test_clubs(snapshot):
    assert keys(snapshot, 'SELECT * FROM club_league_history WHERE club_idx = 414', 'club_league_history',
                'club_idx', S.CLUBS_SQL) == {414}


def test_no_statement():
    assert S.statement_keys(None, 't', 'person_idx', ['a'], S.PEOPLE_SQL) is None


def test_playing_history_rows():
    items = [{'year': 2022, 'yror': 1, 'clid': RecordRef('Ttea', 650, 650), 'onln': False, 'trib': False,
              'ytht': False, 'apps': 16, 'gols': 3, 'cash': 40000000, 'divi': RecordRef('comp', 11, 11),
              'info': None, 'hsfl': 0, 'join': SiDate('1900-01-01'), 'leav': SiDate('2023-01-29')}]
    rows = H.playing_history_rows(5, items, lambda r: r.unique_id + 1000, lambda r: r.unique_id)
    assert rows == [(5, 0, 2022, 1, 1650, 11, None, '2023-01-29', 0, 0, 16, 3, 40000000, 0, 0)]


def test_spell_and_injury_rows():
    spells = [{'PcSd': {'date': '2026-06-23', 'low': 21}, 'Pced': None, 'Yfxf': '2026-',
               'b9r7': {'QKws': 1, '17 !': 'Player'}, 'Team': {'110 ': 28, 'dref': 0x18000221}}]
    assert H.spell_rows(7, spells) == [(7, 0, 545, '2026-06-23', None, 1, 'Player', '2026-')]
    shown = [{'inDa': '2023-03-04', 'inDe': 'A knock', 'inDu': '3 weeks', 'zslN': 22, 'inrh': 2, 'inCa': 0,
              'inTr': 0}, {'inDa': '2024-01-01', 'inDe': 'A virus', 'inDu': '8 days', 'zslN': 8}]
    raw = [{'injr': {'dref': 0x600000B}, 'iida': '2023-03-04', 'iRec': 0, 'iCur': False},
           {'injr': {'dref': 0x6000002}, 'iida': '2024-01-02'}]
    rows = H.injury_rows(7, shown, raw)
    assert rows[0][:4] == (7, 0, '2023-03-04', 11) and rows[0][-2:] == (0, 0)
    assert rows[1][3] is None                       # dates disagree: no injury reference


def test_league_history_rows():
    value = [[{'comp': {'dref': 0x19000207}, 'ODJi': 0, 'year': 2030, 'ntms': 20, 'Q0uf': 1, 'dEkT': 2.5,
               'fate': 0, 'wtom': '29/30', 'lYlr': 'PL', '5ot ': 'Premier League'}]]
    assert H.league_history_rows(414, value) == [(414, 0, 0, 2030, '29/30', 519, 'Premier League', 'PL', 0, 20, 1,
                                                  0, 2.5)]


def test_plain_and_dates():
    assert H.plain(Unavailable('x')) is None and H.plain(True) == 1
    assert H.iso(SiDate('1900-01-01')) is None and H.iso({'date': '2026-06-23', 'low': 21}) == '2026-06-23'
    assert H.ui_index({'dref': 0x18000221}, H.UI_TEAM) == 545 and H.ui_index({'dref': 0x18000221}, 1) is None


def test_season_statistics_keys_and_columns():
    from fm_live_mcp.fmdb import history_season as HS
    cols = [c for c, _, _ in HS.column_specs()]
    assert len(cols) == len(set(cols)) == len(HS.KEYS)
    assert {'appearances', 'goals', 'average_rating', 'starts'} <= set(cols)
    table = next(t for t in S.tables(object()) if t.name == 'person_season_statistics')
    names = [c.name for c in table.columns]
    assert len(names) == len(set(names)) and names[:3] == ['person_idx', 'entry', 'career_row']
    assert HS.SCOPE_NAMES[5] == 'Overall (Club)' and len(HS.SCOPE_NAMES) == HS.SCOPES


def test_season_statistics_unset_bytes_are_null():
    from fm_live_mcp.fmdb import history_season as HS
    entries = [0] * 83
    entries[0], entries[1], entries[3], entries[4] = 16, 0, 3, HS.UNSET_BYTE
    row = {'ovAp': 16, 'ovGo': 3, 'OaAs': 255, 'ovAR': float('nan'), 'Cqja': False}
    assert HS._value('ovAp', row, entries) == 16
    assert HS._value('OaAs', row, entries) is None              # 0xFF byte: unset (0xF75588 reads -1)
    assert HS._value('ovAR', row, entries) is None              # NaN: nothing to divide by
    assert HS._value('Cqja', row, entries) == 0
    assert HS.keep({'scope': 5, 'values': {'ovAp': 0}})
    assert not HS.keep({'scope': 2, 'values': {'ovAp': 0}})
    assert not HS.keep({'scope': 2, 'values': {'ovAp': None}})
    assert HS.keep({'scope': 0, 'values': {'ovAp': 6}})


def test_competition_and_award_history_rows():
    team = lambda i: {'110 ': 28, 'dref': H.UI_TEAM << 24 | i}           # noqa: E731
    comp = H.competition_history_rows(7, [{'year': '2029/30', 'stgn': '', 'mshs': '', '1pla': team(545),
                                           '2pla': team(289), '3pla': team(460), '9H95': {'110 ': 0},
                                           'pown': {'110 ': 0}, 'HstN': '', 'HstS': ''}])
    assert comp == [(7, 0, '2029/30', None, 545, 289, 460, None, None, None, None)]
    person = {'110 ': 28, 'dref': H.UI_PERSON << 24 | 13009}
    winner = {'pers': person, 'Team': team(545), 'stvl': {'ptvl': '7.7', 'qvJ6': 'Avg. Rating'}, '15  ': 31,
              'ovAp': 53, 'ovGo': None, 'ovAR': 7.7}
    award = H.award_history_rows(0, [{'Strn': '2029-2030', '5nfy': 2, 'fIoV': winner, 'qRMU': [winner, winner]},
                                     {'Strn': '2028-2029', '5nfy': 1, 'fIoV': winner, 'qRMU': []}])
    assert [(r[1], r[2], r[3], r[5], r[6], r[7]) for r in award] == [
        (0, 0, '2029-2030', 0, 13009, 545), (1, 0, '2029-2030', 1, 13009, 545), (2, 1, '2028-2029', 0, 13009, 545)]
    assert award[0][8:12] == ('7.7', 'Avg. Rating', 31, 53)


def test_club_transfer_rows():
    person = {'110 ': 28, 'dref': H.UI_PERSON << 24 | 33495}
    team = lambda i: {'110 ': 28, 'dref': H.UI_TEAM << 24 | i}           # noqa: E731
    got = H.club_transfer_rows(414, [(2025, 'in', [{'pers': person, '220 ': '£65M', 'TObt': team(545),
                                                     'TOst': team(1100), 'byts': '', 'slts': ''}], 215381000),
                                     (2025, 'out', [], 142016000)])
    assert got == [(414, 0, 2025, 'in', 33495, '£65M', 545, 1100, None, 215381000)]
    free = H.club_transfer_rows(414, [(2029, 'in', [{'pers': person, '220 ': 'Free', 'TObt': team(545),
                                                      'slts': 'Free Transfer'}], 1)])
    assert free == [(414, 0, 2029, 'in', 33495, 'Free', 545, None, 'Free Transfer', 1)]


class _DatedEngine:
    def game_date(self):
        return '2031-01-18'


def _club_table(engine, read_batch):
    return S._Table(engine, 'club_transfer_history', 'd', 'club_idx', 'club',
                    [S._c('club_idx', 'INTEGER', 'club'), S.ENTRY, S._c('year', 'INTEGER', 'season')],
                    read_batch, 'note', S.CLUBS_SQL, S.NARROW_CLUB)


def test_a_failed_read_is_named_and_read_again(monkeypatch):
    """A club the game did not answer gets no rows, no read mark and a reason in the answer; a club
    that was read and has no transfers is marked and not read again on the same game date."""
    refusal = 'PTin 2025: data key Cpts: external call _pthread_condattr_init'
    answers, asked = {1: 'rows', 2: 'failed', 3: 'empty'}, []

    def read_batch(keys):
        asked.append(list(keys))
        rows, failed = [], []
        for k in keys:
            if answers[k] == 'rows':
                rows.append((k, 0, 2025))
            elif answers[k] == 'failed':
                rows.append((k, 0, 2030))                # a season that was read before the failing one
                failed.append((k, refusal))
        return rows, failed

    engine = _DatedEngine()
    table = _club_table(engine, read_batch)
    monkeypatch.setattr(S, 'current_statement', lambda: ('sql', None, 'path'))
    monkeypatch.setattr(S, 'statement_keys', lambda *args, **kwargs: {1, 2, 3})
    assert table.compute() == [(1, 0, 2025, '2031-01-18')]          # no row of the club that failed
    assert table.not_read() == [f'club 2: {refusal}']
    assert f'unavailable: 2: {refusal}' in table.coverage()
    assert S._read_marks(engine) == {('club_transfer_history', 3): '2031-01-18'}
    # the next statement: club 1 is stored, club 3 is marked as read, club 2 is read again and answers
    answers[2] = 'rows'
    assert table.compute(existing={(1, 0, '2031-01-18')}) == [(2, 0, 2025, '2031-01-18')]
    assert asked == [[1, 2, 3], [2]]
    assert table.not_read() == [] and table.source_table().not_read() == []


def test_a_club_whose_read_moved_under_it_is_read_once_more_on_a_fresh_copy(monkeypatch):
    from types import SimpleNamespace
    readers, answers = [], {
        1: [Unavailable('PTin 2027: data key Cpts: write to shipped code'), [(2030, 'in', [], 5)]],
        2: [Unavailable('PTin 2026: data key Cpts: game file changed while it was read'),
            Unavailable('PTin 2026: data key Cpts: unreadable live memory')],
        3: [Unavailable('PTin 2025: data key Cpts: external call _pthread_condattr_init')],
    }

    class Reader:
        def __init__(self, engine):
            readers.append(self)
            self.closed = False

        def close(self):
            self.closed = True

    monkeypatch.setattr(H, 'UiReader', Reader)
    monkeypatch.setattr(H, 'club_transfers', lambda reader, club: answers[club].pop(0))
    monkeypatch.setattr(H, 'club_transfer_rows', lambda club, seasons: [(club, 0, seasons[0][0])])
    monkeypatch.setattr(S.C, 'live', lambda engine, kind: SimpleNamespace(pointers=[1] * 8))
    rows, failed = S._transfer_batch(object())([1, 2, 3])
    assert rows == [(1, 0, 2030)]                                    # answered on the second copy
    assert failed == [(2, 'PTin 2026: data key Cpts: unreadable live memory'),      # moved twice: reported
                      (3, 'PTin 2025: data key Cpts: external call _pthread_condattr_init')]   # not retried
    assert len(readers) == 3 and all(r.closed for r in readers) and not any(answers.values())


def test_many_failed_reads_are_counted(monkeypatch):
    table = _club_table(_DatedEngine(), lambda keys: ([], [(k, 'no answer') for k in keys]))
    monkeypatch.setattr(S, 'current_statement', lambda: ('sql', None, 'path'))
    monkeypatch.setattr(S, 'statement_keys', lambda *args, **kwargs: set(range(8)))
    assert table.compute() == []
    lines = table.not_read()
    assert lines[:2] == ['club 0: no answer', 'club 1: no answer'] and len(lines) == S.NOT_READ_SHOWN + 1
    assert lines[-1] == 'and 3 more club(s)'


@pytest.mark.slow
@pytest.mark.parametrize('build, initialiser, pool, guard', [
    ('27.0.0.2493426', 0x184AA38, 0x56B4E70, 0x56B4FB0), ('27.0.1.2503222', 0x18554F4, 0x5750E70, 0x5750FB0)])
def test_the_past_trade_pool_is_built_inside_the_vm(build, initialiser, pool, guard):
    """A past transfer with a trade part is read into the game's PAST_TRADE pool, a function-local
    static that a game process builds on first use. Where the running game has not built it, the
    season read of club_transfer_history builds it inside the VM: the pool's constructor sets up a
    mutex and a condition variable (pthread_condattr_init, which the VM refused until 14 November
    2026: every club's 2025 season, and with it the whole table, was unavailable). On the plugin file
    alone, as in a game that has not built the pool, the initialiser runs to its end on both builds."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_function_match import BUILDS, _static_vm
    path = BUILDS / build / 'game_plugin'
    if not path.is_file():
        pytest.skip(f'{path} is not preserved here')
    vm, base = _static_vm(path)
    assert vm.read(base + guard, 1) == b'\0'
    result, stats = vm.call(base + initialiser, ())
    assert result == base + pool and vm.read(base + guard, 1) == b'\1'
    assert vm.read(vm.read_u64(base + pool), 11) == b'PAST_TRADE\0'
    assert {'_pthread_condattr_init', '_pthread_cond_init', '_pthread_condattr_destroy'} <= set(stats.externals)


def test_archive_inherited_file_position():
    import struct as st
    from fm_live_mcp.fmdb.sources import _archive_vm as AV

    class Fake:
        def __init__(self, flags, offset, r, ur=0):
            buf = bytearray(0x98)
            st.pack_into('<i', buf, AV.FILE_R, r)
            st.pack_into('<H', buf, AV.FILE_FLAGS_AT, flags)
            st.pack_into('<i', buf, AV.FILE_UR, ur)
            st.pack_into('<q', buf, AV.FILE_OFFSET, offset)
            self.buf = bytes(buf)

        def read(self, address, n):
            return self.buf[:n]

    assert AV.inherited_position(Fake(AV.SOFF | 4, 0x20000, 0x1000), 0) == 0x1F000   # _offset - _r
    assert AV.inherited_position(Fake(4, 0x20000, 0x1000), 0) is None                  # offset not valid
    assert AV.inherited_position(Fake(AV.SOFF, 0x20000, 0x10, ur=2), 0) is None        # ungetc data
