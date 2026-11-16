"""Synthetic public/lifetime controls around an authentic attacking fixture."""
from historical_match_identity_fixture import historical_team_identity_contract
from contextlib import nullcontext
from unittest.mock import Mock
from types import MethodType, SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP
from fm_live_mcp import current_match_report as report, current_match_tools as tools, world
from fm_live_mcp import bridge as bridge_module
from test_current_player_match_statistics import Original


def test_public_statistics_opt_in_is_strict_and_defaults_false(monkeypatch):
    mcp = FastMCP('statistics-contract')
    bridge = object()
    call = Mock(return_value={'synthetic_contract': True})
    monkeypatch.setattr(tools, 'current_match_report', call)
    tools.register_current_match_tools(mcp, bridge)
    tool = mcp._tool_manager.get_tool('fm_get_current_match')
    field = tool.parameters['properties']['include_player_statistics']
    assert field['type'] == 'boolean' and field['default'] is False
    tool.fn('sid')
    assert call.call_args.args == (bridge, 'sid', 'simulation', True, False, False, False)
    tool.fn('sid', include_player_statistics=True)
    assert call.call_args.args[-2:] == (False, True)
    for bad in (None, 0, 1, 'true', [], {}):
        with pytest.raises(ValueError, match='include_player_statistics must be a boolean'):
            report.current_match_report(object(), 'sid', include_player_statistics=bad)


def test_unbound_source_preserves_unknown_and_default_shape(monkeypatch):
    context = {'source_state': 'inactive', 'reason': 'no_client', 'physical_client_count': 0}
    monkeypatch.setattr(report.active_match_source, 'inspect_context', lambda *_args, **_kw: (context, None))
    result = report._inspect(Mock(), 0, '2030-11-26', 'client_snapshot', False, include_player_statistics=True)
    assert result['player_statistics'] == {'state': 'unavailable', 'reason': 'no_client', 'rows': None}
    default = report._inspect(Mock(), 0, '2030-11-26', 'client_snapshot', False)
    assert 'player_statistics' not in default and 'player_passing' not in default


def setup(monkeypatch, *, change=False, scope_change=False):
    original = Original()
    bridge = Mock()
    bridge.lock = nullcontext()
    bridge._reader = None
    bridge._read_scope = MethodType(bridge_module.Bridge._read_scope, bridge)
    monkeypatch.setattr(bridge_module, 'ReadStream', Mock())
    bridge._player_layout.return_value = [original.base + report.players.RVA[0]]
    bridge.plugin_identity = ('isolated-statistic-fixture', b'isolated runtime')
    bridge.world_identity = None
    bridge.session = 'synthetic'
    bridge.process = SimpleNamespace(pid=123)
    # This authentic scalar/counter fixture isolates report lifecycle and has no
    # runtime Mach-O. Actual Bridge/native verification has a separate strict rig.
    monkeypatch.setattr(report.players, 'verify_runtime', lambda *_: bridge._player_layout.return_value)
    attempts = []

    def state(*_):
        snapshot = world.ReadSet(original.read)
        attempts.append(snapshot)
        return snapshot, {'current_date': '2030-11-26'}, None

    def public_save(save):
        if change:
            at = int(original.numeric()['stats_private'], 16) + 0x90
            original.write(at, bytes([(original.read(at, 1)[0] + 1) % 256]))
        return save

    calls = []
    def current(_):
        calls.append(None)
        if scope_change and len(calls) in (4, 10):
            at = int(original.numeric()['stats_private'], 16) + 0x90
            original.write(at, bytes([(original.read(at, 1)[0] + 1) % 256]))
        return SimpleNamespace(pid=123)

    def projection(read, base, _date, _scope, _tactics, _shots, passing, statistics):
        assert passing is False and statistics is True
        from fm_live_mcp.current_player_match_statistics import inspect
        return {'state': 'synthetic_context_only', 'player_statistics': inspect(read, base, original.engine, expected_match_unique_id=original.uid)}

    bridge._world_state.side_effect = state
    bridge._public_save.side_effect = public_save
    bridge._current.side_effect = current
    monkeypatch.setattr(report, 'ReportReadSet', lambda read, observed: world.ReadSet(read))
    monkeypatch.setattr(report, '_inspect', projection)
    return original, bridge, attempts


def test_authentic_projection_survives_unchanged_lifetime_callbacks(monkeypatch):
    _, bridge, attempts = setup(monkeypatch)
    packet = report.current_match_report(bridge, 'synthetic', include_player_statistics=True)
    assert packet['player_statistics']['coverage']['available_statistic_rows'] == 37
    assert packet['player_statistics']['native_timestamp_association'] is False
    assert len(attempts) == 2


def test_last_callback_mutation_refuses_both_attempts(monkeypatch):
    _, bridge, attempts = setup(monkeypatch, change=True)
    with pytest.raises(ValueError, match='Game state changed during read; retry'):
        report.current_match_report(bridge, 'synthetic', include_player_statistics=True)
    assert len(attempts) == 4


def test_real_scope_exit_callback_mutation_refuses_and_closes(monkeypatch):
    _, bridge, attempts = setup(monkeypatch, scope_change=True)
    with pytest.raises(ValueError, match='Game state changed during read; retry'):
        report.current_match_report(bridge, 'synthetic', include_player_statistics=True)
    assert len(attempts) == 4 and bridge._reader is None
    assert bridge_module.ReadStream.return_value.close.call_count == 2
