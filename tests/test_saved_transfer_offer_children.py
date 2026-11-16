import struct

import pytest

from fm_live_mcp._saved_offers import option, reference_collection, trade, trade_clause
from fm_live_mcp._saved_offers.wire import PROFILE, UnsupportedOffer


def test_reference_collection_positive_escape_namespace_and_all_truncations():
    for index, encoded in (
        (56, struct.pack("<h", 56)),
        (65536, struct.pack("<hi", -2, 65536)),
    ):
        data = struct.pack("<IH", 1, 1) + encoded + struct.pack("<IB", 1234, 255)
        result = reference_collection.parse(data, 0, reference_mode="compact16")
        assert result["end"] == len(data)
        assert result["rows"][0]["reference"]["stored_index"] == index
        assert result["reference_namespace"] == "unresolved_descriptor_slot0"
        assert result["runtime_globals_observed"] is False
        for end in range(len(data)):
            with pytest.raises(ValueError):
                reference_collection.parse(data, 0, limit=end)
        with pytest.raises(ValueError, match="work/input"):
            reference_collection.parse(data, 0, max_rows=0)
    with pytest.raises(ValueError):
        reference_collection.parse(struct.pack("<IHhIB", 1, 0, 56, 1234, 255), 0)


def test_fixed_option31_version_is_opaque():
    for marker in (0, 1, 65535):
        data = struct.pack("<H", marker) + bytes(range(29))
        assert option.parse(data, 0)["end"] == 31
        for end in range(31):
            with pytest.raises(ValueError):
                option.parse(data, 0, limit=end)


def test_actual_trade_clause_and_full_wrapper_boundaries():
    clause = bytes.fromhex("011e00000164009c5b000001e907")
    decoded = trade_clause.parse(clause, 0)
    assert decoded["end"] == 14
    assert decoded["team08"]["stored_index"] == 23452
    assert decoded["native_property_special_cases"]["pick_100"] is True
    # Native1857024 owns its discarded marker and two trailing byte fields.
    body = b"\x00\x00\x01\x01" + clause + b"\x00" * 19
    result = trade.parse(
        body,
        0,
        version=20,
        reference_profile=PROFILE,
        child_readers={0x11DD52C: trade_clause.parse},
    )
    assert result["end"] == 37
    assert result["vectors"][2]["rows"][0]["end"] == 20
    assert result["vectors"][2]["rows"][0]["value"]["end"] == 18
    for end in range(37):
        with pytest.raises(ValueError):
            trade.parse(
                body,
                0,
                version=20,
                reference_profile=PROFILE,
                child_readers={0x11DD52C: trade_clause.parse},
                limit=end,
            )
    with pytest.raises(UnsupportedOffer) as error:
        trade.parse(body, 0, version=20, reference_profile=PROFILE)
    assert error.value.native == "0x11dd52c" and error.value.offset == 4


def test_positive_mls_child_stops_before_unproved_payload():
    body = b"\x00\x00\x00\x01\x01" + bytes(64)
    with pytest.raises(UnsupportedOffer) as error:
        trade.parse(body, 0, version=20, reference_profile=PROFILE)
    assert error.value.native == "0x1802494" and error.value.offset == 5
