"""Season statistics tables of the match lane (`sources/matches.py` lists them).

* `player_season_stats`: one row per PERSON_COMP_STATS row (competition, season, player). The
  counters are direct plans, two values (average rating, starting appearances) are emulated.
  A row is computed again only when its 172 stored bytes change (`row_digest`): a match day
  changes the rows of the players who played, nothing else.
* `player_season_rates`: the getter's 67 derived values (per 90, percentages, ratios), about
  7 ms of emulation a row (400 s for the save). The table holds a row for every current key;
  its values are computed only for the rows a statement reads, found by running the statement
  once against the keys with every rate column bound to a recorder (`statement_rows`), and
  memoised by `row_digest` until the row's stored bytes change. A statement that filters,
  sorts or aggregates on a rate column over the whole table reads every row and computes the
  whole save; one that names players or competitions computes those rows only.
"""
from __future__ import annotations

import sqlite3
import time

from . import match_compstats as mc
from .sources import Column, SourceTable, current_statement

RATES = 'player_season_rates'
DRY_RUN_S = 20.0                 # the recording run of a statement stops after this long
LAYOUT = 'season-v3'             # v3: average_rating is NULL where the game's getter returns 0 (no rating)


def _state(engine):
    """Per-process memo of the competition rows: (fixture fingerprint, rows read)."""
    return engine.__dict__.setdefault('_fmdb_season_rows', {})


def current_rows(engine, fingerprint):
    """`match_compstats.rows` of every competition, reused while the fixture fingerprint is
    unchanged (the rows change only when matches are played)."""
    memo = _state(engine)
    try:
        fp = fingerprint()
    except Exception:  # noqa: BLE001
        fp = None
    if fp is not None and memo.get('fp') == fp:
        return memo['rows']
    got = mc.rows(engine, mc.stats_objects(engine))
    memo.update(fp=fp, rows=got)
    return got


# Declared inputs of the rates (tracked reads of the getter on 40 rows x 72 codes, 12 Nov 2026):
# the row's 172 bytes, two words of the competition's GAME_COMP_STATS (+0x7B8, +0x808), constant
# image words, 8 heap words shared by every row, and about 12 heap words specific to each row that
# no row byte locates (not identified; they are assumed to change only with the row, i.e. when
# the player plays in the competition). The digest covers the row and the two competition words.
COMPETITION_WORDS = (0x7B8, 0x808)


def competition_words(engine, fingerprint, raw_rows):
    memo = _state(engine)
    fp = memo.get('fp')
    if fp is None or memo.get('words_fp') != fp or 'words' not in memo:
        stats = sorted({r[2] for r in raw_rows})
        reqs = [(s + o, 8) for s in stats for o in COMPETITION_WORDS]
        got = engine.read_many(reqs)
        words = {}
        for n, s in enumerate(stats):
            words[s] = b''.join(x or b'' for x in got[n * len(COMPETITION_WORDS):(n + 1) * len(COMPETITION_WORDS)])
        memo.update(words=words, words_fp=fp)
    return memo['words']


def labels(engine):
    memo = _state(engine)
    if 'labels' not in memo:
        memo['labels'] = mc.labels(engine)
    return memo['labels']


KEY_COLUMNS = [Column('competition_idx', 'INTEGER', 'competition', references='competition'),
               Column('season', 'INTEGER', 'runtime season of the competition statistics (+0x3B0)'),
               Column('person_idx', 'INTEGER', 'player', references='person'),
               Column('team_idx', 'INTEGER', 'last team the counters were credited to', references='team')]
DIGEST = Column('row_digest', 'TEXT', 'content check of the stored statistics row (172 bytes); no game meaning')


def _column(code, name, label):
    how = (f'direct plan {mc.DIRECT[code]} checked against the getter' if code in mc.DIRECT
           else 'emulated getter 0xF314B4')
    if code in mc.NO_VALUE_ZERO:
        how += '; NULL where the getter returns 0 (the game has no rating for the row)'
    return Column(name, 'REAL', f"{label} (game label; stat code {code}; {how})")


def _values(row, cols):
    return (row['competition_idx'], row['season'], row['person_idx'], row['team_idx'],
            *(row.get(name) for _, name, _ in cols))


# --------------------------------------------------------------------------- player_season_stats
def stats_rows(engine, fingerprint, skip=frozenset()):
    """Rows whose (competition, season, person, digest) is not in `skip`."""
    got = mc.collect(engine, all_rows=current_rows(engine, fingerprint), label_map=labels(engine),
                     want=(lambda c, s, p, d: (c, s, p, d) not in skip) if skip else None)
    for r in got['rows']:
        yield _values(r, got['columns']) + (r['row_digest'],)


