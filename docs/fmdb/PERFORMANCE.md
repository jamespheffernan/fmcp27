# fmdb performance: profiles, changes, measurements

Branch `fmdb/perf` against the released reader 0.164.0 (`cd0a93f`), on the running FM27 build
27.0.0.2493426 (Newcastle United, 10 December 2030), 11 November 2026. Every number below was
measured on that save unless it is marked "documented" (taken from SNAPSHOT.md or the
knowledge docs and not measured again) or "estimate".

## Third pass: names, first calls, screens (`r3/uispeed`)

12 November 2026, game date 13 December 2030, through the MCP stdio server (`live_q.py`) or
`tools.db_query` in fresh processes. Other lanes ran throughout; the load average of each run
is given.

| path | before | after | load |
| --- | ---: | ---: | --- |
| Fixtures filtered by a team name on a fresh snapshot (`... FROM fixture_view WHERE home_team = 'Newcastle United' LIMIT 5`) | 165.8 s | 1.41 s | 11 / 8 to 10 |
| The same after a rebuild of the snapshot (`fm_db_refresh`), another team | 0.48 s (names memoised in that file only) | 0.60 s (names carried into the new file) | 11 / 10 |
| A whole team-name column (`SELECT count(*) FROM team WHERE name_Tlna LIKE '%Under 21s'`, 66,021 names) | 115 to 206 s (brief) | 19.6 s | 8 to 10 |
| One team name (`Tlna`, CPU, all 66,021 teams) | 0.96 ms | 0.345 ms | 9 to 14 |
| `Tsna` / `dbnm` of a team (all 66,021) | 0.85 / 0.73 ms | 0.33 / 0.27 ms | 9 to 14 |
| `dbnm` / `Csna` / `Cnam` of a competition (all 8,136) | 0.27 / 0.06 / 0.02 ms | 0.08 / 0.08 / 0.02 ms | 9 |
| First `fm_db_query` of a process, snapshot present (30 fresh processes, `tools.db_query`) | 1.6 to 2.0 s (brief) | 0.90 to 1.83 s, no outlier | 9 to 10 |

### Names

Where a team name goes (`Tlna`, reference VM, block trace): a team with a name of its own (an
affiliate such as "Poongsaeng High School") costs 233 instructions; every other team composes
the club name and a translated suffix through the game's text object (0x43CD17C, 17,000 to
82,000 instructions, 84 mutex calls and 28 `memmove`). On FastVM the instructions are a small
part of the 0.8 ms: the 49 imports a call makes that FastVM models in Python (`memmove`,
`strcmp`, the shared-mutex calls, `tlv_bootstrap`) are most of it. The UI accelerator models
those in C and the game's pool allocators as well, so the same getter on `FastUiHandlerVM` in
the database view costs 0.25 to 0.35 ms.

A direct plan (stored club name plus a type suffix) does not hold: of 66,021 teams, 1,804 do
not start with their club's stored name (affiliates, schools, B teams with names of their own)
and 3,603 have no club (national sides), and the suffix of one team type varies (`Under 19s`,
`U19`, `Development`).

Three changes (`ondemand.py`, `snapshot.py`):

1. Declared-input name columns (team `Tlna`, `Tsna`, `dbnm`; competition `dbnm`, `Csna`,
   `Cnam`; `ondemand.NAME_VM_CODES`) are computed on `ondemand.name_vm(engine)`.
   `scripts/fmdb_name_check.py` compared it with FastVM on every record of these six columns:
   222,111 values, 0 different.
2. These columns are computed for the rows a statement asks for, without the whole-column
   pass after 1,024 cells: a join from 79,530 fixtures needs at most the 7,055 teams that play
   in them, and `LIMIT` stops earlier.
3. A build carries every memoised declared-input cell of the previous snapshot of the save to
   the rows whose input cells are equal (`ondemand.carry_declared`, 0.1 s; input tuples that
   gave two values are not carried; `_build.declared_carried` lists the counts). A rebuild in
   the same or another game process therefore starts with the names (and position texts)
   already known.

Club names the views read first (`club.name` = `dbnm`, `short_name`, `stadium_name`,
`six_letter_name`) are direct for CLUB. The translated club name `Cnam` (0.6 ms) and the other
on-demand name columns are not declared-input columns: they keep a read set, which the UI VM
does not record in the memo's format, so they stay on FastVM. Stage names and names in other
languages were not measured in this pass.

