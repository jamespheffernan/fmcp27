"""`fm_get_match`: one match as the game's match screens present it: result, half-time score,
attendance, referee, goals with scorers and minutes, team statistics, every player's line with
ratings, substitutions and dismissals, and for retained full-detail matches the shot map.

`get_match_live` (the tool): the match is found in the light result index (record pointers,
keys and team words of every resident result, about 2.5 s cold, kept per fixture fingerprint)
and only that match's record, goal events, statistics frame and retained record are decoded,
by the same row builders as the snapshot tables (sources/matches.py), so no save-wide table is
built. The names come from the snapshot (team, competition, stadium, person) in one statement.
The rows are then shaped by `get_match` over a private in-memory database with the match
tables' columns, so the output is the one `get_match` gives over `fm_db_query`. A match that is
no longer resident (an old season the game has paged out) is answered from the snapshot match
tables when they are built."""
from __future__ import annotations

import sqlite3

PERSON_NAME = ("coalesce(nullif(p.common_name, ''), trim(coalesce(p.first_name, '') || ' ' || "
               "coalesce(p.second_name, '')))")

MATCH_SQL = f"""
SELECT m.*, c.name AS competition, h.name AS home_team, a.name AS away_team, s.name AS stadium,
       {PERSON_NAME} AS referee
FROM match m LEFT JOIN competition c ON c.idx = m.competition_idx
LEFT JOIN team h ON h.idx = m.home_team_idx LEFT JOIN team a ON a.idx = m.away_team_idx
LEFT JOIN stadium s ON s.idx = m.stadium_idx LEFT JOIN person p ON p.idx = m.referee_person_idx
WHERE {{where}} ORDER BY m.date DESC, m.idx DESC LIMIT 20"""

EVENT_SQL = f"""
SELECT e.source, e.kind, e.kind_label, e.side, e.minute, e.added_minute, e.person_idx,
       {PERSON_NAME} AS person, e.second_person_idx
FROM match_event e LEFT JOIN person p ON p.idx = e.person_idx
WHERE e.match_idx = ? ORDER BY e.minute, e.added_minute, e.seq"""

TEAM_SQL = 'SELECT * FROM match_team_stats WHERE match_idx = ? ORDER BY side'

PLAYER_SQL = f"""
SELECT ps.*, {PERSON_NAME} AS person FROM match_player_stats ps LEFT JOIN person p ON p.idx = ps.person_idx
WHERE ps.match_idx = ? ORDER BY ps.side, ps.started DESC, ps.slot"""

SHOT_SQL = f"""
SELECT sh.*, {PERSON_NAME} AS person FROM match_shot sh LEFT JOIN person p ON p.idx = sh.person_idx
WHERE sh.match_idx = ? ORDER BY sh.clock_raw"""


PASS_SQL = f"""
SELECT pa.displayed_minute, pa.second, pa.side, pa.outcome, {PERSON_NAME} AS passer,
       {PERSON_NAME.replace('p.', 'w.')} AS won_by, pa.end_state, pa.origin_x, pa.origin_y, pa.end_x, pa.end_y
FROM match_pass pa LEFT JOIN person p ON p.idx = pa.person_idx LEFT JOIN person w ON w.idx = pa.won_by_person_idx
WHERE pa.match_idx = ? AND pa.completed = 0 ORDER BY pa.clock_raw"""

PASS_SUMMARY_SQL = """
SELECT side, outcome, count(*) AS passes FROM match_pass WHERE match_idx = ? GROUP BY side, outcome ORDER BY side, outcome"""


def _records(result):
    cols = result.get('columns') or []
    return [dict(zip(cols, row)) for row in result.get('rows') or []]


