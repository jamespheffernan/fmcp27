"""Acceptance-order controls without attaching to a game or invoking helpers."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from fm_live_mcp import players, world
from test_club_debt_obligations import debt_memory
from test_club_finance import finance_memory
from test_database import database_memory
from test_players import memory
from test_world import world_memory


def collector_module():
    path = Path(__file__).parents[1] / 'evidence/obligations-20261109/collect.py'
    spec = importlib.util.spec_from_file_location('debt_collector_control', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('mutation', [None, 'public_save', 'final_current', 'source_pin_callback', 'source_pin_change'])
def test_final_acceptance_follows_all_callbacks_and_dependency_rechecks(debt_memory, monkeypatch, tmp_path, mutation):
    module = collector_module()
    m = debt_memory
    helper = tmp_path / 'helper'
    helper.write_bytes(b'No native helper is executed by this control.')
    output = tmp_path / 'receipt.json'
    identity = ('synthetic_game', 1)
    process = type('Process', (), {'pid': 42, 'started': 'synthetic'})()
    save = {'coaches': [{'team_address': m['team']}]}
    callbacks = []

    def mutate():
        m['put'](m['loan'], b'\x01')

    class FakeStream:
        def __init__(self, helper, pid):
            self.pid = pid
        def close(self):
            callbacks.append('stream_closed')

    class FakeBridge:
        def __init__(self, helper):
            import threading
            self.helper, self._reader = helper, None
            self.lock = threading.RLock()
            self.plugin_identity = (('synthetic',), 'uuid')
            self.currents = 0
        def attach(self):
            return {'session_id': 'synthetic'}
        def _current(self, session):
            self.currents += 1
            callbacks.append(f'current_{self.currents}')
            if self.currents == 3 and mutation == 'final_current':
                mutate()
            return process
        def _player_layout(self, process):
            return tuple(m['base'] + rva for rva in players.RVA)
        def _world_state(self, process, tables):
            return world.ReadSet(m['read']), save, identity
        def _select_coach(self, record, name):
            return save['coaches'][0]
        def _public_save(self, record):
            callbacks.append('public_save')
            if mutation == 'public_save':
                mutate()
            return {'name': 'synthetic_save'}
        def detach(self):
            callbacks.append('detached')
            return {'detached': True}

    pin_calls = []
    def pins(helper):
        pin_calls.append(1)
        if len(pin_calls) == 2 and mutation == 'source_pin_callback':
            mutate()
        return {'pin': 2 if len(pin_calls) == 2 and mutation == 'source_pin_change' else 1}

    monkeypatch.setattr(module, 'Bridge', FakeBridge)
    monkeypatch.setattr(module, 'ReadStream', FakeStream)
    monkeypatch.setattr(module, 'source_state', pins)
    monkeypatch.setattr(module.world, 'loaded', lambda read, base: (save, identity))
    monkeypatch.setattr(sys, 'argv', ['collect.py', '--helper', str(helper), '--output', str(output)])
    if mutation:
        with pytest.raises(ValueError, match='changed'):
            module.main()
    else:
        module.main()
    receipt = json.loads(output.read_text())
    assert receipt['state'] == ('rejected' if mutation else 'accepted')
    assert receipt['detach'] == {'detached': True}
    assert callbacks[-2:] == ['stream_closed', 'detached']
    assert callbacks.index('public_save') < callbacks.index('current_3')
    assert len(pin_calls) == 2
    assert ('projection' in receipt) == (mutation is None)
