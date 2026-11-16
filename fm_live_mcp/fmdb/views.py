"""Views over the snapshot tables (created by `snapshot.Build` after the tables are written).

* `<table>_labelled`: every column plus `<column>_label` for enum columns (labels from
  `_enum_labels`).
* curated manager views: `player_view`, `club_view`, `staff_view`, `competition_view`
  (see `CURATED`). A curated column is included only when its source column exists in
  the snapshot, so a view never invents a value.
"""
from __future__ import annotations

import re


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def _columns(conn, table):
    return [r[1] for r in conn.execute(f'PRAGMA table_info({_q(table)})')]


def _label(table, alias, column):
    return (f"(SELECT label FROM _enum_labels WHERE table_name='{table}' AND column_name='{column}' "
            f"AND value={alias}.{_q(column)})")


def create_views(conn):
    tables = [r[0] for r in conn.execute("SELECT table_name FROM _tables ORDER BY table_name")]
    for t in tables:
        enum_cols = [r[0] for r in conn.execute(
            "SELECT DISTINCT column_name FROM _enum_labels WHERE table_name=?", (t,))]
        if not enum_cols:
            continue
        extra = ', '.join(f'{_label(t, "t", c)} AS {_q(c + "_label")}' for c in enum_cols)
        conn.execute(f'CREATE VIEW {_q(t + "_labelled")} AS SELECT t.*, {extra} FROM {_q(t)} t')
    conn.execute('CREATE TABLE IF NOT EXISTS _view_columns(view TEXT, column_name TEXT, base_table TEXT, '
                 'base_column TEXT)')
    for t in tables:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='view' AND name=?", (t + '_labelled',)).fetchone():
            enum_cols = {r[0] for r in conn.execute(
                "SELECT DISTINCT column_name FROM _enum_labels WHERE table_name=?", (t,))}
            conn.executemany('INSERT INTO _view_columns VALUES (?, ?, ?, ?)',
                             [(t + '_labelled', c, t, c) for c in _columns(conn, t)]
                             + [(t + '_labelled', c + '_label', t, c) for c in enum_cols])
    for name, builder in CURATED.items():
        built = builder(conn, set(tables))
        if built:
            sql, deps = built
            conn.execute(f'CREATE VIEW {_q(name)} AS {sql}')
            conn.execute('INSERT OR REPLACE INTO _build VALUES (?, ?)', (f'view:{name}', sql))
            conn.executemany('INSERT INTO _view_columns VALUES (?, ?, ?, ?)',
                             [(name, alias, table, column) for alias, table, column in deps])
    from . import sources                 # resolved views over collection tables (contract_view, ...)
    try:
        sources.create_views(conn)
    except Exception:  # noqa: BLE001 - core views stand without them
        pass




def recreate_views(conn):
    """Drop and rebuild every view of an existing snapshot (after a views.py change) without a rebuild."""
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall():
        conn.execute(f'DROP VIEW {_q(name)}')
    conn.execute('DROP TABLE IF EXISTS _view_columns')
    conn.execute("DELETE FROM _build WHERE key LIKE 'view:%'")
    create_views(conn)


