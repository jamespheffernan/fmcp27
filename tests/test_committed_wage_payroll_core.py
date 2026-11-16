"""Owned synthetic graphs executing exact pinned native payroll code; no FM reads."""
import hashlib
import os
from pathlib import Path
import struct

import pytest

from fm_live_mcp import committed_wage_spending_core as core
from fm_live_mcp import committed_wage_payroll_core as payroll
from fm_live_mcp import database, players, world

import _pinned_build
BINARY = _pinned_build.PLUGIN

BASE = 0x180000000

@pytest.fixture(scope='module')
def image():
    if not BINARY.exists():
        pytest.skip('pinned native ARM64 source file is required for copied-code tests')
    with BINARY.open('rb') as f:
        assert hashlib.file_digest(f, 'sha256').hexdigest() == players.SHA256
    st = BINARY.stat()
    return (str(BINARY), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)

class Graph:
    def __init__(self, image, combined=False):
        self.image = image
        self.pages = {}
        self.static = {}
        self.next = 0x10000000
        self.club = self.alloc()
        self.finance = self.alloc()
        self.team = self.alloc()
        self.primary = self.alloc()
        self.common = self.primary+(0x370 if combined else 0x278)
        self.person = self.primary+(0x480 if combined else 0x388)
        self.contract = self.alloc()
        self.ext = self.alloc()
        self.service = self.alloc()
        self.put(self.service, '<Q', BASE+0x55dfcf8)
        self.put(BASE+0x56d2c68, '<Q', self.service)
        self.put(self.club, '<QIII', BASE+world.TYPES['club'][0], 0, 20, 20)
        self.put(self.club+0x150, '<Q', self.finance)
        self.put(self.club+0x100, '<Q', self.ext)
        self.put(self.finance, '<Q', BASE+world.TYPES['club_finance'][0])
        self.put(self.finance+0x818, '<4i', 91, 92, 93, 94)
        self.put(self.ext+0x88, '<I', (2030<<16)|100)
        self.put(self.team, '<QIII', BASE+world.TYPES['team'][0], 0, 30, 30)
        self.put(self.team+0x30, '<Q', self.club)
        self.put(self.primary, '<Q', BASE+(players.STAFF_RVA[0] if combined else players.RVA[0]))
        self.put(self.common, '<Q', BASE+(0x558fbf0 if combined else 0x5589a90))
        self.put(self.person, '<QIII', BASE+(players.STAFF_RVA[2] if combined else players.RVA[2]), 0, 40, 40)
        self.put(self.common+0x78, '<Q', self.contract)
        self.put(self.contract, '<QQQ', BASE+world.TYPES['full_contract'][0], self.person, self.team)
        self.put(self.contract+0x20, '<i', 1200)
        self.put(self.contract+0x48, '<I', (2030<<16)|130)
        self.vector(self.club+0x18, [self.team])
        self.vector(self.team+0x38, [self.primary])
        self.table('clubs', [self.club])
        self.table('people', [self.person])
        self.table('teams', [self.team])
        self.put(BASE+0x56d34e0, '<B', 1)
        self.put(BASE+0x56d497d, '<B', 0)
        self.put(BASE+0x56d4950, '<B', 0)
        self.put(BASE+world.CURRENT_DATE, '<I', (2030<<16)|100)
        manager = self.alloc()
        self.put(manager, '<Q', BASE+world.TYPES['transfer_manager'][0])
        self.put(manager+0x18, '<Q', BASE+0x55f9ad0)
        self.put(BASE+0x56a49f8, '<Q', manager)
        self.put(BASE+0x56a4a90, '<Q', self.alloc())
        self.selected = ()
        with open(image[0], 'rb') as file:
            self.bindings = core._StaticBindings(file, BASE)
            # Keep a separate owned file descriptor for subsequent lazy pages.
            self.bindings.image = open(image[0], 'rb')

    def alloc(self):
        out = self.next
        self.next += 4096
        self.pages[out] = bytearray(4096)
        return out

    def put(self, address, fmt, *values):
        data = struct.pack(fmt, *values)
        for i, value in enumerate(data):
            page = (address+i) & -4096
            self.pages.setdefault(page, bytearray(4096))[(address+i) % 4096] = value

    def vector(self, address, values, stride=8):
        start = self.alloc()
        for i, value in enumerate(values):
            self.put(start+i*stride, '<Q', value)
        self.put(address, '<QQQ', start, start+len(values)*stride, start+len(values)*stride)
        return start

    def table(self, kind, values):
        root = self.alloc()
        header = self.alloc()
        start = self.vector(header, values)
        root_rva, table_rva, _ = database.TABLES[kind]
        self.put(BASE+root_rva, '<Q', root)
        self.put(root, '<Q', BASE+table_rva)
        self.put(root+0x88, '<Q', header)
        self.put(root+0x68, '<QQQ', start, start+8*len(values), start+8*len(values))

    def read(self, address, size):
        result = bytearray()
        while size:
            page = address & -4096
            length = min(size, 4096-address%4096)
            if page in self.pages:
                raw = self.pages[page]
            elif BASE <= page < BASE+0x56a4000:
                if page not in self.static:
                    with open(self.image[0], 'rb') as f:
                        f.seek(core.ffp.ARM_SLICE+page-BASE)
                        raw = bytearray(f.read(4096))
                    assert len(raw) == 4096
                    # Test-fixture relocation of the pinned file's static local
                    # chained pointers. Runtime code never manufactures these.
                    if page-BASE >= core.ffp.TEXT_END:
                        raw = self.bindings.relocated(page-BASE, 4096, leave_imports=True)
                    self.static[page] = bytes(raw)
                raw = self.static[page]
            else:
                raise ValueError(f'unavailable synthetic source {address:#x}')
            result.extend(raw[address%4096:address%4096+length])
            address += length
            size -= length
        return bytes(result)

    def run(self, **kwargs):
        return payroll.calculate(self.read, BASE, self.image, club=self.club,
                                 lifetime=lambda: ('fixture', 1), **kwargs)


