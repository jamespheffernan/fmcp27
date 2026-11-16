"""Club finance ledger, sponsorships, loans and labelled affiliations (docs/fmdb/MANAGERS_MARKET.md).

The finance tables are the Finances screens of the managed club, read by running the game's own
CLUB_UI_HANDLER (the DATABASE_RECORD handler, type 28, for the club) in the UI VM on copied live
memory, the way `fm_ui_read` and the sweep read them; nothing is written to the game:

* `club_finance_breakdown`  Finances > Income / Expenditure: every category for this month, last
                             month, this season and last season (keys IncomeBreakdownThisMonth ...
                             ExpenditureBreakdownLastSeason): amount, share of the total, change
* `club_finance_month`       the monthly graphs of the same screens: balance, income, expenditure,
                             wage and scouting expenditure, remaining transfer budget (TotalIncomeGraph,
                             TotalExpenditureGraph, FinanceBalanceHistory, Finance*History)
* `club_sponsorship`         Finances > Sponsors (SponsorshipsData): deal, value per season, length,
                             end date, total value
* `club_debt_loan`           Finances > Debts and loans (DebtsAndLoansData)

They hold the managed clubs only (the game lets other clubs' finances be viewed only with the
`CanViewFinances*` permissions; the manager view withholds them). Lazy, game-date invalidation: the
handler runs once per managed club when a statement names a table (about 0.4 s a club).

`club_affiliation` (view) labels every current affiliation of every club (club.current_affiliations,
editor list Cafl): the editor catalog names each item field and the type enum (CAfT), and the view adds
the FEEDER_CLUB_MANAGER group the link belongs to (`feeder_club_group`).
"""
from __future__ import annotations

import datetime as _dt

from . import Column, SourceTable
from . import _common as C

PERIODS = (('this_month', 'ThisMonth'), ('last_month', 'LastMonth'), ('this_season', 'ThisSeason'),
           ('last_season', 'LastSeason'))
BREAKDOWN_KEYS = {f'{d}_{p}': f'{D}Breakdown{P}' for d, D in (('income', 'Income'), ('expenditure', 'Expenditure'))
                  for p, P in PERIODS}
MONTH_KEYS = {'balance': 'FinanceBalanceHistory', 'income': 'TotalIncomeGraph',
              'expenditure': 'TotalExpenditureGraph', 'wage_expenditure': 'FinanceWageExpenditureHistory',
              'scouting_expenditure': 'FinanceScoutingExpenditureHistory',
              'transfer_budget_remaining': 'FinanceTransferBudgetRemainingHistory'}
OTHER_KEYS = {'sponsorships': 'SponsorshipsData', 'debts': 'DebtsAndLoansData',
              'affiliations': 'AffiliatedClubsDetailsList'}
CLUB_TABLE_TYPE = 3

# editor catalog, club/Cafl/type (enum CAfT), copied from editor.fmf (tests compare it with the catalog).
# Code 21 has no label in the catalog (406 links on 13 Dec 2030): `type` is NULL there, type_code says 21.
AFFILIATION_TYPES = {1: 'Normal Affiliated Club', 2: 'Sub Team', 3: 'Feeder Team', 4: 'B Club', 5: 'C Club',
                     6: '2 Club', 7: '3 Club', 8: 'II Club', 16: 'Good Relations', 17: 'Likely Friendly',
                     18: 'Shared Youth Club', 22: 'Regional Academy', 24: 'Extinct B or C Club',
                     25: 'Opposite Gender Club'}
