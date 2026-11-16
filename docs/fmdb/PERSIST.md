# Persisted native state through the game's own save code

`fm_live_mcp/fmdb/persist.py`, `persist_stream.py`, `sources/native_state.py`, tools `fm_native_schema` and
`fm_native_read`, schema builder `scripts/fmdb_persist.py`, data `fm_live_mcp/fmdb/data/persist_routes.json`
and `persist_schema.json.gz`.

## Route

`SAVE_SYSTEM` (vtable 0x55F4AC8) slot function 0x2583DCC handles the save messages. It calls two walkers:
0x2562300 (load: opens each manager's chunk with 0x43197F4 and calls the manager's load function) and
0x256D728 (save). The save walker hands each manager singleton to that manager's own save function:

    save(manager [+ offset | *offset], holder)       holder: x29-0xB8, a cell -> siapplication::ARCHIVE_ITEM

A static scan of the walker (every direct `bl f` whose x1 is the holder and whose x0 derives from a manager
global root) gives 44 routes for 42 roots (`persist_routes.json`; TRANSFER_MANAGER is saved as two calls,
`+0x18` and `*0x7E0`; REGENERATION_MANAGER and MEDIA_MANAGER as `+0x18`). Each route's call site is checked to
be `bl function` in the loaded plugin before it runs.

## Stream interface (what save code writes to)

Save code never touches a file itself. It talks to two objects:

| Object | Call | Meaning |
|---|---|---|
| archive item (`ARCHIVE_ITEM`, vtable 0x5694CE0) | virtual +0xE8 (slot 29) `child(this, key*, name, x8 out)` | a named child item (".dat"); the name is the C-string literal just turned into a sicore string (0x4388EF8) |
| | 0x4319C00 `open_writer(tag*, &item, version, mode, x8 out)` | an output stream for the item; tag is 8 bytes ('NULL' 0x4E554C4C + version word 0x0801) |
| output stream (`sicore::OUTPUT_STREAM` family, e.g. `MEMORY_OUTPUT_STREAM` 0x56980B8) | virtual +0x30 (slot 6) `write(this, buffer, length)` -> bytes written | every value: integers, dates, strings (u32 length + characters), vectors (u32 count + elements), nested objects |
| | +0x10 / +0x18 size / position, +0x20 seek, +0x28 flags; error word at object +0x10 | save code tests the error word after each write |

There are no typed write calls: integers, floats, dates and references are all stored to a stack buffer and
written with their width. Types therefore come from the width and from the helper that wrote them.

## Recorder

`persist_stream.SaveRecorderVM` (FastVM; `SaveRecorderClassicVM` on PropertyVM when the accelerator is not
built) answers those calls itself:

* the archive item and the writer are VM-private objects whose vtable slots point into a VM-private page of
  `ret` instructions; a code hook on that page runs the slot's model. Unmodelled slots stop the call with
  `save stream: ... slot N not modelled`.
* 0x4319C00 is the one shipped function replaced: it would wrap the item's file stream; the model returns a
  recording writer bound to the item.
* every `write` is kept in order with the writer, its offset in the writer, the bytes, the return addresses
  on the frame-pointer chain and the innermost save function active.
* save functions are found at run time: a function entered (block hook at an `LC_FUNCTION_STARTS` address)
  with a recorder item or writer, or a cell holding one, in x1 or x2 is a save function of the object in x0
  (a `Call`, nested by stack pointer). The object's RTTI gives its class.
* provenance (optional, `provenance=True`): a Python hook on every load from the live-page pool and every
  store to VM-private memory. A write whose buffer is live memory came straight from that address
  (`buffer`). Otherwise the store that put each byte range into the buffer is matched with the most recent
  load (within 4,096 loads) that read the same value (`load`, with the load's pc), else `computed`. FastVM's
  hooks see pool addresses; the guest address is rebuilt from the load instruction's base register and
  immediate (`persist_stream._load_form`), checked against the page offset.

Nothing reaches the game or a file:

* the save runs on copied pages; stores are copy-on-write inside the VM;
* `persist_stream.SAVE_REFUSED`: `fopen`, `open`, `mkdir`, `opendir`, `stat`, `access`, `rename`, `unlink`,
  `remove`, `fwrite`, `write`, `pwrite`, `ftruncate`, `fsync` stop the call;
* reads through a FILE* the game already holds open (`fseeko`/`fread`/`ftello`/`ferror`) are served read-only
  by vm.py's stdio models for `.fmf` and `Temporary/*_dt.cmt` (as everywhere in the reader) and, in the
  recorder only, `Temporary/*.obs` (the game's archive files: retired-person history, news pages, season
  summaries, which the save copies into the save); every file read is listed in `files_read`;
* `mach_absolute_time` (progress timing of long saves) answers a VM-private clock from the instruction count
  (marked).

## Offsets and labels

For each save function the fields are keyed by (write site in that function, helper functions between it and
`write`, width): loops repeat a key, so a key written more than once per object is a container. A nested save
function call is keyed by (function, call site); its objects' classes are the element classes.

Offsets, in order of proof:

* `buffer`: save code wrote straight from the object (`write(&obj->field, n)`);
* `load`: the stored value came from a load at that address (provenance run);
* `value`: the same bytes sit at exactly one offset of the object on every instance with a nonzero value;
* `caller<k>+0x..`: the address is in the object of the k-th enclosing save function (save code that builds a
  temporary struct on the stack from a record's fields).

Labels are only from evidence: `rtti` (element class of a nested object) and `decoder:<module>` (an existing
hand-built decoder reads that class and offset). Everything else is `field_<n>` with type and offset.

## Checks against the hand-built decoders (`scripts/fmdb_persist_check.py`)

Per object (one object can be written by several save functions, base class then derived), for each offset a
hand-built decoder reads: `agree` when a write of the object came from exactly that address and the bytes are
the live bytes; for a pointer, when a write came from inside the pointed-to object. Game date 2030-12-13.

| Decoder | Objects | Result |
|---|---|---|
| `live_transfer_offers` (TRANSFER_MANAGER+0x18, 80 M instructions with provenance, 1,167,514 writes) | 2,036 FULL_TRANSFER_OFFER, 2,009 LOAN_OFFER, 10 TRADE_OFFER, 5 B_CLUB_MOVE_OFFER, 1 TRIAL_OFFER | amount +0x58 and state +0x8D agree on every object (one FULL_TRANSFER_OFFER was cut by the timeout); person +0x38 and teams +0x40/+0x48: the save writes the pointee's +0x8 (the record's unique id) on every object; the four dates +0x70..+0x7C agree, each written as two u16 (low half at +0, high half at +2) |
| `live_state.news_item` (NEWS_MANAGER, 30 M instructions) | 90 items of 37 news classes | unique id +0x90 and flags +0x98 agree on all; the packed date +0x88 agrees, written as two u16 |

Disagreements and limits:

* offer +0x50 ("team 3" in `live_transfer_offers`): for TRADE, TRIAL and B_CLUB_MOVE offers the save writes the
  pointee's +0x8 (a record reference, as the decoder assumes); for FULL_TRANSFER_OFFER (928 non-null of 2,036) and
  LOAN_OFFER (2,009) it writes the pointee's +0x178, +0x230 and +0x2E8, never +0x8: that object is not saved as a
  record reference by these classes' save code, so "team 3" is unproven for them by the save route. It is
  proven another way: the pointer resolves to a TEAM record, and on 26 Newcastle transfers and loans that are
  both an offer and a row of the club's transfer history screen (`club_transfer_history`, CLUB_UI_HANDLER
  PTin/PTou) +0x40 is the buying (borrowing) team and +0x50 the selling (loaning) team, none swapped
  (13 Dec 2030); `transfer_offer_view` names them `buying_team_idx` / `selling_team_idx`.
* contracts (`contracts.py`: FULL/BASIC/LOAN/TRIAL_CONTRACT +0x8, +0x10, +0x18) and club finance
  (`club_finance`: CLUB_FINANCE +0x814): no save route writes objects of those classes. They hang off database
  records (PERSON - 0x98, CLUB + 0x150), and the database tables have no (manager, holder) save call in the walker
  (`persist_routes.json` "not_routed"); CONTRACT_MANAGER writes 156 + 498 vector entries and 30 objects (negotiations, inferred), not the
  signed contracts, and FINANCE_MANAGER 183 objects of 4 classes, not CLUB_FINANCE.
* fixtures (`fixture_tables`): GAME_RULE_GROUP_MANAGER writes `sicomps::FIXTURE_RESULT`, league and cup stages
  and settings; not compared with the fixture decoder in this round.
* injuries (`player_health`: injury entry +0x8 definition, +0x20 start date): INJURY_MANAGER's save writes 1.1 M
  values from two save functions and no object of its own per injury (the entries are written inline from
  vectors), so the per-object check does not apply; its offsets are in the schema as `+0x..[]` vector fields.

## Results

Totals on 2030-12-13 (45 save roots): 29.9 M writes, 129.9 MB written, 1,462 save functions, 5.0 M objects
handed to a save function, 401 classes with written objects, 16,424 value fields in write order. Four roots
stop at the recorder's 4,000,000-write cap (`persist.MAX_WRITES`, a memory bound): GAME_RULE_GROUP_MANAGER
(competitions, stages, fixture results; 15.2 M writes in 371 M instructions when uncapped, 314 s),
NEWS_MANAGER, TRANSFER_MANAGER+0x18 and TEAM_CONTAINER_RECORD_MANAGER. Their schema holds the classes written
before the cap.

The per-root table and the per-class list (written by `scripts/fmdb_persist.py --markdown`) follow at the end.

## Using it

* `fm_native_schema()`: every root (status, writes, bytes, refusal) and every class with its save function and
  object count. `fm_native_schema(root="INJURY_MANAGER")` or `search="OFFER"`: the field lists.
