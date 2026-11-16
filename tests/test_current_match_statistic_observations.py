"""Real failed150 source + declared deterministic motion; no live acceptance.

Only previously unconsumed padding in simulated contiguous blocks is synthetic
(0xA5). Every projected operand comes from the preserved genuine source unless
an explicit control changes it. No game process or helper is accessed here.
"""
from copy import deepcopy
from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
import struct
import threading

import pytest

from fm_live_mcp import current_match_statistic_observations as window
from fm_live_mcp import current_player_match_statistic_groups as groups
from fm_live_mcp import players, world
from fm_live_mcp.bridge import Bridge, BridgeError
from fm_live_mcp.reader import ReaderError


@dataclass(frozen=True)
class FakeProcess:
    pid: int = 123


class Memory:
    def __init__(self, *, moving=True):
        raw = gzip.decompress((Path(__file__).parent / 'fixtures/current_match_statistic_observations_failed150.json.gz').read_bytes())
        assert hashlib.sha256(raw).hexdigest() == 'c2b70e78e04993c4abecfce4329a2c9eac64fe6f2cdfff8792af4d2e3159d459'
        self.packet = json.loads(raw)
        assert self.packet['accepted'] is False and self.packet['state'] == 'capture_failed'
        assert self.packet['detach'] == {'detached': True}
        self.cells = {}
        for span in self.packet['raw_consumed_byte_journal']['regions']:
            at, value = int(span['address'], 16), bytes.fromhex(span['rawhex'])
            assert len(value) == span['size']
            for i, byte in enumerate(value):
                assert at+i not in self.cells or self.cells[at+i] == byte
                self.cells[at+i] = byte
        self.base = int(self.packet['plugin']['base_private'], 16)
        self.engine = self.packet['context_before']['private']['engine']
        self.uid = self.packet['context_before']['official_match_unique_id']
        first = next(row for row in self.packet['rows'] if row['raw_statistics150_bytes'])
        self.stats, self.player = int(first['stats_private'], 16), int(first['match_player_private'], 16)
        change = self.packet['raw_consumed_byte_journal']['changed_reads'][0]
        assert int(change['address'], 16) == self.stats + 0x68
        self.distance = struct.unpack('<f', bytes.fromhex(change['expected_hex']))[0]
        self.delta = struct.unpack('<f', bytes.fromhex(change['changed_hex']))[0] - self.distance
        assert self.delta > 0
        self.moving, self.t = moving, 0
        self.after_callbacks = False
        self.reads, self.callbacks = [], []
        self.on_block = None
        self.closed = False
        self.pid = FakeProcess().pid
        self.synthetic_padding = set()
        # The genuine packet did not capture unused padding. Fill it only in
        # the fake transport, without pretending it was genuine source data.
        for row in self.packet['rows']:
            if row['raw_statistics150_bytes']:
                at = int(row['stats_private'], 16)
                for i in range(window.BLOCK_SIZE):
                    if at+i not in self.cells:
                        self.synthetic_padding.add(at+i)
                        self.cells[at+i] = 0xA5

        # Reader 0.160 resolves unmatched resident actors through the actor's
        # stats pointer. This frozen capture predates that source and never read
        # actor+0x1880 for its five genuinely unavailable-identity rows. Model
        # that unobserved pointer as null so those rows stay unavailable; it is
        # transport scaffolding, never genuine data and never a dynamic span.
        self.synthetic_null_actor_stats = set()
        for row in self.packet['rows']:
            if row['identity_state'] == 'unmatched_canonical_roster_pointer':
                side = struct.unpack('<Q', bytes(self.cells[self.engine + 0x15370 + row['side_index']*8 + i] for i in range(8)))[0]
                at = struct.unpack('<Q', bytes(self.cells[side + 0x140 + row['engine_array_index']*8 + i] for i in range(8)))[0] + 0x1880
                assert all(at+i not in self.cells for i in range(8))
                self.synthetic_null_actor_stats.update(at+i for i in range(8))
                self.put(at, bytes(8))

    def put(self, at, raw):
        self.cells.update({at+i: value for i, value in enumerate(raw)})

    def clock(self):
        return self.t

    def read(self, at, size):
        assert not self.closed
        self.t += 1
        if self.moving:
            self.put(self.stats + 0x68, struct.pack('<f', self.distance + self.delta*self.t))
        if self.on_block and size == window.BLOCK_SIZE:
            self.on_block(self, at)
        try:
            raw = bytes(self.cells[at+i] for i in range(size))
        except KeyError as exc:
            raise ValueError('Missing preserved source operand') from exc
        self.reads.append((self.t, at, size, raw, self.after_callbacks))
        return raw

    def callback(self):
        self.callbacks.append(self.t)
        self.put(self.stats + 0x90, b'\xc8')
        self.after_callbacks = True

    def close(self):
        self.closed = True


