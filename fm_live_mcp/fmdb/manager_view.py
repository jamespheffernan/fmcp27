"""Manager view of the fmdb snapshot: the same SQL, restricted to what the manager knows.

`open_manager_connection(snapshot, knowledge)` opens the snapshot read-only, attaches the
knowledge store (`knowledge_store`) as schema `kn`, creates masked temp views and installs a
SQLite authorizer:

* `m_player_view` (from `player_view`), `m_player` (from `player`), `m_person` (from `person`) and
  `m_scouted_player_view`: the base rows restricted to players with a knowledge row. Each of the
  47 visible attributes becomes `<attr>` (exact value, else NULL), `<attr>_min`, `<attr>_max`
  (bounds; equal to the value when exact; NULL when unknown) and `<attr>_state`. Every other
  column follows `column_policy` (see docs/fmdb/MANAGER_VIEW.md): `public` passes through,
  `own_club` passes through only for the manager's own players, `never` is NULL.
* `m_columns`, `m_attribute_columns`, `m_coverage`: what each masked column is and how much of
  the save the knowledge covers.

Enforcement. A view is expanded inside the caller's statement, so the authorizer sees the base
column reads it performs, tagged with the innermost view (or CTE) name. CTE names are chosen by
the caller, so a CTE named like a public view would receive the same tag. Each masked view is
therefore a public view over a private view whose name carries a per-connection random token
(`_mv_<hex>_...`); only reads tagged with a private name may touch base tables, and only the
public views may read the private ones. The token cannot be learned through SQL: reads of
`sqlite_master`/`sqlite_temp_master`, every PRAGMA (including `pragma_*` table functions),
ATTACH/DETACH and all writes are denied, and `check_sql` (applied by `prepare_manager_query`)
rejects statements that are not a single SELECT/WITH/VALUES or that mention `_mv_` at all.
Reads of anything else not on the allow-list (the knowledge schema, snapshot metadata, json
table functions) are denied.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import knowledge_codes as codes
from . import knowledge_store as ks

PRIVATE_PREFIX = '_mv_'
PUBLIC, OWN_CLUB, NEVER, ATTRIBUTE, IDENTITY = 'public', 'own_club', 'never', 'attribute', 'identity'
_RANK = {NEVER: 0, OWN_CLUB: 1, PUBLIC: 2, IDENTITY: 3}

# ---------------------------------------------------------------------------------------------
# Policy (by editor FourCC). This is policy, not proven game behaviour: see MANAGER_VIEW.md.
# ---------------------------------------------------------------------------------------------
PUBLIC_CODES = frozenset({
    # names and identity
    'duni', 'Pfna', 'Psna', 'Pcna', 'PAfn', 'PAna', 'PAcn', 'PnRV', 'Pfln', 'PShN', 'dbnm', 'Ptyp', 'Pife',
    # date of birth, age, height
    'Pdob', 'Page', 'Phes', 'Phei',
    # nationality and birthplace
    'Pnti', 'Pnat', 'P2ni', 'PNRs', 'Pnbi', 'Prbi', 'Pcbi',
    # club, loan club, squad number
    'Pcti', 'Ptaj', 'PLcl', 'Pion', 'Psnu',
    # position (the position string, not the 1..20 familiarity ratings)
    'Ppos', 'Ppsr',
    # international caps and goals
    'Piap', 'Pigl', 'Puia', 'Puig',
    # the current contract's wage and expiry: on every profile (PERSON panel list 0x3B1B8C gives
    # CanViewCurrentContract for every person; ContextContractWeeklyWage formats another club's
    # player's exact wage). See MANAGER_VIEW.md "Evidence".
    'Pcwg', 'Pcex',
    # favoured and disliked people and clubs (CanViewFavouredPeople / CanViewFavouredClubs for every person)
    'Pfvp', 'Pdsp', 'Pfvc', 'Pdsc',
})
NEVER_CODES = frozenset({
    # current / potential ability and everything derived from them
    'PCAB', 'ERCL', 'ERCA', 'PCRD', 'PRDF', 'PPAB', 'PPMX', 'PPAR', 'PPPA', 'PkCA', 'PkPA',
    # raw reputation numbers (the UI shows a band; band thresholds are not mapped)
    'PCRP', 'PHRP', 'PWRP', 'PCRI', 'PHRI', 'PWRI', 'PSCR', 'PGRP',
    # raw foot ratings (the UI shows a word), whole-attribute lists, weightings, role/position scores
    'Plft', 'Prft', 'PATL', 'PWEI', 'PRjm', 'PRae', 'PRLS', 'ORLS', 'PRSS', 'PBrI', 'Porl', 'PFDv',
    # personality values
    'Pada', 'Pamb', 'Pcvy', 'Ploy', 'Ppre', 'Ppro', 'Pspo', 'Ptem',
    # staff-role preference ratings
    'PPam', 'PPco', 'PPfc', 'PPgk', 'PPpc', 'PPmn', 'PPph', 'PPdf', 'PPtd', 'PPpd', 'PPch', 'PPhy',
    'PPsc', 'PPda', 'PPss',
    # editor bookkeeping
    'rdui', 'NDBC', 'FDBC', 'ReAR', 'PeTR',
}) | codes.HIDDEN_ATTRIBUTE_CODES | codes.SCALED_CODES
IDENTITY_COLUMNS = frozenset({'idx', 'uid', 'class'})
# Derived columns without an editor code that are public by name.
PUBLIC_UNCODED = frozenset({'name', 'full_name', 'common_name', 'first_name', 'second_name', 'club_name',
                            'club', 'nation_name', 'nationality', 'nationality_name', 'age',
                            'date_of_birth', 'position', 'positions', 'loan_club_name'})
KNOWLEDGE_COLUMNS = (('scouted', 'k.scouted'), ('k', 'k.k'), ('sources', 'k.sources'),
                     ('ca_gate', 'k.ca_gate'), ('pa_gate', 'k.pa_gate'), ('own_club', 'k.own_club'),
                     ('h_score', 'k.h_score'), ('node_score', 'k.node_score'),
                     ('report_score', 'k.report_score'), ('exact_n', 'k.exact_n'), ('range_n', 'k.range_n'),
                     ('unknown_n', 'k.unknown_n'), ('unavailable_n', 'k.unavailable_n'),
                     ('unavailable_reason', 'k.unavailable_reason'),
                     # perceived ability stars: what the game shows instead of CA/PA, for any player
                     ('current_ability_stars_min', 'k.ca_stars_min'), ('current_ability_stars_max', 'k.ca_stars_max'),
                     ('current_ability_stars_state', 'k.ca_stars_state'),
                     ('potential_ability_stars_min', 'k.pa_stars_min'),
                     ('potential_ability_stars_max', 'k.pa_stars_max'),
                     ('potential_ability_stars_state', 'k.pa_stars_state'),
                     ('in_player_search', 'k.in_player_search'), ('knowledge_date', 'k.game_date'))
# Base views/tables masked into m_* views: (public name, base name, adds the 47 attributes).
MASKED = (('m_player_view', 'player_view', True), ('m_player', 'player', True), ('m_person', 'person', False))
METADATA_TABLES = frozenset({'_fields', '_tables', '_snapshot'})
# The user's own career (team idx, club idx, coach name): never hidden from him. Readable under the
# bare name and as m__managed.
OWN_CAREER_TABLE = '_managed'
SAFE_TABLE_FUNCTIONS = frozenset({'json_each', 'json_tree'})
DENIED_FUNCTIONS = frozenset({'load_extension', 'readfile', 'writefile', 'edit', 'fts3_tokenizer',
                              'sqlite_dbpage', 'zipfile'})
SCHEMA_TABLES = frozenset({'sqlite_master', 'sqlite_temp_master', 'sqlite_schema', 'sqlite_temp_schema'})
KN_PRIVATE_TABLES = frozenset({'knowledge_input', 'knowledge_group', '_knowledge_meta'})

# Range-aware filters the tools can advertise; `{a}` is an attribute column, `{x}` 1..20.
RANGE_FILTERS = {
    'sure_at_least': '"{a}_min" >= {x}',       # the manager knows it is at least x
    'could_be_at_least': '"{a}_max" >= {x}',   # at least x is consistent with what the manager knows
    'sure_at_most': '"{a}_max" <= {x}',
    'could_be_at_most': '"{a}_min" <= {x}',
    'exact': '"{a}" IS NOT NULL',
    'known': '"{a}_min" IS NOT NULL',          # exact or range
    'unknown': '"{a}_state" = \'unknown\'',
}


class ManagerViewError(RuntimeError):
    """The manager view cannot serve the request; the message says why."""


def range_filter(kind: str, attribute: str, x: int | None = None) -> str:
    """SQL predicate for a range-aware filter, e.g. range_filter('sure_at_least', 'passing', 15)."""
    if kind not in RANGE_FILTERS:
        raise ValueError(f'kind must be one of {sorted(RANGE_FILTERS)}')
    if not re.fullmatch(r'[a-z0-9_]+', attribute or ''):
        raise ValueError('attribute must be a column name such as "passing"')
    if '{x}' in RANGE_FILTERS[kind] and (type(x) is not int or not 1 <= x <= 20):
        raise ValueError('x must be an integer 1..20')
    return RANGE_FILTERS[kind].format(a=attribute, x=x)


# ---------------------------------------------------------------------------------------------
# SQL checks
# ---------------------------------------------------------------------------------------------
_TOKEN = re.compile(r"""
    (?P<ws>\s+) | (?P<line>--[^\n]*) | (?P<block>/\*.*?(\*/|\Z)) |
    (?P<str>'(?:[^']|'')*'?) | (?P<qid>"(?:[^"]|"")*"?|\[[^\]]*\]?|`(?:[^`]|``)*`?) |
    (?P<semi>;) | (?P<word>[A-Za-z_][A-Za-z0-9_$]*) | (?P<other>.)""", re.S | re.X)


def _tokens(sql: str):
    for m in _TOKEN.finditer(sql):
        kind = m.lastgroup
        if kind in ('ws', 'line', 'block'):
            continue
        yield kind, m.group()


def check_sql(sql: str) -> list[tuple[str, str]]:
    """Reject what the manager view never runs: more than one statement, anything but a query,
    and any mention of the private view prefix. Returns the tokens (kind, text)."""
    if type(sql) is not str or not sql.strip():
        raise ManagerViewError('Supply one SQL query.')
    tokens = list(_tokens(sql))
    meaningful = [t for t in tokens if t[0] != 'semi']
    if not meaningful:
        raise ManagerViewError('Supply one SQL query.')
    seen_semi = False
    for kind, _ in tokens:
        if kind == 'semi':
            seen_semi = True
        elif seen_semi:
            raise ManagerViewError('The manager view runs exactly one statement.')
    first_kind, first = meaningful[0]
    if first_kind != 'word' or first.upper() not in ('SELECT', 'WITH', 'VALUES'):
        raise ManagerViewError('The manager view runs only SELECT, WITH or VALUES queries.')
    for kind, text in tokens:
        if kind in ('word', 'qid') and PRIVATE_PREFIX in text.lower():
            raise ManagerViewError(f'Identifiers containing {PRIVATE_PREFIX!r} are reserved.')
    return tokens


def limited_to_scouted(sql: str) -> bool:
    """True when the query reads only `m_scouted_player_view` among the masked player views, or
    filters `scouted = 1` without any OR. A heuristic: prefer `m_scouted_player_view`."""
    words = [t.lower() for k, t in _tokens(sql) if k in ('word', 'qid')]
    words = [w.strip('"[]`') for w in words]
    masked = {'m_player_view', 'm_player', 'm_person'}
    if 'm_scouted_player_view' in words and not masked & set(words):
        return True
    text = ' '.join(t for _, t in _tokens(sql)).lower()
    return bool(re.search(r'\bscouted\s*(=|==|is)\s*1\b', text)) and not re.search(r'\bor\b', text)


# ---------------------------------------------------------------------------------------------
# Column policy
# ---------------------------------------------------------------------------------------------
@dataclass
class Column:
    name: str            # output column name
    source: str | None   # base column name in the (copied) base query
    code: str | None
    record_type: str | None
    policy: str
    attribute: dict | None = None
    note: str = ''


def _extra_codes():
    """{code: label} of every snapshot extra (getter keys outside the editor catalog)."""
    from . import extras
    out = {}
    for fields in extras.EXTRA_FIELDS.values():
        for code, info in fields.items():
            out.setdefault(code, info['name'])
    return out


EXTRA_LABELS = _extra_codes()
# Columns outside the editor catalog: snapshot extras (FourCC), derived fields ('x:<name>') and
# computed columns ('c:<name>'). Policy, not proven game behaviour; see MANAGER_VIEW.md.
# Season statistics ({valu, numb} records: appearances, goals, assists, minutes, ratings, xG,
# cards, passes, tackles ...) and form: shown on any player's profile -> public.
EXTRA_PUBLIC_CODES = frozenset(
    {code for code, label in EXTRA_LABELS.items() if label.startswith('Statistic') or '(value, matches)' in label}
    | {'Pfrm', 'Posa', 'Posu', 'Poap', 'Ppss', 'PNal', 'c:is_virtual', 'c:club_idx', 'c:contract_club_idx',
       'c:contract_team_idx'})
# Morale, contract wage/dates, position ratings, condition as stored, injuries, contract job:
# shown for own players only, like the editor-code contract and fitness fields.
EXTRA_OWN_CLUB_CODES = frozenset({'Pmor', 'PcwR', 'PcSd', 'PPra', 'Ppsa', 'Pcjo', 'PRCF',
                                  'x:condition_stored', 'c:contract_squad_status_code'})
# The current contract's weekly wage and end date (the extras that repeat Pcwg/Pcex) and current
# injuries: on every player's profile (CanViewCurrentContract and CanViewFitnessInfo are in the
# PERSON panel list for players of every club; player_injury is public for the same reason).
EXTRA_PUBLIC_CODES = EXTRA_PUBLIC_CODES | {'Pcww', 'Pced', 'injr', 'x:injuries', 'x:injury_days_remaining',
                                           'x:has_injury_record'}
# Every other extra (inferred labels, e.g. injury risk InRs, feet ratings Pfot) is withheld.


def _policy_for_code(code: str | None) -> str:
    if code is None:
        return NEVER
    if code in codes.VISIBLE_CODES:
        return ATTRIBUTE
    if code in NEVER_CODES:
        return NEVER
    if code in PUBLIC_CODES or code in EXTRA_PUBLIC_CODES:
        return PUBLIC
    if code in EXTRA_OWN_CLUB_CODES:
        return OWN_CLUB
    if code in EXTRA_LABELS or code.startswith(('x:', 'c:')):
        return NEVER
    return OWN_CLUB


PERSON_TABLES = frozenset({'player', 'person'})
# Staff and other person-family tables: no knowledge cells; the person code policy, with "own
# club" meaning the person is contracted to a team of the manager's club.
STAFF_TABLES = frozenset({'non_player', 'official', 'journalist', 'agent'})
# Name columns of referenced tables (team, club, nation, competition, stadium, city): public.
REFERENCE_NAME_CODES = frozenset({'Cnam', 'dbnm', 'Csnm', 'Nnam', 'Nsnm', 'cnam', 'csnm', 'Tlna', 'Tsna',
                                  'Tnam', 'Snam'})
# Link columns of referenced tables: a team's club (team.club_idx), public like the club itself.
REFERENCE_LINK_CODES = frozenset({'c:club_idx', 'c:parent_club_idx'})
NEUTRAL_TABLES = frozenset({'_enum_labels', '_snapshot'})
_SQL_WORDS = frozenset("""select from where join left right inner outer cross natural on using as and or not
    null is in exists case when then else end group by order having limit offset union all distinct
    like glob between collate asc desc cast integer text real numeric blob escape values with""".split())


def _fields(con) -> dict[tuple[str, str], tuple[str, str]]:
    """{(table, column): (code, record_type)} from the snapshot's `_fields`."""
    try:
        rows = con.execute('SELECT table_name, column_name, code, record_type FROM _fields').fetchall()
    except sqlite3.Error:
        return {}
    return {(t, c): (code, rt) for t, c, code, rt in rows if code}


