"""Actual Bridge roster/layout/world/physical publication controls; no live reads."""
from copy import deepcopy
import asyncio
import hashlib
from pathlib import Path
import struct
import types

import pytest

from fm_live_mcp import bridge as bridge_module, players, world
from fm_live_mcp.bridge import BridgeError
from runtime_publication_fixture import RuntimeRig
from test_bridge import bridge
from test_database import database_memory
from test_players import memory
from test_world import world_memory
from test_virtual import virtual_memory
from test_virtual_identity import compact_virtual_memory


def frozen():
    path = Path(__file__).parent / 'fixtures/core_rosters158.py.txt'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == '15dde0ccbcd818535fa241e68cd63a5eccdcd5bfe0ab73a9bb6fc8b74d7a7f9c'
    module = types.ModuleType('fm_live_mcp._core_rosters158')
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


@pytest.fixture
def roster_rig(database_memory, bridge, monkeypatch, tmp_path):
    m = database_memory
    m['vec'](m['team'] + 0x38, [0x1000])
    rig = RuntimeRig(m, bridge, monkeypatch, tmp_path)
    bridge.team_refs['team-input'] = {'address': m['team'], 'identity': m['read'](m['team'] + 8, 12),
        'tables': m['tables'], 'club_address': m['club'], 'label': 'Senior',
        'club_database_index': None, 'club_identity': None}
    return rig


@pytest.fixture
def cold_roster_rig(compact_virtual_memory, bridge, monkeypatch, tmp_path):
    m = compact_virtual_memory
    m['vec'](m['team'] + 0x38, [m['compact']])
    rig = RuntimeRig(m, bridge, monkeypatch, tmp_path)
    bridge.team_refs['team-input'] = {'address': m['team'], 'identity': m['read'](m['team'] + 8, 12),
        'tables': m['tables'], 'club_address': m['club'], 'label': 'Senior',
        'club_database_index': None, 'club_identity': None}
    return rig


def invoke(rig, method, old=False, **kwargs):
    function = getattr(frozen(), method) if old else getattr(type(rig.bridge), method)
    args = [rig.bridge, rig.bridge.session]
    if method == 'get_team_squad': args.append('team-input')
    return function(*args, **kwargs)


METHODS = ['get_managed_squad', 'get_team_squad', 'get_club_squads']


@pytest.mark.parametrize('method', METHODS)
@pytest.mark.parametrize('late', ['body_current', 'public_save', 'scope_current'])
def test_exact158_old_roster_membership_escape(roster_rig, method, late):
    rig = roster_rig
    def change(r):r.m['vec'](r.m['team'] + 0x38, [])
    if late == 'public_save': rig.public_hook = change
    else: rig.hooks[3 if late == 'body_current' else 4] = change
    result = invoke(rig, method, old=True)
    assert (result['squads'][0]['count'] if method == 'get_club_squads' else result['count']) == 1
    assert world.vector(rig.read, rig.m['team'] + 0x38, 256) == ()
    rig.closed()


@pytest.mark.parametrize('method', METHODS)
@pytest.mark.parametrize('operand', ['uuid', 'rtti_displacement', 'rtti_name'])
def test_exact158_old_roster_runtime_escape(roster_rig, method, operand):
    rig = roster_rig
    rig.hooks[4] = lambda r:r.mutate(operand)
    invoke(rig, method, old=True)
    with pytest.raises(ValueError, match='UUID differs|displacement changed|runtime type changed'):
        players.verify_runtime(rig.read, rig.m['base'], rig.uuid)
    rig.closed()


@pytest.mark.parametrize('method', METHODS)
@pytest.mark.parametrize('late', ['scope_current', 'public_save', 'last_current'])
def test_membership_drift_refuses_without_publishing_refs(roster_rig, method, late):
    rig = roster_rig
    before_players, before_teams = deepcopy(rig.bridge.player_refs), deepcopy(rig.bridge.team_refs)
    def change(r):r.m['vec'](r.m['team'] + 0x38, [])
    if late == 'public_save': rig.public_hook = change
    else: rig.hooks[3 if late == 'scope_current' else 5] = change
    with pytest.raises(BridgeError, match='changed|rejected'):
        invoke(rig, method)
    assert rig.bridge.player_refs == before_players
    assert rig.bridge.team_refs == before_teams
    rig.closed()