def prepared(memory):
    read = window.BindingReadSet(memory.read)
    return window.PreparedObservation(read, memory.base)


def test_motion_refuses_old_strict_twice_but_frozen_source_passes():
    memory = Memory()
    for _ in range(2):
        read = world.ReadSet(memory.read)
        groups.inspect(read, memory.base, memory.engine, expected_match_unique_id=memory.uid)
        with pytest.raises(ValueError, match='Game state changed'):
            read.verify()
    frozen = Memory(moving=False)
    read = world.ReadSet(frozen.read)
    assert len(groups.inspect(read, frozen.base, frozen.engine, expected_match_unique_id=frozen.uid)['rows']) == 52
    read.verify()


def test_post_callback_fresh_values_and_ordered_host_intervals():
    memory = Memory()
    source = prepared(memory)
    assert not source.dynamic & memory.synthetic_padding
    memory.callback()
    ledger = {}
    out = source.capture(memory.read, clock=memory.clock, evidence=ledger)
    projection = out['player_statistics']
    assert projection['rows'][0]['shots'] == 200
    first = ledger['dynamic_rows'][0]
    assert projection['rows'][0]['distance_metres'] == struct.unpack_from('<f', bytes.fromhex(first['rawhex']), 0x68)[0]
    assert projection['rows'][0]['distance_metres'] != struct.unpack('<f', bytes(memory.cells[memory.stats+0x68+i] for i in range(4)))[0]
    assert len(ledger['dynamic_rows']) == len(out['row_observations']) == 37
    assert all(row['size'] == window.BLOCK_SIZE for row in ledger['dynamic_rows'])
    assert ledger['accepted'] is True and ledger['final_static_fence_after_all_dynamic_reads'] is True
    assert all(row['started_monotonic_ns'] >= memory.callbacks[-1] for row in out['row_observations'])
    assert all(a['ended_monotonic_ns'] <= b['started_monotonic_ns'] for a, b in zip(out['row_observations'], out['row_observations'][1:]))
    assert all(row['started_monotonic_ns'] < row['ended_monotonic_ns'] for row in out['row_observations'])
    assert all(out[flag] is False and projection[flag] is False for flag in groups.FALSE_FLAGS)
    assert out['dynamic_values_rechecked_unchanged'] is False
    assert out['all_rows_same_instant_verified'] is out['all_fields_same_instant_verified'] is out['current_at_response_time_verified'] is False
    assert projection['field_qualifiers'] == groups._qualifiers()
    unknown = [row for row in projection['rows'] if row['state'] != groups.AVAILABLE]
    assert len(unknown) == 15
    assert all(row[field] is None for row in unknown for _, _, fields in groups.GROUPS for field in fields)
    # Replay every field with the real projector from recorded final blocks;
    # both provisional numbers and simulated padding are excluded.
    cells = dict(source.static)
    for row in ledger['dynamic_rows']:
        at, raw = int(row['address'], 16), bytes.fromhex(row['rawhex'])
        cells.update({at+i: value for i, value in enumerate(raw) if at+i in source.dynamic})
    rebuilt = groups.inspect(lambda at, size: bytes(cells[at+i] for i in range(size)), memory.base, memory.engine, expected_match_unique_id=memory.uid)
    assert rebuilt['rows'] == projection['rows']
    assert sum(len(fields) for _, _, fields in groups.GROUPS) * len(ledger['dynamic_rows']) == 1221


