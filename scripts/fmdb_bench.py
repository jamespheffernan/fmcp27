"""Benchmarks behind docs/fmdb/PERFORMANCE.md, on the running FM27 (read-only).

Usage: PYTHONPATH=. python scripts/fmdb_bench.py <what> [--runs 3] [--released CHECKOUT] ...

  cold        import, Engine.open, first getter call (fresh process per run)
  build       snapshot build as a tool call runs it (phases from _build.timing)
  plans       snapshot plan phase on an empty plan cache (shipped plans checked on load)
  getters     player getters, 47 codes x N players, one process (--players 300)
  refresh     the content check: with nothing changed, and after --pages pages are made to
              look changed (their stored hash is altered, so their blocks are checked again)
  query       the tool path end to end on a new snapshot: a direct-only statement, 20 and 200
              rows with emulated columns, a sort on a whole emulated column, and each repeated
  knowledge   capture + stars + search admission for --players scouted players
  sql         five queries on a snapshot (--snapshot PATH)
  budget      the gate to run after merging a lane; exit status 1 and "BUDGET EXCEEDED" when
              * the build used more than --max-cpu CPU-seconds (default 40) or more than
                --max-wall seconds (default off),
              * a content check with nothing changed used more than --max-check-cpu
                CPU-seconds (default 2),
              * a collection source is eager and cost more than --max-source-cpu CPU-seconds
                (default 2) in the build, or
              * a tool call (schema, query on direct and on emulated columns, refresh of a
                column) started a process other than the reader's own helpers, or a detached one.
  all         cold, build, plans, getters, refresh, query, knowledge, sql

Every benchmark runs --runs times and prints the runs and their median as one JSON line.
`--released CHECKOUT` runs the same benchmark with the code of another checkout (the
released reader) first, so both are measured under the same machine load; the load average
is part of every result. Benchmarks write only below $FMCP_CACHE_DIR/bench (default cache
root when unset): set FMCP_CACHE_DIR to a scratch directory.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SQL = [
    ('top players at a club by ability',
     "SELECT name, current_ability, potential_ability FROM player_view WHERE club = 'Newcastle United' "
     "ORDER BY current_ability DESC LIMIT 25"),
    ('young high-potential players worldwide',
     "SELECT name, age, club, potential_ability FROM player_view WHERE age <= 21 AND potential_ability >= 150 "
     "ORDER BY potential_ability DESC LIMIT 50"),
    ('clubs by reputation', "SELECT name, reputation FROM club_view ORDER BY reputation DESC LIMIT 50"),
    ('players per nationality',
     "SELECT nationality, COUNT(*) AS players, ROUND(AVG(current_ability), 1) FROM player_view GROUP BY 1 "
     "ORDER BY 2 DESC LIMIT 20"),
    ('raw join person/player/team',
     "SELECT pe.first_name, pe.second_name, t.idx FROM player p JOIN person pe ON pe.idx = p.idx "
     "JOIN team t ON t.idx = pe.club_idx WHERE p.class = 'ACTUAL_PLAYER' LIMIT 2000"),
]


def load():
    return round(os.getloadavg()[0], 1)


def cache_root() -> Path:
    from fm_live_mcp.fmdb.engine import cache_root as root
    return root()


def bench_dir(name) -> Path:
    path = cache_root().parent / 'bench' / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def seed_plans(target: Path):
    """Copy the plan cache of the current cache root (derivation is not what `build` measures)."""
    source = cache_root() / 'plans'
    (target / 'fmdb' / 'plans').mkdir(parents=True, exist_ok=True)
    for path in source.glob('*.v2.json'):
        shutil.copyfile(path, target / 'fmdb' / 'plans' / path.name)


# --------------------------------------------------------------------------- single runs
def run_cold(args):
    t0 = time.time()
    from fm_live_mcp.fmdb.engine import Engine
    t1 = time.time()
    engine = Engine.open()
    t2 = time.time()
    try:
        people = engine.table_entries('people')[0]
        record = next(p for p in people if p)
        engine.get_property(record, 'Pfna')
        t3 = time.time()
    finally:
        engine.close()
    return {'import_s': round(t1 - t0, 2), 'engine_open_s': round(t2 - t1, 2), 'first_getter_s': round(t3 - t2, 2),
            'seconds': round(t3 - t0, 2)}


def run_build(args, empty_plans=False):
    from fm_live_mcp.fmdb import snapshot
    from fm_live_mcp.fmdb.engine import Engine
    cpu_started = time.process_time()
    root = bench_dir('plans-empty' if empty_plans else 'build') / 'fmdb'
    if empty_plans:
        for path in (root / 'plans').glob('*.json'):
            path.unlink()
    else:
        seed_plans(root.parent)
    engine = Engine.open()
    try:
        started = time.time()
        builder = snapshot.Build(engine, root=root, derive_plans=False)
        path = builder.run()
        seconds = time.time() - started
        with sqlite3.connect(path) as conn:
            ready = conn.execute("SELECT COUNT(*) FROM _fields WHERE status = 'ready'").fetchone()[0]
            stored = conn.execute("SELECT COUNT(DISTINCT table_name || '.' || column_name) FROM _column_state "
                                  "WHERE source = 'direct' AND status = 'ready'").fetchone()[0]
            try:
                sources = [{'table': t, 'mode': m, 'cpu_s': c} for t, m, c in conn.execute(
                    "SELECT table_name, mode, cpu_seconds FROM _source_tables WHERE mode = 'eager'")]
            except sqlite3.Error:
                sources = []
        out = {'seconds': round(seconds, 2), 'cpu_s': round(time.process_time() - cpu_started, 2),
               'ready_columns': ready, 'stored_columns': stored, 'eager_sources': sources, 'path': str(path),
               **{k: v for k, v in builder.timing.items() if isinstance(v, (int, float))}}
        if empty_plans:
            out['plan_stats'] = getattr(builder, 'plan_stats', {})
            out['seconds'] = builder.timing.get('plans')
        return out
    finally:
        engine.close()


def tier1_codes(engine):
    """The player codes of the curated view (attributes first), as the getter benchmark always used."""
    from fm_live_mcp.fmdb import views
    return list(dict.fromkeys(c for c, _ in views.PLAYER_RATINGS + views.PLAYER_OTHER + views.PLAYER_EXTRA
                              if not c.startswith('x:')))


def run_getters(args):
    from fm_live_mcp.fmdb import snapshot
    from fm_live_mcp.fmdb.engine import Engine
    engine = Engine.open()
    try:
        live = snapshot.enumerate_table(engine, 'people')
        players = [i for i, c in enumerate(live.classes) if c == 'ACTUAL_PLAYER']
        sample = random.Random(7).sample(players, args.players)
        codes = tier1_codes(engine)[:47]
        engine.prefetch([live.pointers[i] for i in sample])
        started, cpu = time.time(), time.process_time()
        instructions = 0
        for code in codes:
            for i in sample:
                result = engine.get_property(live.pointers[i], code)
                instructions += getattr(result.stats, 'instructions', 0) or 0
        seconds = time.time() - started
        cells = len(codes) * len(sample)
        return {'seconds': round(seconds, 2), 'cpu_s': round(time.process_time() - cpu, 2), 'cells': cells,
                'cells_per_s': round(cells / seconds), 'instructions': instructions, 'vm': type(engine.vm).__name__}
    finally:
        engine.close()


def _tool_engine():
    """An Engine the tool functions use without an MCP session."""
    from fm_live_mcp.fmdb import tools
    from fm_live_mcp.fmdb.engine import Engine
    engine = Engine.open()
    tools.engine_for = lambda bridge, session_id: engine
    return engine, tools


def run_refresh(args):
    from fm_live_mcp.fmdb import freshness, snapshot
    engine, tools = _tool_engine()
    try:
        path, *_ = tools.current_snapshot(engine)
        out = {}
        for label, pages in (('unchanged', 0), ('changed', args.pages)):
            if pages:
                conn = sqlite3.connect(path)
                known = [r[0] for r in conn.execute('SELECT page FROM _direct_pages')]
                pick = random.Random(11).sample(known, min(pages, len(known)))
                conn.executemany('UPDATE _direct_pages SET hash = hash + 1 WHERE page = ?', [(p,) for p in pick])
                conn.commit()
                conn.close()
            started, cpu = time.time(), time.process_time()
            r = freshness.refresh(engine, path, force=True)
            out[label] = {'seconds': round(time.time() - started, 3), 'cpu_s': round(time.process_time() - cpu, 3),
                          **{k: r.get(k) for k in ('pages_checked', 'pages_changed', 'blocks_checked', 'blocks_changed',
                                                   'rows_refreshed', 'rounds', 'page_read_seconds')}}
        out['seconds'] = out['unchanged']['seconds']
        return out
    finally:
        engine.close()


QUERIES = [
    ('direct', "SELECT name, club, current_ability, potential_ability FROM player_view WHERE club = 'Newcastle United' "
               "ORDER BY current_ability DESC LIMIT 25"),
    ('rows20', "SELECT name, club, morale, form, goals, transfer_value, condition FROM player_view "
               "WHERE current_ability > 172 ORDER BY current_ability DESC LIMIT 20"),
    ('rows200', "SELECT name, nationality, morale, form, goals, assists, average_rating, transfer_value "
                "FROM player_view WHERE current_ability BETWEEN 150 AND 160 LIMIT 200"),
    ('whole_column', "SELECT name, goals FROM player_view ORDER BY goals DESC LIMIT 10"),
]


def run_query(args):
    """First and repeated statements through the tool path on a snapshot built for this run."""
    engine, tools = _tool_engine()
    tools.plan_audit = lambda engine, path: None        # the audit has its own budget; not part of a statement
    try:
        started = time.time()
        tools.db_refresh(None, None)
        out = {'rebuild_s': round(time.time() - started, 2)}
        for round_name in ('first', 'repeat'):
            for name, sql in QUERIES:
                t, c = time.time(), time.process_time()
                r = tools.db_query(None, None, sql)
                out[f'{name}_{round_name}'] = {
                    'seconds': round(time.time() - t, 3), 'cpu_s': round(time.process_time() - c, 3),
                    'sql_s': r['seconds'], 'rows': r['row_count'], 'cells_computed': (r.get('computed') or {}).get('cells', 0),
                    'check_ms_ago': r['snapshot'].get('checked_ms_ago'), 'rows_refreshed': r['snapshot'].get('rows_refreshed')}
        out['seconds'] = sum(v['seconds'] for k, v in out.items() if k.endswith('_first'))
        return out
    finally:
        engine.close()


def run_knowledge(args):
    from fm_live_mcp.fmdb import knowledge_store as ks
    store = cache_root() / next(p.name for p in cache_root().iterdir() if (p / 'knowledge.sqlite').is_file())
    conn = sqlite3.connect(f'file:{store / "knowledge.sqlite"}?mode=ro', uri=True)
    scouted = [r[0] for r in conn.execute('SELECT idx FROM knowledge_player WHERE scouted = 1 ORDER BY idx')]
    conn.close()
    keys = sorted(random.Random(5).sample(scouted, min(args.players, len(scouted))))
    bridge, sid = ks._attach()
    try:
        t0 = time.time()
        capture = ks.capture((bridge, sid), keys)
        t1 = time.time()
        ks.star_capture((bridge, sid), keys)
        t2 = time.time()
        ks.search_capture((bridge, sid), keys)
        t3 = time.time()
    finally:
        bridge.detach()
    return {'players': len(keys), 'capture_s': round(t1 - t0, 2), 'stars_s': round(t2 - t1, 2),
            'search_s': round(t3 - t2, 2), 'seconds': round(t3 - t0, 2),
            'ms_per_player': round((t3 - t0) * 1000 / len(keys), 1), 'capture_phases': capture['cost']['phases']}


def run_sql(args):
    conn = sqlite3.connect(f'file:{args.snapshot}?mode=ro', uri=True)
    out = {}
    for name, sql in SQL:
        started = time.time()
        rows = conn.execute(sql).fetchall()
        out[name] = {'seconds': round(time.time() - started, 3), 'rows': len(rows)}
    out['seconds'] = round(sum(v['seconds'] for v in out.values()), 3)
    return out


HELPERS = ('fm_fast_reader', 'fm_live_helper', '/bin/ps', 'ps', 'lsof', '/usr/sbin/lsof')


def run_budget(args):
    """The cost gate (module docstring)."""
    import subprocess
    out = run_build(args)
    reasons = []
    if out['cpu_s'] > args.max_cpu:
        reasons.append(f"build: {out['cpu_s']} CPU-seconds > {args.max_cpu}")
    if args.max_wall and out['seconds'] > args.max_wall:
        reasons.append(f"build: {out['seconds']:.1f} s > {args.max_wall}")
    for source in out['eager_sources']:
        if (source['cpu_s'] or 0) > args.max_source_cpu:
            reasons.append(f"source {source['table']} is eager and cost {source['cpu_s']} CPU-seconds > "
                           f"{args.max_source_cpu}")
    # ---- tool calls: content check cost and processes started
    started_processes = []
    real_popen = subprocess.Popen

    class Recording(real_popen):
        def __init__(self, cmd, *a, **kw):
            argv = cmd if isinstance(cmd, (list, tuple)) else [cmd]
            started_processes.append({'argv': [str(x) for x in argv][:3],
                                      'detached': bool(kw.get('start_new_session'))})
            super().__init__(cmd, *a, **kw)

    engine, tools = _tool_engine()
    try:
        from fm_live_mcp.fmdb import freshness
        path, *_ = tools.current_snapshot(engine)
        subprocess.Popen = Recording
        try:
            cpu = time.process_time()
            check = freshness.refresh(engine, path, force=True)
            check_cpu = round(time.process_time() - cpu, 3)
            tools.db_schema(None, None)
            tools.db_query(None, None, QUERIES[0][1])
            tools.db_query(None, None, QUERIES[1][1])
            tools.db_refresh(None, None, columns=['nation.name_Nnam'])
            if args.manager:
                bridge, session = engine._bridge, getattr(engine, '_session', None)
                try:                            # the manager view needs the Bridge session of this engine
                    out['manager_query'] = tools.db_query(bridge, session, 'SELECT COUNT(*) FROM m_scouted_player_view',
                                                          view='manager').get('status', 'done')
                except Exception as exc:  # noqa: BLE001 - reported; the process check below still applies
                    out['manager_query'] = f'{type(exc).__name__}: {exc}'[:200]
        finally:
            subprocess.Popen = real_popen
    finally:
        engine.close()
    out['check'] = {'cpu_s': check_cpu, 'pages_checked': check.get('pages_checked'),
                    'pages_changed': check.get('pages_changed'), 'rows_refreshed': check.get('rows_refreshed')}
    # a check that had to repair rows is not the "nothing changed" case the budget is about
    if check_cpu > args.max_check_cpu and not check.get('blocks_changed'):
        reasons.append(f'content check with nothing changed: {check_cpu} CPU-seconds > {args.max_check_cpu}')
    foreign = [p for p in started_processes
               if p['detached'] or not any(Path(p['argv'][0]).name == Path(h).name for h in HELPERS)]
    out['processes_started_by_tool_calls'] = started_processes
    if foreign:
        reasons.append(f'tool calls started processes: {foreign}')
    out['budget'] = {'max_cpu_s': args.max_cpu, 'max_wall_s': args.max_wall or None,
                     'max_check_cpu_s': args.max_check_cpu, 'max_source_cpu_s': args.max_source_cpu,
                     'exceeded': reasons}
    return out


RUNNERS = {'budget': run_budget, 'cold': run_cold, 'build': run_build, 'plans': lambda a: run_build(a, empty_plans=True),
           'getters': run_getters, 'refresh': run_refresh, 'query': run_query,
           'knowledge': run_knowledge, 'sql': run_sql}


# --------------------------------------------------------------------------- driver
def child(what, args, checkout):
    """One run in a fresh process with `checkout` on PYTHONPATH; returns its result dict."""
    env = dict(os.environ, PYTHONPATH=str(checkout))
    cmd = [sys.executable, str(Path(__file__).resolve()), what, '--one', '--players', str(args.players),
           '--pages', str(args.pages)]
    if args.snapshot:
        cmd += ['--snapshot', args.snapshot]
    done = subprocess.run(cmd, env=env, cwd=str(checkout), capture_output=True, text=True)
    lines = [line for line in done.stdout.splitlines() if line.startswith('{')]
    if done.returncode or not lines:
        return {'error': (done.stderr or done.stdout)[-400:]}
    return json.loads(lines[-1])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('what', choices=sorted(RUNNERS) + ['all'])
    ap.add_argument('--runs', type=int, default=3)
    ap.add_argument('--released', help='checkout of the released reader to measure first')
    ap.add_argument('--players', type=int, default=300)
    ap.add_argument('--budget', type=float, default=60.0)
    ap.add_argument('--workers', type=int, default=0)
    ap.add_argument('--snapshot')
    ap.add_argument('--max-cpu', type=float, default=30.0, help='budget: CPU-seconds of one build')
    ap.add_argument('--max-wall', type=float, default=0.0, help='budget: seconds of one build (0: off)')
    ap.add_argument('--max-check-cpu', type=float, default=2.0, help='budget: CPU-seconds of an unchanged content check')
    ap.add_argument('--max-source-cpu', type=float, default=2.0, help='budget: CPU-seconds of an eager source')
    ap.add_argument('--pages', type=int, default=50, help='refresh: pages made to look changed')
    ap.add_argument('--manager', action='store_true',
                    help='budget: also run a manager-view query (builds the named knowledge population if missing)')
    ap.add_argument('--one', action='store_true', help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.one or args.what == 'budget':
        result = RUNNERS[args.what](args)
        result['load'] = load()
        print(json.dumps(result), flush=True)
        exceeded = (result.get('budget') or {}).get('exceeded')
        if exceeded:
            print('BUDGET EXCEEDED: ' + '; '.join(exceeded), file=sys.stderr, flush=True)
            return 1
        return 0
    names = ['cold', 'build', 'plans', 'getters', 'refresh', 'query', 'knowledge', 'sql'] if args.what == 'all' \
        else [args.what]
    for name in names:
        if name == 'sql' and not args.snapshot:
            continue
        runs = args.runs
        report = {'benchmark': name}
        for label, checkout in (('released', args.released), ('this', HERE)):
            if checkout is None or (label == 'released' and name == 'plans'):
                continue
            results = []
            for _ in range(runs):
                results.append(child(name, args, Path(checkout)))
                if label == 'released' and args.released and len(results) < runs:
                    pass
            good = [r['seconds'] for r in results if isinstance(r.get('seconds'), (int, float))]
            report[label] = {'median_s': round(statistics.median(good), 2) if good else None, 'runs': results}
        print(json.dumps(report), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
