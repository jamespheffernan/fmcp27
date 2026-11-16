"""Real Bridge layout/scope/world transport over owned synthetic physical RAM.

Only image inventory, disk fingerprint and physical process/transport are
controlled. Native verify_runtime, report inspection, world/coach identity and
Bridge cache/error paths remain production code. Hooks wrap real callbacks.
"""
from dataclasses import replace
import struct

from fm_live_mcp import active_match_source, bridge as bridge_module, players, world
from fm_live_mcp.bridge import Bridge


class RuntimeRig:
    uuid = b'publish UUID ok!'

    def __init__(self, m, bridge, monkeypatch, tmp_path):
        assert len(self.uuid) == 16
        self.m, self.bridge, self.events = m, bridge, []
        self.hooks, self.public_hook, self.layout_hook, self.world_hook = {}, None, None, None
        self.calls, self.layout_calls, self.world_calls = 0, 0, 0
        self.read_sets, self.streams = [], []
        self.put(m['base'], bytes(16384))
        self.put(m['base'], struct.pack('<8I', 0xFEEDFACF, 0x100000C, 0, 6, 1, 24, 0, 0)
                 + struct.pack('<II', 0x1B, 24) + self.uuid)
        self.runtime_texts = []
        for rva, displacement, name in zip(players.RVA, (0, 0, -0x388),
                (b'N2db13ACTUAL_PLAYERE', b'N2db12PLAYING_DATAE', b'N2db13ACTUAL_PLAYERE')):
            info = m['allocate'](16)
            text = m['allocate'](len(name) + 1)
            self.put(text, name + b'\0')
            m['q'](info + 8, text)
            self.put(m['base'] + rva - 16, struct.pack('<qQ', displacement, info))
            self.runtime_texts.append(text)
        contents = tmp_path / 'fm.app/Contents'
        plugin = contents / 'PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin'
        plugin.parent.mkdir(parents=True)
        plugin.write_bytes(b'controlled disk fingerprint only')
        process = replace(bridge.process, version=players.VERSION, executable=str(contents / 'MacOS/fm'))
        bridge.process = process
        bridge.plugin_identity = None
        monkeypatch.setattr(bridge_module, 'process_info', lambda pid: process if pid == process.pid else None)
        monkeypatch.setattr(players, 'disk_uuid', lambda path: self.uuid)
        def images(command, *args):
            assert command == 'images', 'No native game/helper command is authorized in this rig'
            self.events.append(('images',))
            return {'images': [{'path': str(plugin), 'address': hex(m['base'])}]}
        monkeypatch.setattr(bridge, '_run', images)
        monkeypatch.setattr(bridge, '_read_memory', Bridge._read_memory.__get__(bridge, Bridge))
        monkeypatch.setattr(bridge, '_read_scope', Bridge._read_scope.__get__(bridge, Bridge))
        def layout(current):
            self.layout_calls += 1
            self.events.append(('layout', self.layout_calls))
            result = Bridge._player_layout(bridge, current)
            if self.layout_hook:
                self.layout_hook(self, self.layout_calls)
            return result
        monkeypatch.setattr(bridge, '_player_layout', layout)
        def state(current, tables):
            self.world_calls += 1
            self.events.append(('world', self.world_calls))
            result = Bridge._world_state(bridge, current, tables)
            self.read_sets.append(result[0])
            if self.world_hook:
                self.world_hook(self, self.world_calls, result[0])
            return result
        monkeypatch.setattr(bridge, '_world_state', state)
        def current(session):
            result = Bridge._current(bridge, session)
            self.calls += 1
            self.events.append(('current', self.calls))
            if self.calls in self.hooks:
                replacement = self.hooks[self.calls](self)
                if replacement is not None:
                    result = replacement
            return result
        monkeypatch.setattr(bridge, '_current', current)
        def public(save):
            self.events.append(('public',))
            result = Bridge._public_save(save)
            if self.public_hook:
                self.public_hook(self)
            return result
        monkeypatch.setattr(bridge, '_public_save', public)
        rig = self
        class Stream:
            def __init__(self, helper, pid):
                self.pid, self.closed = pid, False
                rig.streams.append(self)
                rig.events.append(('open',))
            def read(self, address, length):
                assert not self.closed
                rig.events.append(('physical', address, length))
                return rig.read(address, length)
            def close(self):
                self.closed = True
                rig.events.append(('close',))
        monkeypatch.setattr(bridge_module, 'ReadStream', Stream)

    def put(self, address, raw):
        self.m['put'](address, raw)

    def read(self, address, length):
        # ReportReadSet's page transport reads padding; the sparse fixture owns
        # that physical zero padding, without adding it to consumed operands.
        return bytes(self.m['cells'].get(address + i, 0) for i in range(length))

    def mutate(self, operand):
        if operand == 'uuid': self.put(self.m['base'] + 40, b'X')
        elif operand == 'rtti_displacement': self.put(self.m['base'] + players.RVA[1] - 16, struct.pack('<q', 1))
        elif operand == 'rtti_name': self.put(self.runtime_texts[1], b'X')
        elif operand == 'focus': self.put(self.m['focus_child'] + 6, b'\x19')
        elif operand == 'save_count':
            at = self.m['game'] + 0xC8
            self.put(at, struct.pack('<I', int.from_bytes(self.read(at, 4), 'little') + 1))
        elif operand == 'date': self.put(self.m['base'] + world.CURRENT_DATE, struct.pack('<I', 2030 << 16 | 263))
        elif operand == 'client_root': self.m['q'](self.m['base'] + active_match_source.ROOT, 3)
        else: raise AssertionError(operand)

    def closed(self):
        assert self.bridge._reader is None
        assert self.streams and all(s.closed for s in self.streams)
        assert self.events[-1][0] == 'close'

    def reset_trace(self):
        self.calls, self.layout_calls, self.world_calls = 0, 0, 0
        self.events.clear()
        self.read_sets.clear()
        self.streams.clear()


def seed_absent_match(m):
    for rva, raw in (*active_match_source.NATIVE_SPANS, *active_match_source.FIXTURE_OWNER_SPANS):
        m['put'](m['base'] + rva, raw)
    m['q'](m['base'] + active_match_source.ROOT, 0)