* `fm_native_read(cls="CONTRACT_MANAGER")`: one root in save order, nested to `depth`, `limit` fields.
  `fm_native_read(cls="LOAN_OFFER", key="0")` or `key="0x7a90c00000"`: one object (the root's save is run,
  cached 120 s, and that object's part returned). A database record written as a reference carries
  `ref: {table, idx}`.
* SQL: `sources/native_state.py` adds up to 80 lazy tables `native_<class>` (classes with at least 20 objects
  and two once-per-object value fields; database records written as references are left out because their
  table has them). A table is built the first time a statement names it, from one fast emulated save of its
  root (fm_db_query `SELECT * FROM native_full_transfer_offer LIMIT 2`: 96.9 s on a cold engine under load
  13, of which the TRANSFER_MANAGER+0x18 save is most). Manager policy `never` (withheld).

## Costs

Fast recorder (FastVM, block hook in Python for the save-function entry check): CONTRACT_MANAGER 0.09 s
(40,782 instructions), HUMAN_NON_PLAYER_MANAGER 1.3 s (2.7 M), SHORTLIST_MANAGER 19 s (160 M), PRESS_CONFERENCE
77 s (2.7 M writes), NEWS_MANAGER 163-194 s to the cap; load average 6-13 while other lanes ran. The classic
recorder (PropertyVM) maps every page on its own and ran HUMAN_NON_PLAYER_MANAGER in 58 s (same 41,146 writes,
same 126,063 bytes). Provenance hooks cost 5-30x; the census runs them for the first 5 M instructions of each
root and merges the offsets by field key.

## Gaps and blockers

* Write cap (four roots above): the recording keeps every write in memory (about 140 bytes each). Next route:
  a streaming analysis that aggregates the schema without keeping writes, and per-table rows built from the
  calls of one element function only.
* Unrouted walker roots (`persist_routes.json` "not_routed"): PERSON_PROGRESSION_MANAGER is only named by the
  walker (no save call); UNLOCKABLE_MANAGER and SETTINGS_MANAGER are read for conditions; the six database
  tables and the sicore/sidistribution/sitranslation managers are loaded outside the per-manager blocks. Next
  route: emulate the walker 0x256D728 itself on the live SAVE_SYSTEM (it opens files through 0x6EC918 slot
  +0xA8 and +0x48, which the recorder would have to answer as it answers 0x4319C00).
* Offsets: of 16,424 value fields, 11,124 have a proven object offset: 9,609 straight from object memory
  (`buffer`), 1,067 from a load, 448 by value. 2,680 are buffers outside the objects of the save functions
  (element arrays of vectors held elsewhere, string characters), 674 come from loads outside those objects or
  from a callee whose value differs from the bytes at the offset on some object, 1,566 have no provenance in the
  first 5 M instructions, 319 are computed (counts, converted values). A load-proven offset is kept only when the
  bytes there equal the written bytes on every sampled object (up to 400).
* Labels: 39 fields carry a database getter key (verified single-load direct plans of the record class at the
  same offset of the table pointer), 14 a hand-built decoder label; everything else is `field_<n>` with type
  and offset. Next route: UI handler traces joined on (class, offset), and the load functions (walker
  0x2562300 calls each manager's load, e.g. AGENT_MANAGER 0x259E0C4) traced for the member each value is stored
  to.
* Persisted classes never instantiated in this career (most of the 471 unreached persisted rows are response
  objects created by user actions) cannot be read from memory until one exists.

## Census tables

Census: game date 2030-12-13, build 27.0.0.2493426, 2026-11-12T06:01:06+0000, 1974.1 s, load average 6.1, 6.9, 8.5.

| Root | Status | Writes | Bytes | Save functions | Objects (classes) | Value fields (with offset) | Fast s | Refusal |
|---|---|---|---|---|---|---|---|---|
| GAME_RULE_GROUP_MANAGER | refused | 4,000,000 | 13,838,043 | 133 | 475,061 (52) | 2,617 (1,603) | 102.15 | save stream: write cap reached (the recording holds the first part of the save) (4000000) |
| HUMAN_NON_PLAYER_MANAGER | ok | 41,146 | 126,063 | 61 | 4,875 (28) | 751 (580) | 1.84 |  |
| NEWS_MANAGER | refused | 4,000,000 | 10,964,950 | 425 | 702,079 (186) | 5,180 (3,857) | 194.12 | save stream: write cap reached (the recording holds the first part of the save) (4000000) |
| TRANSFER_MANAGER+0x18 | refused | 4,000,000 | 22,289,432 | 40 | 605,993 (10) | 608 (389) | 118.37 | save stream: write cap reached (the recording holds the first part of the save) (4000000) |
| TRANSFER_MANAGER*0x7e0 | ok | 13 | 38 | 3 | 3 (1) | 13 (9) | 0.04 |  |
| SHORTLIST_MANAGER | ok | 601,467 | 3,747,282 | 9 | 20,206 (3) | 497 (66) | 20.77 |  |
| TEAM_CONTAINER_RECORD_MANAGER | refused | 4,000,000 | 12,797,948 | 42 | 1,006,032 (28) | 277 (216) | 149.45 | save stream: write cap reached (the recording holds the first part of the save) (4000000) |
| TACTICS_MANAGER | ok | 1,122,978 | 3,638,566 | 66 | 393,937 (14) | 377 (287) | 77.05 |  |
| REGENERATION_MANAGER+0x18 | ok | 104,550 | 543,561 | 18 | 5,026 (6) | 130 (102) | 2.92 |  |
| RETIREMENT_MANAGER | ok | 12,772 | 32,330 | 5 | 2,261 (2) | 39 (17) | 0.39 |  |
| DATABASE_ANALYSER | ok | 6 | 17 | 1 | 1 (1) | 6 (5) | 0.01 |  |
| EDIT_SESSION_MANAGER | ok | 37,620 | 119,535 | 101 | 5,491 (31) | 962 (740) | 2.82 |  |
| FOG_OF_WAR_MANAGER | ok | 5,625 | 14,082 | 4 | 4 (2) | 29 (8) | 0.12 |  |
| INJURY_MANAGER | ok | 1,105,704 | 3,547,442 | 2 | 2 (1) | 50 (22) | 21.73 |  |
| TRAINING_MANAGER | ok | 128,643 | 172,812 | 32 | 21,957 (14) | 217 (151) | 3.79 |  |
| TRAINING_CAMP_MANAGER | ok | 6,423 | 16,458 | 9 | 1,711 (3) | 35 (28) | 0.21 |  |
| SCOUT_MANAGER | ok | 195,068 | 527,905 | 66 | 36,341 (25) | 555 (406) | 7.34 |  |
| AWOL_MANAGER | ok | 1,302 | 3,700 | 8 | 150 (3) | 68 (27) | 0.05 |  |
| AWARD_MANAGER | ok | 62,460 | 227,500 | 24 | 9,488 (11) | 186 (95) | 1.69 |  |
| FINE_MANAGER | ok | 392 | 1,161 | 6 | 51 (3) | 49 (15) | 0.03 |  |
| CONTRACT_MANAGER | ok | 3,140 | 6,781 | 9 | 30 (3) | 61 (28) | 0.04 |  |
| PERSON_RECORD_MANAGER | ok | 1,793,202 | 5,643,861 | 44 | 209,679 (19) | 346 (198) | 35.85 |  |
| OFFICIAL_MANAGER | ok | 56,193 | 173,538 | 4 | 4,158 (2) | 76 (9) | 1.83 |  |
| AGENT_MANAGER | ok | 88 | 352 | 1 | 1 (1) | 3 (1) | 0.01 |  |
| DISPUTE_MANAGER | ok | 1 | 4 | 2 | 2 (1) | 1 (0) | 0.0 |  |
| FINANCE_MANAGER | ok | 639 | 1,783 | 9 | 183 (4) | 52 (46) | 0.02 |  |
| NETWORK_COMPETITION_MANAGER | ok | 97 | 215 | 4 | 19 (2) | 42 (34) | 0.0 |  |
| SIMULATED_STATS_MANAGER | ok | 322,153 | 898,217 | 5 | 91,837 (3) | 22 (16) | 8.08 |  |
| HALL_OF_FAME_MANAGER | ok | 278,403 | 726,836 | 6 | 41,134 (1) | 93 (89) | 6.2 |  |
| BACKROOM_ADVICE_MANAGER | ok | 190,909 | 556,226 | 48 | 34,397 (30) | 188 (125) | 7.7 |  |
| INTERACTION_MANAGER | ok | 1,430,728 | 3,197,474 | 20 | 232,215 (7) | 201 (83) | 47.51 |  |
| PRESS_CONFERENCE_MANAGER | ok | 2,675,960 | 6,554,648 | 33 | 424,758 (11) | 437 (315) | 79.21 |  |
| JOB_CENTRE_MANAGER | ok | 4,561 | 9,710 | 8 | 861 (5) | 39 (31) | 0.19 |  |
| TEAM_TALK_MANAGER | ok | 741 | 2,381 | 13 | 189 (4) | 72 (43) | 0.03 |  |
| BOARD_TAKEOVER_MANAGER | ok | 1,823 | 4,524 | 11 | 246 (3) | 97 (59) | 0.04 |  |
| FINANCIAL_FAIR_PLAY_MANAGER | ok | 46 | 118 | 8 | 8 (3) | 46 (38) | 0.01 |  |
| FEEDER_CLUB_MANAGER | ok | 2,950 | 9,008 | 4 | 1,048 (2) | 11 (8) | 0.07 |  |
| CHALLENGE_MANAGER | ok | 10 | 17 | 1 | 1 (1) | 10 (8) | 0.0 |  |
| MEDIA_MANAGER+0x18 | ok | 1,028,164 | 2,507,321 | 42 | 223,137 (9) | 447 (294) | 71.54 |  |
| MORALE_MANAGER | ok | 7 | 25 | 1 | 1 (1) | 7 (7) | 0.02 |  |
| MATCHDAY_MANAGER | ok | 5,608 | 14,682 | 16 | 695 (7) | 139 (98) | 0.19 |  |
| PLAY_FIXTURE_MANAGER | ok | 137,723 | 455,321 | 54 | 21,051 (13) | 656 (485) | 4.16 |  |
| DYNAMICS_PIVOTAL_MOMENTS_MANAGER | ok | 5 | 16 | 1 | 1 (1) | 5 (3) | 0.02 |  |
| MATCH_STATS_MANAGER | ok | 14,424 | 29,800,956 | 4 | 13 (2) | 24 (14) | 0.19 |  |
| MANAGER_MANAGER | ok | 2,493,864 | 6,767,580 | 59 | 468,269 (14) | 703 (469) | 78.83 |  |

401 classes have objects written by a save function:

| Class | Root | Save function | Objects | Value fields | Offsets proven | Labelled |
|---|---|---|---|---|---|---|
| ACCUMULATIVE_BAN_NEWS | NEWS_MANAGER | 0x3271170 | 21 | 3 | 3 | 0 |
| AGENT_MANAGER | AGENT_MANAGER | 0x259e31c | 1 | 3 | 1 | 0 |
| ASK_TO_PICK_FILTER | HUMAN_NON_PLAYER_MANAGER | 0x11efb60 | 14 | 7 | 5 | 0 |
| ASK_TO_PICK_PICKING_RULES_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x11f0db0 | 19 | 14 | 14 | 0 |
| ASSIGNMENT_UPDATE_ENTRY | NEWS_MANAGER | 0x3972aac | 3 | 4 | 4 | 0 |
| ATTENDANCE_RECORD | NEWS_MANAGER | 0xf99868 | 4 | 2 | 2 | 0 |
| AVERAGE_ATTENDANCE_RECORD | GAME_RULE_GROUP_MANAGER | 0xf9ad84 | 560 | 3 | 3 | 0 |
| AVERAGE_ATTENDANCE_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xf9ad84 | 3,536 | 3 | 3 | 0 |
| AWARD_MANAGER | AWARD_MANAGER | 0x25b8bbc | 1 | 15 | 0 | 0 |
| AWARD_NEWS | NEWS_MANAGER | 0x306fb24 | 17 | 10 | 8 | 0 |
| AWARD_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x220b254 | 9 | 1 | 1 | 0 |
| AWARD_WITH_PERSON_ARRAY_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x220c014 | 1 | 3 | 2 | 0 |
| AWARD_WITH_PERSON_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x220d41c | 2 | 6 | 6 | 0 |
| AWOL_MANAGER | AWOL_MANAGER | 0x25d0364 | 1 | 7 | 1 | 0 |
| BACKROOM_ADVICE_MANAGER | BACKROOM_ADVICE_MANAGER | 0x25d95e0 | 1 | 3 | 0 | 0 |
| BACKROOM_STAFF_PLAYER_ALERT_NEWS | NEWS_MANAGER | 0x3574aec | 1 | 7 | 7 | 0 |
| BASE_OBSERVATION | NEWS_MANAGER | 0x39ee4d4 | 12 | 1 | 0 | 0 |
| BEST_YOUTH_PRODUCTION_NEWS | NEWS_MANAGER | 0x363dc60 | 1 | 4 | 1 | 0 |
| BOARD_COMP_WIN_NEWS | NEWS_MANAGER | 0x374dabc | 1 | 14 | 13 | 0 |
| BOARD_TAKEOVER_IN_TALKS_NEWS | NEWS_MANAGER | 0x30b077c | 1 | 15 | 14 | 0 |
| BOARD_TAKEOVER_MANAGER | BOARD_TAKEOVER_MANAGER | 0x25e836c | 1 | 28 | 0 | 0 |
| BOARD_TAKEOVER_RUMOUR_MILL_NEWS | NEWS_MANAGER | 0x30a0670 | 4 | 11 | 11 | 0 |
| BOARD_TAKEOVER_TALKS_PROGRESS_NEWS | NEWS_MANAGER | 0x30b8298 | 1 | 17 | 17 | 0 |
| BUILDUP_HYPE_AWARD_NEWS | NEWS_MANAGER | 0x3077fb4 | 2 | 1 | 0 | 0 |
| B_CLUB_MANAGER_DETAILS | MANAGER_MANAGER | 0x25976c0 | 13 | 10 | 4 | 0 |
| B_CLUB_MOVE_OFFER | TRANSFER_MANAGER+0x18 | 0x181eb2c | 702 | 1 | 1 | 0 |
| CHALLENGE_MANAGER | CHALLENGE_MANAGER | 0x25f6b60 | 1 | 10 | 8 | 0 |
| CHANGE_PLAYER_TARGETS_FREQUENCY_RESPONSE_OBJECT | NEWS_MANAGER | 0x32fe940 | 1 | 1 | 1 | 0 |
| CHANGE_SCOUTING_MEETING_FREQUENCY_RESPONSE_OBJECT | NEWS_MANAGER | 0x364d270 | 1 | 1 | 1 | 0 |
| CLUB_AWARD_DATA | AWARD_MANAGER | 0x198e128 | 14 | 1 | 0 | 0 |
| CLUB_HUMAN_MANAGER_DETAILS | MANAGER_MANAGER | 0x2595138 | 1 | 15 | 7 | 0 |
| CLUB_MANAGER_APPOINTED_NEWS | NEWS_MANAGER | 0x338dea0 | 2 | 41 | 34 | 0 |
| CLUB_MANAGER_APPOINTED_NEWS | NEWS_MANAGER | 0x337ec78 | 2 | 15 | 14 | 0 |
| CLUB_MANAGER_DEPARTURE_NEWS | NEWS_MANAGER | 0x336be00 | 4 | 9 | 9 | 0 |
| CLUB_MANAGER_DEPARTURE_NEWS | NEWS_MANAGER | 0x334272c | 4 | 14 | 14 | 0 |
| CLUB_MANAGER_DETAILS | MANAGER_MANAGER | 0x258b2a8 | 676 | 40 | 37 | 0 |
| CLUB_RETAINED_LIST_PUBLICATION_NEWS | NEWS_MANAGER | 0x32547b8 | 63 | 9 | 6 | 0 |
| CLUB_STATURE_CONFIDENCE | NEWS_MANAGER | 0x1d8b88c | 1 | 9 | 8 | 0 |
| CLUB_STATURE_CONFIDENCE | MANAGER_MANAGER | 0x1d8b88c | 1 | 9 | 8 | 0 |
| COMPETITION_LEVEL_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x231fa08 | 14 | 1 | 1 | 0 |
| COMPETITION_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x220fb98 | 11 | 4 | 4 | 0 |
| COMPETITION_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x221314c | 7 | 3 | 3 | 0 |
| COMPETITION_TYPE_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x2320128 | 7 | 1 | 1 | 0 |
| COMPETITION_WITH_START_END_DATE_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x221541c | 3 | 4 | 4 | 0 |
| COMP_MATCHDAY_PREVIEW_NEWS | NEWS_MANAGER | 0x3604650 | 6 | 4 | 3 | 0 |
| COMP_PITCH_AND_CONDITIONS_NEWS_ITEM | NEWS_MANAGER | 0x31861ac | 104 | 9 | 7 | 0 |
| COMP_PRIZE_MONEY_NEWS | NEWS_MANAGER | 0x30eee0c | 1 | 12 | 11 | 0 |
| COMP_QUALIFICATION_NEWS | NEWS_MANAGER | 0x3178e60 | 17 | 3 | 3 | 0 |
| COMP_WIN_NEWS | NEWS_MANAGER | 0x374ac48 | 1 | 1 | 1 | 0 |
| COMP_WIN_NEWS | NEWS_MANAGER | 0x374acbc | 1 | 14 | 13 | 0 |
| CONTRACT_DECISION_NEWS | NEWS_MANAGER | 0x3231e78 | 269 | 40 | 40 | 0 |
| CONTRACT_MANAGER | CONTRACT_MANAGER | 0x26047d0 | 1 | 15 | 3 | 0 |
| CUP_COMPETITION_SUMMARY_NEWS | NEWS_MANAGER | 0x31a844c | 2 | 3 | 3 | 0 |
| CUP_DRAW_SUMMARY_NEWS | NEWS_MANAGER | 0x31733d8 | 3 | 9 | 3 | 0 |
| CUP_DRAW_WARNING | NEWS_MANAGER | 0x315c8b8 | 6 | 18 | 15 | 0 |
| CUP_DRAW_WARNING_RESPONSE | NEWS_MANAGER | 0x31592a4 | 1 | 3 | 2 | 0 |
| CUP_FATE_DECIDED_NEWS | NEWS_MANAGER | 0x314be24 | 60 | 20 | 16 | 0 |
| CUP_ROUND_DRAW_NEWS | NEWS_MANAGER | 0x3119c80 | 62 | 10 | 10 | 0 |
| CUP_STAGE_PREVIEW_NEWS | NEWS_MANAGER | 0x31f6924 | 5 | 5 | 4 | 0 |
| DATABASE_ANALYSER | DATABASE_ANALYSER | 0x265bab0 | 1 | 6 | 5 | 0 |
| DECLARE_INTEREST_IN_MANAGER_JOB_REACTION_NEWS | NEWS_MANAGER | 0x3338610 | 15 | 7 | 7 | 0 |
| DISPUTE_MANAGER | DISPUTE_MANAGER | 0x2666838 | 1 | 0 | 0 | 0 |
| DRAFT_SEARCH_PERSON_FILTER | NETWORK_COMPETITION_MANAGER | 0x435f204 | 6 | 3 | 0 | 0 |
| DRAFT_SEARCH_PERSON_FILTER | NETWORK_COMPETITION_MANAGER | 0x1223974 | 6 | 1 | 1 | 0 |
| DRAFT_SEARCH_PERSON_FILTER | NETWORK_COMPETITION_MANAGER | 0x744714 | 6 | 7 | 3 | 0 |
| DYNAMICS_PIVOTAL_MOMENTS_MANAGER | DYNAMICS_PIVOTAL_MOMENTS_MANAGER | 0x2668da8 | 1 | 5 | 3 | 0 |
| EDIT_SESSION_MANAGER | EDIT_SESSION_MANAGER | 0x266c388 | 1 | 4 | 0 | 0 |
| ELIGIBILITY_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x121922c | 7 | 8 | 8 | 0 |
| EXTENDED_COMP_RECORDS | GAME_RULE_GROUP_MANAGER | 0xf8fee0 | 280 | 19 | 18 | 0 |
| EXTRA_COMPETITION_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x2219cb0 | 1 | 1 | 1 | 0 |
| FANS_PLAYER_OF_THE_YEAR | TEAM_CONTAINER_RECORD_MANAGER | 0xfaaa80 | 3,536 | 2 | 2 | 0 |
| FASTEST_GOAL_RECORD | GAME_RULE_GROUP_MANAGER | 0xfaaef0 | 280 | 2 | 2 | 0 |
| FASTEST_GOAL_RECORD | NEWS_MANAGER | 0xfaaef0 | 9 | 2 | 2 | 0 |
| FASTEST_GOAL_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xfaaef0 | 3,536 | 2 | 2 | 0 |
| FEEDER_CLUB_MANAGER | FEEDER_CLUB_MANAGER | 0x2675f58 | 1 | 3 | 0 | 0 |
| FINAL_WARNING_NEWS | NEWS_MANAGER | 0x3717004 | 20 | 6 | 4 | 0 |
| FINANCE_MANAGER | FINANCE_MANAGER | 0x268ba48 | 1 | 3 | 0 | 0 |
| FINANCIAL_FAIR_PLAY_MANAGER | FINANCIAL_FAIR_PLAY_MANAGER | 0x26b9d84 | 1 | 1 | 0 | 0 |
| FINE_MANAGER | FINE_MANAGER | 0x26bbba4 | 1 | 9 | 0 | 0 |
| FINE_NEWS | NEWS_MANAGER | 0x328f704 | 1 | 13 | 13 | 0 |
| FIXTURE_TO_PLAY_QUICK | PLAY_FIXTURE_MANAGER | 0x2940790 | 32 | 2 | 1 | 0 |
| FIXTURE_TO_PLAY_QUICK | PLAY_FIXTURE_MANAGER | 0x2940044 | 32 | 7 | 5 | 0 |
| FOG_OF_WAR_MANAGER | FOG_OF_WAR_MANAGER | 0x26c2c48 | 1 | 2 | 0 | 0 |
| FULL_TRANSFER_OFFER | TRANSFER_MANAGER+0x18 | 0x1865704 | 16,438 | 34 | 33 | 10 |
| FULL_TRANSFER_OFFER | TRANSFER_MANAGER+0x18 | 0x1839460 | 11,942 | 8 | 6 | 0 |
| FUTURE_MANAGER_DEPARTURE_NEWS | NEWS_MANAGER | 0x33d31b8 | 1 | 6 | 5 | 0 |
| FUTURE_TRANSFER_NEWS | NEWS_MANAGER | 0x37f4668 | 14 | 16 | 12 | 0 |
| GAMES_IN_A_SEASON_RECORD | GAME_RULE_GROUP_MANAGER | 0xface34 | 1,680 | 3 | 3 | 0 |
| GAMES_IN_A_SEASON_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xface34 | 21,216 | 3 | 3 | 0 |
| GAME_COMP_STATS | GAME_RULE_GROUP_MANAGER | 0xf39404 | 141 | 61 | 30 | 0 |
| GAME_COMP_STATS | GAME_RULE_GROUP_MANAGER | 0x3be1e90 | 141 | 5 | 2 | 0 |
| GAME_MATCH_DATABASE_HELPER | NEWS_MANAGER | 0x4ac533c | 498 | 12 | 1 | 0 |
| GAME_MATCH_DATABASE_HELPER | NEWS_MANAGER | 0x4ac5794 | 337 | 6 | 3 | 0 |
| GAME_MATCH_DATABASE_HELPER | NEWS_MANAGER | 0x4ac546c | 337 | 1 | 0 | 0 |
| GAME_MATCH_DATABASE_HELPER | NEWS_MANAGER | 0x4ac4f7c | 332 | 43 | 8 | 0 |
| GAME_MATCH_DATABASE_HELPER | NEWS_MANAGER | 0x4ac5664 | 166 | 33 | 2 | 0 |
| GAME_MATCH_DATABASE_HELPER | EDIT_SESSION_MANAGER | 0x4ac533c | 15 | 4 | 0 | 0 |
| GAME_MATCH_DATABASE_HELPER | EDIT_SESSION_MANAGER | 0x4ac4f7c | 10 | 16 | 6 | 0 |
| GAME_MATCH_DATABASE_HELPER | EDIT_SESSION_MANAGER | 0x4ac5794 | 10 | 6 | 1 | 0 |
| GAME_MATCH_DATABASE_HELPER | EDIT_SESSION_MANAGER | 0x4ac546c | 10 | 1 | 0 | 0 |
| GAME_MATCH_DATABASE_HELPER | EDIT_SESSION_MANAGER | 0x4ac5664 | 5 | 9 | 2 | 0 |
| GAME_MATCH_DATABASE_HELPER | PLAY_FIXTURE_MANAGER | 0x4ac533c | 96 | 4 | 1 | 0 |
| GAME_MATCH_DATABASE_HELPER | PLAY_FIXTURE_MANAGER | 0x4ac4f7c | 64 | 16 | 3 | 0 |
| GAME_MATCH_DATABASE_HELPER | PLAY_FIXTURE_MANAGER | 0x4ac5794 | 64 | 6 | 2 | 0 |
| GAME_MATCH_DATABASE_HELPER | PLAY_FIXTURE_MANAGER | 0x4ac546c | 64 | 1 | 0 | 0 |
| GAME_MATCH_DATABASE_HELPER | PLAY_FIXTURE_MANAGER | 0x4ac5664 | 32 | 19 | 3 | 0 |
| GAME_MATCH_PLAYER_STATS | NEWS_MANAGER | 0x2e8c78c | 6,945 | 1 | 0 | 0 |
| GAME_MATCH_PLAYER_STATS | NEWS_MANAGER | 0x4ad215c | 6,945 | 0 | 0 | 0 |
| GAME_MATCH_PLAYER_STATS | EDIT_SESSION_MANAGER | 0x2e8c78c | 218 | 1 | 0 | 0 |
| GAME_MATCH_PLAYER_STATS | EDIT_SESSION_MANAGER | 0x4ad215c | 218 | 0 | 0 | 0 |
| GAME_MATCH_PLAYER_STATS | PLAY_FIXTURE_MANAGER | 0x2e8c78c | 1,040 | 1 | 0 | 0 |
| GAME_MATCH_PLAYER_STATS | PLAY_FIXTURE_MANAGER | 0x4ad215c | 1,040 | 0 | 0 | 0 |
| GAME_MATCH_STATS | NEWS_MANAGER | 0x4940788 | 166 | 64 | 44 | 0 |
| GAME_MATCH_STATS | EDIT_SESSION_MANAGER | 0x4940788 | 5 | 64 | 45 | 0 |
| GAME_MATCH_STATS | PLAY_FIXTURE_MANAGER | 0x4940788 | 32 | 51 | 31 | 0 |
| GAME_PERSON_BIOPIC | NEWS_MANAGER | 0x208aea0 | 5 | 0 | 0 | 0 |
| GAME_RULE_GROUP_MANAGER | GAME_RULE_GROUP_MANAGER | 0x4215d94 | 1 | 4 | 0 | 0 |
| GAME_RULE_GROUP_MANAGER | GAME_RULE_GROUP_MANAGER | 0x1bc36b0 | 1 | 49 | 32 | 0 |
| GAME_RULE_GROUP_MANAGER | GAME_RULE_GROUP_MANAGER | 0x4214c3c | 1 | 22 | 16 | 0 |
| GAME_RULE_GROUP_MANAGER | GAME_RULE_GROUP_MANAGER | 0x1bc4d14 | 1 | 6 | 0 | 0 |
| GAME_TACTIC_INFO | NEWS_MANAGER | 0x2e4e16c | 2 | 14 | 0 | 0 |
| GAME_TACTIC_INFO | NEWS_MANAGER | 0x483b60c | 2 | 6 | 0 | 0 |
| GAME_TACTIC_INFO | NEWS_MANAGER | 0x2e8d524 | 2 | 1 | 0 | 0 |
| GAME_TEAM_COMP_STATS | GAME_RULE_GROUP_MANAGER | 0xf357f8 | 1,976 | 152 | 142 | 0 |
| GAME_TEAM_COMP_STATS | GAME_RULE_GROUP_MANAGER | 0x3be0b8c | 1,976 | 6 | 6 | 0 |
| GOAL_AWARD_DATA | AWARD_MANAGER | 0x1991524 | 33 | 6 | 3 | 0 |
| GROUP_DRAW_NEWS | NEWS_MANAGER | 0x31557c0 | 129 | 12 | 11 | 0 |
| GROUP_DRAW_SUMMARY_NEWS | NEWS_MANAGER | 0x3174c44 | 1 | 2 | 0 | 0 |
| GROUP_DRAW_WARNING | NEWS_MANAGER | 0x317bc84 | 2 | 16 | 14 | 0 |
| HALL_OF_FAME_MANAGER | HALL_OF_FAME_MANAGER | 0x26c93a0 | 2 | 2 | 0 | 0 |
| HALL_OF_FAME_MANAGER | HALL_OF_FAME_MANAGER | 0x26c90b4 | 1 | 0 | 0 | 0 |
| HIDE_PLAYER_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x121ad84 | 19 | 11 | 11 | 0 |
| HIGHEST_AVERAGE_RATING_RECORD | GAME_RULE_GROUP_MANAGER | 0xfa0f18 | 280 | 4 | 4 | 0 |
| HIGHEST_AVERAGE_RATING_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xfa0f18 | 3,536 | 4 | 4 | 0 |
| HIGHEST_GATE_RECEIPTS_RECORD | NEWS_MANAGER | 0xf9a464 | 4 | 2 | 2 | 0 |
| HIGHEST_GATE_RECEIPTS_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xf9a464 | 3,536 | 2 | 2 | 0 |
| HIGHEST_TRANSFER_FEE_PAID_RECORD | NEWS_MANAGER | 0xfa784c | 1 | 5 | 5 | 0 |
| HIGHEST_TRANSFER_FEE_PAID_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xfa784c | 3,536 | 5 | 5 | 0 |
| HIGHEST_TRANSFER_FEE_RECEIVED_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xfa854c | 3,536 | 5 | 5 | 0 |
| HUMAN_FMFC_CLUB_DATA_ENTRY | HUMAN_NON_PLAYER_MANAGER | 0x23445a0 | 5 | 34 | 24 | 0 |
| HUMAN_FMFC_CLUB_DATA_ENTRY | HUMAN_NON_PLAYER_MANAGER | 0x233c698 | 5 | 11 | 11 | 0 |
| HUMAN_NON_PLAYER_MANAGER | HUMAN_NON_PLAYER_MANAGER | 0x26e346c | 1 | 14 | 2 | 0 |
| INJURY_FULL_TRAINING_NEWS | NEWS_MANAGER | 0x32e4ae0 | 1 | 5 | 5 | 0 |
| INJURY_INJURED_NEWS | NEWS_MANAGER | 0x141615c | 2,753 | 33 | 11 | 4 |
| INJURY_INJURED_NEWS | NEWS_MANAGER | 0x32df5b0 | 271 | 15 | 15 | 0 |
| INJURY_MANAGER | INJURY_MANAGER | 0x26fe31c | 1 | 43 | 19 | 0 |
| INTERACTION_MANAGER | INTERACTION_MANAGER | 0x273ee94 | 1 | 9 | 4 | 0 |
| INTERACTION_SUMMARY_PRESS_CONFERENCE_NOTABLE_REACTION_TO_QUESTION_OBSERVATION | EDIT_SESSION_MANAGER | 0x24d0c50 | 2 | 3 | 2 | 0 |
| INTERACTION_SUMMARY_PRESS_CONFERENCE_NOTABLE_REACTION_TO_QUESTION_OBSERVATION | EDIT_SESSION_MANAGER | 0x24dd48c | 1 | 0 | 0 | 0 |
| INTERACTION_SUMMARY_RELATIONSHIP_CHANGE_OBSERVATION | EDIT_SESSION_MANAGER | 0x24d9dac | 1 | 1 | 1 | 0 |
| INTERACTION_TRIGGER | NEWS_MANAGER | 0x3860668 | 6 | 13 | 11 | 0 |
| INTERNATIONAL_RETIREMENT_NEWS | NEWS_MANAGER | 0x352c630 | 3 | 9 | 8 | 0 |
| JOB_ADVERT | JOB_CENTRE_MANAGER | 0x250078c | 143 | 11 | 8 | 0 |
| JOB_CENTRE_MANAGER | JOB_CENTRE_MANAGER | 0x278abfc | 1 | 1 | 0 | 0 |
| JOB_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x2327f48 | 1 | 16 | 16 | 0 |
| JOB_SCOPE_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x2329770 | 2 | 4 | 4 | 0 |
| LEAGUE_FATE_DECIDED_NEWS | NEWS_MANAGER | 0x313240c | 5 | 18 | 13 | 0 |
| LEAGUE_GOALS_IN_A_SEASON_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xfad978 | 7,072 | 3 | 3 | 0 |
| LEAGUE_POSITION_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xf98658 | 7,072 | 3 | 3 | 0 |
| LEAGUE_QUALIFICATION_NEWS | NEWS_MANAGER | 0x3136d9c | 53 | 6 | 6 | 0 |
| LOAN_CONTRACT_EXPIRES_NEWS | NEWS_MANAGER | 0x323bd10 | 1 | 12 | 12 | 0 |
| LOAN_OFFER | TRANSFER_MANAGER+0x18 | 0x183db94 | 3,723 | 27 | 22 | 0 |
| LOAN_OFFER_WITH_ALL_DATA | NEWS_MANAGER | 0x3773f78 | 2 | 11 | 8 | 0 |
| LOAN_OFFER_WITH_ALL_DATA | NEWS_MANAGER | 0x37752b0 | 1 | 10 | 10 | 0 |
| LOAN_OFFER_WITH_PLAYING_DATA | NEWS_MANAGER | 0x3774ac8 | 1 | 5 | 5 | 0 |
| MANAGER_ATTENDING_JOB_INTERVIEW_LEAK_NEWS | NEWS_MANAGER | 0x3395a98 | 1 | 8 | 8 | 0 |
| MANAGER_CAREER_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x221c06c | 12 | 2 | 2 | 0 |
| MANAGER_DETAILS | MANAGER_MANAGER | 0x2587720 | 29,392 | 9 | 6 | 0 |
| MANAGER_GAMES_IN_CHARGE_SUMMARY | NEWS_MANAGER | 0x33bfa88 | 1 | 42 | 40 | 0 |
| MANAGER_JOB_SPECULATION_ANSWER_NEWS | NEWS_MANAGER | 0x337d9bc | 10 | 10 | 10 | 0 |
| MANAGER_MANAGER | MANAGER_MANAGER | 0x27964b8 | 1 | 3 | 0 | 0 |
| MANAGER_SACK_RACE_NEWS | NEWS_MANAGER | 0x33d427c | 6 | 16 | 10 | 0 |
| MANAGER_SPECULATION_AFTER_DEPARTURE_NEWS | NEWS_MANAGER | 0x336dd78 | 2 | 8 | 4 | 0 |
| MANAGER_VOTE_OF_CONFIDENCE_NEWS | NEWS_MANAGER | 0x3712288 | 7 | 5 | 5 | 0 |
| MATCHDAY_MANAGER | MATCHDAY_MANAGER | 0x27cd9c4 | 1 | 5 | 2 | 0 |
| MATCH_OF_THE_DAY_NEWS | NEWS_MANAGER | 0x340db14 | 32 | 10 | 7 | 0 |
| MATCH_PREPARATION_NEWS | NEWS_MANAGER | 0x37701c0 | 2 | 3 | 2 | 0 |
| MATCH_RECORD | GAME_RULE_GROUP_MANAGER | 0xf9ba54 | 560 | 1 | 1 | 0 |
| MATCH_RECORD | NEWS_MANAGER | 0xf9ba54 | 2 | 1 | 1 | 0 |
| MATCH_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xf9ba54 | 3,536 | 1 | 1 | 0 |
| MATCH_REPORT_NEWS | NEWS_MANAGER | 0x33f5dac | 155 | 32 | 27 | 0 |
| MATCH_STATS_MANAGER | MATCH_STATS_MANAGER | 0x1c41fdc | 1 | 4 | 2 | 0 |
| MEDIA_CONTRACT_RENEWAL_SPECULATION_NEWS | NEWS_MANAGER | 0x3472788 | 37 | 22 | 20 | 0 |
| MEDIA_FORMER_STAFF_OPINION_NEWS | NEWS_MANAGER | 0x342d3f4 | 1 | 7 | 7 | 0 |
| MEDIA_INJURY_CRISIS_NEWS | NEWS_MANAGER | 0x32eaa28 | 9 | 3 | 3 | 0 |
| MEDIA_INJURY_NEWS | NEWS_MANAGER | 0x32e5b08 | 1 | 1 | 1 | 0 |
| MEDIA_MANAGER | MEDIA_MANAGER+0x18 | 0x1390904 | 1 | 0 | 0 | 0 |
| MEDIA_MANAGER | MEDIA_MANAGER+0x18 | 0x280ddf0 | 1 | 15 | 9 | 0 |
| MEDIA_MANAGER | MEDIA_MANAGER+0x18 | 0x1390bf8 | 1 | 2 | 0 | 0 |
| MEDIA_MANAGER_OBSERVING_MATCH_NEWS | NEWS_MANAGER | 0x3419528 | 2 | 2 | 1 | 0 |
| MEDIA_MIN_FEE_RELEASE_CLAUSE_EXPIRED_NEWS | NEWS_MANAGER | 0x3478410 | 1 | 7 | 6 | 0 |
| MEDIA_MIN_FEE_RELEASE_CLAUSE_SPECULATION_NEWS | NEWS_MANAGER | 0x3475e40 | 14 | 7 | 5 | 0 |
| MEDIA_OPINION_OF_INTERNATIONAL_PLAYER_NEWS | NEWS_MANAGER | 0x353530c | 94 | 11 | 11 | 0 |
| MEDIA_PENALTY_MISS_NEWS | NEWS_MANAGER | 0x358233c | 15 | 1 | 1 | 0 |
| MEDIA_PLAYER_FORM_NEWS | NEWS_MANAGER | 0x3415b2c | 3 | 14 | 14 | 0 |
| MEDIA_TRANSFER_SPECULATION_NEWS | NEWS_MANAGER | 0x3490cd4 | 45 | 18 | 14 | 0 |
| MERGED_TRANSFER_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x2221e64 | 6 | 2 | 1 | 0 |
| MERGED_TRANSFER_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x2223b88 | 6 | 1 | 1 | 0 |
| MOM_SUMMARY_NEWS | NEWS_MANAGER | 0x34059a4 | 123 | 3 | 3 | 0 |
| MONTH_AWARD_DATA | AWARD_MANAGER | 0x19959ec | 25 | 3 | 2 | 0 |
| MORALE_MANAGER | MORALE_MANAGER | 0x2878750 | 1 | 7 | 7 | 0 |
| MOST_ASSISTS_RECORD | GAME_RULE_GROUP_MANAGER | 0xf9e8d8 | 280 | 4 | 4 | 0 |
| MOST_ASSISTS_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xf9e8d8 | 3,536 | 4 | 4 | 0 |
| MOST_CLEAN_SHEETS_RECORD | GAME_RULE_GROUP_MANAGER | 0xf9f544 | 280 | 4 | 4 | 0 |
| MOST_CLEAN_SHEETS_RECORD | NEWS_MANAGER | 0xf9f544 | 1 | 4 | 4 | 0 |
| MOST_CLEAN_SHEETS_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xf9f544 | 3,536 | 4 | 4 | 0 |
| MOST_GOALS_FOR_NATION_RECORD | NEWS_MANAGER | 0xfa6f7c | 2 | 3 | 3 | 0 |
| MOST_GOALS_IN_MATCH_RECORD | GAME_RULE_GROUP_MANAGER | 0xfa01a0 | 280 | 2 | 2 | 0 |
| MOST_GOALS_IN_MATCH_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xfa01a0 | 7,072 | 2 | 2 | 0 |
| MOST_LEAGUE_APPEARANCES_FOR_CLUB_RECORD | NEWS_MANAGER | 0xfa374c | 4 | 2 | 2 | 0 |
| MOST_LEAGUE_APPEARANCES_FOR_CLUB_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xfa374c | 3,536 | 2 | 2 | 0 |
| MOST_LEAGUE_GOALS_FOR_CLUB_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xfa3dfc | 3,536 | 2 | 2 | 0 |
| MOST_MAN_OF_MATCH_RECORD | GAME_RULE_GROUP_MANAGER | 0xfa1a90 | 280 | 4 | 4 | 0 |
| MOST_MAN_OF_MATCH_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xfa1a90 | 3,536 | 4 | 4 | 0 |
| N2db14OBJECT_STORAGEI14HISTORIC_DRAFT8DRAFT_IDEE | TRANSFER_MANAGER*0x7e0 | 0x1893b14 | 1 | 5 | 5 | 0 |
| N2db14OBJECT_STORAGEI14SEASON_SUMMARY17SEASON_SUMMARY_IDEE | GAME_RULE_GROUP_MANAGER | 0x1893b14 | 2 | 5 | 5 | 0 |
| N2db14OBJECT_STORAGEI20ARCHIVED_MATCH_STATSiEE | MATCH_STATS_MANAGER | 0x1893b14 | 4 | 5 | 5 | 0 |
| N2db14OBJECT_STORAGEI27ARCHIVED_AWARD_PACKED_MATCH21AWARD_PACKED_MATCH_IDEE | AWARD_MANAGER | 0x1893b14 | 2 | 5 | 5 | 0 |
| N2db14OBJECT_STORAGEINS_19RETIRED_PERSON_DATAEiEE | RETIREMENT_MANAGER | 0x1893b14 | 1 | 5 | 5 | 0 |
| NATIONAL_TEAM_COMP_FALLOUT_NEWS | NEWS_MANAGER | 0x3546330 | 13 | 15 | 10 | 0 |
| NATIONAL_TEAM_INJURY_OR_WITHDRAWAL_NEWS | NEWS_MANAGER | 0x35054e8 | 10 | 11 | 6 | 0 |
| NATIONAL_TEAM_POST_MATCH_MEDIA_NEWS | NEWS_MANAGER | 0x3516c18 | 42 | 11 | 6 | 0 |
| NATIONAL_TEAM_PRE_MATCH_MEDIA_NEWS | NEWS_MANAGER | 0x35110cc | 56 | 17 | 17 | 0 |
| NATIONAL_TEAM_REPLACEMENT_NEWS | NEWS_MANAGER | 0x3508bc0 | 5 | 3 | 1 | 0 |
| NATION_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x2321168 | 39 | 5 | 4 | 0 |
| NATION_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x232a460 | 16 | 1 | 1 | 0 |
| NATION_MANAGER_DETAILS | MANAGER_MANAGER | 0x2588b78 | 3,542 | 1 | 0 | 0 |
| NETWORK_COMPETITION_MANAGER | NETWORK_COMPETITION_MANAGER | 0x28cf5b4 | 1 | 31 | 30 | 0 |
| NEWS_MANAGER | NEWS_MANAGER | 0x28f274c | 1 | 15 | 1 | 0 |
| NON_PLAYER_REPLACEMENT_RESPONSE | NEWS_MANAGER | 0x3869304 | 1 | 3 | 1 | 0 |
| OFFICIAL_MANAGER | OFFICIAL_MANAGER | 0x2905b24 | 1 | 8 | 0 | 0 |
| PERSON_CAN_BE_SCOUTED_FILTER_RULE | SCOUT_MANAGER | 0x121d1b8 | 76 | 1 | 1 | 0 |
| PERSON_HAS_BEEN_SCOUTED_FILTER_RULE | SCOUT_MANAGER | 0x123af70 | 76 | 1 | 1 | 0 |
| PERSON_INCLUDE_OWN_FILTER_RULE | SCOUT_MANAGER | 0x123c548 | 78 | 1 | 1 | 0 |
| PERSON_INTERESTED_DP_FILTER_RULE | SCOUT_MANAGER | 0x746bfc | 330 | 7 | 5 | 0 |
| PERSON_INTERESTED_DP_FILTER_RULE | SCOUT_MANAGER | 0x123108c | 250 | 1 | 1 | 0 |
| PERSON_INTERESTED_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x746bfc | 116 | 7 | 5 | 0 |
| PERSON_INTERESTED_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x123d838 | 29 | 2 | 2 | 0 |
| PERSON_INTERESTED_FILTER_RULE | SCOUT_MANAGER | 0x123d838 | 76 | 2 | 2 | 0 |
| PERSON_INTERESTED_LOAN_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x123108c | 87 | 1 | 1 | 0 |
| PERSON_IN_NATIONAL_POOL_RULE | SCOUT_MANAGER | 0x123bf74 | 76 | 1 | 1 | 0 |
| PERSON_MLS_CLUB_RIGHTS_RULE | SCOUT_MANAGER | 0x123f14c | 76 | 1 | 1 | 0 |
| PERSON_NON_PLAYER_INTERESTED_FILTER_RULE | SCOUT_MANAGER | 0x1241410 | 8 | 2 | 2 | 0 |
| PERSON_POSITION_FILTER_RULE | SCOUT_MANAGER | 0x124224c | 2 | 2 | 2 | 0 |
| PERSON_RECORD_MANAGER | PERSON_RECORD_MANAGER | 0x291f604 | 1 | 4 | 1 | 0 |
| PERSON_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x22255b8 | 3 | 0 | 0 | 0 |
| PERSON_VALID_FOR_NATION_RULE | SCOUT_MANAGER | 0x1246d70 | 76 | 1 | 1 | 0 |
| PERSON_WITH_TEAM_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x2223d50 | 6 | 3 | 3 | 0 |
| PERSON_WITH_TEAM_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x222611c | 3 | 0 | 0 | 0 |
| PHYSIO_POST_MATCH_CONDITIONING_REPORT_NEWS | NEWS_MANAGER | 0x3566b08 | 1 | 5 | 4 | 0 |
| PHYSIO_PRE_MATCH_FITNESS_TEST_NEWS | NEWS_MANAGER | 0x35693b8 | 2 | 7 | 4 | 0 |
| PHYSIO_TEAM_REPORT_NEWS | NEWS_MANAGER | 0x356360c | 1 | 12 | 9 | 0 |
| PLAYER_AGE_RECORD | GAME_RULE_GROUP_MANAGER | 0xfa44ac | 1,120 | 3 | 3 | 0 |
| PLAYER_AGE_RECORD | NEWS_MANAGER | 0xfa44ac | 3 | 3 | 3 | 0 |
| PLAYER_AGE_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xfa44ac | 14,144 | 3 | 3 | 0 |
| PLAYER_CLUB_DEBUT_NEWS | NEWS_MANAGER | 0x35a1b5c | 27 | 21 | 20 | 0 |
| PLAYER_COME_AND_GET_ME_PLEA_NEWS_ITEM | NEWS_MANAGER | 0x30964b8 | 1 | 1 | 1 | 0 |
| PLAYER_COMMENT_ON_NATIONAL_TEAM_NEWS | NEWS_MANAGER | 0x35264e4 | 72 | 10 | 10 | 0 |
| PLAYER_COMP_STATS_ANALYSIS_NEWS | NEWS_MANAGER | 0x31a96ec | 13 | 0 | 0 | 0 |
| PLAYER_ENDS_GOAL_DROUGHT_NEWS | NEWS_MANAGER | 0x34205f0 | 3 | 9 | 9 | 0 |
| PLAYER_FILTER | SCOUT_MANAGER | 0x435f204 | 79 | 3 | 0 | 0 |
| PLAYER_FILTER | SCOUT_MANAGER | 0x1223974 | 79 | 1 | 1 | 0 |
| PLAYER_FILTER | SCOUT_MANAGER | 0x744714 | 79 | 9 | 6 | 0 |
| PLAYER_FIRST_CAP_NEWS | NEWS_MANAGER | 0x35192c0 | 5 | 12 | 11 | 0 |
| PLAYER_GAINED_NATIONALITY_NEWS | NEWS_MANAGER | 0x3532570 | 2 | 6 | 6 | 0 |
| PLAYER_HAPPINESS_REMOVED_NEWS_ITEM | NEWS_MANAGER | 0x331b360 | 8 | 5 | 5 | 0 |
| PLAYER_HAPPINESS_STAGE_ADDED_PUBLIC_NEWS_ITEM | NEWS_MANAGER | 0x32f5afc | 42 | 21 | 17 | 0 |
| PLAYER_HAPPINESS_STAGE_ADDED_PUBLIC_NEWS_ITEM | NEWS_MANAGER | 0x3323ff0 | 34 | 4 | 4 | 0 |
| PLAYER_MISSES_IMPORTANT_FIXTURE_NEWS | NEWS_MANAGER | 0x367083c | 4 | 9 | 5 | 0 |
| PLAYER_MULTIPLE_TRANSFER_NEWS | NEWS_MANAGER | 0x3787938 | 4 | 0 | 0 | 0 |
| PLAYER_MULTIPLE_TRANSFER_NEWS | NEWS_MANAGER | 0x37855e0 | 4 | 21 | 14 | 0 |
| PLAYER_OF_THE_DAY_NEWS | NEWS_MANAGER | 0x305410c | 2 | 11 | 6 | 0 |
| PLAYER_ON_GOAL_DROUGHT_RUN_NEWS | NEWS_MANAGER | 0x342233c | 17 | 8 | 8 | 0 |
| PLAYER_RECOMMENDATION_FILTER_RULE | SCOUT_MANAGER | 0x124f918 | 2 | 2 | 2 | 0 |
| PLAYER_SCORES_FIRST_INTERNATIONAL_GOAL_NEWS | NEWS_MANAGER | 0x3521aa8 | 8 | 6 | 5 | 0 |
| PLAYER_STATUS_FLAG_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x1250bcc | 4 | 1 | 1 | 0 |
| PLAYER_WILLING_TO_CONSIDER_REPRESENTING_NATION_FILTER_RULE | SCOUT_MANAGER | 0x125225c | 76 | 1 | 1 | 0 |
| PLAY_FIXTURE_MANAGER | PLAY_FIXTURE_MANAGER | 0x293c320 | 1 | 4 | 0 | 0 |
| POINTS_IN_A_SEASON_RECORD | GAME_RULE_GROUP_MANAGER | 0xfac210 | 2,240 | 3 | 3 | 0 |
| POINTS_IN_A_SEASON_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xfac210 | 7,072 | 3 | 3 | 0 |
| POLYGON_DATA | NEWS_MANAGER | 0x39ed920 | 10 | 8 | 3 | 0 |
| POLYGON_DATA | NEWS_MANAGER | 0x39f63c8 | 10 | 1 | 1 | 0 |
| POLYGON_OBSERVATION | NEWS_MANAGER | 0x39f7178 | 10 | 9 | 4 | 0 |
| POSITION_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x1252468 | 24 | 9 | 9 | 0 |
| POSTPONED_FIXTURE_NEWS | NEWS_MANAGER | 0x319e674 | 2 | 3 | 3 | 0 |
| POST_MATCH_KEY_FINDINGS_NEWS | NEWS_MANAGER | 0x30519d4 | 2 | 2 | 1 | 0 |
| POTENTIAL_CUP_DRAW_NEWS | NEWS_MANAGER | 0x315e3d8 | 6 | 1 | 0 | 0 |
| PRAISE_FOR_MANAGER_NEWS | NEWS_MANAGER | 0x35805a8 | 1 | 9 | 8 | 0 |
| PRESS_CONFERENCE_ANSWERED_QUESTION | NEWS_MANAGER | 0x3920264 | 326 | 49 | 26 | 0 |
| PRESS_CONFERENCE_ANSWERED_QUESTION | NEWS_MANAGER | 0x39302e0 | 304 | 6 | 6 | 0 |
| PRESS_CONFERENCE_ANSWERED_QUESTION | EDIT_SESSION_MANAGER | 0x39302e0 | 6 | 6 | 6 | 0 |
| PRESS_CONFERENCE_ANSWERED_QUESTION | PRESS_CONFERENCE_MANAGER | 0x3920264 | 17,049 | 54 | 30 | 0 |
| PRESS_CONFERENCE_ANSWERED_QUESTION | PRESS_CONFERENCE_MANAGER | 0x39302e0 | 16,549 | 6 | 6 | 0 |
| PRESS_CONFERENCE_EDIT_SESSION | EDIT_SESSION_MANAGER | 0x22a32a8 | 5 | 9 | 9 | 0 |
| PRESS_CONFERENCE_INVITE_NEWS | NEWS_MANAGER | 0x3611e40 | 4 | 9 | 7 | 0 |
| PRESS_CONFERENCE_INVITE_RESPONSE_OBJECT | NEWS_MANAGER | 0x3608f40 | 4 | 3 | 2 | 0 |
| PRESS_CONFERENCE_JOURNALIST | NEWS_MANAGER | 0x2436d28 | 58 | 8 | 6 | 0 |
| PRESS_CONFERENCE_JOURNALIST | EDIT_SESSION_MANAGER | 0x2436d28 | 10 | 8 | 6 | 0 |
| PRESS_CONFERENCE_MANAGER | PRESS_CONFERENCE_MANAGER | 0x295290c | 1 | 48 | 37 | 0 |
| PRESS_CONFERENCE_QUESTION | EDIT_SESSION_MANAGER | 0x3920264 | 21 | 39 | 26 | 0 |
| PRESS_CONFERENCE_SUMMARY | NEWS_MANAGER | 0x24caa3c | 4 | 3 | 0 | 0 |
| PRESS_CONFERENCE_SUMMARY | NEWS_MANAGER | 0x24cbbc4 | 4 | 1 | 0 | 0 |
| PRESS_CONFERENCE_SUMMARY | NEWS_MANAGER | 0x3933418 | 4 | 4 | 2 | 0 |
| PRESS_CONFERENCE_SUMMARY | EDIT_SESSION_MANAGER | 0x24caa3c | 5 | 3 | 2 | 0 |
| PRESS_CONFERENCE_SUMMARY | EDIT_SESSION_MANAGER | 0x24cbbc4 | 5 | 2 | 2 | 0 |
| PRESS_CONFERENCE_SUMMARY | EDIT_SESSION_MANAGER | 0x3933418 | 5 | 4 | 4 | 0 |
| PRESS_CONFERENCE_SUMMARY_NEWS | NEWS_MANAGER | 0x361762c | 73 | 26 | 7 | 0 |
| PRE_MATCH_ANALYSIS_OF_OPPONENTS_NEWS | NEWS_MANAGER | 0x3050b94 | 2 | 8 | 3 | 0 |
| PRE_MATCH_ATTENDANCE_NEWS | NEWS_MANAGER | 0x35c9178 | 5 | 28 | 28 | 0 |
| PRE_MATCH_DANGER_PLAYER_NEWS | NEWS_MANAGER | 0x35bd6ec | 22 | 5 | 5 | 0 |
| PRE_MATCH_FORMER_PLAYERS_CONFRONTATION_NEWS | NEWS_MANAGER | 0x35c4140 | 3 | 13 | 10 | 0 |
| PRE_MATCH_ODDS_NEWS | NEWS_MANAGER | 0x35b40d0 | 185 | 97 | 22 | 0 |
| PRE_MATCH_PRESSURE_ON_TEAM_NEWS | NEWS_MANAGER | 0x3606518 | 2 | 4 | 4 | 0 |
| PRE_SEASON_RETURN_TO_TRAINING_REPORT_NEWS | NEWS_MANAGER | 0x3761248 | 184 | 7 | 1 | 0 |
| RANKING_RECORD | NEWS_MANAGER | 0xfaefa4 | 16 | 4 | 4 | 0 |
| RECOMMEND_SIGNING_RESPONSE_OBJECT | NEWS_MANAGER | 0x386ccb8 | 1 | 0 | 0 | 0 |
| RECORD_NEWS | NEWS_MANAGER | 0x36dfe68 | 35 | 1 | 1 | 0 |
| RECRUITMENT_FOCUS_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19b93d8 | 51 | 23 | 22 | 0 |
| RED_CARD_BAN_NEWS | NEWS_MANAGER | 0x326ebf0 | 59 | 8 | 5 | 0 |
| RED_CARD_BAN_NEWS | NEWS_MANAGER | 0x3273050 | 38 | 11 | 11 | 0 |
| REGENERATION_MANAGER | REGENERATION_MANAGER+0x18 | 0x1596634 | 1 | 0 | 0 | 0 |
| REGENERATION_MANAGER | REGENERATION_MANAGER+0x18 | 0x2a2ce84 | 1 | 12 | 7 | 0 |
| REGENERATION_MANAGER | REGENERATION_MANAGER+0x18 | 0x1596818 | 1 | 10 | 8 | 0 |
| REGENERATION_POSTPONED_RETIREMENT_NEWS | NEWS_MANAGER | 0x36218c4 | 1 | 1 | 1 | 0 |
| REGENERATION_RETIRED_NEWS | NEWS_MANAGER | 0x362f40c | 4 | 23 | 22 | 0 |
| REGENERATION_RETIRING_NEWS | NEWS_MANAGER | 0x3620788 | 13 | 15 | 15 | 0 |
| REGENERATION_YOUTH_INTAKE_NEWS | NEWS_MANAGER | 0x3630a54 | 1 | 0 | 0 | 0 |
| RELEVANT_STORIES_ROUNDUP_NEWS | NEWS_MANAGER | 0x3448584 | 1 | 2 | 1 | 0 |
| REQUIRED_TARGET_UPDATES_NEWS | NEWS_MANAGER | 0x32fdbac | 1 | 13 | 1 | 0 |
| RESERVE_U18_COMP_NEWS | NEWS_MANAGER | 0x3412774 | 3 | 16 | 10 | 0 |
| RETIREMENT_MANAGER | RETIREMENT_MANAGER | 0x2a8d2b0 | 1 | 22 | 2 | 0 |
| SCORELINE_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x2226784 | 8 | 0 | 0 | 0 |
| SCORELINE_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x2228578 | 8 | 1 | 1 | 0 |
| SCOUTING_CENTRE_ENTRY_NEWS | NEWS_MANAGER | 0x364f694 | 4 | 5 | 4 | 0 |
| SCOUTING_FOCUS_UPDATE_NEWS | NEWS_MANAGER | 0x364c950 | 1 | 2 | 1 | 0 |
| SCOUT_ASSIGNMENT_ENTRY | NEWS_MANAGER | 0x396d1e4 | 1 | 11 | 6 | 0 |
| SCOUT_ASSIGNMENT_ENTRY | SCOUT_MANAGER | 0x396d1e4 | 17 | 12 | 7 | 0 |
| SCOUT_MANAGER | SCOUT_MANAGER | 0x2aa8aa8 | 1 | 18 | 0 | 0 |
| SCOUT_SEARCH_PERSON_FILTER | HUMAN_NON_PLAYER_MANAGER | 0x1223974 | 29 | 7 | 7 | 0 |
| SCOUT_TEAM_REPORT_NEWS | NEWS_MANAGER | 0x364588c | 2 | 23 | 0 | 0 |
| SEQUENCE_RECORD | GAME_RULE_GROUP_MANAGER | 0xf9ce00 | 1,680 | 3 | 2 | 0 |
| SEQUENCE_RECORD | NEWS_MANAGER | 0xf9ce00 | 12 | 3 | 2 | 0 |
| SEQUENCE_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xf9ce00 | 21,216 | 3 | 2 | 0 |
| SET_PIECE_EFFECTIVENESS_ATTACK_CORNER_REPRESENTATION | TRAINING_MANAGER | 0x3a26b00 | 3 | 3 | 3 | 0 |
| SET_PIECE_EFFECTIVENESS_ATTACK_DEEP_FK_REPRESENTATION | TRAINING_MANAGER | 0x3a27c48 | 3 | 3 | 3 | 0 |
| SET_PIECE_EFFECTIVENESS_ATTACK_LONG_THROW_REPRESENTATION | TRAINING_MANAGER | 0x3a2810c | 3 | 3 | 3 | 0 |
| SET_PIECE_EFFECTIVENESS_ATTACK_SHOOTING_CHANCE_FK_REPRESENTATION | TRAINING_MANAGER | 0x3a27050 | 3 | 3 | 3 | 0 |
| SET_PIECE_EFFECTIVENESS_ATTACK_WIDE_FK_REPRESENTATION | TRAINING_MANAGER | 0x3a275f0 | 3 | 3 | 3 | 0 |
| SET_PIECE_EFFECTIVENESS_DEFEND_CORNER_REPRESENTATION | TRAINING_MANAGER | 0x3a26d44 | 3 | 3 | 3 | 0 |
| SET_PIECE_EFFECTIVENESS_DEFEND_DEEP_FK_REPRESENTATION | TRAINING_MANAGER | 0x3a27e4c | 3 | 3 | 3 | 0 |
| SET_PIECE_EFFECTIVENESS_DEFEND_LONG_THROW_REPRESENTATION | TRAINING_MANAGER | 0x3a28424 | 3 | 3 | 3 | 0 |
| SET_PIECE_EFFECTIVENESS_DEFEND_SHOOTING_CHANCE_FK_REPRESENTATION | TRAINING_MANAGER | 0x3a27300 | 3 | 3 | 3 | 0 |
| SET_PIECE_EFFECTIVENESS_DEFEND_WIDE_FK_REPRESENTATION | TRAINING_MANAGER | 0x3a27838 | 3 | 3 | 3 | 0 |
| SHORTLIST_MANAGER | SHORTLIST_MANAGER | 0x2b1bb14 | 1 | 106 | 51 | 0 |
| SIMULATED_STATS_MANAGER | SIMULATED_STATS_MANAGER | 0x2b3f7e0 | 1 | 8 | 3 | 0 |
| SPORTS_SCIENTIST_TEAM_REPORT_NEWS | NEWS_MANAGER | 0x356a6ac | 1 | 18 | 12 | 0 |
| SQUAD_FILTER | HUMAN_NON_PLAYER_MANAGER | 0x435f204 | 112 | 3 | 0 | 0 |
| SQUAD_FILTER | HUMAN_NON_PLAYER_MANAGER | 0x744714 | 96 | 8 | 3 | 0 |
| SQUAD_FILTER | HUMAN_NON_PLAYER_MANAGER | 0x1255654 | 35 | 0 | 0 | 0 |
| SQUAD_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x1257cc8 | 43 | 6 | 6 | 0 |
| SQUAD_PLANNER_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x1258924 | 4 | 6 | 6 | 0 |
| STADIUM_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x2229720 | 1 | 2 | 2 | 0 |
| STAFF_MEETING_ADVICE_NEWS | NEWS_MANAGER | 0x309cfac | 5 | 2 | 2 | 0 |
| STAFF_RESPONSIBILITIES_CHANGE_RESPONSE | NEWS_MANAGER | 0x435f204 | 30 | 3 | 0 | 0 |
| STAFF_RESPONSIBILITIES_CHANGE_RESPONSE | NEWS_MANAGER | 0x142a504 | 30 | 6 | 6 | 0 |
| STAFF_RESPONSIBILITIES_CHANGE_RESPONSE | NEWS_MANAGER | 0x387a5a4 | 8 | 4 | 4 | 0 |
| SUBJECT_DATAPOINT | NEWS_MANAGER | 0x39f1194 | 160 | 3 | 1 | 0 |
| TACTICS_MANAGER | TACTICS_MANAGER | 0x2b511a0 | 1 | 4 | 0 | 0 |
| TACTIC_EDIT_SESSION | EDIT_SESSION_MANAGER | 0x22ce494 | 1 | 14 | 2 | 0 |
| TC_EXTENDED_CLUB_RECORDS | TEAM_CONTAINER_RECORD_MANAGER | 0x39510a4 | 3,536 | 8 | 7 | 0 |
| TEAM_AWARD_DATA | AWARD_MANAGER | 0x199ff64 | 61 | 1 | 0 | 0 |
| TEAM_CONTAINER_RECORD_MANAGER | TEAM_CONTAINER_RECORD_MANAGER | 0x2b66f84 | 1 | 5 | 0 | 0 |
| TEAM_FILTER_LIST | HUMAN_NON_PLAYER_MANAGER | 0x7475dc | 16 | 2 | 0 | 0 |
| TEAM_FILTER_LIST | HUMAN_NON_PLAYER_MANAGER | 0x232e93c | 9 | 0 | 0 | 0 |
| TEAM_FORM_NEWS | NEWS_MANAGER | 0x372e7a4 | 2 | 19 | 17 | 0 |
| TEAM_SELECTION_ADVICE_NEWS | NEWS_MANAGER | 0x309b118 | 2 | 10 | 6 | 0 |
| TEAM_TALK_FEEDBACK_NEWS | NEWS_MANAGER | 0x3751ab4 | 1 | 24 | 24 | 0 |
| TEAM_TALK_MANAGER | TEAM_TALK_MANAGER | 0x2bdb0dc | 1 | 7 | 2 | 0 |
| TELEVISED_FIXTURE_NEWS | NEWS_MANAGER | 0x3160390 | 3 | 1 | 0 | 0 |
| TOP_GOALSCORER_RECORD | GAME_RULE_GROUP_MANAGER | 0xf9dad0 | 280 | 4 | 4 | 0 |
| TOP_GOALSCORER_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xf9dad0 | 7,072 | 4 | 4 | 0 |
| TOTAL_TRANSFER_MONEY_RECORD | NEWS_MANAGER | 0xfaa174 | 1 | 3 | 3 | 0 |
| TOTAL_TRANSFER_MONEY_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xfaa174 | 7,072 | 3 | 3 | 0 |
| TOURNAMENT_AWARD_BUILD_UP_HYPE_NEWS | NEWS_MANAGER | 0x3088c04 | 1 | 7 | 7 | 0 |
| TRADE_OFFER | TRANSFER_MANAGER+0x18 | 0x1852c94 | 10 | 20 | 6 | 0 |
| TRAINING_CAMP_MANAGER | TRAINING_CAMP_MANAGER | 0x2c8a83c | 1 | 1 | 0 | 0 |
| TRAINING_MANAGER | TRAINING_MANAGER | 0x2cb9224 | 1 | 13 | 8 | 0 |
| TRANSFER_ACTIVITY_NARRATIVE | PRESS_CONFERENCE_MANAGER | 0x2f59ed4 | 1,264 | 21 | 14 | 0 |
| TRANSFER_COMPLETED_NEWS | NEWS_MANAGER | 0x37eaa14 | 12 | 55 | 47 | 0 |
| TRANSFER_CONTRACT_DECISION_NEWS | NEWS_MANAGER | 0x37bcbf4 | 30 | 24 | 21 | 0 |
| TRANSFER_JOB_TYPE_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x2330524 | 1 | 3 | 3 | 0 |
| TRANSFER_MANAGER | TRANSFER_MANAGER+0x18 | 0x1828858 | 1 | 0 | 0 | 0 |
| TRANSFER_MANAGER | TRANSFER_MANAGER+0x18 | 0x2e0f8e0 | 1 | 0 | 0 | 0 |
| TRANSFER_MANAGER | TRANSFER_MANAGER+0x18 | 0x1829e68 | 1 | 13 | 2 | 0 |
| TRANSFER_OFFER_ACCEPTED_NEWS | NEWS_MANAGER | 0x37a2e68 | 7 | 22 | 18 | 0 |
| TRANSFER_OFFER_ALL_EXTRA_DATA | NEWS_MANAGER | 0x37733b0 | 84 | 8 | 6 | 0 |
| TRANSFER_OFFER_ALL_EXTRA_DATA | NEWS_MANAGER | 0x377554c | 82 | 6 | 6 | 0 |
| TRANSFER_OFFER_CONFIRMATION_NEWS | NEWS_MANAGER | 0x37ccaac | 1 | 90 | 82 | 0 |
| TRANSFER_OFFER_CONFIRMATION_RESPONSE | NEWS_MANAGER | 0x37cfc54 | 1 | 18 | 14 | 0 |
| TRANSFER_OFFER_NEWS | NEWS_MANAGER | 0x3796e3c | 20 | 61 | 56 | 0 |
| TRANSFER_OFFER_REJECTED_NEWS | NEWS_MANAGER | 0x37a7dd4 | 1 | 16 | 15 | 0 |
| TRANSFER_STATUS_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x2330ae4 | 1 | 15 | 15 | 0 |
| TRANSFER_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x2229e24 | 86 | 9 | 7 | 0 |
| TRANSFER_TIMELINE_EVENT | PERSON_RECORD_MANAGER | 0x222d77c | 33 | 7 | 7 | 0 |
| TRANSFER_TYPE_FILTER_RULE | HUMAN_NON_PLAYER_MANAGER | 0x2331718 | 1 | 12 | 12 | 0 |
| TRIAL_OFFER | TRANSFER_MANAGER+0x18 | 0x1874ef0 | 61 | 1 | 1 | 0 |
| UNHAPPY_PLAYERS_IN_TRAINING_NEWS | NEWS_MANAGER | 0x376ef48 | 1 | 5 | 2 | 0 |
| VIEW_MATCH_HIGHLIGHT_RESPONSE_OBJECT | NEWS_MANAGER | 0x387d274 | 4 | 6 | 6 | 0 |
| WEEKLY_TRAINING_PREVIEW_NEWS | NEWS_MANAGER | 0x37668fc | 2 | 16 | 6 | 0 |
| WORST_DISCIPLINE_RECORD | GAME_RULE_GROUP_MANAGER | 0xfa26e8 | 560 | 4 | 4 | 0 |
| WORST_DISCIPLINE_RECORD | TEAM_CONTAINER_RECORD_MANAGER | 0xfa26e8 | 3,536 | 4 | 4 | 0 |
| YEAR_AWARD_DATA | AWARD_MANAGER | 0x197e25c | 413 | 12 | 12 | 0 |
| YEAR_AWARD_DATA | AWARD_MANAGER | 0x199a24c | 305 | 5 | 5 | 0 |
| YEAR_AWARD_DATA | AWARD_MANAGER | 0x19a896c | 280 | 2 | 2 | 0 |
| backroom_advice_player_development_topics::CHANGE_PLAYER_SQUAD_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19cabb4 | 28 | 1 | 1 | 0 |
| backroom_advice_player_development_topics::DRESSING_ROOM_ATMOSPHERE_LEVEL_ADVICE_SUGGESTIONS | BACKROOM_ADVICE_MANAGER | 0x19cc208 | 51 | 1 | 1 | 0 |
| backroom_advice_player_development_topics::HIGH_POTENTIAL_PLAYER_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19cc608 | 113 | 0 | 0 | 0 |
| backroom_advice_player_development_topics::MANAGER_SUPPORT_LEVEL_ADVICE_SUGGESTIONS | BACKROOM_ADVICE_MANAGER | 0x19cc984 | 51 | 1 | 1 | 0 |
| backroom_advice_player_development_topics::PLAYER_ABILITY_CHANGE_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19ccdfc | 225 | 0 | 0 | 0 |
| backroom_advice_player_development_topics::PLAYER_FORM_INTERACTION_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19b26b4 | 142 | 1 | 1 | 0 |
| backroom_advice_player_development_topics::PLAYER_TRAINING_HAPPINESS_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19ce968 | 22 | 2 | 2 | 0 |
| backroom_advice_player_development_topics::SEND_PLAYER_ON_LANGUAGE_COURSE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19cf160 | 15 | 0 | 0 | 0 |
| backroom_advice_player_development_topics::TEAM_HIERARCHY_MOVEMENT_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19cedb8 | 7 | 2 | 2 | 0 |
| backroom_advice_recruitment_topics::INCREASE_PLAYER_ASKING_PRICE_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19dd948 | 12 | 3 | 3 | 0 |
| backroom_advice_staff_topics::APPROACH_TO_SIGN_STAFF_MEMBER_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x435f204 | 2,368 | 3 | 0 | 0 |
| backroom_advice_staff_topics::APPROACH_TO_SIGN_STAFF_MEMBER_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19b39b0 | 2,368 | 7 | 6 | 0 |
| backroom_advice_staff_topics::APPROACH_TO_SIGN_STAFF_MEMBER_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19e3794 | 337 | 4 | 3 | 0 |
| backroom_advice_staff_topics::APPROACH_TO_SIGN_STAFF_MEMBER_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19e85fc | 299 | 1 | 1 | 0 |
| backroom_advice_staff_topics::SEND_ON_COACHING_COURSE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19b30bc | 51 | 1 | 1 | 0 |
| backroom_advice_staff_topics::SEND_ON_COACHING_COURSE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19e9954 | 51 | 1 | 1 | 0 |
| backroom_advice_tactical_topics::ADD_MARKING_OPPOSITION_INSTRUCTION_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19f4e38 | 145 | 1 | 1 | 0 |
| backroom_advice_tactical_topics::ADD_PLAYER_INSTRUCTION_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19fc89c | 12 | 1 | 1 | 0 |
| backroom_advice_tactical_topics::ADD_PRESSING_TRIGGER_OPPOSITION_INSTRUCTION_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19f51b8 | 57 | 1 | 1 | 0 |
| backroom_advice_tactical_topics::ADD_TACKLING_OPPOSITION_INSTRUCTION_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19f0844 | 937 | 0 | 0 | 0 |
| backroom_advice_tactical_topics::ADD_TACKLING_OPPOSITION_INSTRUCTION_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19f470c | 644 | 1 | 1 | 0 |
| backroom_advice_tactical_topics::ADD_TACKLING_OPPOSITION_INSTRUCTION_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19f5538 | 294 | 1 | 1 | 0 |
| backroom_advice_tactical_topics::ADD_TEAM_INSTRUCTION_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19f25cc | 239 | 1 | 1 | 0 |
| backroom_advice_tactical_topics::ADD_WEAK_FOOT_OPPOSITION_INSTRUCTION_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19f4ac4 | 148 | 1 | 1 | 0 |
| backroom_advice_tactical_topics::TEAM_MENTALITY_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x19f19fc | 44 | 2 | 2 | 0 |
| backroom_advice_training_topics::PLAYER_PERSONALITY_CHANGE_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x1a058ac | 58 | 1 | 1 | 0 |
| backroom_advice_training_topics::PLAYER_PROGRESSION_OBSERVATION_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x1a05e28 | 113 | 4 | 4 | 0 |
| backroom_advice_training_topics::PLAYER_START_INDIVIDUAL_TRAINING_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x1a0685c | 26 | 4 | 4 | 0 |
| backroom_advice_training_topics::PLAYER_STOP_INDIVIDUAL_TRAINING_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x1a0751c | 24 | 3 | 3 | 0 |
| backroom_advice_training_topics::PLAYER_TRAIT_ADVICE_SUGGESTION | BACKROOM_ADVICE_MANAGER | 0x1a0a5c0 | 1 | 2 | 2 | 0 |
| db::ACTUAL_NON_PLAYER | TRAINING_MANAGER | 0x1104334 | 116 | 5 | 5 | 0 |
| db::ACTUAL_NON_PLAYER | BACKROOM_ADVICE_MANAGER | 0x1104334 | 5,361 | 6 | 5 | 0 |
| db::ACTUAL_NON_PLAYER | PRESS_CONFERENCE_MANAGER | 0x1f4cf34 | 35,845 | 4 | 0 | 0 |
| db::ACTUAL_PLAYER | HUMAN_NON_PLAYER_MANAGER | 0x1104334 | 1,003 | 6 | 4 | 0 |
| db::ACTUAL_PLAYER | NEWS_MANAGER | 0x1104334 | 51,305 | 13 | 4 | 1 |
| db::ACTUAL_PLAYER | TRANSFER_MANAGER+0x18 | 0x1104334 | 43,170 | 6 | 1 | 0 |
| db::ACTUAL_PLAYER | EDIT_SESSION_MANAGER | 0x1104334 | 313 | 6 | 3 | 0 |
| db::ACTUAL_PLAYER | SCOUT_MANAGER | 0x1104334 | 3,247 | 6 | 4 | 0 |
| db::ACTUAL_PLAYER | AWOL_MANAGER | 0x1104334 | 37 | 5 | 3 | 0 |
| db::ACTUAL_PLAYER | AWARD_MANAGER | 0x1104334 | 958 | 5 | 4 | 0 |
| db::ACTUAL_PLAYER | FINE_MANAGER | 0x1104334 | 10 | 5 | 3 | 0 |
| db::ACTUAL_PLAYER | CONTRACT_MANAGER | 0x1104334 | 8 | 6 | 3 | 0 |
| db::ACTUAL_PLAYER | MEDIA_MANAGER+0x18 | 0x1104334 | 13,473 | 6 | 4 | 1 |
| db::ACTUAL_PLAYER | MATCHDAY_MANAGER | 0x1104334 | 110 | 6 | 4 | 0 |
| db::ACTUAL_PLAYER | PLAY_FIXTURE_MANAGER | 0x1104334 | 1,104 | 6 | 4 | 0 |
| db::BASIC_GOAL_DESCRIPTION | NEWS_MANAGER | 0xd92dac | 305 | 7 | 6 | 0 |
| db::BASIC_GOAL_DESCRIPTION | SCOUT_MANAGER | 0xd92dac | 118 | 7 | 6 | 0 |
| db::BASIC_GOAL_DESCRIPTION | PRESS_CONFERENCE_MANAGER | 0xd92dac | 646 | 7 | 6 | 0 |
| db::BASIC_GOAL_DESCRIPTION | MEDIA_MANAGER+0x18 | 0xd92dac | 2,994 | 7 | 6 | 0 |
| db::CLUB | GAME_RULE_GROUP_MANAGER | 0x1107d38 | 19,175 | 3 | 3 | 0 |
| db::CLUB | HUMAN_NON_PLAYER_MANAGER | 0x1107d38 | 391 | 4 | 3 | 0 |
| db::CLUB | NEWS_MANAGER | 0x1107d38 | 43,418 | 4 | 3 | 0 |
| db::CLUB | TRANSFER_MANAGER+0x18 | 0x1107d38 | 82,215 | 4 | 1 | 0 |
| db::CLUB | SHORTLIST_MANAGER | 0x1107d38 | 162 | 3 | 1 | 0 |
| db::CLUB | TEAM_CONTAINER_RECORD_MANAGER | 0x1107d38 | 86,442 | 4 | 4 | 0 |
| db::CLUB | TACTICS_MANAGER | 0x1107d38 | 16,911 | 3 | 3 | 0 |
| db::CLUB | REGENERATION_MANAGER+0x18 | 0x1107d38 | 64 | 4 | 3 | 0 |
| db::CLUB | EDIT_SESSION_MANAGER | 0x1107d38 | 25 | 3 | 3 | 0 |
| db::CLUB | TRAINING_MANAGER | 0x1107d38 | 5 | 3 | 3 | 0 |
| db::CLUB | TRAINING_MANAGER | 0x11008fc | 1 | 1 | 1 | 0 |
| db::CLUB | TRAINING_CAMP_MANAGER | 0x1107d38 | 171 | 3 | 3 | 0 |
| db::CLUB | SCOUT_MANAGER | 0x1107d38 | 1,813 | 4 | 4 | 0 |
| db::CLUB | AWOL_MANAGER | 0x1107d38 | 1 | 3 | 3 | 0 |
| db::CLUB | AWARD_MANAGER | 0x1107d38 | 734 | 3 | 3 | 0 |
| db::CLUB | FINE_MANAGER | 0x1107d38 | 10 | 3 | 3 | 0 |
| db::CLUB | CONTRACT_MANAGER | 0x1107d38 | 2 | 3 | 3 | 0 |
| db::CLUB | PERSON_RECORD_MANAGER | 0x1107d38 | 14,808 | 3 | 1 | 0 |
| db::CLUB | FINANCE_MANAGER | 0x1107d38 | 24 | 4 | 3 | 0 |
| db::CLUB | SIMULATED_STATS_MANAGER | 0x1107d38 | 22,959 | 3 | 3 | 0 |
| db::CLUB | BACKROOM_ADVICE_MANAGER | 0x1107d38 | 2,774 | 3 | 3 | 0 |
| db::CLUB | INTERACTION_MANAGER | 0x1107d38 | 10,096 | 3 | 1 | 0 |
| db::CLUB | PRESS_CONFERENCE_MANAGER | 0x1107d38 | 19,473 | 3 | 3 | 0 |
| db::CLUB | JOB_CENTRE_MANAGER | 0x1107d38 | 143 | 3 | 3 | 0 |
| db::CLUB | TEAM_TALK_MANAGER | 0x1107d38 | 1 | 3 | 3 | 0 |
| db::CLUB | BOARD_TAKEOVER_MANAGER | 0x1107d38 | 25 | 3 | 3 | 0 |
| db::CLUB | FINANCIAL_FAIR_PLAY_MANAGER | 0x1107d38 | 1 | 3 | 3 | 0 |
| db::CLUB | FEEDER_CLUB_MANAGER | 0x1107d38 | 349 | 3 | 3 | 0 |
| db::CLUB | MEDIA_MANAGER+0x18 | 0x1107d38 | 7,305 | 3 | 3 | 0 |
| db::CLUB | MATCHDAY_MANAGER | 0x1107d38 | 76 | 3 | 3 | 0 |
| db::CLUB | PLAY_FIXTURE_MANAGER | 0x1107d38 | 64 | 3 | 3 | 0 |
| db::CLUB | MANAGER_MANAGER | 0x1107d38 | 30,199 | 4 | 4 | 0 |
| db::CLUB_COMPETITION_VISION_OBJECTIVE | MANAGER_MANAGER | 0xecbadc | 2,075 | 9 | 2 | 0 |
| db::CLUB_VISION_OBJECTIVE | NEWS_MANAGER | 0xeececc | 263 | 8 | 6 | 0 |
| db::CLUB_VISION_OBJECTIVE | NEWS_MANAGER | 0xee6148 | 262 | 7 | 6 | 0 |
| db::CLUB_VISION_OBJECTIVE | NEWS_MANAGER | 0x1ddad64 | 196 | 56 | 55 | 0 |
| db::CLUB_VISION_OBJECTIVE | NEWS_MANAGER | 0x2f8b9c0 | 65 | 2 | 1 | 0 |
| db::CLUB_VISION_OBJECTIVE | NEWS_MANAGER | 0x3017564 | 12 | 7 | 4 | 0 |
| db::CLUB_VISION_OBJECTIVE | NEWS_MANAGER | 0x3a08b68 | 1 | 6 | 4 | 0 |
| db::CLUB_VISION_OBJECTIVE | BOARD_TAKEOVER_MANAGER | 0x3a08b68 | 17 | 6 | 5 | 0 |
| db::CLUB_VISION_OBJECTIVE | BOARD_TAKEOVER_MANAGER | 0xee6148 | 17 | 7 | 6 | 0 |
| db::CLUB_VISION_OBJECTIVE | BOARD_TAKEOVER_MANAGER | 0xeececc | 17 | 8 | 6 | 0 |
| db::CLUB_VISION_OBJECTIVE | MANAGER_MANAGER | 0xee6148 | 6,150 | 7 | 6 | 0 |
| db::CLUB_VISION_OBJECTIVE | MANAGER_MANAGER | 0xeececc | 6,150 | 8 | 6 | 0 |
| db::COMP | HUMAN_NON_PLAYER_MANAGER | 0x1101624 | 202 | 7 | 5 | 1 |
| db::COMP | NEWS_MANAGER | 0x1105e94 | 7,507 | 1 | 0 | 0 |
| db::COMP | TEAM_CONTAINER_RECORD_MANAGER | 0x1101624 | 43,219 | 9 | 8 | 2 |
| db::COMP | SCOUT_MANAGER | 0x1101624 | 724 | 10 | 9 | 2 |
| db::COMP | AWARD_MANAGER | 0x1101624 | 228 | 7 | 4 | 0 |
| db::COMP | PERSON_RECORD_MANAGER | 0x1101624 | 37 | 7 | 4 | 1 |
| db::COMP | BACKROOM_ADVICE_MANAGER | 0x1101624 | 225 | 7 | 5 | 1 |
| db::COMP | INTERACTION_MANAGER | 0x1101624 | 6,787 | 7 | 4 | 1 |
| db::COMP | JOB_CENTRE_MANAGER | 0x1101624 | 143 | 9 | 7 | 2 |
| db::COMP | FINANCIAL_FAIR_PLAY_MANAGER | 0x1101624 | 1 | 7 | 4 | 1 |
| db::COMP | MEDIA_MANAGER+0x18 | 0x1101624 | 8,345 | 14 | 7 | 2 |
| db::COMP | MATCHDAY_MANAGER | 0x1101624 | 44 | 9 | 8 | 2 |
| db::COMP | PLAY_FIXTURE_MANAGER | 0x1101624 | 32 | 7 | 4 | 1 |
| db::COMP | MANAGER_MANAGER | 0x1101624 | 16,742 | 9 | 7 | 2 |
| db::FACILITY_UPGRADE | FINANCE_MANAGER | 0xeb19dc | 1 | 5 | 4 | 0 |
| db::FIXTURE_NAME | GAME_RULE_GROUP_MANAGER | 0x126257c | 7,179 | 12 | 1 | 0 |
| db::FIXTURE_NAME | NEWS_MANAGER | 0x126257c | 4,294 | 1 | 0 | 0 |
| db::FIXTURE_NAME | TEAM_CONTAINER_RECORD_MANAGER | 0x126257c | 23,455 | 1 | 1 | 0 |
| db::FIXTURE_NAME | EDIT_SESSION_MANAGER | 0x110418c | 6 | 2 | 1 | 0 |
| db::FIXTURE_NAME | EDIT_SESSION_MANAGER | 0x126257c | 6 | 1 | 0 | 0 |
| db::FIXTURE_NAME | SCOUT_MANAGER | 0x110418c | 176 | 2 | 2 | 0 |
| db::FIXTURE_NAME | SCOUT_MANAGER | 0x126257c | 122 | 1 | 1 | 0 |
| db::FIXTURE_NAME | PERSON_RECORD_MANAGER | 0x110418c | 8 | 2 | 1 | 0 |
| db::FIXTURE_NAME | PERSON_RECORD_MANAGER | 0x126257c | 8 | 1 | 0 | 0 |
| db::FIXTURE_NAME | PRESS_CONFERENCE_MANAGER | 0x110418c | 8,858 | 2 | 2 | 0 |
| db::FIXTURE_NAME | PRESS_CONFERENCE_MANAGER | 0x126257c | 4,653 | 1 | 1 | 0 |
| db::FIXTURE_NAME | MEDIA_MANAGER+0x18 | 0x110418c | 6,758 | 2 | 2 | 0 |
| db::FIXTURE_NAME | MEDIA_MANAGER+0x18 | 0x126257c | 6,142 | 1 | 1 | 0 |
| db::FIXTURE_NAME | PLAY_FIXTURE_MANAGER | 0x110418c | 32 | 2 | 1 | 0 |
| db::FIXTURE_NAME | PLAY_FIXTURE_MANAGER | 0x126257c | 32 | 1 | 0 | 0 |
| db::FIXTURE_NAME | MANAGER_MANAGER | 0x126257c | 2,498 | 1 | 0 | 0 |
| db::GOAL_DESCRIPTION | NEWS_MANAGER | 0x12b0674 | 173 | 4 | 3 | 0 |
| db::GOAL_DESCRIPTION | SCOUT_MANAGER | 0x12b0674 | 118 | 4 | 3 | 0 |
| db::HUMAN_NON_PLAYER | TACTICS_MANAGER | 0x1104334 | 1 | 5 | 3 | 0 |
| db::HUMAN_NON_PLAYER | FOG_OF_WAR_MANAGER | 0x1104334 | 1 | 5 | 3 | 0 |
| db::HUMAN_NON_PLAYER | TEAM_TALK_MANAGER | 0x1104334 | 1 | 5 | 3 | 0 |
| db::INTERACTION_COMMENT | INTERACTION_MANAGER | 0x1332798 | 22,707 | 16 | 10 | 0 |
| db::INTERACTION_COMMENT | MANAGER_MANAGER | 0x1332798 | 41 | 16 | 7 | 0 |
| db::MEDIA_SOURCE | NEWS_MANAGER | 0x1102ce4 | 4,437 | 10 | 6 | 2 |
| db::MEDIA_SOURCE | EDIT_SESSION_MANAGER | 0x1102ce4 | 21 | 3 | 2 | 0 |
| db::MEDIA_SOURCE | PRESS_CONFERENCE_MANAGER | 0x1102ce4 | 17,049 | 10 | 10 | 1 |
| db::NATION | HUMAN_NON_PLAYER_MANAGER | 0x1103e7c | 36 | 1 | 0 | 0 |
| db::NATION | SCOUT_MANAGER | 0x1103e7c | 1 | 1 | 0 | 0 |
| db::NATIONAL_TEAM | MEDIA_MANAGER+0x18 | 0x1101440 | 39,506 | 1 | 1 | 0 |
| db::NATIONAL_TEAM | MEDIA_MANAGER+0x18 | 0x1107810 | 39,506 | 8 | 6 | 0 |
| db::NON_PLAYER_TENDENCY_TEMPLATE | REGENERATION_MANAGER+0x18 | 0x1462e98 | 2,619 | 9 | 9 | 0 |
| db::OFFICIAL | OFFICIAL_MANAGER | 0x1104334 | 1,953 | 5 | 4 | 0 |
| db::PLAYER_HEIGHTS_TEMPLATE | REGENERATION_MANAGER+0x18 | 0x154b204 | 90 | 5 | 4 | 0 |
| db::PLAYING_DATA | REGENERATION_MANAGER+0x18 | 0x140a4a4 | 16 | 26 | 21 | 0 |
| db::SCORELINE | GAME_RULE_GROUP_MANAGER | 0x1629048 | 2,604 | 16 | 15 | 0 |
| db::SCORELINE | GAME_RULE_GROUP_MANAGER | 0x2f9d430 | 434 | 85 | 77 | 0 |
| db::SCORELINE | HUMAN_NON_PLAYER_MANAGER | 0x1683a34 | 6 | 10 | 9 | 0 |
| db::SCORELINE | HUMAN_NON_PLAYER_MANAGER | 0x1629048 | 6 | 16 | 15 | 0 |
| db::SCORELINE | NEWS_MANAGER | 0x1629048 | 3,621 | 16 | 15 | 0 |
| db::SCORELINE | NEWS_MANAGER | 0x2f9d430 | 655 | 85 | 79 | 0 |
| db::SCORELINE | NEWS_MANAGER | 0x1ca4e08 | 542 | 106 | 98 | 0 |
| db::SCORELINE | NEWS_MANAGER | 0x1cd2504 | 159 | 29 | 21 | 0 |
| db::SCORELINE | NEWS_MANAGER | 0x2f3a768 | 128 | 18 | 17 | 0 |
| db::SCORELINE | NEWS_MANAGER | 0x392f380 | 73 | 10 | 9 | 0 |
| db::SCORELINE | NEWS_MANAGER | 0x2f50d38 | 49 | 4 | 3 | 0 |
| db::SCORELINE | NEWS_MANAGER | 0x2f4f554 | 32 | 3 | 2 | 0 |
| db::SCORELINE | NEWS_MANAGER | 0x2f38ecc | 1 | 7 | 5 | 0 |
| db::SCORELINE | EDIT_SESSION_MANAGER | 0x1629048 | 1 | 16 | 15 | 0 |
| db::SCORELINE | SCOUT_MANAGER | 0x395db18 | 7 | 8 | 7 | 0 |
| db::SCORELINE | SCOUT_MANAGER | 0x1629048 | 7 | 16 | 15 | 0 |
| db::SCORELINE | PERSON_RECORD_MANAGER | 0x1629048 | 8 | 16 | 15 | 0 |
| db::SCORELINE | PRESS_CONFERENCE_MANAGER | 0x1629048 | 7,682 | 16 | 15 | 0 |
| db::SCORELINE | PRESS_CONFERENCE_MANAGER | 0x392f380 | 4,674 | 10 | 10 | 0 |
| db::SCORELINE | PRESS_CONFERENCE_MANAGER | 0x2f9d430 | 588 | 85 | 81 | 0 |
| db::SCORELINE | PRESS_CONFERENCE_MANAGER | 0x2f38ecc | 102 | 7 | 5 | 0 |
| db::SCORELINE | MEDIA_MANAGER+0x18 | 0x1629048 | 6,450 | 16 | 15 | 0 |
| db::SCORELINE | MEDIA_MANAGER+0x18 | 0x2f3a768 | 2,994 | 18 | 17 | 0 |
| db::SCORELINE | MEDIA_MANAGER+0x18 | 0x2f9d430 | 154 | 85 | 77 | 0 |
| db::STADIUM | NEWS_MANAGER | 0x11047bc | 7,941 | 1 | 1 | 0 |
| db::STADIUM | EDIT_SESSION_MANAGER | 0x11047bc | 10 | 1 | 1 | 0 |
| db::STADIUM | SCOUT_MANAGER | 0x11047bc | 118 | 1 | 1 | 0 |
| db::STADIUM | PERSON_RECORD_MANAGER | 0x11047bc | 9 | 1 | 0 | 0 |
| db::STADIUM | FINANCE_MANAGER | 0x11047bc | 44 | 1 | 1 | 0 |
| db::STADIUM | INTERACTION_MANAGER | 0x11047bc | 6,787 | 1 | 0 | 0 |
| db::STADIUM | PRESS_CONFERENCE_MANAGER | 0x11047bc | 5,850 | 1 | 0 | 0 |
| db::STADIUM | MEDIA_MANAGER+0x18 | 0x11047bc | 3,456 | 1 | 1 | 0 |
| db::STADIUM | MATCHDAY_MANAGER | 0x11047bc | 38 | 1 | 1 | 0 |
| db::STADIUM | PLAY_FIXTURE_MANAGER | 0x11047bc | 32 | 1 | 1 | 0 |
| db::TEAM | TRANSFER_MANAGER+0x18 | 0x1101440 | 69,566 | 1 | 0 | 0 |
| db::TEAM | TRANSFER_MANAGER+0x18 | 0x1107810 | 69,565 | 8 | 5 | 2 |
| db::TEAM | SHORTLIST_MANAGER | 0x1101440 | 162 | 1 | 0 | 0 |
| db::TEAM | SHORTLIST_MANAGER | 0x1107810 | 162 | 6 | 5 | 2 |
| db::TEAM | TACTICS_MANAGER | 0x1101440 | 24,354 | 1 | 1 | 0 |
| db::TEAM | TACTICS_MANAGER | 0x1107810 | 24,354 | 8 | 6 | 0 |
| db::TEAM | REGENERATION_MANAGER+0x18 | 0x1101440 | 16 | 1 | 1 | 0 |
| db::TEAM | REGENERATION_MANAGER+0x18 | 0x1107810 | 16 | 6 | 6 | 0 |
| db::TEAM | TRAINING_MANAGER | 0x1101440 | 4 | 1 | 1 | 0 |
| db::TEAM | TRAINING_MANAGER | 0x1107810 | 4 | 6 | 5 | 2 |
| db::TEAM | TRAINING_CAMP_MANAGER | 0x1101440 | 171 | 1 | 1 | 0 |
| db::TEAM | TRAINING_CAMP_MANAGER | 0x1107810 | 171 | 6 | 5 | 0 |
| db::TEAM | AWARD_MANAGER | 0x1101440 | 1,280 | 1 | 1 | 0 |
| db::TEAM | AWARD_MANAGER | 0x1107810 | 1,280 | 8 | 7 | 2 |
| db::TEAM | SIMULATED_STATS_MANAGER | 0x1101440 | 22,959 | 1 | 1 | 0 |
| db::TEAM | SIMULATED_STATS_MANAGER | 0x1107810 | 22,959 | 6 | 5 | 2 |
| db::TEAM | BACKROOM_ADVICE_MANAGER | 0x1101440 | 3,784 | 1 | 1 | 0 |
| db::TEAM | BACKROOM_ADVICE_MANAGER | 0x1107810 | 3,784 | 7 | 6 | 1 |
| db::TEAM | INTERACTION_MANAGER | 0x1101440 | 10,327 | 1 | 0 | 0 |
| db::TEAM | INTERACTION_MANAGER | 0x1107810 | 10,327 | 7 | 3 | 0 |
| db::TEAM | JOB_CENTRE_MANAGER | 0x1101440 | 143 | 1 | 1 | 0 |
| db::TEAM | JOB_CENTRE_MANAGER | 0x1107810 | 143 | 6 | 5 | 2 |
| db::TEAM | TEAM_TALK_MANAGER | 0x1101440 | 1 | 1 | 1 | 0 |
| db::TEAM | TEAM_TALK_MANAGER | 0x1107810 | 1 | 6 | 6 | 0 |
| db::TEAM | MATCHDAY_MANAGER | 0x1101440 | 76 | 1 | 1 | 0 |
| db::TEAM | MATCHDAY_MANAGER | 0x1107810 | 76 | 6 | 5 | 2 |
| db::TEAM | PLAY_FIXTURE_MANAGER | 0x1101440 | 64 | 1 | 1 | 0 |
| db::TEAM | PLAY_FIXTURE_MANAGER | 0x1107810 | 64 | 6 | 6 | 1 |
| db::TEAM | MANAGER_MANAGER | 0x1101440 | 50,752 | 1 | 1 | 0 |
| db::TEAM | MANAGER_MANAGER | 0x1107810 | 50,752 | 8 | 5 | 0 |
| db::TEAM_MEETING_INTERACTION_COMMENT | INTERACTION_MANAGER | 0x13333f0 | 25 | 4 | 2 | 0 |
| db::VISION_OBJECTIVE | TRANSFER_MANAGER+0x18 | 0xeececc | 806 | 8 | 6 | 0 |
| db::VISION_OBJECTIVE | SCOUT_MANAGER | 0xeececc | 17 | 8 | 6 | 0 |
| fmdate::SI_DATE_TYPED_TRAITS | GAME_RULE_GROUP_MANAGER | 0x42f0744 | 332 | 1 | 1 | 0 |
| fmdate::SI_DATE_TYPED_TRAITS | NEWS_MANAGER | 0x42f0744 | 230 | 1 | 1 | 0 |
| fmdate::SI_DATE_TYPED_TRAITS | EDIT_SESSION_MANAGER | 0x42f0744 | 8 | 1 | 1 | 0 |
| fmdate::SI_DATE_TYPED_TRAITS | PRESS_CONFERENCE_MANAGER | 0x42f0744 | 2,133 | 1 | 1 | 0 |
| sicomps::ACTUAL_COMP | GAME_RULE_GROUP_MANAGER | 0x3af1b00 | 112 | 1 | 0 | 0 |
| sicomps::ACTUAL_COMP | GAME_RULE_GROUP_MANAGER | 0x3af1e7c | 112 | 418 | 75 | 0 |
| sicomps::AGE_EXTRA_SQUAD_SELECTION_RULE | NEWS_MANAGER | 0x3cd6cf8 | 1 | 4 | 4 | 0 |
| sicomps::CONTINENTAL_CUP_SEEDING | GAME_RULE_GROUP_MANAGER | 0x3c2d8b8 | 12 | 167 | 74 | 0 |
| sicomps::CUP_FATE_ACTION_COMP_QUALIFICATION | GAME_RULE_GROUP_MANAGER | 0x3c382a8 | 14 | 12 | 12 | 0 |
| sicomps::CUP_FATE_ACTION_INSERT_INTO_CUP | GAME_RULE_GROUP_MANAGER | 0x3c38c00 | 11 | 6 | 6 | 0 |
| sicomps::CUP_FATE_ACTION_QUALIFICATION | GAME_RULE_GROUP_MANAGER | 0x3c37244 | 43 | 6 | 6 | 0 |
| sicomps::CUP_FATE_ACTION_SET_CONTINENTAL_CUP | GAME_RULE_GROUP_MANAGER | 0x3c380b8 | 45 | 3 | 3 | 0 |
| sicomps::CUP_FATE_ACTION_SET_LEAGUE_FATE | GAME_RULE_GROUP_MANAGER | 0x3c375a4 | 8 | 7 | 7 | 0 |
| sicomps::CUP_FATE_ACTION_SET_TEAM_PLACING | GAME_RULE_GROUP_MANAGER | 0x3c38950 | 5 | 5 | 5 | 0 |
| sicomps::CUP_SETTINGS | GAME_RULE_GROUP_MANAGER | 0x3c72c28 | 44 | 87 | 68 | 0 |
| sicomps::CUP_STAGE | GAME_RULE_GROUP_MANAGER | 0x3c72174 | 44 | 62 | 59 | 0 |
| sicomps::EMPTY_SETTINGS | GAME_RULE_GROUP_MANAGER | 0x3fc38ac | 2 | 7 | 7 | 0 |
| sicomps::EMPTY_STAGE | GAME_RULE_GROUP_MANAGER | 0x3fc3f3c | 2 | 2 | 0 | 0 |
| sicomps::EUR_SEEDING | GAME_RULE_GROUP_MANAGER | 0x407972c | 1 | 31 | 28 | 0 |
| sicomps::FIXTURE | EDIT_SESSION_MANAGER | 0x3cf71a8 | 5 | 27 | 26 | 0 |
| sicomps::FIXTURE | MATCHDAY_MANAGER | 0x3cf71a8 | 7 | 27 | 26 | 0 |
| sicomps::FIXTURE | PLAY_FIXTURE_MANAGER | 0x3cf71a8 | 32 | 27 | 26 | 0 |
| sicomps::FIXTURE_RESULT | GAME_RULE_GROUP_MANAGER | 0x3cf8340 | 423 | 17 | 9 | 0 |
| sicomps::FIXTURE_RESULT | GAME_RULE_GROUP_MANAGER | 0x3cf71a8 | 423 | 27 | 26 | 0 |
| sicomps::FIXTURE_RESULT | NEWS_MANAGER | 0x4acbad4 | 166 | 10 | 7 | 0 |
| sicomps::FIXTURE_RESULT | NEWS_MANAGER | 0x4acbf68 | 166 | 23 | 20 | 0 |
| sicomps::FIXTURE_RESULT | NEWS_MANAGER | 0x3cf9adc | 166 | 13 | 5 | 0 |
| sicomps::FIXTURE_RESULT | NEWS_MANAGER | 0x3cf71a8 | 4 | 27 | 26 | 0 |
| sicomps::FIXTURE_RESULT | NEWS_MANAGER | 0x3cf8340 | 2 | 11 | 7 | 0 |
| sicomps::FIXTURE_RESULT | EDIT_SESSION_MANAGER | 0x4acbad4 | 5 | 10 | 5 | 0 |
| sicomps::FIXTURE_RESULT | EDIT_SESSION_MANAGER | 0x4acbf68 | 5 | 23 | 20 | 0 |
| sicomps::FIXTURE_RESULT | EDIT_SESSION_MANAGER | 0x3cf9adc | 5 | 2 | 1 | 0 |
| sicomps::FIXTURE_RESULT | EDIT_SESSION_MANAGER | 0x3cf8340 | 1 | 10 | 9 | 0 |
| sicomps::FIXTURE_RESULT | PLAY_FIXTURE_MANAGER | 0x4acbad4 | 32 | 10 | 7 | 0 |
| sicomps::FIXTURE_RESULT | PLAY_FIXTURE_MANAGER | 0x4acbf68 | 32 | 23 | 20 | 0 |
| sicomps::FIXTURE_RESULT | PLAY_FIXTURE_MANAGER | 0x3cf9adc | 32 | 5 | 1 | 0 |
| sicomps::GROUP_SETTINGS | GAME_RULE_GROUP_MANAGER | 0x3de5394 | 47 | 7 | 1 | 0 |
| sicomps::GROUP_SETTINGS | GAME_RULE_GROUP_MANAGER | 0x3de98c0 | 47 | 6 | 4 | 0 |
| sicomps::GROUP_STAGE | GAME_RULE_GROUP_MANAGER | 0x3de5204 | 47 | 3 | 1 | 0 |
| sicomps::GROUP_STAGE | GAME_RULE_GROUP_MANAGER | 0x3de4e2c | 47 | 6 | 6 | 0 |
| sicomps::LEAGUE_FATE_ACTION_COMP_QUALIFICATION | GAME_RULE_GROUP_MANAGER | 0x3e0db04 | 219 | 8 | 8 | 0 |
| sicomps::LEAGUE_FATE_ACTION_INSERT_INTO_CUP | GAME_RULE_GROUP_MANAGER | 0x3e0d778 | 64 | 3 | 3 | 0 |
| sicomps::LEAGUE_FATE_ACTION_POSITION_COMP_QUALIFICATION | GAME_RULE_GROUP_MANAGER | 0x3e0ddfc | 44 | 12 | 12 | 0 |
| sicomps::LEAGUE_FATE_ACTION_POSITION_QUALIFICATION | GAME_RULE_GROUP_MANAGER | 0x3e0c504 | 2 | 5 | 4 | 0 |
| sicomps::LEAGUE_FATE_ACTION_PROMOTION | GAME_RULE_GROUP_MANAGER | 0x3e0bd4c | 61 | 3 | 3 | 0 |
| sicomps::LEAGUE_FATE_ACTION_QUALIFICATION | GAME_RULE_GROUP_MANAGER | 0x3e0c07c | 131 | 4 | 3 | 0 |
| sicomps::LEAGUE_FATE_ACTION_RELEGATION | GAME_RULE_GROUP_MANAGER | 0x3e0bf08 | 71 | 2 | 2 | 0 |
| sicomps::LEAGUE_FATE_ACTION_SET_CONTINENTAL_CUP | GAME_RULE_GROUP_MANAGER | 0x3e0d5e8 | 10 | 3 | 3 | 0 |
| sicomps::LEAGUE_FATE_ACTION_SET_LEAGUE_FATE | GAME_RULE_GROUP_MANAGER | 0x3e0c738 | 3 | 5 | 5 | 0 |
| sicomps::LEAGUE_FATE_ACTION_SORT_ORDER_RANDOM_DRAW | GAME_RULE_GROUP_MANAGER | 0x3e11670 | 3 | 2 | 2 | 0 |
| sicomps::LEAGUE_SETTINGS | GAME_RULE_GROUP_MANAGER | 0x3fb9000 | 340 | 6 | 5 | 0 |
| sicomps::LEAGUE_SETTINGS | GAME_RULE_GROUP_MANAGER | 0x3eee244 | 247 | 118 | 96 | 0 |
| sicomps::LEAGUE_STAGE | GAME_RULE_GROUP_MANAGER | 0x3fbbb18 | 340 | 14 | 12 | 0 |
| sicomps::LEAGUE_STAGE | GAME_RULE_GROUP_MANAGER | 0x3eedbfc | 247 | 20 | 12 | 0 |
| sicomps::OCE_SEEDING | GAME_RULE_GROUP_MANAGER | 0x41f1870 | 1 | 2 | 2 | 0 |
| sicore::DATA_TYPED_TRAITS | NEWS_MANAGER | 0x437cee0 | 1,880 | 26 | 14 | 0 |
| simatch::ATTACK_CORNER_ROUTINE | NEWS_MANAGER | 0x4a88940 | 4 | 6 | 3 | 0 |
| simatch::ATTACK_CORNER_ROUTINE | NEWS_MANAGER | 0x4a89358 | 2 | 2 | 2 | 0 |
| simatch::ATTACK_CORNER_ROUTINE | TACTICS_MANAGER | 0x4a88940 | 8 | 9 | 8 | 0 |
| simatch::ATTACK_CORNER_ROUTINE | TACTICS_MANAGER | 0x4a89358 | 4 | 2 | 2 | 0 |
| simatch::ATTACK_CORNER_ROUTINE | EDIT_SESSION_MANAGER | 0x4a88940 | 4 | 9 | 9 | 0 |
| simatch::ATTACK_CORNER_ROUTINE | EDIT_SESSION_MANAGER | 0x4a89358 | 2 | 2 | 2 | 0 |
| simatch::ATTACK_FREE_KICK_DEEP_ROUTINE | NEWS_MANAGER | 0x4a87cbc | 4 | 6 | 3 | 0 |
| simatch::ATTACK_FREE_KICK_DEEP_ROUTINE | NEWS_MANAGER | 0x4a886d4 | 2 | 1 | 1 | 0 |
| simatch::ATTACK_FREE_KICK_DEEP_ROUTINE | TACTICS_MANAGER | 0x4a87cbc | 8 | 9 | 8 | 0 |
| simatch::ATTACK_FREE_KICK_DEEP_ROUTINE | TACTICS_MANAGER | 0x4a886d4 | 4 | 1 | 1 | 0 |
| simatch::ATTACK_FREE_KICK_DEEP_ROUTINE | EDIT_SESSION_MANAGER | 0x4a87cbc | 4 | 9 | 9 | 0 |
| simatch::ATTACK_FREE_KICK_DEEP_ROUTINE | EDIT_SESSION_MANAGER | 0x4a886d4 | 2 | 1 | 1 | 0 |
| simatch::ATTACK_FREE_KICK_EDGE_OF_AREA_ROUTINE | NEWS_MANAGER | 0x4a86354 | 4 | 6 | 3 | 0 |
| simatch::ATTACK_FREE_KICK_EDGE_OF_AREA_ROUTINE | NEWS_MANAGER | 0x4a86d6c | 2 | 1 | 1 | 0 |
| simatch::ATTACK_FREE_KICK_EDGE_OF_AREA_ROUTINE | TACTICS_MANAGER | 0x4a86354 | 8 | 9 | 8 | 0 |
| simatch::ATTACK_FREE_KICK_EDGE_OF_AREA_ROUTINE | TACTICS_MANAGER | 0x4a86d6c | 4 | 1 | 1 | 0 |
| simatch::ATTACK_FREE_KICK_EDGE_OF_AREA_ROUTINE | EDIT_SESSION_MANAGER | 0x4a86354 | 4 | 9 | 9 | 0 |
| simatch::ATTACK_FREE_KICK_EDGE_OF_AREA_ROUTINE | EDIT_SESSION_MANAGER | 0x4a86d6c | 2 | 1 | 1 | 0 |
| simatch::ATTACK_FREE_KICK_WIDE_ROUTINE | NEWS_MANAGER | 0x4a86fd8 | 4 | 6 | 3 | 0 |
| simatch::ATTACK_FREE_KICK_WIDE_ROUTINE | NEWS_MANAGER | 0x4a879f0 | 2 | 2 | 2 | 0 |
| simatch::ATTACK_FREE_KICK_WIDE_ROUTINE | TACTICS_MANAGER | 0x4a86fd8 | 8 | 9 | 8 | 0 |
| simatch::ATTACK_FREE_KICK_WIDE_ROUTINE | TACTICS_MANAGER | 0x4a879f0 | 4 | 2 | 2 | 0 |
| simatch::ATTACK_FREE_KICK_WIDE_ROUTINE | EDIT_SESSION_MANAGER | 0x4a86fd8 | 4 | 9 | 9 | 0 |
| simatch::ATTACK_FREE_KICK_WIDE_ROUTINE | EDIT_SESSION_MANAGER | 0x4a879f0 | 2 | 2 | 2 | 0 |
| simatch::ATTACK_THROW_IN_ROUTINE | NEWS_MANAGER | 0x4a85810 | 4 | 6 | 3 | 0 |
| simatch::ATTACK_THROW_IN_ROUTINE | TACTICS_MANAGER | 0x4a85810 | 8 | 9 | 8 | 0 |
| simatch::ATTACK_THROW_IN_ROUTINE | EDIT_SESSION_MANAGER | 0x4a85810 | 4 | 9 | 9 | 0 |
| simatch::DEFEND_CORNER_ROUTINE | NEWS_MANAGER | 0x4a815b0 | 40 | 4 | 3 | 0 |
| simatch::DEFEND_CORNER_ROUTINE | NEWS_MANAGER | 0x4a813ac | 4 | 6 | 3 | 0 |
| simatch::DEFEND_CORNER_ROUTINE | NEWS_MANAGER | 0x4a80b48 | 2 | 5 | 4 | 0 |
| simatch::DEFEND_CORNER_ROUTINE | TACTICS_MANAGER | 0x4a815b0 | 80 | 4 | 3 | 0 |
| simatch::DEFEND_CORNER_ROUTINE | TACTICS_MANAGER | 0x4a813ac | 8 | 6 | 5 | 0 |
| simatch::DEFEND_CORNER_ROUTINE | TACTICS_MANAGER | 0x4a80b48 | 4 | 5 | 4 | 0 |
| simatch::DEFEND_CORNER_ROUTINE | EDIT_SESSION_MANAGER | 0x4a815b0 | 40 | 4 | 3 | 0 |
| simatch::DEFEND_CORNER_ROUTINE | EDIT_SESSION_MANAGER | 0x4a813ac | 4 | 6 | 6 | 0 |
| simatch::DEFEND_CORNER_ROUTINE | EDIT_SESSION_MANAGER | 0x4a80b48 | 2 | 5 | 4 | 0 |
| simatch::DEFEND_FREE_KICK_DEEP_ROUTINE | NEWS_MANAGER | 0x4a83c80 | 4 | 6 | 3 | 0 |
| simatch::DEFEND_FREE_KICK_DEEP_ROUTINE | NEWS_MANAGER | 0x4a847e8 | 2 | 1 | 1 | 0 |
| simatch::DEFEND_FREE_KICK_DEEP_ROUTINE | TACTICS_MANAGER | 0x4a83c80 | 8 | 9 | 9 | 0 |
| simatch::DEFEND_FREE_KICK_DEEP_ROUTINE | TACTICS_MANAGER | 0x4a847e8 | 4 | 1 | 1 | 0 |
| simatch::DEFEND_FREE_KICK_DEEP_ROUTINE | EDIT_SESSION_MANAGER | 0x4a83c80 | 4 | 9 | 9 | 0 |
| simatch::DEFEND_FREE_KICK_DEEP_ROUTINE | EDIT_SESSION_MANAGER | 0x4a847e8 | 2 | 1 | 1 | 0 |
| simatch::DEFEND_FREE_KICK_EDGE_OF_AREA_ROUTINE | NEWS_MANAGER | 0x4a820f0 | 4 | 9 | 7 | 0 |
| simatch::DEFEND_FREE_KICK_EDGE_OF_AREA_ROUTINE | TACTICS_MANAGER | 0x4a820f0 | 8 | 9 | 8 | 0 |
| simatch::DEFEND_FREE_KICK_EDGE_OF_AREA_ROUTINE | EDIT_SESSION_MANAGER | 0x4a820f0 | 4 | 9 | 9 | 0 |
| simatch::DEFEND_FREE_KICK_WIDE_ROUTINE | NEWS_MANAGER | 0x4a82eac | 4 | 9 | 6 | 0 |
| simatch::DEFEND_FREE_KICK_WIDE_ROUTINE | NEWS_MANAGER | 0x4a83a14 | 2 | 1 | 1 | 0 |
| simatch::DEFEND_FREE_KICK_WIDE_ROUTINE | TACTICS_MANAGER | 0x4a82eac | 8 | 9 | 9 | 0 |
| simatch::DEFEND_FREE_KICK_WIDE_ROUTINE | TACTICS_MANAGER | 0x4a83a14 | 4 | 1 | 1 | 0 |
| simatch::DEFEND_FREE_KICK_WIDE_ROUTINE | EDIT_SESSION_MANAGER | 0x4a82eac | 4 | 9 | 9 | 0 |
| simatch::DEFEND_FREE_KICK_WIDE_ROUTINE | EDIT_SESSION_MANAGER | 0x4a83a14 | 2 | 1 | 1 | 0 |
| simatch::DEFEND_LONG_THROW_IN_ROUTINE | NEWS_MANAGER | 0x4a84a54 | 4 | 6 | 3 | 0 |
| simatch::DEFEND_LONG_THROW_IN_ROUTINE | TACTICS_MANAGER | 0x4a84a54 | 8 | 6 | 5 | 0 |
| simatch::DEFEND_LONG_THROW_IN_ROUTINE | EDIT_SESSION_MANAGER | 0x4a84a54 | 4 | 6 | 6 | 0 |
