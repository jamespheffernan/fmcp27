# The injected attach route

FMCP reads a running Football Manager 27 career from live process memory. The
existing route attaches with `task_for_pid`, which the kernel allows only on a
Mac whose System Integrity Protection has been relaxed. This route removes that
requirement: a small library is loaded into the game at launch and serves the
reader's memory reads over a Mach channel, so the reader never calls
`task_for_pid`. The owner approved this route on 2026-11-12 ("use an injected
library at launch as the attach route for distribution"), which reverses, for
this one library, the project's earlier rule that no FMCP code runs inside the
game.

## What runs in the game, and what it cannot do

`build/libfmcp_attach.dylib` (source `native/fmcp_attach_lib.c`) is the only FMCP
code inside the game. A constructor starts one detached thread on its own 512 KiB
stack and returns. The thread registers a Mach bootstrap service named
`com.fmcp27.attach.<pid>`, blocks in `mach_msg`, and wakes only when a reader
sends a batch. It then reads the requested bytes **from its own address space**
with `mach_vm_read_overwrite(mach_task_self(), …)` and replies. It never:

- writes to game memory, or changes any page's protection (the only Mach calls
  are `mach_vm_read_overwrite` and `mach_vm_region`, both read-only);
- interposes a symbol, installs a hook, or patches code;
- allocates on, or runs on, a game worker thread — reads happen on the library's
  own thread, and the kernel copies bytes, never a game thread;
- creates a file or writes a log;
- spends CPU while no reader is connected (it blocks in `mach_msg`).

The channel exposes exactly two operations to a reader: read a list of
(address, length) items, and list the memory regions. A reader cannot make the
library write, allocate in the game, create threads, or do anything but read
bytes and enumerate regions. The paid write tier is a separate, later piece and
shares none of this code.

### It cannot crash or stall the game

A read of an unmapped or unreadable address returns `KERN_INVALID_ADDRESS`
from the kernel; the library turns that into a per-item status and keeps serving.
It never dereferences a game pointer itself, so a bad request from the reader
cannot fault the game. Measured on this machine (Darwin 27): a read of
`0xdead0000` comes back as item status `bad_address` and the process stays alive
(`tests/test_fmcp_attach.py::test_injected_route_bad_address_is_not_fatal`).
Because the serving thread only ever blocks in `mach_msg` or copies bytes, it
cannot deadlock or stall a game thread.

### Kill switch and scoping

- `FMCP_ATTACH_DISABLE=1` in the environment makes the constructor return at once;
  the library does nothing.
- The library serves only the process whose executable path equals
  `FMCP_ATTACH_TARGET`. A child process that inherits the environment (a crash
  reporter, a helper) stays inert.

## Why the library serves reads instead of handing over a task port

The first design was for the library to send the reader a send right to the
game's own task **read** port, after which the reader's existing `mach_vm_read`
code would work unchanged. On current macOS that is impossible without changing
the game's entitlements. A hardened process's own task ports are *immovable*
(an anti-exfiltration feature): moving or copying `mach_task_self()`'s read port
into a Mach message raises `EXC_GUARD` / `ILLEGAL_MOVE` and kills the process.
Reproduced here directly — the test target died with
`EXC_GUARD … ILLEGAL_MOVE on mach port` the moment the library tried to send its
read port, with both `MOVE_SEND` and `COPY_SEND`. The game has the hardened
runtime (`codesign` flags `0x10000`), so its self ports are immovable, and we
cannot add `com.apple.security.cs.disable-immovable-task-ports` to a binary we do
not sign. So the library serves reads itself; that path never transfers a task
port and cannot hit the guard.

### Throughput

The library reads its own memory very fast and the Mach channel is not the
bottleneck. Measured against the 256 MiB test target on this machine:

| path | 100,000 × 8 B (batches of 10,000) | 16 KiB pages | 1 MiB reads |
|---|---|---|---|
| library self-read, no IPC (ceiling) | 1,986,000 items/s | — | 10,474 MiB/s |
| injected channel, C client | 1,553,000 items/s | 5,170 MiB/s | 6,340 MiB/s |
| **injected channel, full Python reader** | **184,000 items/s** | — | **1,363 MiB/s** |
| present reader (`task_for_pid` + pipe, Python) | 138,000 items/s | — | 1,203 MiB/s |

The full Python path over the injected channel matches — slightly beats — the
present `task_for_pid` path, because the reader's cost is Python plus the pipe,
not the Mach hop. The channel's own ceiling (1.5 M items/s) is an order of
magnitude above what the Python reader consumes, so the injected route adds no
meaningful overhead. (`scripts/bench_fast_reader.py` measures the present reader
against the live game; the numbers above come from the self-built target so the
two transports could be compared without the game.)

## How the owner tries it

1. Build the pieces (already built here; the launcher checks):
   ```
   sh scripts/build_fast_reader.sh     # reader, gains the injected route
   sh scripts/build_attach_lib.sh      # build/libfmcp_attach.dylib (universal, ad-hoc)
   ```
2. In Steam, Football Manager 27 → Properties → General → Launch Options, set:
   ```
   /ABSOLUTE/PATH/TO/scripts/fm_launch.sh %command%
   ```
   Steam passes the `.app` bundle as `%command%`; the launcher resolves it to the
   inner executable, sets `DYLD_INSERT_LIBRARIES` and `FMCP_ATTACH_TARGET`, and
   execs it. Launch the game from Steam as usual.
3. Confirm the library is loaded (works on default SIP, uses no `task_for_pid`):
   ```
   PYTHONPATH=. python scripts/fm_attach_doctor.py
   ```
   It prints `attach library loaded … route=injected` when the channel is live,
   or names the launcher fix when it is not.
4. The reader uses the injected channel automatically. `route="auto"` (the
   default) prefers it and falls back to `task_for_pid`; `FMCP_ATTACH_ROUTE` or
   `LiveMemory(route=…)` can force `injected` or `task-for-pid`.

### How the owner removes it

Delete the one Steam launch option (or clear `DYLD_INSERT_LIBRARIES` in it). The
game then launches normally and loads nothing of FMCP's. Nothing in the game
bundle or Steam's files is ever modified, so there is nothing else to undo.
`FMCP_ATTACH_DISABLE=1` turns the library off without touching the launch option.

## Privacy and who can connect

The library answers only a peer whose Mach audit token shows:

- the game's own effective user id (no other user on the machine can connect);
- a valid code signature (`csops` `CS_VALID`);
- an executable in the **same directory as the library** — the FMCP build
  directory — so only an FMCP reader installed beside it is served.

The channel carries no data except the bytes a reader explicitly requests, and
the reader verifies the service names the pid it asked for. A version number
(`FMCP_ATTACH_PROTOCOL_VERSION`) is checked on both sides; a mismatched library
or reader is refused rather than misread.

## Anti-cheat and integrity: what was found

- Football Manager 27 is a single-player Unity/IL2CPP game (`UnityPlayer.dylib`,
  `GameAssembly.dylib`). It bundles the Epic Online Services SDK
  (`libEOSSDK-Mac-Shipping.dylib`) for online services. No dedicated anti-cheat
  bootstrapper (EasyAntiCheat, BattlEye, a kernel component) is present in the
  bundle.
- Steam itself does not validate the game's loaded libraries; Steam's own overlay
  is injected into every game the same way (`gameoverlayrenderer.dylib` via
  `DYLD_INSERT_LIBRARIES`), so a dyld insertion is ordinary for a Steam title.
- `GameAssembly.dylib` imports `_dyld_image_count` / `_dyld_get_image_name` and
  `dlopen`. These are standard IL2CPP/Unity facilities (stack traces, plugin
  loading), but they also mean the game *can* enumerate its own loaded images, in
  which `libfmcp_attach.dylib` would appear by name. I could **not** determine
  whether the game actually inspects that list, reports it, or acts on it. The
  game's main executable and `GameAssembly` import no `csops` / `SecCode` calls
  that would inspect another process's signature.

