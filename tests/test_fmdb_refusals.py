"""Refusal removal (docs/fmdb/REFUSALS.md): RNG policies, new external models, long-walk retry and
the virtual-player helpers, on synthetic code and memory (no game needed). Every VM test runs on
PropertyVM and on FastVM."""
import struct
from types import SimpleNamespace

import pytest
import unicorn.arm64_const as A

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fm_live_mcp.fmdb import fastvm  # noqa: E402
from fm_live_mcp.fmdb import vm as V
from fm_live_mcp.fmdb.vm import PropertyVM, Unavailable, _Stop

from test_fmdb_vm import (BASE, GETTER, REGISTRY, RET, Image, Memory, VMS, record, words,  # noqa: F401
                          world as _world_fixture)

world = _world_fixture
TLV_STUB, RD_CTOR, RD_DRAW, CLOCK_STUB = 0x8030, 0x803C, 0x8048, 0x8054


def bl(src, dst):
    return 0x94000000 | (((dst - src) >> 2) & 0x3FFFFFF)


# getter(record, key, out): x0 = record[+0x18] (a TLV descriptor address), __tlv_bootstrap,
# then out = {record[+8] traits, payload}; payload = generator state ([x0+8]) or record[+0x10].
def rng_getter(at, depends):
    store = 0xF9000689 if depends else 0xF900068B          # str x9 | str x11, [x20,#8]
    return words(0xA9BF7BFD, 0xA9BF53F3, 0xAA0003F3, 0xAA0203F4,
                 0xF9400E60, bl(at + 0x14, TLV_STUB), 0xF9400409, 0xF940066A, 0xF9400A6B,
                 0xF900028A, store, 0x52800020, 0xA8C153F3, 0xA8C17BFD, RET)


def make_vm(cls, code, stubs, **kwargs):
    m = Memory()
    from test_fmdb_vm import TRAITS
    from fm_live_mcp.fmdb.vm import VARIANT_REGISTRY_RVA
    m.put(BASE + VARIANT_REGISTRY_RVA, struct.pack('<Q', REGISTRY))
    m.put(REGISTRY, bytes(0xE0))
    for i, (offset, name) in enumerate(TRAITS.items()):
        vtable = 0x20_0001_0000 + i * 0x100
        info, text = vtable + 0x80, vtable + 0xA0
        m.put(vtable - 8, struct.pack('<QQQQQ', info, 0, 0, 0, 0))
        m.put(info + 8, struct.pack('<Q', text))
        m.put(text, name.encode() + b'\0')
        m.put(REGISTRY + offset, struct.pack('<QB', vtable, i))
    image = Image(code)
    image.stubs.update(stubs)
    vm = cls(m, BASE, image, view='game', budget=10_000, **kwargs)
    return SimpleNamespace(m=m, vm=vm)


def rng_record(w, address, getter_rva, payload=41):
    vtable = address + 0x800
    w.m.put(vtable, struct.pack('<QQQQ', 0, 0, 0, BASE + getter_rva))
    w.m.put(address, struct.pack('<QQQQ', vtable, REGISTRY + 0x48, payload, BASE + V.RNG_STATE_TLV))
    return address


@pytest.fixture(params=VMS)
def rng_world(request):
    def build(rng):
        return make_vm(request.param, {0x1000: rng_getter(0x1000, True), 0x1100: rng_getter(0x1100, False)},
                       {TLV_STUB: '__tlv_bootstrap'}, rng=rng)
    return build


def test_rng_refuse_keeps_the_old_reason(rng_world):
    w = rng_world('refuse')
    r = rng_record(w, 0x30_0000_0000, 0x1100)
    result = w.vm.get_property(r, 'Xxxx')
    assert result.value == Unavailable('thread-local RNG state')


def test_rng_isolate_keeps_values_stable_under_two_seeds(rng_world):
    w = rng_world('isolate')
    r = rng_record(w, 0x30_0000_0000, 0x1100, payload=41)
    result = w.vm.get_property(r, 'Xxxx')
    assert (result.value, result.rng) == (41, 'stable')
    assert result.stats.rng_draws == 1


def test_rng_isolate_refuses_values_that_depend_on_the_draws(rng_world):
    w = rng_world('isolate')
    r = rng_record(w, 0x30_0000_0000, 0x1000)
    result = w.vm.get_property(r, 'Xxxx')
    assert result.value == Unavailable(V.RNG_DEPENDS)


def test_rng_private_is_marked_and_seeded_like_the_game(rng_world):
    w = rng_world('private')
    r = rng_record(w, 0x30_0000_0000, 0x1000)
    result = w.vm.get_property(r, 'Xxxx')
    seed = V.RNG_SEEDS[0]
    assert result.rng == 'private'
    state = (seed * V.PCG_SEED_MULT + V.PCG_SEED_ADD) & 0xFFFF_FFFF_FFFF_FFFF
    assert result.value == struct.unpack('<q', struct.pack('<Q', state))[0]    # int64 variant
    again = w.vm.get_property(r, 'Xxxx')                   # a fresh generator per call
    assert again.value == result.value