def _scan(text: str):
    """(depth, kind, token) over SQL text; kinds: word, qid, str, punct. Comments dropped."""
    depth = 0
    for kind, tok in _tokens(text):
        if tok == '(':
            depth += 1
        elif tok == ')':
            depth -= 1
        yield depth, kind, tok


def _ident(tok: str) -> str:
    if tok[:1] in '"`[':
        return tok[1:-1].replace('""', '"')
    return tok


def _select_items(body: str) -> tuple[list[tuple[str, str]], dict[str, str], set[str]]:
    """([(output name, expression)], {alias: table}, outer tables) for a `SELECT ... FROM ...` body."""
    toks = list(_scan(body))
    if not toks or toks[0][2].upper() != 'SELECT':
        raise ManagerViewError('Base view is not a plain SELECT.')
    try:
        from_at = next(i for i, (d, k, t) in enumerate(toks) if d == 0 and k == 'word' and t.upper() == 'FROM')
    except StopIteration:
        raise ManagerViewError('Base view has no FROM clause.') from None
    start = 2 if toks[1][2].upper() in ('DISTINCT', 'ALL') else 1
    items, current = [], []
    for depth, kind, tok in toks[start:from_at] + [(0, 'other', ',')]:
        if depth == 0 and tok == ',':
            items.append(current)
            current = []
        else:
            current.append((depth, kind, tok))
    out = []
    for item in items:
        as_at = max((i for i, (d, k, t) in enumerate(item) if d == 0 and k == 'word' and t.upper() == 'AS'),
                    default=None)
        if as_at is not None:
            expr, name = item[:as_at], _ident(item[as_at + 1][2])
        else:
            expr, name = item, _ident(item[-1][2])
        out.append((name, ' '.join(t for _, _, t in expr)))
    # Table aliases at every depth (outer joins and subqueries inside select items). An alias bound
    # to two different tables maps to None, so its references stay unresolved (never).
    aliases: dict[str, str | None] = {}
    outer: set[str] = set()

    def bind(alias, table):
        if aliases.get(alias, table) != table:
            aliases[alias] = None
        else:
            aliases[alias] = table
    for i, (depth, kind, tok) in enumerate(toks):
        if kind == 'word' and tok.upper() in ('FROM', 'JOIN') and i + 1 < len(toks):
            j = i + 1
            if toks[j][1] not in ('word', 'qid'):
                continue                       # FROM (subquery): its own tables bind below
            if toks[j][2].lower() == 'main' and j + 2 < len(toks) and toks[j + 1][2] == '.':
                j += 2
            table = _ident(toks[j][2])
            alias = table
            if j + 1 < len(toks) and toks[j + 1][1] in ('word', 'qid'):
                k = j + 2 if toks[j + 1][2].upper() == 'AS' else j + 1
                if k < len(toks) and _ident(toks[k][2]).lower() not in _SQL_WORDS:
                    alias = _ident(toks[k][2])
            bind(alias, table)
            bind(table, table)
            if depth == 0:
                outer.add(table)
    return out, aliases, outer


def _ref_policy(table: str | None, column: str, fields: dict, *, derived: bool, ctx: dict | None = None):
    """(policy, code, record_type) of one base column reference.

    `ctx` (the generic masked views, `_CoreContext`): staff tables follow the person code
    policy, name and link columns of every core table are public, and the other columns of
    the object's own table (`ctx['own_table']`) are own-club when the object has own rows."""
    if table in NEUTRAL_TABLES:
        return None
    found = fields.get((table, column)) if table else None
    if ctx is not None and table in STAFF_TABLES:
        if column in IDENTITY_COLUMNS:
            return (IDENTITY, None, None)
        if found is None or _is_secret_core(column, found[0]) or found[0] in STAFF_NEVER_CODES:
            return (NEVER, *(found or (None, None)))
        if found[0] in STAFF_PUBLIC_CODES:
            return (PUBLIC, *found)
        policy = _policy_for_code(found[0])
        return (NEVER if policy == ATTRIBUTE else policy, *found)
    if table in PERSON_TABLES:
        if column in IDENTITY_COLUMNS:
            return (IDENTITY, None, None)
        if found is None:
            return (NEVER, None, None)
        policy = _policy_for_code(found[0])
        if policy == ATTRIBUTE and derived:
            policy = NEVER   # an expression over a raw attribute would leak the stored value
        return (policy, *found)
    if found and (found[0] in REFERENCE_NAME_CODES or found[0] in REFERENCE_LINK_CODES):
        return (PUBLIC, *found)
    if table and column == 'idx':
        return (PUBLIC, None, None)    # the row identity of a referenced club/team/nation
    if ctx is not None and table:
        if column in IDENTITY_COLUMNS:
            return (PUBLIC, None, None)
        code = found[0] if found else None
        if _is_secret_core(column, code):
            return (NEVER, code, found[1] if found else None)
        if (table, column) in ctx['names'] or (table, column) in ctx['links']:
            return (PUBLIC, code, found[1] if found else None)
        if table == ctx.get('own_table') and found:
            return (OWN_CLUB, *found)
    return (NEVER, found[0] if found else None, found[1] if found else None)


def _is_secret_core(column: str, code: str | None) -> bool:
    """A core-table column whose raw value the game never shows (raw reputation, the codes the
    person policy withholds): never public, not even for the manager's own club."""
    low = column.lower()
    return (code in NEVER_CODES or code in STAFF_NEVER_CODES or 'reputation' in low
            or 'current_ability' in low or 'potential_ability' in low)


# Staff (non_player) current and potential ability: never shown as numbers.
STAFF_NEVER_CODES = frozenset({'Ncra', 'Npta'})
# The staff attributes of the Non-Player Attributes panel (coaching, mental, knowledge, medical):
# shown for staff of every club and free agents (PERSON panel list 0x3B1B8C gives
# CanViewNonPlayerAttributes for every non-player sampled). Tendencies and board attributes are
# not in that panel and stay withheld.
STAFF_PUBLIC_CODES = frozenset({'Ncha', 'Nchd', 'Nchf', 'Npgs', 'Nchm', 'Ncsp', 'Ncta', 'Ncte', 'Npwy',
                                'Npad', 'Npde', 'Npld', 'Npmo', 'Npmm',
                                'Npja', 'Npjp', 'Npjs', 'Nneg', 'Nptk', 'Npjd', 'Npph', 'NpIM'})


