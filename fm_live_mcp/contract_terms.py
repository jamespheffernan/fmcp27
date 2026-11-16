"""Stored main-contract entries, including repeated clauses and unmapped kinds."""
from datetime import date, timedelta

from . import contract_bonuses, players, wages, world

# kind: public name. These are native entry kinds, not UI availability rules.
KINDS = {
    0: 'minimum_fee_release', 1: 'relegation_release', 2: 'non_promotion_release',
    3: 'yearly_wage_rise', 4: 'promotion_wage_rise', 5: 'relegation_wage_drop',
    6: 'non_playing_job_offer_release', 8: 'sell_on_fee', 9: 'sell_on_profit',
    10: 'seasonal_goal_bonus', 11: 'final_season_league_games_extension',
    12: 'match_highest_earner', 13: 'wage_after_club_league_games',
    14: 'top_division_promotion_wage_rise', 15: 'top_division_relegation_wage_drop',
    16: 'foreign_club_release', 17: 'higher_domestic_division_release',
    18: 'domestic_club_release', 19: 'wage_after_international_appearances',
    22: 'club_extension_option', 23: 'waive_managerial_compensation',
    24: 'managerial_compensation_percentage',
    25: 'promoted_final_season_league_games_extension',
    26: 'avoid_relegation_final_season_league_games_extension',
    27: 'major_continental_competition_release', 29: 'extension_after_promotion',
    30: 'injury_release', 31: 'continental_competition_release',
    32: 'appearance_fee', 33: 'goal_bonus', 34: 'clean_sheet_bonus',
    37: 'international_cap_bonus', 38: 'unused_substitute_fee', 39: 'assist_bonus',
    40: 'seasonal_assist_bonus', 41: 'seasonal_goal_and_assist_bonus',
    20: 'sponsor_wage_percentage', 21: 'player_gate_receipts_percentage',
    28: 'mls_guaranteed_contract', 55: 'active_relegation_release',
    56: 'active_non_promotion_release', 57: 'committee_decided_release_fee',
    54: 'leave_at_contract_end', 63: 'explore_options_at_contract_end',
}
# kind, output field, getter slot, contract property, person/editor property, label
FIELDS = (
    (0, 'amount_gbp', 52, 'Cmfc', 'Pmfr', 'Minimum Fee Release Clause'),
    (0, 'expiry', 56, 'Cmfe', 'Pmfe', 'Minimum Fee Release Clause - Expiry Date'),
    (1, 'amount_gbp', 52, 'Crrf', 'Prrf', 'Relegation Release Clause'),
    (2, 'amount_gbp', 52, 'Cnpr', 'Pnpr', 'Non Promotion Release Clause'),
    (3, 'percentage', 54, 'Cywi', 'Pywi', 'Yearly Wage Rise'),
    (4, 'percentage', 54, 'Cpwi', 'Pcpi', 'Promotion Wage Rise'),
    (5, 'percentage', 54, 'Crwd', 'Pcrd', 'Relegation Wage Drop'),
    (6, 'present', 46, 'CMCR', 'Pmcr', 'Non-Playing Job Offer Release Clause'),
    (8, 'percentage', 54, 'CSOF', 'Psof', 'Sell On Fee Percentage'),
    (9, 'percentage', 54, 'CSPP', 'Psfp', 'Sell On Fee Profit Percentage'),
    (9, 'original_transfer_fee_gbp', 52, 'CSPC', 'Psfc', 'Sell On Fee Profit Percentage - Original Transfer Fee'),
    (10, 'amount_gbp', 52, 'CGBF', 'Pfag', 'Seasonal Landmark Goal Bonus'),
    (10, 'goals', 54, 'CGBG', 'Pfgg', 'Seasonal Landmark Goal Bonus - Number Of Goals'),
    (11, 'league_games', 54, 'C1YE', 'Pcxl', 'One-Year Extension After League Games (Final Season)'),
    (12, 'present', 46, 'CMHE', 'Pmhe', 'Match Highest Earner Clause'),
    (13, 'weekly_wage_gbp', 52, 'CPIW', 'Pwwg', 'Wage After Reaching Club League Games'),
    (13, 'league_games', 54, 'CPIG', 'Pwwl', 'Wage After Reaching Club League Games - Number Of Games'),
    (14, 'percentage', 54, 'CTDI', 'Ptpi', 'Top Division Promotion Wage Rise'),
    (15, 'percentage', 54, 'CTDD', 'Ptrd', 'Top Division Relegation Wage Drop'),
    (16, 'amount_gbp', 52, 'CMFF', 'Pfcf', 'Minimum Fee Release Clause (Foreign Clubs)'),
    (16, 'expiry', 56, 'CMFe', 'Pfce', 'Minimum Fee Release Clause (Foreign Clubs) - Expiry Date'),
    (17, 'amount_gbp', 52, 'CMFH', 'Phdr', 'Minimum Fee Release Clause (Domestic Clubs in Higher Division)'),
    (17, 'expiry', 56, 'CMHe', 'Phde', 'Minimum Fee Release Clause (Domestic Clubs in Higher Division) - Expiry Date'),
    (18, 'amount_gbp', 52, 'CMDc', 'Pdcf', 'Minimum Fee Release Clause (Domestic Clubs)'),
    (18, 'expiry', 56, 'CMDe', 'Pdex', 'Minimum Fee Release Clause (Domestic Clubs) - Expiry Date'),
    (19, 'weekly_wage_gbp', 52, 'CIIW', 'PinW', 'Wage After Reaching International Appearances'),
    (19, 'international_appearances', 54, 'CIIG', 'PinG', 'Wage After Reaching International Appearances - Number Of Appearances'),
    (22, 'years', 54, 'CACE', 'Paco', 'Optional Contract Extension By Club'),
    (23, 'present', 46, 'CWCM', 'Pwcm', 'Waive Club Compensation For Managerial Role'),
    (24, 'percentage', 54, 'CPCL', 'Ppcl', 'Percentage Of Club Compensation Required For Managerial Role'),
    (25, 'league_games', 54, 'C1YP', 'Pypr', 'One-Year Extension After League Games (Promoted Final Season)'),
    (26, 'league_games', 54, 'C1YR', 'Pyar', 'One-Year Extension After League Games (Avoid Relegation Final Season)'),
    (27, 'amount_gbp', 52, 'CMcc', 'Pccr', 'Minimum Fee Release Clause (Clubs in a Major Continental Competition)'),
    (27, 'expiry', 56, 'CMce', 'Pcce', 'Minimum Fee Release Clause (Clubs in a Major Continental Competition) - Expiry Date'),
    (29, 'years', 54, 'CACP', 'Pacp', 'Contract Extension After Promotion'),
    (30, 'present', 46, 'CIRC', 'Picr', 'Injury Release Clause'),
    (31, 'amount_gbp', 52, 'CMac', 'Pccc', 'Minimum Fee Release Clause (Clubs in a Continental Competition)'),
    (31, 'expiry', 56, 'CMae', 'Pcae', 'Minimum Fee Release Clause (Clubs in a Continental Competition) - Expiry Date'),
    *((kind, 'amount_gbp', 52, prop, editor, label) for kind, prop, editor, label in contract_bonuses.BONUSES.values()),
    (40, 'amount_gbp', 52, 'CABF', 'PABF', 'Seasonal Landmark Assist Bonus'),
    (40, 'assists', 54, 'CABA', 'PABA', 'Seasonal Landmark Assist Bonus - Number Of Assists'),
    (41, 'amount_gbp', 52, 'CXBF', 'PXBF', 'Seasonal Landmark Combined Goal and Assist Bonus'),
    (41, 'goals_and_assists', 54, 'CXBG', 'PXBG', 'Seasonal Landmark Combined Goal and Assist Bonus - Number Of Combined Goals and Assists'),
    (20, 'percentage', 54, 'CPWS', None, 'Percentage of Wages paid by Sponsor'),
    (21, 'percentage', 54, 'CPGP', None, 'Percentage of Gate Receipts paid to Player'),
    (28, 'present', 46, 'CGCC', None, 'MLS Guaranteed Contract Clause'),
    (55, 'amount_gbp', 52, 'CRRA', None, 'Active Relegation Release Clause'),
    (56, 'amount_gbp', 52, 'CNPA', None, 'Active Non Promotion Release Clause'),
    (57, 'amount_gbp', 52, 'Cdtf', None, 'Minimum Fee Release Clause (Committee Decided Transfer Fee)'),
    (54, 'present', 46, 'Clec', 'Plec', 'Will Leave At End Of Contract'),
    (63, 'present', 46, 'Crdc', 'Prdc', 'Will Explore Options At End Of Contract'),
)
NATIVE_LABELS = {20: 338041, 21: 338040, 28: 392739, 55: 383225, 56: 383224, 57: 420869}
GETTERS = {46: 0x1288E8C, 54: 0x12893A0, 56: 0x12897AC}
PARAMETER_MASK = 0x3002778EF38