def test_default_policy_is_isolate():
    assert V.DEFAULT_RNG == 'isolate'


@pytest.mark.parametrize('cls', VMS)
def test_long_walks_are_retried_with_a_larger_budget(cls):
    # mov x9,#20000; loop: sub x9,x9,#1; cbnz x9,loop; then the plain getter (40,000+ instructions)
    loop = words(0xD289C409, 0xD1000529, 0xB5FFFFE9) + GETTER
    w = make_vm(cls, {0x1000: loop}, {})
    r = record(w, 0x30_0000_0000, 0x1000, 0x28, 7)
    result = w.vm.get_property(r, 'Xxxx')
    assert result.value == 7
    w.vm.retry_long = False
    w.vm._long_results.clear()
    assert w.vm.get_property(r, 'Xxxx').value == Unavailable('instruction budget exceeded')


def call_model(vm, model, *regs, fregs=()):
    for i, value in enumerate(regs):
        vm.uc.reg_write(getattr(A, f'UC_ARM64_REG_X{i}'), value & (2**64 - 1))
    for i, value in enumerate(fregs):
        vm.uc.reg_write(getattr(A, f'UC_ARM64_REG_D{i}'), struct.unpack('<I', struct.pack('<f', value))[0])
    model(vm)
    return vm.uc.reg_read(A.UC_ARM64_REG_X0)


def test_pure_library_models(world):
    vm, m = world.vm, world.m
    text = 0x60_0000_0000
    m.put(text, b'  -42xyz\0')
    m.put(text + 0x100, b'0x1F\0')
    m.put(text + 0x200, b'hello world\0')
    m.put(text + 0x300, b'wor\0')
    assert call_model(vm, V.EXTERNALS['_strtoll'], text, 0, 10) == (-42) & (2**64 - 1)
    assert call_model(vm, V.EXTERNALS['_strtoull'], text, 0, 10) == (2**64 - 42)
    assert call_model(vm, V.EXTERNALS['_strtoull'], text + 0x100, 0, 0) == 31
    assert call_model(vm, V.EXTERNALS['_atoi'], text, 0) == (-42) & 0xFFFFFFFF
    assert call_model(vm, V.EXTERNALS['_strchr'], text + 0x200, ord('w')) == text + 0x206
    assert call_model(vm, V.EXTERNALS['_strchr'], text + 0x200, ord('z')) == 0
    assert call_model(vm, V.EXTERNALS['_strrchr'], text + 0x200, ord('o')) == text + 0x207
    assert call_model(vm, V.EXTERNALS['_strstr'], text + 0x200, text + 0x300) == text + 0x206
    for n, prime in ((0, 2), (14, 17), (17, 17), (2**32, 4294967311)):
        assert call_model(vm, V.EXTERNALS['__ZNSt3__112__next_primeEm'], n) == prime
    with pytest.raises(_Stop):
        call_model(vm, V.EXTERNALS['__ZNSt3__112__next_primeEm'], 2**64 - 2)
    call_model(vm, V.EXTERNALS['_asinf'], fregs=(0.5,))
    got = struct.unpack('<f', struct.pack('<I', vm.uc.reg_read(A.UC_ARM64_REG_D0) & 0xFFFFFFFF))[0]
    assert got == pytest.approx(0.5235988)


def test_lock_setup_models_are_constant_and_run_in_c():
    for name in ('_pthread_mutexattr_init', '_pthread_mutexattr_settype', '_pthread_mutexattr_destroy',
                 '_pthread_mutex_init', '_pthread_mutex_destroy',
                 '_pthread_condattr_init', '_pthread_cond_init', '_pthread_condattr_destroy', '_pthread_cond_destroy'):
        assert V.EXTERNALS[name] is V._noop          # FastVM runs _noop models in C


def test_stand_ins_are_marked(world):
    vm = world.vm
    vm._call = V.CallStats()
    buf = 0x60_0000_0000
    world.m.put(buf, bytes(16))
    assert call_model(vm, V.EXTERNALS['_gettimeofday'], buf) == 0
    seconds = struct.unpack('<q', vm.read(buf, 8))[0]
    assert seconds > 1_700_000_000
    context = call_model(vm, V.EXTERNALS['_SteamInternal_ContextInit'], 0x1234)
    assert vm.read(context, 0x200) == bytes(0x200)
    assert vm._call.marked == [V.HOST_CLOCK, V.STEAM_OFFLINE]
    vm._call = None


