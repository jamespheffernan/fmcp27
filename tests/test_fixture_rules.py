import json
import struct
from pathlib import Path

import pytest

from fm_live_mcp import fixture_rules, fixtures
from fm_live_mcp.bridge import BridgeError
from test_fixtures import fixture_memory, team_memory, database_memory, world_memory, memory, query
from test_bridge import bridge

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture
def rules_memory(fixture_memory):
    m = fixture_memory
    for item in json.loads((FIXTURES / 'fixture_rules_native.json').read_text()):
        m['put'](m['base'] + item['rva'], bytes.fromhex(item['raw_hex']))
    for kind in ('fixture', 'result'):
        m['q'](m['base'] + fixtures.TYPES[kind][0] + 0xB0, m['base'] + 0x3CFAB7C)
    for a in m['fixtures']:
        m['put'](a + 0x32, struct.pack('<H', 514))
        m['put'](a + 0x3C, b'\0')
        m['put'](a + 0x3E, bytes([58]))
    return m


def test_all_native_signed_codes_both_sides():
    oracle = json.loads((FIXTURES / 'fixture_substitution_oracle.json').read_text())
    assert len(oracle) == 512
    for code, away, named, used, stoppages in oracle:
        row = fixture_rules.substitutions(code, away, 15)
        assert row['named_substitute_cap'] == min(named, 15)
        assert row['used_substitute_cap'] == min(used, 15)
        assert row['substitution_stoppages'] == (None if stoppages < 0 else stoppages)
        assert row['extra_time_substitute_addition'] is None
        assert row['stage_adjusted_confirmation_cap'] is None
        assert row['player_eligibility_evaluated'] is False


def test_asymmetric_context_and_native_fallback():
    assert fixture_rules.substitutions(67, False, 15)['named_substitute_cap'] == 12
    assert fixture_rules.substitutions(58, False, 8)['named_substitute_cap'] == 8
    assert fixture_rules.substitutions(-1, False, 15)['state'] == 'native_fallback_for_out_of_range_code'
    assert fixture_rules.substitutions(-1, False, 15)['substitution_stoppages'] is None


@pytest.mark.parametrize('word,special,after,extra', [
    (514, 0, 'penalty_shootout', None), (515, 0, 'extra_time', 'penalty_shootout'),
    (512, 0, 'no_deciding_flag', None), (512, 4, 'replay', None),
    (513, 0, 'extra_time', 'not_established'), (513, 4, 'extra_time', 'replay'),
])
def test_native_simple_draw_patterns(word, special, after, extra):
    row = fixture_rules.draw_resolution(word, special)
    assert row['state'] == 'decoded_supported_stored_pattern'
    assert row['after_90_if_level'] == after
    assert row['after_extra_time_if_still_level'] == extra


@pytest.mark.parametrize('word,special', [(518, 0), (514, 1), (514, 4), (0xFFFF, 255)])
def test_unmapped_draw_combinations_preserve_raw_flags(word, special):
    row = fixture_rules.draw_resolution(word, special)
    assert row['state'] == 'unavailable_unmapped_rule_pattern'
    assert row['after_90_if_level'] is None
    assert row['raw_FxMR_u16'] == word and row['raw_FxSR_u8'] == special


@pytest.mark.parametrize('args', [(True, 0), (-1, 0), (65536, 0), (514, True), (514, -1), (514, 256)])
def test_invalid_draw_scalars(args):
    with pytest.raises(ValueError): fixture_rules.draw_resolution(*args)


def test_query_exact_context_and_no_new_refs(bridge, monkeypatch, rules_memory):
    rows = query(bridge, monkeypatch, rules_memory)['fixtures']
    before = tuple(set(getattr(bridge, key)) for key in ('fixture_refs', 'team_refs', 'competition_refs', 'stadium_refs'))
    response = bridge.get_fixture_rules(bridge.session, rows[0]['fixture_ref'])
    assert response['fixture']['fixture_ref'] == rows[0]['fixture_ref']
    limits = response['rules']['substitutions']
    assert [x['side'] for x in limits] == ['home', 'away']
    assert all((x['named_substitute_cap'], x['used_substitute_cap'], x['substitution_stoppages']) == (9, 5, 3) for x in limits)
    assert limits[0]['team']['database_index'] != limits[1]['team']['database_index']
    assert response['rules']['draw_resolution']['after_90_if_level'] == 'penalty_shootout'
    after = tuple(set(getattr(bridge, key)) for key in ('fixture_refs', 'team_refs', 'competition_refs', 'stadium_refs'))
    assert before == after


