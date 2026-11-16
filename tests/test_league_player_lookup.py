# ruff: noqa: F401, F811
import asyncio
from copy import deepcopy

import pytest
from test_assessment_people import binding, canonical, identity_memory
from test_bridge import bridge
from test_database import database_memory
from test_league_player_ranking import bind, candidate, census, ranking_census, row
from test_players import memory
from test_shortlist_members import member_memory
from test_virtual import virtual_memory
from test_virtual_identity import compact_virtual_memory
from test_world import world_memory

from fm_live_mcp import (
    assessment_people,
)
from fm_live_mcp import (
    league_player_lookup as lookup,
)
from fm_live_mcp import (
    league_player_ranking as totals,
)
from fm_live_mcp.bridge import BridgeError


def public(index=0, kind="actual"):
    return {
        "display_name": f"Player{index}",
        "record_kind": kind,
        "native_identity": {
            "database_index": index,
            "native_id": 100 + index,
            "random_id": None,
        },
    }


def source_candidate(index=0, **kwargs):
    return {
        **candidate(index, **kwargs),
        "_identity": public(index),
        "_primary_address": 0x70000 - 0x388,
        "last_associated_team_index": 545,
        "last_associated_team": {"database_index": 545},
    }


def available(count):
    return {
        "source_state": "available",
        "complete_resident_pool": True,
        "physical_count": count,
    }


def test_project_preserves_duplicate_request_order_and_unknown_not_zero():
    r = lookup.project(
        available(1),
        [source_candidate()],
        [
            ("missing", 0x80000, public(10)),
            ("present", 0x70000, public()),
            ("again", 0x70000, public()),
        ],
    )
    assert [p["person_index"] for p in r["rows"]] == [10, 0, 0]
    assert r["requested_count"] == 3 and r["unique_requested_person_count"] == 2
    assert r["not_observed_count"] == 1 and r["observed_count"] == 2
    assert r["rows"][0]["state"] == "not_observed_in_resident_pool"
    assert r["rows"][0]["minutes"] is None and r["rows"][0]["raw"] is None
    assert r["rows"][1]["minutes"] == 1080 and r["response_complete"]
    assert not r["all_requested_rows_observed"]
    assert "0x70000" not in repr(r)


def test_zero_anomalous_and_null_TEAM_metrics_remain_distinct():
    for kwargs in (
        {"apps": 0, "subs": 0, "minutes": 0, "goals": 0},
        {"apps": 255, "subs": 0, "minutes": -1, "goals": 255},
    ):
        item = source_candidate(**kwargs)
        got = lookup.project(available(1), [item], [("r", 0x70000, public())])["rows"][
            0
        ]
        assert got["state"] == "observed_competition_counter"
        for key in totals.METRICS:
            assert got[key] == item[key]
        assert got["metric_states"] == item["metric_states"]
    item["starting_appearances"] = None
    item["metric_states"]["starting_appearances"] = (
        "unavailable_native_getter_TEAM_precondition"
    )
    assert (
        lookup.project(available(1), [item], [("r", 0x70000, public())])["rows"][0][
            "starting_appearances"
        ]
        is None
    )


def test_source_unavailable_and_available_empty_differ():
    requested = [("r", 0x70000, public())]
    a = lookup.project({"source_state": "unavailable"}, [], requested)
    b = lookup.project(available(0), [], requested)
    assert a["rows"][0]["state"] == "source_unavailable" and a["unavailable_count"] == 1
    assert (
        b["rows"][0]["state"] == "not_observed_in_resident_pool"
        and b["not_observed_count"] == 1
    )
    assert a["response_complete"] and b["response_complete"]


@pytest.mark.parametrize(
    "change", ["id", "secondary", "primary", "kind", "duplicate", "incomplete"]
)
def test_join_requires_independent_exact_canonical_identity(change):
    item = source_candidate()
    cover = available(1)
    items = [item]
    if change == "id":
        item["_identity"]["native_identity"]["native_id"] += 1
    elif change == "secondary":
        item["_identity"]["native_identity"]["random_id"] = 0
    elif change == "primary":
        item["_primary_address"] += 8
    elif change == "kind":
        item["_identity"]["record_kind"] = "player_staff"
    elif change == "duplicate":
        items.append(deepcopy(item))
        cover = available(2)
    else:
        cover["complete_resident_pool"] = False
    with pytest.raises(ValueError):
        lookup.project(cover, items, [("r", 0x70000, public())])


def test_real_actual_ref_rebind(identity_memory):
    m = identity_memory
    person, p = lookup.bound_subject(
        m["read"], m["base"], m["tables"], canonical(m), binding(m)
    )
    assert person == 0x1388 and p["display_name"] == "Test Müller"
    bad = binding(m)
    bad["identity"] = (999,) + bad["identity"][1:]
    with pytest.raises(assessment_people.StalePlayerReference):
        lookup.bound_subject(m["read"], m["base"], m["tables"], canonical(m), bad)


def test_compact_virtual_identity_never_reads_manager_or_profile(
    compact_virtual_memory,
):
    from fm_live_mcp import virtual, virtual_identity

    m = compact_virtual_memory
    core = virtual_identity.inspect(m["read"], m["compact"], m["tables"])
    b = {
        "record_kind": "virtual",
        "tables": m["tables"],
        "binding_kind": virtual_identity.BINDING_KIND,
        "person_offset": 0x20,
        "address": m["compact"],
        "database_index": 1,
        "identity": core["identity"],
    }

    def read(a, n):
        assert not a <= m["base"] + virtual.MANAGER_ROOT < a + n
        return m["read"](a, n)

    person, p = lookup.bound_subject(read, m["base"], m["tables"], {}, b)
    assert person == m["compact_person"] and p["display_name"] is None
    b["identity"] = (core["identity"][0], 1, 999, 12345)
    with pytest.raises(assessment_people.StalePlayerReference):
        lookup.bound_subject(read, m["base"], m["tables"], {}, b)


