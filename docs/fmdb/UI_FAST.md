# Fast runtime screens

11 November 2026. Game build 27.0.0.2493426, Newcastle career. `UiHandlerVM` now runs on
C-accelerated machinery, answers are cached by what was asked and validated by what the
computation read, and the inbox lists stored objects and renders text on demand.

Files: `fm_live_mcp/fmdb/ui_fastvm.py`, `native/fm_ui_accel.c` (built by
`scripts/build_ui_accel.sh` to `build/libfm_ui_accel2.dylib`, ABI 2 since round 3), `ui_cache.py` (version 2),
`ui_tools.py` (`tracked`, `inbox`). Scripts: `fmdb_ui_profile.py`, `fmdb_ui_vm_check.py`,
`fmdb_ui_bench.py`, `fmdb_ui_volatile.py`. Tests: `tests/test_fmdb_ui_fast.py`.

## Where the time went (profile, reference emulator)

`scripts/fmdb_ui_profile.py --vm classic`, load average 30, wall seconds, exclusive per mechanism:

| Mechanism | Board confidence, cold 15.7 s | Post-match item, cold 15.2 s | Player status, cold 4.0 s |
|---|---|---|---|
| Emulation, including the Python store hook (0.85 M to 2.7 M calls) | 6.3 | 6.6 | 1.5 |
| Reading live memory in 512 KiB windows (138,511 / 80,816 / 112,655 pages copied) | 5.6 | 0.5 | 0.75 |
| External models in Python | 2.3 (100,810 calls) | 7.4 (910,354 calls; `memcpy` 6.5 s, `bzero` 0.7 s) | 0.9 |
| of which `lsof` per file descriptor (`_fseeko`) | 1.07 | 0.08 | 0.65 |
| Fault handling and `mem_map` | 1.05 | 0.48 | 0.47 |
| Baseline commit and restore | 0.45 | 0.09 | 0.38 |
| Value decoding | 0.02 | 0.08 | 0.01 |

By phase: board confidence is one server computation (`Tcnf`, 131 M instructions, the game's
`TEAM_CONFIDENCE` data builder 0x1DC62F4) plus 71 cheap key reads; a news item spends its
time in the 24 client getters (the body text); a player status is 73 server data keys.
Handler construction is 1 to 40 ms in all three. Language-file reads are one 4 KiB read per
item. The game's history files (`Temporary/*_dt.cmt`) cost 13,166 `fread` calls for the board.

## What the port changed

`UiHandlerVM(...)` returns `ui_fastvm.FastUiHandlerVM` when the library is built.
`FMDB_UI_VM=classic` or `UiHandlerVM.classic(...)` gives the reference class. The subclass
keeps the interface the recipes use (`build`, `transfer`, `get`, `commit`, `_baseline`,
`_restore`, `vm.uc.mem_write`, code hooks), so no recipe changed.

* Unicorn runs in virtual-TLB mode over pools mapped once (code, copied live pages, private
  ranges), as `fastvm.FastVM` does. No page is mapped on its own and no store hook runs:
  copy-on-write is a TLB permission.
* The instruction count and budget, `memcpy`/`memmove`, `memset`, `bzero`, `strlen`,
  `strcmp`, `strncmp`, `memcmp`, `malloc`/`new`, `pthread_self`, the owner thread's TLV
  accessor and the three pool-allocator intercepts run in C. A C model declines anything
  unusual (absent page, refused range, size limit) and the Python model then runs, so stop
  reasons keep their wording.
* A baseline is an immutable snapshot `{page -> shared 4 KiB copy}` in C. `commit()` and
  `_restore()` cost the pages written since the last one; the reference copied the whole
  heap and every dirty page through Python each time.
* Live memory is read 16 KiB around a fault. The board computation copies 23,016 pages
  instead of 138,511.
* The file descriptor of a game file is resolved with `proc_pidfdinfo` (microseconds)
  instead of `lsof` (0.1 to 0.6 s per descriptor).
* The Bridge's pinned-build check ran on every tool call (0.23 s, five subprocesses). It now
  runs once per game process; the load address and plugin cannot change inside one.

Instruction counts are now real in `fast()` mode (`ok (data, server 131189515 insns)`); the
reference reports 0 there.

### Equivalence

