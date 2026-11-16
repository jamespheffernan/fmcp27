"""Exercise the installed stdio MCP against the open game; save local evidence."""
import argparse
import asyncio
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify(args):
    root = Path(__file__).resolve().parent.parent
    evidence = {"transport": "stdio", "steps": []}
    params = StdioServerParameters(command="/bin/sh", args=[str(root / "scripts/run_mcp.sh")])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            evidence["tools"] = [t.name for t in (await client.list_tools()).tools]

            async def call(name, arguments):
                response = await client.call_tool(name, arguments)
                data = response.structuredContent or {"content": [c.model_dump() for c in response.content]}
                evidence["steps"].append({"tool": name, "error": response.isError, "result": data})
                if response.isError:
                    raise RuntimeError(str(data))
                return data

            try:
                await call("fm_status", {})
                attached = await call("fm_attach", {})
                session = attached["session_id"]
                cursor = None
                found = []
                for page in range(args.pages):
                    scan = await call("fm_search_text", {
                        "session_id": session, "texts": args.texts, "max_mib": args.mib,
                        "max_matches": 20, "cursor": cursor,
                    })
                    print(f"Page {page + 1}: {len(scan['matches'])} hits; {scan['stop_reason']}", flush=True)
                    found.extend(scan["matches"])
                    cursor = scan["next_cursor"]
                    if found or not cursor:
                        break
                if found:
                    await call("fm_read_anchor", {"session_id": session, "anchor_id": found[0]["anchor_id"]})
                evidence["live_text_readback_verified"] = bool(found)
                await call("fm_detach", {})
                # Confirm cached session cannot be used after detachment.
                rejected = await client.call_tool("fm_search_text", {"session_id": session, "texts": args.texts})
                evidence["detached_session_rejected"] = rejected.isError
                if not rejected.isError:
                    raise RuntimeError("Detached session was accepted")
            finally:
                path = root / "evidence/live-mcp.json"
                path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps(evidence, indent=2) + "\n")
                print(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--texts", nargs="+", default=["Woltemade", "Wirtz"])
    parser.add_argument("--pages", type=int, choices=range(1, 17), default=8)
    parser.add_argument("--mib", type=int, choices=range(1, 1025), default=512)
    asyncio.run(verify(parser.parse_args()))

