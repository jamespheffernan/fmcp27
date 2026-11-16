"""Differential check of the incremental match tables against a full rebuild (live, read-only).

    python -m fm_live_mcp.fmdb.match_differential simulate --since 2030-12-10 [--competition IDX]
    python -m fm_live_mcp.fmdb.match_differential compare [--table T ...]

`simulate` deletes from the live snapshot's match tables the rows of the matches dated on or after
`--since` (and the player_season_stats rows of one competition) so that the next reference reads
them again through the incremental path, as after a match day. `compare` builds every table in
full in memory (a fresh collector: `SourceTable.rows`) and compares it with the stored table row
for row (as multisets; the row number `idx` of tables without a game identity is left out, since
the incremental path numbers added rows after the stored ones). Nothing is written to the game.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import sqlite3
import sys
import time

from . import sources, snapshot
from .sources import matches as M

TABLES = ('match', 'match_event', 'match_team_stats', 'match_player_stats', 'match_shot', 'match_pass',
          'match_event_stream', 'player_season_stats')


def _norm(v):
    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 9)
    return v


def simulate(path, since: str, competition=None) -> dict:
    floor = M.idx_floor(since)
    conn = sqlite3.connect(path)
    out = {}
    try:
        for t in TABLES:
            try:
                if t == 'match':
                    cur = conn.execute('DELETE FROM match WHERE idx >= ?', (floor,))
                elif t == 'match_event_stream':
                    cur = conn.execute('DELETE FROM match_event_stream WHERE date >= ?', (since,))
                elif t == 'player_season_stats':
                    cur = conn.execute('DELETE FROM player_season_stats WHERE competition_idx = ?', (competition,))
                else:
                    cur = conn.execute(f'DELETE FROM "{t}" WHERE match_idx >= ?', (floor,))
                out[t] = cur.rowcount
            except sqlite3.Error as exc:
                out[t] = f'{type(exc).__name__}: {exc}'
        conn.execute('UPDATE _source_tables SET checked_at = 0')
        conn.commit()
    finally:
        conn.close()
    return out


def compare(engine, path, names=TABLES) -> dict:
    sources.reset_cache(engine)
    found, _ = sources.discover(engine, only=['matches'])
    by = {t.name: t for _, t in found}
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    out = {}
    try:
        for name in names:
            t = by[name]
            cols = [c.name for c in t.columns]
            started = time.time()
            full = Counter(tuple(_norm(v) for v in r) for r in t.rows())
            seconds = time.time() - started
            stored = Counter(tuple(_norm(v) for v in r) for r in conn.execute(
                f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{name}"'))
            missing, extra = full - stored, stored - full
            out[name] = {'full_rows': sum(full.values()), 'stored_rows': sum(stored.values()),
                         'identical': not missing and not extra, 'only_in_full': sum(missing.values()),
                         'only_stored': sum(extra.values()), 'full_build_s': round(seconds, 1),
                         'examples_only_in_full': [list(r)[:6] for r in list(missing)[:3]],
                         'examples_only_stored': [list(r)[:6] for r in list(extra)[:3]]}
            print(name, json.dumps(out[name], default=str), flush=True)
    finally:
        conn.close()
    return out


def main(argv=None) -> int:
    from .engine import Engine
    ap = argparse.ArgumentParser(prog='match_differential')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('simulate')
    s.add_argument('--since', required=True)
    s.add_argument('--competition', type=int)
    c = sub.add_parser('compare')
    c.add_argument('--table', action='append')
    args = ap.parse_args(argv)
    engine = Engine.open()
    try:
        path = snapshot.snapshot_path(engine)
        print(json.dumps({'game_date': engine.game_date(), 'path': str(path)}), flush=True)
        if args.cmd == 'simulate':
            print(json.dumps(simulate(path, args.since, args.competition)))
        else:
            got = compare(engine, path, args.table or TABLES)
            return 0 if all(v['identical'] for v in got.values()) else 1
        return 0
    finally:
        engine.close()


if __name__ == '__main__':
    sys.exit(main())
