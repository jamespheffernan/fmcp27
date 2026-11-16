"""Histories of people and clubs, computed for the people or clubs a statement names.

Tables (routes in `fmdb/history_read.py`, findings in docs/fmdb/HISTORIES.md):

* `person_playing_history`      starting playing history (`Plhs`: season, club, apps, goals, fee, loan)
* `person_non_playing_history`  starting non-playing history (`Pnph`: club, job, dates)
* `person_career_spells`        every club and job of the career so far, including this save's seasons
                                (PERSON_UI_HANDLER `erHw` StaffHistory)
* `person_career_totals`        career totals, honours and milestone counts (PERSON_UI_HANDLER)
* `player_injury_history`       injury history (PERSON_UI_HANDLER `b1SW` + server `Phis`)
* `person_season_statistics`    statistics of every season, club and competition scope (career rows
                                0xF1FB44 > block lists 0xF74E50 > client SeasonStats rows 0x39AF34;
                                `fmdb/history_season.py`)
* `club_league_history`         a club's league position per season (CLUB_UI_HANDLER `LgHs`)
* `club_transfer_history`       a club's transfers in and out per season of this save (CLUB_UI_HANDLER `PTin`/`PTou`)
* `competition_history`         a competition's past winners (COMPETITION_UI_HANDLER `hist`)
* `award_history`               an award's past winners (AWARD_UI_HANDLER `I20k`)

Cost rule: nothing is computed save-wide. A statement is first run against a temporary view in
which every value column records the person (or club) of the row it is read for
(`statement_keys`); only those are read, then stored until the game date changes. A statement
whose value columns would be read for more than MAX_KEYS people or clubs is refused with how to
narrow it (`sources.StatementTooWide`).
"""
from __future__ import annotations

import sqlite3
import time

from . import Column, SourceTable, StatementTooWide, current_statement, dry_run_connection
from . import _common as C
from .. import history_read as H

MAX_KEYS = 400                  # people or clubs one statement may have computed
DRY_RUN_S = 20.0
UI_REUSE_S = 300.0              # a PERSON handler read serves the person tables for this long (same game date)
LAYOUT = 'histories-1'
READ_DATE = Column('read_date', 'TEXT', 'game date on which the row was read (rows are re-read when it changes)')
PUBLIC = {'scope': 'public'}


# --------------------------------------------------------------------------- statement keys
def statement_keys(statement, table, key_column, value_columns, candidates_sql, engine=None):
    """The keys (person or club idx) of the rows the statement visits, by running it once on a
    read-only connection where `table` is a TEMP view of every candidate key that records each row
    it yields (and each value column read). A statement without a key restriction visits every
    candidate. None when the statement cannot be run that way.

    With an `engine` the statement is first run once with the on-demand session of the real run
    attached and nothing recorded: a filter on a column the game computes (person.person_type)
    reads NULL until that column is computed, and the recording run would then find fewer rows
    than the real run selects. The recording run itself stays on a plain connection, because the
    shadow views of the session change the join order and make it visit every candidate."""
    if not statement:
        return None
    sql, params, path = statement
    if not sql or not path:
        return None

    def run(conn, record):
        tmp = f'_hist_keys_{table}'
        conn.execute(f'CREATE TEMP TABLE {tmp}(k INTEGER PRIMARY KEY)')
        conn.execute(f'INSERT INTO {tmp} {candidates_sql}')
        conn.create_function('fm_history_need', 1, record, deterministic=False)
        conn.create_function('fm_history_visit', 1, lambda k: record(k) or 1, deterministic=False)
        cols = ', '.join(f'fm_history_need(k) AS "{c}"' for c in value_columns)
        # the view's own WHERE term runs for every row the statement visits after its key
        # constraints (person_idx = ?, IN (...), a join on the key) have been applied
        conn.execute(f'CREATE TEMP VIEW "{table}" AS SELECT NULL AS idx, k AS "{key_column}", {cols} '
                     f'FROM {tmp} WHERE fm_history_visit(k)')
        deadline = time.time() + DRY_RUN_S
        conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10000)
        return conn.execute(sql, params or [])

    if engine is not None:                         # computes the on-demand columns the statement filters on
        try:
            conn, close = dry_run_connection(engine, statement)
            try:
                cur = run(conn, lambda k: None)
                while cur.fetchmany(5000):
                    pass
            except sqlite3.Error:
                pass
            finally:
                close()
        except sqlite3.Error:
            pass
    need = set()

    def record(k):
        need.add(k)
        return None

    try:
        conn, close = dry_run_connection(None, statement)
    except sqlite3.Error:
        return None
    try:
        cur = run(conn, record)
        while cur.fetchmany(5000):
            if len(need) > MAX_KEYS:
                break
        return need
    except sqlite3.Error:
        return None
    finally:
        close()


