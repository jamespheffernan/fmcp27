"""Causal retained publication checks over actual Bridge scope and world.ReadSet."""
from contextlib import ExitStack
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import struct
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from fm_live_mcp import bridge as bm, live_retained_shots, players, world

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'evidence/retained-shot-seal-next/baseline_live_retained_shots.py'


def load_module(path):
    spec = importlib.util.spec_from_file_location('fm_live_mcp._retained_seal_control', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


query = load_module(os.environ['FM_RETAINED_SEAL_MODULE']) if os.environ.get('FM_RETAINED_SEAL_MODULE') else live_retained_shots


class Rig:
    base, human, owner, cbe, shot = 0x100000000, 0x10000, 0x20000, 0x30000, 0x40000

    def __init__(self, module=query, *, current_hook=None, layout_hook=None, world_hook=None,
                 detail_hook=None, final_read_error=None, close_error=None, unavailable=None):
        self.module = module
        self.memory, self.calls, self.read_sets, self.closed, self.events = {}, [], [], [], []
        self.read_count, self.world_count, self.layout_count, self.detail_count = 0, 0, 0, 0
        self.current_hook, self.layout_hook, self.world_hook = current_hook, layout_hook, world_hook
        self.detail_hook, self.final_read_error, self.close_error = detail_hook, final_read_error, close_error
        self.uuid = b'seal UUID guard!'
        self.put(self.base, bytes(16384))
        self.put(self.base, struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 6, 1, 24, 0, 0)
            + struct.pack('<II', 0x1b, 24) + self.uuid)
        for index, (rva, displacement, name) in enumerate(zip(players.RVA, (0, 0, -0x388),
                (b'N2db13ACTUAL_PLAYERE', b'N2db12PLAYING_DATAE', b'N2db13ACTUAL_PLAYERE'))):
            info = 0x90000 + index * 0x100; text = info + 0x20
            self.put(self.base + rva - 16, struct.pack('<qQ', displacement, info))
            self.put(info + 8, struct.pack('<Q', text)); self.put(text, name + b'\0')
        for rva, raw in module.NATIVE_SPANS:
            self.put(self.base + rva, raw)
        for offset in (0x188, 0x1a0, 0x170, 0x1b8):
            self.put(self.human + offset, bytes(24))
        self.put(self.human + 0x188, struct.pack('<QQQ', 0x50000, 0x50008, 0x50008))
        self.put(0x50000, struct.pack('<Q', self.owner))
        self.put(self.owner, struct.pack('<IIQII', 0, (2030 << 16) | 334,
            0 if unavailable == 'null' else self.cbe, 688, 0))
        if unavailable == 'absent':
            for offset in (0x188, 0x1a0, 0x170, 0x1b8):
                self.put(self.human + offset, bytes(24))
        self.put(self.cbe + 0x100, struct.pack('<ff', 34., 52.5))
        self.put(self.cbe + 8, bytes(24))
        self.put(self.cbe + 0x20, struct.pack('<QQQ', self.shot, self.shot + 48, self.shot + 48))
        self.put(self.cbe + 0x38, bytes(24))
        record = bytearray(48); struct.pack_into('<f', record, 32, .5); self.put(self.shot, record)
        self.put(0x60000 + 0x58, struct.pack('<i', 138871))
        self.put(0x70000, struct.pack('<i', 1))
        self.fixture = {'date': '2030-11-30', 'home_team': {'native_id': 688}, 'away_team': {'native_id': 676}}
        self.native_fixture = deepcopy(self.fixture)
        self.tables = tuple(self.base + rva for rva in players.RVA)
        self.process = SimpleNamespace(pid=1)
        self.save = {'coaches': [{'name': 'Controlled'}], 'current_date': '2030-12-01'}
        self.identity = {'world': 'controlled'}
        self.bridge = SimpleNamespace(lock=threading.RLock(), _reader=None, helper='controlled',
            session='s', process=self.process, plugin_identity=(('controlled', 1, 1, 1, 1), self.uuid), world_identity=deepcopy(self.identity),
            _current=self.current, _player_layout=self.layout, _world_state=self.world,
            fixture_refs={'ref': {'tables': self.tables, 'catalog_identity': 'catalog', 'year': 2030,
                'day': 334, 'group': 1, 'route': 'route', 'slot': 0, 'address': 0x60000, 'identity': 'fixture'}})
        self.bridge._read_scope = bm.Bridge._read_scope.__get__(self.bridge)

    def put(self, at, raw):
        self.memory.update({at + i: value for i, value in enumerate(raw)})

    def read(self, at, size):
        self.events.append('read')
        if self.final_read_error is not None and len(self.calls) >= 6:
            raise self.final_read_error
        return bytes(self.memory[at + i] for i in range(size))

    def current(self, sid):
        self.events.append('current')
        self.calls.append(sid)
        if self.current_hook:
            self.current_hook(self, len(self.calls))
        return self.bridge.process

    def layout(self, process):
        self.events.append('layout'); self.layout_count += 1
        if self.layout_hook:
            self.layout_hook(self, self.layout_count)
        return self.tables

    def world(self, process, tables):
        self.events.append('world'); self.world_count += 1
        read = world.ReadSet(self.read); read(0x70000, 4)
        self.read_sets.append(read)
        if self.world_hook:
            self.world_hook(self, self.world_count)
        return read, self.save, deepcopy(self.identity)

    def detail(self, *args):
        self.events.append('detail'); self.detail_count += 1
        if self.detail_hook:
            self.detail_hook(self, self.detail_count)
        return (self.native_fixture,)

    def run(self):
        rig = self
        class Stream:
            def __init__(self, *args):
                self.pid = 1
            def close(self):
                rig.events.append('close'); rig.closed.append(True)
                if rig.close_error:
                    raise rig.close_error
        try:
            with ExitStack() as stack:
                stack.enter_context(patch.object(bm, 'ReadStream', Stream))
                stack.enter_context(patch.object(self.module.fixtures, 'catalog', lambda *_: (None, {2030: 'year'}, 'catalog')))
                stack.enter_context(patch.object(self.module.fixtures, 'bucket', lambda *_: ([0x60000], 'route')))
                stack.enter_context(patch.object(self.module.fixtures, 'record', lambda *_: {'identity': 'fixture', 'kind': 'result'}))
                stack.enter_context(patch.object(self.module.fixtures, 'detail', self.detail))
                stack.enter_context(patch.object(self.module.prepared_tactics_source, '_team_and_human', lambda *_: (None, self.human)))
                return self.module.capture_source(self.bridge, 's', 'ref', 138871, self.fixture)
        finally:
            assert self.closed == [True] and self.bridge._reader is None