def test_getpid_is_the_game_pid(world):
    vm = world.vm
    vm.reader.pid = 4242
    assert call_model(vm, V.EXTERNALS['_getpid']) == 4242
    del vm.reader.pid
    with pytest.raises(_Stop):
        call_model(vm, V.EXTERNALS['_getpid'])


def test_cfstring_path_round_trip(world):
    vm = world.vm
    vm._call = V.CallStats()
    text, buf = 0x60_0000_0000, 0x60_0000_1000
    world.m.put(text, b'/tmp/fm\0')
    world.m.put(buf, bytes(64))
    obj = call_model(vm, V.EXTERNALS['_CFStringCreateWithCStringNoCopy'], 0, text, 0x08000100, 0)
    assert call_model(vm, V.EXTERNALS['_CFStringGetMaximumSizeOfFileSystemRepresentation'], obj) == 22
    assert call_model(vm, V.EXTERNALS['_CFStringGetFileSystemRepresentation'], obj, buf, 64) == 1
    assert vm.read(buf, 8) == b'/tmp/fm\0'
    with pytest.raises(_Stop):
        call_model(vm, V.EXTERNALS['_CFStringGetMaximumSizeOfFileSystemRepresentation'], buf)
    vm._call = None


def test_random_device(world):
    vm = world.vm
    vm.rng = 'refuse'
    with pytest.raises(_Stop):
        call_model(vm, V.EXTERNALS['__ZNSt3__113random_deviceC1ERKNS_12basic_stringIcNS_11char_traitsIcEENS_9allocatorIcEEEE'], 0x10)
    vm.rng = 'private'
    vm._call = V.CallStats()
    call_model(vm, V.EXTERNALS['__ZNSt3__113random_deviceC1ERKNS_12basic_stringIcNS_11char_traitsIcEENS_9allocatorIcEEEE'], 0x10)
    a = call_model(vm, V.EXTERNALS['__ZNSt3__113random_deviceclEv'], 0x10)
    b = call_model(vm, V.EXTERNALS['__ZNSt3__113random_deviceclEv'], 0x10)
    assert a != b and vm._call.rng_draws == 3 and V.RANDOM_DEVICE in vm._call.marked
    vm._call = None


# ----------------------------------------------------------------------------- virtual players
def test_virtual_profile_state():
    from fm_live_mcp.fmdb.sources import virtual_players as VP
    m = Memory()
    base = 0x10_0000_0000
    manager, ring, profile, vtable = 0x40_0000_0000, 0x40_0000_1000, 0x40_0000_2000, 0x40_0000_3000
    compact = 0x40_0000_4000
    m.put(base + VP.MANAGER_RVA, struct.pack('<Q', manager))
    m.put(manager + 8, struct.pack('<QQ', ring, ring + 16))
    m.put(ring, struct.pack('<QQ', 0, profile))
    m.put(profile, struct.pack('<Q', vtable))
    m.put(vtable - 0x18, struct.pack('<q', 0x40))
    m.put(profile + 0x40 + VP.PROFILE_ID, struct.pack('<I', 777))
    raw = bytearray(0x40)
    struct.pack_into('<h', raw, VP.CACHE_INDEX, 1)
    struct.pack_into('<I', raw, VP.IDENTITY, 777)
    m.put(compact, bytes(raw))
    record = compact + VP.COMPACT_OFFSET
    assert VP.profile_state(m.read, base, record) == ('cached', profile)
    struct.pack_into('<I', raw, VP.IDENTITY, 778)             # the slot now holds another player
    m.put(compact, bytes(raw))
    assert VP.profile_state(m.read, base, record) == ('generated', None)
    struct.pack_into('<h', raw, VP.CACHE_INDEX, -1)
    m.put(compact, bytes(raw))
    assert VP.profile_state(m.read, base, record) == ('generated', None)


def test_virtual_difference_of_committed_states():
    from fm_live_mcp.fmdb.sources import virtual_players as VP
    from fm_live_mcp.fmdb.ui_vm import Baseline
    page = 0x50_0000_0000
    original = bytes(4096)
    a = Baseline(V.HEAP + 32, b'\1' * 32, {}, {page: b'\0' * 10 + b'\5' + b'\0' * 4085}, {page: original}, None)
    b = Baseline(V.HEAP + 32, b'\1' * 31 + b'\2', {}, {page: b'\0' * 10 + b'\6' + b'\0' * 4085}, {page: original}, None)
    assert VP._difference(a, b) == {page + 10, V.HEAP + 31}
    assert VP._difference(a, a) == set()


