"""One passive already-cached frame, reselected by its exact native tick."""

import math
import struct

from . import (
    active_match_entity_identity as identity,
    active_match_people,
    active_match_playback,
    players,
)

MAX_ENTITIES = 128


def _read(read, address, size):
    raw = read(address, size)
    if len(raw) != size:
        raise ValueError("Incomplete fixed-frame read")
    return raw


def _q(read, address):
    return players.u64(_read(read, address, 8))


def _pointer(value):
    return identity._pointer(value)


def verify_native(read, base):
    for rva, expected in identity.NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError("Native frame identity construction changed")
    for table, getter in ((0x56A07A0, 0x4AB20D0), (0x56A0750, 0x4AB1F94)):
        if _q(read, base + table + 0x10) != base + getter:
            raise ValueError("Native frame entity classification changed")


def _sample(point, local):
    if not all(math.isfinite(v) for v in (*point, local)):
        raise ValueError("Nonfinite fixed-frame sample")
    # Preserve native local parameters; the public projector selects exact1.0.
    return {"native_xy": list(point), "native_local_time": local}


def read_frame(read, base, bound, *, fixed_tick=None):
    """No game getter is called; absent exact cached tick is unavailable."""
    provider, playback = bound["frame_provider_address"], bound["playback_address"]
    cursor = bound["current_time_slice"]
    tick = cursor if fixed_tick is None else fixed_tick
    if type(tick) is not int or not 0 <= tick <= cursor:
        raise ValueError("Fixed frame is beyond the observed playback cursor")
    cache = _q(read, provider + 0x220)
    if not cache:
        return {"state": "unavailable_frame_cache"}
    _pointer(cache)
    matches = []
    for slot in range(6):
        header = _read(read, cache + slot * 0x420, 0x40)
        if struct.unpack_from("<I", header, 0x38)[0] == tick:
            matches.append(cache + slot * 0x420)
    if len(matches) != 1:
        return {"state": "unavailable_unique_exact_cursor_frame"}
    frame = _read(read, matches[0], 0x420)
    if struct.unpack_from("<I", frame, 0x38)[0] != tick:
        raise ValueError("Selected frame tick changed during read")
    count = struct.unpack_from("<b", frame, 0x26)[0]
    if not 0 <= count < MAX_ENTITIES:
        raise ValueError("Unsupported fixed-frame entity count")
    pointers = (
        struct.unpack(
            f"<{count}Q", _read(read, _pointer(players.u64(frame)), count * 8)
        )
        if count
        else ()
    )
    entities = []
    checked_types = set()
    for index, address in enumerate(pointers):
        _pointer(address)
        header = _read(read, address, 0x20)
        table = players.u64(header) - base
        if table not in (0x56A07A0, 0x56A0750):
            raise ValueError("Unclassified fixed-frame entity runtime type")
        if table not in checked_types:
            active_match_people._type(
                read,
                base,
                address,
                table,
                b"N7simatch17FRAME_PLAYER_DATAE"
                if table == 0x56A07A0
                else b"N7simatch17FRAME_PERSON_DATAE",
            )
            checked_types.add(table)
        samples_count = struct.unpack_from("<i", header, 0x10)[0]
        # The typed native base has two inline32-byte samples before flags+6c.
        if not 0 <= samples_count <= 2:
            raise ValueError("Unsupported fixed-frame entity sample count")
        samples_raw = (
            _read(read, address + 0x20, samples_count * 32) if samples_count else b""
        )
        samples = [
            _sample(
                struct.unpack_from("<ff", samples_raw, j * 32),
                struct.unpack_from("<f", samples_raw, j * 32 + 16)[0],
            )
            for j in range(samples_count)
        ]
        entities.append(
            {
                "entity_index": index,
                "kind": "player" if table == 0x56A07A0 else "non_player",
                "playback_uid": struct.unpack_from("<I", header, 8)[0],
                "position_samples": samples,
                "required_sample_bytes": [
                    samples_raw[j * 32 : j * 32 + 8].hex()
                    + samples_raw[j * 32 + 16 : j * 32 + 20].hex()
                    for j in range(samples_count)
                ],
            }
        )
    ball_count = frame[0x100]
    if ball_count > 10:
        raise ValueError("Unsupported fixed-frame ball sample count")
    ball = []
    ball_bytes = []
    for j in range(ball_count):
        xyz = struct.unpack_from("<fff", frame, 0x120 + j * 64)
        local = struct.unpack_from("<f", frame, 0x140 + j * 64)[0]
        if not all(math.isfinite(v) for v in (*xyz, local)):
            raise ValueError("Nonfinite ball frame sample")
        ball.append({"native_xyz": list(xyz), "native_local_time": local})
        ball_bytes.append(
            frame[0x120 + j * 64 : 0x12C + j * 64].hex()
            + frame[0x140 + j * 64 : 0x144 + j * 64].hex()
        )
    first, last, capacity = struct.unpack("<QQQ", _read(read, playback + 0x1DA8, 24))
    if (first, last, capacity) == (0, 0, 0):
        return {"state": "unavailable_entity_setup"}
    _pointer(first)
    if (
        not first <= last <= capacity
        or (last - first) % 0x160
        or (capacity - first) % 0x160
        or (capacity - first) // 0x160 > MAX_ENTITIES
    ):
        raise ValueError("Unsupported fixed-frame entity setup")
    setup_raw = identity._bytes(read, first, last - first)
    setup = [
        {
            "entity_index": j,
            "kind_raw": setup_raw[j * 0x160],
            "team_index": struct.unpack_from("<b", setup_raw, j * 0x160 + 0x3A)[0],
            "playback_uid": struct.unpack_from("<I", setup_raw, j * 0x160 + 0x3C)[0],
        }
        for j in range(len(setup_raw) // 0x160)
    ]
    bases = struct.unpack("<bb", _read(read, playback + 0x43, 2))
    return {
        "state": "available",
        "frame_tick": tick,
        "entities": entities,
        "setup": setup,
        "player_bases": list(bases),
        "ball_samples": ball,
        "required_ball_bytes": ball_bytes,
    }


def _signature(source):
    return {
        key: source[key]
        for key in (
            "frame_tick",
            "entities",
            "setup",
            "player_bases",
            "ball_samples",
            "required_ball_bytes",
        )
    }


def verify_frame(read, base, client, bound, source):
    current = active_match_playback.capture(read, base, client=client)
    if current["state"] != "bound_playback_cursor":
        raise ValueError("Fixed-frame playback owner is unavailable")
    after = current["bound_playback"]
    fields = (
        "playback_address",
        "frame_provider_address",
        "source_match_address",
        "local_playback_handle",
        "official_match_unique_id",
    )
    if (
        any(after[k] != bound[k] for k in fields)
        or after["current_time_slice"] < bound["current_time_slice"]
    ):
        raise ValueError("Fixed-frame source relinked or playback moved backwards")
    selected = read_frame(read, base, after, fixed_tick=source["frame_tick"])
    if selected["state"] != "available":
        raise ValueError("Fixed frame evicted or no longer unique")
    if _signature(selected) != _signature(source):
        raise ValueError("Consumed fixed-frame bytes or identities changed")
    return {
        "state": "verified_exact_fixed_frame_under_monotonic_same_match_playback",
        "frame_tick": source["frame_tick"],
        "observed_cursor": bound["current_time_slice"],
        "verification_cursor": after["current_time_slice"],
    }