def _bare_tables(column: str, table_columns: dict) -> list[str]:
    return sorted(t for t, cols in table_columns.items() if column in cols)


def _simple(name, table, column, fields, note=None, ctx=None) -> Column:
    ref = _ref_policy(table, column, fields, derived=False, ctx=ctx)
    if ref is None:
        return Column(name, name, None, None, NEVER, note='metadata column')
    policy, code, rt = ref
    if policy == IDENTITY:
        policy = IDENTITY if name in IDENTITY_COLUMNS else PUBLIC
    if policy == ATTRIBUTE:
        return Column(name, name, code, rt, ATTRIBUTE, attribute=codes.BY_CODE[code])
    return Column(name, name, code, rt, policy, note=note or f'{table}.{column}')


def _classify_expression(name: str, expr: str, aliases: dict, fields: dict,
                         table_columns: dict | None = None, outer: set | None = None, ctx=None) -> Column:
    table_columns = table_columns or {}
    outer_columns = {t: c for t, c in table_columns.items() if outer is None or t in outer}
    toks = [(k, t) for _, k, t in _scan(expr)]
    if len(toks) == 3 and toks[1][1] == '.' and toks[0][0] in ('word', 'qid') and toks[2][0] in ('word', 'qid'):
        return _simple(name, aliases.get(_ident(toks[0][1])), _ident(toks[2][1]), fields, ctx=ctx)
    if len(toks) == 1 and toks[0][0] in ('word', 'qid') and toks[0][1].lower() not in _SQL_WORDS:
        column = _ident(toks[0][1])
        hits = _bare_tables(column, outer_columns)   # SQLite resolves a bare item in the outer FROM
        return _simple(name, hits[0] if len(hits) == 1 else None, column, fields, ctx=ctx)
    refs = []
    for i, (kind, tok) in enumerate(toks):
        if kind not in ('word', 'qid'):
            continue
        after = toks[i + 1][1] if i + 1 < len(toks) else ''
        before = toks[i - 1][1] if i else ''
        if after == '.' or after == '(' or (kind == 'word' and tok.lower() in _SQL_WORDS):
            continue
        if before.upper() == 'AS' or (before.upper() in ('FROM', 'JOIN')) or \
                (i > 1 and toks[i - 2][1].upper() in ('FROM', 'JOIN') and kind == 'word'
                 and toks[i - 1][0] in ('word', 'qid')):
            continue                           # output alias, table name or table alias
        if before == '.':
            table = aliases.get(_ident(toks[i - 2][1]))
            refs.append(_ref_policy(table, _ident(tok), fields, derived=True, ctx=ctx) if table
                        else (NEVER, None, None))
        else:
            column = _ident(tok)
            hits = _bare_tables(column, table_columns)
            # inside subqueries scope is not modelled: every table that has the column counts
            candidates = [_ref_policy(t, column, fields, derived=True, ctx=ctx) for t in hits] or [(NEVER, None, None)]
            candidates = [c for c in candidates if c is not None]
            if candidates:
                refs.append(min(candidates, key=lambda r: _RANK[r[0]]))
    refs = [r for r in refs if r is not None]
    if not refs:
        policy = PUBLIC if name in PUBLIC_UNCODED else NEVER
        return Column(name, name, None, None, policy, note='derived, no base column')
    policy, code, rt = min(refs, key=lambda r: _RANK[r[0]])
    if policy == IDENTITY:
        policy = PUBLIC
    used = sorted({r[1] for r in refs if r[1]})
    return Column(name, name, code, rt, policy, note='derived from ' + (', '.join(used) or 'identity'))


def column_policy(con, table: str, names: list[str], body: str | None = None, *, ctx=None) -> list[Column]:
    """Classify each output column of base `table`.

    A table column maps to its editor code through `_fields`. A view column is classified from
    its select expression: a plain column reference takes that column's policy (an attribute
    stays an attribute); a derived expression takes the strictest policy of every base column it
    reads, with raw attributes counted as `never`. Columns of referenced tables are public only
    for name codes. Anything unresolved is `never`.
    """
    fields = _fields(con)
    if body is None:
        return [_classify_expression(n, f'"{table}".{_q(n)}', {table: table}, fields, ctx=ctx) for n in names]
    items, aliases, outer = _select_items(body)
    expanded = []
    for name, expr in items:
        star = re.fullmatch(r'(?:("?[\w]+"?)\s*\.\s*)?\*', expr.strip())
        if not star:
            expanded.append((name, expr))
            continue
        sources = [star.group(1).strip('"')] if star.group(1) else \
            list(dict.fromkeys(t for a, t in aliases.items() if a == t or a not in aliases.values()))
        for alias in sources:
            table = aliases.get(alias, alias)
            for _, column, *_ in con.execute(f'PRAGMA main.table_info({_q(table)})'):
                expanded.append((column, f'{_q(alias)}.{_q(column)}'))
    items = expanded
    if len(items) != len(names):
        raise ManagerViewError(f'Cannot match the select list of {table} to its columns.')
    table_columns = {t: {r[1] for r in con.execute(f'PRAGMA main.table_info({_q(t)})')}
                     for t in set(aliases.values()) if t}
    return [_classify_expression(name, expr, aliases, fields, table_columns, outer, ctx=ctx)
            for name, (_, expr) in zip(names, items)]


# ---------------------------------------------------------------------------------------------
# View construction
# ---------------------------------------------------------------------------------------------
_CREATE_VIEW = re.compile(
    r'^\s*CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?'
    r'(?:"(?:[^"]|"")+"|\[[^\]]+\]|`[^`]+`|[\w.]+)\s*(?P<cols>\([^)]*\))?\s*AS\s+(?P<body>.*)$', re.S | re.I)


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _base_query(con, base: str) -> tuple[str, list[str], str | None] | None:
    """(SELECT text producing `base`'s rows, output names, view body or None) or None if absent."""
    row = con.execute("SELECT type, sql FROM main.sqlite_master WHERE name = ? AND type IN ('table','view')",
                      (base,)).fetchone()
    if row is None:
        return None
    kind, sql = row
    names = [r[1] for r in con.execute(f'PRAGMA main.table_info({_q(base)})')]
    if kind == 'table':
        return f'SELECT * FROM main.{_q(base)}', names, None
    m = _CREATE_VIEW.match(sql or '')
    if not m:
        raise ManagerViewError(f'Cannot read the definition of view {base}.')
    body = m.group('body').strip().rstrip(';')
    body_names = [d[0] for d in con.execute(f'SELECT * FROM ({body}) LIMIT 0').description]
    if len(body_names) != len(names) or len(set(body_names)) != len(body_names):
        raise ManagerViewError(f'View {base} has duplicate or mismatched column names.')
    select = ', '.join(f'{_q(b)} AS {_q(n)}' for b, n in zip(body_names, names))
    return f'SELECT {select} FROM ({body})', names, body


STAR_KNOWLEDGE = frozenset({'k.ca_stars_min', 'k.ca_stars_max', 'k.ca_stars_state', 'k.pa_stars_min',
                            'k.pa_stars_max', 'k.pa_stars_state', 'k.in_player_search'})


CELL = 'cell:'  # need(idx, CELL + column): the statement read that on-demand public/own-club cell of the row


def _on_demand_sources(con, base: str) -> set[str]:
    """Output columns of `base` (a snapshot table, or a curated view through `_view_columns`)
    that read an on-demand column (`_column_state`): NULL in the stored table until computed."""
    try:
        lazy = set(con.execute("SELECT DISTINCT table_name, column_name FROM main._column_state "
                               "WHERE status = 'on_demand'").fetchall())
    except sqlite3.Error:
        return set()
    out = {c for t, c in lazy if t == base}
    try:
        for alias, t, c in con.execute('SELECT column_name, base_table, base_column FROM main._view_columns '
                                       'WHERE view = ?', (base,)).fetchall():
            if (t, c) in lazy:
                out.add(alias)
    except sqlite3.Error:
        pass
    return out


def _view_sql(private: str, base_query: str, columns: list[Column], add_attributes: bool, *, epoch: int = 0,
              need: str | None = None, seeds_only: bool = False,
              lazy: frozenset | set = frozenset()) -> tuple[str, list[dict]]:
    """CREATE VIEW for one private masked view.

    Without `need`, rows are the base rows with a knowledge row of the current epoch. With
    `need` (the name of the connection's need function), rows are the base rows of the player
    universe (of the named population with `seeds_only`), and every expression that depends on
    a knowledge row calls `need(idx, 1)` when that row is not current (`need(idx, 2)` for the
    star and Player Search columns), which records the PERSON index and yields NULL. Public
    columns never call it, so a query that reads only public columns computes nothing.

    `lazy`: base columns that are computed on demand. With `need`, a public or own-club column
    built from one calls `need(idx, 'cell:<column>')` for every row whose value the statement
    reads, so `tools.manager_prewarm` computes exactly those cells (the call yields NULL and the
    stored value is returned)."""
    exprs, described, taken = [], [], set()

    def cell(col, src):
        if need is None or col.source not in lazy:
            return src
        tag = (CELL + col.name).replace("'", "''")
        return f"CASE WHEN {need}(b.idx, '{tag}') IS NULL THEN {src} END"

    def emit(name, expr, **info):
        if name in taken:
            name = f'knowledge_{name}'
        if name in taken:
            raise ManagerViewError(f'Column name collision on {name}')
        taken.add(name)
        exprs.append(f'{expr} AS {_q(name)}')
        described.append(dict(column=name, **info))
        return name

    def known(expr):
        """`expr` (which reads k or w) for a current row; the need call otherwise."""
        return expr if need is None else f'CASE WHEN k.idx IS NULL THEN {need}(b.idx, 1) ELSE {expr} END'

    present = set()
    for col in columns:
        src = f'b.{_q(col.source)}'
        if col.policy == ATTRIBUTE:
            a = col.attribute['column']
            present.add(col.attribute['code'])
            for suffix in ('', '_min', '_max', '_state'):
                emit(col.name + suffix, known(f'w.{_q(a + suffix)}'), code=col.code, policy=ATTRIBUTE,
                     field=col.attribute['name'], note='knowledge cell' + (f' {suffix[1:]}' if suffix else ' exact value'))
        elif col.policy in (IDENTITY, PUBLIC):
            emit(col.name, src if col.policy == IDENTITY else cell(col, src), code=col.code, policy=col.policy,
                 field=None, note=col.note)
        elif col.policy == OWN_CLUB:
            emit(col.name, known(f'CASE WHEN k.own_club = 1 THEN {cell(col, src)} END'), code=col.code, policy=OWN_CLUB,
                 field=None, note=col.note)
        else:
            emit(col.name, 'NULL', code=col.code, policy=NEVER, field=None, note=col.note)
    if add_attributes:
        for f in codes.FIELDS:
            if f['code'] in present:
                continue
            for suffix in ('', '_min', '_max', '_state'):
                emit(f['column'] + suffix, known(f'w.{_q(f["column"] + suffix)}'), code=f['code'], policy=ATTRIBUTE,
                     field=f['name'], note='knowledge cell (not in base)')
    for name, expr in KNOWLEDGE_COLUMNS:
        if expr in STAR_KNOWLEDGE:
            stale = "'not_computed'" if expr.endswith('_state') else 'NULL'
            if need is None:
                expr = f'CASE WHEN k.stars_epoch = {epoch} THEN {expr} ELSE {stale} END'
            else:
                expr = (f'CASE WHEN k.idx IS NULL OR k.stars_epoch IS NOT {epoch} THEN {need}(b.idx, 2) '
                        f'ELSE {expr} END')
        elif name == 'scouted' and need is not None:
            expr = '(s.idx IS NOT NULL)'
        else:
            expr = known(expr)
        emit(name, expr, code=None, policy='knowledge', field=None, note='knowledge_player')
    # The scan is driven by a knowledge-store table in PERSON index order (CROSS JOIN fixes the
    # join order) and the base row is looked up by idx. Left to the planner, a scan of a base
    # table may run through any index that covers the columns a statement uses, including an
    # index on a hidden column, and then the order of an unordered result, the order of ties
    # and which rows a LIMIT keeps would follow the hidden values.
    base = f'CROSS JOIN ({base_query}) AS b ON b.idx = d.idx'
    if need is None:
        driver = 'kn.knowledge_seed' if seeds_only else 'kn.knowledge_universe'
        source = (f'(SELECT k0.idx FROM kn.knowledge_player AS k0 WHERE k0.epoch = {epoch}'
                  + (' AND k0.idx IN (SELECT idx FROM kn.knowledge_seed)' if seeds_only else '')
                  + f' ORDER BY k0.idx) AS d {base} CROSS JOIN kn.knowledge_player AS k ON k.idx = d.idx')
        del driver
    else:
        source = (f'(SELECT idx FROM kn.{"knowledge_seed" if seeds_only else "knowledge_universe"} ORDER BY idx) '
                  f'AS d {base} LEFT JOIN kn.knowledge_seed AS s ON s.idx = d.idx '
                  f'LEFT JOIN kn.knowledge_player AS k ON k.idx = d.idx AND k.epoch = {epoch}')
    sql = (f'CREATE TEMP VIEW {_q(private)} AS SELECT {", ".join(exprs)} FROM {source} '
           f'LEFT JOIN kn.knowledge_wide AS w ON w.idx = k.idx')
    return sql, described


