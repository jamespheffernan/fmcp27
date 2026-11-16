"""Typed source controls; explicit variants are synthetic, not live settings."""
import pytest
from fm_live_mcp import individual_training_intensity as intensity
from fm_live_mcp.bridge import BridgeError
from test_individual_training_focus import focus_memory, native_image, inspect
from test_live_individual_training import live_focus, get
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_database import database_memory
from test_players import memory
from test_shortlist_members import member_memory
from test_teams import team_memory
from test_world import world_memory


def test_all_256_codes_keep_named_zero_default_request_and_unknowns_distinct(focus_memory):
    m = focus_memory
    expected = {0: (466612, 'Half Intensity'), 1: (467455, 'Normal Intensity'),
                2: (466613, 'Double Intensity'), 254: (467456, 'No pitch or gym work')}
    for raw in range(256):
        m['put'](0x1000 + 0x1eb, bytes([raw]))
        m['put'](0x1000 + 0x1f5, bytes([raw ^ 255]))
        row = inspect(m)
        value = row['club_training_intensity']
        assert value['raw_code'] == raw and value['native_code'] == (raw if raw < 128 else raw - 256)
        assert value['applied_intensity'] is None and value['workload'] is None
        assert row['additional_focus']['english_definition_name'] == 'Crossing'
        if raw == 255:
            assert value['state'] == 'native_default_resolution_requested'
            assert value['explicit_intensity'] is False and value['english_definition_name'] is value['english_resource_key'] is None
        elif raw in expected:
            assert value['state'] == 'stored_named_intensity' and value['explicit_intensity'] is True
            assert (value['english_resource_key'], value['english_definition_name']) == expected[raw]
        else:
            assert value['state'] == 'unknown_native_code' and value['explicit_intensity'] is None
            assert value['english_definition_name'] is value['english_resource_key'] is None


def test_missing_focus_child_does_not_hide_concrete_zero_intensity(focus_memory):
    m = focus_memory
    m['q'](0x1190, 0)
    m['put'](0x11eb, b'\0')
    row = inspect(m)
    assert row['source_state'] == 'missing_child' and row['additional_focus']['state'] == 'unset'
    assert row['club_training_intensity']['state'] == 'stored_named_intensity'
    assert row['club_training_intensity']['english_definition_name'] == 'Half Intensity'


@pytest.mark.parametrize('value', [None, True, False, -1, 256, '1', 1.0, b'\x01'])
def test_invalid_byte_inputs_are_not_coerced(value):
    with pytest.raises(ValueError):
        intensity.decode(value)


@pytest.mark.parametrize('index', range(6))
def test_each_new_native_binding_rejects_drift(focus_memory, index):
    m = focus_memory
    rva, _, _ = intensity.NATIVE_GUARDS[index]
    m['put'](m['base'] + rva, bytes([m['read'](m['base'] + rva, 1)[0] ^ 1]))
    with pytest.raises(ValueError, match='native source changed'):
        inspect(m)
    with pytest.raises(ValueError, match='club-intensity native source changed'):
        intensity.verify_native(m['read'], m['base'])


def test_new_field_participates_in_internal_byte_rechecks(focus_memory):
    m = focus_memory
    calls = 0
    def changing(address, size):
        nonlocal calls
        raw = m['read'](address, size)
        if (address, size) == (0x11eb, 1):
            calls += 1
            if calls == 2:
                return bytes([raw[0] ^ 1])
        return raw
    with pytest.raises(ValueError, match='changed during read'):
        inspect(m, read=changing)


def test_new_byte_is_rechecked_after_final_lifetime_callback(live_focus, monkeypatch):
    m = live_focus
    original = m['bridge']._current
    calls = 0
    def current(session):
        nonlocal calls
        calls += 1
        process = original(session)
        if calls == 3:
            m['put'](0x11eb, b'\x02')
        return process
    monkeypatch.setattr(m['bridge'], '_current', current)
    with pytest.raises(BridgeError, match='changed during read'):
        get(m)


def test_public_batch_keeps_intensity_distinct_from_focus_and_default(live_focus):
    m = live_focus
    for raw, name, state in [(0, 'Half Intensity', 'stored_named_intensity'),
                             (2, 'Double Intensity', 'stored_named_intensity'),
                             (255, None, 'native_default_resolution_requested'),
                             (99, None, 'unknown_native_code')]:
        m['put'](0x11eb, bytes([raw]))
        result = get(m)
        row, = result['players']
        assert row['club_training_intensity']['english_definition_name'] == name
        assert row['club_training_intensity']['state'] == state
        assert row['additional_focus']['english_definition_name'] == 'Crossing'
        assert result['field_sources']['club_training_intensity'] == 'stored_regular_player_club_training_intensity'
        assert result['source'] == 'stored_player_individual_training_additional_focus'
