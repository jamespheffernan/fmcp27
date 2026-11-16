"""TRADE_OFFER paired1853840/1852C94, preserving explicit child boundaries."""

from .wire import Cursor, PROFILE, UnsupportedOffer as Unsupported


def parse(
    data, start, *, limit=None, version=20, reference_profile=None, child_readers=None
):
    if version != 20 or reference_profile != PROFILE:
        raise ValueError("Explicit current TRADE_OFFER context required")
    c = Cursor(data, start, limit)
    children = child_readers or {}
    vectors = []

    def child(native):
        callback = children.get(native)
        if callback is None:
            raise Unsupported(native, c.offset, {"vectors": vectors})
        row = callback(data, c.offset, limit=c.limit)
        if (
            not isinstance(row, dict)
            or type(row.get("end")) is not int
            or (not c.offset <= row["end"] <= c.limit)
        ):
            raise ValueError("Invalid TRADE child boundary")
        c.offset = row["end"]
        return row

    for destination, kind in (
        (144, "person"),
        (168, "person"),
        (192, "clause"),
        (216, "mls"),
        (240, "person"),
        (264, "person"),
        (288, "clause"),
        (312, "mls"),
    ):
        count_offset = c.offset
        count = c.number(1)
        rows = []
        vector = {
            "native_destination": hex(destination),
            "count_offset": count_offset,
            "count": count,
            "rows": rows,
        }
        vectors.append(vector)
        for ordinal in range(count):
            begin = c.offset
            marker = c.number(1)
            if kind == "person":
                index = c.number(4, True)
                if index < -1 or (index == -1 and destination in (144, 168)):
                    raise ValueError(
                        "Trade PERSON reference outside checked native subset"
                    )
                value = {
                    "namespace": "PERSON",
                    "database_index": None if index == -1 else index,
                }
            elif kind == "clause":
                value = child(18732332)
            else:
                value = child(25175188)
            first = c.number(1)
            second = c.number(1)
            rows.append(
                {
                    "ordinal": ordinal,
                    "start": begin,
                    "end": c.offset,
                    "marker_raw_u8": marker,
                    "value": value,
                    "native_extra_u8": [first, second],
                }
            )
        vector["end"] = c.offset
    fields = []
    for destination, width in (
        (360, 4),
        (364, 1),
        (365, 1),
        (366, 1),
        (367, 1),
        (368, 4),
    ):
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
    return {
        "start": start,
        "end": c.offset,
        "vectors": vectors,
        "fields": fields,
        "source_record_kind": "TRADE_OFFER",
        "native_reader": "0x185383c→0x1853840",
        "native_writer": "0x1852c90→0x1852c94",
        "runtime_native_globals_proved": False,
        "offer_accepted_or_payable_proved": False,
    }
