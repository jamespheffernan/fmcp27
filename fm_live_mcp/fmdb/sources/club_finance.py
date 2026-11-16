"""Club wage bill and budgets the `club` table lacks: one lazy row per CLUB entry (`club_finance`).

Every value is the club record's own property getter run in the VM with the game-layer fallback:
the CLUB getter 0xE476C4 hands finance keys to the finance object (club +0x150: CLUB_FINANCE getter
0xE7DFB8, CLUB_FINANCE_BASE 0xE7D238) and GAME_CLUB (0x1FAF4D8) answers the current budgets. The
keys here are outside the editor catalog (wage bill Ccwt/ClPa, remaining budget Cwrb, Cntb, Csba);
each column gives the evidence for its label. The other finance and facility values are `club`
columns (see the comment above FIELDS); the editor-only club keys Ctbu, Crmb, CcfE read their live
keys through fieldroutes.ROUTES.

Lazy (`MODE`): no build computes it; a query computes the rows it needs. Invalidation: game date.

Checked (scripts/fmdb_club_finance_check.py): against the hand-built club_finance.decode and
financial_details.club_details on 50 clubs, and against the managed club's finances screen.
"""
from __future__ import annotations

import dataclasses
import json

try:                                    # the collections lane's contract (sources/__init__.py)
    from . import Column, SourceTable
except ImportError:                     # pragma: no cover - same shape, defined locally until it lands
    @dataclasses.dataclass
    class Column:
        name: str
        sql_type: str
        meaning: str
        enum: dict | None = None
        references: str | None = None

    @dataclasses.dataclass
    class SourceTable:
        name: str
        description: str
        columns: list
        rows: object
        key: str = 'idx'
        cost_note: str = ''

GBP_WEEK = 'GBP per week'
# (column, key, member of a record value or None, sql type, meaning)
# Columns the `club` table lacks (keys outside the editor catalog); every other finance and facility
# value is a `club` column: direct plans for balance Ccba, scouting package CScP, season ticket holders
# Csth, ticket prices Cmtp/Casp, ownership Cown, Csot, training Ctlv, youth Cyfb/Cytv/Crcb; on demand for
# the transfer budget (Ctbu -> Ctfc), remaining wage budget (Crmb -> Cwrb), scouting budget CSbR,
# corporate facilities (CcfE -> Ccfa), debts Cdbt/Cfln/Chdb, instalments Cmti, income Coin, Cwcl.
FIELDS = (
    ('wage_budget_weekly', 'Cwwb', None, 'INTEGER',
     f'total wage budget, {GBP_WEEK} (catalog "Wage Budget"; CLUB_FINANCE getter 0xE7DFB8)'),
    ('wage_spend_weekly', 'Ccwt', None, 'INTEGER',
     f'wage bill recomputed by the game layer, {GBP_WEEK} (game-layer key Ccwt, outside the catalog; equal to '
     'the stored spending at finance +0x814 on 36 of 44 checked clubs, the rest differ by up to 6%: the stored '
     'figure lags contract changes); NULL without a full CLUB_FINANCE'),
    ('wage_spend_annual', 'ClPa', None, 'INTEGER',
     'stored wage spending per year, GBP (game-layer key ClPa, outside the catalog; equals the stored weekly '
     'spending at finance +0x814 x 52 on every checked club and the finances screen\'s wage total); '
     '-1 without a full CLUB_FINANCE'),
    ('remaining_wage_budget_weekly', 'Cwrb', None, 'INTEGER',
     f'wage budget not yet committed, {GBP_WEEK} (game-layer key Cwrb; wage_budget.py: budget less stored '
     'spending, without recalculation); -1 without a full CLUB_FINANCE'),
    ('transfer_budget_finance_Cntb', 'Cntb', None, 'INTEGER',
     'CLUB_FINANCE getter key Cntb (outside the catalog), GBP; label not established'),
    ('budget_record_Csba', 'Csba', None, 'TEXT',
     'game-layer record Csba as JSON: otfu/atfu equal the transfer budget and owbu/awbu the scouting budget on '
     'the checked clubs; bmat/bmit/bmaw/bmiw are the board budget-adjustment bounds (labels inferred)'),
)
COMPUTED = (
    ('wage_budget_annual', 'INTEGER', 'wage_budget_weekly x 52, GBP per year (computed; the finances screen shows '
                                      'this figure)'),
    ('remaining_wage_budget_annual', 'INTEGER', 'remaining_wage_budget_weekly x 52, GBP per year (computed)'),
)
NOT_FOUND = {
    'maximum_wage': 'editor CMWE is answered only from STARTING_CLUB_DEBT (0 records); no live getter key found; '
                    'next route: the finances UI handler (UI keys FinanceDebugMaximumWage, AdvisedMaxBasicWage)',
    'data_analysis_facilities': 'no catalog or getter key found for the club; next route: the facilities UI handler',
    'takeover_state': 'only Csot (stop outside takeovers) and Cown (ownership type) are getter keys; '
                      'next route: the takeover news/board UI handlers',
}