What this does not tell us: whether a future game update adds an integrity check,
and whether EOS's optional anti-cheat is ever enabled for this title. Treat the
library name as visible to the game and keep the write tier separate.

## What is unverified, and how to verify it

These claims could not be settled on this machine (its SIP is custom) or without
the real game. All three were settled on a rented default-SIP Mac, as the next two
paragraphs record.

**Checked on a default-SIP Mac, 13 November 2026, with a stand-in for the game.** A
rented EC2 `mac2.metal` (M1, macOS 27.2, `csrutil status`: enabled, Gatekeeper
assessments enabled, Developer mode disabled, no boot-args; `scripts/mac_vm/mac.sh`)
ran `FMCP27_TEST_REQUIRE_SIP=1 scripts/test_package_mac.py` on the Developer ID signed,
notarized download built from `83e4269523` (reader 0.169.0): PASS. The quarantined zip
installed into an empty home; the launch line loaded the library into a hardened-runtime
target carrying the game's two entitlements; `fm_live_helper`, `fm_fast_reader` and the
doctor read it with `route=injected`; `task_for_pid` on that same process was refused
(`task_for_pid_failed`, Mach code 5); the MCP server listed 196 tools and answered
`fm_status`. The same held with the download installed in the account's real home and the
target under `/Users/Shared/Steam Library/steamapps/common/Football Manager 27/fm.app`,
a library outside the home folder, and the doctor named the fix when the target was
started without the launcher. The download rebuilt from `90d7c604d5` (reader 0.170.0,
sha256 `4a40b04d…c89f`, the fix message and the quiet installer) passed the same two runs
there, installed over the earlier copy.

**Checked on a default-SIP Mac, 14 November 2026, with the real game.** A second machine
on the same rented host (macOS 27.2, `csrutil status`: enabled), the 0.170.0 download
installed in the account's home, Football Manager 27 build 27.0.1.2503222 installed by
Steam under the owner's sign-in and started from Steam with the launch option
`/Users/ec2-user/FMCP27/fm_launch.sh %command%`. `scripts/mac_vm/mac.sh real-game`
(`real_game_check.py`, run in the desktop session) reported: the doctor `attach library
loaded … route=injected`; the helper's probe over the injected route ok (3,854 regions
seen); the probe forced to `task-for-pid` refused (`task_for_pid_failed`, Mach code 5);
the game signed by Sega's Developer ID with the hardened runtime and the two entitlements
below; the MCP server listed 196 tools, `fm_status` gave the build as `mapped` with 2,600
of 2,607 addresses and no tool unavailable (two partial: `fm_get_current_match_frame`,
`fm_get_retained_cross_events`); `fm_attach` ok; `fm_get_save` named the loaded career
("Cesar Jules - Newcastle", game date 2031-01-14); the first whole-save query on a new
cache answered in 17.1 s. One fault was found on the way: the installer, the README and
the site gave the launch option as `~/FMCP27/fm_launch.sh %command%`, and Steam starts the
launch option itself with no shell, so the `~` is not expanded and the game fails to
start with "OS Error 260". The stand-in test had started the line through `/bin/sh -c`,
which hid this. The installer now prints the full path and the test starts the printed
line directly. The download rebuilt with that fix (commit `7409240010`, reader 0.173.0,
sha256 `c0f8777a…3cb5`, notarized) was then put through both stages on the same Mac the
same afternoon: the stand-in test passed with SIP required, and, installed over the
earlier copy with the game started from Steam by the line the installer printed,
`real-game` gave the same answers (injected route, `task_for_pid` refused, 200 tools, the
career named, first whole-save query in 16.9 s). For a later rented run: `scripts/mac_vm/mac.sh up`, `prepare`,
`desktop --set-password` (`signin` if the Mac's sign-in screen rejects the password; the
owner signs in to Steam, installs the game, sets the launch option and loads a save), then
`real-game`. Steam's Mac app is Intel-only and needs Rosetta there.

