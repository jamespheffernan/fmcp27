"""Read-only full-native PI discovery with a separately frozen profile oracle."""
from pathlib import Path
import hashlib
import importlib.util
import struct
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pi'))
sys.path.append('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/lib/python3.14/site-packages')
import fm_tactic_native_authoring as native


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


writer = module('inspection_test_writer', ROOT / 'pi/fm-tactic-files.py')
ORACLE = ROOT / 'tests/native_optional_profile_oracle.py'
assert hashlib.sha256(ORACLE.read_bytes()).hexdigest() == 'e1034e2b3b3e45a2d6d834788f03708927416220a39f4f3412b77d23388a2069'
oracle = module('independent_current_optional_profile_oracle', ORACLE)


@pytest.fixture(scope='module')
def source():
    return writer.read_template(str(writer.TEMPLATES / '3421 FM27 .fmf'))[2]['.tac']


@pytest.mark.parametrize('filename', ['3421 FM27 .fmf', '4231 FM27 .fmf'])
def test_actual_current_profiles_match_independent_oracle_and_preserve_creator(filename):
    source = writer.read_template(str(writer.TEMPLATES / filename))[2]['.tac']
    creator = native.NativeCreator(source)
    initial = creator.serialize()
    raw = bytes(creator.uc.mem_read(native.CREATOR, 0x800))
    result = native.inspect_current_profiles(creator, native.role_catalog())
    assert len(result['current_role_profiles']) == 22
    for profile in result['current_role_profiles']:
        expected = oracle.current_optional_profile(lambda at, size: bytes(creator.uc.mem_read(at, size)),
                                                    profile['phase'], profile['position_index'], native_key_getter=creator.call)
        assert profile['entry_present'] == expected['stored_profile_present']
        assert profile['selected_native_option_ids'] == expected['selected_optional_ids']
        assert int(profile['stored_bits'], 16) & oracle.OPTION_MASK == expected['stored_low43']
        assert len(profile['native_editor_availability']) == 42
        assert {row['native_option'] for row in profile['native_editor_availability']} == set(range(1, 43))
        assert all(row['native_available'] == (row['native_state'] == 0) for row in profile['native_editor_availability'])
    assert result['full_native_serialization_unchanged'] and result['complete_creator_bytes_unchanged']
    assert creator.serialize() == initial
    assert bytes(creator.uc.mem_read(native.CREATOR, 0x800)) == raw


def absent_profile_creator(source):
    """Synthetic removal in owned VM; no game or product mutation API."""
    creator = native.NativeCreator(source)
    pointer = native.CREATOR + 0x120 + 9 * 72
    key = int(native.current_instructions(creator, 'in_possession', 9)['current_role_key'], 16)
    first, last, _ = struct.unpack('<3Q', creator.uc.mem_read(pointer + 8, 24))
    entries = bytes(creator.uc.mem_read(first, last - first))
    kept = b''.join(entries[at:at+24] for at in range(0, len(entries), 24)
                    if struct.unpack_from('<Q', entries, at)[0] != key)
    assert len(kept) == len(entries) - 24
    creator.uc.mem_write(first, kept)
    creator.uc.mem_write(pointer + 16, struct.pack('<Q', first + len(kept)))
    assert not native.current_instructions(creator, 'in_possession', 9)['entry_present']
    return creator, pointer


def test_missing_profile_remains_absent_during_discovery(source):
    creator, _ = absent_profile_creator(source)
    before = creator.serialize()
    result = native.inspect_current_profiles(creator, native.role_catalog())
    row = next(row for row in result['current_role_profiles'] if (row['phase'], row['position_index']) == ('in_possession', 9))
    assert row['entry_present'] is False and row['selected_native_option_ids'] == []
    assert creator.serialize() == before


def test_original_optional_getter_really_inserts_an_absent_profile(source):
    creator, pointer = absent_profile_creator(source)
    before = creator.serialize()
    creator.call(0x4976030, [pointer, 0])
    assert native.current_instructions(creator, 'in_possession', 9)['entry_present']
    assert creator.serialize() != before