`scripts/fmdb_ui_vm_check.py` runs both emulators over the handlers and keys of the sweep:
every buildable factory type and every class the `DATABASE_RECORD` type dispatches to, with
the sweep's bindings, inputs transferred, every client key read through `KeyReader`. Both
read one frozen copy of live memory. It compares class or build error, each input's transfer
status, and per key the status, kind, decoded value, protocol, server keys, stop reason,
failed server keys and random draws. Result: see "Checks" below.

Differences that exist by construction: `limit_instructions` counts per call (the reference
counts per emulation segment); a refused store or load names the 1 KiB block in `detail`;
`CallStats.externals` does not list calls the C models served (`vm.stubbed` counts them).

## Stale pages

Cause: a long-lived emulator copies each live page once, on first use. After minutes the
copies are of different ages, and a pointer read from an old page leads into memory the game
has since reused ("write to shipped code", "call into non-plugin code").

Fix: every copied page carries the generation it was read in. `begin_read()` starts a new
generation (and `reset()` does once the generation is older than 5 s; a reset is the point
where no handler state survives). A page of an older generation counts as absent in the TLB
fill, in the C models and in `vm.read`, so the fault callback reads it again from the game
before anything sees it. `tracked()` calls `begin_read()` for every computation and hands the
emulator the pages it has just re-read for the validity check, so they are not read twice.
The emulator, its page tables and its translated code stay for the life of the save
(`UiSession.vm`); the 15-minute expiry and the per-date emulator are gone for this class.
`refresh_live_memory` (the old retry) now starts a generation: one warm computation instead
of about 15 s.

`vm.reader.read` serves the same copied pages, so what a recipe reads directly is of the same
generation as what the emulated code sees.

What this does not fix: see "What remains".

## Cache: identity plus read set

`ui_cache.ScreenCache` stores an answer under `(save, kind, identity)`, not under a game
date. Each entry has one of two validity modes.

* `forever`: the object does not change. A news item's subject and body are rendered once
  and kept for the life of the save.
* `read_set`: the entry carries the read set of its computation: the live 4 KiB pages it
  touched (from the TLB fills and the C and Python accessors), a 64-bit fingerprint of each as
  the computation saw it, and size and modification time of each game file it read. A later
  call reads exactly those pages again in one batched request (11,000 pages in 60 to 100 ms)
  and serves the stored answer when every fingerprint matches. Otherwise it recomputes, with
  the pages it has just read.

A page the running game keeps changing (a counter beside the data) would invalidate every
entry. Pages seen to change become *watched*: the emulator enters them in the TLB inside an
I/O region, so each load and store on them reaches a C callback with offset and size, and
their read set is kept per 8-byte word. Only the words read are fingerprinted. All other
pages keep the direct path (a read hook on every load costs 5x; this costs nothing
measurable: 0.59 s against 0.53 s with one page in seven watched). The watched set is kept
per game process in `ui2/volatile-pages.json`.

Read sets are addresses: an entry made in another game process never validates and is
removed (`prune_process`).

Random numbers: a computation that drew runs a second time with the copied generator state
reseeded (`ui_vm.two_seed`). Leaves that differ are replaced by "generated at read" and never
stored as values; the generator state words are then left out of the fingerprint, because
the answer has been shown not to depend on them.

A budget stop or failed input is returned and not stored.

The reference emulator records no read sets; with it the tools keep the per-date cache.

## Inbox: list from stored objects, text on demand

`fm_get_inbox` reads the stored `NEWS_ITEM` objects (unique id, class, date +0x88, flags
+0x98) on every call, so read flags are current, and adds each item's subject from the
cache. An item without a cached subject renders the five header keys once. `items=[unid,
...]` adds the full narrative of those items (24 keys), rendered once and kept. Fields that
can change after rendering (response state, deadline, age) are returned under `as_rendered`
with the date of rendering; `fresh=true` with `items` renders again.

One handler per item is kept: construction costs 1 ms warm, and the item is selected by the
`UI_RECORD` the handler is built from. The cost is the item's inputs and getters.

## What remains slow, and why

* Board confidence: the server's `Tcnf` computation is 131 M instructions (about 1.1 s of
  emulation at 120 M instructions per second) and draws random numbers, so storing it costs
  two computations (two-seed rule).
* ~~Three allocators of the plugin keep free lists in game memory that no intercept covers.~~
  Fixed in round 3, see "Free lists" below.
* A first inbox listing renders one header per item (10 to 100 ms each).

## Free lists (round 3, `r3/uispeed`)