def _read_marks(engine):
    """{(table, key): game date read} for keys whose read succeeded and gave no rows (kept for the
    process). A key whose read failed is not marked: the next statement that names it reads it again."""
    return engine.__dict__.setdefault('_history_read_marks', {})


NOT_READ_SHOWN = 5              # failed keys named in an answer; the rest are counted


class _Table:
    """One history table: which key it is computed for and how a batch of keys is read.

    `read_batch(keys)` returns (rows, failed): `failed` is [(key, reason)] for the keys the game
    did not answer. Those keys get no rows and no read mark, and the statement's answer names them
    (`not_read`), so a failed read is never the same answer as a key that has no history."""

    def __init__(self, engine, name, description, key_column, kind, columns, read_batch, source_note,
                 candidates_sql, narrow_hint):
        self.engine, self.name, self.key_column, self.kind = engine, name, key_column, kind
        self.columns = [Column('idx', 'INTEGER', 'row id'), *columns, READ_DATE]
        self.read_batch, self.candidates_sql, self.narrow_hint = read_batch, candidates_sql, narrow_hint
        self.description, self.source_note = description, source_note
        self.last = {}

    def value_columns(self):
        return [c.name for c in self.columns if c.name not in ('idx', self.key_column)]

    def compute(self, existing=frozenset()):
        engine = self.engine
        date = engine.game_date()
        statement = current_statement()
        need = statement_keys(statement, self.name, self.key_column, self.value_columns(), self.candidates_sql,
                              engine=engine)
        self.last = {'statement_keys': None if need is None else len(need)}
        if not need:
            return []
        if len(need) > MAX_KEYS:
            raise StatementTooWide(
                f'the statement would compute histories for more than {MAX_KEYS} {self.kind}s; {self.narrow_hint}')
        key_pos = [c.name for c in self.columns].index(self.key_column) - 1
        stored = {row[0] for row in existing if row[-1] == date}
        marks = _read_marks(engine)
        todo = sorted(k for k in need if k not in stored and marks.get((self.name, k)) != date)
        started, cpu = time.time(), time.process_time()
        rows, failed = self.read_batch(todo) if todo else ([], [])
        failed = [(k, str(reason)) for k, reason in failed]
        unread = {k for k, _ in failed}
        rows = [r for r in rows if r[key_pos] not in unread]      # a key is read whole or not at all
        got = {r[key_pos] for r in rows}
        for k in todo:
            if k not in got and k not in unread:
                marks[(self.name, k)] = date
        self.last.update({'read': len(todo), 'rows': len(rows), 'seconds': round(time.time() - started, 2),
                          'cpu_seconds': round(time.process_time() - cpu, 2), 'failed': failed})
        return [(*r, date) for r in rows]

    def not_read(self):
        """One line per key of the last statement whose read failed, with the reason."""
        failed = self.last.get('failed') or []
        lines = [f'{self.kind} {k}: {reason}' for k, reason in failed[:NOT_READ_SHOWN]]
        if len(failed) > NOT_READ_SHOWN:
            lines.append(f'and {len(failed) - NOT_READ_SHOWN} more {self.kind}(s)')
        return lines

    def coverage(self):
        x = self.last
        if not x.get('read'):
            return ''
        text = f"read {x['read']} {self.kind}(s): {x['rows']} rows, {x['seconds']} s"
        if x.get('failed'):
            text += '; unavailable: ' + '; '.join(f'{k}: {reason}' for k, reason in x['failed'][:NOT_READ_SHOWN])
        return text

    def source_table(self):
        return SourceTable(
            self.name, self.description, self.columns[1:], lambda: self.compute(),
            key='idx', mode='lazy', invalidation='append', identity=(self.key_column, 'entry', 'read_date'),
            replace_key=(self.key_column,), layout=LAYOUT, check_interval=0.0,
            new_rows=lambda existing: self.compute(existing), source_note=self.source_note,
            indexes=(self.key_column,), manager=PUBLIC, coverage=self.coverage, not_read=self.not_read,
            cost_note=f'computed for the {self.kind}s a statement names (at most {MAX_KEYS}); see docs/fmdb/HISTORIES.md')


