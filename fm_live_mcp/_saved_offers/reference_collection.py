"""16EF9D8/127A970 vector with explicit1116FA4 descriptor-slot0 transport.

The current writer emits u16 marker1 per row. Reference identities and raw
payload meanings remain unresolved; no surrounding raw64 mode is inherited.
"""

import struct


def parse(data, start, *, limit=None, reference_mode="compact16", max_rows=4096):
    if reference_mode not in ("compact16", "direct32", "raw64"):
        raise ValueError("Unsupported explicit1116FA4 profile")
    bound = len(data) if limit is None else limit
    if (
        type(start) is not int
        or type(bound) is not int
        or (not 0 <= start <= bound <= len(data))
    ):
        raise ValueError("Invalid16EF9D8 bounds")
    if type(max_rows) is not int or not 0 <= max_rows <= 65536:
        raise ValueError("Invalid16EF9D8 work bound")
    at = start

    def take(n):
        nonlocal at
        if n > bound - at:
            raise ValueError(f"Truncated16EF9D8 at{at}")
        old = at
        at += n
        return bytes(data[old:at])

    def number(code):
        return struct.unpack("<" + code, take(struct.calcsize("<" + code)))[0]

    count = number("I")
    minimum = (
        9
        if reference_mode == "compact16"
        else 11
        if reference_mode == "direct32"
        else 15
    )
    if count > max_rows or count > (bound - at) // minimum:
        raise ValueError("16EF9D8 collection exceeds work/input bounds")
    rows = []
    for ordinal in range(count):
        begin = at
        marker = number("H")
        if marker != 1:
            raise ValueError("16EF9D8 row marker differs from paired current writer1")
        ref_start = at
        if reference_mode == "compact16":
            value = number("h")
            ref = {"signed16": value}
            if value == -2:
                value = number("i")
                if value < 0:
                    raise ValueError("Negative16EF9D8 escaped reference")
                ref["escaped_index"] = value
            elif value < -1:
                raise ValueError("Negative16EF9D8 compact reference")
            ref["stored_index"] = None if value == -1 else value
        else:
            ref = {
                "raw_unsigned_word": number(
                    "I" if reference_mode == "direct32" else "Q"
                )
            }
        ref.update(
            start=ref_start,
            end=at,
            raw_hex=bytes(data[ref_start:at]).hex(),
            identity_resolved=False,
        )
        field8_start = at
        field8 = number("I")
        fieldc = number("B")
        rows.append(
            {
                "ordinal": ordinal,
                "start": begin,
                "end": at,
                "marker_u16": marker,
                "reference": ref,
                "native_08_raw_u32": field8,
                "native_08_source_offset": field8_start,
                "native_0c_raw_u8": fieldc,
            }
        )
    return {
        "start": start,
        "end": at,
        "complete_child_wire": True,
        "count": count,
        "rows": rows,
        "reference_mode": reference_mode,
        "reference_native_reader": "0x1116fa4",
        "reference_native_writer": "0x111cc80",
        "descriptor_global": "0x56d2d18",
        "descriptor_table_offset": 0,
        "reference_namespace": "unresolved_descriptor_slot0",
        "runtime_globals_observed": False,
        "native_collection_limit_observed": False,
        "native_limit_condition": "count < [global56C1628] remains conditional",
    }