def match_filter(match_idx=None, team=None, date=None, opponent=None, exact=True):
    """(WHERE clause, params) selecting the match; team names match exactly, or as substrings
    with exact=False."""
    if match_idx is not None:
        return 'm.idx = ?', [match_idx]
    clauses, params = [], []
    if date:
        clauses.append('m.date = ?')
        params.append(date)
    for name in (team, opponent):
        if name:
            if str(name).strip().isdigit():
                clauses.append('(m.home_team_idx = ? OR m.away_team_idx = ?)')
                params += [int(name), int(name)]
            elif exact:
                clauses.append('(h.name = ? OR a.name = ?)')
                params += [name, name]
            else:
                clauses.append('(h.name LIKE ? OR a.name LIKE ?)')
                params += [f'%{name}%', f'%{name}%']
    if not clauses:
        raise ValueError('Give match_idx, or a team (optionally with date and opponent)')
    return ' AND '.join(clauses), params


def get_match(query, match_idx=None, team=None, date=None, opponent=None):
    """`query(sql, params, max_rows)` runs fm_db_query; returns the shaped match or candidates."""
    where, params = match_filter(match_idx, team, date, opponent)
    first = query(MATCH_SQL.format(where=where), params, 20)
    if 'rows' not in first:
        # snapshot still building, or the match tables are pending in the background pass
        return {'state': 'snapshot_not_ready', 'detail': first}
    found = _records(first)
    if not found and match_idx is None:
        where, params = match_filter(match_idx, team, date, opponent, exact=False)
        found = _records(query(MATCH_SQL.format(where=where), params, 20))
    if not found:
        return {'state': 'not_found', 'filter': {'match_idx': match_idx, 'team': team, 'date': date,
                                                  'opponent': opponent}}
    if match_idx is None and date is None and opponent is None and len(found) > 1:
        # a team alone: its latest match
        found = found[:1]
    if len(found) > 1:
        return {'state': 'ambiguous', 'candidates': [
            {k: m[k] for k in ('idx', 'date', 'competition', 'home_team', 'away_team', 'home_goals', 'away_goals')}
            for m in found]}
    m = found[0]
    idx = m['idx']
    events = _records(query(EVENT_SQL, [idx], 500))
    teams = _records(query(TEAM_SQL, [idx], 2))
    lineups = _records(query(PLAYER_SQL, [idx], 200))
    full = m.get('detail_level') == 'full_events'
    shots = _records(query(SHOT_SQL, [idx], 200)) if full else []
    pass_summary = _records(query(PASS_SUMMARY_SQL, [idx], 20)) if full else []
    failed_passes = _records(query(PASS_SQL, [idx], 500)) if full else []
    side_name = {0: m['home_team'], 1: m['away_team']}
    for row in events + teams + lineups + shots + pass_summary + failed_passes:
        if 'side' in row and row['side'] in side_name:
            row['team'] = side_name[row['side']]
    score = f"{m['home_goals']}-{m['away_goals']}"
    if m.get('home_penalties') is not None:
        score += f" ({m['home_penalties']}-{m['away_penalties']} pens)"
    return {
        'state': 'found', 'match': m, 'score': score,
        'half_time': None if m.get('home_goals_half_time') is None
        else f"{m['home_goals_half_time']}-{m['away_goals_half_time']}",
        'goals': [e for e in events if e['source'] == 'result_vector'],
        'substitutions_and_dismissals': [e for e in events if e['source'] == 'statistics_frame'],
        'team_stats': teams, 'players': lineups, 'shots': shots,
        'pass_outcomes': pass_summary, 'failed_passes': failed_passes,
        'coverage': {
            'detail_level': m.get('detail_level'),
            'goals': m.get('goal_events_state'),
            'statistics': 'present' if teams else 'not archived for this match',
            'shots': 'present' if shots else 'only for retained full-detail matches',
            'passes': ('present; failed passes carry outcome, who won the ball and minute; the game stores '
                       'no intended recipient for them' if pass_summary else 'only for retained full-detail matches'),
        },
    }


