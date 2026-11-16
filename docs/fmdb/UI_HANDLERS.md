# UI handlers: runtime game state through the game's own UI code

`fm_live_mcp/fmdb/ui_vm.py` (`UiHandlerVM`, a subclass of `PropertyVM`) builds the plugin's
per-screen UI handlers inside the emulator, runs the game-side computation that feeds them,
and reads their properties by key. `ui_handlers.py` has the generic reader and recipes,
`ui_registry.py` the key/label registry and handler tables (data file
`fm_live_mcp/fmdb/data/ui_registry.json.gz`, 161 KB, rebuilt by
`scripts/fmdb_ui_registry_build.py --live`). `scripts/fmdb_ui_read.py` reads a handler from
the command line.

Trust model: values are what the game's UI layer would display, produced by the unmodified
shipped handler code (from the pinned on-disk slice) running on copied live memory.
Anything the emulation cannot produce is `Unavailable(reason)`. Output includes values
derived at call time (grades, feedback sentences, per-player reactions); in a manager
career it is already limited to what the human manager may see (e.g. a player report for an
unscouted player says "Scouting Required").

## ABI (verified on build 27.0.0.2493426)

| Piece | Address (RVA) | Verified behaviour |
|---|---|---|
| `GAME_UI_HANDLER_FACTORY` vtable | 0x54BBBC8 | slot 3 = 0x218258 builds the client handler, slot 5 = 0x21A960 the server; both `(this, UI_RECORD&, x8 -> out pointer)`, switch on the record's `'110 '` value (1..144) |
| `UI_RECORD` | accessors 0x77E714, 0x77F300 | `{begin, end, cap, u32}`; sorted 8-byte `(u32 key, u32 value)` pairs |
| UI object id | packer 0x11B8B0C, resolver 0x111344C | `table type << 24 \| index` (23 bits); a database object returns its own id from virtual +0x88 (x8 result). Team = type 0x18 (Newcastle 0x18000221), person = type 1 + people-table index |
| client base | vtable 0x54EDE08, ctor 0x771C54 | ctor copies the UI_RECORD to +0x18 |
| client slot 4 | get_property | `(this, request, out typed*, inputs)`, key u32 at request+0x44; 0x100-byte zeroed request and empty input bag suffice |
| client slot 16 / 17 | declare / consume input | slot 17 `(this, key, typed*, x3, x4 notify list, x5)`; TEAM_CONFIDENCE consumes `'Tcnf'` |
| server base | vtable 0x54EE008 (7 slots), ctor e.g. 0x21D8E0 | the factory leaves the server's UI_RECORD at +0x10 empty; `UiHandlerVM.build` copies the record header there (the only field written by hand) |
| server slot 2 | get | `(this, key, out typed*, context)`; reads record keys from +0x10 (`0x656BD4` object, `0x77F180` u32) |

Input transfer, TEAM_CONFIDENCE: server slot 2 (0x551D60) with key `'Tcnf'` computes a
TEAM_CONFIDENCE data object (ctor 0x1DB05B8, compute 0x1DC62F4 with flags 0x1FFE),
serialises it into a DATA typed value (0x552508); client slot 17 (0x551A9C) turns the DATA
value into a byte stream (0x437D9C8, DATA traits = registry 0x56D5F18) and deserialises it
into its cache at +0xA0 (0x1DB1ABC). So the club reference is not the input: the record
carries `'Ttea'` (team object id) and the input is the serialised result. When the record
has `'unid'`, `'LiNI'` and `'Hhum'` the server serialises the snapshot stored with a news item
instead (0x265DBC / 0x265C00).

## What the VM adds to PropertyVM (all in ui_vm.py; no change to vm.py/variant.py)

* Baseline state: `commit()` makes the current heap and copy-on-write pages the start of
  every later call (build, then inputs, then one get per key from the same state).
* Owner thread (`thread='owner'`, default): `pthread_self` is the game thread and TLV
  reads go to that thread's own block (key = low half of the live descriptor word at +8,
  TSD at pthread_t+0xE0, checked by tsd[0] == pthread_t). Needed because `get_list`
  (0x14A0FB0) only pages history in on the main thread.