def base_service(graph):
    service = graph.alloc()
    graph.put(service, '<Q', BASE+0x55DFBD8)
    graph.put(BASE+0x56D2B10, '<Q', service)
    return service


@pytest.mark.parametrize('combined', (False, True))
def test_full_native_payroll_recomputes_actual_and_combined_wages_not_old_cache(image, combined):
    graph = Graph(image, combined)
    base_service(graph)
    graph.put(graph.finance+0x810, '<ii', 9_999_999, -1001)
    result = graph.run()
    assert (result.spending_signed32, result.field_810, result.field_814) == (1200, 1200, 1200)
    assert result.basis == 'host_recomputed_full_E830E4'
    assert result.field_820 == 1200
    assert struct.unpack('<ii', graph.read(graph.finance+0x810, 8)) == (9_999_999, -1001)
    graph.put(graph.contract+0x20, '<i', 1701)
    assert graph.run().spending_signed32 == 1701


@pytest.mark.parametrize('adjustment', (0, 1, -1, 2_147_483_647, -2_147_483_648))
def test_actual_base_service_adjustment_and_signed_native_addition_are_not_a_zero_stub(image, adjustment):
    graph = Graph(image)
    base_service(graph)
    manager = struct.unpack('<Q', graph.read(BASE+0x56A49F8, 8))[0]
    record = graph.alloc()
    graph.put(record+8, '<Q', graph.club)
    graph.put(record+0x14, '<i', adjustment)
    graph.vector(manager+0xF0, [record])
    result = graph.run()
    expected = ((1200+adjustment+2**31) % 2**32)-2**31
    assert (result.spending_signed32, result.field_810, result.field_814) == (expected,)*3


def test_empty_native_rosters_produce_zero_without_consuming_unreached_service_or_pending_cache(image):
    graph = Graph(image)
    graph.vector(graph.club+0x18, [])
    graph.put(graph.finance+0x810, '<ii', 123, 456)
    graph.put(BASE+0x56D2C68, '<Q', 3)
    graph.put(BASE+0x56D2B10, '<Q', 5)
    result = graph.run()
    assert result.spending_signed32 == 0
    assert result.pending_reducer_ran is False
    assert (result.field_818, result.field_81c, result.field_820, result.field_824) == (None,)*4


@pytest.mark.parametrize('bad', ('full_type', 'base_alias', 'full_dispatch', 'team_owner', 'person_slot', 'contract_owner'))
def test_reached_wrong_sources_and_owner_links_reject_instead_of_publishing_payroll(image, bad):
    graph = Graph(image)
    base_service(graph)
    if bad == 'full_type':
        graph.put(graph.service, '<Q', BASE+0x55DFBD8)
    elif bad == 'base_alias':
        graph.put(BASE+0x56D2C68, '<Q', struct.unpack('<Q', graph.read(BASE+0x56D2B10, 8))[0])
    elif bad == 'full_dispatch':
        graph.put(BASE+0x55DFCF8+0x88, '<Q', BASE+0x1FFE470)
    elif bad == 'team_owner':
        graph.put(graph.team+0x30, '<Q', 0)
    elif bad == 'person_slot':
        graph.put(graph.person+8, '<I', 1)
    else:
        graph.put(graph.contract+8, '<Q', graph.person+8)
    with pytest.raises(ValueError):
        graph.run()