# --------------------------------------------------------------------------- live path
LIVE_TABLES = ('match', 'match_event', 'match_team_stats', 'match_player_stats', 'match_shot', 'match_pass')
REUSE_S = 3.0                   # a collector younger than this is reused without a fingerprint check


def live_collector(engine):
    """A match collector kept on the engine while the fixture fingerprint is unchanged (results,
    frames and retained records already decoded are reused: a played result is final)."""
    import time
    from .sources import fixture_tables
    from .sources.matches import _Collector
    memo = engine.__dict__.get('_fmdb_match_tool')
    now = time.time()
    if memo is not None and now - memo[2] < REUSE_S:
        return memo[1]
    fp = fixture_tables.fingerprint(engine)
    if memo is None or memo[0] != fp:
        memo = (fp, _Collector(engine), now)
    else:
        memo = (fp, memo[1], now)
    engine.__dict__['_fmdb_match_tool'] = memo
    return memo[1]


def snapshot_query(engine, path, sql, params, max_rows=2000):
    """One statement over the snapshot's core tables with their on-demand columns (what
    fm_db_query does, without the collection pre-pass or the plan audit)."""
    from . import ondemand, query
    reads = query.referenced_columns(path, sql, params)
    with engine.lock:
        session = ondemand.Session(engine, path)
        try:
            session.plan(reads, sql)
            return query.run_session(path, sql, params, session=session, max_rows=max_rows)
        finally:
            session.finish()


def _ids(values):
    return ', '.join(str(int(v)) for v in sorted(set(values))) or 'NULL'


CHUNK = 1000        # idxs per IN list: a statement stays far below query.MAX_SQL whatever the candidates


def _chunked(sq, template, values):
    """Rows of `template` (one `{ids}` IN list) over `values` in chunks of CHUNK idxs, so the
    statement does not grow with the number of candidates."""
    values = sorted({int(v) for v in values})
    rows = []
    for i in range(0, len(values), CHUNK):
        rows += sq(template.format(ids=_ids(values[i:i + CHUNK])), []).get('rows') or []
    return rows


def _team_names(engine, sq, idxs):
    """{team idx: name} through the snapshot (team.name is an emulated getter, about 3 ms a team:
    66,021 teams would take 200 s, so only candidate teams are named; kept per engine)."""
    memo = engine.__dict__.setdefault('_fmdb_match_team_names', {})
    want = [i for i in set(idxs) if i not in memo]
    for idx, name in _chunked(sq, 'SELECT idx, name FROM team WHERE idx IN ({ids})', want):
        memo[idx] = name
    return {i: memo.get(i) for i in idxs}


def _managed(sq):
    """(team idxs, club idxs) of the user's career (`_managed`)."""
    rows = sq('SELECT team_idx, club_idx FROM _managed', []).get('rows') or []
    return {r[0] for r in rows if r[0] is not None}, {r[1] for r in rows if r[1] is not None}


def _team_ids(engine, sq, index, name, exact):
    """Team idxs a `team`/`opponent` argument names: a number is a team idx; otherwise the teams
    whose name equals `name` (exact) or contains it. Candidates: the teams of clubs whose stored
    name starts the given name or contains it (club.name is a direct column), then, when none
    matches, the clubless teams (national teams) that have a resident result. Of several
    substring matches the user's own team, else his club's teams, are preferred."""
    if str(name).strip().isdigit():
        return {int(name)}

    def matches(names):
        if exact:
            return {i for i, n in names.items() if n == name}
        low = name.lower()
        found = {i for i, n in names.items() if n and low in n.lower()}
        if len(found) > 1:
            own_teams, own_clubs = _managed(sq)
            if found & own_teams:
                return found & own_teams
            mine = {r[0] for r in _chunked(sq, 'SELECT idx FROM team WHERE idx IN ({ids}) AND club_idx IN '
                                               '(SELECT club_idx FROM _managed)', found)} if own_clubs else set()
            if mine:
                return mine
        return found

    teams = [r[0] for r in sq("SELECT idx FROM team WHERE club_idx IN (SELECT idx FROM club WHERE "
                              "? LIKE name || '%' OR name LIKE ?)", [name, f'%{name}%']).get('rows') or []]
    if teams:
        found = matches(_team_names(engine, sq, teams))
        if found:
            return found
    played = {t for e in index.values() for t in (e['home_team_idx'], e['away_team_idx']) if t is not None}
    clubless = [r[0] for r in _chunked(sq, 'SELECT idx FROM team WHERE club_idx IS NULL AND idx IN ({ids})', played)]
    return matches(_team_names(engine, sq, clubless))