* Game files, read-only: `fseeko/fread/ftello/ferror` on the game's own `FILE*`; the
  descriptor is mapped to a path with `lsof`. Used: `Temporary/player_stats_hist_dt.cmt`,
  `pl_hist_dt.cmt`, `person_record_history_dt.cmt` (FILE_LLIST history) and the plugin's
  `languages.fmf` (text). A FILE with unflushed write data is read as the game would read it:
  the disk file with the buffered bytes at the kernel's file offset, where that is established
  (HISTORIES.md, "Unflushed write data in a game file"); otherwise it is refused.
* Pool allocator on the VM heap: 0x4355A04 / 0x4355ED4 / 0x4356EB8 are intercepted. Using
  the live free lists gave flaky results (the game allocates while pages are copied).
* Unaligned LSE atomics (LDADD/LDCLR/LDEOR/LDSET/SWP, e.g. string refcounts at 0x43D2FBC)
  emulated in an interrupt hook; libc++ `std::sort` on primitive arrays; `strncmp`;
  fixed `gettimeofday`/`localtime_r` (diagnostic log timestamps only) and a per-call
  deterministic `mach_absolute_time`.
* RNG: `rng='copy'` lets code draw from a VM copy of the game thread's RNG (never
  advanced in the game). TEAM_CONFIDENCE draws 8 values (bio text in 0x3E25BC0); with
  `rng='refuse'` the server stops at TLV 0x56C4510. Draws are what the game would draw
  next, not necessarily what an already rendered screen drew; readings report `rng_uses`.
* `fast()`: drops the per-block Python hook (no instruction budget/counts);
  `limit_instructions(n)` sets Unicorn's own per-segment counter instead (about 2.3x slower).

## Speed (11 Nov 2026, Newcastle, board confidence: build + `Tcnf` + 71 keys)

Superseded for the default emulator by `docs/fmdb/UI_FAST.md`: `UiHandlerVM(...)` now builds
the C-accelerated `FastUiHandlerVM` (board confidence warm 1.0 CPU-s) and answers are cached
by read set instead of by game date. The numbers below are the Python-hooked reference
(`FMDB_UI_VM=classic`).

Before: 27-47 s cold (40 s measured; 17 s of it in 4,282 `mem_map` calls, whose cost grows
with the number of mapped regions), 11 s with every page already copied. After: 5-9 s cold
(machine load varies), 2.2-4 s warm, identical readings for all 71 keys. What bought it:

* whole `__TEXT` run mapped once from the slice (was ~1,150 single-page maps);
* live data faulted in aligned 512 KiB windows, read as 64 KiB items in one
  `LiveMemory.read_many_status` request (~1,100 maps; 1 MiB windows were no faster and
  hold 30 % more memory);
* imports whose model returns a constant (locks, free/delete) run as `mov x0,#c; ret` on
  the private TRAP page through VM-private overlays of their pointer slots (240,000
  Python calls per computation gone); other modelled imports reached through a pointer
  slot (`__tlv_bootstrap` thunks, `___chkstk_darwin`) go to hooked TRAP trampolines
  instead of faulting on the libsystem address and restarting `emu_start` (4,400
  restarts gone);
* register access through the C API with one buffer, and the copy-on-write store hook as
  a direct C callback that returns at once for already-copied pages.

The MCP tools keep one emulator per (save, game date, save count) for at most 15 minutes
and cache answers on disk (`ui_cache.py`), so a repeated question costs ~0.4 s.

## MCP tools (`ui_tools.py`)

`fm_ui_schema` (offline registry: buildable types, input keys, documented record fields,
key search), `fm_ui_read` (any buildable type with explicit UI_RECORD inputs; instruction
and time budgets), `fm_get_board_confidence` (shaped TEAM_CONFIDENCE answer), and, when
`ui_recipes_news` / `ui_recipes_person` exist, `fm_get_inbox`, `fm_get_calendar`,
`fm_get_player_status`, `fm_get_club_vision`. Cache: `<FMCP_CACHE_DIR or
/Volumes/4TB Private/Offloaded/Agent Work/fmcp-source-cache>/fmdb/<save key>/ui/<game
date>/`, keyed by kind and inputs, invalid for another save count or plugin build, other
dates pruned on write, failed or budget-stopped computations not stored, `fresh=true`
recomputes. RNG: with the VM copy of the generator state (TLV 0x56C44F8) perturbed in six
runs, no TEAM_CONFIDENCE key changed although each run drew 8 numbers.

