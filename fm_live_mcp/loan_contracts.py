"""Stored current loan agreements; no match eligibility or payment execution."""
import struct

from . import competitions, players, wages, world

GETTERS = {3: 0x1374874, 9: 0xD8C3C0, 18: 0x13781B8,
           19: 0x13781C0, 29: 0x1005C68, 30: 0x1005C70}
CASH_FIELDS = {
    'playing_weekly_wage_gbp': (0x20, 'Cclc'),
    'unused_weekly_wage_gbp': (0xD4, 'ClDw'),
    'playing_monthly_fee_gbp': (0xCC, 'Clmf'),
    'unused_monthly_fee_gbp': (0xD0, 'ClDf'),
    'future_buy_back_fee_gbp': (0xC8, 'Clbb'),
}
MAX_FEE_COMPONENTS = 128
# Clfl's native display formatter (0x186B10) tests these bits independently.
# These are stored clauses, not an evaluation of today's recall/eligibility rules.
CLAUSE_BITS = {
    'can_play_against_parent_club': 0,
    'can_play_in_cup_matches': 1,
    'can_be_recalled': 2,
    'loan_cannot_be_terminated': 12,
    'can_play_for_parent_club_reserve_team': 13,
    'work_permit_loan': 14,
    'can_play_against_parent_club_b_team': 15,
    'can_play_for_parent_club': 16,
    'can_play_for_parent_club_in_cup_matches': 20,
    'trains_with_parent_club': 24,
    'season_long_affiliate_loan_exempt_from_parent_salary_cap': 26,
    'cannot_play_against_parent_club_in_cup_matches': 37,
    'cannot_play_in_continental_competitions': 38,
}
COMPETITION_ACHIEVEMENTS = {
    0: 'win_competition',
    3: 'promotion',
    6: 'avoid_relegation',
    10: 'qualify_for_competition',
    14: 'win_competition',
    20: 'avoid_fine',
}
SCOPE = ('Stored current loan agreement, signed/end dates, wage and monthly-fee terms, '
         'future fee, competition achievements, native match counters and thirteen displayed loan clauses. '
         'Clause flags do not establish permission to recall or play today. '
         'Stage-name composition remains undecoded. No current-date validity, match eligibility, recall windows, payment schedule, '
         'actual payments, future loans or UI visibility. '
         'The auxiliary loan slot can differ from the current club; this does not prove the loan is active today.')


def _cash(value):
    if value < -1:
        raise ValueError('Unsupported negative loan cash value')
    return {'amount': None if value == -1 else value,
            'state': 'not_specified' if value == -1 else 'stored'}


def _clauses(read, loan):
    # A nonzero override replaces the entire base word; it is not an OR mask.
    flags = players.u64(read(loan + 0xB8, 8))
    source = 'override' if flags else 'base'
    if not flags:
        flags = players.u64(read(loan + 0xB0, 8))
    known = sum(1 << bit for bit in CLAUSE_BITS.values())
    return {'clauses': {name: bool(flags & (1 << bit)) for name, bit in CLAUSE_BITS.items()},
            'clause_flags': {'source': source, 'native_flags_hex': f'0x{flags:016x}',
                             'unmapped_flags_hex': f'0x{flags & ~known:016x}'}}


def _competition_condition(read, base, loan, index):
    if index < 0:
        return None
    competition = competitions.by_index(read, base, index)
    target, stage_one, stage_two, kind = struct.unpack('<iiiB', read(loan+0x90, 13))
    target_competition = competitions.by_index(read, base, target) if target >= 0 else None
    achievement = COMPETITION_ACHIEVEMENTS.get(kind)
    if achievement is None:
        state = 'achievement_not_decoded'
    elif stage_one != -1 or stage_two != -1:
        state = 'stage_names_not_decoded'
    elif kind == 10 and target_competition is None:
        state = 'qualification_target_unavailable'
    else:
        state = 'decoded'
    return {'state': state, 'competition': competition, 'achievement': achievement,
            'native_achievement_code': kind, 'target_competition': target_competition,
            'native_stage_name_ids': [stage_one, stage_two], 'trigger_satisfied': None}


