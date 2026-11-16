"""PropertyVM mechanics and variant decoding on synthetic code and memory (no game needed)."""
import struct
from types import SimpleNamespace

import pytest

from fm_live_mcp.fmdb import fastvm, variant
from fm_live_mcp.fmdb.vm import (HEAP, PropertyVM, Unavailable, VARIANT_REGISTRY_RVA, _Stop)

# Every test runs on PropertyVM and on FastVM (C accelerator; skipped when it is not built).
VMS = [pytest.param(PropertyVM, id='classic'),
       pytest.param(fastvm.FastVM, id='fast', marks=pytest.mark.skipif(
           not fastvm.available(), reason='build/libfm_vm_accel.dylib is not built'))]

BASE = 0x10_0000_0000
TEXT_SIZE = 0x10000
REGISTRY = 0x20_0000_1000
STUBS = {0x8000: '_malloc', 0x800C: '_frobnicate'}


def words(*ws):
    return b''.join(struct.pack('<I', w) for w in ws)


LDR_X9_X0_8, LDR_X10_X0_16 = 0xF9400409, 0xF940080A
STR_X9_X2, STR_X10_X2_8 = 0xF9000049, 0xF900044A
STR_W10_X0_32, MOV_W0_1, RET = 0xB900200A, 0x52800020, 0xD65F03C0
GETTER = words(LDR_X9_X0_8, LDR_X10_X0_16, STR_X9_X2, STR_X10_X2_8, MOV_W0_1, RET)
WRITING_GETTER = words(LDR_X9_X0_8, LDR_X10_X0_16, STR_W10_X0_32, STR_X9_X2, STR_X10_X2_8, MOV_W0_1, RET)


def branch(src, dst):
    return 0x14000000 | (((dst - src) >> 2) & 0x3FFFFFF)


class Memory:
    """Page-granular fake process memory; it has no write method at all."""

    def __init__(self):
        self.pages = {}
        self.reads = 0

    def put(self, address, data):
        for i, byte in enumerate(data):
            page = (address + i) & ~0xFFF
            self.pages.setdefault(page, bytearray(4096))[(address + i) & 0xFFF] = byte

    def read(self, address, length):
        self.reads += 1
        out = bytearray()
        for a in range(address, address + length):
            page = self.pages.get(a & ~0xFFF)
            if page is None:
                raise OSError(f'unmapped {a:#x}')
            out.append(page[a & 0xFFF])
        return bytes(out)


class Image:
    def __init__(self, code):
        self.text = bytearray(TEXT_SIZE)
        for rva, data in code.items():
            self.text[rva:rva + len(data)] = data
        for rva in range(0x8000, 0x8100, 4):
            self.text[rva:rva + 4] = struct.pack('<I', 0xD503201F)  # nop
        self.text_range = (0x1000, 0x8100)
        self.stub_range = (0x8000, 0x8100)
        self.stubs, self.binds = dict(STUBS), {}

    def segment(self, name):
        return SimpleNamespace(vmsize=TEXT_SIZE)

    def file_bytes(self, rva, length):
        return bytes(self.text[rva:rva + length])


TRAITS = {  # registry offset -> RTTI name
    0x08: 'N6sicore17NULL_TYPED_TRAITSE', 0x18: 'N6sicore16RAW_TYPED_TRAITSIbEE',
    0x28: 'N6sicore16RAW_TYPED_TRAITSIiEE', 0x48: 'N6sicore16RAW_TYPED_TRAITSIxEE',
    0x68: 'N6sicore16RAW_TYPED_TRAITSIfEE', 0x88: 'N6sicore19STRING_TYPED_TRAITSE',
    0x98: 'N6sicore19SYMBOL_TYPED_TRAITSE',
    0xA8: 'N6sicore28INTERNAL_OBJECT_TYPED_TRAITSINS_10TYPED_LISTELh11EEE',
    0xB8: 'N6sicore28INTERNAL_OBJECT_TYPED_TRAITSINS_6RECORDELh10EEE',
}