@pytest.mark.parametrize('target', ['engine_owner', 'side_owner', 'stats_pointer', 'stats_person', 'person', 'fixture', 'native_code', 'date', 'save_name'])
@pytest.mark.parametrize('phase', ['callback', 'during_block'])
def test_static_drift_never_returns_accepted_values(target, phase):
    memory = Memory()
    source = prepared(memory)
    save = source.world_identity[1]
    name = struct.unpack('<Q', memory.read(save + 0x28, 8))[0]
    locations = {'engine_owner': memory.player + 0x280, 'side_owner': memory.player + 0x288,
                 'stats_pointer': memory.player + 0x1880, 'stats_person': memory.stats + 0x18,
                 'person': struct.unpack('<Q', memory.read(memory.player + 0x20, 8))[0] + 12,
                 'fixture': memory.engine + 0x20,
                 'native_code': memory.base + groups.attacking.SOURCE_SPANS[0][0],
                 'date': memory.base + world.CURRENT_DATE, 'save_name': name + 4}
    def mutate(*_):
        at = locations[target]
        memory.cells[at] ^= 1
        memory.on_block = None
    memory.callback()
    if phase == 'callback':
        mutate()
    else:
        memory.on_block = mutate
    ledger = {}
    with pytest.raises(ValueError, match='changed'):
        source.capture(memory.read, clock=memory.clock, evidence=ledger)
    assert ledger['accepted'] is False
    if phase == 'callback':
        assert not any(size == window.BLOCK_SIZE for _, _, size, _, _ in memory.reads)


def test_missing_final_block_byte_rejects_instead_of_reusing_preflight():
    memory = Memory(moving=False)
    source = prepared(memory)
    del memory.cells[memory.stats+0x68]
    ledger = {}
    with pytest.raises(ValueError, match='Missing preserved'):
        source.capture(memory.read, clock=memory.clock, evidence=ledger)
    assert ledger['accepted'] is False


def test_final_encoding_preserves_real_zero_wrap_sums_signed_and_float_units():
    memory = Memory(moving=False)
    source = prepared(memory)
    memory.put(memory.stats + 0x90, b'\0\xff')
    memory.put(memory.stats + 0x99, b'\xff\xff\xff')
    memory.put(memory.stats + 0xDF, b'\xff'*4)
    memory.put(memory.stats + 0x10A, struct.pack('<h', 32767))
    memory.put(memory.stats + 0x68, struct.pack('<f', 1234.5))
    memory.put(memory.stats + 0x1C, struct.pack('<f', 2.25))
    out = source.capture(memory.read)['player_statistics']
    row = out['rows'][0]
    assert (row['shots'], row['shots_on_target']) == (0, 255)
    assert row['total_saves'] == (255*3)&255
    assert row['open_play_crosses_attempted'] == row['open_play_crosses_completed'] == 510
    assert row['open_play_final_third_passes'] == 32767
    assert row['distance_metres'] == 1234.5 and row['expected_goals'] == 2.25
    assert out['field_qualifiers']['distance_metres']['unit'] == 'metres'


@pytest.mark.parametrize('offset,raw', [(0x10A, struct.pack('<h', -1)),
                                      (0x68, struct.pack('<f', float('nan')))])
def test_invalid_final_numeric_encoding_rejects_without_provisional_fallback(offset, raw):
    memory = Memory(moving=False)
    source = prepared(memory)
    memory.put(memory.stats + offset, raw)
    ledger = {}
    with pytest.raises(ValueError):
        source.capture(memory.read, evidence=ledger)
    assert ledger['accepted'] is False


def test_missing_padding_is_not_silently_fabricated_by_product():
    memory = Memory(moving=False)
    source = prepared(memory)
    memory.cells.pop(next(at for at in memory.synthetic_padding if memory.stats <= at < memory.stats + window.BLOCK_SIZE))
    with pytest.raises(ValueError, match='Missing preserved'):
        source.capture(memory.read)


def test_all_unknown_stats_rows_stay_explicit_without_dynamic_reads():
    memory = Memory(moving=False)
    for row in memory.packet['rows']:
        if row['raw_statistics150_bytes']:
            memory.put(int(row['match_player_private'], 16) + 0x1880, b'\0'*8)
    source = prepared(memory)
    out = source.capture(memory.read)
    assert out['state'] == 'unavailable' and out['row_observations'] == []
    assert len(out['player_statistics']['rows']) == 52
    assert all(row[field] is None for row in out['player_statistics']['rows']
               for _, _, fields in groups.GROUPS for field in fields)
    assert not any(size == window.BLOCK_SIZE for _, _, size, _, _ in memory.reads)