# ---------------------------------------------------------------------------------------------
# Every other table and view of the reader: collection tables (fmdb/sources), the core tables
# and the curated views. Naming rule: every masked object is `m_<name>`; the bare names stay
# denied, so a statement that reads `fixture` means the stored data and `m_fixture` the manager's.
# ---------------------------------------------------------------------------------------------
KNOWLEDGE_VIEWS = frozenset({'m_player_view', 'm_scouted_player_view', 'm_player', 'm_person'})
# person-family views of the snapshot that only the knowledge path may serve
KNOWLEDGE_BASES = frozenset({'player_view', 'player', 'person', 'person_labelled', 'player_labelled'})
REF = 'ref:'   # need(idx, 'ref:<view>\t<column>\t<table>\t<column>'): an on-demand cell of a generic view
OWN_SCOPES = ('own_club',)
NAME_COLUMN = re.compile(r'(^|_)(name|short_name|long_name|nickname|three_letter_name)(_|$)', re.I)


class Withheld(Exception):
    """A table or view the manager connection does not open; the message says why."""


@dataclass
class Exposed:
    name: str                       # public view name, m_<base>
    base: str                       # table or view of the snapshot
    kind: str                       # 'collection' or 'core'
    scope: str                      # public | own_club | own_rows | never
    policy: dict = field(default_factory=dict)
    policy_table: str | None = None # the collection table whose policy a view inherits
    tables: frozenset = frozenset() # collection tables it reads (built when a statement reads it)
    rule: str = ''                  # one line: what the manager sees
    reason: str = ''


def referenced_names(sql: str) -> set[str]:
    """Lower-case identifiers of a statement (words and quoted names), for picking the masked
    objects a statement can read; a superset of the names it reads."""
    return {_ident(t).lower() for k, t in _tokens(sql) if k in ('word', 'qid')}


def rename_views(sql: str, names: dict) -> str:
    """`sql` with each identifier in `names` (lower-case public name -> base name) replaced; string
    literals, comments and every other token are kept as written."""
    out, at = [], 0
    for m in _TOKEN.finditer(sql):
        kind = m.lastgroup
        if kind in ('word', 'qid') and _ident(m.group()).lower() in names:
            out.append(sql[at:m.start()])
            out.append(_q(names[_ident(m.group()).lower()]))
            at = m.end()
    out.append(sql[at:])
    return ''.join(out)


def _exists(con) -> dict:
    return {n: t for n, t in con.execute("SELECT name, type FROM main.sqlite_master WHERE type IN ('table','view')")}


def _rule(scope: str, policy: dict) -> str:
    if scope == 'public':
        return 'every row and column'
    if scope == 'own_rows':
        return "only your club's rows"
    if scope == 'own_club':
        pub = policy.get('public_columns')
        return (f"every row: {', '.join(pub)}; other columns only on your club's rows" if pub
                else "only your club's rows")
    if scope == 'core':
        return "names and links on every row; other columns only on your club's rows"
    if scope == 'core_public':
        return 'names and links; other columns withheld'
    return 'withheld'


def catalog(con) -> dict[str, Exposed]:
    """{public name: Exposed} of every object the generic masked views may serve, from the
    snapshot's metadata only (no column parsing). Objects with scope `never` are listed too."""
    objects = _exists(con)
    out: dict[str, Exposed] = {}
    states, view_policy = {}, {}
    try:
        for name, module, mjson, vjson in con.execute(
                'SELECT table_name, module, manager_json, views_json FROM main._source_tables'):
            states[name] = (module, json.loads(mjson or '{}') or {'scope': 'never'}, json.loads(vjson or '{}'))
    except sqlite3.Error:
        pass
    try:
        for name, mjson in con.execute('SELECT view, manager_json FROM main._source_views'):
            view_policy[name] = json.loads(mjson or '{}') or {'scope': 'never'}
    except sqlite3.Error:
        pass
    collection = set(states)

    def reads(name):
        if objects.get(name) == 'table':
            return frozenset({name} & collection)
        row = con.execute("SELECT sql FROM main.sqlite_master WHERE name = ?", (name,)).fetchone()
        words = {w.lower() for w in re.findall(r'[A-Za-z_]\w*', row[0] or '')} if row else set()
        return frozenset(words & collection)

    def add(base, kind, policy, policy_table=None):
        public = f'm_{base}'
        if public in KNOWLEDGE_VIEWS or base not in objects or base.startswith(('_', 'sqlite_')):
            return
        scope = policy.get('scope', 'never')
        if scope not in ('public', 'own_club'):
            scope = 'never'
        if scope == 'own_club' and not policy.get('public_columns'):
            scope = 'own_rows'
        out[public] = Exposed(public, base, kind, scope, policy, policy_table, reads(base),
                              _rule(scope, policy), policy.get('reason', ''))
    for table, (module, policy, views) in sorted(states.items()):
        add(table, 'collection', policy)
        for view in views:
            add(view, 'collection', view_policy.get(view, policy), table)
    for view, policy in sorted(view_policy.items()):
        if f'm_{view}' not in out:
            add(view, 'collection', policy)
    try:
        core = [t for t, rt in con.execute('SELECT table_name, record_type FROM main._tables')
                if not str(rt or '').startswith('collection')]
    except sqlite3.Error:
        core = []
    for name in sorted(set(core) | {n for n, t in objects.items() if t == 'view'}):
        if f'm_{name}' in out or name in collection or name in view_policy:
            continue
        if name in KNOWLEDGE_BASES:
            if f'm_{name}' not in KNOWLEDGE_VIEWS:
                out[f'm_{name}'] = Exposed(f'm_{name}', name, 'core', 'never', {}, None, frozenset(), 'withheld',
                                           'person and player rows are served by m_person, m_player and '
                                           'm_player_view (knowledge cells)')
            continue
        if name not in objects:
            continue
        main = _main_table(con, name) if objects[name] == 'view' else None
        if main in states:          # an undeclared view over a collection table (labels): its policy
            add(name, 'collection', states[main][1], main)
            continue
        scope = 'core' if _core_own_table(con, name) else 'core_public'
        out[f'm_{name}'] = Exposed(f'm_{name}', name, 'core', scope, {}, None, reads(name), _rule(scope, {}),
                                   'core table: names, links and identity are shown on every screen that '
                                   'lists the record; other values follow the editor-code policy')
    return out


def _outer_from(body: str) -> tuple[str, str] | None:
    """(table, alias) of the first table of the top-level FROM of a SELECT body."""
    toks = [(d, k, t) for d, k, t in _scan(body)]
    for i, (d, k, t) in enumerate(toks):
        if d == 0 and k == 'word' and t.upper() == 'FROM' and i + 1 < len(toks):
            j = i + 1
            if toks[j][1] not in ('word', 'qid'):
                return None
            if toks[j][2].lower() == 'main' and j + 2 < len(toks) and toks[j + 1][2] == '.':
                j += 2
            table = _ident(toks[j][2])
            alias = table
            if j + 1 < len(toks) and toks[j + 1][1] in ('word', 'qid'):
                k2 = j + 2 if toks[j + 1][2].upper() == 'AS' else j + 1
                if k2 < len(toks) and _ident(toks[k2][2]).lower() not in _SQL_WORDS:
                    alias = _ident(toks[k2][2])
            return table, alias
    return None


def _main_table(con, base: str) -> str | None:
    row = con.execute("SELECT type, sql FROM main.sqlite_master WHERE name = ?", (base,)).fetchone()
    if row is None:
        return None
    if row[0] == 'table':
        return base
    m = _CREATE_VIEW.match(row[1] or '')
    found = _outer_from(m.group('body')) if m else None
    return found[0] if found else None


def _core_own_table(con, base: str) -> str | None:
    """The table whose rows can belong to the manager's club for a core object: club, team or a
    staff table (the object's main FROM table), else None."""
    t = _main_table(con, base)
    return t if t in ('club', 'team') or t in STAFF_TABLES else None


def _own_sql(con) -> dict:
    """SQL subqueries for the manager's own clubs, teams and people (from `_managed`)."""
    def cols(t):
        return {r[1] for r in con.execute(f'PRAGMA main.table_info({_q(t)})')}
    managed = cols('_managed')
    none = '(SELECT NULL WHERE 0)'
    clubs = '(SELECT club_idx FROM main._managed WHERE club_idx IS NOT NULL)' if 'club_idx' in managed else none
    code_col = dict(con.execute("SELECT table_name || '.' || code, column_name FROM main._fields "
                                "WHERE code IN ('c:club_idx', 'Pcti')").fetchall()) if cols('_fields') else {}
    team_club = code_col.get('team.c:club_idx')
    if team_club:
        teams = f'(SELECT idx FROM main.team WHERE {_q(team_club)} IN {clubs})'
    else:
        teams = '(SELECT team_idx FROM main._managed)' if 'team_idx' in managed else none
    pcti = code_col.get('person.Pcti')
    people = f'(SELECT idx FROM main.person WHERE {_q(pcti)} IN {teams})' if pcti else none
    return {'clubs': clubs, 'teams': teams, 'people': people}