def setup(bridge, ranking_census, monkeypatch):
    b = bind(bridge, ranking_census, monkeypatch)
    for index in (0, 1, 10):
        b.player_refs[str(index)] = {"requested": index}
    calls = []

    def subject(read, base, tables, people, binding):
        index = binding["requested"]
        kind = "player_staff" if index == 1 else "actual"
        return 0x70000 + index * 0x10000, public(index, kind)

    monkeypatch.setattr(lookup, "bound_subject", subject)
    original = totals.collect

    def collect(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(totals, "collect", collect)
    return b, calls


def test_bridge_one_full_pool_for_middle_missing_combined_duplicate_requests(
    bridge, ranking_census, monkeypatch
):
    b, calls = setup(bridge, ranking_census, monkeypatch)
    before = dict(b.player_refs)
    got = b.get_league_player_statistics(b.session, "comp", ["1", "10", "0", "1"])
    assert calls == [1] and got["source"]["physical_count"] == 2
    assert (
        got["source_pin"]
        and got["observed_count"] == 3
        and got["not_observed_count"] == 1
    )
    assert [r["person_index"] for r in got["rows"]] == [1, 10, 0, 1]
    assert got["rows"][0]["person"]["record_kind"] == "player_staff"
    assert b.player_refs == before
    again = b.get_league_player_statistics(b.session, "comp", ["0"])
    assert again["source_pin"] == got["source_pin"]


def test_bridge_source_and_byte_change_fail_closed(bridge, ranking_census, monkeypatch):
    b, _ = setup(bridge, ranking_census, monkeypatch)
    original = lookup.project

    def project(*args):
        result = original(*args)
        ranking_census["memory"].put(0x5000C, b"\x06")
        return result

    monkeypatch.setattr(lookup, "project", project)
    with pytest.raises(BridgeError, match="changed"):
        b.get_league_player_statistics(b.session, "comp", ["0"])
    assert set(b.player_refs) == {"0", "1", "10"}


@pytest.mark.parametrize("refs", [[], ["missing"], [True], [""], ["0"] * 101])
def test_invalid_requests(bridge, ranking_census, monkeypatch, refs):
    b, _ = setup(bridge, ranking_census, monkeypatch)
    with pytest.raises(BridgeError):
        b.get_league_player_statistics(b.session, "comp", refs)


def test_tool_schema_and_forwarding(monkeypatch):
    from fm_live_mcp import server

    tools = asyncio.run(server.mcp.list_tools())
    t = next(t for t in tools if t.name == "fm_get_league_player_statistics")
    assert t.annotations.readOnlyHint and not t.annotations.destructiveHint
    assert set(t.inputSchema["required"]) == {
        "session_id",
        "competition_ref",
        "player_refs",
    }
    assert t.inputSchema["properties"]["player_refs"]["maxItems"] == 100
    calls = []
    monkeypatch.setattr(
        server.bridge, "get_league_player_statistics", lambda *a: calls.append(a) or {}
    )
    server.fm_get_league_player_statistics("s", "c", ["r"])
    assert calls == [("s", "c", ["r"])]


def test_real_combined_ref_keeps_independent_secondary(identity_memory):
    m = identity_memory
    primary, person = m["add_person"]("player_staff", 0, 444, 0, "Combined Player")
    m["vec"](m["headers"]["people"], [person])
    found, p = lookup.bound_subject(
        m["read"],
        m["base"],
        m["tables"],
        canonical(m),
        binding(m, primary, True, "player_staff"),
    )
    assert (
        found == person
        and p["native_identity"]["random_id"] == 0
        and p["record_kind"] == "player_staff"
    )


def test_full100_requests_are_preserved_and_source_read_once(
    bridge, ranking_census, monkeypatch
):
    b, calls = setup(bridge, ranking_census, monkeypatch)
    result = b.get_league_player_statistics(b.session, "comp", ["0", "1"] * 50)
    assert (
        calls == [1]
        and result["requested_count"] == 100
        and result["observed_count"] == 100
    )
    assert (
        result["unique_requested_person_count"] == 2
        and result["all_requested_rows_observed"]
    )


@pytest.mark.parametrize("absent", [False, True])
def test_bridge_empty_and_unresident_source(
    bridge, ranking_census, monkeypatch, absent
):
    b, _ = setup(bridge, ranking_census, monkeypatch)
    m = ranking_census["memory"]
    m.pack(ranking_census["stats"] + 0x1278, "<QQQ", 0, 0, 0)
    if absent:
        m.pack(ranking_census["runtime"] + 0x390, "<Q", 0)
    result = b.get_league_player_statistics(b.session, "comp", ["0"])
    assert result["rows"][0]["state"] == (
        "source_unavailable" if absent else "not_observed_in_resident_pool"
    )
    assert (result["source_pin"] is None) == absent
    assert all(result["rows"][0][key] is None for key in totals.METRICS)


def test_stale_input_removed_only_after_checked_failure(
    bridge, ranking_census, monkeypatch
):
    b, _ = setup(bridge, ranking_census, monkeypatch)

    def stale(*a):
        raise assessment_people.StalePlayerReference("changed")

    monkeypatch.setattr(lookup, "bound_subject", stale)
    with pytest.raises(BridgeError, match="changed"):
        b.get_league_player_statistics(b.session, "comp", ["0"])
    assert set(b.player_refs) == {"1", "10"}