@pytest.mark.parametrize('late', [3, 4, 5, 6])
def test_late_current_cannot_publish_consumed_shot(late):
    rig = Rig(current_hook=lambda r, count: r.put(r.shot + 32, struct.pack('<f', .25)) if count == late else None)
    with pytest.raises(ValueError, match='changed'):
        rig.run()


@pytest.mark.parametrize('state', [None, 'absent', 'null'])
def test_clean_available_and_unavailable_payloads_equal_frozen_baseline(state):
    old = Rig(load_module(BASELINE), unavailable=state).run()
    rig = Rig(unavailable=state)
    assert rig.run() == old
    assert rig.events[-1] == 'close'
    # The last semantic callback precedes the final physical reads and close.
    last_callback = max(i for i, event in enumerate(rig.events) if event not in ('read', 'close'))
    assert all(event in ('read', 'close') for event in rig.events[last_callback + 1:])
    assert 'read' in rig.events[last_callback + 1:]


@pytest.mark.parametrize('change', ['cache_mutation', 'cache_replacement', 'session', 'process', 'plugin', 'world'])
def test_final_callback_cannot_change_reference_or_context(change):
    def alter(rig, count):
        if count != 6:
            return
        if change == 'cache_mutation': rig.bridge.fixture_refs['ref']['slot'] = 1
        elif change == 'cache_replacement': rig.bridge.fixture_refs['ref'] = {'expired': True}
        elif change == 'session': rig.bridge.session = 'other'
        elif change == 'process': rig.bridge.process = SimpleNamespace(pid=2)
        elif change == 'plugin': rig.bridge.plugin_identity = (('changed', 1, 1, 1, 1), rig.uuid)
        elif change == 'world': rig.bridge.world_identity['world'] = 'changed'
    with pytest.raises(ValueError, match='changed'):
        Rig(current_hook=alter).run()


@pytest.mark.parametrize('change', ['date_alias', 'coach_alias', 'world_identity', 'context_byte_alias'])
def test_final_world_context_cannot_change_initial_save_or_consumed_bytes(change):
    def alter(rig, count):
        if count != 2:
            return
        if change == 'date_alias': rig.save['current_date'] = '2030-12-02'
        elif change == 'coach_alias': rig.save['coaches'][0]['name'] = 'Other'
        elif change == 'world_identity': rig.identity['world'] = 'Other'
        elif change == 'context_byte_alias': rig.put(0x70000, struct.pack('<i', 2))
    with pytest.raises(ValueError, match='changed'):
        Rig(world_hook=alter).run()