def _core_context(con) -> dict:
    """Name and link columns of the core tables (public on every row), the field codes, the
    on-demand columns and the own-club subqueries, computed once per connection."""
    names, links = set(), set()
    try:
        rows = con.execute('SELECT table_name, column_name, code, references_table FROM main._fields').fetchall()
    except sqlite3.Error:
        rows = []
    for t, c, code, ref in rows:
        if t in PERSON_TABLES or t in STAFF_TABLES or _is_secret_core(c, code):
            continue
        if code in REFERENCE_NAME_CODES or NAME_COLUMN.search(c):
            names.add((t, c))
        elif ref:
            links.add((t, c))
    try:
        lazy = set(con.execute("SELECT DISTINCT table_name, column_name FROM main._column_state "
                               "WHERE status = 'on_demand'").fetchall())
    except sqlite3.Error:
        lazy = set()
    return {'names': names, 'links': links, 'fields': _fields(con), 'lazy': lazy, 'own': _own_sql(con),
            'own_table': None}


def _main_reads(con, select: str) -> set[tuple[str, str]]:
    """(table, column) of every `main` read the statement performs (the authorizer reports them)."""
    seen = set()

    def record(action, a1, a2, db, source):
        if action == sqlite3.SQLITE_READ and db == 'main' and a2:
            seen.add((a1, a2))
        return sqlite3.SQLITE_OK
    con.set_authorizer(record)
    try:
        con.execute(f'SELECT * FROM ({select}) LIMIT 0').fetchall()
    finally:
        con.set_authorizer(None)
    return seen


def _secret_read(t: str, c: str, ctx: dict, *, strict: bool) -> bool:
    """True when reading column `c` of `t` may expose a value the manager never sees (strict:
    also a person's own-club-only value, for objects whose rows show on every club)."""
    if t in NEUTRAL_TABLES or t in METADATA_TABLES or t == '_managed':
        return False
    found = ctx['fields'].get((t, c))
    if t in PERSON_TABLES or t in STAFF_TABLES:
        ref = _ref_policy(t, c, ctx['fields'], derived=False, ctx=ctx)
        policy = ref[0] if ref else NEVER
        return policy in (NEVER, ATTRIBUTE) or (strict and policy == OWN_CLUB)
    return _is_secret_core(c, found[0] if found else None) if (found or 'reputation' in c.lower()) else False


def _ref_tokens(expr: str):
    """[(alias, column)] of `alias.column` references and [bare words] of an expression."""
    toks = [(k, t) for _, k, t in _scan(expr)]
    refs, bare = [], []
    for i, (kind, tok) in enumerate(toks):
        if kind not in ('word', 'qid'):
            continue
        after = toks[i + 1][1] if i + 1 < len(toks) else ''
        before = toks[i - 1][1] if i else ''
        if after == '.':
            continue
        if before == '.' and i >= 2:
            refs.append((_ident(toks[i - 2][1]), _ident(tok)))
        elif after != '(' and not (kind == 'word' and tok.lower() in _SQL_WORDS) \
                and before.upper() not in ('FROM', 'JOIN', 'AS') and \
                not (i > 1 and toks[i - 2][1].upper() in ('FROM', 'JOIN') and kind == 'word'):
            bare.append(_ident(tok))
    return refs, bare


def _own_condition(con, exp: Exposed, columns: list[str], ctx: dict) -> str | None:
    """SQL over the base row `b` that is true for the manager's own rows, or None."""
    p, own = exp.policy, ctx['own']
    have = set(columns)
    club_cols = p.get('own_club_columns') or ([p['own_club_column']] if p.get('own_club_column') else [])
    cond = None
    if club_cols and all(c in have for c in club_cols):
        cond = ' OR '.join(f'b.{_q(c)} IN {own["clubs"]}' for c in club_cols)
    elif p.get('own_person_column') in have:
        cond = f'b.{_q(p["own_person_column"])} IN {own["people"]}'
    elif p.get('own_team_column') in have:
        cond = f'b.{_q(p["own_team_column"])} IN {own["teams"]}'
    elif p.get('own_club_via') and not club_cols:
        table, column = p['own_club_via'].split('.', 1)
        if f'{table}_idx' in have:
            cond = (f'b.{_q(table + "_idx")} IN (SELECT idx FROM main.{_q(table)} '
                    f'WHERE {_q(column)} IN {own["clubs"]})')
    elif p.get('own_club_rule') and not club_cols:
        words = {w for w in re.findall(r"[A-Za-z_]\w*", re.sub(r"'(?:[^']|'')*'", '', p['own_club_rule']))
                 if w.lower() not in _SQL_WORDS}
        if words <= have:
            cond = '(' + re.sub(r'(?<![\w.\'"])([A-Za-z_]\w*)(?![\w(\'"])',
                                lambda m: f'b.{_q(m.group(1))}' if m.group(1) in words else m.group(1),
                                p['own_club_rule']) + ')'
    if cond is not None or exp.policy_table is None or 'idx' not in have:
        return cond
    # a view without the own column: its rows are the policy table's rows (same idx)
    row = con.execute("SELECT sql FROM main.sqlite_master WHERE name = ?", (exp.base,)).fetchone()
    m = _CREATE_VIEW.match(row[0] or '') if row else None
    if not m:
        return None
    try:
        items, aliases, _ = _select_items(m.group('body').strip().rstrip(';'))
    except ManagerViewError:
        return None
    idx_expr = dict(items).get('idx', '')
    refs, _ = _ref_tokens(idx_expr)
    if len(refs) != 1 or refs[0][1] != 'idx' or aliases.get(refs[0][0]) != exp.policy_table:
        return None
    table_cols = [r[1] for r in con.execute(f'PRAGMA main.table_info({_q(exp.policy_table)})')]
    inner = _own_condition(con, Exposed(exp.name, exp.policy_table, exp.kind, exp.scope, exp.policy), table_cols, ctx)
    if inner is None:
        return None
    return f'b.idx IN (SELECT b.idx FROM main.{_q(exp.policy_table)} AS b WHERE {inner})'


def _view_lineage_public(con, exp: Exposed, body: str, names: list[str], ctx: dict,
                         collection_public: set) -> list[str]:
    """Policy of each output column of a view whose policy table names `public_columns`: public
    when every column it reads is public (the policy table's public columns, public collection
    tables, name/link columns of core tables), else own-club."""
    items, aliases, _ = _select_items(body)
    if len(items) != len(names):
        raise Withheld(f'cannot match the select list of {exp.base} to its columns')
    pub = set(exp.policy.get('public_columns') or ())
    out = []
    for name, expr in items:
        refs, bare = _ref_tokens(expr)
        known_aliases = set(aliases)
        bare = [b for b in bare if b not in known_aliases]
        ok = not bare
        for alias, column in refs:
            t = aliases.get(alias)
            if t == exp.policy_table:
                ok &= column in pub
            elif t in collection_public or t in NEUTRAL_TABLES:
                continue
            elif t is None:
                ok = False
            else:
                ref = _ref_policy(t, column, ctx['fields'], derived=False, ctx=dict(ctx, own_table=None))
                ok &= ref is not None and ref[0] in (PUBLIC, IDENTITY)
        out.append(PUBLIC if ok else OWN_CLUB)
    return out


def _norm(expr: str) -> str:
    return ''.join(_ident(t).lower() for _, _, t in _scan(expr))


def _lazy_links(con, base: str, body: str | None, names: list[str], ctx: dict) -> dict:
    """{output column: (link output column, table, column)} for the output columns that show an
    on-demand cell of a core table, with the output column holding that table's idx."""
    lazy = ctx['lazy']
    if not lazy:
        return {}
    if body is None:
        return {n: ('idx', base, n) for n in names if (base, n) in lazy and 'idx' in names}
    try:
        lineage = con.execute('SELECT column_name, base_table, base_column FROM main._view_columns WHERE view = ?',
                              (base,)).fetchall()
    except sqlite3.Error:
        return {}
    lineage = [(c, t, bc) for c, t, bc in lineage if (t, bc) in lazy and c in names]
    if not lineage:
        return {}
    try:
        items, aliases, _ = _select_items(body)
    except ManagerViewError:
        return {}
    by_expr = {_norm(expr): name for name, expr in items}
    # alias -> normalised expression its idx is joined to (JOIN t a ON a.idx = <expr>)
    joined = {}
    for m in re.finditer(r'\bJOIN\s+"?(\w+)"?\s+(?:AS\s+)?(\w+)\s+ON\s+(.+?)(?=\bLEFT\b|\bJOIN\b|\bINNER\b|\bCROSS\b'
                         r'|\bWHERE\b|\bGROUP\b|\bORDER\b|\bUNION\b|$)', body, re.I | re.S):
        alias, cond = m.group(2), m.group(3)
        sides = [s.strip() for s in cond.split('=', 1)] if cond.count('=') == 1 else []
        for i, side in enumerate(sides):
            if _norm(side) in (f'{alias.lower()}.idx',):
                joined[alias] = _norm(sides[1 - i])
    main = _outer_from(body)
    if main:
        joined.setdefault(main[1], f'{main[1].lower()}.idx')
    out = {}
    items_by_name = dict(items)
    for column, table, base_column in lineage:
        refs, _ = _ref_tokens(items_by_name.get(column, ''))
        for alias, _c in refs:
            if aliases.get(alias) == table and alias in joined and joined[alias] in by_expr:
                out[column] = (by_expr[joined[alias]], table, base_column)
                break
    return out


