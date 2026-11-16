"""Synthetic malformed/stale records, independent of the live UI oracle."""
import struct

import pytest

from fm_live_mcp import players
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge

TABLES = (0x11100, 0x22200, 0x33300)


@pytest.fixture
def memory():
    data = bytearray(0x5000)
    for off, value in zip((0, 0x140, 0x388), TABLES):
        struct.pack_into("<Q", data, 0x1000 + off, value)
    struct.pack_into("<II", data, 0x1394, 12345, 12345)
    struct.pack_into("<HH", data, 0x12D0, 60, 2000)
    for offset, handle, pointer, name in ((0x298, 0x2000, 0x3000, b"Test"),
                                          (0x2A0, 0x2100, 0x3100, "Müller".encode())):
        struct.pack_into("<Q", data, 0x1000 + offset, handle)
        struct.pack_into("<Q", data, handle, pointer)
        struct.pack_into("<I", data, pointer, len(name))
        data[pointer + 4:pointer + 4 + len(name)] = name
    data[0x1148:0x118D] = bytes([50] * 69)
    data[0x1270] = 0x80  # Native fifths-scale flag.
    data[0x1157] = 43  # crossing 8.6 -> 9
    data[0x1158] = 82  # dribbling 16.4 -> 16
    return data


def reader(memory):
    def read(address, size):
        if address <= 0 or address + size > len(memory):
            raise BridgeError("Unreadable pointer")
        return bytes(memory[address:address + size])
    return read


def test_decode_named_fields_rounding_and_leap_day(memory):
    result, identity = players.decode(reader(memory), 0x1000, TABLES)
    assert result["name"] == "Test Müller"
    assert result["birth_date"] == "2000-02-29"
    assert len(result["attributes"]) == 36
    assert result["attributes"]["crossing"] == 9
    assert result["attributes"]["dribbling"] == 16
    assert result["attributes"]["concentration"] == 10
    assert identity == (12345, "Test", "Müller", "2000-02-29", 12345)
    assert "potential_ability" not in result


@pytest.mark.parametrize('missing,expected', [(0x298, 'Müller'), (0x2A0, 'Test')])
def test_single_name_component_has_no_invented_text(memory, missing, expected):
    struct.pack_into('<Q', memory, 0x1000 + missing, 0)
    result, _ = players.decode(reader(memory), 0x1000, TABLES)
    assert result['name'] == result['display_name'] == expected


def test_nameless_player_fails_unless_common_name_exists(memory):
    struct.pack_into('<QQ', memory, 0x1298, 0, 0)
    with pytest.raises(ValueError, match='no readable name'):
        players.decode(reader(memory), 0x1000, TABLES)
    struct.pack_into('<Q', memory, 0x12A8, 0x2000)
    assert players.decode(reader(memory), 0x1000, TABLES)[0]['name'] == 'Test'


@pytest.mark.parametrize("address,value", [
    (0x1000, b"\0" * 8), (0x1394, b"\0" * 4), (0x1390, b"\xff" * 4),
    (0x12D0, struct.pack("<HH", 366, 2001)),
    (0x3000, struct.pack("<I", 129)), (0x3004, b"\xff"),
    (0x3008, b"x"), (0x1157, b"\xff"),
])
def test_rejects_malformed_records(memory, address, value):
    memory[address:address + len(value)] = value
    with pytest.raises(ValueError):
        players.decode(reader(memory), 0x1000, TABLES)


def test_rejects_record_changed_during_read(memory):
    original = reader(memory)
    reads = 0
    def changing(address, size):
        nonlocal reads
        if address == 0x1000 and size == players.SIZE:
            reads += 1
            if reads == 2:
                memory[0x1157] += 1
        return original(address, size)
    with pytest.raises(ValueError, match="changed during read"):
        players.decode(changing, 0x1000, TABLES)


def test_macho_uuid_and_bad_architecture():
    header = struct.pack("<8I", 0xFEEDFACF, 0x100000C, 0, 6, 1, 24, 0, 0)
    image = header + struct.pack("<II", 0x1B, 24) + b"1234567890abcdef"
    assert players.macho_uuid(image) == b"1234567890abcdef"
    with pytest.raises(ValueError):
        players.macho_uuid(b"\0" * 56)
    with pytest.raises(ValueError):
        players.macho_uuid(image[:-1])


def test_unsupported_build_rejected_before_native_reads(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "_run", lambda *a: pytest.fail("Native read for unsupported version"))
    with pytest.raises(BridgeError, match="Unsupported player layout"):
        bridge.find_players(bridge.session, "Wirtz")


