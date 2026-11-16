# Bulk manager knowledge (fog of war)

`fm_live_mcp/knowledge_bulk.py` computes what the selected manager knows about many players in one read-only call. It returns the same cells as `fm_get_manager_visible_attributes` (see `docs/manager-visible-attributes.md`) at about 400 to 560 players per second of CPU instead of one player-field cell per 0.13 s, and it can confirm an earlier result from the inputs that result consumed instead of computing it again.

## API

| Function | Returns | Reads attribute bytes |
| --- | --- | --- |
| `visible_attributes_bulk(bridge_or_session, player_keys, fields=ALL_FIELDS, *, coach_name=None, on_progress=None)` | Per player the tool's cells (`exact`/`range`/`unknown`/`unavailable`) and `state_counts` | Only cells whose H is 1 or 2, one byte each |
| `player_knowledge_summary(bridge_or_session, player_keys, *, coach_name=None, on_progress=None)` | Per player: `context_k`, `node_score`, `report_score`, `own_club_context`, `category_byte`, `h_score`, `winning_sources`, exact/range/unknown/unavailable counts over the 47 fields, CA/PA star-gate H states (`0x62`, `0x63`) | None |
| `known_population(bridge_or_session, *, coach_name=None, evaluate=True, on_progress=None)` | Seed sets, their union and counts under each definition of "known" | None |

`bridge_or_session` is an attached `Bridge` or `(bridge, session_id)`. A player key is one of:

- an `int`: database PERSON index (`[PERSON+8]`);
- `('ordinal', n)`: position in the native all_actual PLAYER vector (global `0x56d2e18`, the Player Search base source);
- `('address', primary)`: a PLAYER or PLAYER_STAFF primary address;
- a `player_ref` string from any reader tool. These go through the tool's own resolver unchanged.

`on_progress(done, total)` runs after each player. `bind_player_refs` publishes ordinary `player_ref`s for the first three key kinds and `random_ordinals` draws a seeded sample of the all_actual vector.

Extra `unavailable` reasons for keys the tool cannot receive: `not_a_player_record` (the PERSON is staff, an official or a null vector slot), `key_outside_native_vector`, and `identity_rejected` with `detail` (the canonical identity checks failed for that one player). A `player_ref` that fails its checks still rejects the call, as in the tool.

## How it works

Once per call:

- a private journalled bridge restricted to `probe`, `images` and `read-bytes`, with the kernel process-incarnation token checked around every native port;
- the world, save, coach, HUMAN and club context;
- the forbidden interval of every primary record's attribute block (`primary+0x148..0x18d`, 66,048 records on the live save), bound before any player is resolved;
- one shared world read for all sources;
- three indexes over HUMAN-owned vectors, built lazily with the approved source's own readers: the sorted report vector (`HUMAN+0x110`), the alternate raw-UID report vector (`HUMAN+0x128`, reverse order) and the HUMAN's FOW owner record nodes. Each lookup returns or raises exactly what the tool's per-subject scan returns or raises.