class _Select:
    """Collect `expr AS alias` items by catalog code, keeping only columns that exist.

    Columns are looked up in `_fields` by (table, code), so a view never depends on the
    de-duplicated snake_case names and never invents a value. Every item records the base
    columns it reads (`deps`, written to `_view_columns`) so fm_db_query can tell which
    pending base columns a query really needs."""

    def __init__(self, conn):
        self.conn = conn
        self.codes, self.status, self.names = {}, {}, set()
        for table, column, code, status in conn.execute(
                'SELECT table_name, column_name, code, status FROM _fields ORDER BY rowid'):
            self.names.add((table, column))
            if code:
                self.codes.setdefault((table, code), column)   # first column of a code (not a second member)
                self.status[(table, column)] = status
        # A column the getter computes on demand for more than a tenth of its rows is not 'ready'
        # here: where a view can choose (a display name over several name codes), it reads the
        # stored columns, as a build that had not emulated the others did. Such a column is still
        # selectable by name.
        try:
            for table, column in conn.execute(
                    "SELECT table_name, column_name FROM _column_state GROUP BY table_name, column_name "
                    "HAVING 10 * SUM(CASE WHEN status = 'on_demand' THEN rows ELSE 0 END) > SUM(rows)"):
                if self.status.get((table, column)) == 'ready':
                    self.status[(table, column)] = 'on_demand'
        except Exception:  # noqa: BLE001 - a snapshot without _column_state: every column counts as stored
            pass
        self.items = []
        self.deps = []

    def c(self, table, code):
        """Quoted column name for (table, code), or None."""
        name = self.codes.get((table, code))
        return _q(name) if name else None

    def _add(self, sql, as_name, deps):
        taken = self.__dict__.setdefault('taken', set())
        if as_name in taken:
            return
        taken.add(as_name)
        self.items.append(f'{sql} AS {_q(as_name)}')
        self.deps += [(as_name, t, c) for t, c in deps]

    def col(self, alias, table, code, as_name):
        name = self.codes.get((table, code))
        if name:
            self._add(f'{alias}.{_q(name)}', as_name, [(table, name)])
        return name

    def first(self, alias, table, codes, as_name, extra_deps=()):
        """COALESCE over the codes that exist; columns that are not ready are skipped when a
        ready one exists (a display name should not wait on an emulated duplicate)."""
        names = [n for n in (self.codes.get((table, c)) for c in codes) if n]
        ready = [n for n in names if self.status.get((table, n)) == 'ready']
        names = ready or names
        parts = [f"NULLIF({alias}.{_q(n)}, '')" for n in names]
        if not parts:
            return False
        sql = parts[0] if len(parts) == 1 else f'COALESCE({", ".join(parts)})'
        self._add(sql, as_name, [(table, n) for n in names] + list(extra_deps))
        return True

    def named(self, alias, table, column, as_name):
        """A column by its snapshot name (for columns that share a code, e.g. a statistic's matches)."""
        if (table, column) in self.names:
            self._add(f'{alias}.{_q(column)}', as_name, [(table, column)])
            return column
        return None

    def label(self, alias, table, code, as_name):
        name = self.codes.get((table, code))
        if name:
            self._add(_label(table, alias, name), as_name, [(table, name)])

    def raw(self, sql, as_name, deps=()):
        self._add(sql, as_name, deps)

    def sql(self):
        return ',\n  '.join(self.items)

    def done(self, joins):
        return 'SELECT\n  ' + self.sql() + '\n' + '\n'.join(joins), self.deps


GAME_DATE = '(SELECT game_date FROM _snapshot LIMIT 1)'


def _age(expr):
    return (f"CASE WHEN {expr} IS NULL THEN NULL ELSE "
            f"CAST(strftime('%Y', {GAME_DATE}) AS INTEGER) - CAST(strftime('%Y', {expr}) AS INTEGER) - "
            f"(strftime('%m-%d', {GAME_DATE}) < strftime('%m-%d', {expr})) END")


def _person_name(s, alias):
    first, second, common = (s.c('person', c) for c in ('Pfna', 'Psna', 'Pcna'))
    if first and second and common:
        s.raw(f"COALESCE(NULLIF({alias}.{common}, ''), TRIM(COALESCE({alias}.{first}, '') || ' ' || "
              f"COALESCE({alias}.{second}, '')))", 'name',
              [('person', s.codes[('person', c)]) for c in ('Pfna', 'Psna', 'Pcna')])
        s.col(alias, 'person', 'Pfna', 'first_name')
        s.col(alias, 'person', 'Psna', 'second_name')
        s.col(alias, 'person', 'Pcna', 'common_name')