@pytest.mark.parametrize('method', METHODS)
@pytest.mark.parametrize('operand', ['uuid', 'rtti_displacement', 'rtti_name'])
def test_runtime_last_callback_drift_refuses(roster_rig, method, operand):
    rig = roster_rig
    rig.hooks[5] = lambda r:r.mutate(operand)
    with pytest.raises(BridgeError, match='changed|rejected'):
        invoke(rig, method)
    rig.closed()


@pytest.mark.parametrize('method', METHODS)
def test_clean_payload_and_binding_shapes_equal158_except_fresh_refs_and_time(roster_rig, method):
    rig = roster_rig
    expected = invoke(rig, method, old=True)
    old_refs = deepcopy(rig.bridge.team_refs if method == 'get_club_squads' else rig.bridge.player_refs)
    rig.bridge.player_refs.clear()
    if method == 'get_club_squads':rig.bridge.team_refs.pop(expected['squads'][0]['team_ref'])
    rig.reset_trace()
    actual = invoke(rig, method)
    key, refkey = ('squads', 'team_ref') if method == 'get_club_squads' else ('players', 'player_ref')
    actual_refs = rig.bridge.team_refs if method == 'get_club_squads' else rig.bridge.player_refs
    for before, after in zip(expected[key], actual[key], strict=True):
        assert old_refs[before.pop(refkey)] == actual_refs[after.pop(refkey)]
    assert expected.pop('observed_at') and actual.pop('observed_at')
    assert actual == expected
    assert len(rig.read_sets) == 2
    assert all((rig.m['base'], 16384) in read.observed for read in rig.read_sets)
    last = max(i for i,e in enumerate(rig.events) if e[0] not in ('physical', 'close'))
    assert all(e[0] in ('physical','close') for e in rig.events[last+1:])
    rig.closed()


@pytest.mark.parametrize('method', METHODS)
def test_stream_closes_before_any_new_reference_is_published(roster_rig, method, monkeypatch):
    rig = roster_rig
    players_before, teams_before = deepcopy(rig.bridge.player_refs), deepcopy(rig.bridge.team_refs)
    stream = bridge_module.ReadStream
    original = stream.close
    def close(instance):
        assert rig.bridge.player_refs == players_before
        assert rig.bridge.team_refs == teams_before
        original(instance)
    monkeypatch.setattr(stream, 'close', close)
    invoke(rig, method)
    rig.closed()


@pytest.mark.parametrize('method', METHODS)
def test_close_failure_publishes_no_refs(roster_rig, method, monkeypatch):
    rig = roster_rig
    before_players, before_teams = deepcopy(rig.bridge.player_refs), deepcopy(rig.bridge.team_refs)
    stream = bridge_module.ReadStream
    original = stream.close
    def close(instance):
        original(instance)
        raise OSError('controlled close failure')
    monkeypatch.setattr(stream, 'close', close)
    with pytest.raises(OSError, match='close failure'):invoke(rig, method)
    assert rig.bridge.player_refs == before_players and rig.bridge.team_refs == before_teams
    rig.closed()


@pytest.mark.parametrize('method', METHODS[:2])
@pytest.mark.parametrize('options', [{}, {'include_clubs': True}, {'include_profile': True},
                                   {'include_health': True}, {'include_clubs': True, 'include_profile': True, 'include_health': True}])
def test_cold_available_payload_and_identity_only_defaults_equal158(cold_roster_rig, method, options):
    rig = cold_roster_rig
    expected = invoke(rig, method, old=True, profile_policy='available', **options)
    rig.bridge.player_refs.clear()
    rig.reset_trace()
    actual = invoke(rig, method, profile_policy='available', **options)
    expected['players'][0].pop('player_ref');actual['players'][0].pop('player_ref')
    expected.pop('observed_at');actual.pop('observed_at')
    assert actual == expected
    assert actual['players'][0]['profile_state'] == 'identity_only'
    rig.closed()


@pytest.mark.parametrize('method', METHODS)
@pytest.mark.parametrize('error', [EOFError('controlled EOF'), TimeoutError('controlled timeout'), asyncio.CancelledError()])
def test_final_physical_fence_failures_publish_no_new_refs(roster_rig, method, error, monkeypatch):
    rig = roster_rig
    before_players, before_teams = deepcopy(rig.bridge.player_refs), deepcopy(rig.bridge.team_refs)
    original = rig.read
    def read(address, length):
        if rig.calls >= 5:raise error
        return original(address, length)
    monkeypatch.setattr(rig, 'read', read)
    with pytest.raises(type(error)):invoke(rig, method)
    assert rig.bridge.player_refs == before_players and rig.bridge.team_refs == before_teams
    rig.closed()