Once per player, the approved typed source (the tool's overlay composition: used-range, CLUB INFO, relation fixes and the structural offer operand) computes the field-independent inputs in the tool's order: upstream PERSON_UI report, own-club candidate and auxiliary association, category byte (`primary+0x268`), reciprocal FOW node score, contextual K, the report byte (`row+0x3f`), and, only when some field reaches H 1, the range inputs (native age, assessor judging bytes).

Once per field, `field_state` applies the field's thresholds for that category (`knowledge_attribute_thresholds`) and `cell_value` applies the native range projection (`knowledge_passing_range`). Both are pure functions.

### Firewall

`BulkJournal` keeps the tool's rules:

- every attribute byte is forbidden; a read that touches one raises and poisons the journal for good;
- a byte opens only as an exact one-byte region, after `authorize_cell` recomputed that cell's H from the knowledge record the approved source registered with the journal (a private copy) and found it 1 or 2;
- any journal error rejects the call with no partial result.

What changed against the tool:

- the per-cell world rechecks are gone; inside the call, `lifetime()` and `verify()` reduce to the kernel incarnation check. The tool's journal serves every repeated read from its first read, so those rechecks could never see a change;
- the call ends with one context check (save, date, coach, world identity, process, plugin), a byte-for-byte check of every overlapping read shape, and one physical fence that re-reads every consumed region. Regions sharing a 4 KiB page are re-read with one read when that span touches no attribute byte; granted attribute bytes are re-read on their own;
- journal budgets: 8 million regions, 1 GiB consumed, 60 million physical reads.

A game that advances during the call (for example the day changes) fails the fence and rejects the call. That happened once on the live save while the day moved from 9 to 10 December 2030.

## Profile of the tool path

cProfile of one existing capture, fixed 28 all_actual ordinals x 47 fields, 9 December 2030: 289.8 s profiled for 1,316 cells (about 171 s unprofiled). Cumulative times overlap.

| Cost | Seconds | Where |
| --- | --- | --- |
| Contextual K | 149.3 | 2,336 evaluations: 1,316 for H plus 1,020 again for the getter grant |
| World read rechecks | 164.5 | 118,393 `ReadSet.verify` calls re-reading through the journal; most of K's time |
| Getter-grant H recomputation | 87.5 | `Journal.authorize` reruns the whole H per granted cell |
| Report selection | 51.2 | 2,336 scans of the 3,193-row report vector |
| Native ports | 43.6 | 1,036 helper processes, one per cell stream, about 41 ms each (fork 9.5 s) |
| Source lifetime callbacks | 9.9 | 17,856 world/coach re-reads |
| Source construction | 4.0 | world, coach and native guards per cell |
| Two final fences | 1.2 | 34,716 warm reads, about 33 us each |
| Setup | 0.5 | context, forbidden intervals (0.42 s), subjects |
| H thresholds, getter, range projection | 0.05 | |

On the managed squad (29 x 47, all own-club, 163.4 s profiled) K never runs; report selection (62.4 s), port launches (about 52 s), world rechecks (40 s) and the grant recomputation (31 s) take the time.

## Engines

`knowledge_bulk._run(..., engine=)` runs the same typed sources two ways. Every public function uses `'paged'`.

| Engine | Transport | Per player | Use |
| --- | --- | --- | --- |
| `'journal'` | one `fm_live_helper read-stream` round trip per region | a new source per player | the first bulk engine; kept as the comparison path |
| `'paged'` | 16 KiB pages read in batches by `fm_fast_reader` (`knowledge_inputs.PageSource`) | a copy of one prototype source, shared checks (`knowledge_fast`) | default |

### Paged transport and the firewall

`PagedJournal` subclasses `BulkJournal`. The forbidden-interval check, the grant rule and the poison rule are the same code. The transport differs: a region is a slice of a page held once for the whole call, so pages that hold attribute bytes are in the reader's cache, as they already were for the native-operand VM and the star VM. The engine obtains bytes only through `journal.read`, and `journal.read` refuses any forbidden byte without a grant. `tests/test_knowledge_inputs.py::test_firewall_holds_on_the_page_transport` covers the refusal, the exact granted byte and the wider read that would cover a forbidden byte.

The call ends with one context check and one fence: every page a read was served from is read again in one batch, and each consumed region on a changed page is compared with its first bytes. Two read shapes over one byte cannot disagree, because both are slices of the same page copy. A missing page is fetched with the next three (`READAHEAD`); those extra pages join the fence only when a read uses them.

Per process incarnation the engine keeps the helper's loaded-image answer, the plugin's hashed identity (revalidated by file stamp) and the sorted forbidden geometry (revalidated by the bytes of the primary vectors). Inside a call the kernel incarnation token stands for the `ps` check.

### Sharing inside one call (`knowledge_fast`)

The journal serves a region's first bytes to every later read, so a function of its arguments and of memory returns the same value each time it runs in the call. `journal.memo(key, compute)` uses that:

- One source is constructed in full. Each later player is a copy that runs only the subject-specific constructor steps (resolve the PERSON, compare the identity, build the subject, check its getter route), in the constructor's order. Until one construction succeeds, every player is constructed in full.
- Canonical record checks (`entity`, `team`, `contract`, `transfer._Reader.entity/person/team/contract/parent/current_team`, database table headers), the owner's club, teams and contract, club-relation operands, `club_relation` and `parent` of the K composition, pinned-code guards, the manager's offer vector, and the emulated fixture helpers run once per distinct argument.
- The getter's per-player checks run once per player, not once per granted cell.
- `ReadSet.verify` returns at once under a journalled source, and the process identity is checked again only after memory was read.

A memo caches a refusal like a value and raises it again for the next user. Nothing here changes a result: `engine='journal'` runs the same sources without `knowledge_fast`.

## Inputs, fingerprints and incremental calls

Every read is appended to the collector of the player being evaluated. A memo records its own inputs once and attaches them to each user, so a skipped read still counts as that user's input. After the fence, `Fingerprints` turns each player's inputs into:

| Part | Content |
| --- | --- |
| `spans`, `digest` | the merged byte ranges the evaluation consumed (code of the game binary left out) and a blake2b digest of their bytes |
| `groups` | outcome groups the evaluation used, as `[key, outcome digest]` |
| `facts` | derived facts, as `[kind, args, outcome]` |

An outcome group is a memo whose users depend on its outcome only, not on its bytes: a lookup in the HUMAN report vector (`report_rows`, `alternate_report`), membership of the FOW owner vector (`owner_node`), the three indexes those lookups read, CLUB INFO recent nodes (`recent_nodes`), the emulated `next_fixture` and `game_team98`, and the club score of one (club, nation, player) (`club_score`: each lookup walks a search path through the owner club's score store, which the game re-sorts and rescores as scouting goes on). A new scout report moves every row of the sorted report vector; with groups, only the players whose own lookup changed are evaluated again. Regions that at least 20% of a call's players consumed go into one `common` group per call.

`_run(..., plan=Plan(context, players, groups))` hands stored fingerprints back. The call verifies them before evaluating: a player is kept when its digest matches, every group it used still has the recorded outcome (a group whose bytes changed is recomputed through the engine and compared), and every fact recomputes to the recorded outcome. The others are evaluated. Everything the verification compared is covered by the same final fence. `raw['inputs']` returns the context, the kept PERSON indices and the new fingerprints.

The argument for keeping a row: an evaluation is a deterministic function of the bytes it reads through the journal. Its first read address is fixed by the call's context; each later address follows from bytes already read. If every consumed range holds the same bytes, every group returns the same outcome and every fact holds, a new evaluation reads the same bytes and returns the same row.

A fingerprint is relative to a context: process incarnation, plugin, save, world identity, coach, team, HUMAN and the people table's start, root and header. The people table may grow: a fingerprinted evaluation passed every `index < count` check it made, growth keeps those true, and the table's end pointer is left out of the byte ranges. The two places where the count decides something else (a placeholder PERSON index beyond the table, the retained-person search) record the count as a `people_count` fact. A row with any failure (`failure`, `score_failure`, `range_failure`, `context_k_failure`, an `unavailable` cell) gets no fingerprint and is evaluated every time. Fingerprints hold addresses, so a new game process voids them all.

### Date-dependent inputs

The game date is not a raw input. These are the places that read it, and what each records:

| Place | Fact | Changes when |
| --- | --- | --- |
| national-team assignment expiry (`apply_auxiliary`, `_auxiliary_equal`, K at `national_b8`) | `date_le (year, day)` | the expiry date passes |
| CLUB INFO recent node, relation mask (`_recent_nodes`) | `date_since_gt (year, day, 20)` | a node becomes more than 20 days old |
| transfer change row (`_Reader.before_today`) | `date_lt (year, day)` | the row's date passes |
| age: K's youth test, the state-1 range projection, the club-score age frame (`_age_from_birth`, `native_age_from_birth`) | `age (birth)` → age | the player's birthday |
| trial-contract date contribution of K (`date_contribution`) | `date_raw` → the date | every day (own-club trial contracts only) |
| `next_fixture(team, 365)`, `game_team98` (emulated) | outcome groups | the helper returns another fixture or flag |

On frozen whole-save pages, 1,949 of 2,000 random players carry an `age` fact and one a `date_le` fact; the fixture helper is used by about 3% of scouted and 9% of other players. Moving only the date global by 1, 2, 3, 7, 30 and 90 days re-evaluates 2, 3, 8, 18, 105 and 308 of 1,500 players; a from-scratch evaluation changes 2, 3, 7, 17, 103 and 292 of them, and no kept row differs from it.

### Across real game days

Fingerprints taken on the frozen pages of 10 December 2030 were verified against the live game on 13 December, after three days of the owner's play (3,000 random players, 163 of them in the named population, load 35):

| | Players |
| --- | --- |
| kept from their fingerprint | 2,115 |
| evaluated again | 885 |
| of those, rows that differ from 10 December | 161 |
| kept rows that differ from a from-scratch evaluation on the live game | 0 |

Why the 881 fingerprinted players that were evaluated again were not kept: own consumed bytes changed 857, an `age` fact 20, a `people_count` fact 3, a `recent_nodes` outcome 1. Two earlier versions kept almost nobody, and the data showed why. First, two persons had been added, and the people table's end pointer was part of every fingerprint; the context rule above removed that. Second, 1,226 of 3,000 players shared the owner club's score-store rows through the common group and 1,641 through their own bytes; the `club_score` outcome group removed that (3,635 groups were recomputed in 1.5 s and kept their outcome). What still changes in a player's own bytes without changing the row was not broken down further; the reputation scalars at `primary+0x258` and `+0x25a` (consumed as values, compared against thresholds) and the transfer-offer index vector are the visible candidates. One game day was not measured on its own.

## Throughput of the paged engine

Frozen pages of the live save (10 December 2030, 9,103 pages, `scripts/knowledge_golden.py`), one process, CPU seconds of that process:

| Run | Reference tree `0f70115` | This tree |
| --- | --- | --- |
| Named population, 3,555 players, engine only | 40.0 s wall | 6.31 CPU s (1.77 ms per player) |
| Other 62,488 players, engine only | 480.8 s wall | 143.05 CPU s (2.29 ms per player) |
| Whole store: engine, SQLite, stars and Player Search for 3,555 | 432.7 CPU s (522.5 s wall, load 81) | 206.3 CPU s (285.4 s wall, load 18), fingerprints included |
| 600 players again, nothing changed | 2.2 CPU s | 0.27 CPU s (600 kept) |
| 600 players after the date moved one day | 2.2 CPU s | 0.29 CPU s (1 evaluated) |

On frozen pages the reference pays no helper round trips, so its numbers are the cost of its Python evaluation alone. Live, the reference engine costs 24 ms of CPU per player (300 players in 9.2 to 9.4 s wall at load 16 to 24, helper process included); the paged engine cost 12 ms before the sharing work and 2.8 ms after it, measured at load 80 with SQLite writes and fingerprints included (3,607 players, 10.1 CPU s, 14.8 s wall).

Profile of the paged engine before the sharing work (300 unscouted players, 2,090 logical reads per player): K operands 56% of the reads, source construction 19.5%, the getter 12.4%, report selection 4.4%, own-club candidate 3.5%. `ReadSet.verify` re-reads were 10.5% of all reads, canonical entity checks 14%, table headers 6%, pinned-code guards 7%. At scale the largest single cost was the structural operand: it indexed the manager's 2,860 offers once per player (7.4 s of 23.1 s profiled for 3,000 players).

## Throughput of the first engine (live, 9 and 10 December 2030)

| Run | Players x fields | Seconds | Setup / evaluate / fence | Cells per second |
| --- | --- | --- | --- | --- |
| Managed squad | 29 x 47 | 1.4 | 0.46 / 0.39 / 0.48 | 950 |
| Fixed 28 ordinals | 28 x 47 | 1.5 | 0.44 / 0.54 / 0.43 | 870 |
| Random save sample | 300 x 47 | 7.1 | 0.47 / 2.80 / 3.71 (fence before page coalescing) | 1,990 |
| Random save sample | 1,000 x 47 | 8.4 | 0.57 / 5.57 / 2.10 | 5,620 |
| Random save sample | 5,000 x 47 | 42.0 | 0.94 / 33.04 / 7.91 | 5,590 (274 MB peak RSS, 366,174 regions) |
| Known-population sample | 300 x 47 | 4.5 | 0.49 / 2.32 / 1.55 | 3,160 |
| Summary, random | 1,000 players | 14.6 | 0.96 / 11.40 / 2.14 | 68 players/s |
| Summary, known population | 3,555 players | 24.3 | 0.79 / 19.23 / 4.10 | 147 players/s |

The 1,000-player call consumed 115,887 distinct regions over 4 native ports and opened 24,343 attribute bytes, one per exact or range cell.

## Regression against the tool

Same game state, all 47 fields, cell dictionaries compared for equality (state, value, minimum, maximum, reason and detail):

| Players | Cells equal | Different |
| --- | --- | --- |
| Managed squad (29, all own-club exact) | 1,363 | 0 |
| Fixed 28 all_actual ordinals (as ordinals and as player_refs) | 1,316 | 0 |
| 25 random players, 13 with unavailable branches | 1,175 | 0 |
| 20 known players: 10 node-only, 4 node and report, 4 report-only, 2 own-club | 940 | 0 |

The fixed 28 give exact 120, range 900, unknown 296, the tool's verified totals. The summary's H score and CA/PA gate states equal original H (RVA `0x23871f0`) replayed on 8 December for all 28 (`evidence/knowledge-perceived-ability-20261110`), including the two players with a stored report.

Whole store, both trees on the same frozen pages (`scripts/knowledge_golden.py build`, then `diff`): `knowledge_player` 66,043 of 66,043 rows equal over 26 columns (stars and Player Search included; `computed_at` and `tier` are bookkeeping), `knowledge_attribute` 3,104,021 of 3,104,021, `knowledge_wide` 66,043 of 66,043, universe 66,043, seeds 3,555, fields 47. The paged engine also consumes the same regions as the first engine: 56,377 and 44,860 regions for two 300-player samples, with equal SHA-256 over addresses and bytes.

`tests/test_knowledge_bulk_live.py` repeats the first two comparisons when FM27 is attached (the bulk side now runs the paged engine); `tests/test_knowledge_bulk.py` tests the pure functions and the journal offline against `tests/fixtures/knowledge_bulk_fixed28.json` (knowledge inputs and visible cells; no exact values or getter bytes).

## Known population

Seeds on the live save (10 December 2030):

| Seed | Players |
| --- | --- |
| HUMAN's FOW owner record nodes (`FOG_OF_WAR_MANAGER+0x18[HUMAN+0x3e4]`) | 2,729 (all owned by this HUMAN) |
| Report vector `HUMAN+0x110` (placeholders resolved) | 3,193 |
| Alternate report vector `HUMAN+0x128` | 0 |
| Selected club's team rosters | 66 |
| Union | 3,555 |

Definitions over the union (knowledge summary, no attribute byte):

| Definition | Players |
| --- | --- |
| Reciprocal node present (node in the subject's `primary+0xc8` vector and in the owner record) | 2,729 |
| Report selected for H | 3,193 |
| Own-club H branch | 66 |
| At least one field at range or exact | 3,518 |
| At least one field exact | 3,028 |
| CA star gate (0x62) at least range / exact | 3,362 / 1,785 |
| H score unavailable (K source gap) | 37 |

Contextual K reaches players without a node or report (same nation, league, reputation, club relations). In a seeded random sample of 1,000 of the 66,048 all_actual players, 979 have at least one field at range or exact, 68 at least one exact, 676 a known CA star gate and 8 every field unknown; 47 have a node and 59 a report. "Known" therefore has three different sizes: about 3,555 players named by the manager's own nodes, reports and club; about 4,500 with an exact field (estimate); about 64,700 with any range (estimate). Only the first is enumerable without evaluating K per player. At 68 to 147 players per second, a K-only pass over all 66,048 takes 8 to 16 minutes.

Player Search admission is a different predicate: `same_club OR club_leaf(0xe58e5c) OR (search context AND FOW leaf)`, bypassed entirely by show-all. The original club leaf admitted 91 of 92 sampled subjects (`evidence/knowledge-perceived-ability-20261110`), so the searchable population is close to the whole database and does not follow H. See "Player Search admission" below for the emulated per-person decision.

## Unavailable branches

| Detail (`unavailable_source`) | 1,000 random | 5,000 random | 300 known-population |
| --- | --- | --- | --- |
| Required contextual K unavailable: Unproved transfer predicate contract type | 9 players | 30 | 1 |
| Required contextual K unavailable: Unproved owned CLUB node family | 4 | 40 | 2 |
| Required contextual K unavailable: Reached unproved 17bb4c0 selection; absence is not native null | 0 | 4 | 0 |

Each affects every field of the player whose thresholds are nonzero (the whole row here). Over the 3,555 known players the first two account for 17 and 20 players. About 1.5% of random players are unavailable; no other reason occurred.

### Native operands (`native=True`)

`visible_attributes_bulk(..., native=True)` and `player_knowledge_summary(..., native=True)` answer those three refusals with the game's own functions, run in the emulator (`fm_live_mcp/knowledge_native.py`). All three are refusals of two K operands, and K (`0x2386548`) calls each through one function:

| Operand | Original call in K | Refusals it answers |
| --- | --- | --- |
| `relation_mask` | `0x20EE608(HUMAN primary, subject primary)` at `0x238679C` | owned CLUB node family (`_recent_nodes`), `17bb4c0` selection (`_refuse_selection`), contract type inside it |
| `transfer_predicate` | `0xCBB9F8(subject COMMON, owner CLUB, 0, 0, 0, 0)` at `0x2386DB8`; COMMON = subject + [vtable - 0x20] | contract type |

Only a refusal whose message is exactly one of the three is answered; every other path, and every operand the Python source answers, is unchanged. The native layer sits outside the structural-offer extension, so that extension still runs, unchanged, on every Python-answered transfer predicate. The default is off, so default outputs are those of the tool.

Memory: the emulator faults whole pages through a separate fast reader (a refused read must not close the call's journalled stream), with every primary record's attribute block blanked; a read hook refuses the call if the code loads a blanked byte. A second hook records each byte range the code loads; after the call each range is read again through the journal, must equal the bytes the emulator used and is then covered by the final fence. Pages are refreshed before every native call. An emulator refusal keeps the row `unavailable` with the reason in `native_operands.refusals`.

Live, 10 December 2030, `player_knowledge_summary` (rows with an H score or own-club context):

| Set | Unavailable before | Unavailable after | Native calls (mask / predicate) | Emulator refusals | Previously available rows changed |
| --- | --- | --- | --- | --- | --- |
| 1,000 random | 13 (4 node family, 9 contract type) | 0 | 4 / 9 | 0 | 0 |
| 5,000 random | 74 (40, 4 `17bb4c0`, 30) | 0 | 44 / 30 | 0 | 0 |
| 3,555 known population | 37 (20, 17) | 0 | 20 / 20 | 0 | 0 |

The 74 formerly unavailable rows as cells: 3,478 `unavailable` before; 236 exact, 1,504 range, 1,738 unknown after (1,740 attribute bytes opened, one per exact or range cell, through the unchanged H grant).

Check of the native functions against the Python sources where those answered (`native='verify'` runs both and counts): 327 relation masks and 340 transfer predicates equal, none different, none refused (300 random players plus the 74).

The four replays through `knowledge_relation_fixes.replay_lazy` (`0xE02F00`, `0x148A068`, `0x17743B8`, `0x21EB7DC`) are unchanged.

## Player Search admission

`knowledge_native.search_admission(bridge_or_session, player_keys)` reproduces the per-person decision of the Player Search refresh `0x208B238` for the non-show-all branch. The decision is inline code (`0x208BBA4..0x208BFB4`); the glue follows it and every function it calls runs natively: the subject's current team (contract slot `0x90`, COMMON slots `0x230` / `0x3F8`), the same-club test (`[team+0x30]` equal to the viewer club admits, branch to `0x208BB94`), then the club leaf `0xE58E5C(viewer club, subject primary, 0)`. The FOW leaf (service `[0x56D2D08]` slot `0x348`) runs only with a non-null search context; that context is null on this save, so the result reports it as not reached.

Live: equal to all 92 evidence subjects (admitted, club leaf, same club); all 29 squad players admitted by the same-club branch (the branch the evidence could not reach); 1,986 of 2,000 random players admitted (about 17 ms per player).

## Stored fields for a vectorised version

A vectorised H/Range over a table snapshot needs the fields below. Code-integrity reads (SHA-256 guards over code, vtable slot routes, `[vtable-0x..]` displacements, RTTI names) are omitted; a snapshot taken from the same build needs them only once. `COMMON` is the PERSON common data at `primary+0x278` (PLAYER) or `primary+0x370` (PLAYER_STAFF); the HUMAN's is at `HUMAN+0x438`. PERSON is at `primary+0x388` / `+0x480` / `HUMAN+0x548`. DATE is packed u16 day word, u16 year.

### H, report selection and Range

| Record | Offset | Width | Use |
| --- | --- | --- | --- |
| PERSON | +0x8, +0xc, +0x10 | u32 x3 | index, UID, secondary; placeholder when `i32 +0xc == -1` (index at +0x8) |
| PLAYER primary | +0x148 + field offset (`knowledge_field_catalog`) | u8 | attribute byte, read only when H >= 1 |
| PLAYER primary | +0x268 | u8 | category (thresholds) |
| PLAYER primary | +0x270 | u8 | getter scale mode (bit 7: signed byte to 1..20) |
| PLAYER primary | +0xc8 | vector of node ptr (used length <= 4,096) | reciprocal FOW nodes |
| PLAYER primary | +0x120 | ptr | national TEAM assignment |
| PLAYER primary | +0x128 | ptr | stored TEAM |
| PLAYER primary | +0x258, +0x25a | i16 | reputation scalars (K) |
| COMMON | +0x38 | ptr | NATION (association) |
| COMMON | +0x58 | DATE | birth date (age band of Range) |
| COMMON | +0x68 | ptr to i32 vector | transfer offer indices |
| COMMON | +0x78 | ptr | main contract |
| COMMON | +0x80 | ptr; holder +0x0, +0x8, +0x10, +0x18 ptr | contract holder |
| COMMON | +0xd8 | ptr | stored context CLUB |
| COMMON | +0x102 | u16 | bit 0x80 forces K = 0 |
| CONTRACT (full, basic, loan, trial by vtable) | +0x8, +0x10, +0x18 | ptr | owner PERSON, TEAM, current TEAM |
| CONTRACT | +0x26, +0xc2 | u8 | acceptance |
| CONTRACT (trial) | +0x44 | DATE | expiry (K date contribution) |
| TEAM | +0x28, +0x2f | u8 | youth flag, national marker |
| TEAM | +0x30, +0x50, +0x80 | ptr | owner, competition, HUMAN of the selected team |
| National TEAM | +0xb8, +0xe2 | DATE, u8 | assignment expiry, active flag |
| CLUB | +0x18 | vector of TEAM ptr | first team |
| CLUB | +0x118 | vector of relation row ptr | parents and relations |
| CLUB | +0xb9, +0xba, +0x163 | u8 | association selector, special flag, no-parent bit 0x10 |
| CLUB | +0xd8 | ptr | NATION |
| Relation row | +0x0, +0x8 | ptr | first, second CLUB |
| Relation row | +0x15, +0x1c, +0x30 | u8, u32, u8 | flags, flags, kind |
| NATION | +0xc | u32 | UID (special nations 0x186, 0x16c) |
| NATION | +0x110, +0x118 | ptr | national team container |
| National team container | +0x170, +0x1ea | ptr, i16 | NATION, association scalar |
| HUMAN primary | +0x110 | vector of report row ptr, sorted by subject index | report selection |
| HUMAN primary | +0x128 | vector of report row ptr | alternate selection, reverse raw UID |
| HUMAN primary | +0x388 | ptr | personal data (scouting range, +0x1cc u8) |
| HUMAN primary | +0x3e4, +0x3fc, +0x422 | i32, u8, u8 | FOW ordinal, owner exclusion bit 16, fog gate bit 0 |
| HUMAN DATA | +0x78, +0x80 (then +0x10) | ptr | main and secondary contract |
| Report row | +0x0, +0x8, +0x3f | ptr, ptr, i8 | subject PERSON, assessor PERSON, score |
| Assessor | PERSON-0x98 | ptr | main contract (eligible club) |
| Assessor NON_PLAYER | +0x2c, +0x2d | u8 x2 | judging bytes (Range width) |
| FOW manager (global `0x56a8430`) | +0x18 | vector of owner record ptr | owner record by HUMAN+0x3e4 |
| FOW owner record | +0x0, +0x18 | vector of node ptr, ptr | owned nodes, owner PERSON |
| FOW node (12 bytes) | +0x0, +0x4, +0x8 | u32, u32, i8 | subject index, owner UID, score |
| Globals | `0x56d4980`, `0x56d4981`, `0x56d4993`, `0x56d34e0`, `0x56d498a`, `0x56d498b`, `0x56d4951` | u8 | FOW enabled/bypass, secondary-team mode, fog-all flags, age mode |
| Globals | `0x56d3518`, `0x52efdf0`, `0x56b1db8`, `0x56b3390`, `0x56d57d0` (+0x184) | u32, DATE, DATE, u16, ptr (DATE) | club mode, age date, current date, fallback year, game rules |

### Lower K dependencies

| Operand | Module | Additional records |
| --- | --- | --- |
| `transfer_predicate` | `knowledge_transfer_predicate` | PLAYER +0xe0 change row (+0x0 DATE, +0x10 club UID); CONTRACT +0x28, +0xc0, +0xf7; TEAM +0x58, +0x60; COMPETITION +0xc, +0x60, +0xf9; container +0x56e; transfer manager (global `0x56a49f8`/`0x56a67f0`) +0x20 offer vector; offer +0x30, +0x38, +0x40, +0x50, +0x85, +0x8d, +0x8e, +0x90 (16-byte trade rows); people and clubs table roots (+0x64, +0x68, +0x90, +0xa8) |
| structural offer operand | `knowledge_structural_operand` | manager-owned offer +0x8 (u32) when visited, offer class by vtable |
| `club_score` | `knowledge_club_score_source` | CLUB +0x100 score store (+0x38 retained rows: +0x0 key, +0x24 u8); COMPETITION +0xb0 payload (+0x138, +0x4c, +0x4c0, +0x510, +0x388 then +0x23c, +0x3b6, +0x3be); NATION +0x100 region; container +0xc, +0xf0, +0x108, +0x120 (16-byte rows); shortlist manager (global `0x56a4be0`) +0x650; region-to-continent table `0x53b0998` |
| `club_aggregate` | `knowledge_club_aggregate` | NON_PLAYER +0xb0 retained rows (+0x0 key, +0x24 i8); CONTRACT +0xa0; owner +0x78, +0x90 pools; national containers table root +0x62 |
| `range_helper` | `knowledge_scouting_range_source` | CLUB +0x161, +0xc; NATION +0xf8, +0x100; COMPETITION +0xb0 then +0x7c8, +0x1aa; globals `0x56d496e`, `0x56d2ce8` |
| relation mask fanouts | `knowledge_relation_mask_source`, `knowledge_person_selector`, `knowledge_club_info_overlay`, `knowledge_retained_person` | CLUB +0xb0 CLUB INFO nodes (+0x38 TEAM, +0x48, +0x4c UIDs, +0x50 DATE) and retained nodes (+0x0 i32, +0x4, +0x5, +0x9 u8); teams table root +0x8, +0x64, +0x90, +0xa8; TEAM +0xc, +0x10 |

Four operands replay original ARM64 code in a Unicorn VM (`knowledge_relation_fixes`) and read whatever that code reads: special-country club `0xe02f00(CLUB)`, association fallback `0x148a068(PERSON, 1)`, next fixture `0x17743b8(TEAM, days)` and game team `0x21eb7dc(service, TEAM, TEAM, fixture)`. A snapshot cannot list their inputs in advance. A vectorised version should take their outputs per (person) and per (team, team) pair from a live pass, or refuse those branches.

## Not verified

- Other managers, clubs or saves; the oracle replay still covers one coach, club and date (the code path is the same).
- Concurrent game progress: a day change during a long call rejects it; `knowledge_store` retries.
- Star and Player Search columns have no fingerprint. They are recomputed for the rows that read them in each epoch.
- The memoised functions were checked by the whole-store diff and by mutation runs on frozen pages, not by a proof per function. `engine='journal'` remains the reference.
- The context-only population sizes are estimates from a 1,000-player sample, not a full K pass.
- Star values are computed separately by `knowledge_stars` (`docs/knowledge-stars.md`); the summary's CA/PA fields here are only the H gates. The Player Search refresh loop itself, its show-all flag and a non-null search context (FOW leaf) are not emulated.
- `native=True` is checked on one save and date; no emulator refusal occurred, so the refusal path is tested offline only.