def _team_club_name(s, joins, alias, src_alias, code, as_name, tables, idx_name=None):
    """Club name (and, with `idx_name`, club.idx) for a TEAM reference. The team's club is
    `team.club_idx` (team record +0x30, so reserve and youth sides map to their club); when
    that column is missing, a club's first team carries the club's unique id (27,560 of
    27,560 clubs), so club.uid = team.uid. National sides fall back to the team's own names."""
    column = s.codes.get(('person', code))
    if not column or not {'team', 'club'} <= tables:
        return
    joins.append(f'LEFT JOIN team {alias}t ON {alias}t.idx = {src_alias}.{_q(column)}')
    link = s.codes.get(('team', 'c:club_idx'))
    if link:
        joins.append(f'LEFT JOIN club {alias}c ON {alias}c.idx = {alias}t.{_q(link)}')
        if idx_name:
            s.raw(f'{alias}t.{_q(link)}', idx_name, [('person', column), ('team', link)])
    else:
        joins.append(f'LEFT JOIN club {alias}c ON {alias}c.uid = {alias}t.uid')
        if idx_name:
            s.raw(f'{alias}c.idx', idx_name, [('person', column)])
    club_names = [n for n in (s.codes.get(('club', c)) for c in CLUB_NAMES) if n and s.status.get(('club', n)) == 'ready']
    team_names = [n for n in (s.codes.get(('team', c)) for c in NAMED['team'])
                  if n and s.status.get(('team', n)) == 'ready']
    if not club_names and not team_names:       # no stored name at all: the on-demand ones
        club_names = [n for n in (s.codes.get(('club', c)) for c in CLUB_NAMES) if n]
        team_names = [n for n in (s.codes.get(('team', c)) for c in NAMED['team']) if n]
    parts = [f"NULLIF({alias}c.{_q(n)}, '')" for n in club_names] + [f"NULLIF({alias}t.{_q(n)}, '')" for n in team_names]
    if parts:
        expr = parts[0] if len(parts) == 1 else f'COALESCE({", ".join(parts)})'
        deps = [('person', column)] + [('club', n) for n in club_names] + [('team', n) for n in team_names]
        s.raw(expr, as_name, deps)
        return expr, deps
    return None


def _ref_name(s, joins, alias, src_alias, src_table, code, target, name_codes, as_name, tables):
    """LEFT JOIN target ON idx = src.<code column>; select its first non-empty name."""
    column = s.c(src_table, code)
    if not column or target not in tables:
        return
    joins.append(f'LEFT JOIN {_q(target)} {alias} ON {alias}.idx = {src_alias}.{column}')
    s.first(alias, target, name_codes, as_name, [(src_table, s.codes[(src_table, code)])])


CLUB_NAMES = ('Cnam', 'dbnm', 'Csnm')
NATION_NAMES = ('Nnam', 'dbnm', 'Nsnm')
COMP_NAMES = ('cnam', 'dbnm', 'csnm')
NAMED = {'club': CLUB_NAMES, 'nation': NATION_NAMES, 'competition': COMP_NAMES, 'team': ('Tlna', 'dbnm', 'Tsna'),
         'city': ('Cnam', 'dbnm'), 'stadium': ('Snam', 'dbnm'), 'continent': ('Cnam', 'dbnm')}

