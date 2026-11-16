"""Round-2 screens: groups the second UI sweep made readable (docs/fmdb/UI_ROUND2.md).

Each screen is a list of parts; a part names a handler type, the UI_RECORD it is built from and
the keys to read, by the registry's own labels (exact labels, or a regular expression over the
labels of the handler class). A key whose getter reads a screen parameter gets the value the
view would set (`ui_params` names; verified in the round-2 sweep on the reference save). Every
value comes from `ui_recipes_more.KeyReader` running shipped code on copied live memory; keys
that return nothing are reported as unset, failures as unavailable with the reason.

Screens: player_comparison (two people side by side: the front end shows two PERSON reads next
to each other, there is no plugin comparison), staff_comparison, tactics, squad_registration,
training, contract_negotiation, transfer_negotiation, competition_rules.
"""
from __future__ import annotations

import re
import struct
import time

from . import ui_params, ui_registry
from .ui_recipes_more import (DATABASE_RECORD, Refs, _answer, _vm_and_view, read_screen)
from .vm import _Stop

PERSON_TABLE = 1
CONTRACT, TRANSFER_OFFER_EDIT_SESSION = 19, 137
CONTRACT_EDIT_SESSION, SQUAD_REGISTRATION_EDIT_SESSION = 20, 105
COMPETITION_TACTIC, PLAYER_TRAINING, TEAM_TRAINING = 18, 77, 128
MAX_KEYS_PER_PART = 80

# Part = (part name, handler type, record kind, [label or ('re', pattern)], {label: {param: value}})
# record kinds: 'person' (dref = the person), 'other' (dref = the second person), 'team' (dref = the
# managed team), 'competition' (dref = the competition), 'context' (the manager's context fields
# only), 'person_fields' (Pers/pers/plyr/dref = the person, as the edit-session screens use).
PERSON_LABELS = (
    'AttributesComparisonTechnical', 'AttributesComparisonMental', 'AttributesComparisonPhysical',
    'AttributesComparisonSetPieces', 'AttributesComparisonGoalkeeping', 'PositionalStatsTable',
    'SelectedPositionalAbilities', 'BestRole', 'TotalCareerClubAppearances',
    'TotalCareerLeaguePlayerOfTheMatchAwards', 'ExpectedGoalsPer90', 'AssistsPer90', 'ChancesCreated',
    'Blocks', 'GoalsOutsideBox', 'FoulsAgainst', 'HeaderCompleted', 'InjuriesLastSeason',
    'InternationalGoalsThisSeason', 'SquadNumberBlankIfInvalid')
PERSON_PARAMS = {'PositionalStatsTable': {'boolean': 1}, 'SelectedPositionalAbilities': {'positionmask': 1}}