@pytest.fixture(params=VMS)
def world(request):
    m = Memory()
    m.put(BASE + VARIANT_REGISTRY_RVA, struct.pack('<Q', REGISTRY))
    m.put(REGISTRY, bytes(0xE0))
    for i, (offset, name) in enumerate(TRAITS.items()):
        vtable = 0x20_0001_0000 + i * 0x100
        info, text = vtable + 0x80, vtable + 0xA0
        m.put(vtable - 8, struct.pack('<QQQQQ', info, 0, 0, 0, 0))
        m.put(info + 8, struct.pack('<Q', text))
        m.put(text, name.encode() + b'\0')
        m.put(REGISTRY + offset, struct.pack('<QB', vtable, i))
    code = {0x1000: GETTER, 0x1100: words(branch(0x1100, 0x1100)),
            0x1200: words(0xD2800400, branch(0x1204, 0x8000)),      # mov x0,#0x20; b _malloc
            0x1300: words(branch(0x1300, 0x800C)),                   # b _frobnicate
            0x1400: words(0xF940000B, RET),                          # ldr x11,[x0]; ret
            0x1500: words(0x9100A008, 0xD61F0100),                   # add x8,x0,#0x28; br x8
            0x1600: WRITING_GETTER}
    vm = request.param(m, BASE, Image(code), view='game', budget=10_000)
    return SimpleNamespace(m=m, vm=vm, fast=request.param is not PropertyVM)


def record(world, address, getter_rva, traits_offset, payload, extra=b''):
    vtable = address + 0x800
    world.m.put(vtable, struct.pack('<QQQQ', 0, 0, 0, BASE + getter_rva))
    world.m.put(address, struct.pack('<QQQ', vtable, REGISTRY + traits_offset, payload) + extra)
    return address


def test_int_and_negative_int(world):
    r = record(world, 0x30_0000_0000, 0x1000, 0x28, 0xFFFFFF85)
    result = world.vm.get_property(r, 'PCAB')
    assert (result.kind, result.value, result.handled) == ('int', -123, True)
    assert result.stats.instructions == 6


def test_string_float_bool(world):
    text = 0x30_0001_0000
    world.m.put(text, struct.pack('<I', 5) + 'Ghënt'.encode()[:5])
    world.m.put(text, struct.pack('<I', 6) + 'Ghënt'.encode())
    r = record(world, 0x30_0000_0000, 0x1000, 0x88, text)
    assert world.vm.get_property(r, 'Cnam').value == 'Ghënt'
    r = record(world, 0x30_0002_0000, 0x1000, 0x68, struct.unpack('<I', struct.pack('<f', 51.25))[0])
    assert world.vm.get_property(r, 'Clat').value == 51.25
    r = record(world, 0x30_0003_0000, 0x1000, 0x18, 1)
    assert world.vm.get_property(r, 'DELE').value is True


def test_writes_stay_in_the_vm_and_are_rolled_back(world):
    r = record(world, 0x30_0000_0000, 0x1600, 0x28, 77, extra=b'\0' * 0x20)
    assert world.vm.get_property(r, 'Xxxx').value == 77
    assert struct.unpack('<I', world.vm.read(r + 0x20, 4))[0] == 77      # VM copy written
    assert world.m.read(r + 0x20, 4) == b'\0' * 4                          # game memory untouched
    world.vm.call(BASE + 0x1000, (r, 0, HEAP + 0x100))
    assert world.vm.read(r + 0x20, 4) == b'\0' * 4                          # rolled back next call


def test_modelled_external_allocates_on_the_vm_heap(world):
    value, stats = world.vm.call(BASE + 0x1200)
    assert value == HEAP and stats.externals == ['_malloc']
    assert world.vm.stubbed['_malloc'] == 1


@pytest.mark.parametrize('rva,args,reason', [
    (0x1300, (), 'external call _frobnicate'),
    (0x1100, (), 'instruction budget exceeded'),
    (0x1400, (0,), 'null or low pointer dereference'),
    (0x1500, (0x30_0000_0000,), 'call into non-plugin code'),
])
def test_failures_are_typed(world, rva, args, reason):
    world.m.put(0x30_0000_0000, bytes(64))
    with pytest.raises(_Stop) as stop:
        world.vm.call(BASE + rva, args)
    assert stop.value.reason == reason


