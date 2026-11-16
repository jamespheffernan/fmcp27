"""On the rented Mac, with Football Manager 27 running and a save loaded: what an
assistant gets from the installed package.

    ~/FMCP27/.venv/bin/python real_game_check.py

Run it inside the desktop session (the in-game library registers its Mach service in
that session, so a plain SSH shell cannot look it up). It starts ~/FMCP27/fmcp27-mcp
with an empty cache, the way a first run on a new Mac has it, and prints one JSON
object: the Mac's SIP state, the game's signature flags, fm_status, fm_attach with the
route that served it, fm_get_save, and the first whole-save query with its time.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HOME = Path.home()
SERVER = HOME / "FMCP27/fmcp27-mcp"


def text(cmd):
    done = subprocess.run(cmd, capture_output=True, text=True)
    return (done.stdout + done.stderr).strip()


async def main():
    out = {"sip": text(["/usr/bin/csrutil", "status"]).splitlines()[:1],
           "macos": text(["/usr/bin/sw_vers", "-productVersion"])}
    pid = text(["/usr/bin/pgrep", "-f", "Football Manager 27/fm.app/Contents/MacOS/"]).split()
    out["game_pids"] = pid
    if pid:
        exe = text(["/bin/ps", "-o", "comm=", "-p", pid[0]])
        out["game_executable"] = exe
        out["game_signature"] = [line for line in text(["/usr/bin/codesign", "-dvv", exe]).splitlines()
                                 if line.startswith(("flags", "Authority=Developer ID Application", "CodeDirectory"))]
        out["game_entitlements"] = sorted(
            key for key in ("allow-dyld-environment-variables", "disable-library-validation", "get-task-allow")
            if key in text(["/usr/bin/codesign", "-d", "--entitlements", "-", exe]))
        out["doctor"] = text([str(HOME / "FMCP27/fmcp27-doctor")]).splitlines()[:6]
        helper = str(HOME / "FMCP27/build/fm_live_helper")
        for route in ("injected", "task-for-pid"):
            done = subprocess.run([helper, "probe", "--pid", pid[0]], capture_output=True, text=True,
                                  env={**os.environ, "FMCP_ATTACH_ROUTE": route})
            out[f"probe_{route}"] = " ".join(done.stdout.split())[:220]
    cache = tempfile.mkdtemp(prefix="fmcp27-fresh-cache.")
    env = {**os.environ, "FMCP_CACHE_DIR": cache, "FM_LIVE_OBSERVED_STORE": cache + "/observed"}
    params = StdioServerParameters(command=str(SERVER), args=[], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            out["tools"] = len((await session.list_tools()).tools)

            async def call(name, **arguments):
                started = time.time()
                result = await session.call_tool(name, arguments)
                body = "".join(getattr(part, "text", "") for part in result.content)
                return result.isError, body, round(time.time() - started, 1)

            failed, body, seconds = await call("fm_status")
            status = {} if failed else json.loads(body)
            out["fm_status"] = {"ok": not failed, "version": status.get("version"),
                                "game_build": status.get("game_build"), "seconds": seconds}
            failed, body, seconds = await call("fm_attach")
            out["fm_attach"] = {"ok": not failed, "seconds": seconds, "answer": body[:600]}
            if not failed:
                session_id = json.loads(body).get("session_id")
                failed, body, seconds = await call("fm_get_save", session_id=session_id)
                out["fm_get_save"] = {"ok": not failed, "seconds": seconds, "answer": body[:500]}
                failed, body, seconds = await call(
                    "fm_db_query", session_id=session_id, max_rows=5,
                    sql="SELECT name, age, club, position FROM player_view "
                        "WHERE club LIKE '%Newcastle%' ORDER BY name LIMIT 5")
                out["first_whole_save_query"] = {"ok": not failed, "seconds": seconds, "answer": body[:900]}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
