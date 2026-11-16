#!/usr/bin/env python3
"""Install the Mac download in a clean place and check that it works.

    python3 scripts/test_package_mac.py [path/to/FMCP27-mac.zip]

What it does, in a new temporary folder that it removes at the end:

1. Unzips the package and marks every file as a browser download (the
   com.apple.quarantine attribute), which is what Safari and Archive Utility
   leave on a player's Mac.
2. Runs install.sh the way the README says, with HOME set to an empty folder
   and PATH reduced to the system directories, so the installer has to fetch
   uv and Python itself. Checks that the installed copy has no quarantine
   mark, that every binary passes its signature check, and that the installer
   printed the launch line.
3. Starts a stand-in for the game (native/fmcp_attach_target.c, signed with the
   game's two dyld entitlements, inside a .app bundle) through the launch line
   as Steam runs it -- the printed line split into arguments and started directly,
   with no shell, so a "~" in it would fail as it does in Steam (OS Error 260) -- and reads its memory with the installed fm_live_helper and fm_fast_reader
   with the route forced to "injected", which never calls task_for_pid.
4. Starts the installed MCP server (fmcp27-mcp), and over stdio: initialize,
   tools/list, and a call of fm_status. If Football Manager 27 is running it
   also calls fm_attach and fm_get_save, and reports which attach route served
   them.

Environment:
  FMCP27_TEST_DIR         where the temporary folder is made (default: the
                          external work volume if mounted, else $TMPDIR)
  FMCP27_TEST_KEEP=1      keep the folder
  FMCP27_TEST_REQUIRE_SIP=1
                          fail unless System Integrity Protection is at its default
                          and task_for_pid is refused on the stand-in: the run then
                          proves the package on a Mac whose security was not relaxed
  FMCP27_TEST_HELPER, FMCP27_TEST_FAST_READER
                          an fm_live_helper and an fm_fast_reader to use for step 4
                          instead of the installed ones, with the route forced to
                          "injected". The in-game library answers only programs that
                          sit beside the copy the game loaded, so this is how to check
                          the injected route against a game that was started from
                          another install.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
QUARANTINE = "0083;{:x};Safari;".format(int(time.time()))

MCP_CLIENT = r'''
import asyncio, json, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command=sys.argv[1], args=[], env=dict(os.environ))
    out = {}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            out["server"] = init.serverInfo.name
            tools = (await session.list_tools()).tools
            out["tools"] = len(tools)
            names = {tool.name for tool in tools}
            out["write_tools"] = sorted(n for n in names if "set_" in n or "write" in n)

            async def call(name, **arguments):
                result = await session.call_tool(name, arguments)
                text = "".join(getattr(part, "text", "") for part in result.content)
                return result.isError, text

            failed, text = await call("fm_status")
            out["fm_status_ok"] = not failed
            status = json.loads(text) if not failed else {}
            games = status.get("games") or status.get("processes") or []
            out["game_running"] = bool(games)
            out["game_build"] = (status.get("game_build") or {}).get("state")
            if games:
                failed, text = await call("fm_attach")
                out["fm_attach_ok"] = not failed
                if failed:
                    out["fm_attach_error"] = text[:400]
                else:
                    session_id = json.loads(text).get("session_id")
                    failed, text = await call("fm_get_save", session_id=session_id)
                    out["fm_get_save_ok"] = not failed
                    out["fm_get_save"] = text[:300]
    print(json.dumps(out))

asyncio.run(main())
'''


def run(cmd, **kwargs):
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(map(str, cmd))}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def step(text):
    print(f"-- {text}", flush=True)


def has_quarantine(folder: Path) -> list[str]:
    out = subprocess.run(["/usr/bin/xattr", "-r", folder], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if "com.apple.quarantine" in line]


def main() -> int:
    package = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "site/public/download/FMCP27-mac.zip").resolve()
    if not package.is_file():
        raise SystemExit(f"no package at {package}; run sh scripts/package_mac.sh")
    external = Path("/Volumes/4TB Private/Offloaded/Agent Work")
    base = Path(os.environ.get("FMCP27_TEST_DIR") or (external if external.is_dir() else tempfile.gettempdir()))
    work = Path(tempfile.mkdtemp(prefix="fmcp27-package-test.", dir=base))
    target = None
    try:
        home = work / "home"
        downloads = home / "Downloads"
        downloads.mkdir(parents=True)

        sip = subprocess.run(["/usr/bin/csrutil", "status"], capture_output=True, text=True).stdout.strip()
        sip_on = sip.splitlines()[:1] == ["System Integrity Protection status: enabled."]
        step(f"this Mac: macOS {run(['/usr/bin/sw_vers', '-productVersion']).strip()}, {os.uname().machine}; "
             f"{sip.splitlines()[0] if sip else 'csrutil gave no answer'}")
        require_sip = os.environ.get("FMCP27_TEST_REQUIRE_SIP") == "1"
        assert sip_on or not require_sip, f"FMCP27_TEST_REQUIRE_SIP=1 but SIP is not at its default:\n{sip}"

        step(f"unzip {package.name} ({package.stat().st_size:,} bytes) as a quarantined download")
        run(["/usr/bin/ditto", "-x", "-k", package, downloads])
        run(["/usr/bin/xattr", "-r", "-w", "com.apple.quarantine", QUARANTINE, downloads / "FMCP27"])
        assert has_quarantine(downloads / "FMCP27"), "the test could not set the quarantine mark"

        step("install.sh with an empty HOME and the system PATH only")
        clean_env = {"HOME": str(home), "PATH": SYSTEM_PATH, "FMCP27_NO_CLIPBOARD": "1"}
        started = time.time()
        printed = run(["/bin/sh", str(downloads / "FMCP27/install.sh")], env=clean_env)
        dest = home / "FMCP27"
        print(f"   installed in {time.time() - started:.0f} s; "
              f"{int(run(['/usr/bin/du', '-sk', dest]).split()[0]) // 1024} MB at {dest}")
        launch_lines = [line.strip() for line in printed.splitlines() if line.strip().endswith("%command%")]
        assert len(launch_lines) == 1, printed
        launch_argv = shlex.split(launch_lines[0])[:-1]
        assert launch_argv == [str(dest / "fm_launch.sh")], f"not the full path: {launch_lines[0]}"
        assert not has_quarantine(dest), "quarantine left on the installed copy"
        assert (dest / "bin/uv").is_file(), "the installer did not fetch its own uv"
        for binary in sorted((dest / "build").iterdir()):
            run(["/usr/bin/codesign", "--verify", "--strict", binary])
        print("   launch line printed; no quarantine mark; all signatures verify")

        step("launch a stand-in game through the launch line as Steam runs it")
        app = work / "Stand In.app"
        macos = app / "Contents/MacOS"
        macos.mkdir(parents=True)
        (app / "Contents/Info.plist").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
            "<key>CFBundleExecutable</key><string>Stand In</string></dict></plist>\n")
        binary = macos / "Stand In"
        run(["/usr/bin/clang", "-std=c11", "-O2", "-o", binary, ROOT / "native/fmcp_attach_target.c"])
        run(["/usr/bin/codesign", "--force", "--sign", "-", "--options", "runtime",
             "--entitlements", ROOT / "native/fmcp_attach_target.entitlements", binary])
        target = subprocess.Popen([*launch_argv, str(app), "8"],
                                  env={"HOME": str(home), "PATH": SYSTEM_PATH},
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        ready = target.stdout.readline().split()
        assert ready and ready[0] == "READY", f"the stand-in did not start: {ready}"
        pid, address = int(ready[1]), int(ready[2])
        injected = {**os.environ, "FMCP_ATTACH_ROUTE": "injected"}
        data = json.loads(run([dest / "build/fm_live_helper", "read-bytes", "--pid", str(pid),
                               "--addr", hex(address + 1000), "--read-len", "32"], env=injected))
        assert list(bytes.fromhex(data["hex"])) == [((1000 + i) * 131 + 7) & 0xFF for i in range(32)]
        probe = json.loads(run([dest / "build/fm_live_helper", "probe", "--pid", str(pid)], env=injected))
        assert probe["attach_ok"] is True and probe["regions"]["readable"] > 0
        doctor = run([dest / "fmcp27-doctor", "--pid", str(pid)], env={"HOME": str(home), "PATH": SYSTEM_PATH})
        assert "route=injected" in doctor, doctor
        print("   library loaded by the launch line; fm_live_helper and fm_fast_reader read over the injected route")
        # The older route on the same process. With SIP at its default it must be refused: the
        # stand-in, like the game, has the hardened runtime and no get-task-allow.
        old = subprocess.run([dest / "build/fm_live_helper", "probe", "--pid", str(pid)],
                             env={**os.environ, "FMCP_ATTACH_ROUTE": "task-for-pid"}, capture_output=True, text=True)
        try:
            old_ok = old.returncode == 0 and json.loads(old.stdout).get("attach_ok") is True
        except ValueError:
            old_ok = False
        print("   task_for_pid on the same process: "
              + ("worked, so this Mac's SIP is relaxed" if old_ok else
                 f"refused ({' '.join((old.stdout or old.stderr).split())[:160]})"))
        assert not (old_ok and require_sip), "task_for_pid worked although SIP reports enabled"
        target.stdin.close()
        target.wait(timeout=10)
        target = None

        step("MCP server: initialize, tools/list, fm_status")
        env = {**os.environ, "FMCP_CACHE_DIR": str(work / "cache"),
               "FM_LIVE_OBSERVED_STORE": str(work / "observed")}
        readers = os.environ.get("FMCP27_TEST_HELPER") and os.environ.get("FMCP27_TEST_FAST_READER")
        if readers:
            env.update(FM_LIVE_HELPER=os.environ["FMCP27_TEST_HELPER"],
                       FM_FAST_READER=os.environ["FMCP27_TEST_FAST_READER"], FMCP_ATTACH_ROUTE="injected")
        out = json.loads(run([dest / ".venv/bin/python", "-c", MCP_CLIENT, dest / "fmcp27-mcp"],
                             env=env, timeout=600).strip().splitlines()[-1])
        assert out["fm_status_ok"] and out["tools"] > 100, out
        assert out["write_tools"] == [], f"the free package must not offer edits: {out['write_tools']}"
        print(f"   server {out['server']!r}: {out['tools']} tools, none of them edits; fm_status answered")
        if out["game_running"]:
            route = "injected (forced)" if readers else "auto"
            assert out.get("fm_attach_ok"), out
            assert out.get("fm_get_save_ok"), out
            print(f"   Football Manager is running: fm_attach and fm_get_save answered, attach route {route}")
            print(f"   fm_get_save: {out['fm_get_save'][:160]}")
        else:
            print("   Football Manager is not running: fm_attach was not tried")
        print("PASS")
        return 0
    finally:
        if target is not None:
            target.kill()
        if os.environ.get("FMCP27_TEST_KEEP") == "1":
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
