"""Synthetic typed graphs replayed through actual pinned ARM64 arithmetic.

These tests read only the installed file on disk. They never attach to FM and
are neither a current payroll read nor proof of native selector admission.
"""
import hashlib
import os
from pathlib import Path
import struct

import pytest

from fm_live_mcp import committed_wage_spending_core as core
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
        return core.calculate(self.read, BASE, self.image, club=self.club,
                              selected_offers=self.selected, lifetime=lambda: ('fixture', 1), **kwargs)


@pytest.mark.parametrize('combined', [False, True])
def test_actual_and_combined_roster_native_wage_is_classified(image, combined):
    graph = Graph(image, combined)
    result = graph.run()
    assert (result.field_818, result.field_81c, result.field_820, result.field_824,
            result.returned_signed32, result.roster_slots) == (0, 0, 1200, 0, 0, 1)
    assert struct.unpack('<4i', graph.read(graph.finance+0x818, 16)) == (91, 92, 93, 94)


def test_source_status_bit_moves_native_amount_into_debit_not_a_stubbed_total(image):
    graph = Graph(image)
    graph.put(graph.contract+0x57, '<B', 32)
    result = graph.run()
    assert (result.field_818, result.field_81c, result.field_820, result.field_824,
            result.returned_signed32) == (-1200, 0, 0, 0, -1200)
    graph.put(graph.contract+0x20, '<i', 1701)
    assert graph.run().field_818 == -1701


def test_long_contract_excludes_wage_while_retaining_existing_initial_fields_only_locally(image):
    graph = Graph(image)
    graph.put(graph.contract+0x48, '<I', (2031<<16)|130)
    result = graph.run()
    assert (result.field_818, result.field_81c, result.field_820, result.field_824) == (0, 0, 0, 0)


def add_offer(graph, *, trade=False):
    address = graph.alloc()
    graph.put(address, '<Q', BASE+(0x55c8808 if trade else 0x55c7fd8))
    graph.put(address+8, '<I', 1)
    graph.put(address+0x38, '<Q', graph.person)
    graph.put(address+0x40, '<Q', graph.team)
    graph.put(address+0x50, '<Q', graph.team)
    graph.put(address+0x7c, '<I', (2030<<16)|100)
    graph.put(address+0x8d, '<BB', 19, 1)
    if trade:
        graph.vector(address+0x90, [graph.person], stride=16)
        graph.vector(address+0xf0, [], stride=16)
    else:
        proposed = graph.alloc()
        graph.put(proposed, '<QQQ', BASE+world.TYPES['full_contract'][0], graph.person, graph.team)
        graph.put(proposed+0x20, '<i', 1500)
        graph.put(proposed+0x26, '<B', 1)
        wrapper = graph.alloc()
        graph.put(wrapper, '<I', 1)
        graph.put(wrapper+0x10, '<Q', proposed)
        holder = graph.alloc()
        graph.vector(holder, [wrapper])
        graph.put(graph.common+0x70, '<Q', holder)
    graph.vector(graph.team+0x38, [])
    graph.selected = (address,)
    return address


@pytest.mark.parametrize('trade,expected', [(True, 1200), (False, 1500)])
def test_typed_offer_native_arithmetic_and_ordered_duplicate_slots(image, trade, expected):
    graph = Graph(image)
    address = add_offer(graph, trade=trade)
    assert graph.run().field_818 == expected
    graph.selected = (address, 0, address)
    result = graph.run()
    assert result.field_818 == expected*2
    assert result.selected_offer_addresses == (address, 0, address)
    assert struct.unpack('<I', graph.read(address+8, 4))[0] == 1


@pytest.mark.parametrize('mode', range(256))
def test_loan_wage_branch_uses_exact_native_mode_boundary(image, mode):
    graph = Graph(image)
    loan = graph.alloc()
    graph.put(loan, '<QQQ', BASE+world.TYPES['loan_contract'][0], graph.person, graph.team)
    graph.put(loan+0x20, '<i', 300)
    graph.put(loan+0xd4, '<i', 125)
    holder = graph.alloc()
    graph.put(holder, '<Q', loan)
    graph.put(graph.common+0x80, '<Q', holder)
    graph.put(BASE+0x56d497d, '<B', 1)
    graph.put(BASE+0x56d4950, '<B', mode)
    assert graph.run().field_820 == (1500 if mode in (1, 2, 3) else 1325)