SCREENS = {
    'player_comparison': (
        ('person', DATABASE_RECORD, 'person', PERSON_LABELS, PERSON_PARAMS),
        ('other', DATABASE_RECORD, 'other', PERSON_LABELS, PERSON_PARAMS),
    ),
    'staff_comparison': (
        ('team', DATABASE_RECORD, 'team', (('re', r'^Staff\w*SubGroupComparison'), 'PlayersForComparison'), {}),
    ),
    # The tactic itself is not read here. A COMPETITION_TACTIC handler built from the team record
    # answers for a default tactic (on a live Newcastle save, 12 November 2026: "4-4-2", Balanced, one
    # slot) while the manager's three prepared tactics were 4-2-3-1 on Positive. fm_get_ui_screen adds
    # the manager's tactics from the hand-built readers instead (ui_tools.manager_tactics).
    'tactics': (
        ('team', DATABASE_RECORD, 'team', (
            'SelectedInPossessionFormationChances', 'SelectedOutOfPossessionFormationChances', 'TacticalStyleName',
            'HeatMapPlayerList'),
         {'SelectedInPossessionFormationChances': {'formation': 0},
          'SelectedOutOfPossessionFormationChances': {'formation': 0}, 'HeatMapPlayerList': {'id': 'person'}}),
    ),
    'squad_registration': (
        ('registration', SQUAD_REGISTRATION_EDIT_SESSION, 'person_fields', (
            'SquadSelectionName', 'Competition', 'DeadlineDate', 'NextStartDate', 'RegistrationDaysLeft',
            'WindowOpenState', 'RuleWarningStrings', 'ExtraSquadRules', 'RuleDropdownList', 'RegisteredPlayersCount',
            'UnregisteredPlayersCount', 'RegisteredPlayers', 'UnregisteredPlayers'), {}),
        ('team', DATABASE_RECORD, 'team', (
            'SquadRegistrationComps', 'SquadRegistrationRulesCompliance', 'NextMatchMaxSquadRuleStatus',
            'RegistrationDate'), {}),
    ),
    'training': (
        ('team', TEAM_TRAINING, 'context', (
            'GoalkeepingUnit', 'DefensiveUnit', 'MidfieldUnit', 'AttackingUnit', 'AverageTrainingRating',
            'TrainingPerformanceStatus', 'TrainingPerformanceMonthlyString', 'TrainingBestRatings',
            'TrainingWorstRatings', 'TrainingMentoring', 'CoachAssignments', 'IndividualTrainingOverview',
            'CurrentWeekTraining', 'LastWeekTrainingTemplateName'),
         {'TrainingBestRatings': {'number': 10}, 'TrainingWorstRatings': {'number': 10}}),
        ('player', PLAYER_TRAINING, 'person_fields', (
            'Workload', 'LoadDetail', 'TrainingPosition', 'TrainingRating', 'TrainingRatingAndColour',
            'ImprovementOverall', ('re', r'^Improvement'), 'ProgressReport', 'Traits', 'RecentChanges',
            'AdditionalFocus'), {}),
    ),
    'contract_negotiation': (
        ('negotiation', CONTRACT_EDIT_SESSION, 'person_fields', (
            ('re', r'^ContractNegotiation'), 'NegotiationDisplayMode', 'WageBudgetImpactPieChartData',
            'AdditionalFunds', 'FutureTransferWages', 'OverallOfferLockStatus'), {}),
        ('contract', CONTRACT, 'person_fields', (('re', r'^(Contract|Wage|Transfer|Loan|SellingOn)'),), {}),
    ),
    'transfer_negotiation': (
        ('offer', TRANSFER_OFFER_EDIT_SESSION, 'person_fields', (
            ('re', r'^(TransferOffer|ExchangePlayers|Proposal|TransferBudget|ResponseActions)'),), {}),
    ),
    'competition_rules': (
        ('competition', DATABASE_RECORD, 'competition', (
            ('re', r'(Rule|Registration|Squad|Format|Stage)'),), {}),
    ),
}


def labels_to_codes(reg, cls: str, items) -> dict:
    """{label: code} for exact labels and ('re', pattern) entries over the class's keys (exact
    labels may name keys no class claims: those are looked up in the whole registry)."""
    class_keys = list(reg.classes[cls].keys(4)) if cls in reg.classes else []
    out = {}
    for item in items:
        if isinstance(item, tuple) and item[0] == 're':
            rx = re.compile(item[1])
            for code in class_keys:
                label = reg.label(code) or ''
                if rx.search(label) and not label.startswith('Debug') and label not in out:
                    out[label] = code
            continue
        codes = [c for c in reg.codes(item) if c in class_keys] or list(reg.codes(item))
        if codes:
            out.setdefault(item, codes[0])
    return dict(list(out.items())[:MAX_KEYS_PER_PART])