# --------------------------------------------------------------------------- readers
def _people(engine, keys):
    pointers = C.live(engine, 'people').pointers
    return {k: pointers[k] for k in keys if 0 <= k < len(pointers) and pointers[k]}


def _getter_batch(engine, code, shape):
    def read(keys):
        people = _people(engine, keys)
        lists = H.getter_lists(engine, list(people.values()), [code])
        rows, notes = [], []
        for k, rec in people.items():
            value = lists[rec][code]
            if isinstance(value, H.Unavailable):
                notes.append((k, value.reason))
                continue
            rows += shape(k, value)
        return rows, notes
    return read


def _person_ui(engine, keys):
    """PERSON_UI_HANDLER values for these people. One handler read feeds every person table; it
    is kept for UI_REUSE_S on the same game date, so a profile asked as several statements (spells,
    totals, injuries) reads each person once."""
    cache = engine.__dict__.setdefault('_history_person_ui', {})
    date, now = engine.game_date(), time.time()
    todo = [k for k in keys if not (k in cache and cache[k][0] == date and now - cache[k][1] < UI_REUSE_S)]
    if todo:
        reader = H.UiReader(engine)
        try:
            for k in todo:
                cache[k] = (date, now, reader.read(H.ui_id(H.UI_PERSON, k), H.PERSON_KEYS, H.PERSON_DATA_KEYS))
        finally:
            reader.close()
    if len(cache) > 4 * MAX_KEYS:
        for k in sorted(cache, key=lambda k: cache[k][1])[:len(cache) - 2 * MAX_KEYS]:
            cache.pop(k, None)
    return {k: cache[k][2] for k in keys}


def _ui_batch(engine, shape, names):
    def read(keys):
        got = _person_ui(engine, keys)
        rows, notes = [], []
        for k, values in got.items():
            bad = [n for n in names if isinstance(values.get(n), H.Unavailable)]
            if bad:
                notes.append((k, values[bad[0]].reason))
                continue
            drew = sorted(n for n in names if (values.get('_rng') or {}).get(n))
            if drew:
                notes.append((k, f'reading {", ".join(drew)} drew random numbers (not stored)'))
                continue
            rows += shape(k, values)
        return rows, notes
    return read


