"""No-persistence query controls; saved bytes and isolated Bridge scopes only."""
from historical_match_identity_fixture import historical_team_identity_contract
import asyncio
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock
import os

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from fm_live_mcp import bridge as bridge_module, world
from fm_live_mcp import current_match_report as report, current_match_tools as tools
from fm_live_mcp import match_period_observations as periods
from fm_live_mcp import spatial_period_observations as spatial, spatial_period_witness as witness

BAD = [None, 0, 1, -1, 0.0, 1.0, 'true', 'false', [], {}]
DISABLED = {'state': 'not_captured', 'reason': 'disabled_by_request'}


def contract(monkeypatch):
    mcp = FastMCP('no-persistence-contract')
    bridge = Mock()
    call = Mock(return_value={'contract_only': True})
    monkeypatch.setattr(tools, 'current_match_report', call)
    tools.register_current_match_tools(mcp, bridge)
    return mcp, bridge, call


def test_schema_keeps_defaults_annotation_and_existing_positional_route(monkeypatch):
    mcp, bridge, call = contract(monkeypatch)
    tool = mcp._tool_manager.get_tool('fm_get_current_match')
    assert tool.parameters['properties']['persist_host_observations'] == {
        'default': True, 'title': 'Persist Host Observations', 'type': 'boolean'}
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is False
    tool.fn('sid')
    assert call.call_args.args == (bridge, 'sid', 'simulation', True, False, False, False)
    assert call.call_args.kwargs == {'persist_host_observations': True}
    tool.fn('sid', include_player_statistics=True, persist_host_observations=False)
    assert call.call_args.args[-1] is True
    assert call.call_args.kwargs == {'persist_host_observations': False}
    assert 'persist_host_observations=false' in tool.description


@pytest.mark.parametrize('value', [True, False])
def test_actual_mcp_accepts_only_boolean_values(monkeypatch, value):
    mcp, bridge, call = contract(monkeypatch)
    asyncio.run(mcp._tool_manager.call_tool('fm_get_current_match', {
        'session_id': 'sid', 'persist_host_observations': value}))
    assert call.call_args.kwargs['persist_host_observations'] is value


@pytest.mark.parametrize('value', BAD)
def test_malformed_flag_refused_by_mcp_and_report_before_bridge_io(monkeypatch, value):
    mcp, bridge, call = contract(monkeypatch)
    with pytest.raises(ToolError):
        asyncio.run(mcp._tool_manager.call_tool('fm_get_current_match', {
            'session_id': 'sid', 'persist_host_observations': value}))
    call.assert_not_called()
    with pytest.raises(ValueError, match='persist_host_observations must be a boolean'):
        report.current_match_report(bridge, 'sid', persist_host_observations=value)
    assert not bridge.mock_calls