# 1-20 ratings as the game's getter reports them (DATA [1, r, r, r] -> r)
PLAYER_RATINGS = [
    ('Pcor', 'corners'), ('Pcro', 'crossing'), ('Pdri', 'dribbling'), ('Pfin', 'finishing'),
    ('Pfrs', 'first_touch'), ('Pfrk', 'free_kicks'), ('Phea', 'heading'), ('Plsh', 'long_shots'),
    ('Plth', 'long_throws'), ('Pmar', 'marking'), ('Ppas', 'passing'), ('Ppen', 'penalty_taking'),
    ('Ptac', 'tackling'), ('Ptec', 'technique'),
    ('Pagg', 'aggression'), ('Pant', 'anticipation'), ('Pbra', 'bravery'), ('Pcmp', 'composure'),
    ('Pcnt', 'concentration'), ('Pdec', 'decisions'), ('Pdet', 'determination'), ('Pfla', 'flair'),
    ('Pinf', 'leadership'), ('Potb', 'off_the_ball'), ('Ppsn', 'positioning'), ('Ptwr', 'teamwork'),
    ('Pcre', 'vision'), ('Pwkr', 'work_rate'),
    ('Pacc', 'acceleration'), ('Pagi', 'agility'), ('Pbal', 'balance'), ('Pjum', 'jumping_reach'),
    ('Pnft', 'natural_fitness'), ('Ppac', 'pace'), ('Psta', 'stamina'), ('Pstr', 'strength'),
    ('Paab', 'aerial_reach'), ('Pcoa', 'command_of_area'), ('Pcom', 'communication'), ('Pecc', 'eccentricity'),
    ('Phan', 'handling'), ('Pkic', 'kicking'), ('Pooo', 'one_on_ones'), ('Pttp', 'punching_tendency'),
    ('Pref', 'reflexes'), ('Prou', 'rushing_out_tendency'), ('Pthr', 'throwing'),
    ('PCON', 'consistency'), ('Pdir', 'dirtiness'), ('Pimp', 'important_matches'),
    ('Pipr', 'injury_proneness'), ('Pver', 'versatility'),
    ('Plft', 'left_foot'), ('Prft', 'right_foot'),
]
PLAYER_OTHER = [
    ('PCAB', 'current_ability'), ('PPAB', 'potential_ability'),
    ('PCRP', 'current_reputation'), ('PHRP', 'home_reputation'), ('PWRP', 'world_reputation'),
    ('Pgoa', 'pos_goalkeeper'), ('Pdls', 'pos_defender_left'), ('Pdce', 'pos_defender_central'),
    ('Pdrs', 'pos_defender_right'), ('Pdmc', 'pos_defensive_midfielder'), ('Pwbl', 'pos_wing_back_left'),
    ('Pwbr', 'pos_wing_back_right'), ('Pmls', 'pos_midfielder_left'), ('Pmce', 'pos_midfielder_central'),
    ('Pmrs', 'pos_midfielder_right'), ('Paml', 'pos_attacking_midfielder_left'),
    ('Pamc', 'pos_attacking_midfielder_central'), ('Pamr', 'pos_attacking_midfielder_right'),
    ('Pace', 'pos_striker'),
    ('Pcon', 'condition'), ('Pfit', 'match_sharpness'), ('Pjad', 'fatigue'), ('Phij', 'is_injured'),
    ('PbvE', 'transfer_value'),
]
# extras (getter keys outside the editor catalog; labels inferred unless noted) and derived fields
PLAYER_EXTRA = [
    ('x:condition_stored', 'condition_stored'), ('x:injury_days_remaining', 'injury_days_remaining'),
    ('x:injuries', 'injuries'),
    ('Pmor', 'morale'), ('Pfrm', 'form'),
    ('Prat', 'average_rating'), ('POmi', 'minutes'), ('POgl', 'goals'), ('Poas', 'assists'),
    ('PoxG', 'expected_goals'), ('PoxA', 'expected_assists'), ('Poyc', 'yellow_cards'), ('Porc', 'red_cards'),
    ('POpa', 'passes_attempted'), ('POpC', 'passes_completed'), ('POkp', 'key_passes'),
    ('POta', 'tackles_attempted'), ('POtc', 'tackles_won'),
    ('PcSd', 'contract_start'), ('PPra', 'position_ratings'), ('Ppss', 'positions_short'),
]
PERSON_OTHER = [
    ('Pdob', 'date_of_birth'), ('Phes', 'height'),
    ('Pada', 'adaptability'), ('Pamb', 'ambition'), ('Pcvy', 'controversy'), ('Ploy', 'loyalty'),
    ('Ppre', 'pressure'), ('Ppro', 'professionalism'), ('Pspo', 'sportsmanship'), ('Ptem', 'temperament'),
    ('Pcwg', 'wage'), ('Pcex', 'contract_expires'), ('Pcjd', 'date_joined'), ('Psnu', 'squad_number'),
    ('Pion', 'on_loan'), ('Piap', 'international_apps'), ('Pigl', 'international_goals'),
]


