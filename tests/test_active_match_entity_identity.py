import copy
import struct

import pytest

from fm_live_mcp import active_match_entity_identity as identities


def source():
    # Entity index != CBE 2*slot+side; playback UID != PERSON native ID.
    actors = [
        dict(
            side_index=0,
            stored_player_slot=2,
            canonical_person_id=998,
            person_name="Player A",
            engine_playback_uid=123,
        ),
        dict(
            side_index=1,
            stored_player_slot=0,
            canonical_person_id=997,
            person_name=None,
            engine_playback_uid=124,
        ),
    ]
    setup = [
        dict(entity_index=8, kind_raw=0, team_index=0, playback_uid=123),
        dict(entity_index=30, kind_raw=0, team_index=1, playback_uid=124),
    ]
    frame = [
        dict(entity_index=0, kind="non_player", playback_uid=111),
        dict(entity_index=8, kind="player", playback_uid=123),
        dict(entity_index=30, kind="player", playback_uid=124),
    ]
    return [[6, 30], setup, frame, actors]


def test_native_index_uid_join_does_not_conflate_person_id_or_cbe_key():
    result = identities.project(*source())
    assert result["state"] == "available"
    assert [
        (r["entity_index"], r["canonical_person_id"], r["engine_playback_uid"])
        for r in result["players"]
    ] == [(8, 998, 123), (30, 997, 124)]
    assert result["players"][1]["person_name"] is None
    assert result["non_player_entities"] == 1
    assert result["nearest_opponent"] is None and result["distance_units"] is None
    assert (
        not result["active_xi_verified"]
        and not result["online_positive_control_verified"]
    )
    assert all(r["on_pitch"] is None for r in result["players"])


@pytest.mark.parametrize(
    "field,value", [("playback_uid", 999), ("team_index", 1), ("kind_raw", 1)]
)
def test_unmatched_native_setup_leaves_actor_unresolved(field, value):
    args = source()
    args[1][0][field] = value
    result = identities.project(*args)
    assert result["state"] == "available_partial"
    assert [p["canonical_person_id"] for p in result["players"]] == [997]
    assert result["unresolved_player_entities"][0]["entity_index"] == 8


def test_frame_uid_mismatch_is_not_joined_by_index_alone():
    args = source()
    args[2][1]["playback_uid"] = 456
    assert len(identities.project(*args)["players"]) == 1


def test_absent_home_base_does_not_invent_entity_zero():
    args = source()
    args[0][0] = -1
    result = identities.project(*args)
    assert [p["side_index"] for p in result["players"]] == [1]
    assert len(result["unresolved_player_entities"]) == 1


@pytest.mark.parametrize("part", [1, 2, 3])
def test_duplicate_source_keys_fail_closed(part):
    args = source()
    args[part].append(copy.deepcopy(args[part][0]))
    with pytest.raises(ValueError, match="Duplicate|Ambiguous"):
        identities.project(*args)


def test_untyped_entity_is_not_classified_as_player():
    args = source()
    args[2][1]["kind"] = "unknown"
    with pytest.raises(ValueError, match="Unclassified"):
        identities.project(*args)


def test_missing_setup_or_canonical_actor_is_unknown_not_zero():
    args = source()
    args[1].clear()
    args[3].clear()
    result = identities.project(*args)
    assert result["state"] == "unavailable_no_resolved_player_entities"
    assert len(result["unresolved_player_entities"]) == 2


@pytest.mark.parametrize("bases", [[-2, 30], [128, 30], [True, 30], [1]])
def test_invalid_player_base_is_rejected(bases):
    args = source()
    args[0] = bases
    with pytest.raises(ValueError):
        identities.project(*args)


def test_overlapping_native_entity_indices_fail_closed():
    args = source()
    args[0] = [28, 30]
    with pytest.raises(ValueError, match="Overlapping"):
        identities.project(*args)


