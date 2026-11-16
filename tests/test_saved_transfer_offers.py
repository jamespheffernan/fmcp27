import hashlib
import io
import json
import os
import struct
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from fm_live_mcp import saved_transfer_offers as offers
from fm_live_mcp._saved_offers import wire


def common(person=11, teams=(545, 500, 545), state=20, first=0, second=-1):
    # Independent fixed native field offsets under the marker0 source profile.
    data = bytearray(116)
    struct.pack_into("<Hi", data, 0, 20, person)
    for at, index in zip((6, 11, 67), teams, strict=True):
        data[at] = 0
        struct.pack_into("<i", data, at + 1, index)
    struct.pack_into("<iii", data, 16, 100, first, 1234)
    data[28] = state
    struct.pack_into("<i", data, 29, second)
    return bytes(data)


def small(kind=7, *, person=11, teams=(545, 500, 545), first=0, second=-1):
    child = b"\x00" + (b"\x00" + struct.pack("<i", 545) if kind == 10 else b"")
    return bytes([kind]) + common(person, teams, first=first, second=second) + child


def component(first=(), second=(), *, tail=b"\x00" * 4):
    return (
        b"\x03\x01tad."
        + struct.pack("<HBI", 35, 0, len(first))
        + b"".join(first)
        + struct.pack("<I", len(second))
        + b"".join(second)
        + tail
    )


def sample():
    return component(
        (small(), b"\x00"),
        (
            small(4, person=11, teams=(500, 500, 500), second=0),
            small(10, person=13, second=1),
        ),
    )


def test_scope_paging_and_null_slots():
    data = sample()
    page = offers.scan_buffer(data, person_index=11, limit=1)
    assert page["matched_count"] == 2
    assert page["next_offset"] == 1
    assert page["rows"][0]["source_class"] == "ENQUIRY_OFFER"
    last = offers.scan_buffer(data, person_index=11, offset=1, limit=1)
    assert last["rows"][0]["source_class"] == "TRIAL_OFFER"
    assert last["next_offset"] is None
    assert offers.scan_buffer(data, person_index=11, offset=1, limit=1) == last
    assert page["coverage"]["decoded_slots"] == 4
    assert page["coverage"]["offer_objects"] == 3
    assert page["coverage"]["null_slots"] == 1
    assert page["coverage"]["complete_requested_scope"] is True
    assert page["coverage"]["whole_manager_decoded"] is False
    assert page["coverage"]["full_save_absence_proved"] is False
    assert page["runtime_native_globals_proved"] is False
    assert page["accepted_or_scheduled_commitments_proved"] is False
    assert (
        offers.scan_buffer(data, person_index=11, team_index=545)["matched_count"] == 1
    )
    assert offers.scan_buffer(data, team_index=545)["matched_count"] == 2
    absent = offers.scan_buffer(data, person_index=99)
    assert absent["coverage"]["absence_proved_in_requested_scope"] is True
    assert absent["rows"] == []


def test_team_selector_is_explicit_common_fields():
    # An additional B_CLUB_MOVE TEAM is not one of the documented selectors.
    data = component((small(10, teams=(500, 500, 500)),))
    result = offers.scan_buffer(data, team_index=545)
    assert result["matched_count"] == 0
    assert (
        result["query"]["team_matching_scope"] == "common offer TEAM+0x40/+0x48/+0x50"
    )


def test_every_prefix_truncation_rejects():
    data = sample()
    for end in range(len(data)):
        with pytest.raises(ValueError):
            offers.scan_buffer(data[:end], person_index=11)


def test_unknown_later_sections_remain_unknown():
    source = component((small(),))
    result = offers.scan_buffer(source + b"opaque later manager bytes", person_index=11)
    assert result["matched_count"] == 1
    assert result["coverage"]["later_manager_sections"]["state"] == "not_decoded"
    bad = source[:-4] + struct.pack("<I", 5)
    with pytest.raises(ValueError, match="Following manager"):
        offers.scan_buffer(bad, person_index=11)


@pytest.mark.parametrize(
    "patch",
    [
        {"person_index": True},
        {"team_index": False},
        {"person_index": -1},
        {"person_index": 2**31},
        {"offset": True},
        {"limit": False},
        {"limit": 501},
    ],
)
def test_strict_requests(patch):
    arguments = {"person_index": 11, **patch}
    with pytest.raises(ValueError):
        offers.scan_buffer(sample(), **arguments)


