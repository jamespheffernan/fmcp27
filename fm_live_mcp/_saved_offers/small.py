"""Paired TRIAL_OFFER and B_CLUB_MOVE_OFFER leafs, raw fields only."""

from .wire import Cursor, PROFILE


def parse(data, start, *, kind, version=20, limit=None, reference_profile=None):
    if version != 20 or reference_profile != PROFILE:
        raise ValueError("Explicit current offer source context required")
    if kind not in (4, 7, 10):
        raise ValueError("Unsupported small transfer offer kind")
    c = Cursor(data, start, limit)
    raw = c.number(1)
    layouts = {
        4: ("TRIAL_OFFER", "0x1874f50", "0x1874ef0"),
        7: ("ENQUIRY_OFFER", "0x18319b4", "0x1831954"),
        10: ("B_CLUB_MOVE_OFFER", "0x181ebc0", "0x181eb2c"),
    }
    name, reader, writer = layouts[kind]
    out = {
        "start": start,
        "raw_native_8f_u8": raw,
        "source_record_kind": name,
        "native_reader": reader,
        "native_writer": writer,
        "offer_accepted_or_payable_proved": False,
    }
    if kind == 10:
        begin = c.offset
        marker = c.number(1)
        if marker not in (0, 1):
            raise ValueError(f"Unproved inline TEAM at {begin}")
        index = c.number(4, True)
        if index < -1:
            raise ValueError("Negative TEAM original index outside checked subset")
        identity = c.take(4).hex() if marker == 1 and index != -1 else None
        out["native_90_TEAM"] = {
            "start": begin,
            "end": c.offset,
            "marker": marker,
            "database_index": None if index == -1 else index,
            "identity_words_raw_hex": identity,
            "namespace": "TEAM_BASE",
        }
    out["end"] = c.offset
    return out