def squad_people(vm, view, count=2) -> list:
    """UI ids of the first players of the managed team's roster."""
    from .. import players, world
    from .ui_recipes_person import person_id
    read = vm.reader.read
    roster = world.vector(read, view.team + 0x38, 512)
    out = []
    for p in roster:
        if struct.unpack('<Q', read(p, 8))[0] == vm.base + players.RVA[0]:
            out.append(person_id(vm, read, p))
            if len(out) >= count:
                break
    return out


def _record(kind, view, person, other, competition):
    if kind == 'person':
        return view.record(dref=person)
    if kind == 'other':
        return view.record(dref=other)
    if kind == 'team':
        return view.record(dref=view.team_id)
    if kind == 'competition':
        return view.record(dref=competition, comp=competition)
    if kind == 'person_fields':
        return view.record(Pers=person, pers=person, plyr=person, dref=person)
    return view.record()


def _param_values(spec: dict, person) -> dict:
    """{param name: value} -> {param RVA: int}; the value 'person' stands for the person read."""
    out = {}
    for name, value in spec.items():
        out[ui_params.rva_of(name)] = person if value == 'person' else int(value)
    return out


def screen(vm_or_session, name: str, *, person=None, other=None, competition=None, coach=0) -> dict:
    """Read one round-2 screen (SCREENS). person/other: PERSON UI ids (default: the first two
    players of the managed squad); competition: COMPETITION UI id (default: the managed team's
    league, as fm_get_league_table finds it)."""
    if name not in SCREENS:
        raise ValueError(f'unknown screen {name!r}; one of {", ".join(SCREENS)}')
    vm, view = _vm_and_view(vm_or_session, coach)
    reg = ui_registry.default()
    started, rng0 = time.perf_counter(), vm.rng_uses
    if person is None or (other is None and name == 'player_comparison'):
        squad = squad_people(vm, view, 2)
        person = person if person is not None else squad[0]
        other = other if other is not None else (squad[1] if len(squad) > 1 else squad[0])
    if competition is None and name == 'competition_rules':
        competition = managed_league(vm, view, reg)
    parts = {}
    for part, htype, kind, labels, params in SCREENS[name]:
        record = _record(kind, view, person, other, competition)
        cls = reg.types.get(htype, {}).get('client') if htype != DATABASE_RECORD else {
            'person': 'PERSON_UI_HANDLER', 'other': 'PERSON_UI_HANDLER', 'team': 'TEAM_UI_HANDLER',
            'competition': 'COMPETITION_UI_HANDLER'}.get(kind)
        keys = labels_to_codes(reg, cls, labels)
        subject = other if kind == 'other' else person
        pvals = {label: _param_values(params[label], subject) for label in keys if label in params}
        try:
            parts[part] = read_screen(vm, htype, record, keys, params=pvals, inputs=htype != DATABASE_RECORD
                                      or kind != 'team')
        except _Stop as stop:
            parts[part] = {'unavailable': f'{stop.reason} {stop.detail or ""}'.strip()}
    refs = Refs(vm)
    uses_person = any(kind in ('person', 'person_fields') or 'person' in str(params)
                      for _p, _h, kind, _l, params in SCREENS[name])
    out = {'screen': name, 'subject': {
        'person': refs.ref(person) if person and uses_person else None,
        'other': refs.ref(other) if other and name == 'player_comparison' else None,
        'competition': refs.ref(competition) if competition else None}, 'fields': {}}
    for part, value in parts.items():
        out['fields'][part] = refs(value.fields) if hasattr(value, 'fields') else value
    return _answer(parts, started, rng0, vm, **out)


def managed_league(vm, view, reg=None) -> int | None:
    """The managed team's league (the same lookup as fm_get_league_table)."""
    from .ui_recipes_more import managed_league as more_league
    return more_league(vm, view)


def player_comparison(vm_or_session, person=None, other=None, coach=0):
    return screen(vm_or_session, 'player_comparison', person=person, other=other, coach=coach)


__all__ = ['SCREENS', 'screen', 'player_comparison', 'labels_to_codes', 'managed_league']
