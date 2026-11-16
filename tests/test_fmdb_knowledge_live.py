"""Live-gated checks of the knowledge store and manager view against the running game.

Skipped unless FM27 is attached (FM_LIVE_REGRESSION=0 skips too). Read-only against the game.
Databases go under `$FMCP_CACHE_DIR/fmdb/_tests/`, never the internal disk. Takes a minute or two
(the named population with stars, 50-player bulk captures on both engines).

* the 47 field/FourCC pairs on own-club players (PropertyVM values vs exact engine cells);
* tier 1 build: every seed player has a row, timings recorded;
* `m_player_view` attribute columns equal `visible_attributes_bulk` cells for 50 scouted players;
* the summary columns taken from the cells capture equal `player_knowledge_summary` (native=True);
* tier 1 has stars and Player Search admission for every player, equal to `perceived_ability`;
* `native=True` leaves no tier 1 row with every attribute unavailable;
* rows confirmed from their fingerprints in a new epoch equal a fresh capture by the first
  (helper round-trip) engine, and a statement computes knowledge only for the rows it reads.
"""
import os
import shutil
import sqlite3
import time

import pytest

from fm_live_mcp import bridge as bridge_module, knowledge_bulk as kb
from fm_live_mcp.fmdb import knowledge_codes as codes
from fm_live_mcp.fmdb import knowledge_store as ks
from fm_live_mcp.fmdb import manager_view as mv


@pytest.fixture(scope='module')
def live():
    if os.environ.get('FM_LIVE_REGRESSION') == '0':
        pytest.skip('FM_LIVE_REGRESSION=0')
    bridge = bridge_module.Bridge()
    if not bridge.helper.is_file():
        pytest.skip('native helper not built')
    try:
        session_id = bridge.attach()['session_id']
    except Exception as exc:   # no FM27 process, permission, or unsupported build
        pytest.skip(f'FM27 is not attached: {exc}')
    yield bridge, session_id
    bridge.detach()


@pytest.fixture(scope='module')
def built(live):
    # a directory of its own: other checkouts may run this test against the same cache at the same time
    root = ks.cache_root() / '_tests' / f'kview-{os.getpid()}-{int(time.time())}'
    root.mkdir(parents=True)
    store = ks.KnowledgeStore(root / ks.FILE_NAME)
    builder = ks.KnowledgeBuilder(live, store)
    for _ in range(3):
        try:
            cov = builder.tier1()
            break
        except ks.DayChanged:
            continue
    yield root, store, cov
    store.close()
    shutil.rmtree(root, ignore_errors=True)


def test_field_code_pairing(live):
    result = codes.verify_field_codes(live)
    assert result['players'] >= 11 and result['codes_tested'] == 106
    assert result['paired'] == 47 and result['unpaired'] == []
    assert result['codes_without_field'] == ['PCON', 'Pdir', 'Pimp', 'Pipr', 'Pver']


def test_tier1_build(built):
    _, store, cov = built
    assert cov['tier1_complete'] and cov['seed_players'] == cov['seed_players_covered'] > 1000
    assert cov['scouted_rows'] == cov['seed_players']
    assert store.con.execute('SELECT count(*) FROM knowledge_attribute').fetchone()[0] == 47 * cov['knowledge_rows']
    own = store.con.execute('SELECT count(*), sum(exact_n) FROM knowledge_player WHERE own_club = 1').fetchone()
    assert own[0] > 0 and own[1] == 47 * own[0]
    assert store.meta('timings')['ensure_last']['seconds'] > 0
    # every row came with its input fingerprint
    assert store.con.execute('SELECT count(*) FROM knowledge_input').fetchone()[0] == cov['knowledge_rows']