## Recipes and coverage (live, 11 Nov 2026, Newcastle, 10 Dec 2030)

| Handler (type) | UI_RECORD | Inputs | Keys: value / unset / unavailable | Time |
|---|---|---|---|---|
| TEAM_CONFIDENCE (114) | `Ttea` = team id | `Tcnf` (server, 130 M insns) | 45 / 26 / 0 of 71, identical in two runs | build+input 27-47 s, keys 0.1-120 ms |
| PLAYER_REPORT (75) | `Pers` = person id, `PbPY` = manager person id | `anli`, `scri`, `scrp` all ok | 28 / 27 / 0 of 55 | 0.3 s total |
| TEAM_TRAINING (128) | `Ttea`, `Hhum` | `TiSc` fails | 26 / 23 / 1 of 50 | 0.3 s |
| NEWS_ITEM (70) | `huma` = manager person index, `unid` = item+0x90 | 10 inputs ok | 0 / 47 / 0 (no item found) | - |
| CALENDAR (9) | `Ttea`, `Hhum` | all 9 fail | - | - |
| PERSON keys | PERSON_UI_HANDLER is only a base class (of SQUAD_SELECTION_PLAYER, type 106) | - | not read | - |

TEAM_CONFIDENCE grades are integers: 5 = C, 6 = C+, 7 = B-, 8 = B, 9 = B+, 11 = A (matched
against the Board screen; 0 = no grade yet). Supporter grades are a separate 1..6 scale
where lower is better (1 very pleased, 3 pleased/happy, 4 satisfied, 6 disappointed).
Strings carry link markup `\x01<base64 link record>\x02<text>\x01`; `plain_text()` keeps
the display text. Nested record references come back as `UiRecord` (`{'110 ': type,
'dref': object id}`). `Debug*Score` keys are null in a release build.

Oracle comparison with the user's Board screens: all six board grades (B, C+, C, B, C+, B+),
the overall/vision/match/recruitment/tactics/squad sentences, the board and supporter
highlights and criticisms, the tactics feedback lines, all five signings (board grades
B+, B+, B-, B+, A, supporter reactions, wages £64.06K/£225K/£150K/£81.76K/£91.8K) and the
supporter per-player reactions shown match. Fees (`K0qE` 5,340,963 for Huber vs £5.25M
shown) do not match the displayed figure; the unit or basis of `K0qE` is not established.

## Blockers

* TEAM_TRAINING input `TiSc`: null dereference at 0x43FEB48 (server slot 2 0x581F70 path);
  the unit records then all read "Goalkeeping Unit" and schedule keys are unset.
* CALENDAR: every input stops at 0x43CCCF0 (`str x0, [x8]`, an x8-result helper) reached
  directly from the server call, i.e. the object the server factory returns for type 9 is
  not called through the slot this code assumes; not resolved.
* NEWS_ITEM: the inbox is not at HUMAN+0x350 for the object `'Hhum'`->virtual 0x6F0 returns
  (vector empty), so no `unid` was found; the item lookup is 0x12D125C (sorted by +0x90).
* PERSON runtime keys (happiness, promises, interest: 59 labels in PERSON_UI_HANDLER slot 4,
  e.g. `HappinessPositives` HPPo, `PromisesMadeByManager` Pmbm, `ActiveInterestedClubsList`
  OMVS): the record key that selects the person for DATABASE_RECORD_UI_HANDLER subclasses
  was not established.
* Factory gaps: types 1, 28, 102, 113 make no client; 101 and one more need
  `CFStringCreateWithCStringNoCopy` (0x4429450).
* Speed: the per-store copy-on-write hook stays (Unicorn does not retry a store after a
  write-protection handler returns true); it is now a direct C callback (see Speed).
