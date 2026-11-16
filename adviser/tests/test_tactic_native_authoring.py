"""Whole original-native authoring over actual retained tactic archives.

These checks execute ARM in isolated owned memory, never the running game.
"""
from pathlib import Path
import importlib.util
import struct
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pi'))
sys.path.append('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/lib/python3.14/site-packages')
import fm_tactic_native_authoring as native

spec = importlib.util.spec_from_file_location('native_authoring_test_writer', ROOT / 'pi/fm-tactic-files.py')
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)


@pytest.fixture(scope='module')
def source():
    return writer.read_template(str(writer.TEMPLATES / '4231 FM27 .fmf'))[2]['.tac']


def test_noop_is_byte_exact_and_has_independent_native_reload(source):
    output, receipt = native.author(source, {})
    assert output == source
    assert receipt['changed_records'] == []
    assert receipt['all22_position_role_selections_legal']
    assert receipt['phase_correspondence']['before'] == receipt['phase_correspondence']['after']
    assert writer.native_source_preservation(source, output, {})['source_outside_declared_native_footprints_preserved']


def test_complete_role_plan_native_defaults_and_clean_team_replacement(source):
    request = {'roles': [
        {'phase': 'in_possession', 'position_index': slot, 'role': role}
        for slot, role in [(2, 'Centre-Back'), (3, 'Ball-Playing Centre-Back'),
                           (4, 'Full-Back'), (5, 'Defensive Midfielder'), (9, 'Winger')]],
        'instruction_policy': 'native_defaults', 'team_instructions': ['Counter', 'Mid Block', 'Regroup']}
    output, receipt = native.author(source, request)
    assert len(receipt['roles']) == 5 and all(row['changed'] for row in receipt['roles'])
    # The stored words are the ones the earlier interface wrote for these roles at these positions.
    assert [row['after_word'] for row in receipt['roles']] == [
        '0000000000200002', '0000000001200000', '0000000000400004', '0000000000200010', '0000000000400080']
    assert len(receipt['current_role_resets']) == 22
    assert all(row['selected_native_option_ids'] == [] for row in receipt['current_role_instructions'])
    assert receipt['team_instructions']['selected_native_option_ids'] == [54, 62, 71]
    assert receipt['phase_correspondence']['after'] == [0, 1, 2, 3, 4, 5, 6, 7, 9, 8, 10]
    assert output[:15] == source[:15]
    proof = writer.native_source_preservation(source, output, request)
    assert proof['source_outside_declared_native_footprints_preserved']
    # An undeclared role change must fail the actual source-footprint comparison.
    assert not writer.native_source_preservation(source, output, {})['source_outside_declared_native_footprints_preserved']


@pytest.mark.parametrize('kind,value', [
    ('role', 0), ('role', 0x200003), ('role', (1 << 63) | 0x200001),
    ('role', 0x200002), ('position', 0x80000000), ('position', 1)])
def test_canonical_but_illegal_inherited_sources_refuse(source, kind, value):
    creator = native.NativeCreator(source)
    pointer = native.CREATOR + 0x120 + 10 * 72
    creator.uc.mem_write(pointer + (64 if kind == 'role' else 0),
                         struct.pack('<Q' if kind == 'role' else '<I', value))
    if kind == 'position' and value == 1:
        creator.uc.mem_write(pointer + 64, struct.pack('<Q', 0x200001))
    malformed = native._preserve_header(creator.serialize(), source)
    with pytest.raises(ValueError):
        native.author(malformed, {})


@pytest.mark.parametrize('selection', [
    {'roles': [{'phase': 'in_possession', 'position_index': 0, 'role': 'Centre-Back'}]},
    {'roles': [{'phase': 'in_possession', 'position_index': 0, 'role': 'Sweeper Keeper'}]},
    {'roles': [{'phase': 'in_possession', 'position_index': 0, 'role': 'Goalkeeper', 'native_word': '0000000000800001'}]},
    {'roles': [{'phase': 'in_possession', 'position_index': 0, 'role': 'Goalkeeper'},
               {'phase': 'in_possession', 'position_index': 0, 'role': 'Ball-Playing Goalkeeper'}]},
    {'positions': {'in_possession': ['GK'] * 11}},
    {'team_instructions': ['Counter', 'Hold Shape']},
    {'team_instructions': ['Distribute To Specific Team-Mate']},
    {'player_instructions': [{'phase': 'out_of_possession', 'position_index': 9, 'instructions': ['PI_MARK_SPECIFIC_POSITION']}]},
    {'instruction_policy': 'invented'}, {'pointer': 0x100400000}])
def test_invalid_complete_requests_refuse(source, selection):
    with pytest.raises(ValueError):
        native.author(source, selection)


def test_native_call_requires_original_balanced_return(source):
    creator = native.NativeCreator(source)
    with pytest.raises(ValueError):
        creator.call(native.STOP, [])


def test_materially_different_plan_uses_native_layout_and_named_pi_setter(source):
    layouts = {phase: [row['position_name'] for row in writer.phase_records(source)[phase]]
               for phase in ('in_possession', 'out_of_possession')}
    for labels in layouts.values():
        labels[10] = 'D(C)'
    selection = {'positions': layouts,
                 'roles': [{'phase': 'in_possession', 'position_index': 8,
                            'role': 'Advanced Playmaker'}],
                 'team_instructions': ['Focus Play Down The Left', 'Focus Play Down The Right'],
                 'instruction_policy': 'native_defaults',
                 'player_instructions': [{'phase': 'in_possession', 'position_index': 9,
                                          'instructions': ['PI_PASS_SHORTER']}]}
    output, receipt = native.author(source, selection)
    assert receipt['positions']
    for phase, labels in layouts.items():
        assert [row['position_name'] for row in writer.phase_records(output)[phase]] == labels
    assert receipt['team_instructions']['selected_native_option_ids'] == [21, 22]
    assert receipt['player_instructions'][0]['after']['selected_native_option_ids'] == [1]
    assert receipt['phase_correspondence']['native_reload_verified']
    assert receipt['all22_position_role_selections_legal']


def test_actual_fmf_delivery_checks_source_and_conditional_preservation(source, tmp_path, monkeypatch):
    template = writer.TEMPLATES / '4231 FM27 .fmf'
    original = template.read_bytes()
    monkeypatch.setattr(writer, 'OUTPUTS', tmp_path)
    selection = {'template_path': str(template), 'template_sha256': writer.sha(original),
                 'name': 'Native authoring regression candidate',
                 'fm27_folder': True, 'tactics_directory': str(tmp_path),
                 'native_authoring': {'roles': [{'phase': 'in_possession', 'position_index': 5,
                                                'role': 'Defensive Midfielder'}]}}
    result = writer.generate(selection)
    assert result['native_authoring']['roles'][0]['after_word'] == '0000000000200010'
    assert result['stored_football']['phase_positions_and_roles']['in_possession'][5] == {
        'slot': 5, 'position': 'DM(CR)', 'native_position_mask': 2097280, 'role': 'Defensive Midfielder',
        'native_role_word': '0000000000200010'}
    assert Path(result['output_path']).is_file() and Path(result['receipt_path']).is_file()
    assert template.read_bytes() == original
    assert result['verification']['all_unrequested_tactic_bytes_preserved']
    assert result['verification']['host_edits_preserved_native_authoring_result']
    assert not {'formations', 'phase roles', 'player instruction bytes'} & set(result['preserved'])
    assert result['native_authoring']['postpack_verification']['all22_typed_records_verified']
    with pytest.raises(FileExistsError):
        writer.generate(selection)
