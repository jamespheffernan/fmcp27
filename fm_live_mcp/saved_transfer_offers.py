"""Selected stored offers from two complete, same-snapshot native vectors."""

import hashlib
import json
import struct
from threading import BoundedSemaphore

from . import saved_component_stream, snapshot_catalog
from ._saved_offers.rows import parse_row
from ._saved_offers.wire import Cursor, manager_prefix

MAX_COMPONENT_BYTES = 32 * 1024 * 1024
MAX_PACKED_BYTES = 64 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_VECTOR_SLOTS = 1_000_000
_QUERY_SLOT = BoundedSemaphore(1)
PROFILE = "source3754_minor9_file35_common20_person32_team_marker32_comp16_descriptor_slot0_16"
SCOPE = "complete first and second BASE_TRANSFER_MANAGER offer vectors"


def _selectors(person_index, team_index):
    if person_index is None and team_index is None:
        raise ValueError("Supply a same-snapshot PERSON or TEAM index")
    for value in (person_index, team_index):
        if value is not None and (type(value) is not int or not 0 <= value < 2**31):
            raise ValueError("Invalid same-snapshot offer selector")


def _scalar(common, destination, *, signed=False):
    field = next(
        row for row in common["fields"] if row["native_destination"] == destination
    )
    raw = bytes.fromhex(field["raw_hex"])
    return (
        int.from_bytes(raw, "little", signed=signed),
        field["start"],
        field["raw_hex"],
    )


def _term(value, offset, raw_hex, period):
    return {
        "amount": value if value >= 0 else None,
        "raw_signed32": value,
        "currency": None,
        "unit": "whole_base_currency_units",
        "basis": "stored_offer_term",
        "period": period,
        "state": "stored_offer_term" if value >= 0 else "unmapped_negative_code",
        "source_offset": offset,
        "raw_hex": raw_hex,
    }


def _project(record, container, ordinal, data):
    common, child = record["common"], record["child"]
    first_index, _, _ = _scalar(common, "0x5c", signed=True)
    second_index, _, _ = _scalar(common, "0x64", signed=True)
    word, _, _ = _scalar(common, "0x60")
    state, state_offset, _ = _scalar(common, "0x8d")
    person = common["references"][0]
    teams = [
        {
            "native_field": ref["native_destination"],
            "database_index": ref["database_index"],
            "namespace": "TEAM_BASE",
            "role": "unresolved",
            "source_offset": ref["start"],
            "source_end": ref["end"],
            "index_source_offset": ref["start"] + 1,
            "marker_raw_u8": ref["marker"],
            "identity_word_raw_hex": ref["identity_words_raw_hex"],
        }
        for ref in common["references"][1:]
    ]
    terms = {}
    if record["kind"] == 3:
        for name, native, period in (
            ("playing_weekly_wage", "0x108", "week"),
            ("unused_weekly_wage", "0x100", "week"),
            ("unused_monthly_fee", "0x104", "month"),
        ):
            field = child["fields"][native]
            terms[name] = _term(
                field["stored_signed32"],
                field["source_offset"],
                field["raw_hex"],
                period,
            )
        value, offset, raw = _scalar(common, "0x58", signed=True)
        terms["playing_monthly_fee"] = _term(value, offset, raw, "month")
    raw_value, raw_offset, raw_hex = _scalar(common, "0x58", signed=True)
    return {
        "container": container,
        "serialized_slot": ordinal,
        "source_class": record["source_class"],
        "source_kind_code": record["kind"],
        "person_index": person["database_index"],
        "person_namespace": "PERSON",
        "person_match_field": "native+0x38",
        "person_reference_witness": {
            "start": person["start"],
            "end": person["end"],
            "raw_hex": bytes(data[person["start"] : person["end"]]).hex(),
        },
        "team_references": teams,
        "stored_vector_indices": {"first": first_index, "second": second_index},
        "native_60_unsigned_word": word,
        "offer_state": {
            "raw_code": state,
            "label": None,
            "meaning": "unresolved",
            "source_offset": state_offset,
        },
        "stored_loan_terms": terms,
        "native_58": {
            "raw_signed32": raw_value,
            "source_offset": raw_offset,
            "raw_hex": raw_hex,
            "meaning": "playing_monthly_fee"
            if record["kind"] == 3
            else "unresolved_for_this_class",
        },
        "commitment_state": "unresolved",
        "currency_state": "not_joined",
        "source": {
            "offset_space": "transfer_manager_component_decompressed",
            "start": record["start"],
            "end": record["end"],
            "sha256": hashlib.sha256(
                memoryview(data)[record["start"] : record["end"]]
            ).hexdigest(),
        },
    }