def _player_view(conn, tables):
    if not {'player', 'person'} <= tables:
        return None
    s = _Select(conn)
    s.raw('p.idx', 'idx')
    s.raw('p.uid', 'uid')
    s.raw('p.class', 'class')
    joins = ['FROM player p JOIN person pe ON pe.idx = p.idx']
    _person_name(s, 'pe')
    for code, name in PERSON_OTHER[:1]:
        s.col('pe', 'person', code, name)
    dob = s.c('person', 'Pdob')
    if dob:
        s.raw(_age(f'pe.{dob}'), 'age', [('person', s.codes[('person', 'Pdob')])])
    s.col('pe', 'person', 'Pnat', 'nationality_idx')
    _ref_name(s, joins, 'nat', 'pe', 'person', 'Pnat', 'nation', NATION_NAMES, 'nationality', tables)
    second = s.c('person', 'P2ni')
    if second and 'nation' in tables:
        # P2ni is a JSON list of nation table indices (other nationalities); the first is the second nationality
        expr = f"json_extract(pe.{second}, '$[0]')"
        s.raw(expr, 'second_nationality_idx', [('person', s.codes[('person', 'P2ni')])])
        joins.append(f'LEFT JOIN nation nat2 ON nat2.idx = {expr}')
        s.first('nat2', 'nation', NATION_NAMES, 'second_nationality', [('person', s.codes[('person', 'P2ni')])])
    # Pcti (and Ptaj's Ttea member) is the team the player plays for now: the loan club while on
    # loan. The club holding the main contract (the parent club of a loanee) is the computed
    # person.contract_club_idx (main contract at PERSON - 0x98).
    s.col('pe', 'person', 'Pcti', 'team_idx')
    club_name = _team_club_name(s, joins, 'cl', 'pe', 'Pcti', 'club', tables, idx_name='club_idx')
    contract = s.codes.get(('person', 'c:contract_club_idx'))
    if contract and 'club' in tables:
        s.col('pe', 'person', 'c:contract_club_idx', 'contracted_club_idx')
        joins.append(f'LEFT JOIN club ccc ON ccc.idx = pe.{_q(contract)}')
        s.first('ccc', 'club', CLUB_NAMES, 'contracted_club', [('person', contract)])
    else:
        _team_club_name(s, joins, 'cc', 'pe', 'Ptaj', 'contracted_club', tables, idx_name='contracted_club_idx')
    s.col('pe', 'person', 'Pion', 'on_loan')
    link, pion = s.codes.get(('team', 'c:club_idx')), s.c('person', 'Pion')
    if link and pion and club_name:
        # the club the player is on loan at: the playing club while the getter's on-loan flag is set
        deps = [('person', s.codes[('person', c)]) for c in ('Pion', 'Pcti')] + [('team', link)]
        s.raw(f'CASE WHEN pe.{pion} = 1 THEN clt.{_q(link)} END', 'loan_club_idx', deps)
        s.raw(f'CASE WHEN pe.{pion} = 1 THEN {club_name[0]} END', 'loan_club', deps + club_name[1])
    pos = s.c('player', 'Ppsr')
    if pos:
        s.raw(f"json_extract(p.{pos}, '$.text')", 'position', [('player', s.codes[('player', 'Ppsr')])])
    s.col('p', 'player', 'Ppos', 'position_bitmask')
    for code, name in PLAYER_OTHER[:2]:
        s.col('p', 'player', code, name)
    for code, name in PLAYER_RATINGS:
        s.col('p', 'player', code, name)
    for code, name in PLAYER_OTHER[2:]:
        days = s.c('player', 'x:injury_days_remaining') if code == 'Phij' else None
        if days:
            # Phij reads the STARTING_INJURY database table, which is empty in a running career,
            # so it is 0 for every player. is_injured follows the game's own rule for a player
            # who is out: his injuries leave days still out (the condition under which the game's
            # condition getter returns -1; docs/fmdb/ORACLE.md, M1).
            s.raw(f'CASE WHEN p.{days} IS NULL THEN NULL WHEN p.{days} > 0 THEN 1 ELSE 0 END', 'is_injured',
                  [('player', s.codes[('player', 'x:injury_days_remaining')])])
            continue
        s.col('p', 'player', code, name)
    for code, name in PERSON_OTHER[1:]:
        s.col('pe', 'person', code, name)
    # squad status: the agreed playing time on the main FULL contract (the person getter key PMsq
    # is unset on every live player); PMsq where a snapshot has no computed column
    if s.codes.get(('person', 'c:contract_squad_status_code')):
        s.label('pe', 'person', 'c:contract_squad_status_code', 'squad_status')
    else:
        s.label('pe', 'person', 'PMsq', 'squad_status')
    s.label('pe', 'person', 'Pces', 'contract_type')
    for code, name in PLAYER_EXTRA:
        s.col('p', 'player', code, name)
    s.named('p', 'player', 'season_appearances_Prat', 'appearances')
    virtual = ('player', 'is_virtual') in s.names
    if virtual:
        joins.append('WHERE p.is_virtual = 0')
    return s.done(joins)