def test_discovery_refuses_an_inserting_native_getter(source, monkeypatch):
    creator, pointer = absent_profile_creator(source)
    actual = native.instruction_availability
    inserted = False

    def inserting_query(owned, phase, slot, option):
        nonlocal inserted
        if not inserted and (phase, slot) == ('in_possession', 9):
            owned.call(0x4976030, [pointer, 0])
            inserted = True
        return actual(owned, phase, slot, option)

    monkeypatch.setattr(native, 'instruction_availability', inserting_query)
    with pytest.raises(ValueError, match='discovery unexpectedly changed'):
        native.inspect_current_profiles(creator, native.role_catalog())
    assert inserted


@pytest.mark.parametrize('target_mask', [1, 0x80000000])
def test_inspection_reports_raw_inherited_targets_without_named_person_or_admission_claim(source, target_mask):
    creator = native.NativeCreator(source)
    pointer = native.CREATOR + 0x440 + 9 * 72
    role = struct.unpack('<Q', creator.uc.mem_read(pointer + 64, 8))[0]
    creator.call(0x4976154, [pointer, 34, 0, 25, 0, 0, role])
    creator.call(0x4976154, [pointer, 35, 0, 0, target_mask, 0, role])
    result = native.inspect_current_profiles(creator, native.role_catalog())
    row = next(row for row in result['current_role_profiles'] if (row['phase'], row['position_index']) == ('out_of_possession', 9))
    assert row['specific_player_target']['stored_selection_byte'] == 25
    assert row['specific_player_target']['canonical_person_binding_verified'] is False
    assert row['specific_position_target']['native_mask'] == target_mask
    assert row['specific_position_target']['in_new_authoring_target_domain'] is False


def test_inherited_ip_target_domain_does_not_claim_actor_authoring_admission(source):
    creator = native.NativeCreator(source)
    pointer = native.CREATOR + 0x120 + 9 * 72
    role = struct.unpack('<Q', creator.uc.mem_read(pointer + 64, 8))[0]
    creator.call(0x4ADF614, [pointer, 35, 0, 0, 4, 0, role])
    inherited = native._preserve_header(creator.serialize(), source)
    loaded = native.NativeCreator(inherited)
    inspection = native.inspect_current_profiles(loaded, native.role_catalog())
    row = next(row for row in inspection['current_role_profiles'] if (row['phase'], row['position_index']) == ('in_possession', 9))
    target = row['specific_position_target']
    assert target['native_mask'] == 4 and target['in_new_authoring_target_domain'] is True
    assert 'admitted_for_new_authoring' not in target
    assert target['actor_phase_supported_by_typed_authoring'] is False
    assert target['actor_native_editor_available'] is False
    with pytest.raises(ValueError, match='out-of-possession setter context'):
        native.author(inherited, {'player_instructions': [{'phase': 'in_possession', 'position_index': 9,
                                                         'instructions': [], 'mark_specific_position': 'D(R)'}]})


def test_template_catalog_exposes_read_only_profiles_and_source_correspondence(source):
    result = native.catalog_for_payload(source)
    inspection = result['template_instruction_inspection']
    assert len(result['legal_roles_for_current_positions']) == 22
    assert len(inspection['current_role_profiles']) == 22
    correspondence = inspection['phase_correspondence']
    assert correspondence['forward'] == [slot if value == 255 else value
                                          for slot, value in enumerate(correspondence['stored'])]
    assert inspection['full_native_serialization_unchanged']
    assert 'output_path' not in result


def test_global_catalog_has_no_fabricated_template_state(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Global catalog must not construct a tactic creator')
    monkeypatch.setattr(native, 'NativeCreator', forbidden)
    result = native.catalog_for_payload()
    assert result['template_instruction_inspection'] is None
    assert result['legal_roles_for_current_positions'] is None
