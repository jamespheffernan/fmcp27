import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from fm_live_mcp import server


def test_wrapper_forwards_exact_selectors_without_bridge(monkeypatch):
    calls = []
    expected = {"matched_count": 0, "coverage": {"complete_requested_scope": True}}

    def query(*args, **kwargs):
        calls.append((args, kwargs))
        return expected

    monkeypatch.setattr(server.saved_transfer_offers, "find_offers", query)
    monkeypatch.setattr(server, "bridge", SimpleNamespace())
    assert (
        server.fm_find_saved_transfer_offers(
            "career.fm", "a" * 64, person_index=55949, team_index=545, offset=2, limit=3
        )
        == expected
    )
    assert calls == [
        (
            ("career.fm",),
            {
                "expected_snapshot_id": "a" * 64,
                "person_index": 55949,
                "team_index": 545,
                "offset": 2,
                "limit": 3,
            },
        )
    ]


def test_public_stdio_registration_and_strict_inputs():
    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "fm_live_mcp.server"],
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                tool = next(
                    t for t in tools if t.name == "fm_find_saved_transfer_offers"
                )
                assert tool.annotations.readOnlyHint is True
                assert tool.annotations.destructiveHint is False
                assert tool.annotations.openWorldHint is False
                assert set(tool.inputSchema["required"]) == {
                    "filename",
                    "expected_snapshot_id",
                }
                assert tool.inputSchema["properties"]["limit"]["maximum"] == 500
                base = {"filename": "x.fm", "expected_snapshot_id": "a" * 64}
                for patch in (
                    {},
                    {"person_index": True},
                    {"person_index": -1},
                    {"person_index": 2**31},
                    {"team_index": "545"},
                    {"person_index": 1, "limit": 0},
                    {"person_index": 1, "offset": False},
                    {"person_index": 1, "expected_snapshot_id": "stale"},
                ):
                    result = await client.call_tool(tool.name, {**base, **patch})
                    assert result.isError, patch

    asyncio.run(check())