def _club_view(conn, tables):
    if 'club' not in tables:
        return None
    s = _Select(conn)
    s.raw('c.idx', 'idx')
    s.raw('c.uid', 'uid')
    s.raw('c.class', 'class')
    joins = ['FROM club c']
    s.first('c', 'club', CLUB_NAMES, 'name')
    s.col('c', 'club', 'Csnm', 'short_name')
    for code, name in CLUB_COLUMNS:
        s.col('c', 'club', code, name)
    s.label('c', 'club', 'Cprs', 'status')
    s.label('c', 'club', 'PLgn', 'player_gender')
    s.label('c', 'club', 'Chsd', 'rich_benefactor')
    for code, alias, target, as_name in (('Cnti', 'n', 'nation', 'nation'), ('Ccty', 'ci', 'city', 'city'),
                                         ('Cdvi', 'd', 'competition', 'division'),
                                         ('Codi', 'd2', 'competition', 'secondary_division'),
                                         ('Csti', 'st', 'stadium', 'stadium'),
                                         ('Ctsi', 'tg', 'stadium', 'training_ground')):
        s.col('c', 'club', code, as_name + '_idx')
        _ref_name(s, joins, alias, 'c', 'club', code, target, NAMED[target], as_name, tables)
    # stadium capacity from the stadium record when the club's own capacity field is not ready
    cap = s.c('stadium', 'Scpy') if 'stadium' in tables else None
    if cap and s.c('club', 'Csti') and s.status.get(('stadium', s.codes[('stadium', 'Scpy')])) in ('ready', 'on_demand'):
        s.raw(f'st.{cap}', 'stadium_capacity_from_stadium', [('stadium', s.codes[('stadium', 'Scpy')]),
                                                             ('club', s.codes[('club', 'Csti')])])
    return s.done(joins)


CLUB_COLUMNS = (
    ('Crep', 'reputation'), ('Cyfn', 'year_founded'), ('levl', 'division_level'),
    ('Ccba', 'balance'), ('Ctbu', 'transfer_budget'), ('Cwwb', 'wage_budget'), ('Crmb', 'remaining_wage_budget'),
    ('CMWE', 'maximum_wage'), ('CSbR', 'scouting_budget'), ('Chdb', 'has_debts'),
    ('Catd', 'attendance'), ('CAAa', 'average_attendance'), ('Cmna', 'minimum_attendance'),
    ('Cmxa', 'maximum_attendance'), ('Snam', 'stadium_name'), ('Scpy', 'stadium_capacity'),
    ('Sscy', 'stadium_seating_capacity'),
    ('Ctlv', 'training_facilities'), ('Cytv', 'youth_coaching'), ('Cyfb', 'youth_facilities'),
    ('Crcb', 'youth_recruitment'), ('Cyim', 'youth_importance'), ('CcfE', 'corporate_facilities'),
    ('CLat', 'latitude'), ('CLon', 'longitude'),
    ('ttcl', 'foreground_colour'), ('tbcl', 'background_colour'),
    ('1scl', 'kit_foreground_colour'), ('1sbc', 'kit_background_colour'),
)
CLUB_EXTRA = tuple(c for c, _ in CLUB_COLUMNS) + ('Cprs', 'PLgn', 'Chsd', 'Codi', 'Ctsi')


STAFF_RATINGS = [
    ('Ncha', 'coaching_attacking'), ('Nchd', 'coaching_defending'), ('Nchf', 'coaching_fitness'),
    ('Npgs', 'coaching_goalkeeping'), ('Nchm', 'coaching_possession'), ('Ncsp', 'coaching_set_pieces'),
    ('Ncta', 'coaching_tactical'), ('Ncte', 'coaching_technical'), ('Npwy', 'working_with_youngsters'),
    ('Npad', 'adaptability'), ('Npld', 'authority'), ('Npde', 'determination'), ('Npmo', 'motivating'),
    ('Npmm', 'people_management'), ('Npja', 'judging_player_ability'), ('Npjp', 'judging_player_potential'),
    ('Npjs', 'judging_staff_ability'), ('Nneg', 'negotiating'), ('Nptk', 'tactical_knowledge'),
    ('Npjd', 'analysing_data'), ('Npph', 'physiotherapy'), ('NpIM', 'sports_science'),
]


