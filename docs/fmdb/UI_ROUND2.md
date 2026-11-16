# UI round 2: front-end property keys

Build 27.0.0.2493426, Newcastle United career, game date 13 Dec 2030, read on 12 Nov 2026.
Everything runs shipped code on copied live memory (`UiHandlerVM` / `FastUiHandlerVM`);
nothing is written to the game. The first sweep is `UI_SWEEP.md`.

## Result

Front-end property keys (ledger denominator `ui`, 7,720 registry keys), from the first sweep to
round 2, computed with `ledger.build_ui` over `out/fmdb-ui-sweep/types/*.json` (150 first-pass
jobs, 150 `@r2` jobs, 53 `@r2x` jobs):

| Status | Before | After |
|---|---|---|
| reads | 2,387 | 4,463 |
| unset on every binding | 1,525 | 1,406 |
| needs a screen parameter | 186 | 119 |
| unavailable | 62 | 179 |
| unreached | 3,560 | 1,553 |

Moves: unreached to reads 1,642; unset to reads 356; needs parameter to reads 75; unavailable to
reads 3; unset to unavailable 116 (compiled out, below); unreached to unset 350 (the handler of
the key's record class was asked and returned nothing); unreached to needs parameter 8 and to
unavailable 7. Of the 2,076 new reads, 951 are direct reads of the key and 1,125 are fields of
records a handler returns. The second pass took about 9 minutes and the extra-key pass about
1.5 minutes at load average 8 to 15.

## 1. Keys unset under the first binding: more bindings

`scripts/fmdb_ui_sweep.py --round2` takes every first-pass job and re-reads the keys that did
not return a value:

* under every other profile that fits the handler (the first pass tried the others on 14 keys
  only), plus the manager as a person, the next opponent's team, each competition in the
  calendar 30 days either side, and for `PERSON_UI_HANDLER` the manager, the scouted player, a
  scout, eight more squad players and a squad player with the last fixture's fields;
* with screen parameters (section 2) for keys whose getter read one.

Bindings are in `out/fmdb-ui-sweep/bindings_r2.json`. What the extra bindings found: the manager
as a person gives 35 `Human*` keys (news portal, shortlists, inbox headlines, holiday return
date); other squad players give single keys (interested clubs, nationality eligibility,
languages); other competitions give 4 COMPETITION keys; the opponent gives 3 TEAM keys. Most of
the remaining unset PERSON, CLUB, TEAM and COMPETITION keys are list-row keys (milestones,
relationships, transfer rows, records), keys of a match in progress (minute subbed on, match
rating) or debug keys.

Values the getter itself labels as empty are counted as unset: the text "Failed to get data"
(`GAME_NO_DATA_TEXTS`; 3 first-pass keys still carry it as a value).

## 2. Screen parameters

`fm_live_mcp/fmdb/ui_params.py` names all 231 parameter globals (`plugin_params` in
`ui_frontend.json.gz`) and proposes values: object parameters take a binding's UI id (person,
human, team, club, competition, scout, news item), dates the game date, years the season,
flags 1 then 0, counts 10, 5, 20, 1, and other integers the literals the views set plus 0 to 5.
`assignments` varies one parameter at a time. The globals of the first sweep:

| Global | Name | Global | Name |
|---|---|---|---|
| 0x56D1248 | number | 0x56D1928 | teamselectionindex |
| 0x56D1688 | human | 0x56D1198 | date |
| 0x56D11F8 | gender | 0x56D18A8 | inpossession |
| 0x56D16C8 | person | 0x56D1648 | club |
| 0x56D16B8 | team | 0x56D13D8 | viewid |
| 0x56D1278 | ishometeam | 0x56D12E8 | positionmask |
| 0x56D1258 | id | 0x56D18E8 | rolemask |
| 0x56D1268 | index | 0x56D1D58 | monthindex |
| 0x56D1A28 | visionobjectiveyear | 0x56D1C38 / 0x56D1C48 | setpiecetype / setpiecescenario |

47 keys returned a value only with a parameter, for example TEAM_TRAINING
`TrainingBestRatings` / `TrainingWorstRatings` with `number` (that many players), PERSON
`SelectedPositionalAbilities` with `positionmask`, `PositionalStatsTable` with `boolean`,
`HumanTransferInOutList` with `viewid`, PERSON_SEARCH similar-player suggestions with
`numsimilartosuggestions`, FIXTURE `TeamIncidents` with `ishometeam`, GAME `ActiveRuleGroups`
with `gender`, TEAM `SelectedInPossessionFormationChances` with `formation`, SET_PIECE routine
lists with `setpiecetype` and `setpiecescenario`. The other 119 keys still read a parameter
whose value is not among the candidates; the next step for each is the view that binds the key
(`ui_frontend` views) and the value the view's parent passes.

