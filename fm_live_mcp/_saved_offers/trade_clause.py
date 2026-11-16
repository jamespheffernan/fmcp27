"""11DD52C/11DD3D4 child only; caller owns the1857024 marker/tail.

Current paired-writer subset. References preserve original serialized indices;
no live identity or trade/permission outcome is inferred.
"""

import struct

PROFILE = "comp_compact16_team_marker_index32"


def parse(data, start, *, limit=None, profile=PROFILE):
    if profile != PROFILE:
        raise ValueError("Explicit supported TRADE child reference profile required")
    bound = len(data) if limit is None else limit
    if (
        type(start) is not int
        or type(bound) is not int
        or (not 0 <= start <= bound <= len(data))
    ):
        raise ValueError("Invalid TRADE child bounds")
    at = start

    def take(n):
        nonlocal at
        if n > bound - at:
            raise ValueError(f"Truncated TRADE child at{at}")
        old = at
        at += n
        return bytes(data[old:at])

    def number(code):
        return struct.unpack("<" + code, take(struct.calcsize("<" + code)))[0]

    marker = number("B")
    if marker != 1:
        raise ValueError("TRADE child marker differs from paired current writer")
    reference_start = at
    short = number("h")
    index = short
    if short == -2:
        index = number("i")
        if index < 0:
            raise ValueError("Negative TRADE child escaped reference")
    elif short < -1:
        raise ValueError("Negative TRADE child compact reference")
    reference = {
        "start": reference_start,
        "end": at,
        "signed16": short,
        "stored_index": None if short == -1 else index,
        "raw_hex": bytes(data[reference_start:at]).hex(),
        "native_reader": "0x1101bfc",
        "identity_resolved": False,
    }
    raw12 = number("b")
    raw13 = number("b")
    raw14 = number("b")
    team_start = at
    team_marker = number("B")
    if team_marker not in (0, 1):
        raise ValueError("Unproved TRADE child TEAM marker")
    team_index = number("i")
    if team_index < -1:
        raise ValueError("Negative TRADE child TEAM index")
    identity_word = number("I") if team_marker == 1 and team_index != -1 else None
    team = {
        "start": team_start,
        "end": at,
        "marker": team_marker,
        "stored_index": team_index,
        "secondary_word": identity_word,
        "native_reader": "0x11019a0",
        "namespace": "TEAM_BASE",
        "identity_resolved": False,
    }
    raw15 = number("B")
    year = number("H")
    return {
        "start": start,
        "end": at,
        "complete_child_wire": True,
        "profile": profile,
        "reference00": reference,
        "team08": team,
        "native_fields": {
            "12_signed8": raw12,
            "13_signed8": raw13,
            "14_signed8": raw14,
            "15_unsigned8": raw15,
            "10_unsigned16": year,
        },
        "native_property_values": {
            "type": raw12,
            "roun": raw13,
            "pick": raw14,
            "year": year,
        },
        "native_property_special_cases": {
            "type_minus1": raw12 == -1,
            "pick_100": raw14 == 100,
            "year_1900": year == 1900,
        },
        "runtime_globals_observed": False,
        "reference_identities_resolved": False,
    }
