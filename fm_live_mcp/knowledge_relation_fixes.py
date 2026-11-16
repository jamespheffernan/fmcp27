"""Private overlay: two relation-mask corrections for the typed Passing collector.

Package copy of `evidence/knowledge-club-info-next-family-20261109/relation_fixes_overlay.py` (lane codex/continuous-knowledge-20261109, commit 268c3a2, SHA256 24d95c379ab72b04148888506531c01ce2a101731fdd73c6f25eaf1a24ded052); the code is unchanged.


Evidence-only subclass of the approved source. It does not alter immutable
public150/privatec66, the CLUB INFO overlay, the FOW overlay or any installed or
public source. It adds no attribute permission and calls no game function.

1. A subject with no stored TEAM has no recent-node source. The original
   relation function returns mask 0 for it, exactly as the passive composition
   in knowledge_relation_mask_source does. The selector subclass returned Python
   None for that branch, which the contextual score rejected as a non-integer.
2. For a club whose nation is 0x186 or 0x16c the original special-country helper
   at RVA 0xe02f00 is replayed from the hash-pinned original ARM64 bytes in a
   private Unicorn VM. Its reads come from the checked source reader, one
   access at a time. A return of null yields None. Reaching the helper's
   CLUB-by-UID lookup (any BL) refuses, as does any other unproved behaviour.
"""
from unicorn import (Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ,
                     UC_HOOK_MEM_WRITE, UC_HOOK_MEM_UNMAPPED)
import unicorn.arm64_const as regs

NAME = 'relation_mask_special_club_association_and_fixture_replay'
SPECIAL_NATIONS = (0x186, 0x16c)
FUNCTION = (0xe02f00, 0x37c, 'c1f776b1d5e02e58ee2609ce177e96a3389bd77306838251656d05f1c3e26ef9')
# Private windows of the replay VMs, above any address the game maps (the reader's PropertyVM
# keeps its private memory at 0x7E00_0000_0000 for the same reason). They were 0x200000000 and
# 0x300000000, below the plugin image the old check required, and the 27.0.1 session loaded the
# plugin at 0x159EB0000: every lazy replay refused (12 November 2026).
STACK = 0x7D00_0000_0000
MONITOR = 0x7D00_1000_0000
IMAGE_SPAN = 0x800_0000      # bound of the plugin image (0x58F4000 on 27.0.0, 0x5990000 on 27.0.1)
INSTRUCTION_LIMIT = 400
RET = 0xd65f03c0
TEXT = (0x55c0, 0x50d7920)  # original executable span: __text plus the __stubs section, arm64 slice
LAZY_INSTRUCTION_LIMIT = 200000
LAZY_READ_LIMIT = 20000
ASSOCIATION = (0x148a068, 0x2cc, '92d0cfa708412a836ee68b5cd64c1456730a4577b0d3c6e1fda6a7dfa657005c')
NEXT_FIXTURE_RVA = 0x17743b8
# Owning-thread guard of the fixture producer (and nothing else): two libc stubs are modelled as
# "the evaluating thread is the game's owning thread", the context in which the UI computes K.
THREAD_FLAG = 0x56c10e8
THREAD_MAIN = 0x56c10f0
THREAD_OTHER = 0x56d66b0
# Only the owning-thread guard of the fixture producer may reach the modelled stubs (checked by caller).
SELF_CALLERS = (0x17743ec, 0x17743fc)
EQUAL_CALLERS = (0x1774408,)
PTHREAD_SELF_STUB = 0x4aef0e0
PTHREAD_EQUAL_STUB = 0x4aeefd8
GAME_TEAM_RVA = 0x21eb7dc
GAME_SERVICE_GLOBAL = 0x56d2cf0  # native `adrp 0x56d2000; ldr [+0xcf0]` before the slot 0x98 dispatch
GAME_TEAM_SLOT = 0x98
RECEIPTS = []


def thread_stub_models(owner_global_rva):
    """Machine code replacing the _pthread_self and _pthread_equal stubs, keyed by RVA.

    _pthread_self becomes `adrp x0, page; ldr x0, [x0, #off]; ret` (12 bytes, the size of the
    original stub) so it returns the owning-thread word stored in the game's own global.
    """
    stub = PTHREAD_SELF_STUB
    pages = ((owner_global_rva & ~0xfff) - (stub & ~0xfff)) >> 12
    if not -(1 << 20) <= pages < (1 << 20) or owner_global_rva % 8:
        raise ValueError('Owning-thread global is out of adrp range or unaligned')
    imm = pages & 0x1fffff
    adrp = 0x90000000 | ((imm & 3) << 29) | ((imm >> 2) << 5)
    ldr = 0xf9400000 | (((owner_global_rva & 0xfff) >> 3) << 10)
    return {PTHREAD_SELF_STUB: b''.join(w.to_bytes(4, 'little') for w in (adrp, ldr, 0xd65f03c0)),
            PTHREAD_EQUAL_STUB: b''.join(w.to_bytes(4, 'little') for w in (0xeb01001f, 0x1a9f17e0, 0xd65f03c0))}