def _generic_build(con, exp: Exposed, ctx: dict, collection_public: set, *, dry_run: bool):
    """(base query, [Column], own condition or None, rows filtered to own, lazy links). Raises
    Withheld when the object cannot be served safely."""
    if exp.scope == 'never':
        raise Withheld(exp.reason or 'policy: never')
    found = _base_query(con, exp.base)
    if found is None:
        raise Withheld('not in this snapshot')
    base_query, names, body = found
    if dry_run and exp.kind == 'collection' and body is None:
        base_query = f'SELECT * FROM {_q(exp.base)}'      # a statement-dependent table's dry-run view shadows it
    reads = _main_reads(con, found[0])
    if exp.kind == 'collection':
        bad = sorted(f'{t}.{c}' for t, c in reads if t not in exp.tables and _secret_read(t, c, ctx, strict=False))
        if bad:
            raise Withheld(f'reads values the manager never sees: {", ".join(bad[:5])}')
        own = None
        if exp.scope == 'public':
            bad = sorted(f'{t}.{c}' for t, c in reads if t not in exp.tables and _secret_read(t, c, ctx, strict=True))
            if bad:
                raise Withheld(f'public policy but reads own-club-only values: {", ".join(bad[:5])}')
            policies = [IDENTITY if n == 'idx' else PUBLIC for n in names]
        else:
            own = _own_condition(con, exp, names, ctx)
            if own is None:
                raise Withheld('own-club policy, but the rows of your club cannot be told apart in this '
                               f'{"view" if body else "table"} ({json.dumps(exp.policy)})')
            if exp.scope == 'own_rows':
                policies = [PUBLIC] * len(names)
            elif body is None:
                pub = set(exp.policy.get('public_columns') or ())
                policies = [PUBLIC if n in pub else OWN_CLUB for n in names]
            else:
                policies = _view_lineage_public(con, exp, body, names, ctx, collection_public)
        columns = [Column(n, n, None, None, p, note=f'{exp.base}.{n}') for n, p in zip(names, policies)]
        lazy = _lazy_links(con, exp.base, body, names, ctx)
        return base_query, columns, own, exp.scope == 'own_rows', lazy
    # core tables and curated views: classified column by column through the editor codes
    own_table = _core_own_table(con, exp.base)
    cctx = dict(ctx, own_table=own_table)
    try:
        columns = column_policy(con, exp.base, names, body, ctx=cctx)
    except ManagerViewError as exc:
        raise Withheld(str(exc)) from None
    if body is not None:
        filters = _filter_reads(body)
        aliases = _select_items(body)[1]
        bad = sorted(f'{aliases.get(a)}.{c}' for a, c in filters
                     if aliases.get(a) and _secret_read(aliases[a], c, ctx, strict=False))
        if bad:
            raise Withheld(f'joins or filters on values the manager never sees: {", ".join(bad[:5])}')
    own = None
    if own_table == 'club':
        own = f'b.idx IN {ctx["own"]["clubs"]}' if 'idx' in names else None
    elif own_table == 'team':
        col = next((c.name for c in columns if c.code == 'c:club_idx'), None)
        own = f'b.{_q(col)} IN {ctx["own"]["clubs"]}' if col else None
    elif own_table in STAFF_TABLES:
        own = f'b.idx IN {ctx["own"]["people"]}' if 'idx' in names else None
    for col in columns:
        if col.policy == ATTRIBUTE:
            col.policy = NEVER
        if col.policy == OWN_CLUB and own is None:
            col.policy = NEVER
    lazy = _lazy_links(con, exp.base, body, names, ctx)
    return base_query, columns, own, False, lazy


def _filter_reads(body: str) -> list[tuple[str, str]]:
    """[(alias, column)] read after the top-level FROM of a view body (joins, filters, grouping)."""
    toks = list(_scan(body))
    at = next((i for i, (d, k, t) in enumerate(toks) if d == 0 and k == 'word' and t.upper() == 'FROM'), None)
    if at is None:
        return []
    return _ref_tokens(' '.join(t for _, _, t in toks[at:]))[0]


def _generic_view_sql(private: str, public: str, base_query: str, columns: list[Column], own: str | None,
                      own_rows: bool, lazy: dict, need: str | None, no_index: bool) -> tuple[str, list[dict]]:
    exprs, described = [], []
    for col in columns:
        src = f'b.{_q(col.name)}'
        if need is not None and col.name in lazy:
            link, table, column = lazy[col.name]
            tag = f'{REF}{public}\t{col.name}\t{table}\t{column}'.replace("'", "''")
            src = f"CASE WHEN {need}(b.{_q(link)}, '{tag}') IS NULL THEN {src} END"
        if col.policy in (PUBLIC, IDENTITY):
            expr = src
        elif col.policy == OWN_CLUB and own is not None:
            expr = f'CASE WHEN {own} THEN {src} END'
        else:
            expr = 'NULL'
        exprs.append(f'{expr} AS {_q(col.name)}')
        described.append(dict(column=col.name, code=col.code, policy=col.policy if expr != 'NULL' else NEVER,
                              field=None, note=col.note))
    if no_index and base_query.startswith('SELECT * FROM main.'):
        base_query += ' NOT INDEXED'
    sql = (f'CREATE TEMP VIEW {_q(private)} AS SELECT {", ".join(exprs)} FROM ({base_query}) AS b'
           + (f' WHERE {own}' if own_rows and own else ''))
    return sql, described


def _hidden_index(con, exp: Exposed, columns: list[Column]) -> bool:
    """True when the base table has an index on a column that is not public on every row: a
    covering-index scan would then order rows (and choose LIMIT rows) by a withheld value."""
    if _exists(con).get(exp.base) != 'table':
        return False
    open_cols = {c.name for c in columns if c.policy in (PUBLIC, IDENTITY)}
    for _, index, *_ in con.execute(f'PRAGMA main.index_list({_q(exp.base)})').fetchall():
        cols = {r[2] for r in con.execute(f'PRAGMA main.index_info({_q(index)})')}
        if cols - open_cols - {None}:
            return True
    return False


class ManagerStatement(tuple):
    """(sql, params, snapshot path) of a manager-view statement for `sources.refresh_for_query`.
    `open_dry_run()` gives `sources.dry_run_connection` a masked connection, so a statement-
    dependent table (histories, player_season_rates) computes the rows the masked statement
    reads, decided by what the manager sees and never by a withheld value."""

    def __new__(cls, sql, params, path, knowledge):
        self = super().__new__(cls, (sql, params, path))
        self.knowledge = knowledge
        return self

    def open_dry_run(self):
        try:
            con = open_manager_connection(self[2], self.knowledge, need=set(), only=referenced_names(self[0]),
                                          dry_run=True)
        except ManagerViewError as exc:         # the sources treat sqlite3.Error as "cannot dry-run"
            raise sqlite3.OperationalError(str(exc)) from exc
        return _DryRunConnection(con, self[0]), con.close


class _DryRunConnection:
    """A masked connection for a source's dry run: the source's own setup statements (temporary
    key tables and the view that shadows its table) run without the authorizer; the caller's
    statement runs under it."""

    def __init__(self, con, sql):
        self._con, self._sql = con, sql

    def _setup(self, fn, *args):
        self._con.set_authorizer(None)
        try:
            return fn(*args)
        finally:
            self._con.set_authorizer(self._con.manager_authorizer)

    def execute(self, sql, params=()):
        if sql == self._sql:
            check_sql(sql)
            return self._con.execute(sql, params)
        return self._setup(self._con.execute, sql, params)

    def executemany(self, sql, seq):
        return self._setup(self._con.executemany, sql, seq)

    def __getattr__(self, name):
        return getattr(self._con, name)


def collection_reads(snapshot, sql: str) -> set[str]:
    """Collection tables a manager statement may read (through the m_* names it mentions)."""
    names = referenced_names(sql)
    con = sqlite3.connect(f'file:{snapshot}?mode=ro', uri=True)
    try:
        cat = catalog(con)
    finally:
        con.close()
    return set().union(*[e.tables for n, e in cat.items() if n in names]) if names else set()


class ManagerConnection(sqlite3.Connection):
    """sqlite3 connection carrying the manager view's metadata (`manager_info`)."""
    manager_info: dict
    manager_authorizer = None
    manager_need = None          # the need set of an on-demand connection (open_manager_connection)


def _authorizer(public: set[str], private: set[str], *, dry_run: bool = False):
    """`dry_run`: also allow reads of the temporary key tables a source's dry run creates (they
    hold only the keys of the rows the statement may visit; nothing read is returned)."""
    allowed_actions = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE}

    def auth(action, arg1, arg2, db, source):
        if action in allowed_actions:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION:
            name = (arg2 or '').lower()
            return sqlite3.SQLITE_DENY if name in DENIED_FUNCTIONS else sqlite3.SQLITE_OK
        if action != sqlite3.SQLITE_READ:
            return sqlite3.SQLITE_DENY
        table = arg1 or ''
        if table.lower() in SCHEMA_TABLES:
            return sqlite3.SQLITE_DENY
        if arg2 == '':
            # Table-level access with no column (a flattened view's unused join table, count(*)):
            # SQLite reports it without the view context; it exposes no column value.
            return sqlite3.SQLITE_OK
        if db == 'kn':
            # The manager's knowledge is his to read; the input fingerprints (addresses and
            # digests of consumed bytes) and the store's bookkeeping are not.
            return sqlite3.SQLITE_DENY if table in KN_PRIVATE_TABLES and source not in private \
                else sqlite3.SQLITE_OK
        if db == 'temp' and table in public:
            return sqlite3.SQLITE_OK
        if db == 'temp' and table in private:
            return sqlite3.SQLITE_OK if source in public else sqlite3.SQLITE_DENY
        if db == 'main' and source in private:
            return sqlite3.SQLITE_OK
        if db == 'main' and (table in METADATA_TABLES or table == OWN_CAREER_TABLE):
            return sqlite3.SQLITE_OK
        if table in SAFE_TABLE_FUNCTIONS:
            return sqlite3.SQLITE_OK
        if dry_run and db == 'temp' and not table.startswith(PRIVATE_PREFIX):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    return auth


def _probe_innermost(con, private: str) -> set[str]:
    """Innermost-view tags of the base reads the private view performs (must be just itself)."""
    seen = set()

    def record(action, a1, a2, db, source):
        if action == sqlite3.SQLITE_READ and db == 'main' and a2 != '':
            seen.add(source)
        return sqlite3.SQLITE_OK
    con.set_authorizer(record)
    try:
        con.execute(f'SELECT * FROM {_q(private)} LIMIT 0').fetchall()
    finally:
        con.set_authorizer(None)
    return seen


