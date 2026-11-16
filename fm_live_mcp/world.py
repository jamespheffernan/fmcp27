"""Build-pinned game roots and managed-team rosters, verified against FM27 UI.

Call only after players.verify_runtime and the plugin fingerprint check.
"""
from datetime import date, timedelta
import struct

from . import players
from .players import read_name, u64

GAME_ROOT = 0x56A4B60
SAVE_ROOT = 0x56A4BC0
CURRENT_DATE = 0x56B1DB8
TYPES = {
    "media_source": (0x55B5B30, b"N2db12MEDIA_SOURCEE"),
    "stadium_change": (0x55BD8C0, b"N2db14STADIUM_CHANGEE"),
    "city": (0x559C558, b"N2db4CITYE"),
    "language": (0x55B5080, b"N2db8LANGUAGEE"),
    "local_region": (0x55B5718, b"N2db12LOCAL_REGIONE"),
    "weather": (0x55CC3A0, b"N2db7WEATHERE"),
    "game": (0x54B2058, b"N11game_plugin7GAME_UIE"),
    "save": (0x55F4AC8, b"11SAVE_SYSTEM"),
    "manager": (0x55AC480, b"N2db16HUMAN_NON_PLAYERE"),
    "team": (0x55C2E40, b"N2db4TEAME"),
    "club": (0x559CF48, b"N2db4CLUBE"),
    "national_team": (0x55B5D50, b"N2db13NATIONAL_TEAME"),
    "national_team_container": (0x55B5E98, b"N2db23NATIONAL_TEAM_CONTAINERE"),
    "league_body_club": (0x55B5288, b"N2db16LEAGUE_BODY_CLUBE"),
    "competition": (0x559ED88, b"N2db4COMPE"),
    "nation": (0x55B5C40, b"N2db6NATIONE"),
    "continent": (0x55A06B0, b"N2db9CONTINENTE"),
    "club_finance": (0x559DF18, b"N2db12CLUB_FINANCEE"),
    "club_finance_base": (0x559DA40, b"N2db17CLUB_FINANCE_BASEE"),
    "game_club": (0x55DF850, b"9GAME_CLUB"),
    "game_club_finance": (0x55DFBD8, b"22GAME_CLUB_FINANCE_BASE"),
    "transfer_manager": (0x55F9988, b"16TRANSFER_MANAGER"),
    "currency": (0x55A1188, b"N2db15CURRENCY_RECORDE"),
    "basic_contract": (0x559B9F8, b"N2db14BASIC_CONTRACTE"),
    "full_contract": (0x55ABD68, b"N2db13FULL_CONTRACTE"),
    "loan_contract": (0x55B54E8, b"N2db13LOAN_CONTRACTE"),
    "trial_contract": (0x55A0D28, b"N2db14TRIAL_CONTRACTE"),
    "virtual_player": (0x55CAC48, b"N2db14VIRTUAL_PLAYERE"),
    "virtual_manager": (0x55CABC0, b"N2db15VIRTUAL_MANAGERE"),
    "injury": (0x55B2820, b"N2db6INJURYE"),
    "stadium": (0x55BD7B0, b"N2db7STADIUME"),
    "stage_name": (0x55BD9E8, b"N2db10STAGE_NAMEE"),
}


class ReadSet:
    """Recheck precisely the consumed bytes; this is not an atomic snapshot."""

    def __init__(self, read):
        self.read = read
        self.observed = {}

    def __call__(self, address, length):
        data = self.read(address, length)
        if len(data) != length:
            raise ValueError("Incomplete world read")
        key = (address, length)
        if key in self.observed and self.observed[key] != data:
            raise ValueError("Game state changed during read; retry")
        self.observed[key] = data
        return data

    def verify(self):
        if getattr(self.read, 'journalled', False):
            # Bulk knowledge engine: the source already serves every repeated read from its
            # journal and compares all consumed bytes with memory once, at the end of the call.
            return
        for (address, length), expected in self.observed.items():
            if self.read(address, length) != expected:
                raise ValueError("Game state changed during read; retry")


def pointer(read, address):
    value = u64(read(address, 8))
    if value < 4096 or value % 8:
        raise ValueError("Invalid world pointer")
    return value