def test_failure_through_get_property_is_unavailable(world):
    r = record(world, 0x30_0000_0000, 0x1100, 0x28, 1)
    result = world.vm.get_property(r, 'PCAB')
    assert isinstance(result.value, Unavailable) and result.value.reason == 'instruction budget exceeded'
    assert not result.ok


def test_unreadable_live_memory_is_unavailable(world):
    with pytest.raises(_Stop) as stop:
        world.vm.call(BASE + 0x1400, (0x40_0000_0000,))
    assert stop.value.reason == 'unreadable live memory'


def typed(world, address, traits_offset, payload):
    world.m.put(address, struct.pack('<QQ', REGISTRY + traits_offset, payload))
    return address


def test_record_reference(world):
    value = typed(world, 0x50_0000_0100, 0x48, (99 << 32) | 757)
    world.m.put(0x50_0000_0200, struct.pack('<I4xQ', int.from_bytes(b'Nnat', 'big'), value))
    world.m.put(0x50_0000_0300, struct.pack('<QQQ', 0x50_0000_0200, 0x50_0000_0210, 0x50_0000_0210))
    out = typed(world, 0x50_0000_0000, 0xB8, 0x50_0000_0300)
    assert variant.decode(world.vm, out) == ('record_ref', variant.RecordRef('Nnat', 757, 99))


def test_multi_entry_record_and_list(world):
    a = typed(world, 0x50_0000_0100, 0x28, 3)
    b = typed(world, 0x50_0000_0110, 0x88, 0)
    world.m.put(0x50_0000_0200, struct.pack('<I4xQI4xQ', int.from_bytes(b'year', 'big'), a,
                                            int.from_bytes(b'name', 'big'), b))
    world.m.put(0x50_0000_0300, struct.pack('<QQQ', 0x50_0000_0200, 0x50_0000_0220, 0x50_0000_0220))
    out = typed(world, 0x50_0000_0000, 0xB8, 0x50_0000_0300)
    assert variant.decode(world.vm, out) == ('record', {'year': 3, 'name': ''})
    world.m.put(0x50_0000_0500, struct.pack('<QQ', a, b))
    world.m.put(0x50_0000_0400, struct.pack('<QQQ', 0x50_0000_0500, 0x50_0000_0510, 0x50_0000_0510))
    out = typed(world, 0x50_0000_0010, 0xA8, 0x50_0000_0400)
    world.vm.invalidate()  # pages are cached per VM session; new fake bytes need a new snapshot
    assert variant.decode(world.vm, out) == ('list', [3, ''])


def test_unknown_kind_keeps_raw_bytes(world):
    world.m.put(0x50_0000_0400, b'\xAB' * 64)
    out = typed(world, 0x50_0000_0000, 0x98, 0x50_0000_0400)
    kind, value = variant.decode(world.vm, out)
    assert kind == 'symbol' and isinstance(value, Unavailable)
    assert value.reason.startswith('variant kind 6') and value.raw[16:] == b'\xAB' * 64


def test_tracer_derives_a_direct_plan(world, monkeypatch):
    if world.fast:
        pytest.skip('the load tracer hooks PropertyVM (Engine.plan_tracer)')
    from fm_live_mcp.fmdb import plans, tables
    monkeypatch.setattr(tables, 'class_of', lambda read, base, record: ('SYNTH', 0))
    tracer = plans.Tracer(world.vm)
    records = [record(world, 0x30_0000_0000 + i * 0x1_0000, 0x1000, 0x28, value)
               for i, value in enumerate((5, 17, 200))]
    for r in records:
        assert tracer.get_property(r, 'Catt').value in (5, 17, 200)
    plan = tracer.plans()['SYNTH']['Catt']
    assert plan['status'] == 'direct' and plan['chain'] == [0x10] and plan['type'] == 'int'
    assert plans.apply(world.m.read, records[1], plan) == 17


def test_tracer_refuses_constant_samples(world, monkeypatch):
    if world.fast:
        pytest.skip('the load tracer hooks PropertyVM (Engine.plan_tracer)')
    from fm_live_mcp.fmdb import plans, tables
    monkeypatch.setattr(tables, 'class_of', lambda read, base, record: ('SYNTH', 0))
    tracer = plans.Tracer(world.vm)
    for i in range(3):
        tracer.get_property(record(world, 0x30_0000_0000 + i * 0x1_0000, 0x1000, 0x28, 9), 'Catt')
    assert tracer.plans()['SYNTH']['Catt']['status'] == 'emulate-only'


