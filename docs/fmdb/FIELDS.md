# Editor fields without a getter value: where each one lives

FM27 27.0.0.2493426, Newcastle career, 10 December 2030. Module `fm_live_mcp/fmdb/fieldroutes.py`,
data `fm_live_mcp/fmdb/data/fieldroutes.json.gz`, generator `scripts/fmdb_field_routes.py`.

## Round 2: every record asked (editor2 lane, 12 November 2026, game date 13 December 2030)

Module `fm_live_mcp/fmdb/editor_live.py`, data `fm_live_mcp/fmdb/data/editor_live.json.gz`, scanner
`scripts/fmdb_editor_scan.py`. The ledger of 13 December counted 1,304 editor rows that did not read: 765
unset on the 25 sampled records, 499 unreached, 40 unavailable. The scanner asks every record of the type,
the managed club and squad first, through `Engine.get_property` (record getter, then the game layer) and
stops a field after three values. A field routed by `fieldroutes.ROUTES` is asked through its route.
1,244 scan rows over 28 record types; 1,126 CPU-s in one process at `nice 10`, load average 4 to 29
(people: 170,501 records, 589 CPU-s; clubs: 28,022, 294 CPU-s; teams: 66,021, 25 CPU-s).

`editor_live.decide(key)` turns a scan row into a ledger status, and `ledger.build_editor` lays it over every
row the census left without a value:

| status | meaning |
| --- | --- |
| `reads` | some record of this save gives a value; the reason names an example record (table index, unique id) |
| `empty_in_save` | new ledger status: every record was asked, the getter claims the key on some, none holds a value |
| `unreached` | every record was asked and none claims the key; the `fieldroutes` proof is appended |

Re-running the 3,133 editor rows of the shipped ledger through the overlay (`ledger._editor_live`) gives
reads 1,829 -> 2,064, empty in this save 0 -> 696, unset on samples 765 -> 0, unavailable 40 -> 0,
unreached 499 -> 373. Moves: 125 unset -> reads, 640 unset -> empty, 70 unreached -> reads, 56 unreached ->
empty, 40 unavailable -> reads.

What now reads, with an example the owner can check:

* **Role tables** `play.PATL` (All Attributes) and `play.PWEI` (Weightings) and their 37 item fields. The
  census called them unavailable (null pointer, instruction budget) under PropertyVM; FastVM through the
  engine reads them on all 841 players asked, Anthony Gordon included (Crossing 78).
* **Contract clauses and MLS fields** on people: relegation, non-promotion and minimum-fee release clauses,
  one-year extensions, squad status, international cap bonus, MLS rights and draft fields, other nation caps
  (`Ponc`). Ernest Muçi: relegation release clause 9,027,270; Souleymane Basse: minimum fee release clause
  (foreign clubs) 170,192.
* **Club and competition lists**: stadium changes `Cstc` (17 clubs, KV Kortrijk moves on 30 June 2031),
  alternative stadiums `Calt`, supporter bans `Cspb` (33 clubs), league table names, new clubs;
  competition registered teams `crgt` (33), secondary-division teams, VAR and goal-line technology stages,
  alternative division levels; stadium capacity changes `Scpc`. Counts in brackets are complete counts;
  the other fields stopped after three values.