def typed(read, base, address, kind):
    table_rva, name = TYPES[kind]
    table = base + table_rva
    if pointer(read, address) != table:
        raise ValueError(f"Unexpected native {kind} type")
    metadata = read(table - 16, 16)
    if struct.unpack_from("<q", metadata)[0] != 0:
        raise ValueError(f"Unexpected native {kind} displacement")
    info = u64(metadata, 8)
    text = u64(read(info + 8, 8))
    if read(text, len(name) + 1) != name + b"\0":
        raise ValueError(f"Unexpected native {kind} RTTI")


def string(read, address):
    length = int.from_bytes(read(address, 4), "little")
    if not 1 <= length <= 512:
        raise ValueError("Invalid world string length")
    data = read(address + 4, length + 1)
    value = data[:-1].decode("utf-8", errors="strict")
    if data[-1] or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Invalid world string")
    return value


def vector(read, address, limit):
    start, end, capacity = struct.unpack("<QQQ", read(address, 24))
    if start == end == capacity == 0:
        return ()
    if start < 4096 or any(x % 8 for x in (start, end, capacity)) or not start <= end <= capacity:
        raise ValueError("Invalid native vector")
    count = (end - start) // 8
    if count > limit or capacity - start > limit * 8:
        raise ValueError("Native vector exceeds bound")
    values = struct.unpack(f"<{count}Q", read(start, count * 8)) if count else ()
    if any(x < 4096 or x % 8 for x in values) or len(set(values)) != len(values):
        raise ValueError("Invalid or duplicate vector entry")
    return values


def packed_date(raw):
    value = int.from_bytes(raw, "little")
    year, day = value >> 16, value & 511
    if not 1850 <= year <= 2200 or not 1 <= day <= 366:
        raise ValueError("Invalid game date")
    result = date(year, 1, 1) + timedelta(days=day - 1)
    if result.year != year:
        raise ValueError("Invalid game day")
    return result.isoformat()


def club(read, base, address):
    typed(read, base, address, "club")
    identity, secondary = struct.unpack("<II", read(address + 0xC, 8))
    if not identity:
        raise ValueError("Club primary identity is missing")
    return {"name": string(read, u64(read(address + 0xC0, 8))),
            "short_name": string(read, u64(read(address + 0xC8, 8)))}, (identity, secondary)


def player_clubs(read, base, address, team_cache=None, *, player_staff=False):
    """Resolve independent club links and the stored native On Loan boolean.

    The caller must use a ReadSet and verify it before accepting the result.
    A cache may be shared only within that one ReadSet, never across requests.
    Field 0x130 is deliberately unused: it can contain a national or former team.
    """
    cache = {} if team_cache is None else team_cache
    person_offset = 0x480 if player_staff else 0x388
    person = address + person_offset
    primary = base + (players.STAFF_RVA[0] if player_staff else players.RVA[0])
    if (u64(read(address, 8)) != primary
            or u64(read(primary + 93*8, 8)) != base + 0xCFFFFC
            or struct.unpack('<q', read(primary - 0x20, 8))[0] != person_offset - 0x110):
        raise ValueError('Native player On Loan dispatch changed')

    def team_club(team):
        if team not in cache:
            typed(read, base, team, "team")
            club_address = pointer(read, team + 0x30)
            record, identity = club(read, base, club_address)
            if team not in vector(read, club_address + 0x18, 64):
                raise ValueError("Player team is absent from club teams")
            cache[team] = (record, (club_address, identity))
        return cache[team]

    def contract_club(contract):
        if pointer(read, contract + 8) != person:
            raise ValueError("Player contract owner disagrees")
        first, second = struct.unpack('<QQ', read(contract + 0x10, 16))
        if first == second == 0:
            return None, 0, 0
        record, identity = team_club(first)
        if team_club(second)[1] != identity:
            raise ValueError("Player contract team clubs disagree")
        return record, first, identity[0]

    main = u64(read(person - 0x98, 8))
    parent, parent_state = None, 'no_contract'
    if main:
        table = pointer(read, main)
        kind = next((kind for kind in ('full_contract', 'basic_contract')
                     if table == base + TYPES[kind][0]), None)
        if kind is None:
            raise ValueError('Unsupported player main contract type')
        typed(read, base, main, kind)
        parent, _, _ = contract_club(main)
        parent_state = 'decoded' if parent is not None else 'no_contract_team'
    current_team = u64(read(address + 0x128, 8))
    current = team_club(current_team)[0] if current_team else None
    holder = u64(read(person - 0x90, 8))
    loan_club, on_loan, state = None, False, 'no_auxiliary_holder'
    if holder:
        if holder < 4096 or holder % 8:
            raise ValueError('Invalid auxiliary contract holder')
        auxiliary = u64(read(holder, 8))
        state = 'empty_current_slot'
        if auxiliary:
            table = pointer(read, auxiliary)
            if table == base + TYPES['trial_contract'][0]:
                typed(read, base, auxiliary, 'trial_contract')
                if (pointer(read, auxiliary + 8) != person
                        or u64(read(table + 18*8, 8)) != base + 0x1006B44):
                    raise ValueError('Trial contract owner or loan-type getter changed')
                state = 'trial_contract'
            else:
                typed(read, base, auxiliary, 'loan_contract')
                for slot, getter in ((18, 0x13781B8), (19, 0x13781C0)):
                    if u64(read(table + slot*8, 8)) != base + getter:
                        raise ValueError('Loan classification getter changed')
                loan_club, loan_team, club_address = contract_club(auxiliary)
                on_loan, state = True, 'loan_contract'
                if loan_team and read(loan_team + 0x2F, 1) == b'\0' and club_address:
                    for link in vector(read, club_address + 0x118, 1024):
                        # These are plain affiliation records, not polymorphic objects.
                        if u64(read(link + 8, 8)) == club_address and read(link + 0x30, 1) == b'\x12':
                            on_loan, state = False, 'suppressed_by_affiliation_kind_18'
                            break
    return {"contract_club": parent, "contract_club_state": parent_state,
            "current_club": current, "loan_club": loan_club, "on_loan": on_loan,
            "loan_status_reason": state, "eligibility_evaluated": False,
            "evidence": "native_player_club_links_and_on_loan_getter"}