The plugin pops nodes from three game free lists with inlined code (`ldr xR, [head]; cbz xR,
slow; ldr x9, [xR]; str x9, [head]`) and through the generic pool function 0x43569F8 (push
0x4356AA0). `ui_vm.FREE_LIST_SITES` names the eleven places: eight inline pops and pushes
(bag nodes, pool 0x56A4DF8: 0x43F8374, 0x43F70C4; typed values, pool 0x56A8A18: 0x4404690,
0x4409618, 0x4404494, push 0x44094DC; pool 0x56B1328: 0x44042E0, 0x43EA324, push 0x43EA1F0)
and the two function entries. A pop gives a zeroed VM-heap block of the pool's element size
(u32 at pool+0x12C: 16, 24, 24 and 32 bytes on the running game; the pools' counting flag
+0x128 and zeroing flag +0x13C are 0), a push is dropped, and execution resumes after the
skipped stores with the scratch registers as those instructions leave them for that block
(`x9 = 0`, the `adrp` page). The models run in C (`fm_ui_add_site`, ABI 2 of the library, now
`build/libfm_ui_accel2.dylib`) and in Python for the reference emulator. A site is installed
only when the shipped bytes at its address are the recorded ones, so another game build gets
no model at a wrong address. The four heads (plugin+0x56A4E90, +0x56A8AB0, +0x56B13C0,
+0x56A4D48) are left out of every fingerprint and their pages are always read by word.
`FMDB_UI_FREE_LISTS=0` turns the models off (`=name,name` models only those sites).

Same answers, on one frozen copy of live memory (`scripts/fmdb_ui_freelist_check.py`, load 9
to 12, 13 December 2030):

* every shaped screen tool through the function behind the MCP tool (21 tools, models on
  against off): 21 equal (`fm_get_scouting` stops at the same `null or low pointer
  dereference 0xc2c80000` both ways);
* every handler of the sweep (`fmdb_ui_vm_check.py` with the models off as the reference):
  150 handlers, 5,582 cells, 11 different in 4 handlers, all of them the allocation address
  showing through. 4 are the `raw` bytes of `variant nesting too deep` leaves (node addresses:
  game heap against VM heap; the decoded value is the same). 7 are COMPETITION keys whose
  answer depends on node addresses: `ClubsTopManagerRep` breaks a tie between two managers of
  reputation 18 differently, `RoundUpJournalist` and `RoundUpMediaSource` pick another person,
  and three transfer-window keys draw 38 random numbers with the models (0 without) for the
  same value. The site groups were switched on one at a time: the COMPETITION keys follow
  `pool_get`/`pool_put`, the list leaves the typed-value pools. Control runs with both sides
  on, and with both off, have 0 differences in the same 4 handlers, so the runs are
  deterministic and the 11 cells come from the models. In the game these answers depend on
  which free node the game's own allocator hands out at that moment.
* `scripts/fmdb_ui_order_check.py --players 20` (frozen memory, two read orders): 5,894 leaves,
  0 different. `tests/test_fmdb_ui_stability_live.py`: 1 passed. Offline:
  `tests/test_fmdb_ui_freelists.py` (9: each site kind on both emulators, the byte check, the
  head word left out of the fingerprint) and `tests/test_fmdb_ui_volatile_words.py` (3).

## The volatile-word rule

With the free lists modelled, the misses that remained (`scripts/fmdb_ui_volatile.py`, rounds
8 s and 60 s apart) came from one word: a u32 in a heap object that steps about once a second
(0x...55fe, 0x...55ff, 0x...5601), read by the typed-value accessors of every handler
(0x4406e70, 0x44099d8, 0x44071b4, 0x4409490). Its address moves when the object is reallocated.

A read set now keeps the words it read on watched pages (`ReadSet.words`), so a failed check
names exactly the words that changed when every changed page is read by word. The answer is
computed again from the new bytes anyway; when it equals the stored one (timings and cache
bookkeeping apart, `ui_tools.same_answer`), those words are shown not to decide this answer
and are left out of its fingerprint from then on (`validity.ignored_words`, at most 32). A
different answer clears them all. This is the two-seed rule of the random generator applied to
words the game changes on its own; it assumes the same about them (a word that did not change
the answer at two values does not change it later). `FMDB_UI_IGNORED_WORDS=0` turns it off.

## Hit rate while the game runs (round 3)