### First calls

Profile of the first `fm_db_query` of a process with a snapshot present (cProfile, load 10,
2.15 s profiled): engine 0.76 s (plugin SHA-256 0.22 s, catalog 0.23 s, the Bridge's layout
check 0.27 s), content check 1.28 s (16,358 pages read again 0.55 s, block CRCs 0.19 s, table
vectors 0.1 s), the statement 0.04 s. 30 fresh processes in a row: 0.90 to 1.83 s, alternating,
because a process started within 3 s of the last check reuses it; no run above 2 s, so the 9 to
22 s outliers were not reproduced (they need a rebuild or a lazy collection source, which these
runs did not trigger).

Snapshot write, profiled (cProfile, 17.5 s profiled, 9.5 s unprofiled at load 10): `executemany`
3.2 s, Python conversion of the columns (`convert_column`, `to_sql` on 3.7 M cells) 4.2 s,
commit and close of the 250 MB file 4.0 s. The NULL cells are not the cost: a build with the
all-NULL columns added after the rows (`ALTER TABLE ADD COLUMN`, rows without them) wrote a
115 MB file instead of 252 MB in the same time (9.5 and 12.2 s against 10.0 and 9.8 s, back to
back, load 10 to 11). It was not kept: it changes the column order of `SELECT *`, so tool output
would not stay the same.

### Not changed in this pass

`player_season_stats` (a `sources/` table, another lane's files), `match_player_stats` (18 ms a
frame in the hand-built decoders `saved_match_player_*.py`, 55 % of it the eleven counter
decoders) and `fm_get_match` were not changed; the files that hold their cost are outside this
lane.

## Second pass: on-demand cells and freshness by content (`p2/ondemand`)

The first pass (below) made the same design faster. This pass changes the design: a build
stores direct columns only, a getter runs when a statement names its column, and freshness is
decided by comparing bytes with the game instead of comparing game dates. `fill.py` and every
detached process are gone. SNAPSHOT.md describes the mechanism; this section holds the
measurements. One process at `nice 10`; other agents kept the load average between 13 and 90, and
each figure names the load of its run.

| path | before (integration, 0f70115) | this branch | load |
| --- | ---: | ---: | --- |
| Snapshot build | 41.9 s, 32.8 CPU-s (direct 10.9, eager 6.0, write 23.2) | 19.7 s, 17.5 CPU-s (direct 7.5, write 10.5, final check 0.75) | 25 to 30 / 20 |
| Refresh, nothing changed | none within a game date; a full build on a new date | 0.45 s, 0.28 CPU-s (16,358 pages read and hashed) | 25 |
| Refresh, 50 pages changed | the same full build | 0.90 s, 0.73 CPU-s (659 blocks checked by CRC, 0 evaluated) | 25 |
| Statement on direct columns | 0.25 to 0.76 s | 0.34 s inside the 3 s check interval; 1.1 s with a check | 25 |
| 20 rows, 5 emulated columns (192 cells) | NULL until the fill reached the rows, or 17 s when no fill ran | 0.39 s, 0.35 CPU-s; repeat 0.25 s | 25 |
| 200 rows, 5 emulated columns (1,000 cells) | as above | 0.64 s, 0.58 CPU-s; repeat 0.21 s | 25 |
| Sort on a whole emulated column (`goals`, 65,785 cells) | tier-1 fill 157 s with 8 workers, again every game day | 22.3 s, 20.5 CPU-s once; repeat 0.58 s (257 blocks verified) | 25 |
| World-wide filter on position text (51,885 cells) | as above | 81.6 s, 78.2 CPU-s once; repeat 4.1 s; 6.9 s wall, 1.75 CPU-s after a content check | 9 |
| Manager-view statement filtering on position (17,107 known players) | NULL until the fill reached the rows | 5.5 s with the positions memoised; the prewarm stops after 20 s otherwise | 9 |
| Background work per game day | up to 84.9 M cells, about 71 minutes of 8 workers | none | |

### What the profiles showed

* **Page-level dependencies are too coarse.** With one page set per block, 330 changed pages
  made a refresh evaluate nearly every block: 74.7 s, 47.4 CPU-s, 27.4 M cell comparisons, 0
  rows changed. A page holds many objects and changes far more often than the bytes a plan
  reads on it. Each block now keeps its exact windows and one CRC of their bytes; the CRC
  decides whether the block is evaluated. The same change removed the per-row page bookkeeping
  from the build.
