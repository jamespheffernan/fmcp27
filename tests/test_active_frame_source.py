import struct

import pytest

from fm_live_mcp import active_frame_source as frame


class Memory:
    def __init__(self):
        self.bytes = {}

    def put(self, address, raw):
        self.bytes.update({address + i: v for i, v in enumerate(raw)})

    def q(self, address, value):
        self.put(address, struct.pack("<Q", value))

    def read(self, address, size):
        return bytes(self.bytes.get(address + i, 0) for i in range(size))


def source():
    m = Memory()
    base = 0x10000000
    playback = 0x30000
    provider = 0x40000
    cache = 0x60000
    for table, getter, name, info in (
        (0x56A07A0, 0x4AB20D0, b"N7simatch17FRAME_PLAYER_DATAE", 0xB0000),
        (0x56A0750, 0x4AB1F94, b"N7simatch17FRAME_PERSON_DATAE", 0xB1000),
    ):
        m.put(base + table - 16, struct.pack("<qQ", 0, info))
        m.q(info + 8, info + 32)
        m.put(info + 32, name + b"\0")
        m.q(base + table + 0x10, base + getter)
    for rva, data in frame.identity.NATIVE_SPANS:
        m.put(base + rva, data)
    m.q(provider + 0x220, cache)
    raw = bytearray(0x420)
    struct.pack_into("<Q", raw, 0, 0x62000)
    raw[0x26] = 3
    struct.pack_into("<I", raw, 0x38, 100)
    raw[0x100] = 2
    for j, local in enumerate((0.0, 1.0)):
        struct.pack_into("<fff", raw, 0x120 + j * 64, 1 + j, 2 + j, 0.5)
        struct.pack_into("<f", raw, 0x140 + j * 64, local)
    m.put(cache, raw)
    for index in range(3):
        address = 0x70000 + index * 0x100
        m.q(0x62000 + index * 8, address)
        m.q(address, base + (0x56A0750 if index == 0 else 0x56A07A0))
        m.put(address + 8, struct.pack("<I", 1000 + index))
        m.put(address + 0x10, struct.pack("<i", 1))
        sample = bytearray(32)
        struct.pack_into("<ff", sample, 0, 3.0 + index, 4.0 + index)
        struct.pack_into("<f", sample, 16, 1.0)
        m.put(address + 0x20, sample)
    setup = bytearray(3 * 0x160)
    for index in range(3):
        setup[index * 0x160] = 1 if index == 0 else 0
        setup[index * 0x160 + 0x3A] = 1 if index == 2 else 0
        struct.pack_into("<I", setup, index * 0x160 + 0x3C, 1000 + index)
    m.put(0x80000, setup)
    m.put(
        playback + 0x1DA8,
        struct.pack("<QQQ", 0x80000, 0x80000 + len(setup), 0x80000 + len(setup)),
    )
    m.put(playback + 0x43, struct.pack("<bb", 1, 2))
    bound = dict(
        playback_address=playback,
        frame_provider_address=provider,
        source_match_address=0x50000,
        local_playback_handle=3,
        official_match_unique_id=99,
        current_time_slice=100,
        buffered_max_time_slice=102,
    )
    return m, base, bound


def test_exact_cached_frame_and_native_samples():
    m, base, bound = source()
    frame.verify_native(m.read, base)
    r = frame.read_frame(m.read, base, bound)
    assert r["state"] == "available" and r["frame_tick"] == 100
    assert [e["kind"] for e in r["entities"]] == ["non_player", "player", "player"]
    assert r["entities"][1]["position_samples"] == [
        {"native_xy": [4.0, 5.0], "native_local_time": 1.0}
    ]
    assert r["ball_samples"][-1] == {
        "native_xyz": [2.0, 3.0, 0.5],
        "native_local_time": 1.0,
    }
    assert r["setup"][2]["team_index"] == 1


def test_moving_cursor_and_cache_relocation_preserve_same_frame(monkeypatch):
    m, base, bound = source()
    before = frame.read_frame(m.read, base, bound)
    m.put(0x65000, m.read(0x60000, 0x420))
    m.q(0x40220, 0x65000)
    after = {**bound, "current_time_slice": 101}
    monkeypatch.setattr(
        frame.active_match_playback,
        "capture",
        lambda *a, **k: {"state": "bound_playback_cursor", "bound_playback": after},
    )
    assert (
        frame.verify_frame(m.read, base, 1, bound, before)["verification_cursor"] == 101
    )


@pytest.mark.parametrize(
    "address,raw",
    [
        (0x70120, struct.pack("<f", 4.25)),
        (0x70108, struct.pack("<I", 999)),
        (0x80000 + 0x160 + 0x3A, b"\x01"),
    ],
)
def test_changed_consumed_coordinate_uid_or_setup_rejects(monkeypatch, address, raw):
    m, base, bound = source()
    before = frame.read_frame(m.read, base, bound)
    m.put(address, raw)
    monkeypatch.setattr(
        frame.active_match_playback,
        "capture",
        lambda *a, **k: {"state": "bound_playback_cursor", "bound_playback": bound},
    )
    with pytest.raises(ValueError, match="bytes or identities changed"):
        frame.verify_frame(m.read, base, 1, bound, before)


def test_unconsumed_appearance_change_is_not_a_false_coordinate_failure(monkeypatch):
    m, base, bound = source()
    before = frame.read_frame(m.read, base, bound)
    m.put(0x80000 + 0x18, b"\x05")
    monkeypatch.setattr(
        frame.active_match_playback,
        "capture",
        lambda *a, **k: {"state": "bound_playback_cursor", "bound_playback": bound},
    )
    assert frame.verify_frame(m.read, base, 1, bound, before)["frame_tick"] == 100


def test_evicted_frame_never_uses_nearest_cached_frame(monkeypatch):
    m, base, bound = source()
    before = frame.read_frame(m.read, base, bound)
    m.put(0x60038, struct.pack("<I", 101))
    monkeypatch.setattr(
        frame.active_match_playback,
        "capture",
        lambda *a, **k: {
            "state": "bound_playback_cursor",
            "bound_playback": {**bound, "current_time_slice": 101},
        },
    )
    with pytest.raises(ValueError, match="evicted"):
        frame.verify_frame(m.read, base, 1, bound, before)


@pytest.mark.parametrize(
    "field,value",
    [
        ("current_time_slice", 99),
        ("source_match_address", 0x51000),
        ("official_match_unique_id", 100),
    ],
)
def test_backward_seek_or_owner_change_rejects(monkeypatch, field, value):
    m, base, bound = source()
    before = frame.read_frame(m.read, base, bound)
    monkeypatch.setattr(
        frame.active_match_playback,
        "capture",
        lambda *a, **k: {
            "state": "bound_playback_cursor",
            "bound_playback": {**bound, field: value},
        },
    )
    with pytest.raises(ValueError, match="relinked or playback"):
        frame.verify_frame(m.read, base, 1, bound, before)


def test_future_frame_requested_is_rejected():
    m, base, bound = source()
    with pytest.raises(ValueError, match="beyond"):
        frame.read_frame(m.read, base, bound, fixed_tick=101)


@pytest.mark.parametrize(
    "address,raw",
    [
        (0x70110, struct.pack("<i", 3)),
        (0x60100, b"\x0b"),
        (0x70120, struct.pack("<f", float("nan"))),
    ],
)
def test_malformed_samples_fail_closed(address, raw):
    m, base, bound = source()
    m.put(address, raw)
    with pytest.raises(ValueError):
        frame.read_frame(m.read, base, bound)
