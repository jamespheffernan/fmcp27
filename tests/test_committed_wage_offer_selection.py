"""Synthetic typed sources; native oracle executes copied bytes, never FM.

The fixture holds exact disk-extracted native functions. Its oracle runs the
complete original selector functions in Unicorn on owned memory, with genuine
virtual getter bodies and preallocated output capacity. No selected addresses
or expected outcomes are supplied to the oracle.
"""
import hashlib
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import committed_wage_offer_selection as selected
from fm_live_mcp import database, live_transfer_offers, teams, world


NATIVE = {int(address, 0): bytes.fromhex(raw) for address, raw in json.loads(
    (Path(__file__).parent / "fixtures/committed-wage-selection-native.json").read_text()).items()}
BASE = 0x100000000


def pack(value):
    return struct.pack("<Q", value)


class Fixture:
    def __init__(self):
        self.data = {}
        self.reads = []
        self.next = 0x30000000
        self.types = {}
        for address, raw in NATIVE.items():
            self.put(BASE + address, raw)
        for address, raw in live_transfer_offers.NATIVE_SPANS:
            self.put(BASE + address, raw)
        self.put(BASE + teams.LOOKUP_MODE, b"\0")
        self.manager = self.alloc()
        self.typed(self.manager, *world.TYPES["transfer_manager"])
        self.put(BASE + live_transfer_offers.ROOT, pack(self.manager))
        self.put(self.manager + 0x18, pack(BASE + 0x55F9AD0))
        self.put(BASE + 0x55F9C10, struct.pack("<QQ", BASE + 0x55C7788, 0x1802))
        self.club = self.alloc(0x200)
        self.typed(self.club, *world.TYPES["club"])
        self.put(self.club + 8, struct.pack("<III", 0, 100, 100))
        self.extension = self.alloc()
        self.put(self.club + 0x100, pack(self.extension))
        self.team = self.alloc()
        self.typed(self.team, *world.TYPES["team"])
        self.put(self.team + 8, struct.pack("<III", 0, 200, 200))
        self.put(self.team + 0x30, pack(self.club))
        self.vector(self.club + 0x18, [self.team])
        self.table("teams", [self.team])
        self.table("clubs", [self.club])
        self.table("people", [])
        self.offers([])

    def alloc(self, size=0x100):
        address = self.next
        self.next += (size + 0xFF) & ~0xFF
        self.put(address, bytes(size))
        return address

    def put(self, address, raw):
        self.data.update((address + i, value) for i, value in enumerate(raw))

    def __call__(self, address, size):
        assert size <= 16384
        self.reads.append((address, size))
        return bytes(self.data.get(address + i, 0) for i in range(size))

    def type(self, table_rva, name, displacement=0):
        table = BASE + table_rva
        if table not in self.types:
            info, text = self.alloc(), self.alloc()
            self.types[table] = info
            self.put(table - 16, struct.pack("<qQ", displacement, info))
            self.put(info + 8, pack(text))
            self.put(text, name + b"\0")
        return table

    def typed(self, address, table_rva, name, displacement=0):
        self.put(address, pack(self.type(table_rva, name, displacement)))
        for kind, getter in teams.GETTERS.items():
            if table_rva == world.TYPES[kind][0]:
                self.put(BASE + table_rva + 24, pack(BASE + getter))

    def table(self, kind, pointers):
        root_rva, table_rva, name = database.TABLES[kind]
        root, header = self.alloc(), self.alloc()
        self.typed(root, table_rva, name)
        self.put(BASE + root_rva, pack(root))
        self.put(root + 0x88, pack(header))
        start = self.vector(header, pointers)
        return root, header, start

    def vector(self, header, values, stride=8):
        start = self.alloc(max(8, len(values) * stride))
        self.put(header, struct.pack("<QQQ", start, start + len(values) * stride,
                                     start + len(values) * stride))
        self.put(start, struct.pack(f"<{len(values)}{'Q' if stride == 8 else 'i'}", *values))
        return start

    def offers(self, values):
        return self.vector(self.manager + 0x20, values)

    def cache(self, values):
        header = self.alloc()
        self.put(self.extension + 0x20, pack(header))
        self.vector(header, values, stride=4)
        return header

    def offer(self, *, kind="loan", source=None, alternate=0, destination=0,
              state=0, person=0, destination_known=True, no_destination=False,
              special=0):
        address = self.alloc()
        table_rva, (_, name, getter, code) = next(
            (table, profile) for table, profile in live_transfer_offers.CLASSES.items()
            if profile[0] == kind)
        self.typed(address, table_rva, name)
        table = BASE + table_rva
        self.put(self.types[table] + 16, pack(BASE + 0x55C9020))
        self.put(table + 0x78, pack(BASE + getter))
        self.put(BASE + getter, struct.pack("<II", 0x52800000 | code << 5, 0xD65F03C0))
        special_getter = 0x1831A24 if kind == "enquiry" else 0x181E4A0
        self.put(table + 0x3E0, pack(BASE + special_getter))
        self.put(address + 0x38, struct.pack("<QQQQ", person,
                 self.team if source is None else source, alternate, destination))
        self.put(address + 0x85, bytes([1 if no_destination else 0]))
        self.put(address + 0x8D, bytes([state, 1 if destination_known else 0, special]))
        self.put(address + 8, struct.pack("<i", 10))  # No destruction during native oracle.
        return address

    def extra_club_team(self):
        club, team, ext = self.alloc(0x200), self.alloc(), self.alloc()
        self.typed(club, *world.TYPES["club"])
        self.typed(team, *world.TYPES["team"])
        self.put(club + 8, struct.pack("<III", 1, 101, 101))
        self.put(team + 8, struct.pack("<III", 1, 201, 201))
        self.put(team + 0x30, pack(club))
        self.put(club + 0x100, pack(ext))
        self.vector(club + 0x18, [team])
        self.table("clubs", [self.club, club])
        self.table("teams", [self.team, team])
        return club, team

    def affiliate(self, club, linked, code=18):
        relation = self.alloc()
        self.put(relation, struct.pack("<QQ", linked, club))
        self.put(relation + 0x30, bytes([code]))
        self.vector(club + 0x118, [relation])
        return relation

    def person(self, kind="actual"):
        fields = selected.assessment_people._PERSON_TYPES
        table_rva, (_, primary_rva, offset, name) = next(
            (table, fields) for table, fields in fields.items() if fields[0] == kind)
        primary = self.alloc(0x600)
        person = primary + offset
        self.typed(primary, primary_rva, name)
        self.typed(person, table_rva, name, -offset)
        self.put(person + 8, struct.pack("<III", 0, 300, 300))
        table = BASE + table_rva
        self.put(table + 0x1B0, pack(BASE + (0x1300058 if kind == "human_manager" else 0xCA4638)))
        self.put(table + 0x510, pack(BASE + 0xCA4980))
        self.put(table + 0x3B8, pack(BASE + 0xCB45DC))
        self.put(table - 0x3C8, struct.pack("<q", -0x110))
        self.table("people", [person])
        return person