Two MCP stdio servers side by side on the same running game (the game process at about 67 %
CPU on one screen, game date fixed at 13 December 2030), each calling the seven tools in turn,
`fresh=false`, 8 rounds 10 s apart, then 5 rounds 60 s apart, then 3 rounds 300 s apart.
"after": this branch; "before": the same code with `FMDB_UI_FREE_LISTS=0 FMDB_UI_IGNORED_WORDS=0`
(what round 2 did). Hits of the calls after the first; median wall seconds of a call; load
average 4.6 to 17.8 (`cache-r3-uispeed/work/hitrate.py`).

| Tool | 10 s apart: before | after | 60 s apart: before | after | 300 s apart: before | after |
|---|---|---|---|---|---|---|
| `fm_get_board_confidence` | 4/7, 0.13 s | 4/7, 0.36 s | 3/5, 0.20 s | 2/5, 1.54 s | 0/3, 0.94 s | 0/3, 1.18 s |
| `fm_get_inbox` | 7/7, 0.04 s | 7/7, 0.04 s | 5/5, 0.12 s | 5/5, 0.05 s | 3/3, 0.03 s | 3/3, 0.03 s |
| `fm_get_player_status` | 0/7, 0.36 s | 4/7, 0.11 s | 0/5, 0.64 s | 2/5, 0.56 s | 0/3, 0.30 s | 0/3, 0.43 s |
| `fm_get_squad_happiness` | 0/7, 0.33 s | 2/7, 0.33 s | 0/5, 0.49 s | 2/5, 0.46 s | 0/3, 0.27 s | 0/3, 0.35 s |
| `fm_get_club_vision_progress` | 0/7, 0.21 s | 3/7, 0.20 s | 0/5, 0.33 s | 2/5, 0.25 s | 0/3, 0.17 s | 0/3, 0.22 s |
| `fm_get_ui_screen training` | 0/7, 0.23 s | 3/7, 0.21 s | 0/5, 0.30 s | 2/5, 0.28 s | 0/3, 0.23 s | 0/3, 0.25 s |
| `fm_get_manager_profile` | 0/7, 3.1 s | 0/7, 3.6 s | 0/5, 4.3 s | 1/5, 4.8 s | 0/3, 3.1 s | 0/3, 3.7 s |

At 10 s the first three rounds after the first call still miss: each failed check makes the
pages that changed "watched", and only from then on are the changed words known by name and
can the rule apply. At 300 s 85 to 167 pages of a read set change, most of them pages the
running game rewrites as a whole, so their words are not known and the answers are computed
again. A miss costs what a warm computation costs: board 0.8 to 1.5 s (131 M instructions of
`Tcnf`), manager profile 3 to 5 s (521 M; the recipe runs `Tcnf` twice, `ui_recipes_more.manager_profile`,
outside this lane), the others 0.2 to 0.6 s.

## Before and after, every shaped tool

`scripts/fmdb_ui_bench.py`, one process at `nice 10`, wall / CPU seconds of the tool process
(the memory-reader helper is not counted). The machine ran other agents throughout: load
average 44 to 213 for the "before" run (`FMDB_UI_VM=classic`) and 98 to 221 for the "after"
run, so compare CPU seconds; wall seconds are upper bounds. The owner played during both runs
(the game date moved from 10 to 13 December 2030).

* cold: a new emulator, `fresh=true`. warm: the same question again with `fresh=true`
  (before: another new emulator, because `fresh` discarded it; after: the same emulator, a new
  page generation).
* cached, before: the per-date entry, served without looking at the game. cached, after: the
  read set is read again; "(recomputed)" marks a call whose check found changed bytes and
  recomputed (the free-list heads named above, while the owner played).