@pytest.mark.parametrize('days,flags,status,expected', [
    (89, 0, 0, (0, 0, 1200, 0)),
    (90, 0, 0, (0, 0, 0, 1200)),
    (183, 0, 0, (0, 0, 0, 1200)),
    (184, 0, 0, (0, 0, 0, 0)),
    (89, 32, 0, (-1200, 0, 0, 0)),
    (90, 32, 0, (0, 0, 1200, 0)),
    (89, 0, 1, (0, 0, 0, 1200)),
])
def test_exact_contract_threshold_and_status_classification(image, days, flags, status, expected):
    graph = Graph(image)
    graph.put(graph.contract+0x48, '<I', (2030<<16)|(100+days))
    graph.put(graph.contract+0x57, '<B', flags)
    graph.put(graph.contract+0x54, '<B', status)
    row = graph.run()
    assert (row.field_818, row.field_81c, row.field_820, row.field_824) == expected


@pytest.mark.parametrize('corruption', ['person_slot', 'team_owner', 'contract_owner', 'contract_type',
                                        'compact_team', 'roster_geometry', 'dispatch', 'native_code', 'vtable'])
def test_near_positive_source_corruptions_never_become_totals(image, corruption):
    graph = Graph(image)
    if corruption == 'person_slot':
        graph.put(graph.person+8, '<I', 1)
    elif corruption == 'team_owner':
        graph.put(graph.team+0x30, '<Q', 0)
    elif corruption == 'contract_owner':
        graph.put(graph.contract+8, '<Q', 0)
    elif corruption == 'contract_type':
        graph.put(graph.contract, '<Q', BASE+world.TYPES['club'][0])
    elif corruption == 'compact_team':
        graph.put(graph.team+0x2f, '<B', 1)
    elif corruption == 'roster_geometry':
        graph.put(graph.team+0x40, '<Q', 2)
    elif corruption == 'dispatch':
        graph.put(BASE+0x55dfcf8+0x88, '<Q', BASE+0x1fe8afc)
    elif corruption == 'native_code':
        page = (BASE+0xcc0014) & -4096
        graph.pages[page] = bytearray(graph.read(page, 4096))
        graph.put(BASE+0xcc0014, '<I', 0xd65f03c0)
    elif corruption == 'vtable':
        page = (BASE+0x558a780+0x3c0) & -4096
        graph.pages[page] = bytearray(graph.read(page, 4096))
        graph.put(BASE+0x558a780+0x3c0, '<Q', BASE+0xd5c5fc)
    with pytest.raises(ValueError):
        graph.run()


@pytest.mark.parametrize('change', ['lifetime', 'consumed_after_callback', 'unconsumed_padding'])
def test_lifetime_and_final_callback_order_do_not_hide_source_drift(image, change):
    graph = Graph(image)
    count = 0
    def lifetime():
        nonlocal count
        count += 1
        if count == 2:
            if change == 'consumed_after_callback':
                graph.put(graph.contract+0x20, '<i', 1300)
            elif change == 'unconsumed_padding':
                graph.put(graph.finance+0x900, '<B', 254)
        return ('fixture', count if change == 'lifetime' else 1)
    if change == 'unconsumed_padding':
        assert core.calculate(graph.read, BASE, image, club=graph.club,
                              selected_offers=(), lifetime=lifetime).field_820 == 1200
    else:
        with pytest.raises(ValueError, match='changed'):
            core.calculate(graph.read, BASE, image, club=graph.club,
                           selected_offers=(), lifetime=lifetime)


def test_unknown_cold_effective_team_is_unavailable_not_a_zero_total(image):
    graph = Graph(image)
    address = add_offer(graph, trade=True)
    graph.put(address+0x50, '<Q', 0)
    graph.put(address+0x8e, '<B', 0)
    with pytest.raises(core.SourceUnavailable, match='0x1869938'):
        graph.run()
    # Computed-null is an actual native branch, not the cold state.
    graph.put(address+0x8e, '<B', 1)
    assert graph.run().field_818 == 0


def test_selector_overlay_is_checked_and_cannot_substitute_a_subject(image):
    graph = Graph(image)
    address = add_offer(graph, trade=True)
    assert graph.run(selected_persons=(graph.person,)).field_818 == 1200
    with pytest.raises(core.SourceUnavailable, match='overlay disagrees'):
        graph.run(selected_persons=(0,))
    placeholder = graph.alloc()
    graph.put(placeholder+8, '<iI', 0, 0xffffffff)
    graph.put(address+0x38, '<Q', placeholder)
    assert graph.run(selected_persons=(graph.person,)).field_818 == 1200
    graph.put(placeholder+8, '<i', -1)
    assert graph.run(selected_persons=(0,)).field_818 == 0


