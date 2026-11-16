"""Bounded live BASE_TRANSFER_MANAGER offer collections; no activation inference."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import secrets
import struct

from . import (
    assessment_people,
    currencies,
    database,
    players,
    staff,
    teams,
    wages,
    world,
)

ROOT = 0x56A49F8
BASE_OFFSET = 0x18
MAX_SLOTS = 100_000
CONTAINERS = ((0x20, "first_offer_vector"), (0x38, "second_offer_vector"))
# Full runtime types, not guessed object extents or archive-boundary patterns.
CLASSES = {
    0x55C77A8: ("draft", b"11DRAFT_OFFER", 0x1831790, 8),
    0x55C7BC0: ("enquiry", b"13ENQUIRY_OFFER", 0x1831A1C, 7),
    0x55C8C20: ("base_transfer", b"14TRANSFER_OFFER", 0x1871F18, 1),
    0x55C7FD8: ("full_transfer", b"19FULL_TRANSFER_OFFER", 0x1834944, 2),
    0x55C83F0: ("loan", b"10LOAN_OFFER", 0x1845BA8, 3),
    0x55C9058: ("trial", b"11TRIAL_OFFER", 0x18753F8, 4),
    0x55C8808: ("trade", b"11TRADE_OFFER", 0x1855484, 9),
    0x55C7278: ("b_club_move", b"17B_CLUB_MOVE_OFFER", 0x181ED88, 10),
}
NATIVE_SPANS = (
    (0x2D10278, bytes.fromhex("60620091f93aac97")),
    (0x186E07C, bytes.fromhex("083442391f6900f1")),
    (0x1865CD8, bytes.fromhex("60e20091e10314aab47ce297")),
    (0x1865CFC, bytes.fromhex("60020191e10314aa276fe297")),
    (0x1865D18, bytes.fromhex("60220191e10314aa206fe297")),
    (0x2DF2A44, bytes.fromhex("883a4239812a40f988000036")),
    (0x2DF28A8, bytes.fromhex("880a41b9c82200b9880241b9c8d600b9")),
    (0x2DF2974, bytes.fromhex("885a40b9890641b9c8a61929")),
    (0x2DF275C, bytes.fromhex("e00316aa03009697")),
    (0x13727C8, bytes.fromhex("081202f008a11391080000f9")),
    (0x2DF28C0, bytes.fromhex("882240f9c80a00f9")),
)

LIMITS = (
    "Complete first and second named BASE_TRANSFER_MANAGER offer vectors only, including historical objects. "
    "Not an active/pending-offer, acceptance, obligation or payment query. Current native state bytes are "
    "observed but English state labels remain unmapped; the separate UI display-status enum is not reused. "
    "Common PERSON and three TEAM links are canonical identities. LOAN common_team_40 is the proposed borrowing team; other TEAM roles and additional trade "
    "participants remain unresolved. Selectors cover only these common links. Loan terms are proposed stored "
    "terms, not current agreements. The third/later manager collections are outside this proved offer scope. "
    "Null slots, aliases and distinct offers are preserved. A changed source invalidates pagination. "
    "No game function, refresh, disk-save read, UI or game write is used."
)


def _chunks(read, start, size):
    return b"".join(
        read(at, min(8192, start + size - at))
        for at in range(start, start + size, 8192)
    )


def _vectors(read, manager):
    result = []
    for offset, name in CONTAINERS:
        raw = read(manager + offset, 24)
        start, end, capacity = struct.unpack("<QQQ", raw)
        if (start, end, capacity) == (0, 0, 0):
            values = ()
        else:
            if (
                start < 4096
                or any(p % 8 for p in (start, end, capacity))
                or not start <= end <= capacity
                or (end - start) % 8
                or capacity - start > MAX_SLOTS * 8
            ):
                raise ValueError("Unsupported live offer vector geometry or bound")
            data = _chunks(read, start, end - start)
            values = struct.unpack(f"<{len(data) // 8}Q", data)
            if any(p and (p < 4096 or p % 8) for p in values):
                raise ValueError("Invalid live offer object reference")
        result.append((name, raw, values))
    return result


def _read_headers(snapshot, addresses):
    """Batch only first reads; verify every consumed header independently.

    Padding inside a4KiB bucket is discarded and is never interpreted or kept.
    Header crossings use their own bounded read. The final ReadSet rechecks the
    exact144-byte object ranges, not unrelated padding.
    """
    buckets = {}
    for address in sorted(set(addresses) - {0}):
        key = address // 4096 if address % 4096 + 0x90 <= 4096 else -address
        buckets.setdefault(key, []).append(address)
    for values in buckets.values():
        first, last = values[0], values[-1] + 0x90
        raw = snapshot.read(first, last - first)
        for address in values:
            data = raw[address - first : address - first + 0x90]
            key = (address, 0x90)
            if key in snapshot.observed and snapshot.observed[key] != data:
                raise ValueError("Live offer header changed during batch read")
            snapshot.observed[key] = data


def _manager(read, base):
    pointer = players.u64(read(base + ROOT, 8))
    if not pointer:
        return None
    if pointer < 4096 or pointer % 8:
        raise ValueError("Invalid live transfer-manager root")
    world.typed(read, base, pointer, "transfer_manager")
    if players.u64(read(pointer + BASE_OFFSET, 8)) != base + 0x55F9AD0:
        raise ValueError("Live transfer-manager BASE subobject changed")
    parent, flags = struct.unpack("<QQ", read(base + 0x55F9C10, 16))
    if parent != base + 0x55C7788 or flags != 0x1802:
        raise ValueError("Transfer-manager BASE inheritance changed")
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError("Native transfer-offer member binding changed")
    return pointer


def _type(read, base, table):
    profile = CLASSES.get(table - base)
    if profile is None:
        raise ValueError("Unclassified live offer runtime class; population is unknown")
    kind, name, getter, code = profile
    displacement, info = struct.unpack("<qQ", read(table - 16, 16))
    if displacement != 0 or info < 4096 or info % 8:
        raise ValueError("Live offer primary type displacement changed")
    if code != 1 and players.u64(read(info + 16, 8)) != base + 0x55C9020:
        raise ValueError("Live offer common TRANSFER_OFFER ancestry changed")
    text = players.u64(read(info + 8, 8))
    if text < 4096 or read(text, len(name) + 1) != name + b"\0":
        raise ValueError("Live offer RTTI name changed")
    if players.u64(read(table + 0x78, 8)) != base + getter:
        raise ValueError("Live offer factory-kind getter changed")
    expected = struct.pack("<II", 0x52800000 | (code << 5), 0xD65F03C0)
    if read(base + getter, 8) != expected:
        raise ValueError("Live offer factory kind changed")
    return kind


def _canonical_person(read, base, info, address):
    if not address:
        return None
    if address < 4096 or address % 8:
        raise ValueError("Invalid offer PERSON reference")
    _, index, native, secondary = struct.unpack("<QIII", read(address, 20))
    if (
        not native
        or index >= info["count"]
        or (
            info["pointers"][index]
            if "pointers" in info
            else players.u64(read(info["start"] + index * 8, 8))
        )
        != address
    ):
        raise ValueError("Offer PERSON canonical membership changed")
    return {
        "database_index": index,
        "native_id": native,
        "random_id": None if secondary == native else secondary,
    }


def _canonical_team(read, base, info, address, owner_tables=None):
    if not address:
        return None
    if address < 4096 or address % 8:
        raise ValueError("Invalid offer TEAM reference")
    teams._typed(read, base, address, ("team", "national_team"))
    row, _ = teams._identity(read, address)
    index = row["database_index"]
    if (
        index >= info["count"]
        or index >= info["lookup_count"]
        or (
            info["pointers"][index]
            if "pointers" in info
            else players.u64(read(info["start"] + index * 8, 8))
        )
        != address
        or (
            info["lookup_pointers"][index]
            if "lookup_pointers" in info
            else players.u64(read(info["lookup_start"] + index * 8, 8))
        )
        != address
    ):
        raise ValueError("Offer TEAM canonical membership changed")
    owner_address = players.u64(read(address + 0x30, 8))
    owner = None
    if owner_address:
        kind = teams._typed(
            read,
            base,
            owner_address,
            ("club", "league_body_club", "national_team_container"),
        )
        owner, _ = teams._identity(read, owner_address)
        owner["kind"] = kind
        owner_tables = {} if owner_tables is None else owner_tables
        table_kind = (
            "national_team_containers" if kind == "national_team_container" else "clubs"
        )
        if table_kind not in owner_tables:
            source = database.table(read, base, table_kind)
            source["pointers"] = struct.unpack(
                f"<{source['count']}Q",
                _chunks(read, source["start"], source["count"] * 8),
            )
            owner_tables[table_kind] = source
        source = owner_tables[table_kind]
        if (
            owner["database_index"] >= source["count"]
            or source["pointers"][owner["database_index"]] != owner_address
        ):
            raise ValueError("Offer TEAM owner canonical membership changed")
    return {**row, "owner": owner}


def _person_name(read, base, info, address, identity):
    if identity is None:
        return {"state": "null_primary_person", "identity": None, "name": None}
    if players.u64(read(address, 8)) - base not in assessment_people._PERSON_TYPES:
        return {
            "state": "canonical_PERSON_unsupported_type",
            "identity": identity,
            "record_kind": None,
            "name": None,
            "name_state": "unavailable_unsupported_person_type",
        }
    primary, _, public, _, _ = assessment_people._person(read, base, info, address)
    kind = public["record_kind"]
    if kind in ("actual", "player_staff"):
        decoded, _ = players.decode(
            read, primary, tuple(base + rva for rva in players.RVA)
        )
        name = decoded["display_name"]
    elif kind in staff.LAYOUTS:
        decoded, _ = staff.decode(read, base, primary)
        name = decoded["display_name"]
    else:
        name = None
    return {
        "state": "canonical_PERSON",
        "identity": identity,
        "record_kind": kind,
        "name": name,
        "name_state": "stored_native_strings"
        if name
        else "unavailable_without_generated_profile",
    }


def _cash(value, currency, period):
    return {
        "amount": value if value >= 0 else None,
        "raw_signed32": value,
        "currency": currency,
        "period": period,
        "unit": "whole_base_currency_units",
        "basis": "stored_proposed_offer_term",
        "state": "stored_proposed_term" if value >= 0 else "unmapped_negative_code",
    }


def query(
    bridge,
    session_id,
    *,
    person_native_id=None,
    team_native_id=None,
    club_native_id=None,
    raw_state_codes=None,
    limit=50,
    cursor=None,
):
    for value in (person_native_id, team_native_id, club_native_id):
        if value is not None and (
            type(value) is not int or not 1 <= value <= 0xFFFFFFFF
        ):
            raise ValueError(
                "Native identity selectors must be positive unsigned32 integers"
            )
    if raw_state_codes is not None and (
        not isinstance(raw_state_codes, list)
        or not raw_state_codes
        or len(raw_state_codes) > 256
        or any(type(v) is not int or not 0 <= v <= 255 for v in raw_state_codes)
        or len(set(raw_state_codes)) != len(raw_state_codes)
    ):
        raise ValueError("Supply distinct raw offer-state bytes")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Offer page limit must be 1–100")
    if cursor is not None and (not isinstance(cursor, str) or not cursor):
        raise ValueError("Offer cursor must be a nonempty opaque string")
    selectors = (
        session_id,
        person_native_id,
        team_native_id,
        club_native_id,
        tuple(sorted(raw_state_codes or ())),
        limit,
    )
    with bridge.lock, bridge._read_scope(session_id):
        previous = None
        if cursor is not None:
            previous = bridge.database_cursors.get(cursor)
            if (
                not previous
                or previous.get("kind") != "live_transfer_offers"
                or previous["selectors"] != selectors
            ):
                raise ValueError("Offer cursor expired or selectors changed")
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        base = tables[0] - players.RVA[0]
        snapshot, save, epoch = bridge._world_state(process, tables)
        native_read = snapshot.read
        consumed_requests = consumed_bytes = 0

        def budgeted_read(address, size):
            nonlocal consumed_requests, consumed_bytes
            consumed_requests += 1
            consumed_bytes += size
            if consumed_requests > 90000 or consumed_bytes > 56 * 1024 * 1024:
                raise ValueError(
                    "Live offer native read work budget exceeded; no result accepted"
                )
            return native_read(address, size)

        snapshot.read = budgeted_read

        def read(address, size):
            # Reuse one first observation; final snapshot.verify rereads every
            # consumed range through the uncached native transport.
            key = (address, size)
            if key in snapshot.observed:
                return snapshot.observed[key]
            return snapshot(address, size)

        manager = _manager(read, base)
        if manager is None:
            snapshot.verify()
            return {
                "state": "unavailable_transfer_manager",
                "offers": [],
                "complete_source": False,
                "match_count": None,
                "next_cursor": None,
                "limitations": LIMITS,
            }
        vectors = _vectors(read, manager)
        if not any(any(values) for _, _, values in vectors):
            if previous:
                raise ValueError(
                    "Live offer population changed to empty; start a new query"
                )
            snapshot.verify()
            bridge._current(session_id)
            return {
                "session_id": session_id,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "save": bridge._public_save(save),
                "state": "available_empty",
                "complete_source": True,
                "source_scope": "two_complete_named_BASE_TRANSFER_MANAGER_offer_vectors",
                "source_id": hashlib.sha256(
                    repr(epoch).encode() + b"".join(header for _, header, _ in vectors)
                ).hexdigest(),
                "containers": [
                    {
                        "container": name,
                        "slots": len(values),
                        "null_slots": len(values),
                        "nonnull_slots": 0,
                        "distinct_objects": 0,
                    }
                    for name, _, values in vectors
                ],
                "nonnull_occurrences": 0,
                "distinct_offer_objects": 0,
                "source_offer_type_counts": {},
                "source_native_state_counts": {},
                "match_count": 0,
                "returned_count": 0,
                "offers": [],
                "next_cursor": None,
                "base_currency": None,
                "base_currency_state": "not_read_for_empty_offer_source",
                "native_functions_executed": False,
                "game_writes": False,
                "limitations": LIMITS,
            }
        assessment_people.verify_native(read, base)
        people = database.table(read, base, "people")
        team_table = teams.lookup(read, base)
        if person_native_id is not None:
            people["pointers"] = struct.unpack(
                f"<{people['count']}Q",
                _chunks(read, people["start"], people["count"] * 8),
            )
        if team_native_id is not None or club_native_id is not None:
            team_table["pointers"] = struct.unpack(
                f"<{team_table['count']}Q",
                _chunks(read, team_table["start"], team_table["count"] * 8),
            )
            team_table["lookup_pointers"] = struct.unpack(
                f"<{team_table['lookup_count']}Q",
                _chunks(
                    read, team_table["lookup_start"], team_table["lookup_count"] * 8
                ),
            )
        owner_tables = {}

        def person_for(address):
            if address not in people_cache:
                people_cache[address] = _canonical_person(read, base, people, address)
            return people_cache[address]

        def team_for(address):
            if address not in team_cache:
                team_cache[address] = _canonical_team(
                    read, base, team_table, address, owner_tables
                )
            return team_cache[address]

        _read_headers(snapshot, [a for _, _, values in vectors for a in values])
        objects = {}
        occurrences = []
        inventory = []
        classes = {}
        people_cache = {}
        team_cache = {}
        digest = hashlib.sha256(repr((process.pid, epoch)).encode())
        for name, header, addresses in vectors:
            digest.update(name.encode() + header)
            for ordinal, address in enumerate(addresses):
                digest.update(struct.pack("<Q", address))
                if not address:
                    continue
                if address not in objects:
                    raw = read(address, 0x90)
                    digest.update(raw)
                    table = players.u64(raw, 0)
                    if table not in classes:
                        classes[table] = _type(read, base, table)
                    person = players.u64(raw, 0x38)
                    team_addresses = tuple(
                        players.u64(raw, i) for i in (0x40, 0x48, 0x50)
                    )
                    objects[address] = {
                        "raw": raw,
                        "offer_type": classes[table],
                        "person_address": person,
                        "team_addresses": team_addresses,
                    }
                occurrences.append((name, ordinal, address))
            inventory.append(
                {
                    "container": name,
                    "slots": len(addresses),
                    "null_slots": addresses.count(0),
                    "nonnull_slots": sum(bool(a) for a in addresses),
                    "distinct_objects": len(set(addresses) - {0}),
                }
            )
        selected = []
        for name, ordinal, address in occurrences:
            row = objects[address]
            if raw_state_codes is not None and row["raw"][0x8D] not in raw_state_codes:
                continue
            if person_native_id is not None:
                person = person_for(row["person_address"])
                if not person or person["native_id"] != person_native_id:
                    continue
            linked = (
                [team_for(a) for a in row["team_addresses"]]
                if team_native_id is not None or club_native_id is not None
                else []
            )
            if team_native_id is not None and not any(
                t and t["native_id"] == team_native_id for t in linked
            ):
                continue
            if club_native_id is not None and not any(
                t
                and t["owner"]
                and t["owner"]["kind"] != "national_team_container"
                and t["owner"]["native_id"] == club_native_id
                for t in linked
            ):
                continue
            selected.append((name, ordinal, address))
        digest.update(
            json.dumps(
                {"person_predicates": people_cache, "team_predicates": team_cache},
                sort_keys=True,
            ).encode()
        )
        source_id = digest.hexdigest()
        if previous and (
            previous["source_id"] != source_id or previous["epoch"] != epoch
        ):
            raise ValueError(
                "Live offer population, states or predicate identities changed; start a new query"
            )
        offset = previous["offset"] if previous else 0
        currency = None
        base_currency = None
        currency_state = "unavailable_base_currency_context"
        try:
            currency = wages.base_currency(read, base)
            currency_table = database.table(read, base, "currencies")
            for i in range(currency_table["count"]):
                a = players.u64(read(currency_table["start"] + i * 8, 8))
                if int.from_bytes(read(a + 12, 4), "little") == 86:
                    base_currency, _ = currencies.record(read, base, a)
            currency_state = "verified_native_GBP_base_currency"
        except ValueError:
            # Offers remain useful when optional base-currency semantics differ.
            # The final byte recheck still rejects any changed consumed source.
            currency = None
            base_currency = None
        output = []
        for name, ordinal, address in selected[offset : offset + limit]:
            item = objects[address]
            raw = item["raw"]
            person = item["person_address"]
            references = []
            for native_field, a in zip(
                ("common_team_40", "common_team_48", "common_team_50"),
                item["team_addresses"],
            ):
                if a:
                    linked, _ = teams.by_index(
                        read, base, team_for(a)["database_index"], info=team_table
                    )
                else:
                    linked = None
                references.append(
                    {
                        "source_field": native_field,
                        "business_role": "proposed_borrowing_team"
                        if item["offer_type"] == "loan"
                        and native_field == "common_team_40"
                        else None,
                        "team": linked,
                    }
                )
            terms = {}
            amount = struct.unpack_from("<i", raw, 0x58)[0]
            if item["offer_type"] == "loan":
                unused, fee, playing = struct.unpack("<iii", read(address + 0x100, 12))
                terms = {
                    k: _cash(v, currency, period)
                    for k, v, period in (
                        ("playing_weekly_wage", playing, "week"),
                        ("unused_weekly_wage", unused, "week"),
                        ("playing_monthly_fee", amount, "month"),
                        ("unused_monthly_fee", fee, "month"),
                    )
                }
            output.append(
                {
                    "container": name,
                    "slot": ordinal,
                    "object_id": hashlib.sha256(
                        source_id.encode() + struct.pack("<Q", address)
                    ).hexdigest()[:24],
                    "offer_type": item["offer_type"],
                    "person": _person_name(
                        read, base, people, person, person_for(person)
                    ),
                    "team_references": references,
                    "native_state": {
                        "code": raw[0x8D],
                        "label": None,
                        "state": "unmapped_native_offer_state",
                    },
                    "stored_proposed_loan_terms": terms,
                    "unmapped_common_58": None
                    if terms
                    else {"raw_signed32": amount, "meaning": None, "currency": None},
                    "acceptance_state": "not_established",
                    "payment_obligation": "not_established",
                }
            )
        snapshot.verify()
        bridge._current(session_id)
        next_cursor = None
        if offset + len(output) < len(selected):
            next_cursor = secrets.token_urlsafe(16)
            if len(bridge.database_cursors) >= 256:
                bridge.database_cursors.clear()
            bridge.database_cursors[next_cursor] = {
                "kind": "live_transfer_offers",
                "selectors": selectors,
                "offset": offset + len(output),
                "source_id": source_id,
                "epoch": epoch,
            }
        return {
            "session_id": session_id,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "save": bridge._public_save(save),
            "state": "available" if occurrences else "available_empty",
            "complete_source": True,
            "source_scope": "two_complete_named_BASE_TRANSFER_MANAGER_offer_vectors",
            "source_id": source_id,
            "source_id_scope": "Manager membership, common headers and predicate identities. Names and loan-leaf terms refresh and recheck on the returned page only.",
            "containers": inventory,
            "nonnull_occurrences": len(occurrences),
            "distinct_offer_objects": len(objects),
            "source_count_basis": "distinct_native_objects; offer rows preserve each container membership",
            "source_offer_type_counts": dict(
                Counter(o["offer_type"] for o in objects.values())
            ),
            "source_native_state_counts": dict(
                Counter(o["raw"][0x8D] for o in objects.values())
            ),
            "selectors": {
                "person_native_id": person_native_id,
                "team_native_id": team_native_id,
                "club_native_id": club_native_id,
                "raw_state_codes": raw_state_codes,
            },
            "match_count": len(selected),
            "returned_count": len(output),
            "offers": output,
            "next_cursor": next_cursor,
            "base_currency": base_currency,
            "base_currency_state": currency_state,
            "unavailable_person_names_in_page": sum(
                not o["person"].get("name") for o in output
            ),
            "identity_scope": "Canonical identities used by predicates and returned rows; unreturned unfiltered links are not decoded.",
            "native_functions_executed": False,
            "game_writes": False,
            "limitations": LIMITS,
        }
