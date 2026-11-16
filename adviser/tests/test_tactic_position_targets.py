"""Typed native PI35 transport through whole parent serialization, offline."""
from pathlib import Path
import importlib.util
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pi'))
sys.path.append('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/lib/python3.14/site-packages')
import fm_tactic_native_authoring as native
spec = importlib.util.spec_from_file_location('position_target_writer', ROOT / 'pi/fm-tactic-files.py')
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)


@pytest.fixture(scope='module')
def source():
    return writer.read_template(str(writer.TEMPLATES / '3421 FM27 .fmf'))[2]['.tac']


POSITIONS = [row for row in native.role_catalog()['positions'] if row['native_mask'] != 1]


@pytest.mark.parametrize('target', POSITIONS, ids=lambda row: str(row['native_mask']))
def test_all_menu_position_targets_roundtrip_original_accessors(source, target):
    name = target['compiled_english_name'] or '+'.join(target['metadata_mask_components'])
    request = {'player_instructions': [{'phase': 'out_of_possession', 'position_index': 9,
                                        'instructions': [], 'mark_specific_position': name}]}
    original = native.NativeCreator(source).records()
    output, receipt = native.author(source, request)
    loaded = native.NativeCreator(output)
    pointer = native.CREATOR + 0x440 + 9 * 72
    assert loaded.call(0x4975AD0, [pointer]) == target['native_mask']
    assert loaded.call(0x4975978, [pointer]) & 255 == 255
    assert native.current_instructions(loaded, 'out_of_possession', 9)['selected_native_option_ids'] == [35]
    assert [row for row in loaded.records() if (row['phase'], row['slot']) != ('out_of_possession', 9)] == [
        row for row in original if (row['phase'], row['slot']) != ('out_of_possession', 9)]
    assert receipt['player_instructions'][0]['mark_specific_position']['native_mask'] == target['native_mask']
    assert receipt['player_instructions'][0]['mark_specific_position']['native_editor_target_picker_offering_verified']
    assert receipt['player_instructions'][0]['mark_specific_position']['rendered_target_picker_observed'] is False
    assert writer.native_source_preservation(source, output, request)['source_outside_declared_native_footprints_preserved']


@pytest.mark.parametrize('phase,slot,target,instructions', [
    ('in_possession', 9, 'D(C)', []),
    ('out_of_possession', 0, 'D(C)', []),
    ('out_of_possession', 9, 'invented', []),
    ('out_of_possession', 9, 'GK', []),
    ('out_of_possession', 9, 4, []),
    ('out_of_possession', 9, 'D(C)', ['PI_MARK_SPECIFIC_POSITION']),
    ('out_of_possession', 9, 'D(C)', ['PI_MARK_SPECIFIC_PLAYER']),
])
def test_invalid_or_unbound_target_requests_refuse(source, phase, slot, target, instructions):
    with pytest.raises(ValueError):
        native.author(source, {'player_instructions': [{'phase': phase, 'position_index': slot,
                                                       'instructions': instructions, 'mark_specific_position': target}]})


@pytest.mark.parametrize('slot', [8, 9, 10])
def test_switch_position_plain_toggle_in_native_admitted_contexts(source, slot):
    request = {'player_instructions': [{'phase': 'in_possession', 'position_index': slot,
                                        'instructions': ['PI_SWITCH_POSITION']}]}
    output, receipt = native.author(source, request)
    creator = native.NativeCreator(output)
    pointer = native.CREATOR + 0x120 + 72 * slot
    assert creator.call(0x4ADEC28, [pointer, 28, 0]) == 1
    assert native.current_instructions(creator, 'in_possession', slot)['selected_native_option_ids'] == [28]
    assert receipt['phase_correspondence']['before'] == receipt['phase_correspondence']['after']
    cleared, _ = native.author(output, {'player_instructions': [{'phase': 'in_possession', 'position_index': slot,
                                                                'instructions': []}]})
    reloaded = native.NativeCreator(cleared)
    assert reloaded.call(0x4ADEC28, [pointer, 28, 0]) == 0


@pytest.mark.parametrize('phase,slot', [('in_possession', 0), ('in_possession', 7), ('out_of_possession', 9)])
def test_switch_position_unavailable_contexts_refuse(source, phase, slot):
    with pytest.raises(ValueError, match='unavailable'):
        native.author(source, {'player_instructions': [{'phase': phase, 'position_index': slot,
                                                       'instructions': ['PI_SWITCH_POSITION']}]})