# (view column, item code, editor label) for club/Cafl items
AFFILIATION_TERMS = (
    ('yearly_fee', 'yfee', 'Yearly Fee'),
    ('friendly_chance_percent', 'fri%', 'Percentage Chance Of Friendly Each Year'),
    ('players_move_freely', 'frly', 'Players Move Freely'),
    ('players_go_on_loan', 'golo', 'Players Go On Loan'),
    ('first_option_to_buy', 'fotb', 'First Option To Buy'),
    ('uses_same_kit', 'UsSK', 'Uses Same Kit'),
    ('play_friendlies', 'plfr', 'Play Friendlies'),
    ('same_board', 'smbo', 'Same Board'),
    ('financial_help', 'fnhl', 'Financial Help'),
    ('permanent_deal', 'perm', 'Permanent Deal'),
    ('youth_players_training', 'yutr', 'Youth Players Training'),
    ('help_with_facilities', 'hlwf', 'Help With Facilities'),
    ('marketing_relations', 'mrrl', 'Marketing Relations'),
    ('scouting_knowledge_shared', 'scks', 'Scouting Knowledge Shared'),
    ('cannot_play_in_same_division', 'cpsd', 'Cannot Play In Same Division'),
    ('uses_all_parent_club_facilities', 'ualf', 'Uses All Parent Club Facilities'),
    ('loan_players_from_sub_team', 'lpfs', 'Loan Players from Sub Team'),
    ('uses_sub_team_training_facilities', 'ustf', 'Uses Sub Team Training Facilities'),
    ('max_players_loaned', 'msls', 'Maximum No. Players Loaned'),
    ('sends_youth_for_experience', 'yout', 'Sends youth players to gain experience'),
    ('showcases_reserve_players', 'rsrv', 'Link used to showcase reserve players'),
    ('sends_first_team_for_promotion', 'pfpr', 'Sends first team players to aid affiliate club with promotion'),
    ('loan_wage_percent_paid_by_parent', 'pwgp', 'Percentage of loan player wage paid by parent club'),
    ('b_team_trains_with_main_club', 'bttr', 'Players with the B Team train alongside players from the main club'),
)


# --------------------------------------------------------------------------- reading
def managed_clubs(engine) -> list[int]:
    """Club-table indexes of the human managers' clubs (tables.managed: the loaded career's coaches)."""
    from .. import tables
    clubs, _ = tables.managed(engine.read, engine.base)
    index = C.index_of(engine, 'clubs')
    out = []
    for p in clubs:
        i = index.get(p)
        if i is not None and i not in out:
            out.append(i)
    return out


def _codes(names: dict) -> dict:
    from .. import ui_registry
    reg = ui_registry.default()
    out = {}
    for name, label in names.items():
        codes = list(reg.codes(label))
        if not codes:
            raise KeyError(f'UI key {label} not in the registry')
        out[name] = codes[0]
    return out


def read_club_screens(engine, clubs=None) -> dict:
    """{club idx: {name: value}} of the finance keys, through one UI VM (history_read.UiReader)."""
    cache = C.cache(engine)
    from ..history_read import UiReader
    keys = _codes({**BREAKDOWN_KEYS, **MONTH_KEYS, **OTHER_KEYS})
    clubs = managed_clubs(engine) if clubs is None else clubs
    stamp = (engine.base, tuple(clubs), _game_date(engine))
    if cache.get('market_state_screens', (None,))[0] == stamp:
        return cache['market_state_screens'][1]
    reader = UiReader(engine)
    try:
        out = {c: reader.read(CLUB_TABLE_TYPE << 24 | c, keys) for c in clubs}
    finally:
        reader.close()
    cache['market_state_screens'] = (stamp, out)
    return out


def _game_date(engine):
    try:
        return engine.game_date()
    except Exception:  # noqa: BLE001
        return None


def _iso(value):
    """ISO date of a date value ('YYYY-MM-DD' or {'date': ...}); None for the no-date value."""
    if isinstance(value, dict):
        value = value.get('date')
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        d = _dt.date.fromisoformat(value[:10])
    except ValueError:
        return None
    return None if d.year <= 1900 else d.isoformat()


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _list(value):
    return value if isinstance(value, list) else []


# --------------------------------------------------------------------------- row shaping (pure)
def breakdown_rows(club, values) -> list[tuple]:
    rows = []
    for name in BREAKDOWN_KEYS:
        direction, period = name.split('_', 1)
        for item in _list(values.get(name)):
            if not isinstance(item, dict):
                continue
            rows.append((club, direction, period, _num(item.get('id  ')), item.get('name'), _num(item.get('ptvl')),
                         _num(item.get('iSzq')), _num(item.get('Zf6i')), item.get('qvJ6')))
    return rows