def test_capture_absence_never_calls_native_decoder_or_falls_back(monkeypatch):
    monkeypatch.setattr(
        identities.active_match_shot_timeline, "_verify_bound", lambda *a: None
    )
    base = 0x10000000
    expected = {base + at: data for at, data in identities.NATIVE_SPANS}
    for table, getter in ((0x56A07A0, 0x4AB20D0), (0x56A0750, 0x4AB1F94)):
        expected[base + table + 0x10] = struct.pack("<Q", base + getter)
    expected[0x40220] = bytes(8)

    def read(address, length):
        assert address in expected and len(expected[address]) == length
        return expected[address]

    result = identities.inspect_bound(
        read,
        base,
        0x10000,
        0x20000,
        dict(
            playback_address=0x30000,
            frame_provider_address=0x40000,
            current_time_slice=100,
            official_match_unique_id=99,
        ),
    )
    assert result["state"] == "unavailable_frame_cache" and result["players"] is None
    assert result["caller_readset_and_epoch_verification_required"]
    assert not result["native_functions_executed"]


def capture_memory(monkeypatch):
    data = {}

    def put(address, raw):
        data.update({address + i: value for i, value in enumerate(raw)})

    def q(address, value):
        put(address, struct.pack("<Q", value))

    def read(address, length):
        return bytes(data.get(address + i, 0) for i in range(length))

    base = 0x10000000
    for at, raw in identities.NATIVE_SPANS:
        put(base + at, raw)
    for table, getter, name, info in (
        (0x56A07A0, 0x4AB20D0, b"N7simatch17FRAME_PLAYER_DATAE", 0xB0000),
        (0x56A0750, 0x4AB1F94, b"N7simatch17FRAME_PERSON_DATAE", 0xB1000),
    ):
        q(base + table + 0x10, base + getter)
        put(base + table - 16, struct.pack("<qQ", 0, info))
        q(info + 8, info + 32)
        put(info + 32, name + b"\0")
    q(0x40220, 0x60000)
    header = bytearray(64)
    struct.pack_into("<Q", header, 0, 0x62000)
    header[0x26] = 9
    struct.pack_into("<I", header, 0x38, 100)
    put(0x60000, header)
    q(0x62000 + 8 * 8, 0x70000)
    for index in range(8):
        address = 0x71000 + index * 0x100
        q(0x62000 + index * 8, address)
        q(address, base + 0x56A0750)
        put(address + 8, struct.pack("<I", 1000 + index))
    q(0x70000, base + 0x56A07A0)
    put(0x70008, struct.pack("<I", 123))
    put(0x31DA8, struct.pack("<QQQ", 0x80000, 0x80000 + 9 * 0x160, 0x80000 + 9 * 0x160))
    setup = bytearray(9 * 0x160)
    struct.pack_into("<I", setup, 8 * 0x160 + 0x3C, 123)
    put(0x80000, setup)
    put(0x30043, struct.pack("<bb", 6, 30))
    q(0x40028, 0x52000)
    for side_index in range(2):
        source_side = 0x90000 + side_index * 0x1000
        client_side = 0xC0000 + side_index * 0x1000
        team = 0xD0000 + side_index * 0x1000
        q(0x52000 + 0x15370 + side_index * 8, source_side)
        q(0x20000 + 0x15370 + side_index * 8, client_side)
        q(source_side + 0xB8, team)
        q(client_side + 0xB8, team)
        put(team + 8, struct.pack("<I", side_index))

    def team_by_index(read, base, index):
        return {"native_id": 688 if index == 0 else 692}, {
            "address": 0xD0000 + index * 0x1000
        }

    monkeypatch.setattr(identities.teams, "by_index", team_by_index)

    q(0x52000 + 0x15370, 0x90000)
    q(0x90000 + 0x140 + 2 * 8, 0xA0000)
    put(0xA0048, struct.pack("<I", 123))
    monkeypatch.setattr(
        identities.active_match_shot_timeline, "_verify_bound", lambda *a: None
    )
    seen = []

    def actors(read, base, engine, *, expected_match_unique_id):
        seen.append(engine)
        assert expected_match_unique_id == 99
        return {"players": [source()[3][0]], "unresolved": []}

    monkeypatch.setattr(
        identities.active_match_people, "inspect_actor_bindings", actors
    )
    bound = dict(
        playback_address=0x30000,
        frame_provider_address=0x40000,
        current_time_slice=100,
        official_match_unique_id=99,
    )
    return read, put, q, base, bound, seen