def _staff_job(s, joins, tables):
    """`job`: the job title the game shows for the main contract's job byte (`Pcjo`, contract
    +0x26) on the contract team's type (team.team_type), converted as the hand-built
    `staff_jobs.decode` does (native converter 0x13604D4, labels 0x1358AC8); the labels are
    `_enum_labels` rows of table 'staff_job' keyed by team type ('other' for types past the
    converter's table). The person getter key PCJO is 0 on every live record, so it is the
    fallback only."""
    pcjo, ttyp = s.codes.get(('non_player', 'Pcjo')), s.codes.get(('team', 'Ttyp'))
    team = s.codes.get(('person', 'c:contract_team_idx'))
    if not (pcjo and ttyp and team and 'team' in tables):
        s.label('pe', 'person', 'PCJO', 'job')
        return
    from .. import staff_jobs
    joins.append(f'LEFT JOIN team jt ON jt.idx = pe.{_q(team)}')
    pick = "(SELECT label FROM _enum_labels WHERE table_name = 'staff_job' AND column_name = {} AND value = np.{})"
    expr = (f'CASE WHEN jt.{_q(ttyp)} IS NULL OR np.{_q(pcjo)} IS NULL THEN NULL '
            f'WHEN jt.{_q(ttyp)} < {len(staff_jobs.TEAM_GROUP)} '
            f'THEN {pick.format(f"CAST(jt.{_q(ttyp)} AS TEXT)", _q(pcjo))} '
            f"ELSE {pick.format(repr('other'), _q(pcjo))} END")
    s.raw(expr, 'job', [('non_player', pcjo), ('person', team), ('team', ttyp)])


def staff_job_labels():
    """`_enum_labels` rows ('staff_job', team type or 'other', native job byte, title) for `_staff_job`."""
    from .. import staff_jobs as S
    rows = []
    for key, group in [*((str(t), g) for t, g in enumerate(S.TEAM_GROUP)), ('other', 2)]:
        for native, code in enumerate(S.JOB_GROUPS[group]):
            if code and S.JOB_LABELS.get(code):
                rows.append(('staff_job', key, native, S.JOB_LABELS[code]))
    return rows


def _staff_view(conn, tables):
    if not {'non_player', 'person'} <= tables:
        return None
    s = _Select(conn)
    s.raw('np.idx', 'idx')
    s.raw('np.uid', 'uid')
    s.raw('np.class', 'class')
    joins = ['FROM non_player np JOIN person pe ON pe.idx = np.idx']
    _person_name(s, 'pe')
    s.col('pe', 'person', 'Pdob', 'date_of_birth')
    dob = s.c('person', 'Pdob')
    if dob:
        s.raw(_age(f'pe.{dob}'), 'age', [('person', s.codes[('person', 'Pdob')])])
    s.col('pe', 'person', 'Pnat', 'nationality_idx')
    _ref_name(s, joins, 'nat', 'pe', 'person', 'Pnat', 'nation', NATION_NAMES, 'nationality', tables)
    s.col('pe', 'person', 'Pcti', 'team_idx')
    _team_club_name(s, joins, 'cl', 'pe', 'Pcti', 'club', tables, idx_name='club_idx')
    _staff_job(s, joins, tables)
    s.col('np', 'non_player', 'Pcjo', 'contract_job_code')
    s.label('pe', 'person', 'PSJO', 'secondary_job')
    for code, name in (('Ncra', 'current_ability'), ('Npta', 'potential_ability'), ('Ncrr', 'current_reputation'),
                       ('Nhmr', 'home_reputation'), ('Nwrr', 'world_reputation')):
        s.col('np', 'non_player', code, name)
    for code, name in STAFF_RATINGS:
        s.col('np', 'non_player', code, name)
    for code, name in PERSON_OTHER[2:10]:          # personality (staff attributes own 'adaptability')
        s.col('pe', 'person', code, 'personality_' + name)
    for code, name in (('Pcwg', 'wage'), ('Pcex', 'contract_expires'), ('Pcjd', 'date_joined')):
        s.col('pe', 'person', code, name)
    s.label('pe', 'person', 'Pces', 'contract_type')
    s.label('np', 'non_player', 'Nppf', 'preferred_formation')
    s.label('np', 'non_player', 'Npcs', 'coaching_style')
    for code, name in STAFF_STYLE:
        s.col('np', 'non_player', code, name)
    for code, name in staff_tendencies(s):
        s.col('np', 'non_player', code, name)
    return s.done(joins)