def test_rule_change_expires_identity_then_fresh_search_reads_it(bridge, monkeypatch, rules_memory):
    m = rules_memory
    ref = query(bridge, monkeypatch, m)['fixtures'][0]['fixture_ref']
    m['put'](m['fixtures'][0] + 0x32, struct.pack('<H', 512))
    with pytest.raises(BridgeError, match='identity changed'): bridge.get_fixture_rules(bridge.session, ref)
    fresh = query(bridge, monkeypatch, m)['fixtures'][0]['fixture_ref']
    assert bridge.get_fixture_rules(bridge.session, fresh)['rules']['draw_resolution']['after_90_if_level'] == 'no_deciding_flag'


@pytest.mark.parametrize('fault', ['native', 'table', 'bucket', 'identity'])
def test_changed_sources_reject_and_expire_ref(bridge, monkeypatch, rules_memory, fault):
    m = rules_memory
    ref = query(bridge, monkeypatch, m)['fixtures'][0]['fixture_ref']
    if fault == 'native':
        at = m['base'] + fixture_rules.NATIVE_GUARDS[0][0]
        m['put'](at, bytes([m['read'](at, 1)[0] ^ 1]))
    if fault == 'table': m['q'](m['base'] + fixtures.TYPES['result'][0] + 0xB0, m['base'] + 0x3D03098)
    if fault == 'bucket': m['vec'](m['fixture_buckets'][0], m['fixtures'][1:3])
    if fault == 'identity': m['q'](m['fixtures'][0] + 8, m['team_addresses'][1])
    with pytest.raises(BridgeError, match='no partial result'): bridge.get_fixture_rules(bridge.session, ref)
    assert ref not in bridge.fixture_refs


def test_rules_torn_during_read_publish_nothing(bridge, monkeypatch, rules_memory):
    m = rules_memory
    ref = query(bridge, monkeypatch, m)['fixtures'][0]['fixture_ref']
    old = m['read']
    read_address = m['fixtures'][0]
    calls = 0
    def changing(a, n):
        nonlocal calls
        raw = old(a, n)
        if a == read_address and n == 0x58:
            calls += 1
            if calls == 2: m['put'](read_address + 0x3E, bytes([67]))
        return raw
    monkeypatch.setattr(bridge, '_read_memory', lambda p, a, n: changing(a, n))
    team_refs = set(bridge.team_refs)
    with pytest.raises(BridgeError): bridge.get_fixture_rules(bridge.session, ref)
    assert set(bridge.team_refs) == team_refs
    assert ref not in bridge.fixture_refs


@pytest.mark.parametrize('bad', [None, '', [], 3])
def test_invalid_reference_input(bridge, bad):
    with pytest.raises(BridgeError): bridge.get_fixture_rules(bridge.session, bad)


@pytest.mark.parametrize('index', range(len(fixture_rules.NATIVE_GUARDS)))
def test_every_native_code_or_lookup_table_guard(bridge, monkeypatch, rules_memory, index):
    m = rules_memory
    ref = query(bridge, monkeypatch, m)['fixtures'][0]['fixture_ref']
    at = m['base'] + fixture_rules.NATIVE_GUARDS[index][0]
    m['put'](at, bytes([m['read'](at, 1)[0] ^ 1]))
    with pytest.raises(BridgeError, match='native code changed'):
        bridge.get_fixture_rules(bridge.session, ref)
    assert ref not in bridge.fixture_refs


def test_same_TEAM_pointer_uses_native_equality_not_side_label(bridge, monkeypatch, rules_memory):
    m = rules_memory
    m['q'](m['fixtures'][0] + 16, m['team_addresses'][0])
    m['put'](m['fixtures'][0] + 0x3E, bytes([22]))
    ref = query(bridge, monkeypatch, m)['fixtures'][0]['fixture_ref']
    limits = bridge.get_fixture_rules(bridge.session, ref)['rules']['substitutions']
    assert [x['named_substitute_cap'] for x in limits] == [7, 7]
    assert all(x['away_context'] is False for x in limits)
    assert all(x['team_context_state'] == 'same_team_on_both_sides' for x in limits)


def test_null_side_TEAM_preserves_missing_context(bridge, monkeypatch, rules_memory):
    m = rules_memory
    rows = query(bridge, monkeypatch, m)['fixtures']
    limits = bridge.get_fixture_rules(bridge.session, rows[3]['fixture_ref'])['rules']['substitutions']
    assert all(x['team'] is None and x['team_context_state'] == 'missing_team' for x in limits)
    assert all(x['named_substitute_cap'] is None and x['used_substitute_cap'] is None for x in limits)
    assert all(x['away_context'] is None and x['state'] == 'unavailable_team_context' for x in limits)
