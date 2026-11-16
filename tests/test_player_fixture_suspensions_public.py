"""Optional fixture projection keeps incumbent records and checked batch semantics."""
from copy import deepcopy

import pytest

from fm_live_mcp import fixtures, player_fixture_suspensions as source
from fm_live_mcp.bridge import BridgeError
from test_player_ban_public import (ban_world, public_assessment_memory, bridge,
    shortlist_public_memory, prepared_tactics_memory, database_memory, memory,
    team_memory, world_memory)


@pytest.fixture
def fixture_world(ban_world, bridge, monkeypatch):
    m, ref, *_ = ban_world
    saved = dict(tables=bridge.player_refs[ref]['tables'], catalog_identity=('inventory',),
                 year=2030, day=327, group=0, route=('bucket',), slot=0,
                 address=0x990000, identity=('fixture',))
    bridge.fixture_refs['fixture'] = saved
    calls = []
    monkeypatch.setattr(fixtures, 'catalog', lambda *_: (None, {2030: 'year'}, ('inventory',)))
    monkeypatch.setattr(fixtures, 'bucket', lambda *_: ((0x990000,), ('bucket',)))
    monkeypatch.setattr(fixtures, 'record', lambda *_: dict(identity=('fixture',)))
    m['put'](0x99004C, b'\x47\x01\xee\x07')
    def context(read, base, address, decoded, current_date):
        assert address == 0x990000 and decoded['identity'] == ('fixture',)
        read(address+0x4C, 4)
        return dict(state='available', full_outer_availability_evaluated=False), {'private': 'binding'}
    def project(read, base, primary, kind, binding):
        calls.append((primary, kind, binding))
        return dict(state='checked', native_suspended=False,
                    overall_fixture_eligibility='not_evaluated')
    monkeypatch.setattr(source, 'context', context)
    monkeypatch.setattr(source, 'project', project)
    return m, ref, calls


def test_optional_projection_preserves_default_records_and_repeated_refs(bridge, fixture_world):
    _, ref, calls = fixture_world
    before = deepcopy(bridge.player_refs)
    default = bridge.get_player_bans(bridge.session, [ref, ref])
    optional = bridge.get_player_bans(bridge.session, [ref, ref], 'fixture')
    assert len(calls) == 1
    assert optional['players'][0] == optional['players'][1]
    assert optional['players'][0]['fixture_suspension']['native_suspended'] is False
    assert optional['fixture_context']['fixture_ref'] == 'fixture'
    assert optional['fixture_context']['as_of_date'] == optional['save']['current_date']
    assert optional['fixture_context']['full_outer_availability_evaluated'] is False
    assert optional['eligibility_state'] == 'not_evaluated'
    for result in (default, optional):
        result.pop('observed_at')
    optional.pop('fixture_context'); optional.pop('fixture_suspension_scope')
    for row in optional['players']:
        row.pop('fixture_suspension', None)
    assert default == optional and bridge.player_refs == before


@pytest.mark.parametrize('fault', ['missing', 'tables', 'catalog_identity', 'route', 'identity', 'slot'])
def test_unknown_or_changed_fixture_rejects_entire_optional_batch(bridge, fixture_world, fault):
    _, ref, calls = fixture_world
    if fault == 'missing':
        bridge.fixture_refs.clear()
    else:
        bridge.fixture_refs['fixture'][fault] = -1 if fault == 'slot' else ('changed',)
        if fault == 'slot':
            bridge.fixture_refs['fixture'][fault] = 1
    with pytest.raises(BridgeError, match='fixture|Fixture'):
        bridge.get_player_bans(bridge.session, [ref, ref], 'fixture')
    assert calls == [] and ref in bridge.player_refs


def test_late_fixture_date_drift_rejects_whole_batch(bridge, fixture_world, monkeypatch):
    m, ref, _ = fixture_world
    project = source.project
    def change_date(*args):
        result = project(*args)
        m['put'](0x99004C, bytes(4))
        return result
    monkeypatch.setattr(source, 'project', change_date)
    with pytest.raises(BridgeError, match='changed during read'):
        bridge.get_player_bans(bridge.session, [ref], 'fixture')
    assert ref in bridge.player_refs


@pytest.mark.parametrize('value', ['', True, 1, [], 'x'*257])
def test_invalid_fixture_option_rejected_before_session(value, bridge):
    with pytest.raises(BridgeError, match='fixture_ref'):
        bridge.get_player_bans('invalid', ['ref'], value)


def test_server_default_wrapper_still_calls_incumbent_signature(monkeypatch):
    from fm_live_mcp import server
    calls = []
    class RecordingBridge:
        def get_player_bans(self, *args):
            calls.append(args)
            return {'called': True}
    monkeypatch.setattr(server, 'bridge', RecordingBridge())
    assert server.fm_get_player_bans('session', ['ref']) == {'called': True}
    server.fm_get_player_bans('session', ['ref'], 'fixture')
    assert calls == [('session', ['ref']), ('session', ['ref'], 'fixture')]