* **Nation transfer windows** `nati.cwsd`/`cwed`/`nwsd`/`nwed` (below).
* **Team budgets** `team.Ctbu`/`Crmb`: the club columns, through `team.club_idx`.
* **Editor types that are not table records**: `recs` (21 rows, one per table type) and `lsts` (19) are the
  live `DATABASE_TABLE` singletons, enumerated with their counts; `ktfl` kit records (11 of 12 fields) are the
  items of the colours lists `Tko1`..`Tkg3` (53,255 kit items of 3,000 clubs and 502 national teams carry them; `kite` is the
  editor's kit preview widget and no item carries it).
* **Stadium stand flags** `stad.Shts`..`Shtl` (inferred mapping). No getter or setter handles them: the only
  site of each FourCC is the STADIUM property-name list (vtable slot 5, 0x16C7B4C). The stadium sides are the
  `Ssds` list, whose `indx` enum runs Top, Top Right, Right, Bottom Right, Bottom, Bottom Left, Left, Top
  Left, the order and names of the eight flags; "Has <side> Stand" is that side's `exis`. St James' Park:
  top, right, bottom and left stands exist, the four corners do not.

### Nation transfer windows: the in-game editor's getter

No record getter claims `cwsd`, `cwed`, `nwsd`, `nwed`. The `EDITOR` class getter 0x6710F0 does: arguments
x2 record, w3 key, x4 out value, and a stack flag that must be 1; it accepts a record whose vtable slot 8
returns 9 (NATIONAL_TEAM_CONTAINER) or 3, and computes the windows from the game date and the nation's
competitions (0x429B288). `editor_live.nation_transfer_window` emulates it on the nation's men's container
(`natc.NTCn` = the nation, `PLgn` 0) with the budget raised to 80 M instructions (big nations run 5 to 25 M,
0.1 to 0.3 CPU-s). `extras.DERIVED['nati']` holds four derived fields and `fieldroutes.ROUTES` routes the
four editor codes to them, so the snapshot columns `nation.current_transfer_window_start_date` ...
`next_transfer_window_end_date` compute on demand. Through `fm_db_query` on 13 December 2030: England next
window 1 January to 3 February 2031, Spain 31 December to 30 January, Brazil 3 January to 28 February,
United States 16 December 2030 to 15 September 2031; Ireland is the one nation with a window open now
(1 December 2030 to 22 February 2031).

### What stays unreached, and why

* 198 legacy responsibility rows `RPnn`/`RJnn` (club, natc): new `fieldroutes` category `superseded`. No
  view of `editor.fmf` lists them (club ui.xml and national team container ui.xml show `TCrs`), the FourCCs
  are never immediates in `__text`, and no lone `RP`/`RJ` high half is built. The live responsibilities are
  `TCrs` (items `PUnI`, `PUnT`, `PUnP`, `PUnJ`), which reads.
* `NDBC`/`FDBC` change counters (36 rows, 18 types), `DBvw`, `EFBR`, rule-editor fields and the competition editor
  buttons (`CtRq`, `ChLf`, `ChCf`, `Cgcc`, `AdHR`, `Ctoa`, `Ctua`: type button, editor actions with no
  stored value): full scan shows no record claims them; category as in round 1.
* `natc` record history (`CMA*`, `CMG*`, `CHG*`, `CGL*`, `CHF*`, `CHR*`, 30 fields) and national-team editor
  dates `ED*`: no national team container claims them. The national team records the game shows live in
  the records screen's own history; next route: that UI handler or the saved history readers.
* `fmat` (34 rows), `dbch` (4), `alnm` (4), `prnm` (9): editor file metadata, change logs and name
  records. The EDITOR getter 0x662A1C handles `orvs`, `svvs`, `file`, `dbch`, `dbls`, `DBrf`; it was not
  emulated (it reads the editor's open database file, which a career does not hold). Person names live
  in the three name tables at database root +0xC8/+0xD0/+0xD8: a person's first, second and common name
  handles (+0x298/+0x2A0/+0x2A8 of the player) point at 24-byte entries {string pointer, u32 index, u16 nation
  table index, u16 count, u16 local region (0xFFFF none), u8, u8, u32}; the nation index matches each
  sampled player's nation (139 England, 189 Brazil, 162 Portugal, 163 Ireland). The other bytes have no
  proven meaning, so `prnm` stays unread; next route: emulate the newgen name picker that reads them.
* `club.CMWE`, `club.Csry`, `team.Clri`: STARTING_* tables only (round 1); `club.Cnod`, `club.Crkt`,
  `team.Crkt`, `club.CNse`: set_property or the database loader only.

## Round 1

The coverage run (`COVERAGE.md`, 25 records per type) left 998 (record type, field) pairs without a
value: 505 the record getter did not claim, 477 unset on every sampled record, 12 unavailable, and 4
more that the snapshot marked unavailable although the coverage run had a value. Each pair now has
a category, a reason and its evidence. `fieldroutes.reason(record_type, code)` returns the one-line
reason; the snapshot writes it into `_column_state.note` for every column it leaves unavailable.

## How each pair was classified

1. **Census.** The same pairs asked of 300 to 430 records per type (the managed club and squad
   first, then records spread across each table), through the VM with the game-layer fallback.
   A value on any record makes the pair `sampling`.
2. **Static evidence.** Every FourCC built in the plugin's `__text` with `movz/movk`, a lone
   `movz #imm, lsl #16`, or `add/sub #imm` from such a constant (`fourcc_sites`; the compiler builds
   `Cnam` as `Cnag + 6`). Sites are mapped to functions (`LC_FUNCTION_STARTS`) and functions to
   roles by the vtable slots that point at them (5,830 vtables, slots read from the live game):
   slot 3 of a `db::` class is its property getter, slot 2 `set_property`, slot 5 its property
   list, slot 3 of `db::STARTING_*` an editor start-table getter, slots 8+ of the 15 interceptor
   classes the game layer, class `EDITOR` the in-game editor. `getter_closure` follows `bl`/`b`
   from the record type's own class getters and its game-layer classes (depth 2).
3. **Start tables.** Every `db::DATABASE_TABLE<db::STARTING_*>` singleton in the plugin's
   globals was counted live: all 32 have 0 records. The game consumes them when a career starts.

## Results

| coverage outcome | category | pairs |
| --- | --- | ---: |
| not claimed (505) | `constructed_key` | 236 |
| | `starting_table` | 81 |
| | `editor_only` | 62 |
| | `claimed_unset` (compared, guarded) | 54 |
| | `sampling` | 53 |
| | `setter_only` | 13 |
| | `live_route` | 5 |
| | `other_record` | 1 |
| unset (477) | `claimed_unset` | 410 |
| | `sampling` | 48 |
| | `other_record` | 15 |
| | `emulator` | 3 |
| | `editor_only` | 1 |
| unavailable (12) | `sampling` | 9 |
| | `emulator` | 2 |
| | `claimed_unset` | 1 |
| snapshot only (4) | `emulator` | 3 |
| | `sampling` | 1 |

### Live routes (the field belongs to another key or object)

* `club.Ctbu` transfer budget, `club.Crmb` remaining wage budget, `club.CMWE` maximum wage and
  `club.Csry` stadium rent are answered only by the editor table STARTING_CLUB_DEBT: the CLUB getter
  0xE476C4 looks the club up in that table (0xE4B260) and tail-calls its getter 0x16E9CC8. The live
  values sit under other keys: transfer budget `Ctfc` (catalog "Transfer Budget", game layer),
  remaining wage budget `Cwrb` (weekly, game layer). The snapshot's `club.transfer_budget` and
  `club.remaining_player_wage_budget` now ask those keys (`_fields.code` keeps the editor code, the
  note says which key answered).
* `club.CcfE` corporate facilities: the CLUB getter itself rewrites CcfE to `Ccfa` (0xE53D00) and
  answers `Ccfa`; `club.corporate_facilities` asks `Ccfa`.
* `club.CSbR` scouting budget: the game layer answers it for clubs with a full CLUB_FINANCE object;
  the 12-record plan sample had none, so the snapshot had marked the column unavailable. It is now
  emulated, as is every pair in the `sampling` category whose plan said "getter does not handle".
* `team.Ctbu`, `team.Crmb`: the TEAM getter never claims them; read the club columns through
  `team.club_idx`.
* `CntF.*` (10) and `pers.PF*` / `pers.PL*` (68): STARTING_FUTURE_TRANSFER (getter 0x16F02BC),
  STARTING_LOAN (0x16F8764) and STARTING_PAST_TRANSFER (0x1709344) fields. The live contracts and
  loans are the CONTRACT / FULL_CONTRACT / LOAN_CONTRACT records the collections lane reads
  (`sources/contracts.py`: `contract`, `contract_clause`).
* `team.Clri`: STARTING_RESERVE_TEAM (0x1712C40) only.

### Sampling (unset or not claimed only because the sample missed them)

Census values for 111 pairs, for example: fourth-team fields `C4*` (4 of 301 clubs have a fourth
team), staff tendencies `NT01`-`NT98` (1 to 21 of 429 staff), `Ncra`/`Npta`/`Ncrr`/`Nhmr`/`Nwrr`
(268 of 429 staff), player role tables `PATL`, `PWEI`, `PRLS`, `ORLS`, `BR01`-`BR09` (about 290 of
429 players; `PRSS` hits the instruction budget on 263), personality `Pada`...`Ptem` (every person
since the interceptor bypass), next-move fields `Pnaj`/`Pnsd`/`Pnex`/`Pnww` (5 of 429), club
`Cncl`/`Calt`/`Cbbl`/`Csoc`/`Cren`/`Cnec`, competition `VARm`/`otms`/`nsod`/`AdLe`, region names.

### No live counterpart, with the evidence

* `constructed_key` (236): the FourCC is not an immediate anywhere in `__text`. 198 are the staff
  responsibility rows `RPnn` (person) / `RJnn` (expected job) of clubs and national team
  containers: the editor builds the key from the row index; the live rows are read by the hand-built
  `club_staff_responsibilities.py` (club +0xB0 -> +0x48 vector). The other 38: national-team editor
  dates `ED*` (10), `DBvw`/`EFBR` view helpers, competition rule-editor fields (`CRMS`, `HsAR`,
  `NoBR`, `PSFN`, `SGRF`), nation city counts `NCTB`/`NCTC`, derby team-1 totals `D1t*`, `PPPA`,
  `Cedp`, `Shcc` and eight person keys (`GOcs`, `MYpc`, `PeBi`, `Phbn`, `ReAR`, `TSHR`, `Tdpd`, `Tdph`).
* `editor_only` (63): `NDBC`/`FDBC` (database-change counters) on every type appear only in five
  change-log functions no getter reaches; competition and nation advanced-rule fields (`AXML`,
  `AdHR`, `Cgcc`, `ChCf`, `ChLf`, `CtRq`, `Ctoa`, `Ctua`, transfer-window dates `cwsd`/`cwed`/
  `nwsd`/`nwed`, `Elsd`/`Eled`/`Elex`) live in the `EDITOR` class (slots 22 and 42).
* `setter_only` (13): `CNse`, `Cnod`, `Crkt` and stadium stand flags `Sh**` are compared only by
  `set_property` (CLUB slot 2 0xE374E8, STADIUM slot 5 0x16C7B4C) or the club database-file loader
  0xDEAEC8 (`CssT`/`CssP`/`CssS`/`CssE` are also there; the CLUB getter compares them but never claims
  them for any of 301 clubs).
* `claimed_unset` (465): the record's getter chain compares the key. 411 returned an empty value for
  every census record (club and competition history records `CBW*`, `CBD*`, `CHS*`, `CMA*`, `CGM*`
  ... are empty in this save: the live records screen keeps its own history), 54 were compared but
  never claimed (a guarded branch: the national-team copies of the club history keys, staff
  preference keys `NpBs`/`NpBe`/`Nsbc`/`Nsfc`).
* `emulator` (8): competition team lists `CNTM`, `CTMS`, `cntm`, `rgts` exceed the instruction
  budget; person histories `Plhs`/`Pnhs`/`Pnph` call `gettimeofday` on 329 of 429 people;
  `PGRP` exceeds the budget. These depend on the "virtual" lane's work on clocks and budgets.

## Snapshot columns that stay unavailable

The real snapshot of 11 November had 344 unavailable columns. After this lane, 4 club columns read
values (transfer budget, remaining wage budget, corporate facilities, scouting budget) and every
other unavailable column carries its category and reason: 227 `constructed_key` (200 responsibility
rows), 42 `editor_only`, 38 `claimed_unset`, 12 `setter_only`, 11 `sampling` (the plan sample said
"unavailable": emulated on demand through `fm_db_read`), 5 `emulator`, 3 `starting_table`,
2 `live_route` (team budgets, read through the club) and 1 `other_record`.

`club_view.maximum_wage` stays NULL: CMWE has no live getter key. Next route: the finances UI
handler (UI keys `FinanceDebugMaximumWage` jWYJ, `AdvisedMaxBasicWage` gBHm).

## Club money for every club

Every club money and facility value is a `club` column. Direct plans (read eagerly by the build,
no getter call): balance `Ccba`, scouting package `CScP`, season ticket holders `Csth`, ticket
prices `Cmtp`/`Casp`, ownership type `Cown`, stop outside takeovers `Csot`, training `Ctlv`, youth
facilities `Cyfb`, youth coaching `Cytv`, youth recruitment `Crcb`. Computed on demand through the
getter: transfer budget (`Ctbu` routed to `Ctfc`), remaining wage budget (`Crmb` routed to `Cwrb`),
scouting budget `CSbR`, corporate facilities (`CcfE` routed to `Ccfa`), wage budget `Cwwb`, debts
`Cdbt`/`Cfln`/`Chdb`, instalments `Cmti`, other income `Coin`, wage contributions `Cwcl`.

`sources/club_finance.py` (table `club_finance`, lazy) adds what the `club` table lacks: the wage
bill (game-layer recomputed weekly `Ccwt`, stored annual `ClPa`), remaining wage budget `Cwrb`
weekly and per year, wage budget per year, the finance object's `Cntb` and the budget record
`Csba`. 721 of 28,022 clubs have a full CLUB_FINANCE and so budgets; 27,558 have a balance.

### Cost per cell and invalidation

FastVM, one process at `nice -n 10`, load average 145 to 185, 60 clubs with a full CLUB_FINANCE
and 200 without, 400 people; CPU microseconds per cell, first pass / second pass (warm pages, no
memo). The whole measurement used 3.9 CPU seconds.

| field | full finance | base finance | direct plan | invalidation |
| --- | ---: | ---: | --- | --- |
| balance `Ccba` | 440 / 15 | 57 / 25 | yes | game date |
| wage budget `Cwwb` | 49 / 33 | 101 / 95 | no: the getter branches on the finance class | game date |
| wage bill `Ccwt` | 4,749 / 820 | 129 / 70 | no: recomputed from contracts | game date |
| wage bill per year `ClPa` | 201 / 114 | 97 / 144 | no: game layer | game date |
| remaining wage budget `Cwrb` (route of `Crmb`) | 125 / 58 | 143 / 151 | no: budget less spending | game date |
| transfer budget `Ctfc` (route of `Ctbu`) | 182 / 110 | 93 / 133 | no: availability rules | game date |
| `Cntb` | 37 / 39 | 127 / 141 | no | game date |
| budget record `Csba` | 209 / 130 | 99 / 128 | no: record value | game date |
| scouting budget `CSbR` | 63 / 58 | 252 / 97 | no: game layer, human clubs only | game date |
| corporate facilities `Ccfa` (route of `CcfE`) | 41 / 38 | 32 / 36 | no: attribute blob | content |
| facilities, tickets, ownership (10 direct columns) | 21 to 61 | 30 to 159 | yes | content |
| fourth team name `C4nm` (sampling) | 1,458 / 337 | 189 / 106 | no | content |
| staff tendency `NT01` (sampling) | 497 / 207 (people) | | no | content |
| player role table `PATL` (sampling) | 1,092 / 1,070 (people) | | no: list | game date |

A `club_finance` row costs 0.6 to 0.9 ms CPU for a club without a full CLUB_FINANCE and 1.2 to
5.4 ms for one with it. Nothing in this lane adds eager build work: routed columns and the 111
`sampling` columns are written `pending` ("computed on demand (fieldroutes)") and never enter the
build's eager emulation; `club_finance` declares `mode='lazy'`, `invalidation='game_date'` when the
collections contract carries those fields, and its `rows(idxs)` computes only the given clubs.

Check (`scripts/fmdb_club_finance_check.py`, 50 clubs: the managed club, 44 more with a full
CLUB_FINANCE, 5 with a base finance object) against the hand-built `club_finance.decode` and
`financial_details.club_details` (source rows 0.8 s wall for 50 clubs): balance 50/50, weekly wage
budget 50/50, transfer budget 45/45,
remaining weekly wage budget 45/45, annual wage bill = stored weekly spending x 52 44/44, scouting
budget 1/1 (the only club either reader returns one for). `Ccwt` equals the stored weekly
spending on 36 of 44: it is the game layer's recomputed bill, the stored figure lags it.

Managed club against the finances screen: wage bill 258,727,924 per year (`ClPa`) of budget
284,229,244 (`Cwwb` 5,465,947 x 52), balance 26,390,569, remaining 490,410 per week = 25,501,320 per
year. Transfer budget 92,979,220; scouting budget 209,432; corporate facilities 15.

Clubs without a full CLUB_FINANCE (27,301 of 28,022) return -1 for `Cwrb` and `ClPa` and NULL for
the budgets: the game keeps no budget for them. The scouting budget is kept for the managed club
only (1 of 28,022).

Not found: maximum wage, data analysis facilities, takeover state beyond `Cown`/`Csot` (next route
for each: the finances, facilities and board UI handlers).

## Checks

* Differential (`scripts/fmdb_snapshot_check.py`, lane cache, 200 rows per table): 101,529 direct
  cells, 0 mismatches (unchanged: routes only touch emulated columns).
* Oracle (`scripts/fmdb_oracle.py`, load average 100 to 180): 31,251 match, 128 mismatch,
  224 generic-unavailable, 149 tool-unavailable over 129 players, 50 staff, 51 clubs, 50
  competitions, 50 stadiums, 50 cities, 173 currencies. The new pairing club remaining weekly wage
  budget against `Cwrb` matched on both clubs where the tool decodes it; the transfer and scouting
  budget pairings matched 51/51. Mismatches fell from 134 to 128; the generic-unavailable rise
  (82 to 224) is in player club names, currency names and injury fields, which this lane does not
  touch: it was not re-run at a quiet load.
* `tests/test_fmdb_fieldroutes.py`: 10 offline tests and one live test (12 clubs against the
  hand-built finance tools).

## Enum label sets

The 136 enum fields whose label sets are not in `editor.fmf` use 19 enum names. This lane did not
resolve a value -> label set it could verify. Findings:

* Formation names (`pfms`, `sfms`, `dfms`, `afms`, `foms`) are language ids 636403-636461, but
  those ids are not immediates in `__text`, not in any data section of the plugin and not in any
  `.fmf` data file: the mapping is built at run time from something else. Next route: find the UI
  formation-name function through the tactics UI handlers and emulate it over 0..58.
* Staff jobs (`mdbj`, `mdjz`, `mdnj`, `mdjc`, `mj+c`): `staff_jobs.py` holds the native job-title
  labels, but the editor's job fields (`PCJO` at person +0x24) are 0 for every live person, so the
  numbering cannot be checked against live values.
* `Phei` is a height in cm, `crrp` reputation ranges are declared without labels.

`fieldroutes.language_text(translation_id)` is the shared lookup of the English language table
(`example.ltf`, the template of `languages.fmf`) for the label ledger.
