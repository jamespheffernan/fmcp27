import struct
import json
import pytest
from fm_live_mcp import live_transfer_offers as offers, world


class Memory:
    def __init__(self):
        self.data = {}
        self.reads = []

    def put(self, address, data):
        for i, v in enumerate(data):
            self.data[address + i] = v

    def __call__(self, address, size):
        self.reads.append((address, size))
        return bytes(self.data.get(address + i, 0) for i in range(size))


def vector(memory, manager, offset, start, values, capacity=None):
    memory.put(
        manager + offset,
        struct.pack(
            "<QQQ",
            start,
            start + 8 * len(values),
            start + 8 * (len(values) if capacity is None else capacity),
        ),
    )
    memory.put(start, struct.pack(f"<{len(values)}Q", *values))


def test_vectors_preserve_null_slots_and_object_aliases_without_inventing_offers():
    m = Memory()
    root = 0x10000
    vector(m, root, 0x20, 0x20000, [0x30000, 0, 0x30000])
    vector(m, root, 0x38, 0x21000, [0x40000])
    rows = offers._vectors(m, root)
    assert [(n, v) for n, _, v in rows] == [
        ("first_offer_vector", (0x30000, 0, 0x30000)),
        ("second_offer_vector", (0x40000,)),
    ]
    m = Memory()
    assert [v for _, _, v in offers._vectors(m, root)] == [(), ()]


@pytest.mark.parametrize(
    "header",
    [
        (0x20000, 0x1FFF8, 0x20000),
        (0x20001, 0x20001, 0x20001),
        (0x20000, 0x20000, 0x20000 + 8 * (offers.MAX_SLOTS + 1)),
    ],
)
def test_invalid_or_overbudget_vector_is_unknown_not_empty(header):
    m = Memory()
    m.put(0x10020, struct.pack("<QQQ", *header))
    with pytest.raises(ValueError):
        offers._vectors(m, 0x10000)


def test_batched_initial_read_rechecks_only_consumed_headers_not_padding():
    m = Memory()
    a = 0x30000
    b = a + 0x128
    m.put(a, b"A" * 0x90)
    m.put(b, b"B" * 0x90)
    snapshot = world.ReadSet(m)
    offers._read_headers(snapshot, [a, b, a])
    assert len(m.reads) == 1
    assert snapshot.observed == {(a, 0x90): b"A" * 0x90, (b, 0x90): b"B" * 0x90}
    m.put(a + 0x90, b"changed padding")
    snapshot.verify()
    m.put(b + 0x8D, b"\x03")
    with pytest.raises(ValueError, match="changed"):
        snapshot.verify()


def test_header_crossing_bucket_boundary_keeps_its_bounded_range():
    m = Memory()
    a = 0x30FF8
    m.put(a, b"X" * 0x90)
    snapshot = world.ReadSet(m)
    offers._read_headers(snapshot, [a])
    assert m.reads == [(a, 0x90)]
    snapshot.verify()


def test_null_manager_does_not_become_verified_empty_population():
    assert offers._manager(Memory(), 0x10000000) is None


def test_factory_type_getter_is_checked_without_calling_it():
    m = Memory()
    base = 0x10000000
    vt = base + 0x55C83F0
    ti = base + 0x55C87E0
    name = base + 0x53A3710
    m.put(vt - 16, struct.pack("<qQ", 0, ti))
    m.put(ti + 8, struct.pack("<Q", name))
    m.put(ti + 16, struct.pack("<Q", base + 0x55C9020))
    m.put(name, b"10LOAN_OFFER\0")
    m.put(vt + 0x78, struct.pack("<Q", base + 0x1845BA8))
    m.put(base + 0x1845BA8, bytes.fromhex("60008052c0035fd6"))
    assert offers._type(m, base, vt) == "loan"
    m.put(base + 0x1845BA8, b"\0" * 8)
    with pytest.raises(ValueError, match="factory kind"):
        offers._type(m, base, vt)
    with pytest.raises(ValueError, match="Unclassified"):
        offers._type(m, base, base + 0x1230)


def test_known_proposed_cash_units_preserve_zero_negative_and_unknown_currency():
    assert offers._cash(0, "GBP", "week")["amount"] == 0
    assert offers._cash(-1, "GBP", "month")["amount"] is None
    assert offers._cash(-1, "GBP", "month")["raw_signed32"] == -1
    assert offers._cash(100, None, "week")["currency"] is None
    assert offers._cash(100, "GBP", "week")["basis"] == "stored_proposed_offer_term"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": True},
        {"limit": 101},
        {"person_native_id": True},
        {"team_native_id": -1},
        {"club_native_id": 0},
        {"raw_state_codes": [0, 0]},
        {"raw_state_codes": [True]},
        {"cursor": ""},
    ],
)
def test_invalid_selectors_are_rejected_before_any_game_access(kwargs):
    with pytest.raises(ValueError):
        offers.query(None, "session", **kwargs)


def test_mcp_surface_uses_native_ids_and_no_memory_or_file_selectors():
    import inspect
    from fm_live_mcp.server import fm_query_transfer_offers

    names = set(inspect.signature(fm_query_transfer_offers).parameters)
    assert names == {
        "session_id",
        "person_native_id",
        "team_native_id",
        "club_native_id",
        "raw_state_codes",
        "limit",
        "cursor",
    }
    assert "English state labels remain unmapped" in offers.LIMITS