def _page(address):
    return address & ~4095


def _overlaps(start, size, other, other_size):
    return start < other + other_size and other < start + size


def replay_special_club(source, club_address, SourceUnavailable):
    """Run original e02f00 for one CLUB; return 0 only when it returns null."""
    rva, size, _ = FUNCTION
    start = source.base + rva
    # Executable bytes: the whole pinned function, read once through the checked reader.
    code = source.read(start, size)
    if __import__('hashlib').sha256(code).hexdigest() != FUNCTION[2]:
        raise SourceUnavailable('Special-country helper bytes differ from the pinned original')
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    mapped = set()
    refused = []
    trace = []
    reads = []

    def ensure(address, length):
        for page in range(_page(address), _page(address + length - 1) + 4096, 4096):
            if page not in mapped:
                uc.mem_map(page, 4096)
                mapped.add(page)

    ensure(start, size)
    uc.mem_write(start, code)
    for page in range(STACK, STACK + 0x10000, 4096):
        uc.mem_map(page, 4096)
        mapped.add(page)
    uc.mem_map(MONITOR, 4096)
    mapped.add(MONITOR)
    code_end = start + size

    def guard(callback):
        def hook(machine, *args):
            try:
                return callback(machine, *args)
            except Exception as exc:  # noqa: BLE001 - any failure refuses the replay
                refused.append(exc)
                machine.emu_stop()
                return False
        return hook

    @guard
    def on_code(machine, address, length, user):
        if address == MONITOR:
            machine.emu_stop()
            return
        if not start <= address < code_end or length != 4 or address % 4:
            raise SourceUnavailable('Special-country helper left its pinned original code')
        word = int.from_bytes(bytes(machine.mem_read(address, 4)), 'little')
        if word >> 26 == 0b100101:  # BL: the CLUB-by-UID lookup is not replayed
            raise SourceUnavailable('Special-country helper reached its unproved CLUB-by-UID lookup')
        trace.append(address - source.base)
        if len(trace) > INSTRUCTION_LIMIT:
            raise SourceUnavailable('Special-country helper instruction budget exceeded')

    @guard
    def on_read(machine, access, address, length, value, user):
        if STACK <= address < address + length <= STACK + 0x10000:
            return
        if start <= address < address + length <= code_end:
            return
        data = source.read(address, length)
        ensure(address, length)
        machine.mem_write(address, data)
        reads.append((address - source.base, length))

    @guard
    def on_write(machine, access, address, length, value, user):
        if not STACK <= address < address + length <= STACK + 0x10000:
            raise SourceUnavailable('Special-country helper wrote outside its private stack')

    @guard
    def on_unmapped(machine, access, address, length, value, user):
        # Pages are made only for the exact bytes about to be read; the read hook
        # then fills them from the checked reader before use.
        if access == 20 or access == 21:  # unmapped write or fetch
            raise SourceUnavailable('Special-country helper touched unmapped writable or code memory')
        ensure(address, length)
        machine.mem_write(address, source.read(address, length))
        reads.append((address - source.base, length))
        return True

    uc.hook_add(UC_HOOK_CODE, on_code)
    uc.hook_add(UC_HOOK_MEM_READ, on_read)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
    uc.hook_add(UC_HOOK_MEM_UNMAPPED, on_unmapped)
    uc.reg_write(regs.UC_ARM64_REG_SP, STACK + 0xf000)
    uc.reg_write(regs.UC_ARM64_REG_X30, MONITOR)
    uc.reg_write(regs.UC_ARM64_REG_X0, club_address)
    try:
        uc.emu_start(start, MONITOR)
    except Exception as exc:  # noqa: BLE001
        raise SourceUnavailable('Special-country helper replay refused: ' + str(refused[0] if refused else exc))
    if refused:
        raise refused[0]
    if uc.reg_read(regs.UC_ARM64_REG_PC) != MONITOR:
        raise SourceUnavailable('Special-country helper did not return to its monitor')
    if uc.reg_read(regs.UC_ARM64_REG_SP) != STACK + 0xf000:
        raise SourceUnavailable('Special-country helper returned without restored SP')
    return uc.reg_read(regs.UC_ARM64_REG_X0)


