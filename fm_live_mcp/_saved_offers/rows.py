"""Compose current native offer rows without scanning for record boundaries."""

from ..person_wire import _loan_1862c00
from . import full, loan, option, reference_collection, small, trade, trade_clause
from .wire import Cursor, PROFILE, UnsupportedOffer, parse_common

MAX_ROW_BYTES = 1024 * 1024
CLASS_NAMES = {
    2: "FULL_TRANSFER_OFFER",
    3: "LOAN_OFFER",
    4: "TRIAL_OFFER",
    7: "ENQUIRY_OFFER",
    9: "TRADE_OFFER",
    10: "B_CLUB_MOVE_OFFER",
}


def _references(data, start, *, limit):
    return reference_collection.parse(
        data, start, limit=limit, reference_mode="compact16"
    )


def _details(data, start, *, limit):
    try:
        result = _loan_1862c00.parse(
            data,
            start,
            limit=limit,
            vector_a8_reader=lambda data, start: _references(
                data, start, limit=len(data)
            ),
        )
    except _loan_1862c00.UnsupportedChild as error:
        raise UnsupportedOffer(error.native, error.offset) from error
    result["scope"] = "same native 1862C00 child within the stored offer"
    return result


def parse_row(data, start, *, limit=None):
    cursor = Cursor(data, start, limit)
    kind = cursor.number(1, True)
    if kind == 0:
        return {
            "start": start,
            "end": cursor.offset,
            "kind": 0,
            "source_class": None,
            "common": None,
            "child": None,
        }
    if kind not in CLASS_NAMES:
        raise UnsupportedOffer(0x1829758, start, {"kind": kind})
    common = parse_common(data, cursor.offset, limit=cursor.limit, profile=PROFILE)
    arguments = {"limit": cursor.limit, "version": common["version"]}
    if kind == 3:
        child = loan.parse(
            data,
            common["end"],
            comp_reference_mode="compact16",
            child_readers={
                0x1862C00: _details,
                0x16EF9D8: _references,
                0x1323F30: option.parse,
            },
            **arguments,
        )
    elif kind == 2:
        child = full.parse(
            data,
            common["end"],
            reference_profile=PROFILE,
            child_readers={
                0x16EF9D8: lambda data, start: _references(data, start, limit=len(data))
            },
            **arguments,
        )
    elif kind == 9:
        child = trade.parse(
            data,
            common["end"],
            reference_profile=PROFILE,
            child_readers={
                0x11DD52C: lambda data, start, **kw: trade_clause.parse(
                    data, start, profile="comp_compact16_team_marker_index32", **kw
                )
            },
            **arguments,
        )
    else:
        child = small.parse(
            data, common["end"], kind=kind, reference_profile=PROFILE, **arguments
        )
    end = child["end"]
    if type(end) is not int or not common["end"] <= end <= cursor.limit:
        raise ValueError("Invalid stored offer child extent")
    if end - start > MAX_ROW_BYTES:
        raise ValueError("Stored offer object exceeds byte budget")
    return {
        "start": start,
        "end": end,
        "kind": kind,
        "source_class": CLASS_NAMES[kind],
        "common": common,
        "child": child,
    }