def native_selection(fixture, *, team=None, exclude_native_states=True, skip_state19=False, mode=2):
    """Execute both complete frozen native functions in synthetic RAM only."""
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_CPU_ARM64_MAX, UC_ARM64_REG_PC
    memory = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    memory.ctl_set_cpu_model(UC_CPU_ARM64_MAX)
    pages = sorted({address & ~0xFFF for address in fixture.data}
                   | {(BASE + 0x1869938) & ~0xFFF})
    for page in pages:
        memory.mem_map(page, 4096)
        memory.mem_write(page, bytes(fixture.data.get(page + i, 0) for i in range(4096)))
    scratch, output, entries, sentinel = 0x70000000, 0x70008000, 0x70009000, 0x7000F000
    memory.mem_map(scratch, 0x10000)
    memory.mem_write(output, struct.pack("<QQQ", entries, entries, entries + 4096))
    args = (fixture.manager + 0x18, fixture.team if team is None else team,
            output, int(exclude_native_states), int(skip_state19), mode)
    # Unicorn registers X0..X5 are consecutive.
    for i, value in enumerate(args):
        memory.reg_write(UC_ARM64_REG_X0 + i, value)
    memory.reg_write(UC_ARM64_REG_SP, scratch + 0x7000)
    memory.reg_write(UC_ARM64_REG_LR, sentinel)
    allowed = [(BASE + address, BASE + address + len(raw)) for address, raw in NATIVE.items()]
    stop = []

    def code(uc, address, size, user):
        if address == sentinel:
            uc.emu_stop()
        elif address == BASE + 0x1869938:
            stop.append("generation")
            uc.emu_stop()
        elif not any(start <= address < end for start, end in allowed):
            raise AssertionError(f"Unexpected native oracle callee {address:#x}")

    memory.hook_add(UC_HOOK_CODE, code)
    try:
        memory.emu_start(BASE + 0x1826544, sentinel, count=30_000)
    except Exception as error:
        raise AssertionError(f"Native oracle failed at {memory.reg_read(UC_ARM64_REG_PC):#x}") from error
    if stop:
        return "generation"
    assert memory.reg_read(UC_ARM64_REG_PC) == sentinel, "Native oracle exhausted instruction bound"
    start, end, _ = struct.unpack("<QQQ", memory.mem_read(output, 24))
    assert start == entries and entries <= end <= entries + 4096
    return struct.unpack(f"<{(end-start)//8}Q", memory.mem_read(start, end - start))