@pytest.mark.parametrize('replacement', [False, True])
def test_final_team_reference_mutation_and_registry_replacement_refuse(roster_rig, replacement):
    rig = roster_rig
    def change(r):
        if replacement:r.bridge.team_refs = {}
        else:r.bridge.team_refs['team-input']['label'] = 'Changed'
    rig.hooks[5] = change
    with pytest.raises(BridgeError, match='reference binding changed'):
        invoke(rig, 'get_team_squad')
    assert rig.bridge.player_refs == {}
    rig.closed()


@pytest.mark.parametrize('method', METHODS)
def test_extra_final_context_operands_are_fenced(roster_rig, method):
    rig = roster_rig
    at = 0x700018
    rig.put(at, b'\0' * 4)
    rig.world_hook = lambda r, count, read:read(at, 4) if count == 2 else None
    rig.hooks[5] = lambda r:r.put(at, b'\1\0\0\0')
    with pytest.raises(BridgeError, match='changed during read'):
        invoke(rig, method)
    assert (at, 4) in rig.read_sets[1].observed
    rig.closed()


@pytest.mark.parametrize('replacement', [False, True])
def test_club_reference_mutation_and_replacement_do_not_publish_or_restore_refs(roster_rig, replacement):
    rig = roster_rig
    rig.bridge.club_refs['club-input'] = {'address': rig.m['club'], 'tables': rig.m['tables'],
        'database_index': 0, 'identity': world.club(rig.read, rig.m['base'], rig.m['club'])[1]}
    before = deepcopy(rig.bridge.team_refs)
    def change(r):
        if replacement:r.bridge.club_refs = {}
        else:r.bridge.club_refs['club-input']['identity'] = ('changed',)
    rig.hooks[5] = change
    with pytest.raises(BridgeError, match='reference binding changed'):
        invoke(rig, 'get_club_squads', club_ref='club-input')
    assert rig.bridge.team_refs == before
    if replacement:assert rig.bridge.club_refs == {}
    else:assert rig.bridge.club_refs['club-input']['identity'] == ('changed',)
    rig.closed()


@pytest.mark.parametrize('method', METHODS)
def test_reference_allocation_failure_after_close_preserves_registry(roster_rig, method, monkeypatch):
    rig = roster_rig
    before_players, before_teams = deepcopy(rig.bridge.player_refs), deepcopy(rig.bridge.team_refs)
    # A complete second roster/squad entry makes failure occur after one token.
    if method == 'get_club_squads':
        team = rig.m['allocate'](0xB8)
        rig.put(team, rig.read(rig.m['team'], 0xB8))
        rig.m['vec'](rig.m['club'] + 0x18, [rig.m['team'], team])
    else:
        player = rig.m['allocate'](players.SIZE)
        rig.put(player, rig.read(0x1000, players.SIZE))
        rig.m['vec'](rig.m['team'] + 0x38, [0x1000, player])
    calls = 0
    def token(*args):
        nonlocal calls
        assert rig.bridge._reader is None and rig.events[-1][0] == 'close'
        calls += 1
        if calls == 2:raise RuntimeError('controlled token failure')
        return 'staged-only'
    monkeypatch.setattr(bridge_module.secrets, 'token_urlsafe', token)
    with pytest.raises(RuntimeError, match='token failure'):invoke(rig, method)
    assert calls == 2
    assert rig.bridge.player_refs == before_players and rig.bridge.team_refs == before_teams
    rig.closed()


@pytest.mark.parametrize('method', METHODS)
def test_cancellation_at_final_callback_closes_without_publication(roster_rig, method):
    rig = roster_rig
    before = deepcopy(rig.bridge.team_refs)
    def cancel(r):raise asyncio.CancelledError()
    rig.hooks[5] = cancel
    with pytest.raises(asyncio.CancelledError):invoke(rig, method)
    assert rig.bridge.player_refs == {} and rig.bridge.team_refs == before
    rig.closed()