def test_missing_selector_unknown_kind_versions_and_bounds(monkeypatch):
    with pytest.raises(ValueError):
        offers.scan_buffer(sample())
    with pytest.raises(ValueError, match="Unsupported saved offer child"):
        offers.scan_buffer(component((b"\x01" + common(),)), person_index=11)
    bad = bytearray(sample())
    struct.pack_into("<H", bad, 6, 34)
    with pytest.raises(ValueError):
        offers.scan_buffer(bad, person_index=11)
    bad = bytearray(sample())
    struct.pack_into("<H", bad, 14, 19)
    with pytest.raises(ValueError):
        offers.scan_buffer(bad, person_index=11)
    monkeypatch.setattr(offers, "MAX_COMPONENT_BYTES", 8)
    with pytest.raises(ValueError, match="byte budget"):
        offers.scan_buffer(sample(), person_index=11)
    with pytest.raises(ValueError):
        wire.Cursor(b"123").take(-1)


def test_team_marker1_reads_one_identity_word_and_null_reads_none():
    data = bytearray(common())
    data[6] = 1
    data[11:11] = struct.pack("<I", 9876)
    result = wire.parse_common(data, 0)
    assert result["end"] == 120
    assert result["references"][1]["identity_words_raw_hex"] == "94260000"
    assert result["references"][2]["database_index"] == 500
    assert result["references"][3]["database_index"] == 545
    null = bytearray(common())
    null[6] = 1
    struct.pack_into("<i", null, 7, -1)
    assert wire.parse_common(null, 0)["end"] == 116
    assert wire.parse_common(null, 0)["references"][1]["database_index"] is None


def test_loan_zero_negative_and_weekly_monthly_are_separate():
    # Current LOAN prefix:62B, compact COMP=-1, marker1,13B, signed options0,
    # zero reference vector, absent details, and nativeF0/F2 four bytes.
    child = bytearray(88)
    struct.pack_into("<i", child, 47, 0)
    struct.pack_into("<i", child, 53, 1800)
    struct.pack_into("<i", child, 57, -1)
    struct.pack_into("<h", child, 62, -1)
    child[64] = 1
    record = b"\x03" + common() + child
    result = offers.scan_buffer(component((record,)), person_index=11)
    terms = result["rows"][0]["stored_loan_terms"]
    assert terms["playing_weekly_wage"]["amount"] == 0
    assert terms["unused_weekly_wage"]["amount"] == 1800
    assert terms["unused_weekly_wage"]["period"] == "week"
    assert terms["unused_monthly_fee"]["amount"] is None
    assert terms["unused_monthly_fee"]["raw_signed32"] == -1
    assert terms["unused_monthly_fee"]["period"] == "month"
    assert all(term["currency"] is None for term in terms.values())


class BufferReader:
    def __init__(self, data, *, finished=True):
        self.data, self.offset, self.size = data, 0, len(data)
        self.source = SimpleNamespace(read=lambda n: b"", finished=finished)

    def take(self, amount):
        if amount > self.size - self.offset:
            raise ValueError("Truncated fake component")
        start = self.offset
        self.offset += amount
        return self.data[start : self.offset]


@pytest.fixture
def archive(monkeypatch):
    pin = "a" * 64
    data = sample()
    db = SimpleNamespace(
        path="root/game_db.dat", start=0, compressed_size=1, uncompressed_size=12
    )
    member = SimpleNamespace(
        path="root/transfer_man.dat",
        start=1,
        compressed_size=1,
        uncompressed_size=len(data),
    )
    state = SimpleNamespace(
        entries=[db, member],
        header=b"\x03\x01tad." + struct.pack("<HHH", 4000, 3754, 9),
        finished=True,
        changed=False,
    )

    @contextmanager
    def checked(*args, **kwargs):
        yield io.BytesIO(), state.entries, {}
        if state.changed:
            raise ValueError("Snapshot replaced during query")

    @contextmanager
    def opened(handle, entry):
        yield BufferReader(
            state.header if entry is db else data, finished=state.finished
        )

    monkeypatch.setattr(offers.snapshot_catalog, "checked_snapshot", checked)
    monkeypatch.setattr(offers.snapshot_catalog, "snapshot_id", lambda identity: pin)
    monkeypatch.setattr(
        offers.snapshot_catalog, "_metadata", lambda *args: {"status": "verified"}
    )
    monkeypatch.setattr(offers.saved_component_stream, "open_component", opened)
    monkeypatch.setattr(offers, "_packed_digest", lambda *args: "f" * 64)
    return state, pin, member


def test_snapshot_source_and_readonly_context(archive):
    state, pin, member = archive
    result = offers.find_offers("test.fm", expected_snapshot_id=pin, person_index=11)
    assert result["component"]["full_frame_validated"] is True
    assert result["component"]["raw_bytes"] == member.uncompressed_size
    assert result["snapshot_id"] == pin
    state.changed = True
    with pytest.raises(ValueError, match="replaced"):
        offers.find_offers("test.fm", expected_snapshot_id=pin, person_index=11)