def check(fixture, **options):
    result = selected.select_offers(fixture, BASE, fixture.team, **options)
    expected = native_selection(fixture, **options)
    assert result.state == "selected"
    assert tuple(row.address for row in result.selected) == expected
    return result


def test_whole_source_fixture_hashes_match_production_pins():
    for address, length, digest in selected.SOURCE:
        assert len(NATIVE[address]) == length
        assert hashlib.sha256(NATIVE[address]).hexdigest() == digest


@pytest.mark.parametrize("state", range(256))
@pytest.mark.parametrize("mode", (0, 1, 2))
def test_all_unsigned_state_bytes_and_three_native_modes_match_complete_native_functions(state, mode):
    f = Fixture()
    offer = f.offer(state=state, destination=f.team)
    f.offers([offer])
    check(f, mode=mode)


@pytest.mark.parametrize("state", (0, 2, 3, 4, 15, 16, 19, 20, 25, 26, 255))
@pytest.mark.parametrize("exclude_native_states,skip_state19", ((False, False), (False, True), (True, True)))
def test_state_flags_preserve_independent_state3_source_guard(state, exclude_native_states, skip_state19):
    f = Fixture()
    offer = f.offer(state=state, destination=f.team)
    f.offers([offer])
    check(f, exclude_native_states=exclude_native_states, skip_state19=skip_state19)


def test_cache_is_authoritative_and_preserves_duplicate_indices_aliases_and_ordinal():
    f = Fixture()
    first, omitted = f.offer(), f.offer()
    f.offers([first, omitted, 0, first])
    f.cache([3, -1, 99, 0, 3, 2])
    result = check(f)
    assert [(row.address, row.manager_slot, row.source_ordinal) for row in result.selected] == [
        (first, 3, 0), (first, 0, 3), (first, 3, 4)]
    assert (result.source, result.source_slot_count, result.manager_slot_count,
            result.considered_slot_count) == ("club_cached_indices", 6, 4, 3)


def test_existing_empty_cache_does_not_fall_back_to_nonempty_manager():
    f = Fixture()
    f.offers([f.offer()])
    f.cache([])
    result = check(f)
    assert result.selected == () and result.source == "club_cached_indices"


@pytest.mark.parametrize("kind", tuple(profile[0] for profile in live_transfer_offers.CLASSES.values()))
def test_all_recognised_offer_classes_use_their_actual_special_getter(kind):
    f = Fixture()
    f.offers([f.offer(kind=kind)])
    assert len(check(f).selected) == 1


@pytest.mark.parametrize("mode", (0, 1, 2))
@pytest.mark.parametrize("special", (0, 1, 2, 255))
def test_enquiry_special_getter_uses_nonzero_not_assumed_boolean(mode, special):
    f = Fixture()
    _, other = f.extra_club_team()
    f.offers([f.offer(kind="enquiry", source=other, destination=f.team, special=special)])
    check(f, mode=mode)


@pytest.mark.parametrize("person_kind", ("actual", "staff", "player_staff", "human_manager"))
def test_person_predicates_are_typed_and_human_is_rejected_by_actual_literal(person_kind):
    f = Fixture()
    person = f.person(person_kind)
    f.offers([f.offer(person=person)])
    result = check(f)
    assert len(result.selected) == (0 if person_kind == "human_manager" else 1)