def month_rows(club, values) -> list[tuple]:
    rows = []
    for series in MONTH_KEYS:
        for item in _list(values.get(series)):
            if isinstance(item, dict):
                rows.append((club, series, _iso(item.get('H gt')), _num(item.get('dEkT'))))
    return rows


def sponsorship_rows(club, values) -> list[tuple]:
    rows = []
    for n, item in enumerate(_list(values.get('sponsorships'))):
        if isinstance(item, dict):
            rows.append((club, n, item.get('name'), item.get('pd6h'), item.get('6sdl'), _iso(item.get('Pced')),
                         _num(item.get('ptvl'))))
    return rows


def debt_rows(club, values) -> list[tuple]:
    rows = []
    for n, item in enumerate(_list(values.get('debts'))):
        if isinstance(item, dict):
            rows.append((club, n, item.get('namf'), _num(item.get('ptvl')), item.get('AZI2'), item.get('hmEy'),
                         item.get('KWKt'), item.get(' juQ'), _iso(item.get('PcSd')), _iso(item.get('Pced'))))
    return rows


def affiliation_detail_rows(club, values) -> list[tuple]:
    rows = []
    for n, item in enumerate(_list(values.get('affiliations'))):
        if not isinstance(item, dict):
            continue
        ref = item.get('16  ') if isinstance(item.get('16  '), dict) else {}
        oid = ref.get('dref')
        other = oid & 0xFFFFFF if isinstance(oid, int) and oid >> 24 == CLUB_TABLE_TYPE else None
        terms = item.get('Z13B')
        rows.append((club, n, other, _iso(item.get('PcSd')), item.get('GFy '), _num(item.get('ERNL')),
                     '\n'.join(t for t in terms if isinstance(t, str)) if isinstance(terms, list) else None))
    return rows


def _rows(engine, shape):
    out = []
    for club, values in read_club_screens(engine).items():
        out += shape(club, values)
    return out


def _coverage(engine, names):
    def note():
        from ..vm import Unavailable
        bad = []
        for club, values in (C.cache(engine).get('market_state_screens', (None, {}))[1] or {}).items():
            for n in names:
                v = values.get(n)
                if isinstance(v, Unavailable) or v is None:
                    bad.append(f'club {club} {n}: {getattr(v, "reason", "unset")}')
        return '; '.join(bad[:6])
    return note