* **Read sets need word granularity and the call's own writes removed.** At 64-byte lines every
  block lost its cells within 5 s. At 8-byte words, 58 of 55,589 words read by 26 getter codes
  on 1,024 players changed in 36 s; the changing words were the game's pooled-allocator free
  lists and reference counts, which a getter reads, changes and discards. Leaving out the
  words a call stores in full left 3 changing words, all read by the position-text getters
  `Ppsr` and `Ppss`.
* **Read tracking costs little.** A memory-read and a memory-write hook in the accelerator
  (C, one bit per word) cost 0 to 50 % per call on the measured codes (`Pcon` 49 to 45 µs,
  `Prat` 121 to 164 µs, `Ppsr` 918 to 1,426 µs).
* **A statistic costs two getter calls.** The record getter does not claim the season-statistic
  keys, so `get_property` asks again with the game layer: 270 to 310 CPU-µs per cell, which is
  the 20 CPU-s of the `goals` column.
* **The translated club name is the dearest name.** `Cnam` runs 11,137 instructions and 52 mutex
  calls per club (595 µs, 992 µs with tracking): 36 CPU-s for 28,022 clubs. `player_view.club`
  reads the stored names instead.

### After a game-day tick

The owner advanced the game from 10 to 13 December 2030 during one benchmark run. In that run
the direct statement took 4.1 s with its check (3.3 CPU-s; the row counts were not captured),
every block of `player` lost its memoised cells, and the `goals` column was computed again in
24.5 s. A whole column that was memoised is therefore computed again after a day tick the
first time a statement scans it; point statements compute their own rows (0.25 to 0.7 s).

### Checks

* **Golden diff** (`scripts/fmdb_golden_diff.py`). OLD: integration code (2f4749d), its build
  with eager emulation, then `materialise` of 26 columns on 1,500 rows per table. NEW: this
  branch, built back to back (game date 13 December 2030, load 14 to 40), the same 26 columns
  and rows computed on demand, and every (column, class) OLD had emulated at build computed
  on demand (801 of 810 pairs; 9 skipped for classes above 3,000 rows). 154,837,670 cells by
  name in 3,404 columns: 22,910,054 equal (886,611 of them on-demand cells in 804 columns),
  391,924 filled where OLD was not ready, 0 changed, 16 lost, 131,535,676 on-demand cells not
  computed and not compared. The 16 lost cells are five `person` columns and one `non_player`
  column on the three HUMAN_NON_PLAYER rows: this branch's getter refuses them on both VMs
  (`random_device`, `gettimeofday`); integration answers them since a merge that came after this
  branch's merge point (ad00977).
* **Differential and cross-check** (`scripts/fmdb_snapshot_check.py`, load 41 to 45): 101,984
  direct cells against the getter, 0 mismatches; 15 players against the hand-built tools, 1,293
  fields equal, 0 different, 0 NULL (before: 9 to 30 NULL for columns the fill had not reached).
* **Audit** (`python -m fm_live_mcp.fmdb.audit --cpu 40`): 606,964 direct cells compared with the
  getter (2.48 % of 24,472,604) in 32.8 CPU-s, 2 disagreed and their plans were demoted
  (`person.hair_length`, code `Phln`, for SUPPORT_STAFF and ACTUAL_PLAYER_AND_NON_PLAYER: the
  plan read 4 and 0 where the getter gives 1); 12 memoised cells recomputed, 0 different.
* **Tests.** Offline `tests/test_fmdb_*.py`: 469 passed, 4 skipped (load 55). Live, non-UI
  (`test_fmdb_live`, `_snapshot_live`, `_knowledge_live`, `_sources_live`, `_ledger_live`,
  `_matches_live`, `_oracle_live`; load 18 to 44): 91 passed, 1 failed in the first run
  (`test_manager_view_query`: the warm manager statement took 366 s while a knowledge fill the
  test itself had started grew the population and position text was recomputed every time);
  after the declared-input memo and the prewarm budget the same statement takes 5.5 s.
  `test_fmdb_snapshot_live` and `test_fmdb_live` again: 8 passed in 99.7 s (load 11 to 15). The
  two inventory tests: 2 passed (194 tools). The UI live tests and `adviser/tests` were not run.
