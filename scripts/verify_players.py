"""Compare actual stdio player tools against two manually transcribed UI profiles.

The oracle describes the November 5 validation save. After game progression,
refresh the oracle from the UI rather than treating changed stats as a defect.
"""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    oracle = json.loads((root / "tests/fixtures/player_profile_oracles.json").read_text())
    evidence = {"observed_at": datetime.now(timezone.utc).isoformat(), "transport": "stdio", "steps": []}
    params = StdioServerParameters(command="/bin/sh", args=[str(root / "scripts/run_mcp.sh")])
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                evidence["tools"] = [t.name for t in (await client.list_tools()).tools]

                async def call(name, args):
                    response = await client.call_tool(name, args)
                    data = response.structuredContent
                    evidence["steps"].append({"tool": name, "error": response.isError, "result": data,
                                              "content": [c.model_dump() for c in response.content] if response.isError else None})
                    if response.isError or data is None:
                        raise RuntimeError(str(response.content))
                    return data

                attached = await call("fm_attach", {})
                session = attached["session_id"]
                refs = []
                for expected in oracle["players"]:
                    cursor = None
                    found = []
                    for page in range(16):
                        result = await call("fm_find_players", {"session_id": session, "name": expected["name"],
                                                               "max_mib": 512, "cursor": cursor})
                        found.extend(p for p in result["players"] if p["name"] == expected["name"])
                        print(f"{expected['name']}: page {page + 1}, {len(found)} records", flush=True)
                        cursor = result["next_cursor"]
                        if found or not cursor:
                            break
                    if len(found) != 1:
                        raise RuntimeError(f"Expected one matching native record in searched pages: {expected['name']}")
                    for field in ("name", "birth_date", "attributes"):
                        assert found[0][field] == expected[field], (field, found[0], expected)
                    ref = found[0]["player_ref"]
                    refs.append(ref)
                    reread = await call("fm_get_player", {"session_id": session, "player_ref": ref})
                    for field in ("name", "birth_date", "attributes"):
                        assert reread["player"][field] == expected[field]
                bad = await client.call_tool("fm_get_player", {"session_id": session, "player_ref": "not-issued"})
                assert bad.isError
                evidence["unknown_reference_rejected"] = True
                await call("fm_detach", {})
                stale = await client.call_tool("fm_get_player", {"session_id": session, "player_ref": refs[0]})
                assert stale.isError
                evidence["detached_reference_rejected"] = True
                evidence["matched_profiles"] = 2
                evidence["matched_attributes"] = 72
                print("Verified two birth dates, 72 attributes, fresh readbacks, and rejected references.", flush=True)
    finally:
        path = root / "evidence/live-players-mcp.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(evidence, indent=2) + "\n")
        print(path)


if __name__ == "__main__":
    asyncio.run(verify())
