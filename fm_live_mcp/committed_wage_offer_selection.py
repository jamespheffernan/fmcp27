"""Private input selector for the pinned committed-wage producers.

Reproduce 1826544/1826744, without running either function. This does not
calculate wages, establish offer activation, or expose a public tool. In
particular, the native CLUB cached index list is authoritative when present;
it is not unioned with the retained offer population. Unsupported resolution
never publishes a partial selected list. The caller owns the outer process,
plugin, world, save/date and selected-club lifetime checks for the calculation.
"""

from dataclasses import dataclass
import hashlib
import struct

from . import assessment_people, database, live_transfer_offers, players, teams, world


MAX_SLOTS = 100_000
STATE_MASK = 0x211801C
AFFILIATION_MASK = 0x1001F0
# Whole functions, bounded by LC_FUNCTION_STARTS in the pinned ARM64 image.
SOURCE = (
    (0x1826544, 512, "19dfc8f2af7f08bd6b54030d58fb2b2290b052a386936eddbf4685cbec597491"),
    (0x1826744, 1292, "1e2a8dfce5df07f5387abdcd055c6c0ab6744ad8cbe204aa6fe32e24b1ce212b"),
    (0xCB44B4, 296, "4dabf9e1e712eb526b9c5f23518be8d51304d8b3fd9e2e15213a3c12b44e6010"),
    (0xCB45DC, 20, "9a73fa3d73fb2e7bcff127a63fe56715835cf7f690fd3fa3592013eb3664e188"),
)
ZERO = bytes.fromhex("00008052c0035fd6")
ENQUIRY_GETTER = bytes.fromhex("003c4239c0035fd6")


class UnsupportedSelection(ValueError):
    """A genuine native branch needs an unimplemented/cold source."""


@dataclass(frozen=True)
class SelectedOffer:
    address: int
    manager_slot: int
    source_ordinal: int
    kind: str
    person_address: int


@dataclass(frozen=True)
class OfferSelection:
    state: str
    selected: tuple[SelectedOffer, ...] | None
    source: str
    source_slot_count: int
    manager_slot_count: int
    considered_slot_count: int
    reason: str | None = None


def _address(value, *, null=False, alignment=8):
    if type(value) is not int:
        raise ValueError("Invalid committed-wage source pointer type")
    if null and value == 0:
        return value
    if value < 4096 or value % alignment or value >= 1 << 64:
        raise ValueError("Invalid committed-wage source pointer")
    return value


def _pointer(read, address):
    return _address(players.u64(read(address, 8)), null=True)


def _geometry(read, address, *, stride=8, limit=MAX_SLOTS):
    start, end, capacity = struct.unpack("<QQQ", read(address, 24))
    if (start, end, capacity) == (0, 0, 0):
        return 0, 0
    if (start < 4096 or any(value % stride for value in (start, end, capacity))
            or not start <= end <= capacity or capacity - start > limit * stride):
        raise ValueError("Committed-wage vector geometry or bound changed")
    return start, (end - start) // stride


def _vector(read, address, *, stride=8):
    start, count = _geometry(read, address, stride=stride)
    end = start + count * stride
    raw = b"".join(read(at, min(8192, end - at)) for at in range(start, end, 8192))
    values = struct.unpack(f"<{len(raw) // stride}{'Q' if stride == 8 else 'i'}", raw)
    if stride == 8:
        for value in values:
            _address(value, null=True)
    return values