* **Oracle** (`scripts/fmdb_oracle.py`, which uses its own PropertyVM and none of the code
  changed here): 31,389 match, 110 mismatch, 93 generic-unavailable, 160 tool-unavailable at
  load 6 to 14. The integration code (4cab2a4) run directly afterwards at the same game date
  (13 December 2030, load 8 to 40) gave the same four numbers. The documented baseline (31,385 /
  134 / 82 / 100) was taken on 10 December.
* **Budget gate** (`scripts/fmdb_bench.py budget`, load 20): build 17.5 CPU-s (limit 30), content
  check 0.36 CPU-s (limit 2), no eager source, no process started by a tool call.

### What remains slow, and why

* **A first scan of a dear column.** `goals` 20 CPU-s (two getter calls per cell), position text
  `Ppsr` 78 CPU-s (0.9 to 1.4 ms per cell). Position text reads a scratch buffer that changes
  every few seconds, so it is memoised by declared inputs instead (SNAPSHOT.md): the first scan
  is paid once and a cell is computed again when a position rating of its row changes. A plan
  that derives the text from the ratings would remove the first scan too.
* **After a day tick** a memoised statistic column is computed again on its first scan (the
  matches of the day change what the getters read).
* **Build write, 10.5 s.** SQLite still writes one NULL per on-demand cell. Creating the table
  with its direct columns and adding the others with `ALTER TABLE ADD COLUMN` would leave the
  rows short; it changes the column order of `SELECT *` and was not done.
* **Decode in Python, 5.6 s of the build** (`bulkplans._columns`). A rebuild now happens once per
  game process, so this was left.
* **Collection sources.** `club_finance` is still keyed to the game date (28,022 clubs × 6
  getter calls per rebuild; it needs the per-row on-demand shape). The other sources keep their
  own content fingerprints.
* **Robust lane's plan compilation** took 69 s and verified 0 plans in one tool-triggered build
  at load 65 (budget 15 s). Tool-triggered builds skip it; `scripts/fmdb_snapshot.py` runs it.

## Result (first pass, `fmdb/perf`)

Median of three runs, released code and this branch run back to back by
`scripts/fmdb_bench.py` so both see the same machine load.

| path | released | this branch | note |
| --- | ---: | ---: | --- |
| Snapshot build as the tools run it (new game day, new save on a known build, `fm_db_refresh`) | 58.4 s | 22.5 s | direct 16.6 → 5.5 s, eager emulation 22.3 → 4.0 s, write 18.4 → 12.0 s; measured with a 4 s eager budget, the committed budget is 6 s (up to 2 s more) |
| Same game day, no refresh asked | query only | query only | unchanged |
| Plan phase on an empty plan cache (new user on the pinned build) | 24 to 40 min (documented) | 0.65 s | shipped plans, 1,224 direct plans checked against the getter on load |
| Tier-1 getters, 47 codes × 300 players, one process | 9.42 s (1,497 cells/s) | 0.55 s (25,800 cells/s) | FastVM |
| Tier-1 fill, cells filled in a 60 s budget | 89,834 (4 workers) | 2,108,964 (8 workers) | best of three for both; the other runs had load averages of 15 to 87 |
| Tier-1 fill, whole save (3,221,175 cells) | 39.5 to 43.5 min (documented) | 156.7 s | one run, 8 workers, load average 79; 20,562 cells/s |
| All tiers (84.9 M cells) | about a day (documented) | about 71 min (estimate) | 27,900,446 cells in 1,400 s (19,927 cells/s) at load averages of 60 to 80, then stopped in tier 3 |
| Perceived stars, 400 players | 4.45 s | 0.63 s | same process, both VMs; equal results |
| Player Search admission, 400 players | 1.07 s | 0.52 s | same |
| Knowledge capture (cells, 47 fields), 300 scouted players | 9.0 to 11.2 s | 6.3 to 7.7 s | same code; the difference is machine load |
| Engine open + first getter | 0.64 s | 0.77 s | unchanged path |
| `import fm_live_mcp.server` | 1.0 to 2.0 s | 1.3 to 2.2 s | unchanged |
| Five SQL queries on a filled snapshot | 0.92 to 3.0 s in all | 0.97 to 1.27 s | unchanged code |
| Runtime screens, inbox | not measured again | unchanged | `ui_vm.py` was not touched |