def _season_batch(engine):
    """person_season_statistics: career statistics rows -> client SeasonStats rows (history_season)."""
    from .. import history_season as S

    def read(keys):
        people = _people(engine, keys)
        rows, notes = [], []
        if not people:
            return rows, notes
        reader = H.UiReader(engine)
        try:
            seasons = S.SeasonReader(engine, reader.vm)
            for k, pointer in people.items():
                got = seasons.read(pointer)
                if isinstance(got, H.Unavailable):
                    notes.append((k, got.reason))
                    continue
                n = 0
                for r in got:
                    if not S.keep(r):
                        continue
                    v = r['values']
                    rows.append((k, n, r['career_row'], r['scope'], S.SCOPE_NAMES[r['scope']], r['year'],
                                 r['team_idx'], r['competition_idx'], r['on_loan'], r['fee'],
                                 *[v[key] for key, *_ in S.KEYS]))
                    n += 1
        finally:
            reader.close()
        return rows, notes
    return read


def _club_batch(engine):
    def read(keys):
        clubs = C.live(engine, 'clubs').pointers
        rows, notes = [], []
        reader = H.UiReader(engine)
        try:
            for k in keys:
                if not (0 <= k < len(clubs) and clubs[k]):
                    continue
                values = reader.read(H.ui_id(H.UI_CLUB, k), H.CLUB_KEYS)
                value = values.get('league_history')
                if isinstance(value, H.Unavailable):
                    notes.append((k, value.reason))
                    continue
                rows += H.league_history_rows(k, value)
        finally:
            reader.close()
        return rows, notes
    return read


def _transfer_batch(engine):
    def read(keys):
        clubs = C.live(engine, 'clubs').pointers
        rows, notes = [], []
        reader = H.UiReader(engine)
        try:
            for k in keys:
                if not (0 <= k < len(clubs) and clubs[k]):
                    continue
                got = H.club_transfers(reader, k)
                if isinstance(got, H.Unavailable) and H.moved_under_the_read(got):
                    # pages or a file copied while the game ran (14 Nov 2026: four such stops in about
                    # 40 reads of a club while the owner played): once more on a fresh copy, then reported
                    reader.close()
                    reader = H.UiReader(engine)
                    got = H.club_transfers(reader, k)
                if isinstance(got, H.Unavailable):
                    notes.append((k, got.reason))
                    continue
                rows += H.club_transfer_rows(k, got)
        finally:
            reader.close()
        return rows, notes
    return read


def _record_batch(engine, live_kind, ui_type, keys, name, shape):
    """Rows of one UI handler list value for database records (competition, award) of these idx."""
    def read(idx_list):
        pointers = C.live(engine, live_kind).pointers
        rows, notes = [], []
        reader = H.UiReader(engine)
        try:
            for k in idx_list:
                if not (0 <= k < len(pointers) and pointers[k]):
                    continue
                values = reader.read(H.ui_id(ui_type, k), keys)
                value = values.get(name)
                if isinstance(value, H.Unavailable):
                    notes.append((k, value.reason))
                    continue
                rows += shape(k, value)
        finally:
            reader.close()
        return rows, notes
    return read


def _c(name, sql_type, meaning, references=None):
    return Column(name, sql_type, meaning, references=references)


def _season_columns():
    from .. import history_season as S
    return S.column_specs()


PERSON_KEY = _c('person_idx', 'INTEGER', 'the person (person.idx)', 'person')
ENTRY = _c('entry', 'INTEGER', 'position in the game\'s list')
NARROW_PERSON = ('name the people, e.g. WHERE person_idx = 123, person_idx IN (...), or join player_view '
                 'filtered by club (player_view.club_idx = 414; person.club_idx holds the team idx, team.idx, '
                 'of the team the person plays for, so it compares with team.idx, not club.idx)')
NARROW_CLUB = 'name the clubs, e.g. WHERE club_idx = 414 or club_idx IN (...)'
NARROW_COMP = 'name the competitions, e.g. WHERE competition_idx = 7 or competition_idx IN (...)'
NARROW_AWARD = 'name the awards, e.g. WHERE award_idx = 0 or award_idx IN (...)'
COMPS_SQL = 'SELECT idx FROM competition'
AWARDS_SQL = 'SELECT idx FROM award'
PEOPLE_SQL = 'SELECT idx FROM person'
CLUBS_SQL = 'SELECT idx FROM club'