def expiry(read, base, contract, parameter):
    result = {'date': None, 'state': 'native_default', 'reason': None}
    if parameter < 0:
        return {**result, 'reason': 'negative_expiry_parameter'}
    if read(base + 0x56D4950, 1)[0] in (1, 2, 3):
        return {**result, 'reason': 'native_date_mode'}
    signed = date.fromisoformat(world.packed_date(read(contract + 0x44, 4)))
    # The native date-add helper narrows its initial day count to signed int16.
    if signed.timetuple().tm_yday - 1 + parameter > 32767:
        return {**result, 'state': 'unavailable', 'reason': 'native_day_arithmetic_overflow'}
    value = signed + timedelta(days=parameter)
    if value.year > 2200:
        return {**result, 'state': 'unavailable', 'reason': 'date_outside_verified_range'}
    return {'date': value.isoformat(), 'state': 'computed_from_contract_signed_date',
            'reason': None, 'signed_date': signed.isoformat(), 'days_after_signed': parameter}


def decode(read, base, person, currency=None):
    state, contract, entries = contract_bonuses.read_entries(read, base, person)
    result = {'state': state, 'currency': None, 'terms': None, 'unmapped_entries': None,
              'native_entry_count': None, 'complete_native_vector': False,
              'activation_evaluated': False,
              'scope': 'Stored main-contract vector only. All entries retained; unknown kinds and native flags '
                       'remain uninterpreted. Trigger eligibility, remaining progress, UI visibility, '
                       'payment totals, future contracts and loan terms are not evaluated.'}
    if state != 'full_contract':
        result['state'] = 'no_contract' if state == 'no_contract' else 'basic_contract_terms_unavailable'
        return result
    # Verify the dispatch used to establish parameter, presence and expiry semantics.
    table = base + world.TYPES['full_contract'][0]
    for slot, getter in GETTERS.items():
        if players.u64(read(table + slot * 8, 8)) != base + getter:
            raise ValueError('Contract term getter changed')
    currency = currency or wages.base_currency(read, base)
    selected = {}
    for index, (_, parameter, kind, _) in enumerate(entries):
        previous = selected.get(kind)
        if previous is None or (kind <= 41 and PARAMETER_MASK & (1 << kind)
                                and parameter < entries[previous][1]):
            selected[kind] = index
    terms, unmapped = [], []
    for index, (amount, parameter, kind, flags) in enumerate(entries):
        common = {'entry_index': index, 'native_kind': kind, 'native_flags': flags,
                  'selected_by_native_property': selected[kind] == index}
        if kind not in KINDS:
            unmapped.append({**common, 'native_value': amount, 'native_parameter': parameter,
                             'state': 'unmapped_entry_kind'})
            continue
        values, unavailable = {}, []
        for field_kind, name, slot, _, _, _ in FIELDS:
            if field_kind != kind:
                continue
            if slot == 52:
                if amount < 0: raise ValueError('Unsupported negative contract term cash')
                values[name] = amount
            elif slot == 54:
                if parameter < 0:
                    values[name] = None
                    unavailable.append({'field': name, 'reason': 'negative_native_parameter', 'native_value': parameter})
                else:
                    values[name] = parameter
            elif slot == 46:
                values[name] = True
            else:
                values[name] = expiry(read, base, contract, parameter)
        terms.append({**common, 'kind': KINDS[kind], 'values': values, 'unavailable_fields': unavailable})
    return {**result, 'state': 'decoded', 'currency': currency, 'terms': terms,
            'unmapped_entries': unmapped, 'native_entry_count': len(entries),
            'complete_native_vector': True, 'mapped_entry_count': len(terms),
            'unmapped_entry_count': len(unmapped), 'supported_kinds': sorted(KINDS.values()),
            'evidence': 'native_contract_entry_properties_and_editor_labels'}