# --------------------------------------------------------------------------- tables
def tables(engine):
    own = {'scope': 'own_club', 'own_club_column': 'club_idx',
           'reason': 'the Finances screens show the manager\'s own club; other clubs are withheld'}
    common = dict(mode='lazy', invalidation='game_date', manager=own, indexes=('club_idx',))
    club = Column('club_idx', 'INTEGER', 'the managed club (club-table index)', references='club')
    note = ('CLUB_UI_HANDLER (DATABASE_RECORD type 28, dref = the club) run in the UI VM on copied live memory; '
            'keys {}')
    return [
        SourceTable(
            'club_finance_breakdown',
            'Finances > Income and Expenditure of the managed club: every category for this month, last month, '
            'this season and last season, as the screens show them',
            [club,
             Column('direction', 'TEXT', "'income' or 'expenditure'"),
             Column('period', 'TEXT', "'this_month', 'last_month', 'this_season', 'last_season'"),
             Column('category_id', 'INTEGER', 'category number in the game\'s list (item key "id  ")'),
             Column('category', 'TEXT', 'category name as the screen shows it (Gate Receipts, TV Revenue, '
                                        'Sponsorship, Player Wages, ...)'),
             Column('amount', 'INTEGER', 'amount in the game\'s base currency (pounds; item key ptvl)'),
             Column('percent_of_operating_total', 'INTEGER',
                    'the percentage the screen shows beside the amount (item key iSzq, label Percentage), '
                    'truncated: income rows are a share of the period\'s turnover (key '
                    'TotalIncome<Period>Turnover: total income less Players Sold and Investments), so Players '
                    'Sold can exceed what its share of all income would be; expenditure rows are a share of '
                    'total expenditure less Transfer Expenditure (inferred from the amounts: exact on every row '
                    'of 13 Dec 2030), so Transfer Expenditure can exceed 100; 0 for the last-month and '
                    'last-season lists, which the screen shows without percentages'),
             Column('change_percent', 'INTEGER', 'change shown beside the amount, percent (item key Zf6i, '
                                                 'label MonthToMonthPercentage)'),
             Column('display', 'TEXT', 'the amount as the screen formats it (item key qvJ6)')],
            lambda: _rows(engine, breakdown_rows), cost_note='one CLUB_UI_HANDLER per managed club (~0.4 s)',
            source_note=note.format(', '.join(BREAKDOWN_KEYS.values())),
            coverage=_coverage(engine, list(BREAKDOWN_KEYS)), **common),
        SourceTable(
            'club_finance_month',
            'monthly series of the managed club\'s Finances screens: balance, total income, total expenditure, '
            'wage and scouting expenditure, remaining transfer budget (one row per series and month)',
            [club,
             Column('series', 'TEXT', "'balance' (FinanceBalanceHistory), 'income' (TotalIncomeGraph), "
                                      "'expenditure' (TotalExpenditureGraph), 'wage_expenditure' "
                                      "(FinanceWageExpenditureHistory), 'scouting_expenditure' "
                                      "(FinanceScoutingExpenditureHistory), 'transfer_budget_remaining' "
                                      "(FinanceTransferBudgetRemainingHistory)"),
             Column('month', 'TEXT', 'first day of the month (graph point date, item key "H gt")'),
             Column('amount', 'INTEGER', 'value of the month in pounds (item key dEkT, label GraphPointY)')],
            lambda: _rows(engine, month_rows), cost_note='with club_finance_breakdown',
            source_note=note.format(', '.join(MONTH_KEYS.values())),
            coverage=_coverage(engine, list(MONTH_KEYS)), **common),
        SourceTable(
            'club_sponsorship',
            'Finances > Sponsors of the managed club: every sponsorship deal with its value per season, length, '
            'end date and total value',
            [club,
             Column('deal', 'INTEGER', 'position in the screen\'s list'),
             Column('name', 'TEXT', 'deal type as shown (Main Kit, Kit Manufacturer, Shirt Sleeve, General, ...)'),
             Column('value_per_season', 'TEXT', 'value per season as the screen formats it (key pd6h, label '
                                                'SponsorshipValuePerSeason)'),
             Column('duration', 'TEXT', 'deal length as shown (key 6sdl, label Duration)'),
             Column('end_date', 'TEXT', 'deal end date (key Pced, label EndDate)'),
             Column('total_value', 'INTEGER', 'total value of the deal in pounds (key ptvl; equals the value per '
                                              'season times the years on the checked deals)')],
            lambda: _rows(engine, sponsorship_rows), cost_note='with club_finance_breakdown',
            source_note=note.format('SponsorshipsData'), coverage=_coverage(engine, ['sponsorships']), **common),
        SourceTable(
            'club_debt_loan',
            'Finances > Debts and loans of the managed club: each loan and the overall line',
            [club,
             Column('entry', 'INTEGER', 'position in the screen\'s list'),
             Column('name', 'TEXT', 'loan name as shown (Mortgage Loan, ..., Overall)'),
             Column('amount', 'INTEGER', 'loan amount in pounds (key ptvl)'),
             Column('original_debt', 'TEXT', 'as shown (key AZI2, label OriginalDebt)'),
             Column('remaining_debt', 'TEXT', 'as shown (key hmEy, label RemainingDebt)'),
             Column('payable_per_month', 'TEXT', 'as shown (key KWKt, label PayablePerMonth)'),
             Column('value_juq', 'TEXT', 'fourth amount of the row (key " juQ"; the registry gives no label: '
                                         'not established)'),
             Column('start_date', 'TEXT', 'key PcSd (label StartDate); NULL when the row has none'),
             Column('end_date', 'TEXT', 'key Pced (label EndDate); NULL when the row has none')],
            lambda: _rows(engine, debt_rows), cost_note='with club_finance_breakdown',
            source_note=note.format('DebtsAndLoansData'), coverage=_coverage(engine, ['debts']), **common),
        SourceTable(
            'club_affiliation_detail',
            'the managed club\'s affiliations as its club screen describes them: the other club, start date, the '
            'game\'s one-line description of the link and the sentences saying what each side gets',
            [club,
             Column('entry', 'INTEGER', 'position in the screen\'s list'),
             Column('affiliated_club_idx', 'INTEGER', 'the other club (key "16  ", a CLUB record reference)',
                    references='club'),
             Column('start_date', 'TEXT', 'link start date (key PcSd)'),
             Column('description', 'TEXT', 'the game\'s description of the link (key "GFy "), e.g. "A local '
                                           'partnership in which players are loaned."'),
             Column('cost', 'INTEGER', 'key ERNL (registry label Cost)'),
             Column('terms', 'TEXT', 'the screen\'s sentences on what each side gets, one per line (key Z13B, '
                                     'label AffiliateClubLinkStrings)')],
            lambda: _rows(engine, affiliation_detail_rows), cost_note='with club_finance_breakdown',
            source_note=note.format('AffiliatedClubsDetailsList'), coverage=_coverage(engine, ['affiliations']),
            **dict(common, manager={'scope': 'own_club', 'own_club_column': 'club_idx',
                                    'reason': 'read for the managed club only (the same list shows on every club '
                                              'profile; club_affiliation holds every club\'s links)'})),
        _agent_demand_table(engine),
    ]