def test_si_date_packing():
    assert variant.si_date(0x0FA23700).iso == '2001-02-24'
    assert variant.si_date(0x0FA8FC00).iso == '2004-09-08'
    assert isinstance(variant.si_date(0x0FA20000), Unavailable)


def test_printf_model_formats_variadic_slots(world):
    from fm_live_mcp.fmdb import vm as vmmod
    fmt, args = 0x60_0000_0000, 0x60_0000_1000
    world.m.put(fmt, b'%s is %3d (%.1f%%) %lx\0')
    world.m.put(0x60_0000_2000, b'Gordon\0')
    world.m.put(args, struct.pack('<QQdQ', 0x60_0000_2000, 7, 88.25, 0xBEEF))
    world.m.put(fmt + 0x100, b'%n\0')
    assert vmmod._format(world.vm, fmt, args) == b'Gordon is   7 (88.2%) beef'
    with pytest.raises(_Stop):
        vmmod._format(world.vm, fmt + 0x100, args)


def test_fast_vm_keeps_stores_out_of_later_calls_and_reuses_the_instance(world):
    """Copy-on-write across many calls, more written pages than stay writable, and a page drop."""
    if not world.fast:
        pytest.skip('FastVM mechanics')
    vm = world.vm
    records = [record(world, 0x30_0000_0000 + i * 0x10000, 0x1600, 0x28, 100 + i, extra=b'\0' * 0x20)
               for i in range(40)]                       # 40 pages written, 16 stay writable
    for round_ in range(3):
        for i, r in enumerate(records):
            assert vm.get_property(r, 'Xxxx').value == 100 + i
            assert struct.unpack('<I', vm.read(r + 0x20, 4))[0] == 100 + i
        vm.call(BASE + 0x1000, (records[0], 0, HEAP + 0x100))
        for r in records:
            assert vm.read(r + 0x20, 4) == b'\0' * 4          # every store rolled back
    before = len(vm.live_pages)
    assert before >= 40
    world.m.put(records[0] + 0x10, struct.pack('<Q', 555))   # the "game" changes a value
    assert vm.get_property(records[0], 'Xxxx').value == 100   # still the copied page
    vm.drop_live_pages()
    assert len(vm.live_pages) == 0
    assert vm.get_property(records[0], 'Xxxx').value == 555   # re-read from the reader
    assert vm.get_property(records[1], 'Xxxx').value == 101


def test_fast_vm_external_models_in_c_are_listed_in_call_order(world):
    if not world.fast:
        pytest.skip('FastVM mechanics')
    from fm_live_mcp.fmdb import vm as vm_module
    m = Memory()
    for address, pages in world.m.pages.items():
        m.pages[address] = bytearray(pages)
    image = Image({0x1000: GETTER,
                   # stp x29,x30,[sp,#-16]!; bl lock; bl malloc; bl unlock; ldp x29,x30,[sp],#16; ret
                   0x1700: words(0xA9BF7BFD, 0x94000000 | ((0x8018 - 0x1704) >> 2), 0x94000000 | ((0x8000 - 0x1708) >> 2),
                                 0x94000000 | ((0x8024 - 0x170C) >> 2), 0xA8C17BFD, RET)})
    image.stubs.update({0x8018: '_pthread_mutex_lock', 0x8024: '_pthread_mutex_unlock'})
    vm = fastvm.FastVM(m, BASE, image, view='game', budget=10_000)
    value, stats = vm.call(BASE + 0x1700)
    assert stats.externals == ['_pthread_mutex_lock', '_malloc', '_pthread_mutex_unlock']
    assert value == 0                                          # unlock's model returns 0
    assert vm.stubbed == {'_pthread_mutex_lock': 1, '_malloc': 1, '_pthread_mutex_unlock': 1}
    assert vm_module.EXTERNALS['_pthread_mutex_lock'] is vm_module._noop