def loaded(read, base):
    game = pointer(read, base + GAME_ROOT)
    save = pointer(read, base + SAVE_ROOT)
    typed(read, base, game, "game")
    typed(read, base, save, "save")
    name_address = u64(read(save + 0x28, 8))
    if name_address == 0:
        raise ValueError("No named career is available in the running game. Retry once a career is loaded.")
    name = string(read, name_address)
    created = packed_date(read(game + 0x38, 4))
    created_version = int.from_bytes(read(game + 0x3C, 4), "little")
    current_raw = read(base + CURRENT_DATE, 4)
    current = packed_date(current_raw)
    if current == '1900-01-01':
        raise ValueError('Current game date is unset')
    save_count = int.from_bytes(read(game + 0xC8, 4), "little")
    if not created_version or save_count > 10_000_000:
        raise ValueError("Invalid game metadata")
    info = pointer(read, game + 0x58)
    users = vector(read, info, 64)
    coaches = []
    bindings = []
    for user in users:
        manager = pointer(read, user + 0x148)
        if manager not in vector(read, user + 0xC0, 64):
            raise ValueError("Active manager is absent from the user manager list")
        typed(read, base, manager, "manager")
        first = read_name(read, pointer(read, manager + 0x458))
        last = read_name(read, pointer(read, manager + 0x460))
        contract = pointer(read, manager + 0x4B0)
        if pointer(read, contract + 8) != manager + 0x548:
            raise ValueError("Manager contract owner disagrees")
        team = pointer(read, contract + 0x10)
        if pointer(read, contract + 0x18) != team:
            raise ValueError("Manager contract teams disagree")
        typed(read, base, team, "team")
        if pointer(read, team + 0x80) != manager:
            raise ValueError("Team manager backlink disagrees")
        club_address = pointer(read, team + 0x30)
        club_record, club_id = club(read, base, club_address)
        if team not in vector(read, club_address + 0x18, 64):
            raise ValueError("Managed team is absent from club teams")
        coaches.append({"name": f"{first} {last}", "club": club_record,
                        "team_address": team, "manager_address": manager})
        bindings.append((user, manager, first, last, team, club_address, club_id))
    identity = (game, save, info, name, created, created_version, tuple(bindings))
    return {"name": name, "created_date": created, "created_version": created_version,
            "save_count": save_count, "last_saved_date": packed_date(read(save + 0x70, 4)),
            "current_date": current,
            "coaches": coaches}, identity
