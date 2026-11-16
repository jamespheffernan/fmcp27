"""Fail-closed playback entity identities; never participation or distances.

Caller must finish the shared ReadSet and process/career epoch checks. The
native playback UID is deliberately distinct from the canonical PERSON ID.
"""

import struct

from . import active_match_people, active_match_shot_timeline, players, teams

MAX_ENTITIES = 128
NATIVE_SPANS = (
    (0xD6C4, bytes.fromhex("012c80525f832b95")),
    (0xDB74, bytes.fromhex("4107805233822b95")),
    (0xDBB8, bytes.fromhex("8107805222822b95")),
    (0x734774, bytes.fromhex("09d94ef901d54ef9280101cb08fd4593")),
    (0x741700, bytes.fromhex("5403059116230091")),
    (
        0x74191C,
        bytes.fromhex(
            "0801170b68ef3f37081d0013090b8252696a69f80a0680521b252a9b40230091e1031baa3f010094"
        ),
    ),
    (
        0x741E58,
        bytes.fromhex("084040b9096602d029412b91290140b91f01096b08119f5a280000b9"),
    ),
    (0x736BE8, bytes.fromhex("880240b9683e00b9")),
    (0x736774, bytes.fromhex("a82e40390813013916eb0039")),
    (0x738FEC, bytes.fromhex("e8c31e91a0a200916af4ff9796a23691a1d64ef9")),
    (0x735750, bytes.fromhex("b5060091690240f90a0840b92901178b2ac11fb8")),
    (
        0x48B3128,
        bytes.fromhex(
            "e100f8370898c0391f01016b8d000054080040f900d961f8c0035fd6000080d2c0035fd6"
        ),
    ),
    (0x4AB20D0, bytes.fromhex("20008052c0035fd6")),
    (0x4AB1F94, bytes.fromhex("00008052c0035fd6")),
)


def project(player_bases, setup, frame_entities, actors):
    """Join exact native entity indices through the same engine player objects."""
    if (
        not isinstance(player_bases, (tuple, list))
        or len(player_bases) != 2
        or any(type(v) is not int or not -1 <= v < MAX_ENTITIES for v in player_bases)
    ):
        raise ValueError("Unsupported playback player entity bases")
    if any(
        not isinstance(rows, list) or len(rows) > MAX_ENTITIES
        for rows in (setup, frame_entities, actors)
    ):
        raise ValueError("Unsupported playback entity budget")
    indexed = {}
    for row in setup:
        index = row.get("entity_index")
        if type(index) is not int or not 0 <= index < MAX_ENTITIES or index in indexed:
            raise ValueError("Duplicate or invalid playback setup entity index")
        if (
            type(row.get("kind_raw")) is not int
            or not 0 <= row["kind_raw"] <= 255
            or type(row.get("team_index")) is not int
            or not -128 <= row["team_index"] <= 127
            or type(row.get("playback_uid")) is not int
            or not 0 <= row["playback_uid"] <= 0xFFFFFFFF
        ):
            raise ValueError("Invalid native playback setup identity fields")
        indexed[index] = row
    candidates, actor_keys, canonical_ids = {}, set(), set()
    for actor in actors:
        side, slot = actor.get("side_index"), actor.get("stored_player_slot")
        identity, uid = (
            actor.get("canonical_person_id"),
            actor.get("engine_playback_uid"),
        )
        if (
            type(side) is not int
            or side not in (0, 1)
            or type(slot) is not int
            or not 0 <= slot < 26
            or type(identity) is not int
            or identity <= 0
            or type(uid) is not int
            or not 0 <= uid < 0xFFFFFFFF
            or (side, slot) in actor_keys
            or identity in canonical_ids
        ):
            raise ValueError("Ambiguous canonical engine actor identity")
        actor_keys.add((side, slot))
        canonical_ids.add(identity)
        if player_bases[side] >= 0:
            index = player_bases[side] + slot
            if index >= MAX_ENTITIES or index in candidates:
                raise ValueError(
                    "Overlapping or excessive playback player entity index"
                )
            candidates[index] = actor
    output, unresolved, seen = [], [], set()
    non_players = 0
    for entity in frame_entities:
        index = entity.get("entity_index")
        if type(index) is not int or not 0 <= index < MAX_ENTITIES or index in seen:
            raise ValueError("Duplicate or invalid frame entity index")
        seen.add(index)
        if (
            type(entity.get("playback_uid")) is not int
            or not 0 <= entity["playback_uid"] <= 0xFFFFFFFF
        ):
            raise ValueError("Invalid native frame identity fields")
        if entity.get("kind") == "non_player":
            non_players += 1
            continue
        if entity.get("kind") != "player":
            raise ValueError("Unclassified native frame entity type")
        actor, row = candidates.get(index), indexed.get(index)
        reason = None
        if actor is None:
            reason = "canonical_actor_for_native_entity_index_unavailable"
        elif row is None:
            reason = "playback_setup_entity_unavailable"
        elif row.get("kind_raw") != 0 or row.get("team_index") != actor["side_index"]:
            reason = "native_setup_player_kind_or_ordered_team_mismatch"
        elif row.get("playback_uid") != actor["engine_playback_uid"] or entity.get(
            "playback_uid"
        ) != row.get("playback_uid"):
            reason = "frame_setup_and_same_engine_player_uid_mismatch"
        if reason:
            unresolved.append({"entity_index": index, "reason": reason})
            continue
        output.append(
            {
                **actor,
                "entity_index": index,
                "identity_state": "same_engine_original_slot_constructor_and_frame_setup_uid_agree",
                "on_pitch": None,
                "displayed_participation": None,
            }
        )
    state = (
        ("available_partial" if unresolved else "available")
        if output
        else "unavailable_no_resolved_player_entities"
    )
    return {
        "state": state,
        "players": output,
        "unresolved_player_entities": unresolved,
        "non_player_entities": non_players,
        "identity_policy": "entity_index=ordered_side_native_base+original_roster_slot; same MATCH_PLAYER UID agrees with setup and typed frame entity",
        "uid_namespace_policy": "playback UID is not assumed equal to canonical PERSON native ID",
        "active_xi_verified": False,
        "nearest_opponent": None,
        "distance_units": None,
        "live_vs_replay_verified": False,
        "online_positive_control_verified": False,
    }