# --------------------------------------------------------------------------- agent demands
# What a player's agent says the player would want from the managed club (the "agent demands" panel,
# PERSON_UI_HANDLER key PlayerAgentDemands '1NxK'). The game keeps a computed demands object (0x210
# bytes, ctor 0xD6AE68) only for players whose agent has been in contact (human store +0xCC8, the vector
# GAME_PLAYER slot 9 searches for data key 'PPaD' at 0x20BEB10). For any other player it is computed
# here the way the game computes it, in the UI VM on copied live memory:
#   player object = person record vtable +0x668 (as 0x260D47C passes it)
#   0xD6B0E0(obj, context, player, club, 0, 4)       fills the object (0x12DE8DC is the game's wrapper)
#   0x204DCA4(obj, 0, &tmp) -> typed value            the server's 'PPaD' value (GAME_PLAYER slot 9, 0x20CCA2C)
#   PlayerAgentDemands with data key PPaD = that value: the client getter 0x3D9920 (case 0x3DAA40)
#   -> 0x3E9618 -> 0xD6D1B0, which writes one line per demand (GAME_AGENT_PLAYER_DEMANDS slot 11
#   0x1FA0AE0 -> 0x24419A4 words each line from its type code).
# Context 2 is the scouting context (0x396E170 'SCOUTED_PERSON_TAG', 0x12DD648 deadline-day agent
# offers); 1 is the transfer-status context (0x276EEA8), 3 the contract manager's daily pass (0x260AFA4).
DEMANDS_SIZE = 0x210
DEMANDS_CTOR, DEMANDS_COMPUTE, DEMANDS_VALUE = 0xD6AE68, 0xD6B0E0, 0x204DCA4
PLAYER_OBJECT_SLOT_OFFSET = 0x668
DEMANDS_CONTEXT = 2
# object fields the line writer 0xD6D1B0 reads (u32 unless noted); amounts are pounds, wages weekly
DEMANDS_FIELDS = {'agent_idx': 0x1B8, 'person_idx': 0x1BC, 'player_club_idx': 0x1C0, 'fee_min': 0x1C4,
                  'fee_max': 0x1C8, 'wage_min': 0x1D0, 'wage_max': 0x1D4}
DEMANDS_DATES = {'offer_date': 0x1F0, 'contract_end': 0x1F8}
DEMANDS_MAX_KEYS = 60


