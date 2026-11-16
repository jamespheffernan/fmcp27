"""FULL_TRANSFER_OFFER leaf1839678/1839460; no acceptance/payment inference."""

from ..person_wire import _loan_1862c00 as _details
from .wire import Cursor, UnsupportedOffer as Unsupported


def parse(
    data, start, *, limit=None, version=20, reference_profile=None, child_readers=None
):
    if version != 20:
        raise ValueError("Unsupported inherited FULL_TRANSFER_OFFER common version")
    if reference_profile != "person_index32_team_marker_index32":
        raise ValueError("Explicit PERSON reference profile required")
    c = Cursor(data, start, limit)
    parts = {}
    children = child_readers or {}
    count_start = c.offset
    count = c.number(1, True)
    if count < 0:
        raise Unsupported(
            25632192,
            count_start,
            {
                "count_raw_i8": count,
                "reason": "negative signed count outside checked writer subset",
            },
        )
    clauses = []
    for _ in range(count):
        callback = children.get(25632192)
        if callback is None:
            raise Unsupported(25632192, c.offset, {"count": count, "rows": clauses})
        row = callback(data, c.offset, limit=c.limit)
        if (
            not isinstance(row, dict)
            or type(row.get("end")) is not int
            or (not c.offset <= row["end"] <= c.limit)
        ):
            raise ValueError("Invalid transfer clause endpoint")
        c.offset = row["end"]
        clauses.append(row)
    parts["native_90_vector"] = {"count": count, "rows": clauses}
    fields = []

    def scalar(destination, width):
        begin = c.offset
        raw = c.take(width)
        fields.append(
            {
                "native_destination": hex(destination),
                "start": begin,
                "end": c.offset,
                "raw_hex": raw.hex(),
            }
        )

    scalar(192, 4)
    begin = c.offset
    person = c.number(4, True)
    if person < -1:
        raise ValueError("Negative PERSON original index outside checked subset")
    parts["native_b0_PERSON"] = {
        "start": begin,
        "end": c.offset,
        "database_index": None if person == -1 else person,
    }
    presence = c.number(1)
    if presence not in (0, 1):
        raise ValueError("FULL_TRANSFER_OFFER presence outside paired writer boolean")
    parts["native_a8_present"] = presence
    if presence:
        try:
            details = _details.parse(
                data, c.offset, limit=c.limit, vector_a8_reader=children.get(24050136)
            )
        except _details.UnsupportedChild as error:
            raise Unsupported(
                error.native, error.offset, {"loan_details": error.parts}
            ) from error
        c.offset = details["end"]
        details["scope"] = (
            "same native1862C00 object reached from FULL_TRANSFER_OFFER+A8"
        )
        parts["native_a8_details"] = details
    for destination, width in ((196, 4), (200, 4), (184, 8), (204, 2), (206, 2)):
        scalar(destination, width)
    return {
        "start": start,
        "end": c.offset,
        "fields": fields,
        "parts": parts,
        "source_record_kind": "FULL_TRANSFER_OFFER",
        "native_reader": "0x1839678",
        "native_writer": "0x1839460",
        "offer_accepted_or_payable_proved": False,
        "field_meanings": "unresolved",
    }