def _q(read, address):
    return players.u64(read(address, 8))


def _pointer(value):
    if value < 4096 or value >= 1 << 48 or value % 8:
        raise ValueError("Invalid playback entity source pointer")
    return value


def _bytes(read, address, length):
    return b"".join(
        read(at, min(8192, address + length - at))
        for at in range(address, address + length, 8192)
    )


def inspect_bound(read, base, client, engine, bound_playback):
    """Capture one already resident exact cursor frame; execute no frame getter.

    A missing exact cache frame stays unavailable. No decoding native call,
    nearest-cache-frame substitution or historical source is attempted.
    """
    active_match_shot_timeline._verify_bound(read, base, client, engine, bound_playback)
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError("Native playback entity identity construction changed")
    for table, getter in ((0x56A07A0, 0x4AB20D0), (0x56A0750, 0x4AB1F94)):
        if _q(read, base + table + 0x10) != base + getter:
            raise ValueError("Native frame player classification getter changed")
    cursor = bound_playback["current_time_slice"]
    playback, provider = (
        bound_playback["playback_address"],
        bound_playback["frame_provider_address"],
    )
    common = {
        "official_match_unique_id": bound_playback["official_match_unique_id"],
        "observed_cursor": cursor,
        "clock_units": "native_playback_time_slice",
        "caller_readset_and_epoch_verification_required": True,
        "native_functions_executed": False,
        "game_writes": False,
        "online_positive_control_verified": False,
        "active_xi_verified": False,
        "nearest_opponent": None,
        "distance_units": None,
    }
    cache = _q(read, provider + 0x220)
    if not cache:
        return {**common, "state": "unavailable_frame_cache", "players": None}
    _pointer(cache)
    matching = []
    for index in range(6):
        header = read(cache + index * 0x420, 0x40)
        if struct.unpack_from("<I", header, 0x38)[0] == cursor:
            matching.append((index, header))
    if len(matching) != 1:
        return {
            **common,
            "state": "unavailable_unique_exact_cursor_cache_frame",
            "players": None,
        }
    _, header = matching[0]
    count = struct.unpack_from("<b", header, 0x26)[0]
    if not 0 <= count < MAX_ENTITIES:
        raise ValueError("Unsupported frame entity count")
    pointers = (
        struct.unpack(f"<{count}Q", read(_pointer(players.u64(header)), count * 8))
        if count
        else ()
    )
    frame_entities = []
    for index, address in enumerate(pointers):
        if not address:
            raise ValueError("Incomplete frame entity pointer table")
        _pointer(address)
        table = _q(read, address)
        if table == base + 0x56A07A0:
            active_match_people._type(
                read, base, address, 0x56A07A0, b"N7simatch17FRAME_PLAYER_DATAE"
            )
            kind = "player"
        elif table == base + 0x56A0750:
            active_match_people._type(
                read, base, address, 0x56A0750, b"N7simatch17FRAME_PERSON_DATAE"
            )
            kind = "non_player"
        else:
            raise ValueError("Unknown native playback frame entity type")
        frame_entities.append(
            {
                "entity_index": index,
                "kind": kind,
                "playback_uid": struct.unpack("<I", read(address + 8, 4))[0],
            }
        )
    first, last, capacity = struct.unpack("<QQQ", read(playback + 0x1DA8, 24))
    if (first, last, capacity) == (0, 0, 0):
        return {**common, "state": "unavailable_playback_entity_setup", "players": None}
    _pointer(first)
    if (
        not first <= last <= capacity
        or (last - first) % 0x160
        or (capacity - first) % 0x160
        or (capacity - first) // 0x160 > MAX_ENTITIES
    ):
        raise ValueError("Unsupported playback entity setup geometry")
    raw = _bytes(read, first, last - first)
    setup = [
        {
            "entity_index": index,
            "kind_raw": raw[index * 0x160],
            "team_index": struct.unpack_from("<b", raw, index * 0x160 + 0x3A)[0],
            "playback_uid": struct.unpack_from("<I", raw, index * 0x160 + 0x3C)[0],
        }
        for index in range(len(raw) // 0x160)
    ]
    player_bases = struct.unpack("<bb", read(playback + 0x28 + 0x1B, 2))
    source_engine = _pointer(_q(read, provider + 0x28))
    actor_source = capture_actor_source(
        read, base, engine, source_engine, bound_playback["official_match_unique_id"]
    )
    actors, binding = actor_source["actors"], actor_source["binding"]
    result = project(player_bases, setup, frame_entities, actors)
    return {
        **result,
        **common,
        "native_identity_construction_verified": True,
        "source_kind": "same_GAME_MATCH_playback_exact_cursor_frame_and_entity_setup",
        "unresolved_original_roster_actors": binding["unresolved"],
    }


def capture_actor_source(read, base, engine, source_engine, match_unique_id):
    """Canonical original-slot identities and constructor UIDs, no clock sampling."""
    side_teams = {}
    for side_index in range(2):
        source_side = _pointer(_q(read, source_engine + 0x15370 + side_index * 8))
        client_side = _pointer(_q(read, engine + 0x15370 + side_index * 8))
        team = _pointer(_q(read, source_side + 0xB8))
        if _q(read, client_side + 0xB8) != team:
            raise ValueError(
                "Playback source and bound client ordered TEAM identities differ"
            )
        index = struct.unpack("<I", read(team + 8, 4))[0]
        public_team, team_binding = teams.by_index(read, base, index)
        if team_binding["address"] != team:
            raise ValueError("Playback TEAM canonical membership differs")
        side_teams[side_index] = source_side, public_team["native_id"]
    binding = active_match_people.inspect_actor_bindings(
        read,
        base,
        source_engine,
        expected_match_unique_id=match_unique_id,
    )
    actors = []
    for actor in binding["players"]:
        side, team_native_id = side_teams[actor["side_index"]]
        address = _pointer(_q(read, side + 0x140 + actor["stored_player_slot"] * 8))
        uid = struct.unpack("<I", read(address + 0x48, 4))[0]
        if uid == 0xFFFFFFFF:
            continue
        actors.append(
            {**actor, "engine_playback_uid": uid, "team_native_id": team_native_id}
        )
    return {"actors": actors, "binding": binding}
