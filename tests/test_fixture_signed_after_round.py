import json
import struct
from pathlib import Path

import pytest

from fm_live_mcp import fixture_signed_after_round as signed, fixtures
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_fixture_rules import rules_memory
from test_competition_stages import stage_memory
from test_fixtures import query, fixture_memory
from test_database import database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory


@pytest.fixture
def signed_memory(rules_memory, stage_memory):
    assert rules_memory is stage_memory
    m = rules_memory
    for item in json.loads((Path(__file__).parent / 'fixtures/signed_after_round_native.json').read_text()):
        m['put'](m['base'] + item['rva'], bytes.fromhex(item['raw_hex']))
    m['q'](m['base'] + 0x5671B68, m['base'] + 0x5299280)
    m['put'](m['base'] + 0x5671B70, b'\x80')
    m['put'](m['base'] + 0x5299280, signed.NAME.encode() + b'\0')
    cup = m['stages']['cup']
    table = m['base'] + 0x5671128
    m['q'](table + 0x298, m['base'] + 0x3C8C030)
    m['q'](table + 0x368, m['base'] + 0x3C9C290)
    details = m['allocate'](0x80)
    rounds = [m['allocate'](0x100) for _ in range(2)]
    m['q'](cup + 0x90, details)
    m['vec'](details + 0x58, rounds)
    for fixture in m['fixtures']:
        m['put'](fixture + 0x30, struct.pack('<H', 2030))
        m['put'](fixture + 0x38, b'\x03\x00\x00\x01')
    m.update(cup_details=details, cup_rounds=rounds)
    return m


def source(m):
    fixture = m['fixtures'][0]
    return signed.read_activation(m['read'], m['base'], m['read'](fixture, 0x58), m['competitions'][0])


def test_all_flag_bytes_and_wrong_adjacent_enum_value():
    for flag in range(256):
        row = signed.activation(flag)
        assert row['enabled'] == bool(flag & 128)
    assert not signed.activation(64)['enabled']
    assert signed.activation(128)['specific_check_state'] == 'enabled_player_and_date_checks_not_evaluated'


@pytest.mark.parametrize('bad', [-1, 256, True, None])
def test_invalid_flags(bad):
    with pytest.raises(ValueError):
        signed.activation(bad)


def test_effective_round_uses_signed_3b_not_39_or_fixture_flags(signed_memory):
    m = signed_memory
    m['put'](m['cup_rounds'][0] + 0xDA, b'\x80')
    m['put'](m['fixtures'][0] + 0x3C, b'\x80')
    row = source(m)
    assert row['enabled'] is False and row['round_index'] == 1
    assert row['specific_check_state'] == 'bypassed_by_clear_round_flag'
    assert row['fixture_flag_agrees'] is False
    m['put'](m['cup_rounds'][1] + 0xDA, b'\x80')
    row = source(m)
    assert row['enabled'] is True and row['fixture_flag_agrees'] is True
    assert row['player_eligibility_evaluated'] is False


@pytest.mark.parametrize('fault,reason', [
    ('runtime', 'runtime_competition_absent'),
    ('season', 'fixture_runtime_season_mismatch'),
    ('stage_negative', 'stage_index_outside_runtime_vector'),
    ('stage_outside', 'stage_index_outside_runtime_vector'),
    ('stage_null', 'null_stage'),
    ('league', 'unsupported_stage_kind'),
    ('cup_group', 'unsupported_stage_kind'),
    ('unknown_stage', 'unsupported_stage_kind'),
    ('round_negative', 'negative_round_index'),
    ('round_outside', 'round_index_outside_runtime_vector'),
    ('details_null', 'round_details_absent'),
    ('round_null', 'null_round'),
    ('getter', 'unsupported_round_consumer_or_getter'),
    ('consumer', 'unsupported_round_consumer_or_getter'),
])
def test_narrow_unavailable_states(signed_memory, fault, reason):
    m = signed_memory
    fixture, table = m['fixtures'][0], m['base'] + 0x5671128
    if fault == 'runtime': m['q'](m['competitions'][0] + 0xB0, 0)
    if fault == 'season': m['put'](fixture + 0x30, struct.pack('<H', 2029))
    if fault == 'stage_negative': m['put'](fixture + 0x38, b'\xff')
    if fault == 'stage_outside': m['put'](fixture + 0x38, b'\x70')
    if fault == 'stage_null': m['vec'](m['runtime'] + 0x1D8, [0] * 4)
    if fault in ('league', 'cup_group'): m['vec'](m['runtime'] + 0x1D8, [0, 0, 0, m['stages'][fault]])
    if fault == 'unknown_stage': m['q'](m['stages']['cup'], m['base'] + 0x1238)
    if fault == 'round_negative': m['put'](fixture + 0x3B, b'\xff')
    if fault == 'round_outside': m['put'](fixture + 0x3B, b'\x7f')
    if fault == 'details_null': m['q'](m['stages']['cup'] + 0x90, 0)
    if fault == 'round_null': m['vec'](m['cup_details'] + 0x58, [0, 0])
    if fault == 'getter': m['q'](table + 0x368, m['base'] + 0x3C9C2B4)
    if fault == 'consumer': m['q'](table + 0x298, m['base'] + 1)
    row = source(m)
    assert row['state'] == 'unavailable' and row['reason'] == reason
    assert row['enabled'] is None and row['specific_check_state'] == 'not_established'


@pytest.mark.parametrize('fault', ['native', 'enum_value', 'enum_pointer', 'enum_name', 'backlink', 'bounds'])
def test_changed_or_invalid_source_rejects(signed_memory, fault):
    m = signed_memory
    if fault == 'native': m['put'](m['base'] + signed.NATIVE_GUARDS[0][0], b'!')
    if fault == 'enum_value': m['put'](m['base'] + 0x5671B70, b'\x40')
    if fault == 'enum_pointer': m['q'](m['base'] + 0x5671B68, m['base'] + 0x5299261)
    if fault == 'enum_name': m['put'](m['base'] + 0x5299280, b'!')
    if fault == 'backlink': m['q'](m['stages']['cup'] + 0x70, 0)
    if fault == 'bounds': m['q'](m['cup_details'] + 0x68, 1)
    with pytest.raises(ValueError): source(m)