def scan_buffer(data, *, person_index=None, team_index=None, offset=0, limit=50):
    """Pure bounded decoder; the caller must establish the same-file DB profile."""
    _selectors(person_index, team_index)
    snapshot_catalog._page(offset, limit)
    if len(data) > MAX_COMPONENT_BYTES:
        raise ValueError("Transfer component exceeds supported byte budget")
    prefix = manager_prefix(data, max_rows=MAX_VECTOR_SLOTS)
    cursor = Cursor(data, prefix["first_type_offset"])
    containers, selected = [], []
    matched = total_objects = total_null = 0
    for name, native_offset in (
        ("first_offer_vector", "0x8"),
        ("second_offer_vector", "0x20"),
    ):
        if native_offset == "0x8":
            count_start, count = (
                prefix["first_type_offset"] - 4,
                prefix["first_vector_count"],
            )
        else:
            count_start = cursor.offset
            count = cursor.number(4)
        if count > MAX_VECTOR_SLOTS or count > cursor.limit - cursor.offset:
            raise ValueError("Offer vector exceeds supported work or source extent")
        records_start = cursor.offset
        objects = nulls = container_matches = 0
        classes = {}
        for ordinal in range(count):
            record = parse_row(data, cursor.offset, limit=cursor.limit)
            cursor.offset = record["end"]
            if record["kind"] == 0:
                nulls += 1
                continue
            objects += 1
            source_class = record["source_class"]
            classes[source_class] = classes.get(source_class, 0) + 1
            refs = record["common"]["references"]
            person_matches = (
                person_index is None or refs[0]["database_index"] == person_index
            )
            team_matches = team_index is None or any(
                ref["database_index"] == team_index for ref in refs[1:]
            )
            if person_matches and team_matches:
                container_matches += 1
                if offset <= matched < offset + limit:
                    selected.append(_project(record, name, ordinal, data))
                matched += 1
        total_objects += objects
        total_null += nulls
        containers.append(
            {
                "name": name,
                "native_vector_offset": native_offset,
                "count_offset": count_start,
                "records_start": records_start,
                "end": cursor.offset,
                "declared_slots": count,
                "decoded_slots": count,
                "offer_objects": objects,
                "null_slots": nulls,
                "matched_count": container_matches,
                "source_classes": classes,
                "complete": True,
                "sha256": hashlib.sha256(
                    memoryview(data)[count_start : cursor.offset]
                ).hexdigest(),
            }
        )
    # The native third vector begins with a count and at least13B per row under
    # this explicit PERSON32 profile. Check its header/physical extent, without
    # interpreting its rows or claiming the remaining manager is decoded.
    following_start = cursor.offset
    third_count = cursor.number(4)
    if third_count > (cursor.limit - cursor.offset) // 13:
        raise ValueError("Following manager reference vector exceeds source extent")
    return {
        "query": {
            "person_index": person_index,
            "team_index": team_index,
            "person_matching_scope": "common offer PERSON+0x38",
            "team_matching_scope": "common offer TEAM+0x40/+0x48/+0x50",
            "combined_selectors": "AND",
            "canonical_selector_membership_checked": False,
        },
        "matched_count": matched,
        "offset": offset,
        "limit": limit,
        "next_offset": offset + limit if offset + limit < matched else None,
        "rows": selected,
        "coverage": {
            "scope": SCOPE,
            "containers": containers,
            "decoded_slots": sum(row["decoded_slots"] for row in containers),
            "offer_objects": total_objects,
            "null_slots": total_null,
            "complete_requested_scope": True,
            "absence_proved_in_requested_scope": matched == 0,
            "whole_manager_decoded": False,
            "full_save_absence_proved": False,
            "later_manager_sections": {
                "state": "not_decoded",
                "start": following_start,
                "next_count_header_checked": True,
                "third_declared_count": third_count,
            },
        },
        "source_profile": PROFILE,
        "source_profile_is_conditional": True,
        "runtime_native_globals_proved": False,
        "native_loader_acceptance_proved": False,
        "accepted_or_scheduled_commitments_proved": False,
    }