def test_unbound_current_fixture_returns_no_scalar_projection(monkeypatch):
    memory = Memory(moving=False)
    monkeypatch.setattr(window.active_match_source, 'inspect_context',
                        lambda *_args, **_kwargs: ({'source_state': 'inactive'}, None))
    out = prepared(memory).capture(memory.read)
    assert out['state'] == 'unavailable' and out['player_statistics'] is None
    assert out['row_observations'] == []


def _alias_review_reproduction(memory):
    """Exact reviewer control: both side rosters admit the same canonical PERSON/stats."""
    u64 = lambda at: struct.unpack('<Q', memory.read(at, 8))[0]
    home_side, away_side = u64(memory.engine+0x15370), u64(memory.engine+0x15378)
    home_actor, away_actor = u64(home_side+0x140), u64(away_side+0x140)
    home_person = u64(home_actor+0x20)
    away_team = u64(away_side+0xB8)
    memory.put(u64(away_team+0x38), struct.pack('<Q', home_person-0x388))
    memory.put(away_actor+0x20, struct.pack('<Q', home_person))
    memory.put(away_actor+0x1880, struct.pack('<Q', u64(home_actor+0x1880)))


def test_reviewer_shared_stats_reproduction_rejects_before_observations(monkeypatch):
    # The frozen capture lacks the reader 0.160 global-PERSON getter source, so
    # isolate the overlap guard from that separate unmatched-actor fallback.
    from fm_live_mcp import native_match_stats_person
    monkeypatch.setattr(native_match_stats_person, 'add_global_identities',
                        lambda read, base, engine, result: result)
    memory = Memory()
    _alias_review_reproduction(memory)
    with pytest.raises(ValueError, match='Overlapping statistics observation block'):
        prepared(memory)
    assert not any(size == window.BLOCK_SIZE for _, _, size, _, _ in memory.reads)


@pytest.mark.parametrize('separation', [0, 8, 0x100, 0x108])
def test_partial_and_identical_block_ranges_reject_even_in_reverse_row_order(separation):
    rows = [window.RowBinding(1, 0, 0x10000+separation, ()),
            window.RowBinding(0, 0, 0x10000, ())]
    with pytest.raises(ValueError, match='Overlapping statistics observation block'):
        window._validate_row_blocks(rows)