def _select(index, match_idx, home_away, date, opponents):
    out = []
    for i, e in index.items():
        if match_idx is not None and i != match_idx:
            continue
        teams = {e['home_team_idx'], e['away_team_idx']}
        if home_away is not None and not teams & home_away:
            continue
        if opponents is not None and not teams & opponents:
            continue
        if date and e['date'] != date:
            continue
        out.append(i)
    return sorted(out, key=lambda i: (index[i]['date'], i), reverse=True)[:20]


NAME_SQL = f"""
SELECT 'team' AS kind, idx, name FROM team WHERE idx IN ({{teams}})
UNION ALL SELECT 'competition', idx, name FROM competition WHERE idx IN ({{comps}})
UNION ALL SELECT 'stadium', idx, name FROM stadium WHERE idx IN ({{stadiums}})
UNION ALL SELECT 'person', p.idx, {PERSON_NAME} FROM person p WHERE p.idx IN ({{people}})"""


def _names(sq, teams, comps, stadiums, people):
    def ids(values):
        return ', '.join(str(int(v)) for v in sorted({v for v in values if v is not None})) or 'NULL'
    got = sq(NAME_SQL.format(teams=ids(teams), comps=ids(comps), stadiums=ids(stadiums), people=ids(people)), [])
    out = {}
    for kind, idx, name in got.get('rows') or []:
        out[(kind, idx)] = name
    return out


def _memory_db(tables_by_name, rows_by_table, names):
    """A private in-memory database with the match tables' columns holding `rows_by_table`, and
    name tables holding what `get_match`'s statements join."""
    from . import sources
    db = sqlite3.connect(':memory:')
    for name, t in tables_by_name.items():
        cols = sources._columns(t)
        db.execute(f'CREATE TABLE "{name}" ({", ".join(chr(34) + c.name + chr(34) for c in cols)})')
        rows = rows_by_table.get(name, [])
        if not rows:
            continue
        auto = not any(c.name == 'idx' for c in t.columns)
        data = [(n, *r) for n, r in enumerate(rows)] if auto else rows
        db.executemany(f'INSERT INTO "{name}" VALUES ({", ".join("?" * len(cols))})', data)
    db.executescript('CREATE TABLE team(idx INTEGER PRIMARY KEY, name TEXT); '
                     'CREATE TABLE competition(idx INTEGER PRIMARY KEY, name TEXT); '
                     'CREATE TABLE stadium(idx INTEGER PRIMARY KEY, name TEXT); '
                     'CREATE TABLE person(idx INTEGER PRIMARY KEY, common_name TEXT, first_name TEXT, '
                     'second_name TEXT);')
    for (kind, idx), name in names.items():
        if kind == 'person':
            db.execute('INSERT OR REPLACE INTO person VALUES (?, ?, NULL, NULL)', (idx, name))
        else:
            db.execute(f'INSERT OR REPLACE INTO {kind} VALUES (?, ?)', (idx, name))

    def query(sql, params, max_rows):
        cur = db.execute(sql, params)
        return {'columns': [d[0] for d in cur.description], 'rows': cur.fetchmany(max_rows)}
    return query