def replay_lazy(source, rva, arguments, SourceUnavailable, label, thread_model=False):
    """Run one original function with lazily read, checked bytes; no game write.

    Code pages in the original __text span are read whole through the checked
    reader (code is immutable and the receipt records each page's SHA256 for
    comparison with the on-disk plugin). Every data read is exact. Any write
    outside the private stack, any instruction outside __text, any instruction
    fault or budget excess refuses.
    """
    import hashlib
    base = source.base
    if _overlaps(base, IMAGE_SPAN, STACK, 0x10000) or _overlaps(base, IMAGE_SPAN, MONITOR, 4096):
        raise SourceUnavailable('Plugin base aliases the private VM windows')
    for argument in arguments:
        if argument >= 0x100000000 and (STACK <= argument < STACK + 0x10000 or MONITOR <= argument < MONITOR + 4096):
            raise SourceUnavailable('Argument aliases the private VM windows')
    text_start, text_end = base + TEXT[0], base + TEXT[1]
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    uc.ctl_set_cpu_model(regs.UC_CPU_ARM64_MAX)
    mapped = set()
    code_pages = {}
    refused = []
    state = dict(instructions=0, data_reads=0, data_bytes=0)
    tail = []

    def ensure(address, length):
        for page in range(_page(address), _page(address + length - 1) + 4096, 4096):
            if page not in mapped:
                uc.mem_map(page, 4096)
                mapped.add(page)

    models = {}
    if thread_model:
        flag = source.read(base + THREAD_FLAG, 1)[0]
        models.update({base + a: raw for a, raw in
                       thread_stub_models(THREAD_MAIN if flag == 1 else THREAD_OTHER).items()})

    def load_code(page):
        if page in code_pages:
            return
        ensure(page, 1)
        raw = source.read(page, 4096)
        uc.mem_write(page, raw)
        code_pages[page] = hashlib.sha256(raw).hexdigest()
        for address, replacement in models.items():
            if page <= address < page + 4096:
                uc.mem_write(address, replacement)

    for page in range(STACK, STACK + 0x10000, 4096):
        uc.mem_map(page, 4096)
        mapped.add(page)
    uc.mem_map(MONITOR, 4096)
    mapped.add(MONITOR)

    def guard(callback):
        def hook(machine, *args):
            try:
                return callback(machine, *args)
            except Exception as exc:  # noqa: BLE001 - any failure refuses the replay
                refused.append(exc)
                machine.emu_stop()
                return False
        return hook

    @guard
    def on_code(machine, address, length, user):
        if address == MONITOR:
            machine.emu_stop()
            return
        if not text_start <= address < text_end or length != 4 or address % 4:
            raise SourceUnavailable('Original replay left the original __text span at ' + hex(address - base))
        if thread_model:
            rel = address - base
            caller = machine.reg_read(regs.UC_ARM64_REG_X30) - base
            if rel == PTHREAD_SELF_STUB and caller not in SELF_CALLERS:
                raise SourceUnavailable('Modelled _pthread_self reached from an unproved caller ' + hex(caller))
            if rel == PTHREAD_EQUAL_STUB and caller not in EQUAL_CALLERS:
                raise SourceUnavailable('Modelled _pthread_equal reached from an unproved caller ' + hex(caller))
        state['instructions'] += 1
        tail.append(address - base)
        del tail[:-16]
        if state['instructions'] > LAZY_INSTRUCTION_LIMIT:
            raise SourceUnavailable('Original replay instruction budget exceeded')

    def is_code(address):
        return text_start <= address < text_end

    @guard
    def on_read(machine, access, address, length, value, user):
        if STACK <= address < address + length <= STACK + 0x10000:
            return
        if is_code(address):
            load_code(_page(address))
            if _page(address) != _page(address + length - 1):
                load_code(_page(address + length - 1))
            return
        state['data_reads'] += 1
        state['data_bytes'] += length
        if state['data_reads'] > LAZY_READ_LIMIT:
            raise SourceUnavailable('Original replay data-read budget exceeded')
        data = source.read(address, length)
        ensure(address, length)
        machine.mem_write(address, data)

    @guard
    def on_write(machine, access, address, length, value, user):
        if not STACK <= address < address + length <= STACK + 0x10000:
            raise SourceUnavailable('Original replay wrote outside its private stack: %s size %d at %s'
                                    % (hex(address), length, hex(machine.reg_read(regs.UC_ARM64_REG_PC) - base)))

    @guard
    def on_unmapped(machine, access, address, length, value, user):
        if access == 21:  # fetch from an unmapped page
            if not is_code(address):
                raise SourceUnavailable('Original replay fetched outside __text at ' + hex(address - base))
            load_code(_page(address))
            return True
        if access == 20:
            raise SourceUnavailable('Original replay wrote unmapped memory ' + hex(address))
        if is_code(address):
            load_code(_page(address))
            return True
        state['data_reads'] += 1
        state['data_bytes'] += length
        data = source.read(address, length)
        ensure(address, length)
        machine.mem_write(address, data)
        return True

    uc.hook_add(UC_HOOK_CODE, on_code)
    uc.hook_add(UC_HOOK_MEM_READ, on_read)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
    uc.hook_add(UC_HOOK_MEM_UNMAPPED, on_unmapped)
    uc.reg_write(regs.UC_ARM64_REG_SP, STACK + 0xf000)
    uc.reg_write(regs.UC_ARM64_REG_X30, MONITOR)
    for index, value in enumerate(arguments):
        uc.reg_write(getattr(regs, 'UC_ARM64_REG_X' + str(index)), value)
    entry = base + rva
    load_code(_page(entry))
    try:
        uc.emu_start(entry, MONITOR)
    except Exception as exc:  # noqa: BLE001
        reason = refused[0] if refused else exc
        raise SourceUnavailable('Original %s replay refused: %s (tail %s)' % (
            label, reason, [hex(x) for x in tail[-8:]]))
    if refused:
        raise refused[0]
    if uc.reg_read(regs.UC_ARM64_REG_PC) != MONITOR or uc.reg_read(regs.UC_ARM64_REG_SP) != STACK + 0xf000:
        raise SourceUnavailable('Original replay did not return to its monitor with restored SP')
    result = uc.reg_read(regs.UC_ARM64_REG_X0)
    RECEIPTS.append(dict(label=label, rva=hex(rva), arguments=[hex(a) for a in arguments], result=hex(result),
                         instructions=state['instructions'], data_reads=state['data_reads'],
                         data_bytes=state['data_bytes'],
                         thread_model=('owning_thread_pthread_self_equal' if thread_model else None),
                         code_pages={hex(p - base): h for p, h in sorted(code_pages.items())}))
    return result