def _sample(store, n=50):
    seeds = store.con.execute('SELECT idx FROM knowledge_player WHERE scouted = 1 AND unavailable_n < 47 '
                              'ORDER BY idx').fetchall()
    step = max(1, len(seeds) // n)
    picks = [i for i, in seeds[::step]][:n - 2]
    own = [i for i, in store.con.execute('SELECT idx FROM knowledge_player WHERE own_club = 1 ORDER BY idx LIMIT 2')]
    return sorted(set(picks + own))


def _snapshot_for(root, store):
    """The real snapshot when the snapshot lane has written one for this save, else a minimal
    contract-shaped snapshot whose player_view lists the knowledge rows (attributes then come only
    from knowledge, which is what is being compared)."""
    ident = store.identity()
    real = ks.cache_root() / ident['save_key'] / 'snapshot.sqlite'
    if real.is_file():
        return real, True
    path = root / 'snapshot.sqlite'
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE player(idx INTEGER PRIMARY KEY, uid INTEGER, class TEXT)')
    con.execute('CREATE TABLE _fields(table_name, column_name, code, record_type, name, comment, type, '
                'enum_json, references_table, source, status, note)')
    con.execute('CREATE TABLE _snapshot(save_name, save_key, game_date, built_at, build, plans_verified, notes)')
    con.execute('INSERT INTO _snapshot(save_key, game_date) VALUES (?, ?)', (ident['save_key'], store.game_date()))
    con.executemany('INSERT INTO player(idx) VALUES (?)', store.con.execute('SELECT idx FROM knowledge_player'))
    con.execute('CREATE VIEW player_view AS SELECT idx, uid FROM player')
    con.commit()
    con.close()
    return path, False


def test_manager_view_equals_bulk_cells_for_50_scouted(live, built):
    root, store, _ = built
    sample = _sample(store)
    assert len(sample) >= 50
    snapshot, real = _snapshot_for(root, store)
    for _ in range(3):
        bulk = kb.visible_attributes_bulk(live, sample, native=True)
        if bulk['save']['current_date'] == store.game_date():
            break
        ks.KnowledgeBuilder(live, store).tier1()
    else:
        pytest.skip('game date kept changing')
    con = mv.open_manager_connection(snapshot, store.path)
    try:
        cols = dict(con.execute('SELECT field, column_name FROM m_attribute_columns').fetchall())
        marks = ','.join('?' * len(sample))
        cur = con.execute(f'SELECT * FROM m_player_view WHERE idx IN ({marks})', sample)
        names = [d[0] for d in cur.description]
        view = {r[names.index('idx')]: dict(zip(names, r)) for r in cur.fetchall()}
    finally:
        con.close()
    assert sorted(view) == sample
    equal = different = 0
    states = {}
    for player in bulk['players']:
        row = view[player['key']]
        for cell in player['fields']:
            c = cols[cell['name']]
            if cell['state'] == 'exact':
                want = (cell['value'], cell['value'], cell['value'])
            elif cell['state'] == 'range':
                want = (None, cell['minimum'], cell['maximum'])
            else:
                want = (None, None, None)
            got = (row[c], row[c + '_min'], row[c + '_max'])
            ok = got == want and row[c + '_state'] == cell['state']
            equal += ok
            different += not ok
            states[cell['state']] = states.get(cell['state'], 0) + 1
    print(f'\nm_player_view vs visible_attributes_bulk: {len(sample)} players, {equal} cells equal, '
          f'{different} different, states {states}, real snapshot: {real}')
    assert different == 0 and equal == 47 * len(sample)
    assert states.get('exact', 0) > 0 and states.get('range', 0) > 0


def test_summary_columns_equal_summary_capture(live, built):
    _, store, _ = built
    sample = _sample(store, 30)
    summary = kb.player_knowledge_summary(live, sample, native=True)
    if summary['save']['current_date'] != store.game_date():
        pytest.skip('game date changed')
    rows = {r[0]: r for r in store.con.execute(
        f'SELECT idx, k, node_score, report_score, own_club, h_score, ca_gate, pa_gate FROM knowledge_player '
        f'WHERE idx IN ({",".join("?" * len(sample))})', sample)}
    for p in summary['players']:
        idx, k, node, report, own, h, ca, pa = rows[p['key']]
        assert own == int(p['own_club_context'])
        assert (ca, pa) == (p['star_gates']['current_ability']['h_state'],
                            p['star_gates']['potential_ability']['h_state'])
        if not own:   # the cells capture skips K, node and report scores for own-club players
            assert (k, h, node, report) == (p['context_k'], p['h_score'], p['node_score'], p['report_score'])


def test_tier1_stars_search_and_native(live, built):
    from fm_live_mcp import knowledge_stars
    _, store, cov = built
    q = lambda sql: store.con.execute(sql).fetchall()
    assert store.identity()['native'] is True
    assert q('SELECT count(*) FROM knowledge_player WHERE unavailable_n = 47') == [(0,)]
    assert q("SELECT count(*) FROM knowledge_player WHERE ca_stars_state = 'not_computed' "
             "OR pa_stars_state = 'not_computed' OR in_player_search IS NULL") == [(0,)]
    own = q("SELECT count(*), sum(ca_stars_state IN ('exact', 'range')) FROM knowledge_player WHERE own_club = 1")
    # every player of the managed squad shows stars; other teams of the club (reserves, U21) may show
    # none, because the star code is run with the managed team as the viewer's team
    assert own[0][1] >= 29 and own[0][0] >= own[0][1]
    sample = _sample(store, 40)
    result = knowledge_stars.perceived_ability(live, sample)
    if result['save']['current_date'] != store.game_date():
        pytest.skip('game date changed')
    rows = {r[0]: r[1:] for r in q('SELECT idx, ca_stars_min, ca_stars_max, ca_stars_state, pa_stars_min, '
                                   'pa_stars_max, pa_stars_state FROM knowledge_player WHERE idx IN (%s)'
                                   % ','.join(map(str, sample)))}
    for p in result['players']:
        assert rows[p['key']] == ks._star_cells(p['current']) + ks._star_cells(p['potential'])


def _store_cells(store, sample):
    out = {}
    for idx, field, state, value, lo, hi in store.con.execute(
            f'SELECT idx, field, state, value, min, max FROM knowledge_attribute WHERE idx IN '
            f'({",".join("?" * len(sample))})', sample):
        out[(idx, field)] = (state, value, lo, hi)
    return out


def test_rows_confirmed_by_fingerprint_equal_a_fresh_capture_by_the_first_engine(live, built):
    """New epoch: the sample is confirmed (or re-evaluated) from stored fingerprints by the paged
    engine; the stored cells must equal what the helper round-trip engine computes now."""
    _, store, _ = built
    sample = _sample(store, 60)
    for _ in range(3):
        builder = ks.KnowledgeBuilder(live, store)
        builder.refresh_identity(new_epoch=True)
        assert store.lacking(sample) == sample
        result = builder.ensure(sample)
        fresh = kb._run(live, sample, kb.ALL_FIELDS, None, 'cells', None, native=True, engine='journal')
        if fresh['before']['save']['current_date'] == store.game_date() and store.lacking(sample) == []:
            break
    else:
        pytest.skip('game date kept changing')
    assert result['computed'] + result['confirmed'] == len(sample)
    cells = _store_cells(store, sample)
    equal = different = 0
    for subject in fresh['subjects']:
        row, _ = ks.player_row(subject)
        for f, cell in zip(codes.FIELDS, row['cells']):
            same = cells[(row['idx'], f['name'])] == (cell['state'], cell['value'], cell['min'], cell['max'])
            equal += same
            different += not same
    print(f'\nfingerprint-confirmed store vs fresh journal-engine capture: {len(sample)} players, '
          f'{result["confirmed"]} confirmed, {result["computed"]} re-evaluated, {equal} cells equal, '
          f'{different} different')
    assert different == 0 and equal == 47 * len(sample)


def test_statement_computes_only_the_rows_it_reads(live, built):
    root, store, _ = built
    snapshot, real = _snapshot_for(root, store)
    con = sqlite3.connect(snapshot)
    base = 'player_view'
    universe = [i for i, in store.con.execute('SELECT idx FROM knowledge_universe ORDER BY idx')] or \
        [i for i, in con.execute(f'SELECT idx FROM {base} ORDER BY idx')]
    con.close()
    builder = ks.KnowledgeBuilder(live, store)
    builder.refresh_identity(new_epoch=True)
    builder.ensure_universe()
    seeds = set(store.seeds())
    strangers = [i for i in store.universe() if i not in seeds][:40]
    if len(strangers) < 40:
        pytest.skip('snapshot holds no players outside the named population')
    marks = ','.join(map(str, strangers))
    before = store.con.execute('SELECT count(*) FROM knowledge_player').fetchone()[0]
    sql = f'SELECT idx, passing_min, passing_state, k FROM m_player_view WHERE idx IN ({marks}) ORDER BY idx'
    q = mv.prepare_manager_query((snapshot, store.path), sql, bridge_or_session=live)
    try:
        rows = q.connection.execute(sql).fetchall()
    finally:
        q.connection.close()
    present = [r[0] for r in rows]
    assert q.complete and set(present) <= set(strangers) and all(r[2] is not None for r in rows)
    after = store.con.execute('SELECT count(*) FROM knowledge_player').fetchone()[0]
    assert after - before <= len(strangers)                # nothing beyond what the statement read
    assert store.lacking(present) == []
    assert q.coverage['on_demand']['evaluated'] + q.coverage['on_demand']['confirmed'] >= len(present)