# --------------------------------------------------------------------------- player_season_rates
def statement_rows(statement, keys, rate_names, engine=None):
    """Indexes into `keys` [(competition, season, person, team, digest)] of the rows the statement
    reads a rate column of: the statement runs once on a read-only connection where
    player_season_rates is a TEMP view of the keys and every rate column records its row. None
    when the statement cannot be run that way (then nothing is computed).

    With an `engine` the statement is first run once with the on-demand session attached and
    nothing recorded, so the columns the game computes that the statement filters on are stored
    before the recording run reads them (see `sources.dry_run_connection`)."""
    from .sources import dry_run_connection
    sql, params, path = statement
    if not sql or not path:
        return None

    def run(conn, record):
        conn.execute('CREATE TEMP TABLE _season_rate_keys(idx INTEGER PRIMARY KEY, competition_idx INTEGER, '
                     'season INTEGER, person_idx INTEGER, team_idx INTEGER, row_digest TEXT)')
        conn.executemany('INSERT INTO _season_rate_keys VALUES (?, ?, ?, ?, ?, ?)',
                         [(i, *k) for i, k in enumerate(keys)])
        conn.create_function('fm_season_need', 1, record, deterministic=False)
        cols = ', '.join(f'fm_season_need(idx) AS "{n}"' for n in rate_names)
        conn.execute(f'CREATE TEMP VIEW {RATES} AS SELECT idx, competition_idx, season, person_idx, team_idx, '
                     f"{cols}, row_digest, 'not_computed' AS rates_state FROM _season_rate_keys")
        deadline = time.time() + DRY_RUN_S
        conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10000)
        cur = conn.execute(sql, params or [])
        while cur.fetchmany(5000):
            pass

    if engine is not None:
        try:
            conn, close = dry_run_connection(engine, statement)
            try:
                run(conn, lambda i: None)
            except sqlite3.Error:
                pass
            finally:
                close()
        except sqlite3.Error:
            pass
    need = set()

    def record(i):
        need.add(i)
        return None

    try:
        conn, close = dry_run_connection(None, statement)
    except sqlite3.Error:
        return None
    try:
        run(conn, record)
        return need
    except sqlite3.Error:
        return None
    finally:
        close()


def rates_rows(engine, fingerprint, existing=frozenset(), statement=None):
    """Rows of player_season_rates to add: every current key whose digest is not stored (values
    NULL, `rates_state` not_computed) and every row the statement reads that is not stored
    computed (values emulated, `rates_state` computed)."""
    raw_rows = current_rows(engine, fingerprint)
    label_map = labels(engine)
    _, rate_cols = mc.split_columns(mc.column_names(label_map))
    words = competition_words(engine, fingerprint, raw_rows)
    keys = []
    for comp, season, stats, address, raw in raw_rows:
        k = mc.row_key(comp, season, raw)
        keys.append((*k, mc.row_digest(raw + words.get(stats, b''))))
    stored = {}
    for comp, season, person, digest, state in existing:
        if stored.get((comp, season, person, digest)) != 'computed':
            stored[(comp, season, person, digest)] = state
    statement = statement if statement is not None else current_statement()
    need = statement_rows(statement, keys, [n for _, n, _ in rate_cols], engine=engine) if statement else None
    need = need or set()
    compute = {i for i in need if stored.get((keys[i][0], keys[i][1], keys[i][2], keys[i][4])) != 'computed'}
    out = []
    if compute:
        wanted = {(keys[i][0], keys[i][1], keys[i][2]): keys[i][4] for i in compute}
        got = mc.collect(engine, include_rates=True, include_core=False, all_rows=raw_rows, label_map=label_map,
                         want=lambda c, s, p, d: (c, s, p) in wanted)
        for r in got['rows']:
            digest = wanted[(r['competition_idx'], r['season'], r['person_idx'])]
            out.append(_values(r, rate_cols) + (digest, 'computed'))
    nulls = (None,) * len(rate_cols)
    for i, (comp, season, person, team, digest) in enumerate(keys):
        if i in compute or (comp, season, person, digest) in stored:
            continue
        out.append((comp, season, person, team, *nulls, digest, 'not_computed'))
    return out


def tables(engine, fingerprint):
    columns = mc.column_names(labels(engine))
    core_cols, rate_cols = mc.split_columns(columns)
    public = {'scope': 'public'}

    def gate(fn):
        from .sources.matches import gated
        return gated(engine, 'player_season_stats', fingerprint, fn)

    stats = SourceTable(
        'player_season_stats', "Per player, competition and season: every statistic of the game's competition "
        'statistics screens (GAME_COMP_STATS), labels from the game',
        KEY_COLUMNS + [_column(*c) for c in core_cols] + [DIGEST], lambda: stats_rows(engine, fingerprint),
        cost_note='first build about 15 s (2 emulated getter calls a row); a match day recomputes only the '
                  'rows whose stored bytes changed',
        source_note=mc.__doc__.split('\n')[0], indexes=('person_idx', 'competition_idx', 'team_idx'),
        manager=public, invalidation='append', identity=('competition_idx', 'season', 'person_idx', 'row_digest'),
        replace_key=('competition_idx', 'season', 'person_idx'), layout=LAYOUT,
        new_rows=gate(lambda existing: stats_rows(engine, fingerprint, skip=frozenset(existing))))
    rates = SourceTable(
        RATES, 'Derived competition statistics (per 90, percentages, ratios) from the game\'s getter, per player, '
        'competition and season; values are computed for the rows a statement reads (rates_state)',
        KEY_COLUMNS + [_column(*c) for c in rate_cols] + [
            DIGEST, Column('rates_state', 'TEXT', 'computed | not_computed (no statement has read the row since its '
                           'stored bytes last changed; name the row to have it computed)')],
        lambda: rates_rows(engine, fingerprint),
        cost_note='67 emulated getter calls a row (about 7 ms), only for the rows a statement reads',
        source_note='emulated 0xF314B4', indexes=('person_idx', 'competition_idx'), manager=public,
        invalidation='append', identity=('competition_idx', 'season', 'person_idx', 'row_digest', 'rates_state'),
        replace_key=('competition_idx', 'season', 'person_idx'), layout=LAYOUT, check_interval=0.0,
        new_rows=lambda existing: rates_rows(engine, fingerprint, existing))
    return [stats, rates]