def open_manager_connection(snapshot_path, knowledge_path, *, coverage: dict | None = None,
                            need=None, only=None, dry_run: bool = False) -> ManagerConnection:
    """Read-only snapshot + knowledge, masked temp views and the enforcing authorizer.

    `need`: a set. When given, the views are the on-demand ones (see `_view_sql`): a statement
    that evaluates a knowledge expression for a row without a current knowledge row adds
    `(PERSON index, 1)` (`2` for star and Player Search columns) to it and sees NULL there.
    `prepare_manager_query` repeats the statement until nothing is added. Generic views record
    the on-demand cells of core tables they show as `(idx, 'ref:...')`.

    `only`: the public names to create (`referenced_names(sql)`); None creates every view.
    `m_tables` lists every object either way. `dry_run`: collection tables are read by their
    bare name, so a source's dry-run view shadows them (`ManagerStatement`)."""
    snapshot_path, knowledge_path = Path(snapshot_path), Path(knowledge_path)
    if not snapshot_path.is_file():
        raise ManagerViewError(f'No snapshot at {snapshot_path}; run fm_db_refresh first.')
    only = None if only is None else {n.lower() for n in only}
    if not knowledge_path.is_file() and (only is None or only & KNOWLEDGE_VIEWS):
        raise ManagerViewError(f'No manager knowledge at {knowledge_path}; build tier 1 first.')
    # Autocommit (isolation_level=None): the temp tables below are written with INSERT, and the
    # sqlite3 module's default mode would open a transaction there that is never committed. Every
    # later read of the snapshot through this connection would then keep its SHARED lock until
    # the connection closes, and a writer of the snapshot in the same process (the on-demand
    # cells that tools.manager_prewarm stores, the content check) would wait for it until its
    # busy timeout. In autocommit a read holds its lock only while its statement runs.
    con = sqlite3.connect(f'file:{snapshot_path}?mode=ro', uri=True, factory=ManagerConnection,
                          check_same_thread=False, isolation_level=None)
    try:
        if knowledge_path.is_file():
            con.execute('ATTACH DATABASE ? AS kn', (f'file:{knowledge_path}?mode=ro',))
            row = con.execute("SELECT value FROM kn._knowledge_meta WHERE key = 'epoch'").fetchone()
        else:                                   # a statement that reads no player knowledge
            con.execute("ATTACH DATABASE ':memory:' AS kn")
            row = None
        token = secrets.token_hex(8)
        epoch = int((ks.json.loads(row[0]) if row else {}).get('id', 0))
        need_name = None
        if need is not None:
            need_name = f'{PRIVATE_PREFIX}{token}_need'

            def record(idx, what):
                need.add((idx, what))
                return None
            con.create_function(need_name, 2, record)
            con.manager_need = need
        public, private, described, attribute_columns = set(), set(), [], {}
        for public_name, base, add_attributes in MASKED:
            if only is not None and public_name not in only and not (
                    public_name == 'm_player_view' and 'm_scouted_player_view' in only):
                continue
            found = _base_query(con, base)
            if found is None:
                continue
            base_query, names, body = found
            columns = column_policy(con, base, names, body)
            if 'idx' not in names:
                raise ManagerViewError(f'{base} has no idx column.')
            lazy = _on_demand_sources(con, base) if need is not None else set()
            secret = f'{PRIVATE_PREFIX}{token}_{public_name}'
            sql, info = _view_sql(secret, base_query, columns, add_attributes, epoch=epoch, need=need_name, lazy=lazy)
            con.execute(sql)
            tags = _probe_innermost(con, secret)
            if tags - {secret}:
                con.execute(f'DROP VIEW temp.{_q(secret)}')
                raise ManagerViewError(f'{base} depends on other views {sorted(str(t) for t in tags if t != secret)}; '
                                       'the manager view cannot enforce masking through them.')
            con.execute(f'CREATE TEMP VIEW {_q(public_name)} AS SELECT * FROM {_q(secret)}')
            public.add(public_name)
            private.add(secret)
            for row in info:
                described.append(dict(view=public_name, **row))
                if public_name == 'm_player_view' and row['policy'] == ATTRIBUTE and row['field'] \
                        and not row['column'].endswith(('_min', '_max', '_state')):
                    attribute_columns[row['field']] = row['column']
            if public_name == 'm_player_view':
                # Its own private view over the named population only, so a statement on it
                # can never reach (or ask knowledge for) a player outside that population.
                scouted = f'{PRIVATE_PREFIX}{token}_m_scouted_player_view'
                sql, _ = _view_sql(scouted, base_query, columns, add_attributes, epoch=epoch, need=need_name,
                                   seeds_only=True, lazy=lazy)
                con.execute(sql)
                con.execute(f'CREATE TEMP VIEW m_scouted_player_view AS SELECT * FROM {_q(scouted)}')
                public.add('m_scouted_player_view')
                private.add(scouted)
        if 'm_player_view' not in public and 'm_player' not in public and (only is None or only & KNOWLEDGE_VIEWS):
            raise ManagerViewError('The snapshot has neither player_view nor player.')
        # every other table and view (collection tables, core tables, curated views)
        cat = catalog(con)
        ctx = _core_context(con)
        collection_public = {e.base for e in cat.values() if e.kind == 'collection' and e.scope == 'public'}
        listed, lazy_columns = [], set()
        for name, exp in sorted(cat.items()):
            reason = exp.reason
            if only is not None and name not in only:
                listed.append((name, exp.base, exp.kind, exp.scope, exp.rule, reason, ','.join(sorted(exp.tables))))
                continue
            try:
                base_query, columns, own, own_rows, lazy = _generic_build(con, exp, ctx, collection_public,
                                                                          dry_run=dry_run)
                secret = f'{PRIVATE_PREFIX}{token}_{name}'
                sql, info = _generic_view_sql(secret, name, base_query, columns, own, own_rows, lazy, need_name,
                                              _hidden_index(con, exp, columns))
                con.execute(sql)
                tags = _probe_innermost(con, secret)
                if tags - {secret}:
                    con.execute(f'DROP VIEW temp.{_q(secret)}')
                    raise Withheld(f'depends on other views {sorted(str(t) for t in tags if t != secret)}')
                con.execute(f'CREATE TEMP VIEW {_q(name)} AS SELECT * FROM {_q(secret)}')
            except (Withheld, sqlite3.Error) as exc:
                listed.append((name, exp.base, exp.kind, 'never', 'withheld', f'{exc}', ','.join(sorted(exp.tables))))
                continue
            public.add(name)
            private.add(secret)
            lazy_columns |= {c.lower() for c in lazy}
            described += [dict(view=name, **row) for row in info]
            listed.append((name, exp.base, exp.kind, exp.scope, exp.rule, reason, ','.join(sorted(exp.tables))))
        if (only is None or f'm_{OWN_CAREER_TABLE}' in only) and con.execute(
                "SELECT 1 FROM main.sqlite_master WHERE type = 'table' AND name = ?", (OWN_CAREER_TABLE,)).fetchone():
            name = f'm_{OWN_CAREER_TABLE}'
            con.execute(f'CREATE TEMP VIEW {name} AS SELECT * FROM main.{OWN_CAREER_TABLE}')
            public.add(name)
            listed.append((name, OWN_CAREER_TABLE, 'core', 'public', 'public',
                           "the user's own team (team.idx), club (club.idx) and manager name; also readable as "
                           f'{OWN_CAREER_TABLE}', ''))
        con.execute('CREATE TEMP TABLE m_tables(view TEXT, base TEXT, kind TEXT, scope TEXT, rule TEXT, '
                    'reason TEXT, collection_tables TEXT)')
        con.executemany('INSERT INTO temp.m_tables VALUES (?,?,?,?,?,?,?)', listed)
        con.execute('CREATE TEMP TABLE m_columns(view TEXT, column_name TEXT, code TEXT, policy TEXT, '
                    'field TEXT, note TEXT)')
        con.executemany('INSERT INTO temp.m_columns VALUES (?,?,?,?,?,?)',
                        [(d['view'], d['column'], d['code'], d['policy'], d['field'], d['note']) for d in described])
        con.execute('CREATE TEMP TABLE m_attribute_columns(field TEXT, code TEXT, code_100 TEXT, column_name TEXT)')
        con.executemany('INSERT INTO temp.m_attribute_columns VALUES (?,?,?,?)',
                        [(f['name'], f['code'], f['code_100'], attribute_columns.get(f['name'], f['column']))
                         for f in codes.FIELDS])
        cov = dict(coverage or {})
        con.execute('CREATE TEMP TABLE m_coverage(key TEXT PRIMARY KEY, value)')
        con.executemany('INSERT INTO temp.m_coverage VALUES (?,?)',
                        [(k, v if isinstance(v, (int, float, str)) or v is None else str(v)) for k, v in cov.items()])
        public |= {'m_columns', 'm_attribute_columns', 'm_coverage', 'm_tables'}
        con.manager_authorizer = _authorizer(public, private, dry_run=dry_run)
        con.set_authorizer(con.manager_authorizer)
        con.manager_info = dict(public_views=sorted(public), attribute_columns=attribute_columns,
                                snapshot=str(snapshot_path), knowledge=str(knowledge_path),
                                lazy_columns=sorted(lazy_columns))
        return con
    except Exception:
        con.close()
        raise


# ---------------------------------------------------------------------------------------------
# Query preparation
# ---------------------------------------------------------------------------------------------
@dataclass
class ManagerQuery:
    connection: ManagerConnection
    coverage: dict
    limited_to_scouted: bool
    complete: bool
    message: str
    notes: list[str] = field(default_factory=list)
    # {masked column: PERSON indices} of the on-demand public/own-club cells the statement read
    # (cells_read); None when the connection does not record them (no live game)
    cells: dict | None = None
    # {(view, column, table, table column): idx} of the on-demand core cells the generic views
    # showed (refs_read); None when not recorded
    refs: dict | None = None


def refs_read(need) -> dict:
    """{(view, column, table, table column): {idx}} of the `need(idx, 'ref:...')` records."""
    out = {}
    for idx, what in need:
        if isinstance(what, str) and what.startswith(REF) and idx is not None:
            out.setdefault(tuple(what[len(REF):].split('\t')), set()).add(idx)
    return out


def cells_read(need) -> dict:
    """{column: {idx}} of the `need(idx, 'cell:<column>')` records in a need set."""
    out = {}
    for idx, what in need:
        if isinstance(what, str) and what.startswith(CELL) and idx is not None:
            out.setdefault(what[len(CELL):], set()).add(idx)
    return out


def _paths(engine_or_paths):
    """(snapshot path, knowledge path, live game date or None, engine bridge or None)."""
    if isinstance(engine_or_paths, dict):
        snap = Path(engine_or_paths['snapshot'])
        return snap, Path(engine_or_paths.get('knowledge') or snap.with_name(ks.FILE_NAME)), None, None
    if isinstance(engine_or_paths, (tuple, list)):
        snap = Path(engine_or_paths[0])
        know = Path(engine_or_paths[1]) if len(engine_or_paths) > 1 and engine_or_paths[1] else \
            snap.with_name(ks.FILE_NAME)
        return snap, know, None, None
    if isinstance(engine_or_paths, (str, Path)):
        snap = Path(engine_or_paths)
        return snap, snap.with_name(ks.FILE_NAME), None, None
    info = engine_or_paths.save_info()
    root = ks.cache_root()
    bridge = getattr(engine_or_paths, '_bridge', None)
    return (root / info.save_key / 'snapshot.sqlite', root / info.save_key / ks.FILE_NAME, info.game_date,
            bridge)


_COUNTS: dict = {}          # (snapshot, inode, change seq, epoch, knowledge rows, universe) -> counts


def _snapshot_counts(snapshot: Path, knowledge: Path) -> dict:
    """Rows of the base view, those with current knowledge and those in the player universe.
    The three counts scan the curated view (0.7 s); they are kept while the snapshot's change
    sequence, the knowledge epoch and its row and universe counts are the same."""
    con = sqlite3.connect(f'file:{snapshot}?mode=ro', uri=True)
    try:
        con.execute('ATTACH DATABASE ? AS kn', (f'file:{knowledge}?mode=ro',))
        names = {r[0] for r in con.execute("SELECT name FROM main.sqlite_master WHERE type IN ('table','view')")}
        base = 'player_view' if 'player_view' in names else 'player'
        row = con.execute("SELECT value FROM kn._knowledge_meta WHERE key = 'epoch'").fetchone()
        epoch = int((ks.json.loads(row[0]) if row else {}).get('id', 0))
        try:
            seq = con.execute("SELECT value FROM main._fresh WHERE key = 'change_seq'").fetchone()
            key = (str(snapshot), os.stat(snapshot).st_ino, seq[0] if seq else None, base, epoch,
                   con.execute('SELECT count(*) FROM kn.knowledge_player WHERE epoch = ?', (epoch,)).fetchone()[0],
                   con.execute('SELECT count(*) FROM kn.knowledge_universe').fetchone()[0])
        except (sqlite3.Error, OSError):
            key = None
        snap_date = None
        if '_snapshot' in names:
            row = con.execute('SELECT game_date FROM _snapshot LIMIT 1').fetchone()
            snap_date = row[0] if row else None
        if key is not None and key in _COUNTS:
            return dict(_COUNTS[key], snapshot_game_date=snap_date)
        total = con.execute(f'SELECT count(*) FROM main.{base}').fetchone()[0]
        covered = con.execute(f'SELECT count(*) FROM main.{base} b JOIN kn.knowledge_player k ON k.idx = b.idx '
                              'AND k.epoch = ?', (epoch,)).fetchone()[0]
        in_universe = con.execute(f'SELECT count(*) FROM main.{base} b JOIN kn.knowledge_universe u '
                                  'ON u.idx = b.idx').fetchone()[0]
        out = dict(snapshot_rows=total, snapshot_rows_covered=covered, snapshot_rows_in_universe=in_universe,
                   snapshot_game_date=snap_date, snapshot_base=base)
        if key is not None:
            _COUNTS.clear()
            _COUNTS[key] = dict(out)
        return out
    finally:
        con.close()