What is not reached: a refresh in seconds (22.5 s; the floor of this design is about 17 s, see
"What remains"), incremental refresh, knowledge capture for the scouted set in a few seconds,
and any change to the runtime screens.

## Machine

Mac with 4 performance and 6 efficiency cores, 24 GiB. Other agents ran test suites and two
background fills on the same machine for the whole session: load averages between 5 and 125.
The game's resident size was about 215 MB of 6.4 GiB writable address space, so most game
pages were compressed or swapped and a first read of a page is slower than a repeat read.
Under load every wall-clock figure moved by a factor of two to three between runs; the table
above uses the runs made while the load average was 5 to 12, and each row of
`scripts/fmdb_bench.py` output carries the load average of that run.

## Getter emulation: FastVM (`fastvm.py`, `native/fm_vm_accel.c`)

Profile before, 47 tier-1 codes × 100 players in one process (cProfile, 10.4 s):

* 1.5 million calls of Unicorn's Python hook wrapper, 5.5 s. PropertyVM ran a Python function
  for every basic block (1.37 M), every store to a live page (106 k) and every import stub.
* 2,036 `mem_map` calls, 2.6 s. Every 4 KiB page was its own Unicorn region and the cost of a
  map grows with the number of regions: 3,000 regions cost 16.5 s in a separate measurement,
  300 cost 13 ms.
* `emu_start` itself, 2.6 s for 11,730 starts: Unicorn starts a timer thread for every start
  that has a timeout, and an import reached through a bound address ended the run and started
  another.
* The emulated code: 1,144 instructions per cell on average, 0.5 M instructions per second.

One trivial getter call cost 288 µs.

What FastVM does instead:

* Unicorn runs in virtual-TLB mode over a code pool, a data pool and the private ranges, each
  mapped once. A TLB miss is answered in C from a hash of the copied pages; Python runs only
  for a page that is not copied yet.
* The instruction budget and the timeout are checked in a C block hook (the timeout every
  1,024 blocks instead of by a timer thread).
* Copy-on-write is done in C through TLB permissions: a copied page is read-only until the
  first store of a call, which saves the page and grants write access. Up to 16 written pages
  keep their write access between calls and are copied back before each call; beyond that the
  set is cleared and the TLB flushed.
* The models that return a constant (`pthread_mutex_lock`, `free`, ... : 79 % of external
  calls in the tier-1 workload) and the stack probe run in C, for plugin stubs (code hook) and
  for bound addresses (the fetch is answered with a page of `ret`; the block hook applies the
  model). Every external call is still listed in `CallStats.externals` in call order.
* Dropping the copied pages keeps the instance and its translated code.

One trivial getter call costs 26.5 µs. `Engine.vm`, `knowledge_stars.StarEngine` and
`knowledge_native.search_admission` use FastVM when `build/libfm_vm_accel.dylib` exists
(`scripts/build_vm_accel.sh`; `FMDB_VM=classic` forces PropertyVM). The load tracer
(`Engine.plan_tracer`), `knowledge_native.NativeOperands` (it hooks every load for the
firewall) and `ui_vm.UiHandlerVM` still use PropertyVM.

### Same results

`scripts/fmdb_vm_check.py` runs every column code of every snapshot table on sampled records
of every class through both VMs on the same cached pages and compares the canonical value, the
variant kind, the handled flag, the view, the refusal reason and the instruction count.

* 4 records per class, all 26 tables: 36,065 cells, 0 different, instruction counts equal;
  PropertyVM 378.5 s, FastVM 14.3 s.
* 3 records per class, another seed: 27,522 cells, 16 different before the timeout rule below,
  0 after.

Differences that exist:

* PropertyVM stops a call after 5 s of wall-clock time. On a loaded machine it refuses calls
  that the 2,000,000-instruction budget allows; FastVM completes them (20 of 36,065 cells in
  the run above, among them the game-layer retry of three keys). Each of those cells agrees
  once PropertyVM is given a 10-minute timeout. The released reader's result for these cells
  depended on machine load; FastVM's does not.
* `Unavailable.detail` of a refused store names the 1 KiB block Unicorn asked for, not the
  exact byte. The reason text is unchanged and only the reason reaches the snapshot.
* `CallStats.mutated_pages` counts pages with write access during the call (up to 16 may be
  left from earlier calls).