def test_original_getter_gate_refuses_unproved_thread_context_without_returning_cache(image):
    graph = Graph(image)
    graph.put(BASE+0x56C10E8, '<B', 1)
    graph.put(BASE+0x56C10F0, '<Q', 0x12345678)
    graph.put(graph.finance+0x814, '<i', 999999)
    with pytest.raises(ValueError, match='thread/HUMAN'):
        graph.run(recompute=False)


def test_final_lifetime_callback_mutating_consumed_source_rejects_after_callback(image):
    graph = Graph(image)
    base_service(graph)
    calls = 0

    def lifetime():
        nonlocal calls
        calls += 1
        if calls == 2:
            graph.put(graph.contract+0x20, '<i', 1701)
        return ('same-life', 1)

    with pytest.raises(ValueError, match='changed'):
        payroll.calculate(graph.read, BASE, image, club=graph.club, lifetime=lifetime)
    assert calls == 2


def test_lifetime_identity_change_rejects_even_when_cash_bytes_are_unchanged(image):
    graph = Graph(image)
    base_service(graph)
    calls = 0

    def lifetime():
        nonlocal calls
        calls += 1
        return ('life', calls)

    with pytest.raises(ValueError, match='lifetime changed'):
        payroll.calculate(graph.read, BASE, image, club=graph.club, lifetime=lifetime)


def test_unreached_rule_source_is_lazy_but_same_reached_mutation_rejects(image):
    graph = Graph(image)
    base_service(graph)
    graph.put(BASE+0x13E798C, '<I', 0)
    assert graph.run().spending_signed32 == 1200
    wrapper, container = graph.alloc(), graph.alloc()
    graph.put(graph.club+0xD8, '<Q', wrapper)
    graph.put(wrapper+0x110, '<Q', container)
    graph.put(container, '<QIII', BASE+world.TYPES['national_team_container'][0], 0, 500, 500)
    graph.table('national_team_containers', [container])
    with pytest.raises(ValueError, match='code binding changed'):
        graph.run()


@pytest.mark.parametrize('budget', ('MAX_READ_BYTES', 'MAX_READ_CALLS', 'MAX_INSTRUCTIONS'))
def test_finite_execution_and_read_budgets_cannot_publish_partial_amount(image, monkeypatch, budget):
    graph = Graph(image)
    base_service(graph)
    monkeypatch.setattr(payroll, budget, 0)
    with pytest.raises(ValueError, match='bound'):
        graph.run()


@pytest.mark.parametrize('kwargs', ({'recompute': 1}, {'total_spending': False}, {'total_spending': 1}))
def test_getter_selector_is_exact_boolean_and_preserves_native_810_selection(image, kwargs):
    graph = Graph(image)
    base_service(graph)
    if kwargs == {'total_spending': False}:
        assert graph.run(**kwargs).spending_signed32 == 1200
    else:
        with pytest.raises(ValueError, match='controls'):
            graph.run(**kwargs)


@pytest.mark.parametrize('mode', (0, 1, 2, 3, 4, 255))
def test_native_loan_contribution_is_recomputed_into_current_payroll(image, mode):
    graph = Graph(image)
    base_service(graph)
    loan, holder = graph.alloc(), graph.alloc()
    graph.put(loan, '<QQQ', BASE+world.TYPES['loan_contract'][0], graph.person, graph.team)
    graph.put(loan+0x20, '<i', 300)
    graph.put(loan+0xD4, '<i', 125)
    graph.put(holder, '<Q', loan)
    graph.put(graph.common+0x80, '<Q', holder)
    graph.put(BASE+0x56D497D, '<B', 1)
    graph.put(BASE+0x56D4950, '<B', mode)
    result = graph.run()
    assert result.field_814 == (1500 if mode in (1, 2, 3) else 1325)
    assert result.spending_signed32 == result.field_814


def test_all_club_roster_slots_and_aliases_reach_native_producer_in_original_order(image):
    graph = Graph(image)
    base_service(graph)
    graph.vector(graph.team+0x38, [graph.primary, graph.primary])
    result = graph.run()
    assert (result.field_810, result.field_814) == (2400, 2400)
    assert result.field_820 == 2400