def tables(engine) -> list[SourceTable]:
    resolvers = {}

    def _resolve(kind, ref):
        if not hasattr(ref, 'unique_id'):
            return None
        if kind not in resolvers:                   # built on first use, not at snapshot build
            resolvers[kind] = C.ref_resolver(engine, kind)
        return resolvers[kind](ref)

    def team_of(ref):
        return _resolve('teams', ref)

    def comp_of(ref):
        return _resolve('competitions', ref)

    specs = [
        _Table(engine, 'person_playing_history',
               'Starting playing history per season and club as the database holds it (Plhs): the seasons before '
               'this save started; seasons played in this save are in person_career_spells and player_season_stats',
               'person_idx', 'person',
               [PERSON_KEY, ENTRY, _c('year', 'INTEGER', 'season year'), _c('year_order', 'INTEGER', 'order within the year'),
                _c('team_idx', 'INTEGER', 'club side (team.idx)', 'team'),
                _c('competition_idx', 'INTEGER', 'division (competition.idx)', 'competition'),
                _c('joined', 'TEXT', 'date joined (ISO; NULL when unset)'), _c('left_date', 'TEXT', 'date left'),
                _c('on_loan', 'INTEGER', 'on loan'), _c('youth_team', 'INTEGER', 'youth team'),
                _c('apps', 'INTEGER', 'appearances'), _c('goals', 'INTEGER', 'goals'),
                _c('transfer_fee', 'INTEGER', 'transfer fee (game currency units)'),
                _c('tribunal_fee', 'INTEGER', 'tribunal fee flag'), _c('extras', 'INTEGER', 'Extras (hsfl)')],
               _getter_batch(engine, 'Plhs', lambda k, v: H.playing_history_rows(k, v, team_of, comp_of)),
               'emulated record getter Plhs (FILE_LLIST paging of Temporary/pl_hist_dt.cmt on the owner thread)',
               PEOPLE_SQL, NARROW_PERSON),
        _Table(engine, 'person_non_playing_history',
               'Starting non-playing history (Pnph): club, job and dates as the database holds them, i.e. the jobs '
               'before this save started; jobs taken in this save (all of a manager created with the career, '
               'whose Pnph is empty) are in person_career_spells',
               'person_idx', 'person',
               [PERSON_KEY, ENTRY, _c('team_idx', 'INTEGER', 'club side (team.idx)', 'team'),
                _c('joined', 'TEXT', 'date joined'), _c('left_date', 'TEXT', 'date left'),
                _c('job', 'INTEGER', 'job (editor enum mj+c; its labels are not in editor.fmf, see person_career_spells.job for the game wording)')],
               _getter_batch(engine, 'Pnph', lambda k, v: H.non_playing_history_rows(k, v, team_of)),
               'emulated record getter Pnph (Temporary/non_pl_hist_dt.cmt)', PEOPLE_SQL, NARROW_PERSON),
        _Table(engine, 'person_career_spells',
               "Every club and job of the person's career including this save (the profile's history list): "
               'player spells, loans and staff jobs with start and end dates',
               'person_idx', 'person',
               [PERSON_KEY, ENTRY, _c('team_idx', 'INTEGER', 'club or national side (team.idx)', 'team'),
                _c('started', 'TEXT', 'start date'), _c('ended', 'TEXT', 'end date (NULL: current)'),
                _c('job_type', 'INTEGER', 'JobType'), _c('job', 'TEXT', 'job as the game words it'),
                _c('years', 'TEXT', 'DateYearsRange as the game shows it')],
               _ui_batch(engine, lambda k, v: H.spell_rows(k, v.get('spells')), ['spells']),
               'PERSON_UI_HANDLER erHw (StaffHistory) in the UI VM', PEOPLE_SQL, NARROW_PERSON),
        _Table(engine, 'person_career_totals',
               'Career totals (all clubs, league, current club), honours and milestone counts, and the '
               "game's own flags for whether the history panels can be viewed",
               'person_idx', 'person',
               [PERSON_KEY, ENTRY, _c('total_apps', 'INTEGER', 'TotalCareerAppearances'),
                _c('total_goals', 'INTEGER', 'TotalCareerGoals'),
                _c('league_apps', 'INTEGER', 'TotalCareerLeagueAppearances'),
                _c('league_goals', 'INTEGER', 'TotalCareerLeagueGoals'),
                _c('club_apps', 'INTEGER', 'TotalCareerClubAppearances (current club)'),
                _c('club_goals', 'INTEGER', 'TotalCareerClubGoals'),
                _c('club_league_apps', 'INTEGER', 'TotalCareerClubLeagueAppearances'),
                _c('club_league_goals', 'INTEGER', 'TotalCareerClubLeagueGoals'),
                _c('league_apps_in_nation', 'INTEGER', 'TotalCareerLeagueAppearancesInCurrentNation'),
                _c('injuries', 'INTEGER', 'InjuriesHistoryCount'),
                _c('milestones', 'INTEGER', 'MilestoneTotalCount'), _c('milestone_awards', 'INTEGER', 'MilestoneAwardCount'),
                _c('milestone_honours', 'INTEGER', 'MilestoneHonoursCount'),
                _c('milestone_transfers', 'INTEGER', 'MilestoneTransfersCount'),
                _c('milestone_landmarks', 'INTEGER', 'MilestoneLandmarksCount'),
                _c('most_significant_milestone', 'TEXT', 'MostSignificantMilestoneString'),
                _c('milestone_tally', 'TEXT', 'MilestoneTallyString'),
                _c('can_view_career_stats', 'INTEGER', 'CanViewCareerStats'),
                _c('can_view_season_stats', 'INTEGER', 'CanViewSeasonStats'),
                _c('can_view_staff_history', 'INTEGER', 'CanViewStaffHistory')],
               _ui_batch(engine, lambda k, v: [H.totals_row(k, v)], ['total_apps', 'milestones']),
               'PERSON_UI_HANDLER (GNGR, Ny6I, h4UR, DGAq, 0F6G, y1oK, XA61, Dmwv, ZpBW, G3nh, lcn9, 2KD9, Ogrh, Cq7d)',
               PEOPLE_SQL, NARROW_PERSON),
        _Table(engine, 'player_injury_history',
               'Injury history as the profile shows it: date, injury, description, duration, severity',
               'person_idx', 'person',
               [PERSON_KEY, ENTRY, _c('injury_date', 'TEXT', 'InjuryDate'),
                _c('injury_idx', 'INTEGER', 'injury type (injury.idx), from the server list when its date agrees', 'injury'),
                _c('description', 'TEXT', 'InjuryDescription'), _c('duration', 'TEXT', 'InjuryDuration as worded'),
                _c('duration_days', 'INTEGER', 'InjuryDurationDays'), _c('severity', 'INTEGER', 'InjurySeverity'),
                _c('cause', 'INTEGER', 'InjuryCause'), _c('treatment', 'INTEGER', 'InjuryTreatment'),
                _c('recurrence', 'INTEGER', 'server iRec (label not in the registry)'),
                _c('is_current', 'INTEGER', 'server iCur (label not in the registry)')],
               _ui_batch(engine, lambda k, v: H.injury_rows(k, v.get('injuries'), v.get('injuries_raw')), ['injuries']),
               'PERSON_UI_HANDLER b1SW (InjuriesHistory) + server data Phis (Temporary/injury_histories_dt.cmt)',
               PEOPLE_SQL, NARROW_PERSON),
        _Table(engine, 'person_season_statistics',
               'Season statistics for every season of a player\'s career (seasons before this save and this '
               'save\'s, the current one included), per competition scope: the scope 5 total of every season '
               'and club, and scopes 0-4 where the player had games',
               'person_idx', 'person',
               [PERSON_KEY, ENTRY, _c('career_row', 'INTEGER', "position of the season in the game's career list"),
                _c('scope', 'INTEGER', 'statistics block (PlayerStatsScope): 0-5'),
                _c('scope_name', 'TEXT', 'Non Competitive, League, Cup, Continental, International, Overall (Club) '
                                         '(labels of the hand-built decoder; Overall (Club) = League + Cup + Continental)'),
                _c('year', 'INTEGER', 'season year'), _c('team_idx', 'INTEGER', 'club (team.idx)', 'team'),
                _c('competition_idx', 'INTEGER', 'the club\'s league that season (competition.idx)', 'competition'),
                _c('on_loan', 'INTEGER', 'on loan'), _c('transfer_fee', 'INTEGER', 'fee of the move into this club (NULL: none)'),
                *[_c(col, sql, meaning) for col, sql, meaning in _season_columns()]],
               _season_batch(engine),
               'emulated career statistics builder 0xF1FB44 (Temporary/pl_hist_dt.cmt, player_stats_hist_dt.cmt), '
               'block lists 0xF74E50 and the client SeasonStats row 0x39AF34',
               PEOPLE_SQL, NARROW_PERSON),
        _Table(engine, 'club_league_history',
               'League position per season of a club (the club history screen)', 'club_idx', 'club',
               [_c('club_idx', 'INTEGER', 'the club (club.idx)', 'club'), ENTRY,
                _c('group_index', 'INTEGER', 'list group as the game returns it'), _c('year', 'INTEGER', 'season year'),
                _c('season', 'TEXT', 'YearSeasonString'),
                _c('competition_idx', 'INTEGER', 'league (competition.idx)', 'competition'),
                _c('competition_name', 'TEXT', 'competition name as shown'),
                _c('competition_short_name', 'TEXT', 'CompetitionShortName'), _c('level', 'INTEGER', 'Level'),
                _c('teams', 'INTEGER', 'NumberOfTeams'), _c('position', 'INTEGER', 'LeaguePosition'),
                _c('fate', 'INTEGER', 'LeagueFate'), _c('graph_point', 'REAL', 'GraphPointY')],
               _club_batch(engine), 'CLUB_UI_HANDLER LgHs (Temporary/tc_league_history_dt.cmt)', CLUBS_SQL, NARROW_CLUB),
        _Table(engine, 'club_transfer_history',
               "A club's transfers in and out for every season of this save, as its transfer history screen "
               'lists them (person, fee as worded, buying and selling club)', 'club_idx', 'club',
               [_c('club_idx', 'INTEGER', 'the club (club.idx)', 'club'), ENTRY,
                _c('year', 'INTEGER', "season selected on the screen ('year' of data key Cpts)"),
                _c('direction', 'TEXT', "'in' (PastTransfersIncoming) or 'out' (PastTransfersOutgoing)"),
                _c('person_idx', 'INTEGER', 'Person (person.idx)', 'person'),
                _c('fee', 'TEXT', "fee as the screen words it (client key '220 ', no registry label)"),
                _c('buying_team_idx', 'INTEGER', 'BuyingTeam (team.idx)', 'team'),
                _c('selling_team_idx', 'INTEGER', "selling team (team.idx; client key 'TOst', no registry label)", 'team'),
                _c('selling_team_text', 'TEXT', "SellingTeamString: the seller as worded when there is no selling "
                                                  "team (e.g. 'Free Transfer'); NULL when selling_team_idx is set "
                                                  '(the screen names that team)'),
                _c('season_amount', 'INTEGER', 'PastTransfersInAmount / PastTransfersOutAmount of that season and '
                                               'direction (game currency units)')],
               _transfer_batch(engine),
               'CLUB_UI_HANDLER PTin/PTou/ptia/ptoa (server data Cpts) with the season selection set in the VM',
               CLUBS_SQL, NARROW_CLUB),
        _Table(engine, 'competition_history',
               "A competition's past winners as its History screen lists them (newest first): winner, runner-up, "
               'third, joint winner, play-off winner and host', 'competition_idx', 'competition',
               [_c('competition_idx', 'INTEGER', 'the competition (competition.idx)', 'competition'), ENTRY,
                _c('season', 'TEXT', 'Year as the game shows it (e.g. 2029/30)'),
                _c('missing_history', 'TEXT', "MissingHistoryString: why a season has no winners (e.g. "
                                              "'Competition didn't take place'); NULL for played seasons"),
                _c('first_team_idx', 'INTEGER', 'FirstPlaced (team.idx)', 'team'),
                _c('second_team_idx', 'INTEGER', 'SecondPlaced (team.idx)', 'team'),
                _c('third_team_idx', 'INTEGER', 'ThirdPlaced (team.idx)', 'team'),
                _c('joint_first_team_idx', 'INTEGER', 'JointFirstPlaced (team.idx)', 'team'),
                _c('playoff_winner_team_idx', 'INTEGER', 'PlayoffWinner (team.idx)', 'team'),
                _c('host_nation', 'TEXT', 'HostNation'), _c('host_stadium', 'TEXT', 'HostStadium')],
               _record_batch(engine, 'competitions', H.UI_COMPETITION, H.COMPETITION_KEYS, 'history',
                             H.competition_history_rows),
               'COMPETITION_UI_HANDLER hist (server data chst: GAME_COMP_MANAGER 0x1AC58F4 pages '
               'Temporary/comp_history_dt.cmt)', COMPS_SQL, NARROW_COMP),
        _Table(engine, 'award_history',
               "An award's past winners as its screen lists them: season, placed person and club with the "
               'statistics the screen shows', 'award_idx', 'award',
               [_c('award_idx', 'INTEGER', 'the award (award.idx)', 'award'), ENTRY,
                _c('season_entry', 'INTEGER', "position of the season in the game's list (0 = newest)"),
                _c('season', 'TEXT', 'DisplayString of the season (e.g. 2029 or 2029-2030)'),
                _c('winners_count', 'INTEGER', 'WinnersCount'),
                _c('place', 'INTEGER', 'position in Winners (0 = winner)'),
                _c('person_idx', 'INTEGER', 'Person (person.idx)', 'person'),
                _c('team_idx', 'INTEGER', 'Team (team.idx)', 'team'),
                _c('stat_value', 'TEXT', "StatValue text (sub-key 'ptvl', no registry label)"),
                _c('stat_name', 'TEXT', "StatValue caption (sub-key 'qvJ6', no registry label)"),
                _c('key_15', 'INTEGER', "client key '15  ' (no registry label)"),
                _c('appearances', 'INTEGER', 'Appearances'), _c('goals', 'INTEGER', 'Goals'),
                _c('assists', 'INTEGER', 'Assists'), _c('average_rating', 'REAL', 'AverageRating'),
                _c('clean_sheets', 'INTEGER', 'CleanSheets'), _c('red_cards', 'INTEGER', 'RedCards'),
                _c('man_of_match', 'INTEGER', 'ManOfMatch'), _c('golden_boot_points', 'REAL', 'GoldenBootPoints'),
                _c('manager_points', 'REAL', 'ManagerPoints'), _c('win_ratio', 'REAL', 'WinRatio')],
               _record_batch(engine, 'awards', H.UI_AWARD, H.AWARD_KEYS, 'past_winners', H.award_history_rows),
               'AWARD_UI_HANDLER I20k PastWinners (server data AwHi, AwSd; Temporary/award_year_hist_dt.cmt)',
               AWARDS_SQL, NARROW_AWARD),
    ]
    return [s.source_table() for s in specs]