def compute_agent_demands(engine, people, club_idx, context=DEMANDS_CONTEXT):
    """{person idx: {...}} for these people and the club: the demand lines as the game words them and
    the object's amounts and dates. One UI VM for the batch (history_read.UiReader)."""
    import struct
    import time
    import unicorn
    from unicorn import arm64_const as A
    from .. import mgr_walk as W
    from .. import ui_recipes_person as P
    from ..history_read import UiReader
    from ..vm import Unavailable
    records = C.live(engine, 'people').pointers
    clubs = C.live(engine, 'clubs').pointers
    club = clubs[club_idx] if 0 <= club_idx < len(clubs) else 0
    reader = UiReader(engine)
    vm, base, out = reader.vm, engine.base, {}
    try:
        for k in people:
            started = time.perf_counter()
            record = records[k] if 0 <= k < len(records) else 0
            if not record or not club:
                continue
            try:
                handler = vm.build(P.DATABASE_RECORD, {'dref': 1 << 24 | k})
                data = P.DataReader(vm, handler)
                vm._restore()
                table = struct.unpack('<Q', vm.read(record, 8))[0]
                player, _ = vm.call(struct.unpack('<Q', vm.read(table + PLAYER_OBJECT_SLOT_OFFSET, 8))[0], [record])
                obj, typed, tmp = vm.alloc(DEMANDS_SIZE + 0x40), vm.alloc(16), vm.alloc(16)
                for a, n in ((obj, DEMANDS_SIZE + 0x40), (typed, 16), (tmp, 16)):
                    vm.uc.mem_write(a, b'\0' * n)
                vm.commit()
                vm.call(base + DEMANDS_CTOR, [obj])
                vm.commit()
                draws = vm.rng_uses
                ok, _ = vm.call(base + DEMANDS_COMPUTE, [obj, context, player, club, 0, 4])
                vm.commit()
                draws = vm.rng_uses - draws
                if not ok & 0xFF:
                    out[k] = {'unavailable': 'the game computes no demands for this player and club '
                                             '(0xD6B0E0 returned false)'}
                    continue
                raw = vm.read(obj, DEMANDS_SIZE)
                entry = base + DEMANDS_VALUE

                def sret(uc, addr, size, _):
                    uc.reg_write(A.UC_ARM64_REG_X8, typed)
                hook = vm.uc.hook_add(unicorn.UC_HOOK_CODE, sret, begin=entry, end=entry + 4)
                try:
                    vm.call(entry, [obj, 0, tmp])
                finally:
                    vm.uc.hook_del(hook)
                vm.commit()
                data.data['PPaD'] = typed
                reading = data.get('1NxK')
                if isinstance(reading.value, Unavailable):
                    out[k] = {'unavailable': f'PlayerAgentDemands: {reading.value.reason}'}
                    continue
                value = P._value(reading)
            except Exception as exc:  # noqa: BLE001  the emulator's stop reasons are not ValueErrors
                out[k] = {'unavailable': f'{type(exc).__name__}: {exc}'[:300]}
                continue
            fields = {n: struct.unpack_from('<i', raw, off)[0] for n, off in DEMANDS_FIELDS.items()}
            dates = {n: W.packed_date(struct.unpack_from('<I', raw, off)[0]) for n, off in DEMANDS_DATES.items()}
            agent = (value.get('Agen') or {}).get('dref') if isinstance(value.get('Agen'), dict) else None
            out[k] = {'fields': fields, 'dates': dates, 'interest': value.get('p0in'),
                      'renewal': value.get('meqL'), 'lines': value.get('j AI') or [], 'random_draws': draws,
                      'agent_idx': agent & 0xFFFFFF if isinstance(agent, int) and agent >> 24 == 1 else None,
                      'seconds': round(time.perf_counter() - started, 2)}
    finally:
        reader.close()
    return out