def _packed_digest(handle, entry):
    handle.seek(26 + entry.start)
    digest = hashlib.sha256()
    remaining = entry.compressed_size
    while remaining:
        block = handle.read(min(remaining, saved_component_stream.BLOCK_SIZE))
        if not block:
            raise ValueError("Truncated packed transfer component")
        digest.update(block)
        remaining -= len(block)
    return digest.hexdigest()


def find_offers(
    filename,
    *,
    expected_snapshot_id,
    person_index=None,
    team_index=None,
    offset=0,
    limit=50,
    directory=None,
):
    """Find stored source offer records, preserving container order and duplicates.

    The selectors use original indices issued for this exact snapshot. PERSON
    matches the common+38 field; TEAM matches common+40/+48/+50. Both selectors
    combine with AND. A result is a stored offer, not proof of acceptance, an
    active contract, a scheduled payment or an amount due. Currency stays null.
    """
    _selectors(person_index, team_index)
    snapshot_catalog.check_filename(filename)
    snapshot_catalog._page(offset, limit)
    if (
        not isinstance(expected_snapshot_id, str)
        or len(expected_snapshot_id) != 64
        or any(c not in "0123456789abcdef" for c in expected_snapshot_id)
    ):
        raise ValueError(
            "Supply the exact expected_snapshot_id for these original indices"
        )
    if not _QUERY_SLOT.acquire(blocking=False):
        raise ValueError("Another saved offer query is in progress; retry later")
    try:
        with snapshot_catalog.checked_snapshot(filename, directory=directory) as (
            handle,
            entries,
            identity,
        ):
            pin = snapshot_catalog.snapshot_id(identity)
            if pin != expected_snapshot_id:
                raise ValueError(
                    "Snapshot identity changed since offer indices were read"
                )
            if not entries:
                raise ValueError("Snapshot has no archive entries")
            root = entries[0].path.split("/")[0]
            members = [
                entry for entry in entries if entry.path == f"{root}/transfer_man.dat"
            ]
            databases = [
                entry for entry in entries if entry.path == f"{root}/game_db.dat"
            ]
            if len(members) != 1 or len(databases) != 1:
                raise ValueError(
                    "Snapshot requires one root transfer_man.dat and game_db.dat"
                )
            member = members[0]
            if member.uncompressed_size > MAX_COMPONENT_BYTES:
                raise ValueError("Transfer component exceeds supported byte budget")
            if member.compressed_size > MAX_PACKED_BYTES:
                raise ValueError(
                    "Packed transfer component exceeds supported byte budget"
                )
            with saved_component_stream.open_component(handle, databases[0]) as reader:
                database_header = reader.take(12)
            if database_header[:6] != b"\x03\x01tad." or struct.unpack_from(
                "<HHH", database_header, 6
            ) != (4000, 3754, 9):
                raise ValueError("Unsupported same-snapshot database source profile")
            packed = _packed_digest(handle, member)
            with saved_component_stream.open_component(handle, member) as reader:
                data = bytearray()
                while reader.offset < reader.size:
                    data.extend(
                        reader.take(
                            min(
                                saved_component_stream.BLOCK_SIZE,
                                reader.size - reader.offset,
                            )
                        )
                    )
                if reader.source.read(1) or not reader.source.finished:
                    raise ValueError(
                        "Transfer component did not end at its declared frame extent"
                    )
            result = scan_buffer(
                data,
                person_index=person_index,
                team_index=team_index,
                offset=offset,
                limit=limit,
            )
            if _packed_digest(handle, member) != packed:
                raise ValueError("Packed transfer component changed during offer query")
            result.update(
                source="on-disk save snapshot",
                filename=filename,
                snapshot_id=pin,
                saved_metadata=snapshot_catalog._metadata(handle, entries),
                component={
                    "path": member.path,
                    "compressed_start": 26 + member.start,
                    "compressed_bytes": member.compressed_size,
                    "raw_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "packed_sha256": packed,
                    "full_frame_validated": True,
                },
                database_profile={
                    "serializer_version": 4000,
                    "source_major": 3754,
                    "source_minor": 9,
                },
            )
        if (
            len(json.dumps(result, ensure_ascii=True, separators=(",", ":")).encode())
            > MAX_RESPONSE_BYTES
        ):
            raise ValueError(
                "Selected offer page exceeds response budget; reduce limit"
            )
        return result
    finally:
        _QUERY_SLOT.release()
