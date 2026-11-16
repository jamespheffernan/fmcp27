"""Materialised manager knowledge (fog of war) for the fmdb snapshot, keyed by PERSON index.

`knowledge.sqlite` lives next to the snapshot at `<cache>/fmdb/<save key>/knowledge.sqlite` and
holds, for one save and one manager, what the manager knows about each player it was asked about:

* `knowledge_player`: one row per evaluated player (K, node/report scores, own-club flag, the
  winning sources of H's score, `scouted`, the CA/PA star-gate H states, cell counts, stars);
* `knowledge_attribute`: one row per (player, attribute field) in the engine's cell shape
  (`exact` value, `range` min/max, `unknown`, `unavailable`), with the editor FourCC;
* `knowledge_wide`: the same cells pivoted to one row per player, which the manager view joins;
* `knowledge_input`, `knowledge_group`: for each row, the fingerprint of the inputs its
  evaluation consumed (`knowledge_inputs`): byte ranges with a digest, outcome groups, date facts;
* `knowledge_universe`: every player PERSON index of the save (the native all_actual vector);
* `knowledge_seed`: the named population (FOW node, report, own roster);
* `_knowledge_meta`: save, coach, the current epoch, timings.

Every cell comes from `knowledge_bulk` (mode `cells`); this module never reads an attribute byte.

Freshness. Rows are not keyed by game date. An *epoch* is one freshness generation: it starts
when the game date moves, when the game process or selected coach changes, or when the previous
epoch is older than `EPOCH_SECONDS`. A row is current when it was computed or verified in the
current epoch. `ensure_knowledge(idxs)` makes rows current: it hands the stored fingerprints to
the engine, which evaluates only the players whose inputs changed and confirms the rest.
Nothing is computed that was not asked for: there are no tiers and no background fill.

CLI: `python -m fm_live_mcp.fmdb.knowledge_store status|reset|ensure|pair`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import knowledge_codes as codes

SCHEMA_VERSION = 3          # 3: input fingerprints and epochs replace game-date keys, tiers and the fill
STAR_STATES = ('exact', 'range', 'unknown', 'unavailable', 'not_computed')
STAR_CHUNK = 500            # one perceived_ability call stays well under a minute
DEFAULT_CACHE = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmcp-source-cache')
FILE_NAME = 'knowledge.sqlite'
TIER1, TIER2, TIER3 = 1, 2, 3       # `tier` column: 1 named population, 2 asked for, 3 the rest
DEFAULT_CHUNK = 4000        # players per engine call (one journal, one fence)
EPOCH_SECONDS = 20.0        # rows verified this recently are served without another look
MAX_ATTEMPTS = 3
MAX_ISOLATED_FAILURES = 25   # single players recorded as capture_rejected before a build stops
STATES = ('exact', 'range', 'unknown', 'unavailable')


class KnowledgeError(RuntimeError):
    """The store cannot serve the request; the message says why."""


class DayChanged(KnowledgeError):
    """The game date (or save/coach) moved while building; a new epoch was started."""


# --------------------------------------------------------------------------- paths and identity

def cache_root() -> Path:
    """`$FMCP_CACHE_DIR/fmdb` (same rule as the snapshot lane's `engine.cache_root`)."""
    env = os.environ.get('FMCP_CACHE_DIR')
    return (Path(env) if env else DEFAULT_CACHE) / 'fmdb'


def save_key(name: str, created: str, created_version: int) -> str:
    """Directory name for one career; identical to `engine.save_key` on the snapshot lane."""
    try:
        from .engine import save_key as engine_save_key  # snapshot lane, when merged
        return engine_save_key(name, created, created_version)
    except ImportError:
        slug = re.sub(r'[^A-Za-z0-9]+', '-', name).strip('-').lower()[:48] or 'career'
        digest = hashlib.sha256(f'{name}\0{created}\0{created_version}'.encode()).hexdigest()[:10]
        return f'{slug}-{created}-{digest}'


def knowledge_path(key: str, root: Path | None = None) -> Path:
    return (root or cache_root()) / key / FILE_NAME


def live_identity(bridge_or_session, coach_name: str | None = None) -> dict:
    """Save key, save name, game date and selected coach of the attached game (no attribute byte)."""
    from .. import knowledge_bulk as kb
    bridge, sid = kb._bridge_and_session(bridge_or_session)
    save = bridge.get_save(sid)['save']
    coaches = save.get('coaches') or []
    coach = next((c for c in coaches if coach_name is None or c.get('name') == coach_name), None)
    if coach is None:
        raise KnowledgeError(f'Coach {coach_name!r} is not an active human manager in this save.')
    return dict(save_key=save_key(save['name'], save['created_date'], save['created_version']),
                save_name=save['name'], game_date=save['current_date'], coach=coach['name'],
                club=coach.get('club'))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# --------------------------------------------------------------------------- schema

def _wide_columns() -> list[str]:
    out = []
    for c in codes.COLUMNS:
        out += [f'"{c}" INTEGER', f'"{c}_min" INTEGER', f'"{c}_max" INTEGER', f'"{c}_state" TEXT']
    return out


PLAYER_COLUMNS = ('idx', 'k', 'node_score', 'report_score', 'own_club', 'sources', 'scouted', 'h_score',
                  'ca_gate', 'pa_gate', 'exact_n', 'range_n', 'unknown_n', 'unavailable_n',
                  'unavailable_reason', 'category', 'node_present', 'report_present',
                  'ca_stars_min', 'ca_stars_max', 'ca_stars_state', 'pa_stars_min', 'pa_stars_max', 'pa_stars_state',
                  'in_player_search', 'tier', 'game_date', 'computed_at')
STAR_COLUMNS = ('ca_stars_min', 'ca_stars_max', 'ca_stars_state', 'pa_stars_min', 'pa_stars_max', 'pa_stars_state')

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS _knowledge_meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS knowledge_player(
    idx INTEGER PRIMARY KEY,
    k INTEGER,                 -- contextual K as the engine reports it (NULL: not evaluated or failed)
    node_score INTEGER,        -- reciprocal FOW node score (NULL: no node)
    report_score INTEGER,      -- selected report byte (NULL: no report)
    own_club INTEGER,          -- 1: the engine's own-club branch (every attribute exact)
    sources TEXT,              -- winning sources of H's score: own_club,node,context,report
    scouted INTEGER,           -- 1: FOW node or report or own roster
    h_score INTEGER,
    ca_gate INTEGER,           -- H state of the CA star gate (0 unknown, 1 range, 2 exact)
    pa_gate INTEGER,           -- H state of the PA star gate
    exact_n INTEGER, range_n INTEGER, unknown_n INTEGER, unavailable_n INTEGER,
    unavailable_reason TEXT,
    category INTEGER, node_present INTEGER, report_present INTEGER,
    ca_stars_min REAL, ca_stars_max REAL, ca_stars_state TEXT,   -- perceived CA stars (0.5 steps)
    pa_stars_min REAL, pa_stars_max REAL, pa_stars_state TEXT,   -- perceived PA stars
    in_player_search INTEGER,  -- Player Search admission (NULL: not computed)
    tier INTEGER,
    game_date TEXT NOT NULL,   -- game date at which the row was last computed or confirmed
    computed_at TEXT NOT NULL, -- wall clock of the last evaluation (not of a confirmation)
    epoch INTEGER,             -- epoch in which the row was last computed or confirmed
    stars_epoch INTEGER);      -- epoch of the star and Player Search columns
CREATE TABLE IF NOT EXISTS knowledge_attribute(
    idx INTEGER NOT NULL, field TEXT NOT NULL, code TEXT NOT NULL, state TEXT NOT NULL,
    value INTEGER, min INTEGER, max INTEGER, reason TEXT,
    PRIMARY KEY(idx, field)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS knowledge_attribute_code ON knowledge_attribute(code, state);
CREATE TABLE IF NOT EXISTS knowledge_wide(idx INTEGER PRIMARY KEY, {', '.join(_wide_columns())});
CREATE TABLE IF NOT EXISTS knowledge_universe(idx INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS knowledge_seed(idx INTEGER PRIMARY KEY, fow_node INTEGER, report INTEGER,
                                          own_roster INTEGER);
CREATE TABLE IF NOT EXISTS knowledge_fields(field TEXT PRIMARY KEY, field_id INTEGER, column_name TEXT,
                                            code TEXT, code_100 TEXT);
CREATE TABLE IF NOT EXISTS knowledge_input(idx INTEGER PRIMARY KEY, spans BLOB NOT NULL, digest BLOB NOT NULL,
                                           groups TEXT NOT NULL, facts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge_group(key TEXT PRIMARY KEY, spans BLOB NOT NULL, digest BLOB NOT NULL,
                                           groups TEXT NOT NULL, facts TEXT NOT NULL, outcome TEXT NOT NULL)
                                           WITHOUT ROWID;
"""

_CURRENT_TABLES = ('knowledge_player', 'knowledge_attribute', 'knowledge_wide', 'knowledge_universe',
                   'knowledge_seed', 'knowledge_input', 'knowledge_group')


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    path = Path(path)
    if readonly:
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=60, isolation_level=None)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, timeout=60, isolation_level=None)
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA synchronous=NORMAL')
    con.execute('PRAGMA busy_timeout=60000')
    return con


class KnowledgeStore:
    """One `knowledge.sqlite`. Writers use short IMMEDIATE transactions; readers see WAL snapshots."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.con = connect(self.path)
        self.rebuilt_from = self._check_schema()
        self.con.executescript(_SCHEMA)
        if self.meta('schema_version') is None:
            self._set_meta({'schema_version': SCHEMA_VERSION})
            if self.rebuilt_from is not None:
                self._set_meta({'rebuilt_from_schema': self.rebuilt_from, 'rebuilt_at': _now()})
        if self.con.execute('SELECT count(*) FROM knowledge_fields').fetchone()[0] == len(codes.FIELDS):
            return
        with self.transaction():
            self.con.execute('DELETE FROM knowledge_fields')
            self.con.executemany('INSERT INTO knowledge_fields VALUES (?,?,?,?,?)',
                                 [(f['name'], f['field_id'], f['column'], f['code'], f['code_100'])
                                  for f in codes.FIELDS])

    def close(self):
        self.con.close()

    def reset(self):
        """Drop every knowledge table and rebuild an empty current-schema store (operator action)."""
        with self.transaction():
            for name, in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                if name.startswith(('knowledge_', 'stale_knowledge_')) or name == '_knowledge_meta':
                    self.con.execute(f'DROP TABLE IF EXISTS "{name}"')
        self.con.executescript(_SCHEMA)
        self.set_meta({'schema_version': SCHEMA_VERSION, 'reset_at': _now()})
        self.__init__(self.path)

    def _check_schema(self):
        """Drop a store written by another schema version (its rows were captured differently,
        so they are rebuilt, never mixed). Returns the old version, or None when nothing was dropped."""
        tables = {n for n, in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if '_knowledge_meta' not in tables:
            return None
        row = self.con.execute("SELECT value FROM _knowledge_meta WHERE key='schema_version'").fetchone()
        version = json.loads(row[0]) if row else None
        if version == SCHEMA_VERSION:
            return None
        self.con.execute('BEGIN IMMEDIATE')
        try:
            for name in tables:
                if name.startswith(('knowledge_', 'stale_knowledge_')) or name == '_knowledge_meta':
                    self.con.execute(f'DROP TABLE IF EXISTS "{name}"')
            self.con.execute('COMMIT')
        except Exception:
            self.con.execute('ROLLBACK')
            raise
        return version if version is not None else 0

    # ------------------------------------------------------------------ meta
    def transaction(self):
        store = self

        class _Tx:
            def __enter__(self):
                store.con.execute('BEGIN IMMEDIATE')
                return store.con

            def __exit__(self, exc_type, *_):
                store.con.execute('ROLLBACK' if exc_type else 'COMMIT')
                return False
        return _Tx()

    def meta(self, key, default=None):
        row = self.con.execute('SELECT value FROM _knowledge_meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def all_meta(self) -> dict:
        return {k: json.loads(v) for k, v in self.con.execute('SELECT key, value FROM _knowledge_meta')}

    def _set_meta(self, values: dict):
        self.con.executemany('INSERT OR REPLACE INTO _knowledge_meta VALUES (?,?)',
                             [(k, json.dumps(v)) for k, v in values.items()])

    def set_meta(self, values: dict):
        with self.transaction():
            self._set_meta(values)

    # ------------------------------------------------------------------ identity / epochs
    def identity(self) -> dict | None:
        ident = self.meta('identity')
        return ident if isinstance(ident, dict) else None

    def ensure_identity(self, ident: dict) -> dict:
        """Bind the store to `ident` (save_key, coach, capture options). Another save, coach or
        capture option drops every row; a new game date does not (it starts a new epoch)."""
        with self.transaction():
            return self._ensure_identity(ident)

    def _ensure_identity(self, ident: dict) -> dict:
        current = self.meta('identity')
        if self.meta('schema_version') != SCHEMA_VERSION:
            raise KnowledgeError(f'{self.path} is being written by another knowledge_store (schema '
                                 f'{self.meta("schema_version")}). Stop that process or update it, then run '
                                 '`knowledge_store reset --store <path>`.')
        want = {k: ident[k] for k in ('save_key', 'save_name', 'coach', 'club')}
        want['native'] = bool(ident.get('native', True))
        date = ident.get('game_date')
        if current == want:
            if date is not None and (self.meta('epoch') or {}).get('game_date') != date:
                self._begin_epoch(date)
                return dict(invalidated=False, new_epoch=True, reason='game date changed')
            return dict(invalidated=False)
        reason = 'new store'
        if isinstance(current, dict):
            if (current.get('save_key'), current.get('coach')) != (want['save_key'], want['coach']):
                reason = 'save or coach changed'
            elif current.get('native') != want['native']:
                reason = 'capture options changed'
            else:
                reason = 'identity changed'
        for table in _CURRENT_TABLES:
            self.con.execute(f'DELETE FROM {table}')
        for key in [k for k, in self.con.execute('SELECT key FROM _knowledge_meta')]:
            if key not in ('schema_version',):
                self.con.execute('DELETE FROM _knowledge_meta WHERE key=?', (key,))
        self._set_meta({'identity': want, 'invalidated_at': _now(), 'invalidation_reason': reason})
        self._begin_epoch(date)
        return dict(invalidated=True, reason=reason)

    def _begin_epoch(self, game_date) -> int:
        previous = self.meta('epoch') or {}
        epoch = dict(id=int(previous.get('id', 0)) + 1, game_date=game_date, started=time.time(),
                     started_at=_now())
        self._set_meta({'epoch': epoch})
        return epoch['id']

    def begin_epoch(self, game_date) -> int:
        """Start a new freshness generation: no row is current until it is confirmed again."""
        with self.transaction():
            return self._begin_epoch(game_date)

    def epoch(self) -> dict:
        return self.meta('epoch') or dict(id=0, game_date=None, started=0.0)

    def game_date(self):
        return self.epoch().get('game_date')

    # ------------------------------------------------------------------ population bookkeeping
    def set_seeds(self, seeds: dict):
        fow, rep, own = (set(seeds.get(k, ())) for k in ('fow_nodes', 'report_primary', 'own_club_rosters'))
        rep |= set(seeds.get('report_alternate', ()))
        union = sorted(fow | rep | own)
        with self.transaction():
            self.con.execute('DELETE FROM knowledge_seed')
            self.con.executemany('INSERT INTO knowledge_seed VALUES (?,?,?,?)',
                                 [(i, int(i in fow), int(i in rep), int(i in own)) for i in union])
            self.con.execute('UPDATE knowledge_player SET scouted = (idx IN (SELECT idx FROM knowledge_seed))')
            self._set_meta({'seed_counts': dict(fow_nodes=len(fow), reports=len(rep), own_roster=len(own),
                                                union=len(union)), 'seeds_epoch': self.epoch()['id']})
        return union

    def seeds(self) -> list[int]:
        return [i for i, in self.con.execute('SELECT idx FROM knowledge_seed ORDER BY idx')]

    def set_universe(self, indices, *, source: str):
        with self.transaction():
            self.con.execute('DELETE FROM knowledge_universe')
            self.con.executemany('INSERT OR IGNORE INTO knowledge_universe VALUES (?)', [(i,) for i in indices])
            n = self.con.execute('SELECT count(*) FROM knowledge_universe').fetchone()[0]
            self._set_meta({'universe_count': n, 'universe_source': source, 'universe_at': _now(),
                            'universe_epoch': self.epoch()['id']})
        return n

    def universe(self) -> list[int]:
        return [i for i, in self.con.execute('SELECT idx FROM knowledge_universe ORDER BY idx')]

    def lacking(self, idxs=None, *, stars=False) -> list[int]:
        """PERSON indices (of `idxs`, default the universe) without a current row: never
        computed, or not confirmed in the current epoch. With `stars`, rows whose star and
        Player Search columns are not of the current epoch."""
        epoch = self.epoch()['id']
        column = 'stars_epoch' if stars else 'epoch'
        have = {i for i, in self.con.execute(f'SELECT idx FROM knowledge_player WHERE {column} = ?', (epoch,))}
        if idxs is None:
            idxs = self.universe()
        return [i for i in sorted(set(idxs)) if i not in have]

    def pending(self, limit: int, *, among=None) -> list[int]:
        return self.lacking(among)[:limit]

    def coverage(self) -> dict:
        q = lambda sql, *a: self.con.execute(sql, a).fetchone()[0]
        meta = self.all_meta()
        ident = meta.get('identity') or {}
        epoch = meta.get('epoch') or {}
        e = epoch.get('id', 0)
        universe = meta.get('universe_count')
        covered = q('SELECT count(*) FROM knowledge_player WHERE epoch = ?', e)
        in_universe = q('SELECT count(*) FROM knowledge_player k JOIN knowledge_universe u USING(idx) '
                        'WHERE k.epoch = ?', e)
        seeds = q('SELECT count(*) FROM knowledge_seed')
        seeds_covered = q('SELECT count(*) FROM knowledge_seed s JOIN knowledge_player k USING(idx) '
                          'WHERE k.epoch = ?', e)
        return dict(save_key=ident.get('save_key'), coach=ident.get('coach'), game_date=epoch.get('game_date'),
                    epoch=e, epoch_started_at=epoch.get('started_at'),
                    knowledge_rows=covered, stored_rows=q('SELECT count(*) FROM knowledge_player'),
                    scouted_rows=q('SELECT count(*) FROM knowledge_player WHERE scouted = 1 AND epoch = ?', e),
                    seed_players=seeds, seed_players_covered=seeds_covered,
                    tier1_complete=bool(seeds) and seeds_covered == seeds and meta.get('seeds_epoch') == e,
                    universe_players=universe, universe_players_covered=in_universe,
                    tier3_complete=bool(universe) and in_universe == universe,
                    unavailable_rows=q('SELECT count(*) FROM knowledge_player WHERE unavailable_n = 47 '
                                       'AND epoch = ?', e),
                    stars_computed_rows=q("SELECT count(*) FROM knowledge_player WHERE ca_stars_state != "
                                          "'not_computed' AND stars_epoch = ?", e),
                    stars_shown_rows=q("SELECT count(*) FROM knowledge_player WHERE ca_stars_state IN "
                                       "('exact','range') AND stars_epoch = ?", e),
                    native=(ident.get('native') if ident else None),
                    timings=meta.get('timings', {}))

    # ------------------------------------------------------------------ fingerprints
    def fingerprints(self, idxs) -> tuple:
        """(context, {idx: fingerprint}, {group key: record}) stored for `idxs`."""
        players, groups = {}, {}
        idxs = list(idxs)
        for start in range(0, len(idxs), 900):
            part = idxs[start:start + 900]
            for idx, spans, digest, grp, facts in self.con.execute(
                    f'SELECT idx, spans, digest, groups, facts FROM knowledge_input WHERE idx IN '
                    f'({",".join("?" * len(part))})', part):
                players[idx] = dict(spans=spans, digest=digest, groups=json.loads(grp), facts=json.loads(facts))
        wanted = {key for fp in players.values() for key, _ in fp['groups']}
        while wanted:
            batch, wanted = list(wanted), set()
            for start in range(0, len(batch), 900):
                part = batch[start:start + 900]
                for key, spans, digest, grp, facts, outcome in self.con.execute(
                        f'SELECT key, spans, digest, groups, facts, outcome FROM knowledge_group WHERE key IN '
                        f'({",".join("?" * len(part))})', part):
                    groups[key] = dict(spans=spans, digest=digest, groups=json.loads(grp),
                                       facts=json.loads(facts), outcome=outcome)
                    wanted.update(k for k, _ in groups[key]['groups'] if k not in groups)
            seen = set(batch)
            wanted = {k for k in wanted if k not in groups and k not in seen}
        return self.meta('input_context'), players, groups

    # ------------------------------------------------------------------ writing
    def write_rows(self, rows: list[dict], *, tier: int, ident: dict, inputs: dict | None = None) -> int:
        """Write one capture's rows as current in this epoch. `inputs` is the engine's
        `inputs` record (context, kept, players, groups): fingerprints of the written rows
        are stored and the rows it kept are confirmed without being rewritten."""
        computed = _now()
        with self.transaction():
            self._ensure_identity(ident)
            epoch = self.meta('epoch')
            date = ident.get('game_date') or epoch.get('game_date')
            seeds = {i for i, in self.con.execute('SELECT idx FROM knowledge_seed')}
            players, attrs, wides, stars = [], [], [], []
            for row in rows:
                idx = row['idx']
                scouted = int(idx in seeds) if seeds else int(bool(row['node_present'] or row['report_present']
                                                                  or row['own_club']))
                has_stars = row.get('ca_stars_state', 'not_computed') != 'not_computed' \
                    or row.get('in_player_search') is not None or row.get('stars_current')
                players.append((idx, row['k'], row['node_score'], row['report_score'], row['own_club'],
                                row['sources'], scouted, row['h_score'], row['ca_gate'], row['pa_gate'],
                                row['exact_n'], row['range_n'], row['unknown_n'], row['unavailable_n'],
                                row['unavailable_reason'], row['category'], row['node_present'],
                                row['report_present'], row['ca_stars_min'], row['ca_stars_max'],
                                row['ca_stars_state'], row['pa_stars_min'], row['pa_stars_max'],
                                row['pa_stars_state'], row['in_player_search'],
                                1 if idx in seeds else tier, date, computed, epoch['id'],
                                epoch['id'] if has_stars else None))
                wide = [idx]
                for f, cell in zip(codes.FIELDS, row['cells']):
                    attrs.append((idx, f['name'], f['code'], cell['state'], cell['value'], cell['min'],
                                  cell['max'], cell['reason']))
                    wide += [cell['value'], cell['min'], cell['max'], cell['state']]
                wides.append(tuple(wide))
            columns = PLAYER_COLUMNS + ('epoch', 'stars_epoch')
            self.con.executemany(f'INSERT OR REPLACE INTO knowledge_player({",".join(columns)}) '
                                 f'VALUES ({",".join("?" * len(columns))})', players)
            self.con.executemany('INSERT OR REPLACE INTO knowledge_attribute VALUES (?,?,?,?,?,?,?,?)', attrs)
            self.con.executemany(f'INSERT OR REPLACE INTO knowledge_wide VALUES ({",".join("?" * (1 + 4 * 47))})',
                                 wides)
            if inputs is not None:
                written = {row['idx'] for row in rows}
                self.con.executemany('DELETE FROM knowledge_input WHERE idx = ?',
                                     [(i,) for i in written if i not in inputs['players']])
                self.con.executemany(
                    'INSERT OR REPLACE INTO knowledge_input VALUES (?,?,?,?,?)',
                    [(idx, fp['spans'], fp['digest'], json.dumps(fp['groups']), json.dumps(fp['facts']))
                     for idx, fp in inputs['players'].items() if idx in written])
                self.con.executemany(
                    'INSERT OR REPLACE INTO knowledge_group VALUES (?,?,?,?,?,?)',
                    [(key, g['spans'], g['digest'], json.dumps(g['groups']), json.dumps(g['facts']), g['outcome'])
                     for key, g in inputs['groups'].items()])
                self.con.executemany('UPDATE knowledge_player SET epoch = ?, game_date = ? WHERE idx = ?',
                                     [(epoch['id'], date, idx) for idx in inputs['kept']])
                if self.meta('input_context') != inputs['context'] and inputs['context'] is not None:
                    self._set_meta({'input_context': inputs['context']})
            else:
                self.con.executemany('DELETE FROM knowledge_input WHERE idx = ?', [(row['idx'],) for row in rows])
        return len(rows)

    def write_stars(self, values: dict, *, epoch: int) -> int:
        """Star and Player Search columns for {idx: (ca_min, ca_max, ca_state, pa_min, pa_max,
        pa_state, in_player_search)}, marked as of `epoch`."""
        with self.transaction():
            self.con.executemany(
                'UPDATE knowledge_player SET ca_stars_min=?, ca_stars_max=?, ca_stars_state=?, pa_stars_min=?, '
                'pa_stars_max=?, pa_stars_state=?, in_player_search=?, stars_epoch=? WHERE idx=? AND epoch=?',
                [tuple(v) + (epoch, idx, epoch) for idx, v in values.items()])
        return len(values)


# --------------------------------------------------------------------------- capture

def _cell(cell: dict) -> dict:
    state = cell['state']
    if state == 'exact':
        return dict(state=state, value=cell['value'], min=cell['value'], max=cell['value'], reason=None)
    if state == 'range':
        return dict(state=state, value=None, min=cell['minimum'], max=cell['maximum'], reason=None)
    reason = None
    if state == 'unavailable':
        reason = cell.get('reason') + (f": {cell['detail']}" if cell.get('detail') else '')
    return dict(state=state, value=None, min=None, max=None, reason=reason)


def _gate(k, slot):
    from .. import knowledge_bulk as kb
    state, _ = kb.ability_state(k, slot)
    return state


NOT_COMPUTED = dict(ca_stars_min=None, ca_stars_max=None, ca_stars_state='not_computed', pa_stars_min=None,
                    pa_stars_max=None, pa_stars_state='not_computed', in_player_search=None)


def player_row(raw_row: dict) -> tuple[dict, bool]:
    """Flatten one engine subject (mode `cells`) into a store row.

    Returns (row, needs_summary): `needs_summary` is True when the cells capture did not evaluate
    H's score (every field threshold zero) so the CA/PA gates need a summary capture.
    """
    from .. import knowledge_bulk as kb
    key = raw_row['key']
    ident = raw_row.get('native_identity') or {}
    idx = ident.get('database_index', key if type(key) is int else None)
    cells = [_cell(c) for c in raw_row['fields']]
    counts = {s: sum(c['state'] == s for c in cells) for s in STATES}
    k = raw_row.get('knowledge')
    first_unavailable = next((c['reason'] for c in cells if c['state'] == 'unavailable'), None)
    row = dict(idx=idx, cells=cells, exact_n=counts['exact'], range_n=counts['range'],
               unknown_n=counts['unknown'], unavailable_n=counts['unavailable'],
               unavailable_reason=first_unavailable, k=None, node_score=None, report_score=None,
               own_club=0, sources='', h_score=None, ca_gate=None, pa_gate=None, category=None,
               node_present=None, report_present=None, **NOT_COMPUTED)
    if k is None:
        return row, False
    row.update(k=k['context_k'], node_score=k['reciprocal'] if k['node_present'] else None,
               report_score=k['report'], own_club=int(bool(k['own_context'])),
               sources=','.join(kb.winning_sources(k)), h_score=k['score'], category=k['category'],
               node_present=int(bool(k['node_present'])), report_present=int(bool(k['report_present'])))
    needs = (k['failure'] is None and not k['own_context'] and k['score'] is None
             and k['score_failure'] is None)
    if not needs:
        row['ca_gate'], row['pa_gate'] = _gate(k, 0x62), _gate(k, 0x63)
    return row, needs


def capture(bridge_or_session, keys, *, coach_name=None, native=True, plan=None) -> dict:
    """One engine capture (cells for all 47 fields) of `keys` (PERSON indices).

    Uses the engine's own capture path in mode `cells` (`knowledge_bulk._run`, exactly what
    `visible_attributes_bulk` runs) and keeps its per-player knowledge record so the summary
    columns need no second capture. Players whose cells did not need H's score (zero thresholds)
    get their CA/PA gates from one `player_knowledge_summary` capture of just those players.

    `plan` (`knowledge_bulk.Plan`, or the `(context, players, groups)` of
    `KnowledgeStore.fingerprints`): stored fingerprints. The engine then evaluates only the
    players whose inputs changed; `rows` holds those, and `inputs` the new fingerprints and
    the kept PERSON indices. A row that needed the summary capture gets no fingerprint.
    """
    from .. import knowledge_bulk as kb
    bridge, sid = kb._bridge_and_session(bridge_or_session)
    if plan is not None and not isinstance(plan, kb.Plan):
        plan = kb.Plan(*plan)
    raw = kb._run((bridge, sid), list(keys), kb.ALL_FIELDS, coach_name, 'cells', None, native=native,
                  plan=plan)
    header = kb._header(raw, sid)
    rows, missing = [], []
    for subject in raw['subjects']:
        row, needs = player_row(subject)
        rows.append(row)
        if needs:
            missing.append(row)
    summary_cost = None
    if missing:
        summary = kb.player_knowledge_summary((bridge, sid), [r['idx'] for r in missing], coach_name=coach_name,
                                              native=native)
        if summary['save']['current_date'] != header['save']['current_date']:
            raise kb.Rejected('Selected context changed between the cells and summary captures')
        by_key = {p['key']: p for p in summary['players']}
        for row in missing:
            p = by_key[row['idx']]
            gates = p.get('star_gates') or {}
            row['ca_gate'] = (gates.get('current_ability') or {}).get('h_state')
            row['pa_gate'] = (gates.get('potential_ability') or {}).get('h_state')
            row['k'] = p.get('context_k')
            row['h_score'] = p.get('h_score')
        summary_cost = summary['cost']
    inputs = raw.get('inputs')
    if inputs is not None:
        for row in missing:
            inputs['players'].pop(row['idx'], None)
    return dict(save=header['save'], coach=header['coach'], club=header['club'], cost=header['cost'],
                summary_cost=summary_cost, firewall=header['firewall'], rows=rows, native=raw.get('native'),
                inputs=inputs)


def _star_cells(entry: dict | None) -> tuple:
    if not entry:
        return None, None, 'unavailable'
    state = entry.get('state')
    if state in ('exact', 'range'):
        return entry['min_stars'], entry['max_stars'], state
    return None, None, state if state in STAR_STATES else 'unavailable'


def star_capture(bridge_or_session, keys, *, coach_name=None) -> dict:
    """Perceived CA/PA stars per PERSON index (`knowledge_stars.perceived_ability`, chunked).

    Returns {'current_date', 'players': {idx: (ca_min, ca_max, ca_state, pa_min, pa_max, pa_state)}}."""
    from .. import knowledge_stars
    out, date = {}, None
    for start in range(0, len(keys), STAR_CHUNK):
        result = knowledge_stars.perceived_ability(bridge_or_session, list(keys[start:start + STAR_CHUNK]),
                                                   coach_name=coach_name)
        date = result['save']['current_date']
        for p in result['players']:
            if 'current' not in p:
                out[p['key']] = (None, None, 'unavailable', None, None, 'unavailable')
            else:
                out[p['key']] = _star_cells(p['current']) + _star_cells(p['potential'])
    return dict(current_date=date, players=out)


def search_capture(bridge_or_session, keys, *, coach_name=None) -> dict:
    """Player Search admission per PERSON index (`knowledge_native.search_admission`)."""
    from .. import knowledge_native
    result = knowledge_native.search_admission(bridge_or_session, list(keys), coach_name=coach_name)
    out = {p['key']: (int(p['admitted']) if p.get('state') == 'available' and 'admitted' in p else None)
           for p in result['players']}
    return dict(current_date=result['save']['current_date'], players=out)


def player_universe(bridge_or_session) -> dict:
    """PERSON indices of every player in the native all_actual vector (Player Search base source).

    Reads the vector, each primary's vtable and its PERSON's index/UID words through
    `fm_fast_reader`; no attribute byte.
    """
    from .. import knowledge_bulk as kb, players
    from .memory import LiveMemory
    bridge, sid = kb._bridge_and_session(bridge_or_session)
    with bridge.lock, bridge._read_scope(sid):
        process = bridge._current(sid)
        layout = bridge._player_layout(process)
    base = layout[0] - players.RVA[0]
    staff = base + players.STAFF_RVA[0]
    started = time.monotonic()
    memory = LiveMemory(process.pid, expected_executable=process.executable)
    try:
        primaries = [p for p in kb.all_actual_primaries(memory.read, base) if p]
        heads = memory.read_many([(p, 8) for p in primaries])
        persons = []
        for primary, head in zip(primaries, heads):
            vtable = struct.unpack('<Q', head)[0] if head else None
            if vtable == layout[0]:
                persons.append(primary + 0x388)
            elif vtable == staff:
                persons.append(primary + 0x480)
        words = memory.read_many([(p + 8, 8) for p in persons])
    finally:
        memory.close()
    indices = sorted({struct.unpack('<II', w)[0] for w in words if w and struct.unpack('<II', w)[1]})
    return dict(indices=indices, vector_slots=len(primaries), players=len(indices),
                seconds=round(time.monotonic() - started, 2))


# --------------------------------------------------------------------------- builder

def _changed(exc) -> bool:
    """A rejection worth retrying unchanged: the game moved, or a native read stream broke (seen once
    on the first capture after a perceived_ability call longer than about 60 s; the retry succeeds)."""
    text = str(exc)
    return any(s in text for s in ('changed', 'differs', 'Broken pipe', 'read stream'))


class KnowledgeBuilder:
    """Keeps a `KnowledgeStore` current for the rows that are asked for.

    `bridge_or_session` is an attached Bridge or (bridge, session_id). `on_progress(dict)` is
    called after each written chunk.
    """

    def __init__(self, bridge_or_session, store: KnowledgeStore, *, coach_name=None,
                 chunk_size: int = DEFAULT_CHUNK, on_progress=None, native: bool = True,
                 epoch_seconds: float = EPOCH_SECONDS):
        self.target, self.store, self.coach_name = bridge_or_session, store, coach_name
        self.chunk_size, self.on_progress = chunk_size, on_progress
        self.native, self.epoch_seconds = bool(native), epoch_seconds
        self.ident = None
        self.stats = dict(evaluated=0, kept=0, calls=0, stars=0, search=0)

    # -- identity and epochs ---------------------------------------------------
    def refresh_identity(self, *, new_epoch: bool | None = None) -> dict:
        """Bind the store to the attached save and coach and decide the epoch: a new one when
        the game date moved, when `new_epoch` is True, or (with `new_epoch` None) when the
        current one is older than `epoch_seconds`."""
        self.ident = dict(live_identity(self.target, self.coach_name), native=self.native)
        change = self.store.ensure_identity(self.ident)
        if not change.get('invalidated') and not change.get('new_epoch'):
            age = time.time() - self.store.epoch().get('started', 0.0)
            if new_epoch or (new_epoch is None and age > self.epoch_seconds):
                self.store.begin_epoch(self.ident['game_date'])
                change = dict(change, new_epoch=True, reason='epoch aged out')
        return change

    def _timing(self, key, seconds, players):
        timings = self.store.meta('timings', {}) or {}
        timings[key] = dict(seconds=round(seconds, 2), players=players,
                            players_per_second=round(players / max(seconds, 1e-9), 1))
        self.store.set_meta({'timings': timings})

    # -- capture with retry ----------------------------------------------------
    def _capture_write(self, keys, tier) -> dict:
        """Capture `keys` against their stored fingerprints and write the result. Retries a
        rejected capture; raises DayChanged (after starting a new epoch) when the game date
        moved; isolates a player whose capture keeps failing by bisection."""
        from ..bridge import BridgeError
        last = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                result = capture(self.target, keys, coach_name=self.coach_name, native=self.native,
                                 plan=self.store.fingerprints(keys))
            except BridgeError as exc:
                last = exc
                before = self.ident
                after = self.refresh_identity(new_epoch=False)
                if after.get('invalidated') or after.get('new_epoch'):
                    raise DayChanged(f'{after["reason"]}: {before["game_date"]} -> '
                                     f'{self.ident["game_date"]}') from exc
                if not _changed(exc):
                    break
                continue
            if result['save']['current_date'] != self.ident['game_date']:
                self.refresh_identity(new_epoch=False)
                raise DayChanged(f'game date changed during capture -> {result["save"]["current_date"]}')
            inputs = result.get('inputs') or dict(context=None, kept=[], players={}, groups={})
            self.store.write_rows(result['rows'], tier=tier, ident=self.ident, inputs=inputs)
            self.stats['evaluated'] += len(result['rows'])
            self.stats['kept'] += len(inputs['kept'])
            self.stats['calls'] += 1
            why = self.stats.setdefault('invalid', {})
            for reason, n in ((inputs.get('stats') or {}).get('invalid') or {}).items():
                why[reason] = why.get(reason, 0) + n
            return result
        if len(keys) > 1:
            half = len(keys) // 2
            a = self._capture_write(keys[:half], tier)
            b = self._capture_write(keys[half:], tier)
            return dict(a, rows=a['rows'] + b['rows'])
        self.isolated_failures = getattr(self, 'isolated_failures', 0) + 1
        if self.isolated_failures > MAX_ISOLATED_FAILURES:
            raise KnowledgeError(f'Captures keep failing ({self.isolated_failures} players isolated); '
                                 f'last error: {last}')
        reason = f'capture_rejected: {str(last)[:180]}'
        cell = dict(state='unavailable', value=None, min=None, max=None, reason=reason)
        row = dict(idx=keys[0], cells=[cell] * 47, exact_n=0, range_n=0, unknown_n=0, unavailable_n=47,
                   unavailable_reason=reason, k=None, node_score=None, report_score=None, own_club=0,
                   sources='', h_score=None, ca_gate=None, pa_gate=None, category=None, node_present=None,
                   report_present=None, **NOT_COMPUTED)
        self.store.write_rows([row], tier=tier, ident=self.ident)
        return dict(rows=[row], save={'current_date': self.ident['game_date']})

    def _require_space(self, what):
        """Refuse before writing when the store's volume is below engine.MIN_FREE_BUILD."""
        from .engine import MIN_FREE_BUILD, CacheSpaceError, require_space
        try:
            require_space(Path(self.store.path).parent, MIN_FREE_BUILD, what)
        except CacheSpaceError as exc:
            raise KnowledgeError(str(exc)) from exc

    # -- what a query asks for ---------------------------------------------------
    def ensure(self, idxs, *, tier=TIER2, label='requested players', max_day_restarts=3) -> dict:
        """Make the knowledge rows of `idxs` current in this epoch. Nothing else is computed."""
        if self.ident is None:
            self.refresh_identity()
        started = time.monotonic()
        before = dict(self.stats)
        requested = sorted({int(i) for i in idxs})
        for _ in range(max_day_restarts + 1):
            todo = self.store.lacking(requested)
            try:
                if todo:
                    self._require_space('Knowledge build')
                done = 0
                for start in range(0, len(todo), self.chunk_size):
                    chunk = todo[start:start + self.chunk_size]
                    self._capture_write(chunk, tier)
                    done += len(chunk)
                    if self.on_progress:
                        self.on_progress(dict(label=label, done=done, total=len(todo),
                                              seconds=round(time.monotonic() - started, 1), updated_at=_now()))
                break
            except DayChanged as exc:
                self.store.set_meta({'last_day_change': dict(at=_now(), detail=str(exc))})
        else:
            raise KnowledgeError('The game date kept changing; knowledge build stopped.')
        out = dict(requested=len(requested), computed=self.stats['evaluated'] - before['evaluated'],
                   confirmed=self.stats['kept'] - before['kept'], seconds=round(time.monotonic() - started, 2))
        if out['computed'] or out['confirmed']:
            self._timing('ensure_last', time.monotonic() - started, out['computed'] + out['confirmed'])
        return out

    def seeds(self) -> list[int]:
        """The named population of this epoch (HUMAN FOW nodes, both report vectors, own rosters)."""
        from .. import knowledge_bulk as kb
        if self.ident is None:
            self.refresh_identity()
        if self.store.meta('seeds_epoch') == self.store.epoch()['id']:
            return self.store.seeds()
        t0 = time.monotonic()
        population = kb.known_population(self.target, coach_name=self.coach_name, evaluate=False)
        if population['save']['current_date'] != self.ident['game_date']:
            self.refresh_identity(new_epoch=False)
            population = kb.known_population(self.target, coach_name=self.coach_name, evaluate=False)
            if population['save']['current_date'] != self.ident['game_date']:
                raise DayChanged('game date changed while reading the named population')
        union = self.store.set_seeds(population['seeds'])
        self._timing('seeds', time.monotonic() - t0, len(union))
        return union

    def scouted(self) -> dict:
        """Make the named population current (3,555 players on the live save)."""
        return self.ensure(self.seeds(), tier=TIER1, label='named population')

    def ensure_universe(self) -> int:
        if self.ident is None:
            self.refresh_identity()
        context = self.store.meta('input_context')
        stamp = [self.store.game_date(), context.get('process') if isinstance(context, dict) else context]
        if self.store.meta('universe_stamp') != stamp or self.store.meta('universe_count') is None:
            # once per game date and game process: players enter and leave the list at day changes
            universe = player_universe(self.target)
            self.store.set_meta({'universe_stamp': stamp})
            self.store.set_universe(universe['indices'], source='all_actual vector')
            self._timing('universe', universe['seconds'], universe['players'])
        return self.store.meta('universe_count')

    def everything(self, *, max_players: int | None = None) -> dict:
        """Make every player of the save current (a save-wide query that reads knowledge
        columns of every row, or an explicit operator request)."""
        self.seeds()
        self.ensure_universe()
        todo = self.store.lacking()
        if max_players is not None:
            todo = todo[:max_players]
        self.ensure(todo, tier=TIER3, label='rest of save')
        return self.store.coverage()

    def ensure_stars(self, idxs, *, search=None) -> dict:
        """Star and Player Search columns for the current rows among `idxs`.

        Stars are computed for the named population and for players with a FOW node, a report or
        own-club context; other players keep `not_computed` (the game shows no stars for them:
        1,000 sampled returned unknown). Player Search admission is computed for the named
        population and for the PERSON indices in `search`."""
        from ..bridge import BridgeError
        epoch = self.store.epoch()
        wanted = set(self.store.lacking(idxs, stars=True))
        rows = {}
        for part in _parts(sorted(wanted), 900):
            for idx, e, scouted, node, report, own in self.store.con.execute(
                    'SELECT idx, epoch, scouted, node_present, report_present, own_club FROM knowledge_player '
                    f'WHERE idx IN ({",".join("?" * len(part))})', part):
                if e == epoch['id']:
                    rows[idx] = (bool(scouted), bool(scouted or node or report or own))
        if not rows:
            return dict(stars=0, search=0)
        search = set(search or ())
        star_keys = sorted(i for i, (_, shown) in rows.items() if shown)
        search_keys = sorted(i for i, (scouted, _) in rows.items() if scouted or i in search)
        values = {i: list(NOT_COMPUTED[c] for c in STAR_COLUMNS) + [None] for i in rows}
        t0 = time.monotonic()
        for attempt in range(MAX_ATTEMPTS):
            try:
                stars = star_capture(self.target, star_keys, coach_name=self.coach_name) if star_keys else None
                admitted = search_capture(self.target, search_keys, coach_name=self.coach_name) \
                    if search_keys else None
            except BridgeError as exc:
                if attempt == MAX_ATTEMPTS - 1 or not _changed(exc):
                    raise KnowledgeError(f'Star capture rejected: {exc}') from exc
                continue
            dates = {r['current_date'] for r in (stars, admitted) if r is not None}
            if dates - {epoch['game_date']}:
                self.refresh_identity(new_epoch=False)
                raise DayChanged('game date changed between the knowledge and star captures')
            break
        for i in star_keys:
            got = stars['players'].get(i)
            if got:
                values[i][:6] = got
        for i in search_keys:
            values[i][6] = admitted['players'].get(i)
        self.store.write_stars(values, epoch=epoch['id'])
        self.stats['stars'] += len(star_keys)
        self.stats['search'] += len(search_keys)
        self._timing('stars_last', time.monotonic() - t0, len(rows))
        return dict(stars=len(star_keys), search=len(search_keys))

    # -- names kept from the tiered builder (same work, on demand) ---------------
    def tier1(self, *, force=False) -> dict:
        if self.ident is None:
            self.refresh_identity()
        seeds = self.seeds()
        self.ensure(seeds, tier=TIER1, label='named population')
        self.ensure_stars(seeds)
        return self.store.coverage()

    def tier2(self, indices) -> dict:
        result = self.ensure(indices, tier=TIER2)
        self.ensure_stars(indices, search=indices)
        return result


def _parts(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def ensure_knowledge(bridge_or_session, store: KnowledgeStore, idxs, *, coach_name=None, native=True,
                     stars=False, on_progress=None) -> dict:
    """Make the knowledge rows of the PERSON indices `idxs` current, and nothing else.

    Rows already confirmed in the store's current epoch are not looked at. For the others the
    engine gets their stored fingerprints: it evaluates the players whose inputs changed (or
    that were never computed) and confirms the rest. `stars` also brings the star and Player
    Search columns of those rows to the current epoch. Returns counts and seconds.
    `lacking_knowledge(store, idxs)` says beforehand which rows a call would touch."""
    builder = KnowledgeBuilder(bridge_or_session, store, coach_name=coach_name, native=native,
                               on_progress=on_progress)
    builder.refresh_identity(new_epoch=False)
    out = builder.ensure(idxs)
    if stars:
        out.update(builder.ensure_stars(idxs))
    return out


def lacking_knowledge(store: KnowledgeStore, idxs=None, *, stars=False) -> list[int]:
    """Which of `idxs` (default: the whole universe) have no current knowledge row."""
    return store.lacking(idxs, stars=stars)


def golden_build(bridge_or_session, store: KnowledgeStore, *, limit=None, on_progress=None, native=True) -> dict:
    """Everything the tiered builder used to store for a whole save, through the on-demand path:
    the named population with stars and Player Search admission, then every other player, with
    stars for those with a FOW node, a report or own-club context. Used by
    scripts/knowledge_golden.py to diff a whole store against another code tree's."""
    builder = KnowledgeBuilder(bridge_or_session, store, on_progress=on_progress, native=native,
                               epoch_seconds=float('inf'))
    builder.refresh_identity(new_epoch=False)
    seeds = builder.seeds()
    builder.ensure(seeds, tier=TIER1, label='named population')
    builder.ensure_stars(seeds)
    builder.ensure_universe()
    rest = store.lacking()
    if limit:
        rest = rest[:limit]
    builder.ensure(rest, tier=TIER3, label='rest of save')
    builder.ensure_stars(rest)
    return dict(store.coverage(), stats=builder.stats)


# --------------------------------------------------------------------------- CLI

def _attach():
    from ..bridge import Bridge
    bridge = Bridge()
    return bridge, bridge.attach()['session_id']


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='knowledge_store')
    sub = ap.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('ensure', help='bring rows up to date in the foreground (operator request)')
    f.add_argument('--store', help='knowledge.sqlite path (default: cache/<save key>/knowledge.sqlite)')
    f.add_argument('--coach')
    f.add_argument('--chunk', type=int, default=DEFAULT_CHUNK)
    f.add_argument('--all', action='store_true', help='every player of the save (default: the named population)')
    f.add_argument('--no-native', action='store_true', help='leave the three unproven K branches unavailable')
    s = sub.add_parser('status')
    s.add_argument('--store', required=True)
    r = sub.add_parser('reset', help='drop and recreate an empty store')
    r.add_argument('--store', required=True)
    sub.add_parser('pair', help='verify the 47 field/FourCC pairs on own-club players')
    args = ap.parse_args(argv)
    if args.cmd == 'reset':
        store = KnowledgeStore(Path(args.store))
        store.reset()
        print(json.dumps(store.coverage(), indent=1))
        return 0
    if args.cmd == 'status':
        store = KnowledgeStore(Path(args.store))
        print(json.dumps(dict(coverage=store.coverage()), indent=1))
        return 0
    bridge, sid = _attach()
    try:
        if args.cmd == 'pair':
            print(json.dumps(codes.verify_field_codes((bridge, sid)), indent=1))
            return 0
        ident = live_identity((bridge, sid), args.coach)
        path = Path(args.store) if args.store else knowledge_path(ident['save_key'])
        store = KnowledgeStore(path)
        builder = KnowledgeBuilder((bridge, sid), store, coach_name=args.coach, chunk_size=args.chunk,
                                   native=not args.no_native,
                                   on_progress=lambda p: print(json.dumps(p), flush=True))
        builder.refresh_identity(new_epoch=True)
        if args.all:
            builder.everything()
        else:
            builder.scouted()
        print(json.dumps(dict(store.coverage(), stats=builder.stats), indent=1), flush=True)
        return 0
    finally:
        bridge.detach()


if __name__ == '__main__':
    sys.exit(main())
