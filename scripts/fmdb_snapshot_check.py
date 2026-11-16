"""Live checks of the fmdb snapshot against the game's getter and the hand-built tools.

Usage: PYTHONPATH=. python scripts/fmdb_snapshot_check.py [--rows 200] [--json out.json]
           [--skip-differential] [--skip-crosscheck] [--skip-queries]

1. Differential: for every table with at least 1,000 rows, `--rows` random rows; every
   cell whose (table, column, class) state is `direct` is compared with the getter's value
   (PropertyVM, same conversion as the build). A disagreement demotes the plan in the plan
   cache (the next build emulates the column) and is reported with its exact count.
2. Cross-check: a dozen players (half from the managed squad, half elsewhere found with
   fm_find_save_players) read with Bridge.get_player(include_profile, include_wage,
   include_contract_dates, include_clubs, include_health) against player_view.
3. Three example queries through the fm_db_query code path, with timings.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import random
import sqlite3
import sys
import time

from fm_live_mcp.bridge import Bridge
from fm_live_mcp.fmdb import bulkplans, snapshot, tables, tools
from fm_live_mcp.fmdb.engine import cache_root

QUERIES = {
    'young_left_sided_under_wage_cap': """
        SELECT name, age, club, nationality, current_ability, potential_ability, left_foot,
               pos_defender_left, pos_wing_back_left, wage, contract_expires
        FROM player_view
        WHERE class != 'VIRTUAL_PLAYER' AND age <= 21 AND wage < 20000
          AND (left_foot >= 15 OR pos_defender_left >= 15 OR pos_wing_back_left >= 15)
        ORDER BY potential_ability DESC, current_ability DESC
        LIMIT 15""",
    'managed_contracts_expiring_12_months': """
        SELECT name, age, current_ability, potential_ability, wage, contract_expires
        FROM player_view
        WHERE (contracted_club_idx IN (SELECT club_idx FROM _managed) OR club_idx IN (SELECT club_idx FROM _managed))
          AND contract_expires <= date((SELECT game_date FROM _snapshot), '+12 months')
        ORDER BY contract_expires, name""",
    'clubs_by_reputation_in_nation': """
        SELECT name, reputation, division, city, balance
        FROM club_view
        WHERE nation = ?
        ORDER BY reputation DESC
        LIMIT 10""",
}
QUERY_PARAMS = {'clubs_by_reputation_in_nation': ['England']}


def differential(engine, path, rows_per_table, report):
    conn = sqlite3.connect(path)
    rng = random.Random(7)
    live_cache = {}

    def live_table(kind):
        if kind not in live_cache:
            live_cache[kind] = snapshot.enumerate_table(engine, kind)
        return live_cache[kind]

    store = snapshot.plan_store(engine)
    resolver = snapshot.Resolver({t: live_table(tables.RECORD_TYPES[r].table) for t, r in snapshot.TABLES.items()})
    out = {}
    demoted = []
    already = []        # mismatched, and not direct in the plan cache any more (demoted after this build)
    for table, n in conn.execute('SELECT table_name, rows FROM _tables ORDER BY table_name').fetchall():
        if n < 1000 or table not in snapshot.TABLES:      # collection tables have no getter plans to compare
            continue
        kind = tables.RECORD_TYPES[snapshot.TABLES[table]].table
        live = live_table(kind)
        columns = {c.name: c for c in snapshot.columns_for(engine.catalog, table)}
        direct = defaultdict(set)
        for column, cls in conn.execute("SELECT column_name, class FROM _column_state WHERE table_name=? "
                                        "AND source='direct' AND status='ready'", (table,)):
            direct[cls].add(column)
        idxs = [r[0] for r in conn.execute(f'SELECT idx FROM "{table}"')]
        sample = rng.sample(idxs, min(rows_per_table, len(idxs)))
        compared, mismatches, per_column = 0, 0, Counter()
        examples = {}
        started = time.time()
        for i in sample:
            cls = live.classes[i]
            names = sorted(direct.get(cls, ()))
            if not names:
                continue
            row = conn.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in names)} FROM "{table}" '
                               'WHERE idx=?', (i,)).fetchone()
            for name, stored in zip(names, row):
                col = columns[name]
                value = bulkplans.canonical(engine.get_property(live.pointers[i], col.code))
                if isinstance(value, bulkplans.Missing):
                    plan = store.get(cls, col.code) or {}
                    if plan.get('fallback') and value.reason.endswith('_fseeko'):
                        continue
                expected = snapshot.to_sql(col, i, value, resolver)
                compared += 1
                same = stored == expected or (isinstance(stored, float) and isinstance(expected, float)
                                               and abs(stored - expected) <= 1e-6 * max(1, abs(expected)))
                if not same:
                    mismatches += 1
                    per_column[(cls, col.code, name)] += 1
                    examples.setdefault(name, f'idx {i} {cls}: snapshot {stored!r} vs getter {expected!r}')
        for (cls, code, name), count in per_column.items():
            plan = store.get(cls, code)
            if plan and plan.get('status') == 'direct':
                store.plans[cls][code] = {**plan, 'status': 'emulate-only',
                                          'reason': f'differential check: {count} of {rows_per_table} rows '
                                                    f'disagreed ({examples[name]})'}
                demoted.append(f'{table}.{name} ({cls})')
            else:
                # The snapshot read this column with a direct plan that the plan cache has demoted
                # since (an earlier run of this check, or another process). The cache is right
                # already; the snapshot is rebuilt by the next query (tools.direct_plan_count).
                demoted.append(f'{table}.{name} ({cls})')
                already.append(f'{table}.{name} ({cls})')
        out[table] = {'rows_sampled': len(sample), 'cells_compared': compared, 'mismatches': mismatches,
                      'seconds': round(time.time() - started, 1),
                      'mismatched_columns': {f'{cls}/{name}': c for (cls, _, name), c in per_column.items()},
                      'examples': examples}
        print(f'differential {table}: {compared} cells, {mismatches} mismatches', flush=True)
    if demoted:
        store.save()
    report['differential'] = {'tables': out, 'demoted_plans': demoted, 'demoted_before_this_run': already,
                              'cells_compared': sum(t['cells_compared'] for t in out.values()),
                              'mismatches': sum(t['mismatches'] for t in out.values())}


ATTRIBUTE_ALIASES = {'free_kick_taking': 'free_kicks', 'rushing_out': 'rushing_out_tendency',
                     'tendency_to_punch': 'punching_tendency'}


def _expected_fields(player):
    out = {'date_of_birth': player.get('birth_date')}
    for name, value in (player.get('attributes') or {}).items():
        out[ATTRIBUTE_ALIASES.get(name, name)] = value
    profile = player.get('profile') or {}
    ability = profile.get('ability') or {}
    if ability:
        out['current_ability'] = ability.get('current')
        out['potential_ability'] = ability.get('potential_native_code')
    for name, value in (profile.get('positions') or {}).items():
        out['pos_' + name] = value
    for group in ('goalkeeping', 'hidden_attributes', 'personality'):
        for name, value in (profile.get(group) or {}).items():
            out[ATTRIBUTE_ALIASES.get(name, name)] = value
    feet = profile.get('feet') or {}
    if feet:
        out['left_foot'], out['right_foot'] = feet.get('left'), feet.get('right')
    health = player.get('health') or {}
    # The hand-built tool reads the stored condition. The game's own property (`condition`) is -1
    # while a player has injury days remaining, so the like-for-like column is `condition_stored`.
    for name, column in (('condition', 'condition_stored'), ('match_sharpness', 'match_sharpness'),
                         ('fatigue', 'fatigue')):
        if name in health:
            out[column] = health[name]
    return out


def session_rows(engine, path, sql, params=()):
    """Rows of a statement as dicts, read as fm_db_query reads them: the on-demand columns the
    statement names are computed for the rows it needs."""
    from fm_live_mcp.fmdb import ondemand, query
    with engine.lock:
        session = ondemand.Session(engine, path)
        try:
            session.plan(query.referenced_columns(path, sql, list(params)), sql)
            result = query.run_session(path, sql, list(params), session=session, max_rows=5000, time_limit_s=900.0)
        finally:
            session.finish()
    return [dict(zip(result['columns'], row)) for row in result['rows']]


def crosscheck(bridge, session, path, report):
    engine = tools.engine_for(bridge, session)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # every column of the view by name, so the on-demand ones are computed for the compared players
    view_columns = ', '.join('"' + r[1] + '"' for r in conn.execute('PRAGMA table_info(player_view)'))
    squad = bridge.get_managed_squad(session, include_clubs=True, include_profile=True, include_health=True)
    picks = [(p['player_ref'], 'managed') for p in squad['players'][:6]]
    for row in session_rows(engine, path, "SELECT name, date_of_birth FROM player_view WHERE on_loan = 1 "
                                          "AND current_ability >= 100 ORDER BY uid LIMIT 12"):
        if len(picks) >= 9:
            break
        found = bridge.find_save_players(session, row['name'], max_matches=10)
        for p in found.get('players', []):
            if p.get('birth_date') == row['date_of_birth'] and p.get('player_ref'):
                picks.append((p['player_ref'], 'on loan'))
                break
    others = conn.execute("SELECT name, date_of_birth FROM player_view WHERE class='ACTUAL_PLAYER' "
                          "AND club_idx NOT IN (SELECT club_idx FROM _managed) AND current_ability >= 120 "
                          "ORDER BY uid LIMIT 40").fetchall()
    for row in others:
        if len(picks) >= 15:
            break
        found = bridge.find_save_players(session, row['name'], max_matches=10)
        for p in found.get('players', []):
            if p.get('birth_date') == row['date_of_birth'] and p.get('player_ref'):
                picks.append((p['player_ref'], 'other club'))
                break
    results = []
    totals = Counter()
    for ref, origin in picks:
        got = bridge.get_player(session, ref, include_clubs=True, include_contract_dates=True, include_wage=True,
                                include_profile=True, include_health=True)
        player = got['player']
        rows = session_rows(engine, path, f'SELECT {view_columns} FROM player_view WHERE date_of_birth=? '
                                          'AND (name=? OR name=?)',
                            (player['birth_date'], player.get('display_name'), player.get('name')))
        if len(rows) != 1:
            results.append({'name': player.get('name'), 'origin': origin, 'error': f'{len(rows)} snapshot rows'})
            totals['unmatched_players'] += 1
            continue
        row = dict(rows[0])
        expected = _expected_fields(player)
        clubs = player.get('clubs') or {}
        # the tool's current_club is the club the player plays for (player_view.club), contract_club the
        # club holding the main contract (player_view.contracted_club), loan_club the borrowing club
        for key, column in (('current_club', 'club'), ('contract_club', 'contracted_club'), ('loan_club', 'loan_club')):
            if isinstance(clubs.get(key), dict):
                expected[column] = clubs[key]['name']
        dates = player.get('contract_dates') or {}
        if dates.get('expires'):
            expected['contract_expires'] = dates['expires']
        if dates.get('joined'):
            expected['date_joined'] = dates['joined']
        wage = player.get('wage') or {}
        weekly = wage.get('weekly_gbp', wage.get('amount_gbp_per_week', wage.get('weekly')))
        if weekly is not None:
            expected['wage'] = weekly
        matches, mismatches, nulls = 0, {}, {}
        for column, value in expected.items():
            if column not in row:
                continue
            if row[column] == value:
                matches += 1
            elif row[column] is None:
                nulls[column] = value          # pending or not provided by the getter: not a disagreement
            else:
                mismatches[column] = {'snapshot': row[column], 'tool': value}
        totals['fields_matched'] += matches
        totals['fields_mismatched'] += len(mismatches)
        totals['fields_null_in_snapshot'] += len(nulls)
        results.append({'name': player.get('display_name'), 'origin': origin, 'idx': row['idx'],
                        'matched': matches, 'mismatches': mismatches, 'null_in_snapshot': sorted(nulls),
                        'tool_wage': wage, 'not_compared': sorted(set(expected) - set(row))})
        print(f'crosscheck {player.get("display_name")}: {matches} match, {len(mismatches)} mismatch', flush=True)
    report['crosscheck'] = {'players': results, 'totals': dict(totals)}


def example_queries(bridge, session, report):
    out = {}
    for name, sql in QUERIES.items():
        started = time.time()
        try:
            result = tools.db_query(bridge, session, sql, QUERY_PARAMS.get(name))
            out[name] = {'sql': ' '.join(sql.split()), 'seconds': round(time.time() - started, 3),
                         'row_count': result['row_count'], 'columns': result['columns'],
                         'rows': result['rows'][:5], 'notes': result['notes'][1:],
                         'computed': result.get('computed'), 'snapshot': result.get('snapshot')}
        except Exception as exc:  # noqa: BLE001 - reported
            out[name] = {'sql': ' '.join(sql.split()), 'error': str(exc)}
        print(f'query {name}: {out[name].get("seconds")}s {out[name].get("row_count")} rows '
              f'{out[name].get("error", "")}', flush=True)
    report['queries'] = out


MANAGER_QUERY = """
    SELECT name, age, club, nationality, position, tackling, tackling_min, tackling_max,
           crossing_min, crossing_max, pace_min, pace_max, marking_min, scouted, own_club
    FROM m_player_view
    WHERE age <= 21 AND (position LIKE '%D (%L%' OR position LIKE '%WB (%L%')
      AND tackling_min >= 10 AND crossing_min >= 10
    ORDER BY tackling_min + crossing_min + COALESCE(pace_min, 0) DESC
    LIMIT 15"""


def manager_queries(bridge, session, report):
    """The manager-view example, first call (may build knowledge) and a warm repeat."""
    runs = []
    for attempt in range(12):
        started = time.time()
        try:
            result = tools.db_query(bridge, session, MANAGER_QUERY, view='manager')
        except Exception as exc:  # noqa: BLE001 - reported
            runs.append({'error': str(exc), 'seconds': round(time.time() - started, 2)})
            break
        run = {'seconds': round(time.time() - started, 2), 'status': result.get('status', 'done'),
               'row_count': result['row_count'], 'rows': result['rows'][:5], 'columns': result['columns'],
               'notes': result['notes'], 'coverage': result.get('coverage'), 'complete': result.get('complete')}
        runs.append(run)
        print(f'manager query: {run["status"]} {run["seconds"]}s {run["row_count"]} rows', flush=True)
        if run['status'] == 'done' and sum(1 for r in runs if r.get('status') == 'done') >= 2:
            break
    report['manager_query'] = {'sql': ' '.join(MANAGER_QUERY.split()), 'runs': runs}


class SnapshotNotReady(RuntimeError):
    """The cache has no snapshot for the loaded save yet (its first build is still running)."""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--rows', type=int, default=200)
    ap.add_argument('--json')
    ap.add_argument('--skip-differential', action='store_true')
    ap.add_argument('--skip-crosscheck', action='store_true')
    ap.add_argument('--skip-queries', action='store_true')
    ap.add_argument('--skip-manager', action='store_true')
    ap.add_argument('--materialise', help='comma-separated table.column list to build first via fm_db_refresh')
    args = ap.parse_args(argv)
    bridge = Bridge()
    session = bridge.attach()['session_id']
    engine = tools.engine_for(bridge, session)
    report = {}
    try:
        path, meta, refreshed, _, _ = tools.current_snapshot(engine, log=print)
        if meta is None:
            # A cache with no verified plans derives them in the background (tens of minutes);
            # there is nothing to check until that build has written a snapshot.
            raise SnapshotNotReady(f'no snapshot at {path} yet: {json.dumps(refreshed, default=str)[:400]}')
        report['snapshot'] = {'path': str(path), 'game_date': meta['game_date'], 'refreshed': refreshed}
        if args.materialise:
            started = time.time()
            result = tools.db_refresh(bridge, session, columns=args.materialise.split(','))
            report['materialise'] = {'seconds': round(time.time() - started, 1),
                                     'computed': result.get('computed')}
            print(f'materialised in {time.time() - started:.1f}s', flush=True)
        if not args.skip_queries:
            example_queries(bridge, session, report)
        if not args.skip_manager:
            manager_queries(bridge, session, report)
        if not args.skip_differential:
            with engine.lock:
                differential(engine, path, args.rows, report)
        if not args.skip_crosscheck:
            crosscheck(bridge, session, path, report)
    finally:
        text = json.dumps(report, indent=1, default=str)
        if args.json:
            open(args.json, 'w').write(text)
        else:
            print(text)
        engine.close()
        bridge.detach()
    return 0


if __name__ == '__main__':
    sys.exit(main())