1. **That `task_for_pid` fails on a default-SIP Mac** (the reason this route
   exists). Shown on the rented Mac against the stand-in and, on 14 November 2026,
   against the real game. This machine's SIP is relaxed, so `task_for_pid` succeeds here and
   cannot demonstrate the failure. On a Mac with default SIP, with the game
   running and the library **not** loaded:
   ```
   PYTHONPATH=. FMCP_ATTACH_ROUTE=task-for-pid python -c \
     "from fm_live_mcp.fmdb.memory import LiveMemory, find_fm_process as f; p=f(); LiveMemory(p.pid, expected_executable=p.executable)"
   ```
   Expect an `attach_failed` error. Then launch via `scripts/fm_launch.sh`, run
   `python scripts/fm_attach_doctor.py`, and expect `route=injected`.
2. **That the library loads into the real game.** The game's entitlements allow it
   (`codesign -d --entitlements - "<fm.app>"` shows
   `allow-dyld-environment-variables` and `disable-library-validation`), and an
   ad-hoc signature is accepted because library validation is disabled; confirmed
   against a target carrying the same two entitlements and, on 14 November 2026,
   against the game on a default-SIP Mac. Verify with the doctor, or:
   ```
   build/fm_live_helper images --pid <game pid> | grep libfmcp_attach
   ```
3. **That Steam keeps `DYLD_INSERT_LIBRARIES` through launch** (it may re-exec).
   The launch option above is the supported way; confirm with the doctor after a
   real Steam launch. If Steam strips the variable, the wrapper's `exec` of the
   inner executable (which the launcher already does) preserves it. Confirmed on
   14 November 2026: a Steam launch on the default-SIP Mac had the library loaded.

## Files

- `native/fmcp_attach.h` — the wire protocol and policy, shared by both sides.
- `native/fmcp_attach_lib.c` — the in-game library.
- `native/fmcp_attach_client.h` — the reader side (used by `fm_fast_reader`).
- `native/fmcp_attach_target.c`, `…target.entitlements` — the signed test target.
- `native/fm_fast_reader.c` — the reader, with `--route auto|injected|task-for-pid`.
- `native/fm_live_helper_attach.h` — the same route for `fm_live_helper` (the Bridge's reader:
  attach check, plugin image, scans, entity indexes, the read stream). Reads use the channel's
  READV and the region walk uses its REGIONS list, so the library and its protocol are unchanged.
  The region list has no share mode; the helper takes that one field from
  `proc_pidinfo(PROC_PIDREGIONINFO)`, which needs the same user and no task port, and counts a
  region as private when the kernel does not answer. The loaded game plugin is found by walking
  the executable regions for a bundle header; its path comes from `proc_regionfilename`, or from
  the game's bundle layout when the UUID in memory equals the UUID of that file on disk.
  `FMCP_ATTACH_ROUTE` selects the route as for `fm_fast_reader`; `FMCP_ATTACH_NO_PROC_INFO=1`
  acts as if the kernel refused both `proc_info` calls. Checked on 13 November 2026 against the
  running game (27.0.1, library loaded by the Steam launch option) with the route forced to
  `injected`: `images`, `probe` and `read-bytes` return what the `task_for_pid` route returns,
  with and without `proc_info`; a read through the stream costs about 34 µs against 15 µs.
  Until this header existed the helper called `task_for_pid` unconditionally, so every Bridge
  tool needed relaxed SIP even with the library loaded.
- `fm_live_mcp/fmdb/memory.py` — `LiveMemory(route=…)`, `.route`, the fix message.
- `scripts/build_attach_lib.sh`, `scripts/fm_launch.sh`, `scripts/fm_attach_doctor.py`.
- `tests/test_fmcp_attach.py`, `tests/test_fmcp_attach_route.py`, `tests/test_fm_live_helper_attach.py`.