@pytest.mark.parametrize("mode", (0, 1, 2))
def test_native_source_alternate_and_destination_team_links(mode):
    f = Fixture()
    _, other = f.extra_club_team()
    f.offers([f.offer(source=other, alternate=f.team),
              f.offer(source=other, destination=f.team), f.offer(source=other),
              f.offer(source=f.team, destination=other)])
    check(f, mode=mode)


@pytest.mark.parametrize("affiliation_code", range(22))
def test_native_affiliation_mask_and_effective_team_redirect(affiliation_code):
    f = Fixture()
    other_club, other_team = f.extra_club_team()
    f.affiliate(f.club, other_club, affiliation_code)
    f.offers([f.offer(source=other_team, destination=other_team)])
    check(f)


def test_effective_team_person_auxiliary_affiliation_contract_route_matches_native():
    f = Fixture()
    other_club, other_team = f.extra_club_team()
    f.affiliate(f.club, other_club, 4)
    person = f.person()
    holder, contract = f.alloc(), f.alloc()
    f.put(person - 0x90, pack(holder))
    f.put(holder + 8, pack(contract))
    f.typed(contract, *world.TYPES["loan_contract"])
    f.put(contract + 8, struct.pack("<QQ", person, f.team))
    f.offers([f.offer(source=other_team, destination=other_team, person=person)])
    result = check(f)
    assert len(result.selected) == 1
    f.put(contract + 8, pack(person + 8))
    with pytest.raises(ValueError, match="owner"):
        selected.select_offers(f, BASE, f.team)


def test_destination_generation_branch_withholds_entire_selection_and_oracle_stops_before_it():
    f = Fixture()
    _, other = f.extra_club_team()
    f.offers([f.offer(), f.offer(source=other, destination_known=False)])
    result = selected.select_offers(f, BASE, f.team)
    assert result.state == "unavailable" and result.selected is None
    assert result.reason == "native_destination_generation_required"
    assert native_selection(f) == "generation"


def test_native_no_destination_byte_is_a_proven_null_not_a_generation_request():
    f = Fixture()
    _, other = f.extra_club_team()
    f.offers([f.offer(source=other, destination_known=False, no_destination=True)])
    assert check(f).selected == ()


@pytest.mark.parametrize("mode", (0, 1, 2, 3, 254, 255))
@pytest.mark.parametrize("fast", (True, False))
def test_existing_virtual_person_resolves_only_through_exact_selected_native_index(mode, fast):
    f = Fixture()
    actual = f.person()
    virtual = f.person("virtual")
    f.put(virtual + 0xC, struct.pack("<i", -1))
    root, _, _ = f.table("people", [actual])
    if fast:
        f.vector(root + 0x68, [actual])
    f.put(BASE + teams.LOOKUP_MODE, bytes([mode]))
    offer = f.offer(person=virtual)
    f.offers([offer])
    result = check(f)
    assert result.selected[0].person_address == actual
    # Source memory was never rewritten: native's cached pointer change exists
    # only inside the oracle's owned copy and the private typed result.
    assert f(offer + 0x38, 8) == pack(virtual)


@pytest.mark.parametrize("index", (-1, 1, 100))
def test_native_unresolved_virtual_person_index_is_null_not_generated(index):
    f = Fixture()
    virtual = f.person("virtual")
    f.put(virtual + 8, struct.pack("<ii", index, -1))
    f.table("people", [])
    offer = f.offer(person=virtual)
    f.offers([offer])
    result = check(f)
    assert result.selected[0].person_address == 0
    assert f(offer + 0x38, 8) == pack(virtual)


@pytest.mark.parametrize("known", (0, 1, 2, 255))
@pytest.mark.parametrize("suppress", (0, 1, 2, 255))
def test_destination_flags_preserve_bit0_and_exact_byte1_semantics(known, suppress):
    f = Fixture()
    _, other = f.extra_club_team()
    offer = f.offer(source=other, destination_known=False)
    f.put(offer + 0x8E, bytes([known]))
    f.put(offer + 0x85, bytes([suppress]))
    f.offers([offer])
    if known & 1 or suppress == 1:
        assert check(f).selected == ()
    else:
        result = selected.select_offers(f, BASE, f.team)
        assert result.selected is None and result.reason == "native_destination_generation_required"
        assert native_selection(f) == "generation"