| Tool | Before: cold | warm | cached | After: cold | warm | cached (check) |
|---|---|---|---|---|---|---|
| `fm_get_board_confidence` | 17.81 / 6.06 | 15.41 / 7.32 | 0.09 / 0.05 | 8.48 / 4.35 | 3.90 / 1.87 | 0.27 / 0.11 |
| `fm_get_inbox (50 items)` | 46.91 / 26.41 | 21.32 / 14.93 | 0.40 / 0.20 | 4.33 / 2.15 | 0.20 / 0.09 | 0.09 / 0.07 |
| `fm_get_inbox (one body)` | 26.08 / 16.74 | 23.68 / 13.80 | 0.90 / 0.31 | 0.69 / 0.35 | 0.60 / 0.26 | 0.37 / 0.22 |
| `fm_get_calendar (60 days)` | 4.30 / 1.37 | 2.80 / 1.41 | 0.15 / 0.12 | 1.73 / 0.60 | 1.02 / 0.42 | 0.42 / 0.27 (recomputed) |
| `fm_get_player_status` | 7.09 / 3.63 | 6.90 / 3.48 | 0.27 / 0.20 | 3.98 / 1.39 | 2.06 / 0.88 | 0.39 / 0.22 (recomputed) |
| `fm_get_club_vision` | 4.67 / 3.00 | 2.28 / 1.09 | 0.30 / 0.24 | 3.37 / 0.91 | 3.28 / 1.34 | 1.07 / 0.78 (recomputed) |
| `fm_get_club_vision_progress` | 44.58 / 28.68 | 4.30 / 2.05 | 0.38 / 0.28 | 1.77 / 1.01 | 2.27 / 0.76 | 0.19 / 0.12 |
| `fm_get_squad_happiness (none)` | 6.37 / 2.68 | 3.93 / 1.53 | 0.14 / 0.12 | 0.78 / 0.48 | 0.62 / 0.39 | 0.25 / 0.22 (recomputed) |
| `fm_get_squad_happiness (unhappy)` | 10.45 / 5.09 | 10.91 / 5.03 | 0.27 / 0.16 | 2.56 / 1.07 | 1.21 / 0.80 | 0.65 / 0.53 (recomputed) |
| `fm_get_squad_happiness (all)` | 39.21 / 18.00 | 10.61 / 4.66 | 0.45 / 0.30 | 3.36 / 2.15 | 3.30 / 1.99 | 2.88 / 1.66 (recomputed) |
| `fm_get_scouting` | 139.12 / 63.06 | 102.62 / 72.12 | 0.40 / 0.31 | 6.81 / 2.24 | 5.24 / 2.02 | 2.97 / 1.81 (recomputed) |
| `fm_get_transfer_activity` | 5.84 / 2.73 | 6.32 / 2.95 | 0.35 / 0.23 | 2.51 / 1.17 | 1.98 / 0.93 | 1.69 / 0.80 (recomputed) |
| `fm_get_squad_dynamics` | 2.10 / 0.89 | 5.89 / 1.07 | 0.56 / 0.31 | 0.92 / 0.56 | 1.04 / 0.54 | 0.54 / 0.32 (recomputed) |
| `fm_get_training_schedule` | 6.74 / 2.04 | 8.03 / 2.67 | 0.43 / 0.38 | 1.64 / 0.96 | 1.82 / 0.82 | 0.95 / 0.65 (recomputed) |
| `fm_get_medical_centre` | 11.74 / 4.80 | 11.08 / 5.15 | 0.54 / 0.43 | 12.11 / 4.01 | 6.80 / 2.92 | 5.37 / 2.36 (recomputed) |
| `fm_get_finance_projections` | 3.19 / 2.24 | 4.82 / 2.08 | 0.57 / 0.40 | 1.76 / 0.66 | 1.73 / 0.59 | 0.74 / 0.44 (recomputed) |
| `fm_get_youth_intake` | 1.97 / 1.07 | 2.49 / 1.19 | 0.70 / 0.44 | 2.28 / 0.63 | 3.18 / 0.60 | 1.03 / 0.45 (recomputed) |
| `fm_get_season_expectations` | 3.06 / 1.51 | 3.07 / 1.45 | 0.59 / 0.48 | 2.34 / 0.75 | 1.93 / 0.81 | 0.66 / 0.39 |
| `fm_get_manager_profile` | 111.99 / 46.95 | 109.91 / 43.55 | 0.51 / 0.40 | 29.38 / 14.76 | 13.93 / 6.82 | 5.93 / 4.89 (recomputed) |
| `fm_get_league_table` | 20.12 / 4.39 | 15.46 / 4.38 | 0.88 / 0.34 | 1.09 / 0.64 | 0.93 / 0.40 | 0.76 / 0.51 (recomputed) |
| `fm_ui_read 114 (guarded)` | 80.19 / 16.93 | 83.00 / 18.66 | 0.63 / 0.48 | 4.28 / 3.24 | 1.77 / 1.45 | 0.17 / 0.13 |