def setup(monkeypatch, *, late=False, read_error=False):
    """Real scope/seal over synthetic context and a deterministic byte journal.

    This persistence/lifecycle Rig has no Mach-O image. Only verify_runtime is
    stubbed locally; RuntimeRig's separate tests exercise the real UUID/RTTI
    guards. Both publication journals and all lifetime callbacks still run.
    """
    bridge = Mock()
    bridge.lock = nullcontext()
    bridge.session = 'sid'
    bridge.process = SimpleNamespace(pid=7, started='synthetic-start',
        executable_stamp='synthetic-executable', version='synthetic-build')
    bridge.world_identity = ('synthetic-world', 1)
    bridge.plugin_identity = (('synthetic-plugin', 1, 2, 3, 4), b'\x01' * 16)
    bridge._reader = None
    bridge._read_scope = MethodType(bridge_module.Bridge._read_scope, bridge)
    stream = Mock()
    streams = Mock(return_value=stream)
    monkeypatch.setattr(bridge_module, 'ReadStream', streams)
    bridge._player_layout.return_value = [100]
    def synthetic_runtime_binding(_read, base, expected_uuid):
        assert base == bridge._player_layout.return_value[0] - report.players.RVA[0]
        assert expected_uuid == bridge.plugin_identity[1]
        return bridge._player_layout.return_value
    monkeypatch.setattr(report.players, 'verify_runtime', synthetic_runtime_binding)
    memory = {0x1000: 7}
    scopes = []
    initial_journals = set()
    def read(at, n):
        if read_error: raise OSError('isolated transport failure')
        return bytes(memory[at+i] for i in range(n))
    def state(*_):
        snapshot = world.ReadSet(read)
        # Keep this list's original meaning: one initial journal per native
        # scope/attempt. The seal now also obtains an independent final journal.
        if streams.call_count not in initial_journals:
            initial_journals.add(streams.call_count)
            scopes.append(snapshot)
        return snapshot, {'current_date': '2030-11-30'}, bridge.world_identity
    bridge._world_state.side_effect = state
    bridge._public_save.side_effect = deepcopy
    calls = []
    def current(_):
        calls.append(None)
        if late and len(calls) % 4 == 0: memory[0x1000] ^= 1
        return bridge.process
    bridge._current.side_effect = current
    monkeypatch.setattr(report, 'ReportReadSet', lambda read, observed: world.ReadSet(read))
    payload = {'state': 'available_fixture_bound', 'fixture': {'synthetic_context': True},
        'tactics': {'sides': ['synthetic plans']}, 'chance_breakdown': {'shots': ['synthetic events']},
        'player_statistics': {'row': ['synthetic values']}, 'player_passing': {'row': ['synthetic passing']},
        '_period_capture_candidate': {'bound': 'bound', 'split': 'split', 'source': 'source'},
        '_spatial_period_capture_candidate': {'private': 'spatial'}}
    def inspect(snapshot, *_args):
        snapshot(0x1000, 1)
        return deepcopy(payload)
    projection = Mock(side_effect=inspect)
    monkeypatch.setattr(report, '_inspect', projection)
    class Clock:
        @staticmethod
        def now(_):return datetime(2026, 11, 9, tzinfo=timezone.utc)
    monkeypatch.setattr(report, 'datetime', Clock)
    return bridge, stream, scopes, projection


def forbid_persistence(monkeypatch):
    def forbidden(*_a, **_kw):raise AssertionError('Host persistence path entered')
    for module, names in [(periods, ['process_epoch', 'make_observation', 'ObservationStore']),
                          (witness, ['capture_terminal_source', 'make_observation']),
                          (spatial, ['SpatialPeriodStore'])]:
        for name in names:monkeypatch.setattr(module, name, forbidden)
    # Guards the real application filesystem seams too, not only store mocks.
    for name in ['mkdir', 'write_text', 'write_bytes']:
        monkeypatch.setattr(Path, name, forbidden)
    original_open = os.open
    def read_only_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            forbidden()
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', read_only_open)


@pytest.mark.parametrize('flags', list(product([False, True], repeat=4)))
def test_false_skips_all_persistence_paths_for_every_projection_combination(monkeypatch, flags):
    bridge, stream, scopes, projection = setup(monkeypatch)
    forbid_persistence(monkeypatch)
    out = report.current_match_report(bridge, 'sid', include_tactics=flags[0],
        include_shot_events=flags[1], include_player_passing=flags[2], include_player_statistics=flags[3],
        persist_host_observations=False)
    assert out['host_period_capture'] == out['host_spatial_period_capture'] == DISABLED
    assert out['tactics'] == {'sides': ['synthetic plans']}
    assert out['chance_breakdown'] == {'shots': ['synthetic events']}
    assert out['player_statistics'] == {'row': ['synthetic values']}
    assert out['player_passing'] == {'row': ['synthetic passing']}
    assert projection.call_args.args[-4:] == flags
    assert all(not key.startswith('_') for key in out)
    assert bridge._reader is None and stream.close.call_count == 1
    assert len(scopes) == 1