def test_virtual_fast_vector_resolution_cannot_admit_wrong_canonical_person_slot():
    f = Fixture()
    actual = f.person()
    virtual = f.person("virtual")
    f.put(virtual + 0xC, struct.pack("<i", -1))
    root, _, _ = f.table("people", [0])
    f.vector(root + 0x68, [actual])
    f.offers([f.offer(person=virtual)])
    with pytest.raises(ValueError, match="canonical slot"):
        selected.select_offers(f, BASE, f.team)


def test_empty_affiliated_club_team_list_preserves_native_null_effective_team_branch():
    f = Fixture()
    other_club, other = f.extra_club_team()
    f.affiliate(f.club, other_club, 4)
    f.vector(other_club + 0x18, [])
    # Use source=null so no invalid TEAM ownership is introduced by the control.
    f.offers([f.offer(source=0, destination=0)])
    result = check(f)
    assert len(result.selected) == 1


def test_affiliation_disabled_flag_and_first_matching_relation_order_are_native():
    f = Fixture()
    other_club, other = f.extra_club_team()
    f.affiliate(f.club, other_club, 4)
    f.offers([f.offer(source=other, destination=other)])
    assert len(check(f).selected) == 1
    f.put(f.club + 0x163, b"\x10")
    assert check(f).selected == ()


def test_auxiliary_second_contract_slot_preserves_fallback_and_affiliation_disabled_flag():
    f = Fixture()
    other_club, other = f.extra_club_team()
    f.affiliate(f.club, other_club, 4)
    person = f.person()
    holder, contract = f.alloc(), f.alloc()
    f.put(person - 0x90, pack(holder))
    f.put(holder + 0x18, pack(contract))
    f.typed(contract, *world.TYPES["loan_contract"])
    f.put(contract + 8, struct.pack("<QQ", person, f.team))
    f.offers([f.offer(source=other, destination=other, person=person)])
    assert len(check(f).selected) == 1
    f.put(f.club + 0x163, b"\x10")
    assert check(f).selected == ()


@pytest.mark.parametrize("kwargs", ({"mode": True}, {"mode": 3}, {"exclude_native_states": 1}, {"skip_state19": None}))
def test_invalid_parameters_reject_before_reads(kwargs):
    f = Fixture()
    with pytest.raises(ValueError):
        selected.select_offers(f, BASE, f.team, **kwargs)
    assert not f.reads


@pytest.mark.parametrize("team", (False, 0.0))
def test_null_team_requires_exact_integer_zero_before_reading_native_sources(team):
    f = Fixture()
    with pytest.raises(ValueError, match="pointer type"):
        selected.select_offers(f, BASE, team)
    assert f.reads == []


@pytest.mark.parametrize("bad", ("source", "getter", "type", "club_slot", "person_slot", "vector"))
def test_source_type_owner_membership_and_bounds_fail_closed(bad):
    f = Fixture()
    person = f.person()
    offer = f.offer(person=person)
    f.offers([offer])
    if bad == "source":
        f.put(BASE + 0x1826744, b"\0")
    elif bad == "getter":
        f.put(BASE + 0x181E4A0, b"\xff")
    elif bad == "type":
        f.put(offer, pack(BASE + 0x1230))
    elif bad == "club_slot":
        f.put(f.club + 8, struct.pack("<I", 100))
    elif bad == "person_slot":
        f.put(person + 8, struct.pack("<I", 1))
    elif bad == "vector":
        f.put(f.manager + 0x20, struct.pack("<QQQ", 0x40000000, 0x40000000, 0x41000000))
    with pytest.raises(ValueError):
        selected.select_offers(f, BASE, f.team)


def test_consumed_source_drift_rejects_after_successful_selection():
    f = Fixture()
    offer = f.offer()
    f.offers([offer])
    count = 0

    def read(address, size):
        nonlocal count
        if address == offer + 0x8D:
            count += 1
            if count == 2:
                f.put(address, b"\x02")
        return f(address, size)

    with pytest.raises(ValueError, match="changed"):
        selected.select_offers(read, BASE, f.team)


def test_private_component_does_not_register_tools_or_claim_monetary_total():
    f = Fixture()
    result = selected.select_offers(f, BASE, f.team)
    assert result.state == "selected" and result.selected == ()
    assert not hasattr(result, "amount")
    assert "does not" in selected.__doc__