Against the targets (CPU seconds): the inbox list is 0.07 once subjects exist (2.2 for the
first 50 subjects); one body is 0.26 to 0.35; whole-squad happiness is 0.39 to 0.48 for the
list and 0.8 to 1.1 with reasons for the unhappy; player status is 0.22 when its check passes
or it recomputes from re-read pages, 0.88 on a new generation. Cold in about a second or
less: calendar, club vision, vision progress, squad happiness, squad dynamics, training,
finances, youth intake, season expectations, league table, transfers.

Tools above that, and the game computation responsible (instructions from the C counter):

| Tool | Instructions | Where |
|---|---|---|
| `fm_get_board_confidence` | 131 M | server `Tcnf` (TEAM_CONFIDENCE_UI_HANDLER_SERVER slot 2, 0x551D60) |
| `fm_get_manager_profile` | 521 M | `Tcnf` twice (260.8 M; the recipe builds that handler twice), PERSON server keys `NEWS` 124.6 M and `MSRP` 94.0 M (0x3F1CDC) |
| `fm_get_scouting` | 89 M in 1,337 calls | RECRUITMENT_FOCUS server keys `rfit` 30.6 M and `rftd` 17.0 M (0x45123C), SCOUTING_INFO `HSif` 8.7 M |
| `fm_get_squad_happiness (all)` | 84 M in 6,816 calls | PERSON server keys `gDhI` 54.7 M and `RSDP` 10.4 M |
| `fm_get_medical_centre` | 39 M | TEAM server keys through 0x5C3734 (`subt`, `TExC`, `TriA`, `TciD`, `TPIn`); 1.8 CPU-s, most of it outside emulation |
| `fm_get_player_status`, cold | 73 server keys | 0.36 CPU-s of emulation; the rest of a cold call reads 17,000 pages |

Emulation runs at about 120 M instructions per second, so `Tcnf` alone is 1.1 s.

## Checks

* `scripts/fmdb_ui_vm_check.py` (limit 1,000,000,000 instructions per call, first relevant
  profile per type, load 30 to 210): 150 handlers (all 138 factory types and the 12 classes DATABASE_RECORD dispatches to), 5,494
  cells (150 builds, 463 input transfers, 4,881 keys of which 2,078 values and 627 unavailable), 0
  different. Reference 3,428 s wall and 2,478 CPU-s; accelerated 110 s wall. After merging
  p1/virtual again (new external models): types 5, 15, 29, 45, 70, 131, 197 cells, 0 different.
* `scripts/fmdb_ui_order_check.py --players 20` on frozen memory: 5,640 leaves read in two
  orders, 0 different, across 7 and 5 page generations.
* `tests/test_fmdb_ui_fast.py`: 15 tests on synthetic memory (baseline against the reference
  emulator, generations, read sets, invalidation, two-seed rule, inbox list and bodies).
* Offline UI, VM and refusal tests with both inventory tests (194 tools): 193 passed, 4 skipped.
* Live tests (`FMDB_REFERENCE_SAVE=1`): three full runs while the owner played and the load
  average was 80 to 210: 21 passed, 4 failed, 2 errors, 2 skipped (the errors were
  `vm.uc.mem_write` on live memory, fixed); then 19 passed, 8 failed; then 14 passed, 13
  failed. Three failures are the same on the reference emulator and come from the game
  state of 13 December: `ptvl` is 51 where the test expects 47; `season_expectations` stops at
  `external call _access`; four TEAM_CONFIDENCE keys (`SZtr`, `iajq`, `TjWO`, `bi6D`) stop at a
  bad pointer (0x7372657000000000, backtrace 0x43A910C < 0x43D12B8 < 0x43DBA30 < 0x1EE8CE0).
  The other failures come and go on both emulators ("write to shipped code", "unreadable live
  memory"): two modules run three times alternately gave 1, 1, 2 failures of 10 accelerated
  and 1, 4, 1 reference. They are torn reads of the free lists named above while the game
  runs. `test_read_order_does_not_change_answers` reads the two orders from the running game
  at different moments and failed for the same reason; on frozen memory the orders agree
  (`fmdb_ui_order_check.py`).

## Not verified

* The ground-truth comparisons of 10 December 2030 (board grades, club vision judgements,
  wages, board members, known next fixture): the owner had advanced to 13 December, so those
  tests skip or compare against data that has changed.
* Quiet-machine timings.
* Hit rates over a normal playing session. One soak (8 rounds 10 s apart, load 31) gave the
  board 6 hits of 8 and four other tools none, for the free-list reason above.
* That `limit_instructions` stops where the reference stops (it counts per call here).