PROBE_BATCH = 256           # query.fetch reads the cursor in batches of this size
PROBE_SECONDS = 60.0


def _probe(connection, sql, params, max_rows) -> bool:
    """Run the statement the way `query.fetch` will (same batches, same stop) so the need
    function sees every row the caller's fetch can evaluate. Returns False when the statement
    itself failed or ran out of time; the caller's own fetch reports that."""
    deadline = time.monotonic() + PROBE_SECONDS
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 50_000)
    try:
        cursor = connection.execute(sql, params or ())
        seen = 0
        while True:
            batch = cursor.fetchmany(PROBE_BATCH)
            if not batch:
                break
            seen += len(batch)
            if max_rows is not None and seen > max_rows:
                break
        return True
    except (sqlite3.Error, ValueError, TypeError):
        return False
    finally:
        connection.set_progress_handler(None, 0)


def prepare_manager_query(engine_or_paths, sql: str, *, bridge_or_session=None, coach_name=None,
                          require_idx=None, params=None, max_rows: int | None = None,
                          max_require: int = 5000, native: bool = True, max_passes: int = 6,
                          new_epoch: bool | None = None, **_legacy) -> ManagerQuery:
    """Check `sql`, compute the knowledge that statement needs, and return a masked connection.

    `engine_or_paths`: the snapshot lane's Engine (save key and live game date from
    `save_info()`), a snapshot path, `(snapshot, knowledge)` or `{'snapshot':, 'knowledge':}`.
    `bridge_or_session`: an attached Bridge or (bridge, session_id). `params` and `max_rows`
    are what the caller will pass to `query.fetch`.

    With a bridge, nothing is computed in advance. The statement is run against views whose
    knowledge expressions report the players they were evaluated for without a current
    knowledge row (`open_manager_connection(need=...)`); those players are brought up to date
    (`KnowledgeBuilder.ensure`, which evaluates only players whose inputs changed since their
    stored fingerprint) and the statement is run again, until a run reports none. A statement
    on `m_scouted_player_view` can only reach the named population; one that reads only public
    columns computes nothing. `ManagerQuery.complete` is True when the last run needed nothing.

    Without a bridge the stored knowledge is used as it is (rows of the current epoch only)
    and the live date cannot be checked. Raises ManagerViewError.
    """
    check_sql(sql)
    scouted_only = limited_to_scouted(sql)
    snapshot, knowledge, live_date, engine_bridge = _paths(engine_or_paths)
    target = bridge_or_session or engine_bridge
    names = referenced_names(sql)
    # create only the masked views the statement can name (m_columns describes every view)
    only = None if 'm_columns' in names else names
    if not (names & KNOWLEDGE_VIEWS) and 'kn' not in names and not require_idx:
        return _prepare_without_knowledge(snapshot, knowledge, sql, params, max_rows, only, names, live_date,
                                          live=target is not None)
    notes = []
    work = dict(passes=0, evaluated=0, confirmed=0, stars=0, seconds=0.0)
    connection = None
    complete = False
    cells = refs = None
    if target is not None:
        started = time.monotonic()
        try:
            store = ks.KnowledgeStore(knowledge)
        except sqlite3.Error as exc:
            raise ManagerViewError(f'Knowledge store unusable: {exc}') from exc
        try:
            builder = ks.KnowledgeBuilder(target, store, coach_name=coach_name, native=native)
            change = builder.refresh_identity(new_epoch=new_epoch)
            if change.get('invalidated') and change.get('reason') != 'new store':   # a first store drops nothing
                notes.append(f'knowledge dropped: {change["reason"]}')
            live_date = builder.ident['game_date']
            builder.seeds()
            builder.ensure_universe()
            if require_idx:
                ids = sorted({int(i) for i in require_idx})
                if len(ids) > max_require:
                    raise ManagerViewError(f'require_idx lists {len(ids)} players; the limit is {max_require}.')
                builder.ensure(ids)
                builder.ensure_stars(ids, search=ids)
            for _ in range(max_passes):
                need = set()
                connection = open_manager_connection(snapshot, knowledge, need=need, only=only)
                work['passes'] += 1
                ok = _probe(connection, sql, params, max_rows)
                missing = {(idx, what) for idx, what in need if what in (1, 2)}
                if not missing:
                    complete = ok
                    break
                connection.close()
                connection = None
                wanted = sorted({idx for idx, _ in missing if idx is not None})
                builder.ensure(wanted)
                with_stars = sorted({idx for idx, what in missing if what == 2 and idx is not None})
                if with_stars:
                    builder.ensure_stars(with_stars)
                if store.game_date() != live_date:        # the day moved while computing
                    live_date = store.game_date()
                    builder.seeds()
                    builder.ensure_universe()
            else:
                need = set()
                connection = open_manager_connection(snapshot, knowledge, need=need, only=only)
                _probe(connection, sql, params, max_rows)
                notes.append(f'knowledge still incomplete for this statement after {max_passes} passes')
            cells = cells_read(need)
            refs = refs_read(need)
            work.update(evaluated=builder.stats['evaluated'], confirmed=builder.stats['kept'],
                        stars=builder.stats['stars'], seconds=round(time.monotonic() - started, 2))
            cov = store.coverage()
        except ks.KnowledgeError as exc:
            if connection is not None:
                connection.close()
            raise ManagerViewError(str(exc)) from exc
        finally:
            store.close()
    else:
        if not knowledge.is_file():
            raise ManagerViewError(f'No manager knowledge at {knowledge}; attach FM27 to build it.')
        store = ks.KnowledgeStore.__new__(ks.KnowledgeStore)
        store.path, store.con = knowledge, ks.connect(knowledge, readonly=True)
        try:
            cov = store.coverage()
        finally:
            store.con.close()
        notes.append('no live game attached: knowledge is as stored and was not checked against the game')
        if live_date is not None and cov.get('game_date') != live_date:
            raise ManagerViewError(f'Manager knowledge is for {cov.get("game_date")} but the game is on '
                                   f'{live_date}; attach FM27 so it can be brought up to date.')
        if not cov.get('knowledge_rows'):
            raise ManagerViewError('Manager knowledge has no current rows; attach FM27 to compute them.')
        complete = bool(cov.get('tier1_complete') if scouted_only else cov.get('tier3_complete'))
    counts = _snapshot_counts(snapshot, knowledge)
    universe = cov.get('universe_players')
    if target is not None:
        message = ('Knowledge computed for the rows this statement reads: '
                   f'{work["evaluated"]} players evaluated, {work["confirmed"]} confirmed unchanged, in '
                   f'{work["seconds"]} s ({work["passes"]} pass{"es" if work["passes"] != 1 else ""}); '
                   f'{cov["universe_players_covered"]} of {universe} players of the save are current.')
        if not complete:
            message = 'PARTIAL: ' + message
    elif complete and scouted_only:
        message = f'Scouted population complete: {cov["scouted_rows"]} players known by node, report or own roster.'
    elif complete:
        message = (f'Complete: manager knowledge covers all {cov["universe_players_covered"]} players of the '
                   f'native player list ({cov["unavailable_rows"]} with every attribute unavailable).')
    else:
        denominator = universe if universe else counts['snapshot_rows']
        covered = cov['universe_players_covered'] if universe else counts['snapshot_rows_covered']
        message = (f'PARTIAL: stored manager knowledge covers {covered} of {denominator} players of this save '
                   f'({100.0 * covered / max(denominator, 1):.1f}%); results include only those players. '
                   'Attach FM27 to compute what a statement needs.')
    if target is None or complete:
        outside = counts['snapshot_rows'] - counts['snapshot_rows_in_universe']
        if outside > 0 and (target is not None or cov.get('tier3_complete')):
            message += (f' {outside} of {counts["snapshot_rows"]} snapshot {counts["snapshot_base"]} rows are '
                        'outside the native player list and are not in the manager view.')
    coverage = dict(cov, **counts, limited_to_scouted=scouted_only, complete=complete, message=message,
                    fill_running=False, fill_pid=None, live_game_date=live_date, on_demand=work)
    coverage.pop('timings', None)
    if counts['snapshot_game_date'] and cov.get('game_date') and counts['snapshot_game_date'] != cov['game_date']:
        notes.append(f'snapshot is from {counts["snapshot_game_date"]}, knowledge from {cov["game_date"]}')
    if connection is None:
        connection = open_manager_connection(snapshot, knowledge, coverage=coverage, only=only)
    else:
        connection.set_authorizer(None)
        try:
            connection.executemany('INSERT OR REPLACE INTO temp.m_coverage VALUES (?,?)',
                                   [(k, v if isinstance(v, (int, float, str)) or v is None else str(v))
                                    for k, v in coverage.items()])
        finally:
            connection.set_authorizer(connection.manager_authorizer)
    return ManagerQuery(connection, coverage, scouted_only, complete, message, notes, cells=cells, refs=refs)


def _prepare_without_knowledge(snapshot, knowledge, sql, params, max_rows, only, names, live_date, *,
                               live: bool) -> ManagerQuery:
    """A statement that reads no player knowledge (collection tables, core tables, curated views):
    no knowledge is read or computed. With a live game, a statement that names an on-demand
    column of a core table (a team or competition name) is probed once so `tools.manager_prewarm`
    can compute those cells for exactly the rows it shows."""
    refs = None
    connection = open_manager_connection(snapshot, knowledge, only=only, need=set() if live else None)
    try:
        lazy = set(connection.manager_info.get('lazy_columns') or ())
        if live and lazy & names:
            _probe(connection, sql, params, max_rows)
            refs = refs_read(connection.manager_need)
    except Exception:
        connection.close()
        raise
    message = 'No player knowledge read: the statement reads only views that do not depend on it.'
    coverage = dict(complete=True, knowledge_read=False, live_game_date=live_date, message=message,
                    limited_to_scouted=False, fill_running=False,
                    on_demand=dict(passes=0, evaluated=0, confirmed=0, stars=0, seconds=0.0))
    return ManagerQuery(connection, coverage, False, True, message, [], cells=None, refs=refs)