No getter result is memoised, so nothing had to be excluded for reading the clock or a random
generator; those calls are refused by both VMs as before (`_gettimeofday` 63, thread-local RNG
2,224 and `random_device` 8 of the 36,065 cells).

## Fill (`fill.py`)

* Workers: 4 before, now the core count less two (2 to 8; `FMDB_FILL_WORKERS`).
* A chunk's cells were written with one `UPDATE` per cell, each rewriting a row of up to 679
  columns. Columns that cover the same rows are now set by one `UPDATE` per row.

Measured, tier 1, 60 s budget (`scripts/fmdb_bench.py fill`): released 89,834 / 80,059 /
88,379 cells (1,478 / 721 / 640 cells per second; the second and third runs overran to 111 and
138 s); this branch 2,108,964 / 1,423,884 / 315,605 cells (34,924 / 22,168 / 2,972 cells per
second at load averages 25 / 39 / 87). The workers are CPU-bound: at load average 47 each
got about 40 % of a core.

The whole tier-1 fill (`scripts/fmdb_bench.py fill-full`): 3,221,175 cells in 156.7 s with 8
workers at load average 79 (334.6 CPU seconds). The background fill the tools start (all
tiers) filled 27,900,446 cells in 1,400 s under the same load: tier 1 for every player and
staff row, tier 2, and 409 of 641 tier-3 columns, before it was stopped.

Per cell on a quiet machine the getter workload costs 39 µs in one process. About 60 % of that
is Python around the call (argument set-up, the variant decode, the game-layer retry for keys
the record getter does not claim).

## Snapshot build (`snapshot.py`, `bulkplans.py`, `memory.py`)

Profile before (cProfile, 218 s under load; the unprofiled build is 58 s):

* Direct reads, 107 s: 4.4 million read items, each sliced into its own `bytes` object,
  each cell decoded by a Python call (`_walk` 86 s cumulative, `read_many_status` 41 s).
* Write, 92 s: `write_table` 83 s, of which 16 s in 105 million `dict.get` calls (one per cell,
  NULL or not) and 12 s in SQLite.
* Eager emulation, 15 s: the budget; 1,972 getter calls fitted in it.

Changes:

* `MemoryBase.windows(addresses, length)`: one fixed-stride buffer per stage. For record
  arrays inside allocator arenas (170,499 people on 5,233 pages) the pages are read once and
  sliced locally; otherwise one READV item per address, with the request built and the
  response checked as whole buffers.
* `bulkplans.evaluate(..., windows=...)`: each cluster of a stage is decoded column by column
  with `struct.iter_unpack`; a terminal that needs `decode_terminal` is decoded once per
  distinct byte string; every distinct string or reference pointer is followed once.
* `write_table`: each column is converted as a list; only columns that hold a value are named
  in the `INSERT`; a reference that resolves is resolved once per distinct value.
* `player.is_virtual`, `team.parent_club_idx`, `team.club_idx`, `person.contract_team_idx` and
  `person.contract_club_idx` are part of the row `INSERT` instead of an `UPDATE` per row.
* `REFRESH_BUILD_BUDGET_S` 15 s → 6 s: with FastVM a 3 s and a 5 s build each leave 939 columns
  ready, against 931 in the released 15 s build. The views use the club, team and nation name
  columns that are ready when the build ends (a build with a zero budget has a `player_view`
  without `club`), so the budget keeps a margin for a loaded machine. At load averages of 59
  to 75 the 6 s build left 890 to 925 columns ready and took 51 to 61 s.

Checks:

* `scripts/fmdb_direct_check.py`: all 24,365,743 direct cells of the 26 tables, window route
  against the released per-item route on the same cached pages: 0 different.
* `scripts/fmdb_golden_diff.py`, released build against this build, back to back:
  154,843,447 cells in 3,220 columns; 154,717,026 equal; 126,421 filled where the released
  build left the column pending; 0 changed; 0 lost; no column that was ready is pending. An
  earlier pair had 3 lost cells (`non_player.role_scores` of the 3-row class
  HUMAN_NON_PLAYER, refused as "unreadable live memory" during that build). Both VMs return
  the value for those records when asked again and three later builds had no refusal.
  FastVM now also forgets refused pages when it drops its copied pages, as a new PropertyVM
  did.

## Plans (`snapshot.PlanStore`, `fm_live_mcp/fmdb/data/plans-<sha256>.v2.json.gz`)

