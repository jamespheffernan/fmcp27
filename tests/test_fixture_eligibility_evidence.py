"""Pure combination rules for fixture evidence; no verdict is ever produced."""
import itertools

import pytest

from fm_live_mcp import fixture_eligibility_evidence as evidence


def parts(reg, r14, r26, susp, skipped=False):
    covered = True if any(v is True for v in (reg, r14, r26)) else None
    return (dict(native_predicate_result=reg), dict(native_requirement14=r14),
            dict(native_result=r26, state='not_evaluated_first_requirement14_sufficient' if skipped else 'available'),
            covered, dict(state='checked' if susp is not None else 'unavailable',
                          native_suspended=susp, reason='synthetic'))


def run(*args, **kwargs):
    return evidence.combine(*parts(*args, **kwargs))


@pytest.mark.parametrize('reg,r14,r26,susp', list(itertools.product((True, False, None), repeat=4)))
def test_every_combination_is_never_a_verdict(reg, r14, r26, susp):
    result = run(reg, r14, r26, susp)
    assert result['fixture_eligibility'] == 'not_evaluated'
    assert result['clearance_established'] is result['exclusion_established'] is False
    assert result['suspension']['establishes_registration'] is False
    assert result['suspension']['native_suspended'] is susp
    covered = any(v is True for v in (reg, r14, r26))
    assert (result['registration']['coverage'] == 'covered_by_current_sources') is covered
    # Suspension never changes registration coverage.
    other = run(reg, r14, r26, None if susp is not None else False)
    assert other['registration'] == result['registration']


def test_native_false_registration_coexists_with_exemption():
    result = run(False, True, None, False, skipped=True)
    assert result['registration']['native_false_registration_with_exemption'] is True
    assert result['registration']['satisfied_by'] == ['requirement14']
    assert result['registration']['clauses']['requirement26'] == 'not_evaluated'
    assert run(False, False, True, False)['registration']['native_false_registration_with_exemption'] is True
    assert run(False, False, False, False)['registration']['native_false_registration_with_exemption'] is False


def test_suspension_false_is_not_registration_and_unknown_stays_unknown():
    result = run(None, None, None, False)
    assert result['registration']['coverage'] == 'unknown'
    assert result['reading'] == 'registration_unresolved'
    assert run(False, None, False, False)['registration']['coverage'] == 'unknown'


def test_all_checked_clauses_false_is_not_exclusion():
    result = run(False, False, False, False)
    assert result['registration']['coverage'] == 'not_covered_by_checked_clauses'
    assert result['reading'] == 'registration_not_covered_by_checked_clauses'
    assert result['exclusion_established'] is False


def test_native_suspension_is_an_adverse_fact_not_exclusion():
    result = run(True, None, None, True)
    assert result['reading'] == 'adverse_native_suspension_fact'
    assert result['exclusion_established'] is False
    assert run(None, None, None, True)['reading'] == 'adverse_native_suspension_fact'


@pytest.mark.parametrize('position', range(4))
def test_non_boolean_native_values_are_rejected(position):
    values = [True, False, None, False]
    values[position] = 1
    with pytest.raises(ValueError, match='type changed'):
        run(*values)


def test_changed_coverage_is_rejected():
    reg, r14, r26, _, susp = parts(True, None, None, False)
    with pytest.raises(ValueError, match='coverage changed'):
        evidence.combine(reg, r14, r26, None, susp)
