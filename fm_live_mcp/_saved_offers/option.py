"""Fixed31B native1323F30 option row, paired1323D24; fields opaque."""

from .wire import Cursor

FIELDS = (
    (None, 2),
    (0, 4),
    (20, 4),
    (24, 4),
    (28, 2),
    (None, 1),
    (8, 4),
    (12, 4),
    (16, 1),
    (4, 4),
    (30, 1),
)


def parse(data, start, *, limit=None):
    c = Cursor(data, start, limit)
    fields = []
    for destination, width in FIELDS:
        begin = c.offset
        raw = c.take(width)
        fields.append(
            {
                "native_destination": hex(destination)
                if destination is not None
                else "discarded_marker",
                "start": begin,
                "end": c.offset,
                "raw_hex": raw.hex(),
            }
        )
    return {
        "start": start,
        "end": c.offset,
        "fields": fields,
        "complete_child_wire": True,
        "native_reader": "0x1323f30",
        "native_writer": "0x1323d24",
        "field_meanings": "unresolved",
    }