class _Source:
    def __init__(self, read, base):
        self.read, self.base = read, base
        self.people = self.team_table = self.club_table = None
        self.persons = {}

    def club(self, address):
        if not address:
            return
        if self.club_table is None:
            self.club_table = database.table(self.read, self.base, "clubs")
        world.typed(self.read, self.base, address, "club")
        self._member(address, self.club_table)

    def team(self, address):
        if not address:
            return
        if self.team_table is None:
            self.team_table = database.table(self.read, self.base, "teams")
        teams._typed(self.read, self.base, address, ("team", "national_team"))
        self._member(address, self.team_table)
        owner = _pointer(self.read, address + 0x30)
        # The wage producer operates on a CLUB's TEAM list; other owner classes
        # are outside this private source component.
        if owner:
            self.club(owner)
            if address not in _vector(self.read, owner + 0x18):
                raise ValueError("Committed-wage TEAM is absent from its CLUB")

    def _member(self, address, table):
        index, native = struct.unpack("<II", self.read(address + 8, 8))
        if (not native or index >= table["count"]
                or _pointer(self.read, table["start"] + 8 * index) != address):
            raise ValueError("Committed-wage canonical identity changed")
        if ("lookup_start" in table
                and (index >= table["lookup_count"] or _pointer(
                    self.read, table["lookup_start"] + 8 * index) != address)):
            raise ValueError("Committed-wage canonical lookup identity changed")

    def affiliation(self, club):
        self.club(club)
        if self.read(club + 0x163, 1)[0] & 0x10:
            return False, 0
        for relation in _vector(self.read, club + 0x118):
            if not relation:
                raise ValueError("Null committed-wage affiliation record")
            if _pointer(self.read, relation + 8) != club:
                continue
            code = self.read(relation + 0x30, 1)[0]
            if code <= 20 and (1 << code) & AFFILIATION_MASK:
                linked = _pointer(self.read, relation)
                self.club(linked)
                return True, linked
        return False, 0

    def person(self, address):
        if not address:
            return None
        if struct.unpack("<i", self.read(address + 0xC, 4))[0] == -1:
            raise UnsupportedSelection("native_virtual_person_resolution_unimplemented")
        if self.people is None:
            self.people = database.table(self.read, self.base, "people")
        _, _, record, _, _ = assessment_people._person(
            self.read, self.base, self.people, address)
        if record["record_kind"] == "virtual":
            raise UnsupportedSelection("native_virtual_person_resolution_unimplemented")
        return record["record_kind"]

    def resolve_person(self, address):
        if not address or struct.unpack("<i", self.read(address + 0xC, 4))[0] != -1:
            return address
        table = _pointer(self.read, address)
        fields = assessment_people._PERSON_TYPES.get(table - self.base)
        if fields is None or fields[0] != "virtual":
            raise UnsupportedSelection("native_nonvirtual_person_placeholder_unimplemented")
        _, primary, offset, name = fields
        world.typed(self.read, self.base, address - offset, "virtual_player")
        displacement, info = struct.unpack("<qQ", self.read(table - 16, 16))
        if displacement != -offset or _pointer(self.read, address - offset) != self.base + primary:
            raise ValueError("Committed-wage virtual PERSON cast changed")
        text = _address(players.u64(self.read(_address(info) + 8, 8)), alignment=1)
        if self.read(text, len(name) + 1) != name + b"\0":
            raise ValueError("Committed-wage virtual PERSON RTTI changed")
        index = struct.unpack("<i", self.read(address + 8, 4))[0]
        if index < 0:
            return 0
        if self.people is None:
            self.people = database.table(self.read, self.base, "people")
        if not self.read(self.base + teams.LOOKUP_MODE, 1)[0] & 1:
            start, count = _geometry(self.read, self.people["root"] + 0x68,
                                     limit=2_000_000)
            if index < count:
                return _pointer(self.read, start + 8 * index)
        return (_pointer(self.read, self.people["start"] + 8 * index)
                if index < self.people["count"] else 0)

    def person_excluded(self, person):
        kind = self.person(person)
        if kind is None:
            return False
        table = _pointer(self.read, person)
        if kind == "human_manager":
            if (players.u64(self.read(table + 0x1B0, 8)) != self.base + 0x1300058
                    or self.read(self.base + 0x1300058, 8) != bytes.fromhex("20008052c0035fd6")):
                raise ValueError("Committed-wage HUMAN exclusion getter changed")
            return True
        for slot, rva in ((0x1B0, 0xCA4638), (0x510, 0xCA4980)):
            if (players.u64(self.read(table + slot, 8)) != self.base + rva
                    or self.read(self.base + rva, 8) != ZERO):
                raise ValueError("Committed-wage PERSON exclusion getter changed")
        return False

    def auxiliary_contract_for_club(self, person, club):
        self.person(person)
        self.club(club)
        table = _pointer(self.read, person)
        if (players.u64(self.read(table + 0x3B8, 8)) != self.base + 0xCB45DC
                or struct.unpack("<q", self.read(table - 0x3C8, 8))[0] != -0x110):
            raise ValueError("Committed-wage auxiliary contract getter changed")
        holder = _pointer(self.read, person - 0x90)
        if not holder:
            return False
        for offset in (8, 0x18):
            contract = _pointer(self.read, holder + offset)
            if not contract:
                continue
            table = _pointer(self.read, contract)
            kind = next((kind for kind in ("basic_contract", "full_contract", "loan_contract", "trial_contract")
                         if table == self.base + world.TYPES[kind][0]), None)
            if kind is None:
                raise UnsupportedSelection("native_auxiliary_contract_type_unimplemented")
            world.typed(self.read, self.base, contract, kind)
            if _pointer(self.read, contract + 8) != person:
                raise ValueError("Committed-wage auxiliary contract owner changed")
            team = _pointer(self.read, contract + 0x10)
            if not team:
                continue
            self.team(team)
            if self.read(team + 0x2F, 1)[0]:
                continue
            owner = _pointer(self.read, team + 0x30)
            if owner:
                _, linked = self.affiliation(owner)
                if linked == club:
                    return True
        return False

    def destination(self, offer):
        destination = _pointer(self.read, offer + 0x50)
        if self.read(offer + 0x8E, 1)[0] & 1 or destination:
            self.team(destination)
            return destination
        if self.read(offer + 0x85, 1)[0] == 1:
            return 0
        raise UnsupportedSelection("native_destination_generation_required")

    def matches(self, offer, kind, original, effective, exclude_states, skip_state19, mode):
        state = self.read(offer + 0x8D, 1)[0]
        if exclude_states and state <= 25 and (1 << state) & STATE_MASK:
            return False
        if skip_state19 and state == 19:
            return False
        source = _pointer(self.read, offer + 0x40)
        self.team(source)
        if mode == 0 and source != original:
            return False
        if mode == 1 and self.destination(offer) != original:
            return False
        table = _pointer(self.read, offer)
        expected = 0x1831A24 if kind == "enquiry" else 0x181E4A0
        if players.u64(self.read(table + 0x3E0, 8)) != self.base + expected:
            raise ValueError("Committed-wage special-offer getter changed")
        code = ENQUIRY_GETTER if kind == "enquiry" else ZERO
        if self.read(self.base + expected, 8) != code:
            raise ValueError("Committed-wage special-offer getter body changed")
        special = self.read(offer + 0x8F, 1)[0] if kind == "enquiry" else 0
        if special:
            if state <= 25 and (1 << state) & STATE_MASK:
                return False
            if source == self.destination(offer):
                return False
        if source == original and state == 3:
            return False
        person = self.resolve_person(_pointer(self.read, offer + 0x38))
        self.persons[offer] = person
        if person and self.person_excluded(person):
            return False
        if source == original:
            return True
        alternate = _pointer(self.read, offer + 0x48) or source
        self.team(alternate)
        if alternate == original:
            return True
        destination = self.destination(offer)
        if destination != original and destination != effective:
            return False
        if destination == original or not person:
            return True
        club = _pointer(self.read, effective + 0x30) if effective else 0
        if not club:
            return True
        return self.auxiliary_contract_for_club(person, club)