@pytest.mark.parametrize('start', [4096, ((1 << 64)-window.BLOCK_SIZE-1)//8*8])
def test_block_range_accepts_low_and_high_nonoverflowing_native_addresses(start):
    window._validate_row_blocks([window.RowBinding(0, 0, start, ())])


@pytest.mark.parametrize('start', [4088, 4097, (1 << 64)-0x108, (1 << 64), -8, True])
def test_block_range_rejects_invalid_alignment_overflow_and_extreme_addresses(start):
    with pytest.raises(ValueError, match='Invalid statistics observation block range'):
        window._validate_row_blocks([window.RowBinding(0, 0, start, ())])


def test_nearest_aligned_nonoverlapping_block_ranges_remain_admissible():
    window._validate_row_blocks([window.RowBinding(1, 0, 0x10110, ()),
                                 window.RowBinding(0, 0, 0x10000, ())])


class FakeBridge:
    _read_scope = Bridge._read_scope

    def __init__(self, memory):
        self.memory = memory
        self.process = FakeProcess()
        self.lock = threading.RLock()
        self._reader = None
        self.helper = Path('/never-launched')
        self.plugin_identity = ('fake', bytes.fromhex(memory.packet['plugin']['uuid_hex']))
        self.world_identity = None
        self.current_calls = 0
        self.final_change = None
        self.public_change = None

    def _current(self, session):
        assert session == 'test'
        self.current_calls += 1
        # Entry, body, final body preflight, then hidden scope-exit callback.
        if self.current_calls == 4:
            self.memory.callback()
            if self.final_change:
                self.final_change()
        return self.process

    def _player_layout(self, process):
        return tuple(self.memory.base + rva for rva in players.RVA)

    def _world_state(self, process, tables):
        read = world.ReadSet(self.memory.read)
        save, identity = world.loaded(read, self.memory.base)
        read.verify()
        self.world_identity = identity
        return read, save, identity

    def _public_save(self, save):
        if self.public_change:
            self.public_change()
        return Bridge._public_save(save)

    def _read_memory(self, *_):
        raise AssertionError('Final observation must bypass bridge journal/page cache')


def call_bridge(monkeypatch, memory, **changes):
    from fm_live_mcp import bridge as bridge_module
    b = FakeBridge(memory)
    for key, value in changes.items():
        setattr(b, key, value)
    monkeypatch.setattr(bridge_module, 'ReadStream', lambda helper, pid: memory)
    return b


def test_real_bridge_scope_hidden_last_current_precedes_fresh_blocks_and_close(monkeypatch):
    memory = Memory()
    b = call_bridge(monkeypatch, memory)
    out = window.current_match_statistic_observations(b, 'test')
    assert b.current_calls == 4
    assert out['player_statistics']['rows'][0]['shots'] == 200
    assert memory.closed is True and b._reader is None
    assert all(after for _, _, size, _, after in memory.reads if size == window.BLOCK_SIZE)


@pytest.mark.parametrize('fault', ['vm', 'short', 'cancel', 'close', 'last_identity', 'public_date'])
def test_real_scope_failure_cancellation_and_cleanup_reject_and_close(monkeypatch, fault):
    memory = Memory(moving=False)
    b = call_bridge(monkeypatch, memory)
    if fault in ('vm', 'cancel'):
        def fail(*_):
            raise ReaderError('VM read failed') if fault == 'vm' else KeyboardInterrupt('cancelled')
        memory.on_block = fail
    elif fault == 'short':
        original = memory.read
        memory.read = lambda at, size: original(at, size)[:-1] if size == window.BLOCK_SIZE else original(at, size)
    elif fault == 'close':
        def close():
            memory.closed = True
            raise ReaderError('Close failed')
        memory.close = close
    elif fault == 'last_identity':
        b.final_change = lambda: setattr(b, 'world_identity', ('drift',))
    else:
        b.public_change = lambda: memory.put(memory.base + world.CURRENT_DATE, b'\0'*4)
    ledger = {}
    with pytest.raises(KeyboardInterrupt if fault == 'cancel' else BridgeError):
        window.current_match_statistic_observations(b, 'test', _evidence=ledger)
    assert memory.closed is True and b._reader is None
    assert ledger['accepted'] is False


def test_window_is_an_option_on_existing_current_match_tool_not_a_new_tool(monkeypatch):
    import asyncio
    from fm_live_mcp import current_match_report as report
    from fm_live_mcp.server import mcp
    assert not hasattr(__import__('fm_live_mcp'), 'current_match_statistic_observation_tools')
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    assert 'fm_get_current_match_player_statistic_observations' not in tools
    schema = tools['fm_get_current_match'].inputSchema['properties']['player_statistics_observation_window']
    assert schema['type'] == 'boolean' and schema['default'] is False
    assert 'host_observation_window' in tools['fm_get_current_match'].description
    sentinel = object()
    monkeypatch.setattr(window, 'current_match_statistic_observations', lambda bridge, session: (bridge, session))
    assert report.current_match_report(sentinel, 'test', include_player_statistics=True,
                                       player_statistics_observation_window=True) == (sentinel, 'test')


@pytest.mark.parametrize('kwargs', (
    dict(include_player_statistics=False),
    dict(include_player_statistics=True, include_shot_events=True),
    dict(include_player_statistics=True, include_player_passing=True),
    dict(include_player_statistics=True, player_statistics_observation_window=1)))
def test_window_option_refuses_incompatible_report_sections_before_any_read(kwargs):
    from fm_live_mcp import current_match_report as report
    kwargs = dict(player_statistics_observation_window=True, **kwargs) if 'player_statistics_observation_window' not in kwargs else kwargs
    class Bridge:
        def __getattr__(self, name):
            raise AssertionError('bridge must not be touched')
    with pytest.raises(ValueError):
        report.current_match_report(Bridge(), 'test', **kwargs)