def test_pin_path_scope_duplicate_members_source_and_frame_reject(archive):
    state, pin, member = archive
    with pytest.raises(ValueError, match="Snapshot identity"):
        offers.find_offers("test.fm", expected_snapshot_id="b" * 64, person_index=11)
    with pytest.raises(ValueError):
        offers.find_offers("../test.fm", expected_snapshot_id=pin, person_index=11)
    state.entries.append(member)
    with pytest.raises(ValueError, match="one root"):
        offers.find_offers("test.fm", expected_snapshot_id=pin, person_index=11)
    state.entries.pop()
    state.header = state.header[:8] + struct.pack("<HH", 3753, 9)
    with pytest.raises(ValueError, match="source profile"):
        offers.find_offers("test.fm", expected_snapshot_id=pin, person_index=11)
    state.header = b"\x03\x01tad." + struct.pack("<HHH", 4000, 3754, 9)
    state.finished = False
    with pytest.raises(ValueError, match="frame extent"):
        offers.find_offers("test.fm", expected_snapshot_id=pin, person_index=11)


def test_changed_packed_component_and_response_budget(archive, monkeypatch):
    state, pin, member = archive
    values = iter(("1" * 64, "2" * 64))
    monkeypatch.setattr(offers, "_packed_digest", lambda *args: next(values))
    with pytest.raises(ValueError, match="Packed transfer component changed"):
        offers.find_offers("test.fm", expected_snapshot_id=pin, person_index=11)
    monkeypatch.setattr(offers, "_packed_digest", lambda *args: "1" * 64)
    monkeypatch.setattr(offers, "MAX_RESPONSE_BYTES", 1)
    with pytest.raises(ValueError, match="response budget"):
        offers.find_offers("test.fm", expected_snapshot_id=pin, person_index=11)


ORACLE = os.environ.get("FM_SAVED_OFFER_ORACLE")


@pytest.mark.skipif(
    not ORACLE, reason="Optional independently pinned original offer corpus"
)
def test_original_four_components_against_independent_raw_oracle():
    oracle_path = Path(ORACLE)
    oracle = json.loads(oracle_path.read_text())
    for source in oracle["files"]:
        capture = (
            oracle_path.parent.parent / "lead" / (source["source"]["pin"][:12] + ".dat")
        )
        data = capture.read_bytes()
        assert hashlib.sha256(data).hexdigest() == source["source"]["sha256"]
        for index in oracle["target_PERSON_indices"].values():
            actual = offers.scan_buffer(data, person_index=index)
            expected = [
                row for row in source["selected_rows"] if row["PERSON_index"] == index
            ]
            assert actual["matched_count"] == len(expected)
            assert len(actual["rows"]) == len(expected)
            assert [
                row["declared_slots"] for row in actual["coverage"]["containers"]
            ] == [source["first_vector_slots"], source["second_vector_slots"]]
            for row, want in zip(actual["rows"], expected, strict=True):
                assert row["source_class"] == want["source_kind"]
                assert row["source"]["start"] == want["start"]
                assert row["source"]["end"] == want["end"]
                assert row["source"]["sha256"] == want["record_sha256"]
                assert row["offer_state"]["raw_code"] == want["native_state8d_u8"]
                assert row["native_60_unsigned_word"] == want["native_60_unsigned32"]
                assert row["stored_vector_indices"] == {
                    "first": want["native_vector08_index"],
                    "second": want["native_vector20_index"],
                }
                assert row["native_58"]["raw_signed32"] == want["raw_native58_signed32"]
                assert [ref["database_index"] for ref in row["team_references"]] == [
                    ref["database_index"] for ref in want["TEAM_references"]
                ]
                if "loan_fields" in want:
                    for key, term in want["loan_fields"].items():
                        assert (
                            row["stored_loan_terms"][key]["raw_signed32"]
                            == term["stored_signed32"]
                        )
                        assert (
                            row["stored_loan_terms"][key]["source_offset"]
                            == term["source_offset"]
                        )


def test_concurrent_buffer_budget_rejects_before_io(archive):
    _, pin, _ = archive
    assert offers._QUERY_SLOT.acquire(blocking=False)
    try:
        with pytest.raises(ValueError, match="in progress"):
            offers.find_offers("test.fm", expected_snapshot_id=pin, person_index=11)
    finally:
        offers._QUERY_SLOT.release()
    assert (
        offers.find_offers("test.fm", expected_snapshot_id=pin, person_index=11)[
            "matched_count"
        ]
        == 2
    )


def test_packed_component_budget_rejects_before_decompression(archive):
    _, pin, member = archive
    member.compressed_size = offers.MAX_PACKED_BYTES + 1
    with pytest.raises(ValueError, match="Packed transfer component exceeds"):
        offers.find_offers("test.fm", expected_snapshot_id=pin, person_index=11)