def select_offers(read, base, team, *, exclude_native_states=True, skip_state19=False, mode=2):
    """Select exact native ordered inputs; addresses remain private.

    Modes0/1/2 are the native source/destination/either selectors. This API
    does not accept caller-provided admitted offer IDs. An unavailable branch
    invalidates the whole selected list. Source/type/owner/drift errors raise.
    """
    _address(base)
    _address(team, null=True)
    if (type(exclude_native_states) is not bool or type(skip_state19) is not bool
            or type(mode) is not int or mode not in (0, 1, 2)):
        raise ValueError("Unsupported committed-wage selector parameters")
    snapshot = world.ReadSet(read)
    for rva, size, digest in SOURCE:
        if hashlib.sha256(snapshot(base + rva, size)).hexdigest() != digest:
            raise ValueError("Committed-wage selector native source changed")
    source = _Source(snapshot, base)
    source.team(team)
    manager = live_transfer_offers._manager(snapshot, base)
    if not manager:
        raise UnsupportedSelection("native_transfer_manager_absent")
    offers = _vector(snapshot, manager + live_transfer_offers.BASE_OFFSET + 8)
    effective, cache = team, None
    if team and snapshot(team + 0x2F, 1) == b"\0":
        club = _pointer(snapshot, team + 0x30)
        if club:
            found, linked = source.affiliation(club)
            if found and linked:
                linked_teams = _vector(snapshot, linked + 0x18)
                effective = linked_teams[0] if linked_teams else 0
                source.team(effective)
            extension = _pointer(snapshot, club + 0x100)
            if not extension:
                raise UnsupportedSelection("native_club_extension_absent")
            cache = _pointer(snapshot, extension + 0x20)
    indices = _vector(snapshot, cache, stride=4) if cache else tuple(range(len(offers)))
    source_name = "club_cached_indices" if cache else "manager_first_offer_vector"
    selected, considered = [], 0
    try:
        for ordinal, slot in enumerate(indices):
            if slot < 0 or slot >= len(offers) or not offers[slot]:
                continue
            considered += 1
            offer = offers[slot]
            kind = live_transfer_offers._type(snapshot, base, _pointer(snapshot, offer))
            if source.matches(offer, kind, team, effective,
                              exclude_native_states, skip_state19, mode):
                selected.append(SelectedOffer(offer, slot, ordinal, kind, source.persons[offer]))
    except UnsupportedSelection as error:
        snapshot.verify()
        return OfferSelection("unavailable", None, source_name, len(indices),
                              len(offers), considered, str(error))
    snapshot.verify()
    return OfferSelection("selected", tuple(selected), source_name, len(indices),
                          len(offers), considered)