def _value(engine, record, key):
    res = engine.get_property(record, key)
    value = res.value
    if type(value).__name__ == 'Unavailable' or res.kind in (None, 'null'):
        return None
    from .. import variant
    out = variant.to_json(value)
    if isinstance(out, (dict, list)):
        return json.dumps(out, sort_keys=True, default=str)
    if isinstance(out, bool):
        return int(out)
    if isinstance(out, (int, float, str)):
        return out
    return str(out)


def row(engine, idx: int, record: int) -> tuple:
    """(idx, club pointer's values in FIELDS order, then COMPUTED)."""
    values = [_value(engine, record, key) for _, key, _, _, _ in FIELDS]
    named = dict(zip((f[0] for f in FIELDS), values))
    weekly = named.get('wage_budget_weekly')
    remaining = named.get('remaining_wage_budget_weekly')
    full = isinstance(weekly, int) and weekly >= 0         # only clubs with a full CLUB_FINANCE keep budgets
    computed = [weekly * 52 if full else None,
                remaining * 52 if full and isinstance(remaining, int) else None]   # negative: over budget
    return (idx, *values, *computed)


def columns() -> list:
    out = [Column('idx', 'INTEGER', 'club.idx (live CLUB table index)', references='club')]
    out += [Column(name, sql, meaning) for name, _, _, sql, meaning in FIELDS]
    out += [Column(name, sql, meaning) for name, sql, meaning in COMPUTED]
    return out


def cell(engine, idx: int, column: str):
    """One cell on demand: the getter call for `column` of club `idx` (computed columns call their input)."""
    pointers, _ = engine.table_entries('clubs')
    record = pointers[idx]
    if not record:
        return None
    if column in ('wage_budget_annual', 'remaining_wage_budget_annual'):
        return dict(zip((c.name for c in columns()), row(engine, idx, record)))[column]
    key = next(k for name, k, _, _, _ in FIELDS if name == column)
    return _value(engine, record, key)


# Measured 2026-11-11, FastVM, one process at nice 10, load average 250-300: see FIELDS.md.
MODE = 'lazy'               # never computed by a build: the rows a query needs, on demand
INVALIDATION = 'game_date'  # budgets, wage bill and balance change at the day tick


def tables(engine) -> list:
    def rows(idxs=None):
        """All clubs, or only the club idx values given (on-demand queries)."""
        pointers, _ = engine.table_entries('clubs')
        wanted = range(len(pointers)) if idxs is None else idxs
        for idx in wanted:
            record = pointers[idx] if 0 <= idx < len(pointers) else 0
            if record:
                yield row(engine, idx, record)
    extra = {}
    names = {f.name for f in dataclasses.fields(SourceTable)}
    if 'mode' in names:
        extra['mode'] = MODE
    if 'invalidation' in names:
        extra['invalidation'] = INVALIDATION
    if 'slow' in names and 'mode' not in names:
        extra['slow'] = True        # older contract: at least keep it out of the inline build
    if 'source_note' in names:
        extra['source_note'] = ('CLUB record getter in the VM with the game-layer fallback (finance object club+0x150 '
                                'and GAME_CLUB answer the budgets); not found: ' + '; '.join(
                                    f'{k}: {v}' for k, v in NOT_FOUND.items()))
    if 'manager' in names:
        extra['manager'] = {'scope': 'own_club', 'own_club_column': 'idx',
                            'reason': 'the game shows budgets and the wage bill for the manager\'s own club only'}
    if 'indexes' in names:
        extra['indexes'] = ()
    return [SourceTable('club_finance', 'wage bill (weekly and per year), wage budget per year, remaining wage '
                        'budget (weekly and per year) and budget records for every club; balance, transfer and '
                        'scouting budgets, tickets, debts, income, ownership and facilities are club columns',
                        columns(), rows,
                        cost_note=('lazy: 6 getter calls per club row; CPU per row 0.6-0.9 ms for the 27,301 clubs without a full '
                                   'CLUB_FINANCE, 1.2-5.4 ms for the 721 with one (Ccwt recomputes the bill); no direct plan'),
                        **extra)]