# the tactical tendencies the staff profile shows (the hand-built tool's `tendencies`; oracle 400/400)
STAFF_STYLE = (('Natt', 'tendency_attacking'), ('Ndep', 'tendency_defensive_line'), ('Ndir', 'tendency_directness'),
               ('Ndal', 'tendency_dirtiness_allowance'), ('Nflx', 'tendency_flexibility'),
               ('Npre', 'tendency_trigger_press'), ('Ntem', 'tendency_tempo'), ('Nwid', 'tendency_width'),
               ('Nrot', 'tendency_squad_rotation'))


def _handled_for_staff(conn, column):
    """False when the getter does not handle the column for the main staff classes (only the
    3-row HUMAN_NON_PLAYER class may answer, which would make the column look ready)."""
    states = {r[0] for r in conn.execute(
        "SELECT status FROM _column_state WHERE table_name='non_player' AND column_name=? "
        "AND class IN ('ACTUAL_NON_PLAYER', 'ACTUAL_PLAYER_AND_NON_PLAYER')", (column,))}
    return not states or states != {'unavailable'}


def staff_tendencies(s):
    """Staff tendencies (NT01 ... N100: 'Signs A Lot Of Youth Players', 'Will press intensely', ...),
    named `tendency_<field name>` from the catalog."""
    out = []
    for (table, code), column in sorted(s.codes.items()):
        # editor-only club-policy tendencies; those the record getter does not handle are left out
        if table == 'non_player' and re.fullmatch(r'NT\d\d|N1\d\d', code) \
                and _handled_for_staff(s.conn, column):
            out.append((code, 'policy_' + re.sub(rf'_{code}(_\d+)?$', '', column)))
    return out


def _competition_view(conn, tables):
    if 'competition' not in tables:
        return None
    s = _Select(conn)
    s.raw('c.idx', 'idx')
    s.raw('c.uid', 'uid')
    joins = ['FROM competition c']
    s.first('c', 'competition', COMP_NAMES, 'name')
    s.col('c', 'competition', 'csnm', 'short_name')
    s.col('c', 'competition', 'c3ln', 'three_letter_name')
    for code, name in (('crep', 'reputation'), ('levl', 'level'), ('cext', 'is_extinct'), ('PLgn', 'player_gender')):
        s.col('c', 'competition', code, name)
    s.label('c', 'competition', 'dbty', 'type')
    s.label('c', 'competition', 'CTty', 'trophy_type')
    s.label('c', 'competition', 'PLgn', 'player_gender_label')
    for code, alias, target, as_name in (('cnti', 'n', 'nation', 'nation'), ('ccti', 'co', 'continent', 'continent'),
                                         ('cpcm', 'pc', 'competition', 'parent_competition')):
        s.col('c', 'competition', code, as_name + '_idx')
        _ref_name(s, joins, alias, 'c', 'competition', code, target, NAMED[target], as_name, tables)
    # CLwR / CLrR (extras, labels inferred): {'dref': table << 24 | index}; table 0x18 is TEAM
    # (every team's own `dref` key equals 0x18 << 24 | its idx). Read as last winner / runner-up.
    for code, as_name in (('CLwR', 'last_winner'), ('CLrR', 'last_runner_up')):
        col = s.c('competition', code)
        if col and {'team', 'club'} <= tables:
            ref = f"json_extract(c.{col}, '$.dref')"
            idx = f'CASE WHEN ({ref} >> 24) = 24 THEN ({ref} & 16777215) END'
            s.raw(idx, as_name + '_team_idx', [('competition', s.codes[('competition', code)])])
            joins.append(f'LEFT JOIN team {as_name}_t ON {as_name}_t.idx = {idx}')
            s.first(f'{as_name}_t', 'team', NAMED['team'], as_name, [('competition', s.codes[('competition', code)])])
    return s.done(joins)


CURATED = {'player_view': _player_view, 'club_view': _club_view, 'staff_view': _staff_view,
           'competition_view': _competition_view}
