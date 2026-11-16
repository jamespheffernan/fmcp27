"""Synthetic lifecycle controls; these are not fresh physical-player evidence."""
from contextlib import nullcontext
from unittest.mock import Mock
from types import MethodType, SimpleNamespace

from fm_live_mcp import current_player_physical as product, world
from fm_live_mcp import bridge as bridge_module


def setup(monkeypatch, *, public_change=None, current_change=None):
    value = bytearray([42])
    attempts = []
    calls = []

    def physical(address, size):
        assert (address, size) == (0x1000, 1)
        return bytes(value)

    bridge = Mock()
    bridge.lock = nullcontext()
    bridge._reader = None
    bridge._read_scope = MethodType(bridge_module.Bridge._read_scope, bridge)
    monkeypatch.setattr(bridge_module, 'ReadStream', Mock())
    bridge._player_layout.return_value = (product.players.RVA[0],)
    bridge._select_coach.return_value = {}

    def current(_):
        calls.append('current')
        if current_change:
            current_change(value, len(calls))
        return SimpleNamespace(pid=123)

    def state(*_):
        snapshot = world.ReadSet(physical)
        attempts.append(snapshot)
        return snapshot, {'current_date': '2030-11-26'}, None

    def public(save):
        if public_change:
            public_change(value, len(attempts))
        return dict(save)

    def inspect(read, *_):
        return {'state': 'synthetic_lifecycle_only', 'players': [{'value': read(0x1000, 1)[0]}]}

    bridge._current.side_effect = current
    bridge._world_state.side_effect = state
    bridge._public_save.side_effect = public
    monkeypatch.setattr(product, 'ReportReadSet', lambda read, observed: world.ReadSet(read))
    monkeypatch.setattr(product, '_inspect', inspect)
    return bridge, value, attempts


def test_public_save_change_retries_before_publication(monkeypatch):
    def change(value, attempt):
        if attempt == 1:
            value[0] += 1

    bridge, value, attempts = setup(monkeypatch, public_change=change)
    result = product.current_player_physical(bridge, 'synthetic')
    assert result['players'] == [{'value': 43}]
    assert value[0] == 43 and len(attempts) == 2


def test_repeated_final_callback_change_withholds_every_rejected_value(monkeypatch):
    bridge, value, attempts = setup(monkeypatch, public_change=lambda value, _: value.__setitem__(0, value[0] + 1))
    result = product.current_player_physical(bridge, 'synthetic')
    assert result['state'] == 'withheld'
    assert result['reason'] == 'physical_snapshot_changed_during_read'
    assert result['players'] is result['fixture'] is result['save'] is None
    assert value[0] == 44 and len(attempts) == 2


def test_last_lifetime_callback_change_retries_before_publication(monkeypatch):
    def change(value, call):
        if call == 3:
            value[0] += 1

    bridge, _, attempts = setup(monkeypatch, current_change=change)
    result = product.current_player_physical(bridge, 'synthetic')
    assert result['players'] == [{'value': 43}]
    assert len(attempts) == 2


def test_scope_exit_lifetime_callback_change_retries_before_publication(monkeypatch):
    def change(value, call):
        if call == 4:
            value[0] += 1

    bridge, _, attempts = setup(monkeypatch, current_change=change)
    result = product.current_player_physical(bridge, 'synthetic')
    assert result['players'] == [{'value': 43}]
    assert len(attempts) == 2
    assert bridge._reader is None


def test_repeated_scope_exit_mutation_withholds_and_closes_stream(monkeypatch):
    def change(value, call):
        if call in (4, 8):
            value[0] += 1

    bridge, _, attempts = setup(monkeypatch, current_change=change)
    result = product.current_player_physical(bridge, 'synthetic')
    assert result['state'] == 'withheld'
    assert result['players'] is result['fixture'] is result['save'] is None
    assert len(attempts) == 2 and bridge._reader is None
    assert bridge_module.ReadStream.return_value.close.call_count == 2


def test_stable_physical_source_keeps_single_attempt(monkeypatch):
    bridge, _, attempts = setup(monkeypatch)
    result = product.current_player_physical(bridge, 'synthetic')
    assert result['players'] == [{'value': 42}]
    assert len(attempts) == 1