`fm_ui_read` takes `params` ({name: integer}); with it every key is read through all client
protocols and each row lists the parameters its getter asked for (`params_read`).

## 3. Handler classes the sweep does not build (122 keys)

| Class | Keys | What builds it |
|---|---|---|
| SETUP_GAME_UI_HANDLER | 52 | constructor 0x493E6C, no direct caller: the new-game setup flow, which has no state in a loaded career |
| MATCH_STATS_UI_HANDLER | 27 | constructor 0x269F58, called from 0x292754 and 0x2929E4 (beside MATCH_TACTIC_UI_HANDLER_SERVER); needs a match in progress, which there was not (MATCH_TACTIC type 64 stops on a null input for the same reason) |
| FILTER_COMPARE_RULE_UI_HANDLER | 27 | no code reference to its vtable (0x54BA560): built by copy or from a data table; route: find the data reference to the vtable |
| ADD_USER_EDIT_SESSION_UI_HANDLER | 9 | constructor 0x49858, no direct caller (multiplayer add-user flow) |
| ACTION_BASED_SPEAK_TO and five other *_SPEAK_TO | 7 | constructors 0x38754 / 0x387B4, no direct caller: built by the speak-to action dispatch |

## 4. Keys no handler class claims (3,437 before)

The registry assigns a key to a class when the key is an immediate in that class's
get_property. 3,095 of the 3,437 unclaimed keys are properties of front-end record classes
(`FM.UI.<Name>Reference`, `ui_frontend` records; `PersonReference` alone has 566). get_property
dispatches through helper functions (key compare chains in functions such as 0x3C6640 and
0x3D60CC for PERSON) that the immediate scan does not attribute to the class, so the keys are
served by the same handler. Two routes, both now measured:

1. Ask the handler of the record class (`--round2-extra`, `unclaimed_keys_by_host`): name match
   (PersonReference to PERSON_UI_HANDLER), `RECORD_ALIASES` (CompReference to COMPETITION,
   CharacterSettingsReference to PERSON on the manager, ...), and six fallback hosts (PERSON,
   TEAM, CLUB, COMPETITION, GAME, APPLICATION) for keys whose record class has no buildable
   handler. Fallback hosts record values only. Values: PERSON 476 (career appearances,
   per-90 stats, injuries last season, positional abilities, international first goal date),
   CLUB 126, TEAM 84, NATIONAL_TEAM_CONTAINER 60, COMPETITION 41, GAME 20, CONTINENT 14,
   NATION 13, MATCH 5.
2. Fields of returned records: `note_nested` walks every value a key returns and records the
   registry FourCCs inside (a list of row records carries their properties). The ledger counts
   such a key as read, with the parent key in the reason.

The 1,431 keys still unreached are mostly properties of record classes whose handler is not
built (SetupGameReference, AddUserEditSessionReference, PrivacyPolicyReference, the Debug*
references) or rows that only exist in a match or a negotiation in progress. Of the 342
unclaimed keys outside every record class, 315 are bound by no view or table either (names the
front end registers without using them in a view).

## Compiled-out keys (116)

`fmdb_ui_sweep.py --compiled-out` scans the plugin text for `mov/movk wN, key; cmp; b.eq/b.ne`
cases and follows each to its target. 116 keys have every case end at the shared stub
0x8665C (`mov w0, #1; ret`) with no call and no store: the release build answers "handled" and
writes no value. Example: `DebugPersonName` ('adJf') at 0x37F290. The list is in
`fm_live_mcp/fmdb/data/ui_round2.json.gz`; the ledger marks those keys unavailable (only when
the sweep also read them as unset). The scan agrees with a capstone-based scan key for key.

## 5. Screens: `fm_get_ui_screen`

`fm_live_mcp/fmdb/ui_recipes_round2.py` (`SCREENS`, keys by registry label, parameters as the
views set them). First-call times; those marked * through the MCP stdio server (load average 7),
the others in process (load average 9 to 29):

