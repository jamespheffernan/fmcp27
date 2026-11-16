"""Per-player fixture evidence consumer; never a clearance or an exclusion.

It combines already-read, independent native facts for one explicit player and
one stored fixture: registered-to-play(mode1), requirement14, requirement26 and
the ordinary mode0 suspension predicate. Each axis keeps its own state. A
suspension result says nothing about registration, native-false registration
can coexist with an age exemption, and unknown stays unknown. The original
outer availability and rule consumers read further inputs that are not
collected here, so the overall verdict is always not_evaluated.
"""

SCOPE = ('Independent evidence axes for one explicit player and one stored fixture. '
         'Registration coverage comes only from the registered-to-play(mode1), requirement14 '
         'and requirement26 predicates. The suspension predicate is a separate fact and never '
         'registers or clears a player. A native-false registration predicate can coexist with '
         'an exemption. No submitted squad list, current selection, medical, international-duty, '
         'loan or complete native availability/rule consumer is evaluated, so no player is '
         'cleared or excluded.')

NOT_EVALUATED = ('submitted_squad_list', 'current_selection', 'medical_clearance',
                 'international_duty', 'loan_restrictions', 'native_outer_availability_consumer',
                 'native_rule_consumer_player_virtual300_and_rule_byte130')


def _flag(value, name):
    if value is not None and type(value) is not bool:
        raise ValueError(f'Fixture evidence {name} native predicate type changed')
    return value


def _word(value):
    return 'unknown' if value is None else 'true' if value else 'false'


def combine(registration, requirement14, requirement26, covered, suspension):
    """Combine one row's independent components without inferring a verdict."""
    reg = _flag(registration['native_predicate_result'], 'registration')
    r14 = _flag(requirement14['native_requirement14'], 'requirement14')
    r26 = _flag(requirement26['native_result'], 'requirement26')
    suspended = _flag(suspension['native_suspended'], 'suspension')
    skipped26 = str(requirement26.get('state', '')).startswith('not_evaluated')
    clauses = dict(registered_mode1=_word(reg), requirement14=_word(r14),
                   requirement26='not_evaluated' if skipped26 and r26 is None else _word(r26))
    values = (reg, r14, r26)
    if covered is not (True if any(value is True for value in values) else None):
        raise ValueError('Fixture evidence registration coverage changed')
    if covered:
        coverage = 'covered_by_current_sources'
    elif reg is False and r14 is False and r26 is False:
        coverage = 'not_covered_by_checked_clauses'
    else:
        coverage = 'unknown'
    if suspended is True:
        reading = 'adverse_native_suspension_fact'
    elif coverage == 'unknown':
        reading = 'registration_unresolved'
    elif coverage == 'not_covered_by_checked_clauses':
        reading = 'registration_not_covered_by_checked_clauses'
    elif suspended is False:
        reading = 'registration_covered_and_no_native_suspension_found'
    else:
        reading = 'registration_covered_suspension_unknown'
    return dict(
        registration=dict(
            coverage=coverage, clauses=clauses,
            satisfied_by=[name for name, state in clauses.items() if state == 'true'],
            native_false_registration_with_exemption=reg is False and (r14 is True or r26 is True),
            basis='registered_mode1_or_requirement14_or_requirement26_only'),
        suspension=dict(
            state=suspension['state'], native_suspended=suspended, reason=suspension['reason'],
            establishes_registration=False),
        reading=reading, fixture_eligibility='not_evaluated',
        clearance_established=False, exclusion_established=False,
        not_evaluated=list(NOT_EVALUATED))