def test_virtual_row_tuple_marks_draws_and_reasons():
    from fm_live_mcp.fmdb import bulkplans
    from fm_live_mcp.fmdb.sources import virtual_players as VP

    class Col(SimpleNamespace):
        pass
    cols = [Col(code='PCAB', part=None, kind='int', references=None, table='player', name='ca'),
            Col(code='Phei', part=None, kind='int', references=None, table='player', name='height'),
            Col(code='Pfoo', part=None, kind='int', references=None, table='player', name='foo')]
    row = VP.VirtualRow(5, 99, 'generated', {'PCAB': 120, 'Phei': bulkplans.Missing(V.RNG_DEPENDS),
                                              'Pfoo': bulkplans.Missing('instruction budget exceeded')},
                        ['Phei'], [], 0.1)
    out = VP.row_tuple(row, cols, resolver=None)
    assert out[:6] == (5, 99, 'generated', '["Phei"]', '{"Pfoo": "instruction budget exceeded"}', None)
    assert out[6:] == (120, None, None)


def test_retry_reader_separates_a_race_from_a_hole():
    class Flaky:
        def __init__(self):
            self.calls, self._bad_pages, self.page_size = 0, {0x5000}, 0x1000

        def read(self, address, length):
            self.calls += 1
            if address >= 0x9000 or self.calls == 1:
                raise OSError('unreadable')
            return b'\1' * length
    inner = Flaky()
    reader = V.RetryReader(inner, pause=0)
    assert reader.read(0x5000, 8) == b'\1' * 8           # first read races, second succeeds
    assert (reader.retried, reader.recovered) == (1, 1) and inner._bad_pages == set()
    with pytest.raises(OSError):
        reader.read(0x9000, 8)                             # a real hole stays unreadable
    assert (reader.retried, reader.recovered) == (2, 1)


def test_two_seed_rule_withholds_leaves_that_change():
    from fm_live_mcp.fmdb.ui_vm import GENERATED_AT_READ, two_seed
    answers = {0: {'a': 1, 'b': [1, 2], 'seconds': 3.0, 'only': {'x': 1}},
               7: {'a': 1, 'b': [1, 5], 'seconds': 9.0, 'only': {'x': 1, 'y': 2}}}
    out, changed = two_seed(lambda salt: answers[salt], 7, ignore={'seconds'})
    assert out['a'] == 1 and out['seconds'] == 3.0
    assert out['b'] == [1, {'unavailable': GENERATED_AT_READ}]
    assert out['only'] == {'unavailable': GENERATED_AT_READ}       # a key only the salted run has
    assert changed == [str(('b', 1)), str(('only', 'y'))]


@pytest.mark.parametrize('cls', VMS)
def test_unreadable_memory_is_retried_on_fresh_pages(cls):
    # getter: x11 = record[+0x18]; ldr x12,[x11]; then the plain getter. The copied record page holds
    # a pointer the "game" has since replaced; a refresh of the pages reads the new one.
    w = make_vm(cls, {0x1400: words(0xF9400C0B, 0xF940016C) + GETTER}, {})
    r = record(w, 0x30_0000_0000, 0x1400, 0x28, 5, extra=struct.pack('<Q', 0x7777_0000_0000))
    target = 0x31_0000_0000
    w.m.put(target, bytes(8))

    class Game:
        def invalidate(self):                 # the reader's cache is dropped; the game moved on
            w.m.put(r + 0x18, struct.pack('<Q', target))
    w.vm.reader.memory = Game()
    w.vm.reader.pause = 0
    result = w.vm.get_property(r, 'Xxxx')
    assert result.value == 5 and (w.vm.stale_retries, w.vm.stale_recovered) == (1, 1)


def test_localtime_r_writes_struct_tm(world):
    import time as _time
    vm = world.vm
    src, tm = 0x60_0000_0000, 0x60_0000_1000
    world.m.put(src, struct.pack('<q', 1_800_000_000))
    world.m.put(tm, bytes(64))
    assert call_model(vm, V.EXTERNALS['_localtime_r'], src, tm) == tm
    fields = struct.unpack('<9i', vm.read(tm, 36))
    want = _time.localtime(1_800_000_000)
    assert fields[:6] == (want.tm_sec, want.tm_min, want.tm_hour, want.tm_mday, want.tm_mon - 1, want.tm_year - 1900)


def test_getenv_reads_the_game_environment(world, monkeypatch):
    vm = world.vm
    vm.reader.pid = 777
    monkeypatch.setitem(V._ENVIRONMENTS, 777, {b'HOME': b'/Users/x'})
    name = 0x60_0000_0000
    world.m.put(name, b'HOME\0NOPE\0')
    got = call_model(vm, V.EXTERNALS['_getenv'], name)
    assert vm.read(got, 9) == b'/Users/x\0'
    assert call_model(vm, V.EXTERNALS['_getenv'], name + 5) == 0
    monkeypatch.setitem(V._ENVIRONMENTS, 777, None)
    with pytest.raises(_Stop):
        call_model(vm, V.EXTERNALS['_getenv'], name)