def test_mcp_annotations_and_schema_are_read_only():
    import asyncio
    from fm_live_mcp import server

    async def check():
        tool = next(
            t
            for t in await server.mcp.list_tools()
            if t.name == "fm_query_transfer_offers"
        )
        assert (
            tool.annotations.readOnlyHint is True
            and tool.annotations.destructiveHint is False
        )
        assert (
            tool.inputSchema["properties"]["raw_state_codes"]["anyOf"][0]["items"][
                "minimum"
            ]
            == 0
        )

    asyncio.run(check())


def test_complete_empty_offers_do_not_require_unrelated_identity_or_currency_data(
    monkeypatch,
):
    from contextlib import nullcontext
    from threading import RLock
    from types import SimpleNamespace

    m = Memory()

    class Bridge:
        lock = RLock()
        database_cursors = {}

        def _read_scope(self, s):
            return nullcontext()

        def _current(self, s):
            return SimpleNamespace(pid=1)

        def _player_layout(self, p):
            return (offers.players.RVA[0],)

        def _world_state(self, p, t):
            return world.ReadSet(m), {"current_date": "2030-11-02"}, ("epoch",)

        def _public_save(self, s):
            return s

    monkeypatch.setattr(offers, "_manager", lambda *a: 0x10000)
    monkeypatch.setattr(
        offers.assessment_people,
        "verify_native",
        lambda *a: pytest.fail("empty source needs no PERSON decode"),
    )
    r = offers.query(Bridge(), "session", club_native_id=688)
    assert r["state"] == "available_empty" and r["complete_source"] is True
    assert r["match_count"] == 0 and r["offers"] == []
    assert r["base_currency_state"] == "not_read_for_empty_offer_source"


def test_query_pagination_binds_native_states_and_preserves_alias_membership(
    monkeypatch,
):
    from contextlib import nullcontext
    from threading import RLock
    from types import SimpleNamespace

    m = Memory()
    root = 0x10000
    person = 0x50000
    team = 0x51000
    vector(m, root, 0x20, 0x20000, [0x30000, 0, 0x31000])
    vector(m, root, 0x38, 0x21000, [0x30000])
    for a, state in ((0x30000, 20), (0x31000, 0)):
        raw = bytearray(0x90)
        struct.pack_into("<Q", raw, 0, 0x40000)
        struct.pack_into("<QQQQ", raw, 0x38, person, team, team, team)
        raw[0x8D] = state
        m.put(a, raw)

    class Bridge:
        def __init__(self):
            self.lock = RLock()
            self.database_cursors = {}

        def _read_scope(self, s):
            return nullcontext()

        def _current(self, s):
            return SimpleNamespace(pid=1)

        def _player_layout(self, p):
            return (offers.players.RVA[0],)

        def _world_state(self, p, t):
            return world.ReadSet(m), {"current_date": "2030-11-02"}, ("epoch",)

        def _public_save(self, s):
            return s

    monkeypatch.setattr(offers, "_manager", lambda *a: root)
    monkeypatch.setattr(offers, "_type", lambda *a: "full_transfer")
    monkeypatch.setattr(offers.assessment_people, "verify_native", lambda *a: None)
    monkeypatch.setattr(
        offers.database, "table", lambda *a: {"start": 0x60000, "count": 1}
    )
    monkeypatch.setattr(
        offers.teams,
        "lookup",
        lambda *a: {
            "start": 0x61000,
            "count": 1,
            "lookup_start": 0x61000,
            "lookup_count": 1,
        },
    )
    monkeypatch.setattr(
        offers, "_canonical_person", lambda *a: {"database_index": 0, "native_id": 42}
    )
    monkeypatch.setattr(
        offers,
        "_canonical_team",
        lambda *a: {
            "database_index": 0,
            "native_id": 7,
            "owner": {"native_id": 8, "kind": "club"},
        },
    )
    monkeypatch.setattr(
        offers,
        "_person_name",
        lambda *a: {
            "state": "canonical_PERSON",
            "identity": a[-1],
            "name": "Source person",
        },
    )
    monkeypatch.setattr(
        offers.teams,
        "by_index",
        lambda *a, **k: (
            {"database_index": 0, "native_id": 7},
            {"address": 0xABCDEF0000},
        ),
    )

    def unsupported(*a):
        raise ValueError("unsupported base currency")

    monkeypatch.setattr(offers.wages, "base_currency", unsupported)
    b = Bridge()
    first = offers.query(b, "s", limit=1)
    assert first["nonnull_occurrences"] == 3 and first["distinct_offer_objects"] == 2
    assert first["source_native_state_counts"] == {20: 1, 0: 1}
    assert first["offers"][0]["native_state"] == {
        "code": 20,
        "label": None,
        "state": "unmapped_native_offer_state",
    }
    second = offers.query(b, "s", limit=1, cursor=first["next_cursor"])
    assert (
        second["source_id"] == first["source_id"]
        and second["offers"][0]["native_state"]["code"] == 0
    )
    third = offers.query(b, "s", limit=1, cursor=second["next_cursor"])
    assert (
        third["offers"][0]["object_id"] == first["offers"][0]["object_id"]
        and third["next_cursor"] is None
    )
    assert "address" not in json.dumps([first, second, third])
    with pytest.raises(ValueError, match="selectors changed"):
        offers.query(b, "s", limit=2, cursor=first["next_cursor"])
    m.put(0x31000 + 0x8D, b"\x03")
    with pytest.raises(ValueError, match="changed"):
        offers.query(b, "s", limit=1, cursor=first["next_cursor"])