def get_match_live(engine, path, match_idx=None, team=None, date=None, opponent=None, *, fallback=None):
    """`get_match`'s answer from the live game for one match (module docstring). `fallback`
    is the fm_db_query callable used when the match is not resident."""
    import time
    from .sources import matches as M
    started = time.time()
    team, opponent = (None if v is None else str(v).strip() for v in (team, opponent))
    if match_idx is None and not team:
        match_filter()                                   # raises the selector error
    sq = lambda sql, params: snapshot_query(engine, path, sql, params)  # noqa: E731
    with engine.lock:
        col = live_collector(engine)
        index = col.index()
        found = []
        for exact in (True, False):
            home_away = _team_ids(engine, sq, index, team, exact) if team else None
            opponents = _team_ids(engine, sq, index, opponent, exact) if opponent else None
            found = _select(index, match_idx, home_away, date, opponents)
            if found or match_idx is not None:
                break
        loaded = _loaded(engine)
        pick = _loaded_pick(loaded, index, found, match_idx, home_away if team else None,
                            opponents if opponent else None, date)
        if pick is not None:
            return _loaded_answer(engine, sq, pick, started)
        if not found:
            if fallback is not None:
                out = get_match(fallback, match_idx, team, date, opponent)
                out.setdefault('source', 'snapshot match tables (the match is not resident in the game)')
                _attach_ratings(out, loaded)
                return out
            return {'state': 'not_found', 'filter': {'match_idx': match_idx, 'team': team, 'date': date,
                                                      'opponent': opponent}}
        if match_idx is None and date is None and opponent is None:
            found = found[:1]
        chosen = found[0] if len(found) == 1 else None
        tables = {t.name: t for t in M._tables(engine) if t.name in LIVE_TABLES}
        rows = {'match': list(M.match_rows(col, found))}
        if chosen is not None:
            rows['match_event'] = list(M.event_rows(col, [chosen]))
            rows['match_team_stats'] = list(M.team_rows(col, [chosen]))
            rows['match_player_stats'] = list(M.player_rows(col, [chosen]))
            if rows['match'] and rows['match'][0][-1] == 'full_events':
                rows['match_shot'] = list(M.shot_rows(col, {chosen}))
                rows['match_pass'] = list(M.pass_rows(col, {chosen}))
        decoded = time.time() - started
        m = rows['match']
        people = {r[23] for r in m}
        for name, pos in (('match_event', (6,)), ('match_player_stats', (3,)), ('match_shot', (3,)),
                          ('match_pass', (3, 9))):
            for r in rows.get(name, ()):
                people.update(r[p] for p in pos)
        names = _names(sq, [x for r in m for x in (r[6], r[7])], [r[3] for r in m], [r[8] for r in m], people)
    out = get_match(_memory_db(tables, rows, names), found[0] if chosen is not None else None,
                    *((None, None, None) if chosen is not None else (team, date, opponent)))
    if chosen is None and out.get('state') == 'found':
        out = get_match(_memory_db(tables, rows, names), out['match']['idx'])
    out['source'] = 'live game (this match only)'
    _attach_ratings(out, loaded)
    out['seconds'] = {'decode': round(decoded, 2), 'total': round(time.time() - started, 2)}
    return out


# --------------------------------------------------------------------------- loaded match ratings
ARCHIVED_RATING = ('not stored: archived matches keep the final rating (statistics frame, stored hundredths) and '
                   'the counters, not the inputs the components need (the MATCH_PLAYER position spells +0x1AC0, '
                   'goal items +0x1AA8, the team expectation and the model entry): those live in the match '
                   'engine\'s MATCH_PLAYER objects, which exist only while the match is loaded')