def agent_demand_rows(engine, people, read_date):
    """Rows of `agent_demand` for these people and the first managed club."""
    clubs = managed_clubs(engine)
    if not clubs:
        return [], ['no managed club']
    club = clubs[0]
    got = compute_agent_demands(engine, people, club)
    rows, notes = [], []
    for k, d in got.items():
        if 'unavailable' in d:
            notes.append(f"{k}: {d['unavailable']}")
            continue
        f, dt = d['fields'], d['dates']

        def amount(v):
            return None if v is None or v < 0 else v
        head = (k, club, DEMANDS_CONTEXT, d['interest'], 1 if d['renewal'] else 0, d['agent_idx'],
                f['player_club_idx'] if f['player_club_idx'] >= 0 else None, amount(f['fee_min']),
                amount(f['fee_max']), amount(f['wage_min']), amount(f['wage_max']), dt['contract_end'],
                d['random_draws'])
        lines = [x for x in d['lines'] if isinstance(x, dict)] or [{}]
        for i, line in enumerate(lines):
            rows.append((*head, i if line else None, line.get('fPst'), line.get('3mae'), line.get('gLl5'),
                         line.get('H5oC'), read_date))
    return rows, notes


def _agent_demand_table(engine):
    from . import StatementTooWide, current_statement
    from .histories import NARROW_PERSON, PEOPLE_SQL, statement_keys
    columns = [
        Column('person_idx', 'INTEGER', 'the player (person.idx)', references='person'),
        Column('club_idx', 'INTEGER', 'the club the demands are for: the managed club', references='club'),
        Column('context', 'INTEGER', 'context code passed to the computation 0xD6B0E0 (2: the scouting context '
                                     'of 0x396E170, the one a scout report or an agent offering the player uses)'),
        Column('interest', 'TEXT', "the player's interest in the club as the panel words it (key p0in, label "
                                   'AgentPlayerDemandsInterestLevelString)'),
        Column('is_renewal', 'INTEGER', '1 when the player is already at the club: the demands are for a new '
                                        'contract (key meqL, label AgentPlayerDemandsIsContractRenewal)'),
        Column('agent_idx', 'INTEGER', "the player's agent (key Agen; demands object +0x1B8)", references='person'),
        Column('player_club_idx', 'INTEGER', "the player's current club (demands object +0x1C0)",
               references='club'),
        Column('fee_min', 'INTEGER', 'lower end of the fee the selling club is expected to want, pounds (object '
                                     '+0x1C4, read by the line writer 0xD6D1B0 at 0xD6DFD8; NULL for own players)'),
        Column('fee_max', 'INTEGER', 'upper end of that fee, pounds (+0x1C8)'),
        Column('wage_min', 'INTEGER', 'lower end of the wage the player would want, pounds a week (+0x1D0, read at '
                                      '0xD6E09C; the line shows it per annum, x 52)'),
        Column('wage_max', 'INTEGER', 'upper end of that wage, pounds a week (+0x1D4)'),
        Column('contract_end', 'TEXT', 'the contract end date the player would want (+0x1F8; the line "Would want a '
                                       'contract until ...")'),
        Column('random_draws', 'INTEGER', 'random numbers the computation drew (the same lines came out under the '
                                          'copied, private and isolated random states on 12 Nov 2026)'),
        Column('entry', 'INTEGER', 'position of the line in the panel'),
        Column('line_type', 'INTEGER', 'type code of the line (fPst, AgentPlayerDemandsStringDataStringType: 1 squad '
                                       'status, 5 wage and length, 13 position and role on observed players)'),
        Column('line', 'TEXT', 'the demand as the panel words it (3mae, AgentPlayerDemandsStringDataString)'),
        Column('lock_type', 'INTEGER', 'gLl5, AgentPlayerDemandsStringDataLockType'),
        Column('colour_mode', 'INTEGER', 'H5oC, AgentPlayerDemandsStringDataColourMode'),
        Column('read_date', 'TEXT', 'game date on which the row was computed (recomputed when it changes)')]
    value_columns = [c.name for c in columns if c.name != 'person_idx']
    last = {}

    def compute(existing=frozenset()):
        date = engine.game_date()
        need = statement_keys(current_statement(), 'agent_demand', 'person_idx', value_columns, PEOPLE_SQL,
                              engine=engine)
        last.clear()
        if not need:
            return []
        if len(need) > DEMANDS_MAX_KEYS:
            raise StatementTooWide(f'the statement would compute agent demands for more than {DEMANDS_MAX_KEYS} '
                                   f'players (about 0.5 s each); {NARROW_PERSON}')
        stored = {row[0] for row in existing if row[-1] == date}
        todo = sorted(k for k in need if k not in stored)
        if not todo:
            return []
        import time
        started = time.time()
        rows, notes = agent_demand_rows(engine, todo, date)
        last.update(read=len(todo), rows=len(rows), seconds=round(time.time() - started, 2), notes=notes[:5])
        return rows

    def coverage():
        if not last.get('read'):
            return ''
        text = f"computed for {last['read']} player(s): {last['rows']} rows, {last['seconds']} s"
        return text + ('; unavailable: ' + '; '.join(last['notes']) if last.get('notes') else '')

    return SourceTable(
        'agent_demand',
        "what a player's agent says the player would want from the managed club before an offer is made (the "
        'agent demands panel, PERSON key PlayerAgentDemands): interest, the fee his club would want, wage range, '
        'contract length, squad status and the other lines as the game words them; one row per line. Computed by '
        'the game\'s own code for the players a statement names (WHERE person_idx = ...)',
        columns, lambda: compute(), key='idx', mode='lazy', invalidation='append',
        identity=('person_idx', 'entry', 'read_date'), replace_key=('person_idx',), layout='agent-demand-1',
        check_interval=0.0, new_rows=lambda existing: compute(existing), indexes=('person_idx',),
        source_note='0xD6B0E0 run in the UI VM on copied live memory, rendered by PERSON_UI_HANDLER key 1NxK with '
                    'data key PPaD set to the computed object (docs/fmdb/MANAGERS_MARKET.md)',
        cost_note=f'about 0.5 s a player, for the players a statement names (at most {DEMANDS_MAX_KEYS})',
        coverage=coverage,
        manager={'scope': 'public', 'reason': 'the game shows any player\'s agent demands to the human manager '
                                              '(scout reports, agent contact)'})