def _clubs(read, base, address, person, loan):
    def team_club(team):
        world.typed(read, base, team, 'team')
        club = world.pointer(read, team + 0x30)
        record, identity = world.club(read, base, club)
        if team not in world.vector(read, club + 0x18, 64):
            raise ValueError('Loan-linked team is absent from club teams')
        return record, (club, identity)

    def contract_club(contract, allow_no_team=False):
        if world.pointer(read, contract + 8) != person:
            raise ValueError('Loan-linked contract owner disagrees')
        first, second = struct.unpack('<QQ', read(contract + 0x10, 16))
        if first == second == 0 and allow_no_team:
            return None, None
        one, identity = team_club(first)
        if team_club(second)[1] != identity:
            raise ValueError('Loan-linked contract team clubs disagree')
        return one, identity

    borrower, borrower_identity = contract_club(loan)
    main = players.u64(read(person - 0x98, 8))
    parent, parent_state = None, 'no_main_contract'
    if main:
        table = world.pointer(read, main)
        kind = next((kind for kind in ('full_contract', 'basic_contract')
                     if table == base + world.TYPES[kind][0]), None)
        if kind is None:
            raise ValueError('Unsupported loan parent contract type')
        world.typed(read, base, main, kind)
        parent, _ = contract_club(main, allow_no_team=True)
        parent_state = 'decoded' if parent else 'no_main_contract_team'
    current_team = players.u64(read(address + 0x128, 8))
    current, current_identity = team_club(current_team) if current_team else (None, None)
    return {'parent_club': parent, 'parent_club_state': parent_state,
            'borrowing_club': borrower, 'current_club': current,
            'current_club_relationship': ('no_current_team' if current is None else
                'same_as_borrowing_club' if current_identity == borrower_identity else
                'differs_from_borrowing_club')}


def decode(read, base, address, person_offset, currency=None):
    person = address + person_offset
    holder = players.u64(read(person - 0x90, 8))
    result = {'state': 'no_current_loan', 'currency': None, 'scope': SCOPE,
              'eligibility_evaluated': False}
    if not holder:
        return result
    if holder < 4096 or holder % 8:
        raise ValueError('Invalid auxiliary contract holder')
    loan = players.u64(read(holder, 8))
    if not loan:
        return result
    world.typed(read, base, loan, 'loan_contract')
    table = world.pointer(read, loan)
    for slot, getter in GETTERS.items():
        if players.u64(read(table + slot * 8, 8)) != base + getter:
            raise ValueError('Loan contract getter changed')
    clubs = _clubs(read, base, address, person, loan)
    signed = world.packed_date(read(loan + 0x44, 4))
    ends = world.packed_date(read(loan + 0x48, 4))
    fields = {name: _cash(struct.unpack('<i', read(loan + offset, 4))[0])
              for name, (offset, _) in CASH_FIELDS.items()}
    initial = struct.unpack('<i', read(loan + 0xC0, 4))[0]
    fee = _cash(initial)
    components = []
    # The getter short-circuits when the initial fee is negative. Do likewise.
    if initial >= 0:
        vector = players.u64(read(loan + 0x68, 8))
        if vector:
            if vector < 4096 or vector % 8:
                raise ValueError('Invalid loan fee vector pointer')
            start, end, capacity = struct.unpack('<QQQ', read(vector, 24))
            if start == end == capacity == 0:
                raw = b''
            else:
                if (start < 4096 or any(p % 8 for p in (start, end, capacity))
                        or not start <= end <= capacity):
                    raise ValueError('Invalid loan fee vector')
                if capacity - start > MAX_FEE_COMPONENTS * 8:
                    raise ValueError('Loan fee vector exceeds bound')
                raw = read(start, end - start) if start != end else b''
            for offset in range(0, len(raw), 8):
                amount, parameter = struct.unpack_from('<ib', raw, offset)
                included = amount > 0 and parameter > 0
                components.append({'native_amount': amount, 'native_parameter': parameter,
                                   'included_in_native_total': included})
            total = initial + sum(row['native_amount'] for row in components if row['included_in_native_total'])
            if total > 0x7FFFFFFF:
                fee = {'amount': None, 'state': 'unavailable_native_integer_overflow'}
            else:
                fee = _cash(total)
    threshold = struct.unpack('<b', read(loan + 0xF7, 1))[0]
    played = struct.unpack('<b', read(loan + 0xF8, 1))[0]
    competition_index = struct.unpack('<i', read(loan + 0xC4, 4))[0]
    if initial < 0:
        trigger = 'no_future_fee_specified'
    elif threshold == 100:
        trigger = 'mandatory_future_fee'
    elif threshold >= 0:
        trigger = 'after_matches'
    elif threshold < 0 and competition_index >= 0:
        trigger = 'competition_condition'
    elif threshold < 0:
        trigger = 'optional_future_fee'
    return {**result, 'state': 'decoded', 'currency': currency or wages.base_currency(read, base),
            **clubs, **_clauses(read, loan),
            'signed_date': signed, 'end_date': ends, **fields,
            'purchase': {'future_fee_gbp': fee, 'initial_future_fee_gbp': _cash(initial),
                         'additional_fee_components': components,
                         'fee_components_state': 'complete_native_vector' if initial >= 0 else 'not_evaluated_without_initial_fee',
                         'trigger': trigger,
                         'match_threshold': threshold if trigger == 'after_matches' else None,
                         'matches_played': played if played >= 0 else None,
                         'native_match_threshold': threshold, 'native_matches_played': played,
                         'competition_condition_present': competition_index >= 0,
                         'competition_condition': _competition_condition(read, base, loan, competition_index),
                         'trigger_satisfied': None},
            'evidence': 'native_loan_contract_getters_and_contract_display_paths'}