@pytest.mark.parametrize('bad', ('club_finance_null', 'base_finance', 'roster_bounds', 'short_read'))
def test_no_false_zero_for_missing_or_unsupported_source_graph(image, bad):
    graph = Graph(image)
    base_service(graph)
    if bad == 'club_finance_null':
        graph.put(graph.club+0x150, '<Q', 0)
    elif bad == 'base_finance':
        graph.put(graph.finance, '<Q', BASE+world.TYPES['club_finance_base'][0])
    elif bad == 'roster_bounds':
        graph.put(graph.team+0x38, '<QQQ', 0x40000000, 0x3FFFFFF8, 0x40000000)
    if bad == 'short_read':
        def read(address, count):
            raw = graph.read(address, count)
            return raw[:-1] if address == graph.club+0x150 else raw
    else:
        read = graph.read
    with pytest.raises(ValueError):
        payroll.calculate(read, BASE, image, club=graph.club, lifetime=lambda: ('life', 1))


def test_pointer_metadata_reads_are_chunked_below_actual_bridge_limit():
    data = bytes(range(256))*100
    calls = []
    def read(address, count):
        assert count <= 8192
        calls.append((address, count))
        return data[address-0x10000:address-0x10000+count]
    assert payroll._chunks(read, 0x10000, len(data)) == data
    assert len(calls) == 4


def test_final_callback_can_change_unconsumed_page_padding_without_falsifying_source_drift(image):
    graph = Graph(image)
    base_service(graph)
    count = 0
    def lifetime():
        nonlocal count
        count += 1
        if count == 2:
            graph.put(graph.finance+0x800, '<I', 0xDEADBEEF)
        return ('same', 1)
    result = payroll.calculate(graph.read, BASE, image, club=graph.club, lifetime=lifetime)
    assert result.spending_signed32 == 1200 and count == 2


def pending_offer(graph, amount=1500):
    manager = struct.unpack('<Q', graph.read(BASE+0x56A49F8, 8))[0]
    offer, proposed, wrapper, holder = (graph.alloc() for _ in range(4))
    graph.put(offer, '<Q', BASE+0x55C7FD8)
    graph.put(offer+8, '<I', 10)
    graph.put(offer+0x38, '<QQQQ', graph.person, graph.team, 0, graph.team)
    graph.put(offer+0x7C, '<I', (2030<<16)|100)
    graph.put(offer+0x8D, '<BB', 19, 1)
    graph.put(proposed, '<QQQ', BASE+world.TYPES['full_contract'][0], graph.person, graph.team)
    graph.put(proposed+0x20, '<i', amount)
    graph.put(proposed+0x26, '<B', 1)
    graph.put(wrapper, '<I', 10)
    graph.put(wrapper+0x10, '<Q', proposed)
    graph.vector(holder, [wrapper])
    graph.put(graph.common+0x70, '<Q', holder)
    graph.vector(manager+0x20, [offer])
    return offer, proposed


def test_nonempty_native_selector_and_reducer_compose_with_current_payroll_without_applying_new_terms(image):
    graph = Graph(image)
    base_service(graph)
    offer, proposed = pending_offer(graph)
    result = graph.run()
    assert result.spending_signed32 == 1200
    assert result.pending_reducer_ran is True
    assert result.field_818 == 1500
    graph.put(proposed+0x20, '<i', 1701)
    changed = graph.run()
    assert changed.spending_signed32 == 1200
    assert changed.field_818 == 1701
    assert struct.unpack('<I', graph.read(offer+8, 4))[0] == 10


@pytest.mark.parametrize('offset,size,allowed', (
    (0x838, 8, True), (0x83C, 4, True), (0x844, 8, True), (0x848, 4, True),
    (0x840, 4, False), (0x84C, 4, False), (0x83F, 2, False), (0x84B, 2, False)))
def test_local_finance_store_guard_admits_exact_native_targets_and_rejects_adjacent_gaps(image, offset, size, allowed):
    graph = Graph(image)
    with open(image[0], 'rb') as native:
        cpu = payroll._PayrollCPU(world.ReadSet(graph.read), graph.read,
                                  BASE, native, graph.finance, graph.club)
        try:
            if allowed:
                cpu._store(cpu.vm, None, graph.finance+offset, size, 0, None)
            else:
                with pytest.raises(ValueError, match='unproved local source store'):
                    cpu._store(cpu.vm, None, graph.finance+offset, size, 0, None)
        finally:
            cpu.close()