def _affiliation_view():
    item = "json_extract(j.value, '$.{}')"
    case = ' '.join(f"WHEN {k} THEN '{v}'" for k, v in AFFILIATION_TYPES.items())
    terms = ', '.join(f"{item.format(code)} AS {col}" for col, code, _ in AFFILIATION_TERMS)
    return (
        "SELECT o.idx AS club_idx, tg.idx AS affiliated_club_idx, "
        f"CAST({item.format('affl.unique_id')} AS INTEGER) AS affiliated_uid, "
        f"{item.format('ismc')} AS is_main_club, "
        f"CASE WHEN {item.format('ismc')} THEN 'parent' ELSE 'affiliate' END AS side, "
        f"{item.format('type')} AS type_code, CASE {item.format('type')} {case} END AS type, "
        f"NULLIF({item.format('stdt')}, '1900-01-01') AS start_date, "
        f"NULLIF({item.format('endt')}, '1900-01-01') AS end_date, {terms}, "
        "(SELECT g.group_idx FROM feeder_club_group g, feeder_club_group h WHERE g.club_idx = o.idx "
        "AND h.group_idx = g.group_idx AND h.club_idx = tg.idx LIMIT 1) AS feeder_group_idx "
        "FROM club o, json_each(o.{club.Cafl}) j LEFT JOIN club tg ON tg.uid = "
        f"{item.format('affl.unique_id')} WHERE json_valid(o.{{club.Cafl}})")


def views(engine):
    return {
        'club_affiliation': (
            'every current affiliation of every club with its terms labelled by the editor catalog '
            '(club.current_affiliations, list Cafl): the other club, which side is the main club (Is Main Club: '
            'the link is stored on both clubs, ismc true on the parent\'s copy; Regional Academy links on one '
            'side only), Affiliation Type (enum CAfT), start/end date, yearly fee, friendly chance and every '
            'term flag; feeder_group_idx is the FEEDER_CLUB_MANAGER group holding both clubs (groups are '
            'clubs under the Same Board: see MANAGERS_MARKET.md)',
            _affiliation_view(),
            {'scope': 'public', 'reason': 'affiliations and their terms are shown on club profiles'}),
    }