def test_loan_expiry_uses_both_global_and_caller_dates_for_field_81c(image):
    graph = Graph(image)
    graph.put(graph.common+0x78, '<Q', 0)
    graph.put(graph.contract, '<Q', BASE+world.TYPES['loan_contract'][0])
    graph.put(graph.contract+0x48, '<I', (2030<<16)|200)
    graph.put(graph.ext+0x88, '<I', (2030<<16)|160)
    holder = graph.alloc()
    graph.put(holder, '<Q', graph.contract)
    graph.put(graph.common+0x80, '<Q', holder)
    row = graph.run()
    assert (row.field_818, row.field_81c, row.field_820, row.field_824) == (0, 1200, 0, 0)
    graph.put(graph.ext+0x88, '<I', (2030<<16)|140)
    assert graph.run().field_824 == 1200  # exactly60 uses the other accumulator


@pytest.mark.parametrize('wage,expected', [(-7, -14), (0x7fffffff, -2)])
def test_native_signed32_wrap_is_preserved_instead_of_cash_sanitization(image, wage, expected):
    graph = Graph(image)
    address = add_offer(graph, trade=True)
    graph.put(graph.contract+0x20, '<i', wage)
    graph.selected = (address, address)
    row = graph.run()
    assert row.field_818 == row.returned_signed32 == expected


def test_wrong_effective_team_near_a_valid_trade_is_not_accepted_as_same_owner(image):
    graph = Graph(image)
    address = add_offer(graph, trade=True)
    fake_team = graph.alloc()
    graph.put(fake_team, '<QIII', BASE+world.TYPES['team'][0], 0, 30, 30)
    graph.put(fake_team+0x30, '<Q', graph.club)
    graph.put(address+0x50, '<Q', fake_team)
    with pytest.raises(ValueError, match='canonical membership'):
        graph.run()


def test_code_image_fingerprint_and_stamp_are_checked(image, tmp_path):
    graph = Graph(image)
    bad = tmp_path/'wrong-native-image'
    bad.write_bytes(b'not an FM image')
    st = bad.stat()
    with pytest.raises(core.SourceUnavailable, match='fingerprint'):
        core.calculate(graph.read, BASE, (str(bad), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns),
                       club=graph.club, selected_offers=(), lifetime=lambda: ('fixture', 1))
    with pytest.raises(core.SourceUnavailable, match='image changed'):
        core.calculate(graph.read, BASE, image[:-1]+(image[-1]+1,), club=graph.club,
                       selected_offers=(), lifetime=lambda: ('fixture', 1))


def test_missing_source_and_malformed_selection_are_not_empty_results(image):
    graph = Graph(image)
    del graph.pages[graph.contract]
    with pytest.raises(ValueError, match='unavailable synthetic source'):
        graph.run()
    graph = Graph(image)
    for selected in ([], (False,), (1,), (True,)):
        with pytest.raises(ValueError):
            core.calculate(graph.read, BASE, image, club=graph.club,
                           selected_offers=selected, lifetime=lambda: ('fixture', 1))


@pytest.mark.parametrize('budget', ['MAX_INSTRUCTIONS', 'MAX_READ_BYTES', 'MAX_READ_CALLS'])
def test_positive_native_path_cannot_escape_finite_resource_bounds(image, monkeypatch, budget):
    graph = Graph(image)
    assert graph.run().field_820 == 1200
    monkeypatch.setattr(core, budget, 5)
    with pytest.raises(core.SourceUnavailable, match='bound'):
        graph.run()


def test_native_cold_allocator_cache_store_stays_outside_owned_financial_output(image):
    graph = Graph(image)
    graph.put(BASE+0x56a4a90, '<Q', 0)
    graph.put(BASE+0x56c1668, '<B', 1)
    with pytest.raises(core.SourceUnavailable, match='unproved local source store'):
        graph.run()
    assert graph.read(BASE+0x56a4a90, 8) == bytes(8)


def test_unavailable_lifetime_is_not_a_success_credential(image):
    graph = Graph(image)
    with pytest.raises(core.SourceUnavailable, match='lifetime is unavailable'):
        core.calculate(graph.read, BASE, image, club=graph.club,
                       selected_offers=(), lifetime=lambda: None)


def test_every_club_team_roster_slot_participates_without_deduplication(image):
    graph = Graph(image)
    second = graph.alloc()
    graph.put(second, '<QIII', BASE+world.TYPES['team'][0], 1, 31, 31)
    graph.put(second+0x30, '<Q', graph.club)
    graph.vector(second+0x38, [graph.primary])
    graph.vector(graph.club+0x18, [graph.team, second])
    graph.table('teams', [graph.team, second])
    row = graph.run()
    assert row.roster_slots == 2 and row.field_820 == 2400