def source_type(approved_source_type, relation):
    import hashlib
    rva, size, digest = FUNCTION
    if not issubclass(approved_source_type, relation.RelationSource) or \
            (rva, size, digest) not in relation.NATIVE_GUARDS:
        raise ValueError('Relation fixes overlay requires the pinned original relation source')
    core = relation.core

    class RelationFixesSource(approved_source_type):
        def _recent_fanout(self):
            result = super()._recent_fanout()
            # Only the "no stored TEAM" branch returned None; every other branch
            # returns an integer mask or refuses.
            return 0 if result is None else result

        def _special_club(self, club):
            nation = self.entity(self.ptr(club.address + 0xd8), 'nation')
            if not nation or self.u32(nation.address + 0xc) not in SPECIAL_NATIONS:
                return None
            if hashlib.sha256(self.read(self.base + rva, size)).hexdigest() != digest:
                raise core.SourceUnavailable('Special-country helper source changed')
            result = replay_special_club(self, club.address, core.SourceUnavailable)
            if result != 0:
                raise core.SourceUnavailable('Unproved nonnull special-country club resolution')
            return None

        def association(self, person):
            try:
                return super().association(person)
            except core.SourceUnavailable as exc:
                if not str(exc).startswith('Unproved148a068 fallback'):
                    raise
            arva, asize, adigest = ASSOCIATION
            if hashlib.sha256(self.read(self.base + arva, asize)).hexdigest() != adigest:
                raise core.SourceUnavailable('Association helper source changed')
            result = replay_lazy(self, arva, (person.person.address, 1), core.SourceUnavailable,
                                 'association_148a068_fallback')
            if result == 0:
                return None
            return self.entity(result, 'national_team_container')

        def _operand(self, name, *args):
            if name == 'next_fixture':
                team, days = args
                if type(days) is not int or not 0 < days <= 366:
                    raise core.SourceUnavailable('Unproved next-fixture day horizon')
                address = replay_lazy(self, NEXT_FIXTURE_RVA, (team.address, days), core.SourceUnavailable,
                                      'next_fixture_17743b8', thread_model=True)
                if address == 0:
                    return None
                # Opaque handle: the original function validates and consumes the object; only
                # its address is passed on, never interpreted here.
                return core.Ref(address, 'fixture', (0, (address & 0xfffffff8) | 1, 0))
            if name == 'game_team98':
                first, second, fixture = args
                # Native dispatches through the global game service object's vtable slot 0x98
                # (x0 = that object), so the dispatch bytes are consumed exactly as the original does.
                service = self.ptr(self.base + GAME_SERVICE_GLOBAL)
                if not service or service < 4096 or service % 8:
                    raise core.SourceUnavailable('Game service object is absent or unaligned')
                self.route(self.ptr(service), GAME_TEAM_SLOT, GAME_TEAM_RVA)
                value = replay_lazy(self, GAME_TEAM_RVA,
                                    (service, first.address, second.address, fixture.address if fixture else 0),
                                    core.SourceUnavailable, 'game_team_21eb7dc')
                if value & 0xffffffff not in (0, 1):
                    raise core.SourceUnavailable('Original game-team helper returned a non-Boolean')
                return bool(value & 1)
            return super()._operand(name, *args)
    return RelationFixesSource