The package carries the plan document of the completed derivation for the pinned plugin build
(80 KB, 6,361 class/field pairs, 1,224 direct). `PlanStore` takes from it what the cache does
not have. Before a build uses them, `verify_shipped` compares every shipped direct plan with
the getter on 6 records of its class, demotes a plan that disagrees and writes the cache, so
the check runs once per cache. On the running save: 7,344 comparisons, 0 demoted, 0.65 s
(median of 3), no derivation. A build from the shipped plans equals a build from the derived
cache (154,843,447 cells, 0 changed, 0 lost).

Another game build has another plugin SHA256, finds no shipped file and derives as before.
The derivation itself still uses PropertyVM with a Python load hook and was not measured again.

## Differential demotion (the open item)

The failure "a mismatched column that was not in the demoted set" has this cause: the check
demotes a plan and saves the plan cache, but the snapshot built before the demotion keeps the
demoted plan's values until the game date moves. A second run of the check on that snapshot
finds the same mismatch, finds no direct plan left to demote and reports the column as
mismatched only. The demotion was persisted; the snapshot was not invalidated.

`tools.current_snapshot` now compares the plan cache's direct-plan count with
`_snapshot.plans_verified` and rebuilds when they differ; the check lists such a column under
`demoted_plans` and `demoted_before_this_run`
(`tests/test_fmdb_perf.py::test_snapshot_is_rebuilt_after_a_plan_is_demoted`).

## Knowledge

The capture cost 14 ms per player on a quiet machine: 270 journalled reads at 23 µs each through
`fm_live_helper read-stream`, the rest Python that rebuilt every per-call constant for every
player. Now (`docs/knowledge-bulk.md`, "Engines" to "Throughput of the paged engine"):

* reads are slices of 16 KiB pages fetched in batches by `fm_fast_reader`;
* one source is built per call and copied per player; canonical record checks, the owner's
  context, club relations, pinned-code guards and the emulated fixture helpers run once per
  distinct argument;
* each row keeps a fingerprint of the inputs it consumed, and a later call evaluates only the
  players whose inputs changed. The game date is consumed as facts (a date has passed, an age),
  so a day tick alone re-evaluates the players with a birthday or an expiry that day.

Frozen pages of the live save, CPU seconds: named population (3,555) 6.3 s, the other 62,488
players 143 s, the whole store with SQLite, fingerprints and stars 206 s (the tree before this
work: 433 s on the same pages, 23 minutes live). 600 players with nothing changed 0.27 s; after
moving the date one day 0.29 s with one player evaluated. Every row of both stores is equal
(66,043 player rows, 3,104,021 attribute rows).

Not changed: stars and Player Search admission (FastVM, 1.1 and 0.8 ms per player on frozen
pages) have no fingerprint and are computed again per epoch for the rows that read them.

## What remains slow, and why

* **Refresh, 22.5 s.** Direct reads 5.5 s: 24.4 million cells become Python objects
  (0.22 µs per cell; reading the 12,280 pages takes 0.9 s of it). Write 12 s: SQLite writes
  155 million cells of which 131 million are NULL (6.5 s in `executemany`, 2 s in the rank
  SQL, 2.5 s assembling columns). Eager emulation 4 s is a budget. With this design the floor
  is about 17 s. Going below needs two changes that were not made: decode the direct columns
  in native code into typed arrays and compare them with the previous refresh, so only
  changed rows are updated in place (measured: setting every fill-owned column to NULL in
  place costs 3.5 s, re-ranking 2 s); and stop writing the NULL cells (a table layout whose
  pending columns are physically last or in a second table; this changes `SELECT *` column
  order, so it was not done).
* **Emulated cells are recomputed every game day.** A getter result depends on the bytes it
  read. Recording that set per cell needs a load hook (which disables Unicorn's fast memory
  path) and about 4 KB per row; page-granular sets are invalidated by any change on a page
  the getter touched. With the fill at 22,000 to 35,000 cells per second, recomputing tier 1
  costs two to three minutes under load, in rank order (the managed club first).
* **Fill, 39 µs per cell.** About 60 % is Python per call. A C loop over the records of a
  chunk that returns to Python only for non-scalar results would remove most of it.
* **Knowledge evaluation, 1.8 to 2.3 ms per player** on first use: Python. What remains per
  player is the transfer predicate (run twice, once by the structural closure), the relation
  mask, the club score and the K composition itself. The four `replay_lazy` helpers and the two
  native operands still run on the plain Unicorn VM; they are memoised per argument and cost
  about 5% of a whole-save pass.