def test_unconsumed_proposed_contract_collection_does_not_block_roster_wage(image):
    graph = Graph(image)
    graph.put(graph.common+0x70, '<Q', 0x12345000)
    assert graph.run().field_820 == 1200
    add_offer(graph)
    holder = struct.unpack('<Q', graph.read(graph.common+0x70, 8))[0]
    graph.put(holder+8, '<Q', 3)
    with pytest.raises(core.SourceUnavailable, match='vector geometry'):
        graph.run()


def test_stable_but_wrong_native_percentage_constant_is_rejected(image):
    graph = Graph(image)
    entry = graph.alloc()
    graph.put(entry, '<IhB', 0, 10, 20)
    graph.put(graph.contract+0x68, '<QQQ', entry, entry+8, entry+8)
    assert graph.run().field_820 > 0
    address = BASE+0x52f6f88
    page = address & -4096
    graph.pages[page] = bytearray(graph.read(page, 4096))
    graph.put(address, '<f', 0.0)
    with pytest.raises(core.SourceUnavailable, match='static table binding changed'):
        graph.run()


def test_null_trade_subject_does_not_consume_unreached_trade_vectors(image):
    graph = Graph(image)
    offer = add_offer(graph, trade=True)
    graph.put(offer+0x38, '<Q', 0)
    graph.put(offer+0x90, '<QQQ', 3, 2, 1)
    graph.put(offer+0xf0, '<QQQ', 3, 2, 1)
    assert graph.run().field_818 == 0
    graph.put(offer+0x38, '<Q', graph.person)
    with pytest.raises(core.SourceUnavailable, match='vector geometry'):
        graph.run()


@pytest.mark.parametrize('corruption', ['missing', 'base_type', 'wrong_slot', 'rtti',
                                        'displacement', 'name_pointer', 'name', 'caller'])
def test_actual_full_service_identity_is_required_for_the_same_positive_graph(image, corruption):
    graph = Graph(image)
    assert graph.run().field_820 == 1200
    if corruption == 'missing':
        graph.put(BASE+0x56d2c68, '<Q', 0)
    elif corruption == 'base_type':
        graph.put(graph.service, '<Q', BASE+0x55dfbd8)
    else:
        address, fmt, value = {
            'wrong_slot': (BASE+0x55dfcf8+0x88, '<Q', BASE+0x1febc8c),
            'rtti': (BASE+0x55dfcf8-8, '<Q', BASE+0x55dfbf0),
            'displacement': (BASE+0x55dfcf8-16, '<q', -8),
            'name_pointer': (BASE+0x55dff18+8, '<Q', BASE+0x53b1012),
            'name': (BASE+0x53b1011, '<B', ord('2')),
            'caller': (BASE+0xeaec3c, '<I', 0xd65f03c0),
        }[corruption]
        page = address & -4096
        graph.pages[page] = bytearray(graph.read(page, 4096))
        graph.put(address, fmt, value)
    with pytest.raises(core.SourceUnavailable, match='finance service|full-service caller'):
        graph.run()


def test_base_service_alias_is_not_the_actual_full_service_binding(image):
    graph = Graph(image)
    # The alias and actual full-table slot are the same physical cell. Its
    # shared target alone cannot establish the object's actual runtime type.
    assert BASE+0x55dfbd8+0x1a8 == BASE+0x55dfcf8+0x88
    assert struct.unpack('<Q', graph.read(BASE+0x55dfd80, 8))[0] == BASE+0x1fe8af8
    assert graph.run().field_820 == 1200
    graph.put(graph.service, '<Q', BASE+0x55dfbd8)
    with pytest.raises(core.SourceUnavailable, match='service runtime type'):
        graph.run()
    graph.put(graph.service, '<Q', BASE+0x55dfcf8)
    graph.put(BASE+0x56d2c68, '<Q', 0)
    with pytest.raises(core.SourceUnavailable, match='service root'):
        graph.run()


def test_full_service_root_is_rechecked_after_the_final_lifetime_callback(image):
    graph = Graph(image)
    count = 0
    def lifetime():
        nonlocal count
        count += 1
        if count == 2:
            graph.put(BASE+0x56d2c68, '<Q', 0)
        return ('same-fixture-scope', 1)
    with pytest.raises(ValueError, match='changed'):
        core.calculate(graph.read, BASE, image, club=graph.club,
                       selected_offers=(), lifetime=lifetime)