@pytest.mark.parametrize('change', ['shot', 'native', 'owner', 'fixture_input_alias', 'fixture_native'])
def test_final_fixture_and_layout_callbacks_precede_complete_fence(change):
    def alter(rig, count):
        if count != 2:
            return
        if change == 'shot': rig.put(rig.shot + 32, struct.pack('<f', .25))
        elif change == 'native':
            rva, raw = rig.module.NATIVE_SPANS[0]; rig.put(rig.base + rva, bytes([raw[0] ^ 1]) + raw[1:])
        elif change == 'owner': rig.put(rig.owner + 8, struct.pack('<Q', 0))
        elif change == 'fixture_input_alias':
            rig.fixture['date'] = rig.native_fixture['date'] = '2030-11-29'
        elif change == 'fixture_native': rig.native_fixture['away_team']['native_id'] = 999
    with pytest.raises(ValueError, match='changed|differs'):
        Rig(detail_hook=alter).run()


@pytest.mark.parametrize('error', [EOFError('late EOF'), TimeoutError('late timeout'), KeyboardInterrupt('cancelled')])
def test_final_fence_errors_propagate_and_close(error):
    with pytest.raises(type(error), match=str(error)):
        Rig(final_read_error=error).run()


def test_close_error_prevents_publication():
    with pytest.raises(OSError, match='close failed'):
        Rig(close_error=OSError('close failed')).run()


@pytest.mark.parametrize('change', ['tables', 'plugin', 'native_bytes'])
def test_final_layout_refresh_cannot_bypass_runtime_source_checks(change):
    def alter(rig, count):
        if count != 2:
            return
        if change == 'tables': rig.tables = (rig.tables[0] + 8,)
        elif change == 'plugin': rig.bridge.plugin_identity = (('other', 1, 1, 1, 1), rig.uuid)
        else:
            rva, raw = rig.module.NATIVE_SPANS[-1]
            rig.put(rig.base + rva, raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(ValueError, match='changed'):
        Rig(layout_hook=alter).run()


@pytest.mark.parametrize('late', [3, 4, 5, 6])
def test_process_callback_failure_propagates_and_closes(late):
    def fail(rig, count):
        if count == late:
            raise RuntimeError('process callback failed')
    with pytest.raises(RuntimeError, match='process callback failed'):
        Rig(current_hook=fail).run()


@pytest.mark.parametrize('late', [3, 6])
@pytest.mark.parametrize('operand', ['uuid', 'vtable', 'type_name'])
def test_actual_runtime_layout_operands_are_journaled_before_late_callback(late, operand, tmp_path, monkeypatch):
    rig = Rig()
    # Retain the actual Bridge layout verifier, including its cache-clearing refusal path.
    for name, value in vars(bm.Bridge()).items():
        if not hasattr(rig.bridge, name):
            setattr(rig.bridge, name, value)
    contents = tmp_path / 'fm.app/Contents'
    plugin = contents / 'PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin'
    plugin.parent.mkdir(parents=True)
    plugin.write_bytes(b'controlled disk UUID fixture')
    rig.process = rig.bridge.process = SimpleNamespace(pid=1, version=players.VERSION,
        bundle_id='com.SportsInteractive.FootballManager27', executable=str(contents / 'MacOS/fm'))
    rig.bridge.plugin_identity = None
    rig.bridge._run = lambda *_: {'images': [{'path': str(plugin), 'address': hex(rig.base)}]}
    rig.bridge._read_memory = lambda process, at, size: rig.read(at, size)
    rig.bridge._player_layout = bm.Bridge._player_layout.__get__(rig.bridge)
    monkeypatch.setattr(players, 'disk_uuid', lambda path: rig.uuid)
    def mutate(rig, count):
        if count != late:
            return
        if operand == 'uuid': rig.put(rig.base + 40, b'X')
        elif operand == 'vtable': rig.put(rig.base + players.RVA[0] - 16, struct.pack('<q', 1))
        else: rig.put(0x90020, b'X')
    rig.current_hook = mutate
    with pytest.raises(Exception, match='UUID differs|displacement changed|runtime type changed|state changed'):
        rig.run()
    assert (rig.base, 16384) in rig.read_sets[0].observed
    assert (rig.base + players.RVA[0] - 16, 16) in rig.read_sets[0].observed
    assert (0x90020, len(b'N2db13ACTUAL_PLAYERE') + 1) in rig.read_sets[0].observed
