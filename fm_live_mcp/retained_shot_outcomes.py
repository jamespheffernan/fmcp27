"""Official CBE end-shot categories, distinct from shot situation/body part.

Hit Woodwork describes the native terminal category, not every intermediate
contact. OwnGoal49 is deliberately not a statistical-shot outcome.
"""
from collections import Counter

OUTCOMES = {
    1: ('goal', 'CBE_END_SHOT_GONE_IN'),
    2: ('missed_target', 'CBE_END_SHOT_MISSED_TARGET'),
    3: ('hit_woodwork', 'CBE_END_SHOT_HIT_WOODWORK'),
    4: ('saved', 'CBE_END_SHOT_SAVED'),
    5: ('blocked', 'CBE_END_SHOT_BLOCKED'),
}


def outcome_fields(native_category_code):
    if type(native_category_code) is not int or not 0 <= native_category_code <= 255:
        raise ValueError('Native end-shot category must be an unsigned byte')
    known = OUTCOMES.get(native_category_code)
    return {'outcome': known[0] if known else None,
            'native_outcome_label': known[1] if known else None,
            'outcome_state': ('official_native_end_shot_category' if known else
                              'separate_own_goal_marker' if native_category_code == 49 else
                              'unmapped_native_end_shot_category')}


def outcome_counts(shots):
    counts = Counter(row.get('outcome') for row in shots)
    return {**{value[0]: counts[value[0]] for value in OUTCOMES.values()},
            'unknown': counts[None]}


def outcome_policy():
    return {'source': 'linked CBE event56+0x2A, official registry489B1B0..489B264',
            'mapping': {str(code): {'outcome': value[0], 'native_label': value[1]}
                        for code, value in OUTCOMES.items()},
            'scope': 'Exclusive native end-shot category; no full contact/action sequence',
            'hit_woodwork': 'Native terminal Hit Woodwork only; not every intermediate woodwork contact',
            'own_goal_markers_are_statistical_shots': False,
            'penalty_dimension': 'Independent shot type; a penalty can have different end outcomes',
            'unmapped_categories': 'Null outcome with raw category code preserved',
            'counts_scope': 'All available statistical attempts before paging'}
