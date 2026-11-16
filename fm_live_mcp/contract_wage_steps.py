"""Appearance-linked main-wage scenarios from the current owned contract.

These are differences between stored cash rates, not a forecast, activated clause,
remaining appearance count, total payroll, or budget effect. The caller must bind
PERSON membership/current save and verify its consumed-read/lifetime scope.
"""
from . import contract_terms, players, wages

STEP_KINDS = {
    13: ('club_league_games', 'league_games'),
    19: ('international_appearances', 'international_appearances'),
}
SCOPE = (
    'Current main-contract kinds 13 and 19 only. Each target-minus-current rate is an '
    'independent arithmetic scenario in whole GBP per week. Repeated entries are retained '
    'in native order and are not additive. Getter selection does not establish activation. '
    'No appearances-to-date, remaining progress, trigger eligibility, applicable step, '
    'payment due, future contract, annual wage rise, bonus, loan contribution or budget '
    'effect is evaluated. A lower stored target does not establish a wage saving. '
    'Unmapped entries and other wage-related clauses are outside this scenario scope.'
)


def decode(read, base, person):
    """Read the wage and full term vector from one PERSON-owned current contract."""
    contract_before = players.u64(read(person - 0x98, 8))
    wage = wages.decode(read, base, person)
    terms = contract_terms.decode(read, base, person, wage['currency'])
    if players.u64(read(person - 0x98, 8)) != contract_before:
        raise ValueError('Wage-step current contract changed')
    result = {
        'state': terms['state'], 'current_weekly_main_wage': wage,
        'currency': wage['currency'], 'period': 'week', 'steps': None,
        'native_entry_count': terms['native_entry_count'],
        'unmapped_entry_count': terms.get('unmapped_entry_count'),
        'complete_current_term_vector': terms['complete_native_vector'],
        'appearance_step_count': None,
        'activation_evaluated': False, 'progress_evaluated': False,
        'largest_stored_target_increase_gbp': None,
        'scope': SCOPE,
    }
    if terms['state'] != 'decoded':
        return result
    if wage['state'] != 'decoded' or wage['currency'] != 'GBP' or terms['currency'] != 'GBP':
        raise ValueError('Wage-step sources do not share a decoded GBP weekly main wage')
    steps = []
    for entry in terms['terms']:
        fields = STEP_KINDS.get(entry['native_kind'])
        if fields is None:
            continue
        trigger, threshold_field = fields
        target = entry['values']['weekly_wage_gbp']
        threshold = entry['values'][threshold_field]
        delta = target - wage['amount']
        steps.append({
            'entry_index': entry['entry_index'], 'native_kind': entry['native_kind'],
            'native_flags': entry['native_flags'], 'kind': entry['kind'],
            'selected_by_native_property': entry['selected_by_native_property'],
            'trigger': trigger, 'stored_threshold': threshold,
            'threshold_state': 'stored' if threshold is not None else 'unavailable',
            'unavailable_fields': entry['unavailable_fields'],
            'stored_target_weekly_wage_gbp': target,
            'difference_from_current_weekly_main_wage_gbp': delta,
            'target_relative_to_current': 'higher' if delta > 0 else 'lower' if delta < 0 else 'equal',
            'trigger_satisfied': None, 'remaining_appearances': None,
            'applies_now': None,
        })
    return {**result, 'state': 'decoded_scenarios', 'steps': steps,
            'appearance_step_count': len(steps),
            # A per-person envelope over stored target differences, never a sum of steps.
            'largest_stored_target_increase_gbp': max(
                (max(0, row['difference_from_current_weekly_main_wage_gbp']) for row in steps), default=0),
            'evidence': 'owned_current_main_contract_wage_and_complete_native_term_vector'}
