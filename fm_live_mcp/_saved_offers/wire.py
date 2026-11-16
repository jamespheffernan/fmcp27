"""Bounded BASE_TRANSFER_MANAGER prefix/common row under explicit wire profile."""

PROFILE = "person_index32_team_marker_index32"
BEFORE_TEAM50 = (
    (88, 4),
    (92, 4),
    (96, 4),
    (141, 1),
    (100, 4),
    (132, 1),
    (133, 1),
    (48, 8),
    (134, 1),
    (135, 1),
    (139, 1),
    (104, 4),
    (108, 4),
    (136, 1),
    (120, 4),
    (124, 4),
    (128, 4),
)
AFTER_TEAM50 = (
    (142, 1),
    (137, 1),
    (116, 4),
    (140, 1),
    (112, 4),
    (16, 8),
    (24, 8),
    (32, 8),
    (40, 8),
    (138, 1),
)


class Cursor:
    def __init__(self, data, start=0, limit=None):
        self.data = data
        self.offset = start
        self.limit = len(data) if limit is None else limit
        if (
            type(start) is not int
            or type(self.limit) is not int
            or (not 0 <= start <= self.limit <= len(data))
        ):
            raise ValueError("Invalid transfer source bounds")

    def take(self, width):
        if type(width) is not int or width < 0:
            raise ValueError("Invalid transfer read width")
        if width > self.limit - self.offset:
            raise ValueError(f"Truncated transfer row at {self.offset}, need {width}")
        start = self.offset
        self.offset += width
        return bytes(self.data[start : self.offset])

    def number(self, width, signed=False):
        return int.from_bytes(self.take(width), "little", signed=signed)


def manager_prefix(data, *, limit=None, max_rows=1000000):
    c = Cursor(data, 0, limit)
    if c.take(6) != b"\x03\x01tad.":
        raise ValueError("Unsupported transfer archive header")
    version = c.number(2)
    if version != 35:
        raise ValueError("Unsupported transfer manager file version")
    raw_state = c.number(1)
    count = c.number(4)
    if count > max_rows:
        raise ValueError("Transfer vector work budget exceeded")
    return {
        "version": version,
        "native_50_u8": raw_state,
        "first_vector_count": count,
        "first_type_offset": c.offset,
        "state": "prefix_only",
        "native_reader": "0x1828f18",
    }


def parse_common(data, start, *, limit=None, profile=PROFILE):
    if profile != PROFILE:
        raise ValueError("Unsupported explicit transfer reference profile")
    c = Cursor(data, start, limit)
    version = c.number(2)
    if version != 20:
        raise ValueError(f"Unsupported transfer common serializer {version} at {start}")
    person_start = c.offset
    person = c.number(4, True)
    if person < -1:
        raise ValueError("Negative PERSON index outside original/null subset")
    refs = [
        {
            "native_destination": "0x38",
            "namespace": "PERSON",
            "start": person_start,
            "end": c.offset,
            "database_index": None if person == -1 else person,
        }
    ]

    def team(destination):
        begin = c.offset
        marker = c.number(1)
        if marker not in (0, 1):
            raise ValueError(f"Unsupported inline TEAM marker {marker} at {begin}")
        index = c.number(4, True)
        if index < -1:
            raise ValueError("Negative TEAM index outside original/null subset")
        identity = c.take(4).hex() if marker == 1 and index != -1 else None
        refs.append(
            {
                "native_destination": hex(destination),
                "namespace": "TEAM_BASE",
                "start": begin,
                "end": c.offset,
                "marker": marker,
                "database_index": None if index == -1 else index,
                "identity_words_raw_hex": identity,
            }
        )

    fields = []

    def scalar(destination, width):
        begin = c.offset
        wire = c.take(width)
        fields.append(
            {
                "native_destination": hex(destination),
                "start": begin,
                "end": c.offset,
                "raw_hex": wire.hex(),
            }
        )

    team(64)
    team(72)
    for dest, width in BEFORE_TEAM50:
        scalar(dest, width)
    team(80)
    for dest, width in AFTER_TEAM50:
        scalar(dest, width)
    return {
        "start": start,
        "end": c.offset,
        "version": version,
        "references": refs,
        "fields": fields,
        "reference_profile": profile,
        "runtime_native_globals_proved": False,
        "next_reader": "virtual+0x28",
        "state": "common_prefix_only",
        "field_meanings": "unresolved",
    }


class UnsupportedOffer(ValueError):
    def __init__(self, native, offset, partial=None):
        self.native = hex(native) if isinstance(native, int) else native
        self.offset = offset
        self.partial = partial or {}
        super().__init__(f"Unsupported saved offer child {self.native} at {offset}")