def test_default_and_explicit_true_are_legacy_exact_and_false_differs_only_in_capture_metadata(monkeypatch):
    bridge, stream, scopes, _ = setup(monkeypatch)
    capture = Mock(return_value={'spatial': 'source'})
    monkeypatch.setattr(witness, 'capture_terminal_source', capture)
    monkeypatch.setattr(periods, 'process_epoch', Mock(return_value='epoch'))
    make_period = Mock(return_value={'observation': 'period'})
    make_spatial = Mock(return_value={'observation': 'spatial'})
    monkeypatch.setattr(periods, 'make_observation', make_period)
    monkeypatch.setattr(witness, 'make_observation', make_spatial)
    pstore, sstore = Mock(), Mock()
    def save_period(_):
        assert bridge._reader is None
        return {'state': 'captured', 'id': 'period'}
    def save_spatial(_):
        assert bridge._reader is None
        return {'state': 'captured', 'id': 'spatial'}
    pstore.save.side_effect=save_period;sstore.save.side_effect=save_spatial
    monkeypatch.setattr(periods, 'ObservationStore', Mock(return_value=pstore))
    monkeypatch.setattr(spatial, 'SpatialPeriodStore', Mock(return_value=sstore))
    options={'include_player_statistics': True, 'include_shot_events': True}
    default = report.current_match_report(bridge, 'sid', **options)
    explicit = report.current_match_report(bridge, 'sid', **options, persist_host_observations=True)
    disabled = report.current_match_report(bridge, 'sid', **options, persist_host_observations=False)
    assert default == explicit
    assert pstore.save.call_count == sstore.save.call_count == capture.call_count == 2
    assert make_period.call_count == make_spatial.call_count == 2
    assert {k:v for k,v in default.items()if not k.startswith('host_')} == {k:v for k,v in disabled.items()if not k.startswith('host_')}
    assert disabled['host_period_capture'] == disabled['host_spatial_period_capture'] == DISABLED
    assert stream.close.call_count == 3


@pytest.mark.parametrize('failure', ['late', 'read'])
def test_false_keeps_final_consistency_refusal_and_stream_cleanup(monkeypatch, failure):
    bridge, stream, scopes, _ = setup(monkeypatch, late=failure=='late', read_error=failure=='read')
    forbid_persistence(monkeypatch)
    with pytest.raises(ValueError if failure=='late'else OSError, match='Game state changed|transport failure'):
        report.current_match_report(bridge, 'sid', include_player_statistics=True, persist_host_observations=False)
    assert bridge._reader is None
    assert stream.close.call_count == (2 if failure=='late'else 1)


def test_false_retains_actual_saved_33_field_projection_and_qualifiers(monkeypatch):
    from test_current_player_statistics33_integration import Joint33
    from fm_live_mcp import current_player_match_statistic_groups as statistics
    fixture = Joint33()
    bridge, stream, scopes, _ = setup(monkeypatch)
    bridge._player_layout.return_value = [fixture.base+report.players.RVA[0]]
    bridge._world_state.side_effect = lambda *_: (world.ReadSet(fixture.read), {'current_date': '2030-11-09'}, bridge.world_identity)
    def inspect(read, base, *_):
        return {'player_statistics': statistics.inspect(read, base, fixture.engine, expected_match_unique_id=fixture.uid)}
    monkeypatch.setattr(report, '_inspect', inspect)
    forbid_persistence(monkeypatch)
    out = report.current_match_report(bridge, 'sid', include_player_statistics=True, persist_host_observations=False)
    assert out['player_statistics'] == fixture.packet['candidate_projection']
    assert len(out['player_statistics']['field_qualifiers']) == 33
    assert stream.close.call_count == 1


@pytest.mark.parametrize('failure', [KeyboardInterrupt, bridge_module.BridgeError])
def test_false_closes_scope_on_cancellation_or_lifetime_error(monkeypatch, failure):
    bridge, stream, scopes, projection = setup(monkeypatch)
    forbid_persistence(monkeypatch)
    projection.side_effect = failure('isolated refusal')
    with pytest.raises(failure):
        report.current_match_report(bridge, 'sid', include_player_statistics=True, persist_host_observations=False)
    assert bridge._reader is None and stream.close.call_count == 1


def test_false_closes_after_real_scope_final_lifetime_callback_refuses(monkeypatch):
    bridge, stream, scopes, _ = setup(monkeypatch)
    forbid_persistence(monkeypatch)
    calls = []
    def current(_):
        calls.append(None)
        if len(calls) == 4:
            raise bridge_module.BridgeError('isolated final process identity change')
        return bridge.process
    bridge._current.side_effect = current
    with pytest.raises(bridge_module.BridgeError, match='final process identity change'):
        report.current_match_report(bridge, 'sid', include_player_statistics=True, persist_host_observations=False)
    assert len(calls) == 4 and bridge._reader is None and stream.close.call_count == 1