* **Screens, inbox**: not touched. `UiHandlerVM` subclasses PropertyVM with its own hooks and
  region mapping; moving it to the pools of FastVM is the same work as FastVM itself.
* **Plan derivation for a new game build**: unchanged (24 to 40 minutes, documented).

## Test and oracle runs

* `tests/test_fmdb_*.py` (UI files apart), `tests/test_knowledge_bulk*.py`,
  `tests/test_knowledge_native.py`, `tests/test_knowledge_stars.py`, `tests/test_mcp.py`, live
  tests included: 504 passed, 4 skipped, 2 failed. The two failures
  (`test_fmdb_snapshot_live.py::test_example_queries` and `::test_manager_view_query`,
  "no such column: club") came from the snapshot in the scratch cache, which a timing harness
  had built with a zero eager budget. With a snapshot built by the tool path the file passes:
  4 passed.
* The UI files with `FMDB_REFERENCE_SAVE=1`: 124 passed.
* New tests: `tests/test_fmdb_perf.py` (14) and the FastVM parameters of `tests/test_fmdb_vm.py`
  (33 passed, 4 skipped for the tracer, which uses PropertyVM).
* `scripts/fmdb_oracle.py` builds its own PropertyVM; it does not run FastVM, the window reader
  or the snapshot writer. Documented baseline: 31,385 match, 134 mismatch, 82 generic-unavailable,
  100 tool-unavailable. Two runs on this branch: 31,312 / 134 / 155 / 100 and 31,382 / 134 / 85 /
  100. The first run had 69 name cells (`Cnam`, `dbnm`: the getters that read `languages.fmf`)
  and 4 injury cells refused ("unreadable live memory", "write to shipped code"); the second
  had 3 `Ptaj` cells refused ("write to shipped code"). A probe of `Cnam`, `dbnm`, `injr` and
  `Ptaj` on 300 to 500 records with both VMs gave no refusal and no difference. The released
  checkout, run afterwards at load averages of 20 to 50, gave the baseline exactly (31,385 /
  134 / 82 / 100); the two runs on this branch ran at load averages of 50 to 87, the second
  one next to this branch's own 8-worker background fill. The mismatch count is 134 in every
  run; what moved is refusals of the PropertyVM path, whose code differs from the released
  one only by the `_init_uc` / `_poke` refactor. A third run on this branch at load averages
  above 100 gave 31,353 / 132 / 117 / 99. Both checkouts were then run at the same time at
  load averages of 100 to 300: released 30,267 / 120 / 1,214 / 100, this branch 30,947 / 123 /
  531 / 100. The oracle's result depends on machine load (PropertyVM's 5 s wall-clock
  timeout, reads spread over a longer time on a game that is not paused); it reproduces
  the baseline only on a quiet machine, and this branch was not run on one.

## Not verified

* A real change of game day (the game was not advanced): the 22.5 s is a full build, which is
  what a new day runs.
* The all-tiers fill to the end (stopped after 27.9 of 84.9 million cells).
* Knowledge tier 1, whole-save knowledge and the first manager query of a day end to end.
* Screens and inbox timings.
* A machine without `build/libfm_vm_accel.dylib` uses PropertyVM (covered by the unit tests
  only).

## Build budget

`scripts/fmdb_bench.py budget` runs one build as the tools do and exits 1 with
`BUILD BUDGET EXCEEDED` when the build process used more than `--max-cpu` CPU-seconds
(default 40; 21 to 24 on a quiet machine, 32.7 and 34.5 at load average 103).

## Reproduce

```sh
sh scripts/build_vm_accel.sh                      # build/libfm_vm_accel.dylib
export FMCP_CACHE_DIR=/path/to/scratch-cache      # with plans/<sha>.v2.json and a knowledge.sqlite
PYTHONPATH=. python scripts/fmdb_bench.py all --runs 3 --released /path/to/released/checkout \
    --snapshot /path/to/filled/snapshot.sqlite
PYTHONPATH=. python scripts/fmdb_vm_check.py --records 4 --timing
PYTHONPATH=. python scripts/fmdb_direct_check.py
python scripts/fmdb_golden_diff.py OLD/snapshot.sqlite NEW/snapshot.sqlite
```