def test_player_search_readback_stale_identity_and_cursor_isolation(bridge, monkeypatch, memory):
    monkeypatch.setattr(bridge, "_player_layout", lambda p: TABLES)
    monkeypatch.setattr(bridge, "_read_memory", lambda p, a, n: reader(memory)(a, n))
    calls = []
    def scan(*args):
        calls.append(args)
        return {"matches": [{"address": "0x1000"}], "stop_reason": "byte_budget", "next_address": "0x4000"}
    monkeypatch.setattr(bridge, "_run", scan)
    result = bridge.find_players(bridge.session, "Test")
    assert "--writable-only" in calls[0] and "--private-only" not in calls[0]
    ref = result["players"][0]["player_ref"]
    assert bridge.get_player(bridge.session, ref)["player"]["name"] == "Test Müller"
    with pytest.raises(BridgeError, match="different search"):
        bridge.find_players(bridge.session, "Other", cursor=result["next_cursor"])
    with pytest.raises(BridgeError, match="Cursor is invalid"):
        bridge.search(bridge.session, ["Test"], cursor=result["next_cursor"])
    # Same allocated address with a different identity must not retarget a handle.
    struct.pack_into("<II", memory, 0x1394, 987, 987)
    with pytest.raises(BridgeError, match="identity changed"):
        bridge.get_player(bridge.session, ref)
    assert ref not in bridge.player_refs
    bridge.detach()
    assert not bridge.player_cursors and not bridge.player_refs


def test_rejected_candidates_are_visible(bridge, monkeypatch, memory):
    monkeypatch.setattr(bridge, "_player_layout", lambda p: TABLES)
    monkeypatch.setattr(bridge, "_read_memory", lambda p, a, n: reader(memory)(a, n))
    monkeypatch.setattr(bridge, "_run", lambda *a: {
        "matches": [{"address": "0x1000"}], "stop_reason": "address_space_end"})
    memory[0x1000] = 0
    memory[0x1001] = 0
    result = bridge.find_players(bridge.session, "Test")
    assert result["players"] == [] and result["rejected_candidates"] == 1
    assert result["absence_proven"] is False


def test_loaded_uuid_mismatch_fails_before_rtti():
    header = struct.pack("<8I", 0xFEEDFACF, 0x100000C, 0, 6, 1, 24, 0, 0)
    image = header + struct.pack("<II", 0x1B, 24) + b"1234567890abcdef"
    with pytest.raises(ValueError, match="UUID differs"):
        players.verify_runtime(lambda a, n: image, 0x1000, b"different-uuid123")


def test_fingerprint_mismatch(tmp_path):
    path = tmp_path / "plugin"
    path.write_bytes(b"unsupported build")
    with pytest.raises(ValueError, match="fingerprint"):
        players.disk_uuid(path)


def test_process_loss_during_player_decode_fails_whole_search(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "_player_layout", lambda p: TABLES)
    monkeypatch.setattr(bridge, "_run", lambda *a: {
        "matches": [{"address": "0x1000"}], "stop_reason": "address_space_end"})
    def lost(*args):
        bridge._clear()
        raise BridgeError("Process changed")
    monkeypatch.setattr(bridge, "_decode_player", lost)
    with pytest.raises(BridgeError, match="Unknown session"):
        bridge.find_players(bridge.session, "Test")


@pytest.mark.parametrize("kwargs", [{"name": "ab"}, {"name": "bad\ud800"},
                                   {"name": "bad\x7f"}, {"max_mib": 1025}, {"max_matches": True}])
def test_player_input_bounds_before_layout_reads(bridge, monkeypatch, kwargs):
    monkeypatch.setattr(bridge, "_player_layout", lambda p: pytest.fail("Layout read before validation"))
    with pytest.raises(BridgeError):
        bridge.find_players(bridge.session, **{"name": "Test", **kwargs})


def test_common_name_display_and_recheck(memory):
    struct.pack_into('<Q', memory, 0x12A8, 0x2200)
    struct.pack_into('<Q', memory, 0x2200, 0x3200)
    struct.pack_into('<I', memory, 0x3200, 4)
    memory[0x3204:0x3209] = b'Beto\0'
    result, _ = players.decode(reader(memory), 0x1000, TABLES)
    assert result['name'] == 'Test Müller'
    assert result['display_name'] == 'Beto'
    original = reader(memory)
    reads = 0
    def changing(a, n):
        nonlocal reads
        if a == 0x3204:
            reads += 1
            if reads == 2: memory[0x3204] = ord('N')
        return original(a, n)
    with pytest.raises(ValueError, match='common name changed'):
        players.decode(changing, 0x1000, TABLES)