def test_exact_cache_capture_joins_source_engine_not_unbound_current_player_array(
    monkeypatch,
):
    read, put, q, base, bound, seen = capture_memory(monkeypatch)
    result = identities.inspect_bound(read, base, 0x10000, 0x20000, bound)
    assert seen == [0x52000]  # Provider-owned source GAME_MATCH; different engine copy.
    assert result["players"][0]["canonical_person_id"] == 998
    assert result["players"][0]["entity_index"] == 8
    assert result["players"][0]["team_native_id"] == 688
    assert result["observed_cursor"] == 100
    assert result["official_match_unique_id"] == 99
    assert result["caller_readset_and_epoch_verification_required"]
    assert not result["online_positive_control_verified"]


def test_wrong_cache_tick_does_not_substitute_nearest_frame(monkeypatch):
    read, put, q, base, bound, seen = capture_memory(monkeypatch)
    put(0x60038, struct.pack("<I", 99))
    result = identities.inspect_bound(read, base, 0x10000, 0x20000, bound)
    assert result["state"] == "unavailable_unique_exact_cursor_cache_frame"
    assert result["players"] is None and not seen


def test_duplicate_exact_cursor_frames_reject_ambiguous_source(monkeypatch):
    read, put, q, base, bound, seen = capture_memory(monkeypatch)
    put(0x60420 + 0x38, struct.pack("<I", 100))
    assert (
        identities.inspect_bound(read, base, 0x10000, 0x20000, bound)["players"] is None
    )


def test_unrecognized_runtime_frame_class_rejects(monkeypatch):
    read, put, q, base, bound, seen = capture_memory(monkeypatch)
    q(0x70000, base + 0x123456)
    with pytest.raises(ValueError, match="Unknown native"):
        identities.inspect_bound(read, base, 0x10000, 0x20000, bound)


def test_corrupt_setup_geometry_rejects_instead_of_empty(monkeypatch):
    read, put, q, base, bound, seen = capture_memory(monkeypatch)
    q(0x31DA8 + 8, 0x80001)
    with pytest.raises(ValueError, match="geometry"):
        identities.inspect_bound(read, base, 0x10000, 0x20000, bound)


def test_engine_uid_mismatch_withholds_named_identity(monkeypatch):
    read, put, q, base, bound, seen = capture_memory(monkeypatch)
    put(0xA0048, struct.pack("<I", 999))
    result = identities.inspect_bound(read, base, 0x10000, 0x20000, bound)
    assert result["players"] == [] and result["unresolved_player_entities"]


def test_native_class_getter_change_rejects(monkeypatch):
    read, put, q, base, bound, seen = capture_memory(monkeypatch)
    q(base + 0x56A07A0 + 0x10, base + 0x4AB1F94)
    with pytest.raises(ValueError, match="classification"):
        identities.inspect_bound(read, base, 0x10000, 0x20000, bound)


def test_null_frame_pointer_does_not_silently_drop_unknown_entity(monkeypatch):
    read, put, q, base, bound, seen = capture_memory(monkeypatch)
    q(0x62000, 0)
    with pytest.raises(ValueError, match="Incomplete frame"):
        identities.inspect_bound(read, base, 0x10000, 0x20000, bound)


def test_provider_engine_and_client_team_copy_mismatch_rejects(monkeypatch):
    read, put, q, base, bound, seen = capture_memory(monkeypatch)
    q(0xC0000 + 0xB8, 0xE0000)
    with pytest.raises(ValueError, match="ordered TEAM"):
        identities.inspect_bound(read, base, 0x10000, 0x20000, bound)


def test_team_table_membership_mismatch_rejects(monkeypatch):
    read, put, q, base, bound, seen = capture_memory(monkeypatch)
    monkeypatch.setattr(
        identities.teams,
        "by_index",
        lambda *args: ({"native_id": 688}, {"address": 0xE0000}),
    )
    with pytest.raises(ValueError, match="canonical membership"):
        identities.inspect_bound(read, base, 0x10000, 0x20000, bound)
