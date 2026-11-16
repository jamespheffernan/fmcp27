"""Source-derived legal roles for failed requests, without substitutions.

A role edit is {phase, position_index, role}. The stored word is found through the
game's own legal set; a request names a role and nothing else.
"""
from pathlib import Path
import importlib.util
import json
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pi'))
sys.path.append('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/lib/python3.14/site-packages')
import fm_tactic_native_authoring as native
import fm_tactic_role_catalog as role_catalog
spec = importlib.util.spec_from_file_location('diagnostic_test_writer', ROOT / 'pi/fm-tactic-files.py')
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)

# The field the earlier interface carried beside a role, and the six values it took.
LEGACY_FIELD = re.compile(r'dut(y|ies)', re.IGNORECASE)
LEGACY_VALUES = {'Defend', 'Stopper', 'Cover', 'Support', 'Attack', 'Automatic'}


def legacy_wording(value, path='result'):
    """Every place a result names the removed field or carries one of its values."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if LEGACY_FIELD.search(str(key)):
                found.append(f'{path}.{key}')
            found += legacy_wording(item, f'{path}.{key}')
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found += legacy_wording(item, f'{path}[{index}]')
    elif isinstance(value, str) and (value in LEGACY_VALUES or LEGACY_FIELD.search(value)):
        found.append(f'{path}={value[:60]!r}')
    return found


@pytest.fixture(scope='module')
def source():
    return writer.read_template(str(writer.TEMPLATES / '4231 FM27 .fmf'))[2]['.tac']


@pytest.mark.parametrize('phase,slot,role,reason', [
    ('in_possession', 0, 'Centre-Back', 'Native position role mask refuses requested role'),
    ('in_possession', 10, 'CentreBack', 'Native position role mask refuses requested role'),
    ('out_of_possession', 1, 'Sweeper Keeper', 'Native position role mask refuses requested role'),
    ('in_possession', 5, 'Anchor', 'Known legacy role is removed by the native phase filter'),
    ('in_possession', 9, 'invented role', 'Unknown compiled role: invented role'),
])
def test_failed_role_requests_return_concrete_native_legal_roles(source, phase, slot, role, reason):
    creator = native.NativeCreator(source)
    before = creator.serialize()
    with pytest.raises(native.NativeAuthoringRequestError) as failure:
        native._set_roles(creator, [{'phase': phase, 'position_index': slot, 'role': role}])
    diagnostic = failure.value.diagnostic
    assert diagnostic['phase'] == phase and diagnostic['position_index'] == slot
    assert diagnostic['requested'] == {'role': role}
    assert diagnostic['rejection_reason'] == reason
    assert diagnostic['position_name']
    assert diagnostic['legal_roles'] and all(type(name) is str for name in diagnostic['legal_roles'])
    assert diagnostic['roles_refused_for_more_than_one_stored_word'] == []
    assert diagnostic['automatic_substitution_applied'] is False
    assert diagnostic['diagnostic_queries_mutated_creator'] is False
    assert f'requested {role}. {reason}. Legal roles: ' in str(failure.value)
    assert legacy_wording(diagnostic) == [] and legacy_wording(str(failure.value)) == []
    assert creator.serialize() == before
    for name in diagnostic['legal_roles']:
        actual = role_catalog.validate_role_request(creator, phase, slot, name)
        assert actual['legality_evaluated'] and actual['native_word_valid']


@pytest.mark.parametrize('phase,slot', [('other_phase', 0), ('in_possession', -1), ('in_possession', 11), ('in_possession', True)])
def test_invalid_slot_context_lists_exact_phase_and_index_domain(source, phase, slot):
    with pytest.raises(native.NativeAuthoringRequestError) as failure:
        native.author(source, {'roles': [{'phase': phase, 'position_index': slot, 'role': 'Goalkeeper'}]})
    diagnostic = failure.value.diagnostic
    assert diagnostic['legal_phases'] == ['in_possession', 'out_of_possession']
    assert diagnostic['legal_position_indices'] == list(range(11))
    assert 'legal_roles' not in diagnostic


@pytest.mark.parametrize('role', [[], None, 7])
def test_malformed_names_still_return_bounded_context(source, role):
    with pytest.raises(native.NativeAuthoringRequestError) as failure:
        native.author(source, {'roles': [{'phase': 'in_possession', 'position_index': 0, 'role': role}]})
    assert failure.value.diagnostic['position_name'] == 'GK'
    assert failure.value.diagnostic['rejection_reason'] == 'Explicit compiled role name required'


@pytest.mark.parametrize('row', [
    {'phase': 'in_possession', 'position_index': 0},
    {'phase': 'in_possession', 'position_index': 0, 'role': 'Goalkeeper', 'native_word': '0000000000200001'},
    {'phase': 'in_possession', 'position_index': 0, 'role': 'Goalkeeper', 'duty': 'Defend', 'extra': True},
])
def test_a_role_row_is_exactly_phase_index_and_role(source, row):
    with pytest.raises(ValueError, match='exact phase, position_index and role fields') as failure:
        native.author(source, {'roles': [row]})
    assert not isinstance(failure.value, native.NativeAuthoringRequestError)


@pytest.mark.parametrize('legacy', ['Defend', 'Support', 'Attack', 'Automatic', 'not a value the game ever had', '', None, 3])
def test_a_request_with_the_removed_field_is_accepted_and_the_field_ignored(source, legacy):
    wanted = [('in_possession', 10, 'Deep-Lying Forward', 0x800400), ('out_of_possession', 1, 'Pressing Full-Back', 0x400400),
              ('in_possession', 0, 'Goalkeeper', 0x200001)]
    by_name = {'roles': [{'phase': phase, 'position_index': slot, 'role': role} for phase, slot, role, _ in wanted]}
    carrying = {'roles': [row | {'duty': legacy} for row in by_name['roles']]}
    output, receipt = native.author(source, by_name)
    legacy_output, legacy_receipt = native.author(source, carrying)
    assert legacy_output == output and legacy_receipt == receipt
    assert [(row['phase'], row['position_index'], row['role'], int(row['after_word'], 16)) for row in receipt['roles']] == wanted
    assert all(set(row) == {'phase', 'position_index', 'role', 'before_word', 'after_word', 'changed', 'native_execution'}
               for row in receipt['roles'])
    assert legacy_wording(json.loads(json.dumps(legacy_receipt))) == []
    reloaded = native.NativeCreator(legacy_output).records()
    for phase, slot, _, word in wanted:
        assert next(row for row in reloaded if row['phase'] == phase and row['slot'] == slot)['role'] == word


def test_more_than_one_accepted_word_refuses_with_a_clear_reason_and_changes_nothing(source, monkeypatch):
    creator = native.NativeCreator(source)
    before = creator.serialize()
    accepted = role_catalog._word_accepted
    bits = [bit['word'] for bit in role_catalog._fixed_bits(role_catalog.catalog())]
    # The game's predicate, altered here to accept a second word for the goalkeeper role only.
    monkeypatch.setattr(role_catalog, '_word_accepted', lambda owned, phase, pointer, raw, word:
                        word in (1 | bits[0], 1 | bits[3]) or accepted(owned, phase, pointer, raw, word))
    with pytest.raises(native.NativeAuthoringRequestError) as failure:
        native._set_roles(creator, [{'phase': 'in_possession', 'position_index': 0, 'role': 'Goalkeeper'}])
    diagnostic = failure.value.diagnostic
    assert diagnostic['rejection_reason'] == 'The game offers more than one stored word for this role at this position; none is chosen'
    assert diagnostic['roles_refused_for_more_than_one_stored_word'] == ['Goalkeeper']
    assert 'Goalkeeper' not in diagnostic['legal_roles']
    assert diagnostic['automatic_substitution_applied'] is False
    assert creator.serialize() == before


def test_diagnostics_cannot_hide_cross_record_native_mutation(source, monkeypatch):
    creator = native.NativeCreator(source)
    assert native.current_instructions(creator, 'in_possession', 9)['selected_native_option_ids']
    original = native.legal_roles

    def mutating_choices(owned, phase, slot):
        choices = original(owned, phase, slot)
        native._reset_current(owned, 'in_possession', 9)
        return choices

    monkeypatch.setattr(native, 'legal_roles', mutating_choices)
    with pytest.raises(ValueError, match='diagnostic queries unexpectedly changed'):
        native._set_roles(creator, [{'phase': 'in_possession', 'position_index': 0, 'role': 'Centre-Back'}])


def test_native_source_failure_is_not_recast_as_a_request_correction(source):
    creator = native.NativeCreator(source)
    actual = creator.native
    first_span = role_catalog.NATIVE_GUARDS[0][0]

    def corrupt_source(at, size):
        data = actual(at, size)
        return bytes([data[0] ^ 1]) + data[1:] if at == first_span else data

    creator.native = corrupt_source
    with pytest.raises(ValueError, match='Original tactic selection source changed') as failure:
        native._set_roles(creator, [{'phase': 'in_possession', 'position_index': 0, 'role': 'Centre-Back'}])
    assert not isinstance(failure.value, native.NativeAuthoringRequestError)


def test_outer_generation_retains_structured_context_and_delivers_nothing(source, tmp_path, monkeypatch):
    template = writer.TEMPLATES / '4231 FM27 .fmf'
    original = template.read_bytes()
    monkeypatch.setattr(writer, 'OUTPUTS', tmp_path)
    with pytest.raises(ValueError) as failure:
        writer.generate({'template_path': str(template), 'template_sha256': writer.sha(original),
                         'name': 'Invalid native role diagnostic candidate',
                         'native_authoring': {'roles': [{'phase': 'in_possession', 'position_index': 0,
                                                        'role': 'Centre-Back'}]}})
    assert failure.value.diagnostic['requested'] == {'role': 'Centre-Back'}
    assert failure.value.diagnostic['legal_roles'] == ['Goalkeeper', 'Ball-Playing Goalkeeper', 'No-Nonsense Goalkeeper']
    assert legacy_wording(failure.value.diagnostic) == []
    assert list(tmp_path.iterdir()) == []
    assert template.read_bytes() == original


def test_successful_catalog_uses_the_same_native_choice_enumerator(source):
    result = native.catalog_for_payload(source)
    creator = native.NativeCreator(source)
    for actual in result['legal_roles_for_current_positions']:
        assert actual == role_catalog.legal_roles(creator, actual['phase'], actual['position_index'])
    assert set(result) == {'positions', 'roles', 'record_legality', 'legal_roles_for_current_positions',
                           'player_instructions', 'template_instruction_inspection', 'unbound_player_instruction_ids',
                           'team_instructions', 'typed_player_instruction_targets', 'instruction_policies',
                           'native_binary_sha256', 'scope'}
    assert legacy_wording(json.loads(json.dumps(result))) == []