def _loaded(engine):
    """Loaded matches with rating breakdowns (fmdb/match_rating.py), each with its `match.idx`; [] when none."""
    from . import match_rating as mr
    from .sources import _common as C
    try:
        ms = mr.loaded_matches(engine.read, engine.base)
    except ValueError:
        return []
    teams = C.index_of(engine, 'teams')
    people = C.index_of(engine, 'people')
    for m in ms:
        m['team_idx'] = [teams.get(s['team']) for s in m['sides']]
        m['idx'] = (int(m['date'].replace('-', '')) * 100000 + m['team_idx'][0]
                    if m['date'] and m['team_idx'][0] is not None else None)
        for p in m['players']:
            p['person_idx'] = people.get(p['person'])
            p['team_idx'] = m['team_idx'][p['side']]
    return ms


def _loaded_pick(loaded, index, found, match_idx, home_away, opponents, date):
    """The loaded match the filter asks for when the game has no result for it yet (it is not in the
    result index) and it is the newest match of the filter."""
    for m in loaded:
        if m['idx'] is None or m['idx'] in index:
            continue
        teams = set(m['team_idx'])
        if match_idx is not None and match_idx != m['idx']:
            continue
        if home_away is not None and not teams & home_away:
            continue
        if opponents is not None and not teams & opponents:
            continue
        if date and m['date'] != date:
            continue
        if match_idx is None and found and index[found[0]]['date'] > m['date']:
            continue
        return m
    return None


def _loaded_answer(engine, sq, m, started):
    import time
    from .sources.match_state import screen_stats_rows
    names = _names(sq, m['team_idx'], [], [], [p['person_idx'] for p in m['players']])
    team = {s: names.get(('team', t)) for s, t in enumerate(m['team_idx'])}
    stats = [dict(zip(('client', 'side', 'team_idx', 'date', 'competition_idx', 'shots', 'shots_on_target',
                       'expected_goals', 'passes_attempted', 'passes_completed', 'corners', 'possession_time_raw'), r))
             for r in screen_stats_rows(engine.read, engine.base) if r[0] == m['client']]
    for s in stats:
        s['team'] = team.get(s['side'])
    players = []
    for p in m['players']:
        row = {'side': p['side'], 'team': team.get(p['side']), 'slot': p['slot'], 'person_idx': p['person_idx'],
               'person': names.get(('person', p['person_idx']))}
        if 'breakdown' in p:
            row['rating'] = p['breakdown']['rating']
            row['rating_breakdown'] = p['breakdown']
        else:
            row['rating_breakdown'] = {'state': 'unavailable', 'reason': p['unavailable']}
        players.append(row)
    goals = [s['goals'] for s in m['sides']]
    return {
        'state': 'loaded',
        'match': {'idx': m['idx'], 'date': m['date'], 'competition_index': m['competition_index'],
                  'home_team_idx': m['team_idx'][0], 'away_team_idx': m['team_idx'][1], 'home_team': team[0],
                  'away_team': team[1], 'home_goals': goals[0], 'away_goals': goals[1],
                  'match_minutes': m['match_minutes']},
        'score': f'{goals[0]}-{goals[1]}', 'team_stats': stats, 'players': players,
        'coverage': {'result': 'the game has not archived a result for this match yet: score and statistics are '
                               'the match engine\'s', 'rating_breakdown': 'present for every rated player'},
        'source': 'loaded match (match engine objects)',
        'seconds': {'total': round(time.time() - started, 2)},
    }


def _attach_ratings(out, loaded):
    """`rating_breakdown` per player where the match's MATCH_PLAYER objects exist (the loaded match)."""
    if out.get('state') != 'found':
        return
    idx = out['match'].get('idx')
    m = next((m for m in loaded if m['idx'] == idx), None)
    if m is None:
        out.setdefault('coverage', {})['rating_breakdown'] = ARCHIVED_RATING
        return
    by_person = {(p['side'], p['person_idx']): p for p in m['players']}
    for row in out.get('players', []):
        p = by_person.get((row.get('side'), row.get('person_idx')))
        if p is not None:
            row['rating_breakdown'] = p.get('breakdown') or {'state': 'unavailable', 'reason': p.get('unavailable')}
    out.setdefault('coverage', {})['rating_breakdown'] = 'present where the loaded match has the player'