| Screen | Handlers | Value / unset / unavailable | Time |
|---|---|---|---|
| player_comparison | PERSON x 2 | 40 / 0 / 0 | 2.1 s * |
| staff_comparison | TEAM | 5 / 2 / 0 | 0.8 s |
| tactics | TEAM (4 keys); the tactic itself from the hand-built readers, see below | 4 / 0 / 0 | 1.5 s |
| squad_registration | SQUAD_REGISTRATION_EDIT_SESSION 105, TEAM | 17 / 0 / 0 | 0.4 s * |
| training | TEAM_TRAINING 128, PLAYER_TRAINING 77 | 32 / 1 / 0 | 1.1 s |
| contract_negotiation | CONTRACT_EDIT_SESSION 20, CONTRACT 19 | 46 / 1 / 0 | 0.2 s |
| transfer_negotiation | TRANSFER_OFFER_EDIT_SESSION 137 | 50 / 19 / 0 | 0.1 s |
| competition_rules | COMPETITION | 16 / 6 / 0 | 0.2 s * |

Player comparison is two PERSON reads side by side: the plugin has no comparison getter for two
players (the PERSON comparison keys take a role mask, not a second person). Tactical familiarity
has no key in the registry under any label; role suitability per position is
`SelectedPositionalAbilities` with `positionmask`.

## 6. Speed: the free-list heads

Not changed in this round. The emulated code pops nodes from three game free lists with inlined
code; each site is `ldr xR, [head]; cbz xR, slow; ldr x9, [xR]; str x9, [head]`:

| Head | Pool | Pop sites (register) | Push sites |
|---|---|---|---|
| 0x56A4E90 (bag nodes) | 0x56A4DF8 | 0x43F8374 (x21), 0x43F70C4 (x21) | |
| 0x56A8AB0 (typed values) | 0x56A8A18 (element 0x18 bytes) | 0x4404690 (x22), 0x4409618 (x21), 0x4404494 (x22) | 0x44094DC |
| 0x56B13C0 (typed values) | 0x56B1328 | 0x44042E4 (x22), 0x43EA324 (x21) | 0x43EA1F0 |
| pool+0x98 | function 0x43569F8 (any pool) | 0x4356A10 (x20) | |

The fix: at each pop site set xR to a zeroed VM-heap block of the pool's element size (u32 at
pool+0x12C) and resume after the `str`; at each push site skip the two stores. Function 0x43569F8
can be intercepted at its entry like `pool_alloc`. The sites are hot, so the model belongs in the
C accelerator (`native/fm_vm_accel.c`, beside `ACT_POOL_ALLOC`), not in a Python code hook; this
touches `ui_vm.py`, `ui_fastvm.py` and the C file, which this lane does not own.

## Files

`fm_live_mcp/fmdb/ui_params.py`, `fm_live_mcp/fmdb/ui_recipes_round2.py`,
`fm_live_mcp/fmdb/data/ui_round2.json.gz`, `tests/test_fmdb_ui_round2.py`,
`tests/test_fmdb_ui_round2_live.py`. Additive edits: `scripts/fmdb_ui_sweep.py` (round-2,
extra-key and compiled-out passes, nested fields), `fm_live_mcp/fmdb/ledger.py` (`build_ui`
counts nested fields and compiled-out keys), `fm_live_mcp/fmdb/ui_tools.py` (`params` on
`fm_ui_read`, `fm_get_ui_screen`; 195 tools).

Reproduce: `PYTHONPATH=. python scripts/fmdb_ui_sweep.py --round2`, then `--round2-extra`, then
`--compiled-out`; the ledger reads `out/fmdb-ui-sweep/sweep.json`.

## The tactics screen does not use the tactic handler (12 November 2026)

The `tactics` screen first read 18 keys from a COMPETITION_TACTIC handler built from the managed
team's record. The keys answered, so the sweep counted them, but the handler was describing a
default tactic: on a live Newcastle save it said "4-4-2", Balanced, one slot, while the manager
had three prepared 4-2-3-1 tactics on Positive and a match in progress was using one of them.
pi-fm advised a mentality change the match already had.

`fm_get_ui_screen(screen="tactics")` now puts the manager's tactics in `fields.tactic` from the
hand-built readers: `prepared` (every stored slot with name, mentality, named team instructions
and both phases' positions and roles, from `fm_get_managed_tactics`) and `in_match` (the match
engine's current settings for the managed side while a match is loaded, from
`fm_get_current_match`; null otherwise). The TEAM part (formation chances, style name, heat map
list) is unchanged. A handler key answering is not evidence that it describes the manager's object;
the record the handler is built from decides that.
