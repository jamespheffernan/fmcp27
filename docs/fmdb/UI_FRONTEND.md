# The front end as the specification of every screen

Build 27.0.0.2493426 (GameAssembly.dylib, global-metadata.dat v39, the ui-* asset bundles).
Live save: Newcastle United, manager Cesar Jules, 10 Dec 2030.

The earlier sweep (`UI_SWEEP.md`) supplied plausible inputs. This lane reads what the front
end itself sends: the record schemas, the property each view binds, the parameters each
view sets and their values, and the tables that turn a value into the word on screen.

## Where the specification lives

The C# front end is generic. Screens are UXML views (VisualTreeAssets) in
`ui-visualtreeassets_*.bundle`; each view names the properties it binds
(`clubvision.VisionObjectiveProgress`) and sets named parameters through `BindingVariables`
(`{visionisusingperformancedata}{Bool|1|}`). Lists are drawn by table factories
(`ui-tableviews`, `ui-tablefactories`). Enum values become words and icons through data
collections (`ui-datacollections`: an `IntDataSet` of inclusive maxima, a
`TranslationDataSet` of translation ids, style sets). The C# code adds the property
registry (key <-> label, `PropertyRegistration::Initialise`, one per assembly) and the
record schemas (`*Reference` classes: `get_ID` is the record id, `GetPropertiesInternal`
the property keys, `GetPropertyTypeInternal` the record each property refers to).
`FM.GamePlugin.UiRecordID` names the 144 handler types of the UI_RECORD `'110 '` key in
the same order as the plugin factory.

The plugin side of a parameter: each name is a global `{hash, const char *name}` set by a
static initialiser (`stp x0, x19, [x8]`), looked up through 0x77E228. 231 names are
recovered (`visionobjectivesetter` 0x56D1A08, `visionobjectivetype` 0x56D1A18,
`visionobjectiveyear` 0x56D1A28, `visionisusingperformancedata` 0x56D19F8, ...).

## Files

| File | Content |
|---|---|
| `fm_live_mcp/fmdb/ui_frontend.py` | metadata v39 reader (`Metadata`, `GameAssembly`, `FrontEnd`), `load_table`, `describe`, lookups |
| `scripts/fmdb_ui_frontend.py` | extractor (capstone + UnityPy, offline) and `--resweep` |
| `fm_live_mcp/fmdb/data/ui_frontend.json.gz` | the table, 328 KB |
| `fm_live_mcp/fmdb/ui_recipes_screens.py` | context protocol, translator, club vision judgements, squad happiness, transfer offer rows |

The shipped table is build 27.0.0's front end. Another build gets its own, extracted by
`scripts/fm_update_build.py` into `$FMCP_CACHE_DIR/fmdb/anchors/<sha256>.ui_frontend.json.gz`;
`ui_frontend.table()` loads the running build's and `fm_ui_frontend` names it under `source`
(docs/GAME_UPDATE.md, "The front end per build").

Tools: `fm_get_club_vision_progress`, `fm_get_squad_happiness`, `fm_ui_frontend` (offline
lookup of views, parameters, records, collections). Inventory 189 -> 192.

Table contents: registry 9,130 keys (the older `ui_registry` has 7,720); 981 record
schemas with 11,949 properties and 2,487 record references; 4,915 views; 230 table
factories; 416 data collections (199 with translation ids); 231 plugin parameter names.

Rebuild: `PYTHONPATH=. uv run --no-project --with capstone --with UnityPy python
scripts/fmdb_ui_frontend.py` (~30 s; reads the installed files in place).

The older registry has four wrong keys: registrations written as
`add w0, w8, #1, lsl #12` were read without the shift. `SelectedCreatedClub` is `Ymg9`
(not `YmW:`, which is `CanChangeSquadNumber`), `LoanDurationValue` is `0kaf` (not `0kQg`),
`PreferredFoot` is `22  ` (not `200?`), `ClubEligibilityList` is `cegl` (not `ce7o`).

## The context protocol (what the earlier lanes did not send)

A view's parameters reach the plugin in two places, both shipped code:

1. client slot 4 looks a parameter up through 0x77E228 when it formats the property (the
   earlier `params={rva: int}` hook answers these);
2. client slot 2 `(this, request, out bag)` turns parameters into data-key arguments
   (CLUB_UI_HANDLER 0xCA708: `visionisusingperformancedata` -> `'CVpe'` through 0x657F78),
   and the database getters read those arguments from the plugin-wide UI context record
   at 0x56D38C0 (a vector of `{u32 key, pad, typed*}`): the CLUB getter 0x1FAF4D8 looks up
   `'CVpe'` at 0x1FB9A88 and `'ytpe'` / `'CVls'` at 0x1FB3878, and 0x11B5510 reads `'Hhum'`
   from it. In live memory the record held a `'CVpe'` entry (null) after the owner had
   left the screen; the earlier emulation never set it.

`ContextReader` (data-key protocol) and `ContextKeyReader` (every protocol,
`ui_recipes_more.KeyReader`) run slot 2 with the view's parameters, point the context
record at a VM-heap copy of its entries plus the slot-2 output for each server computation,
then restore the record header. Two observations shape this: the getters null a context
value after reading it, so each computation gets a fresh copy of the value bytes; and
inserting through the game's bag insert 0x43F72E4 into the live record produced a null
pool value, so the entry array is rebuilt in the VM heap instead. Who copies slot 2's bag
into 0x56D38C0 in the running game (the channel layer) was not traced; the recipe does that
step itself and nothing else.

## Club Vision judgements: 22 of 22

The judgement column is `VisionObjectiveProgress` = `cvop` of the objective record `cvor`
(table factory `ClubVisionObjectiveTableFactory`, column `judgement`; widget
`ClubVisionObjectiveProgressWidget`). The words come from
`ClubVisionProgressDataCollection`: value 0..16 -> translation ids 1743..1758, 4583,
translated by the game's translator (plugin export
`i_translator_get_translation_from_id`; `translate()` calls the translator object at
0x5721E70, vtable slot 4):

| value | word | value | word |
|---|---|---|---|
| 0 | Failed | 9 | Delighted |
| 1, 2 | Struggling | 10 | Very Pleased |
| 3, 4 | On Course | 11 | Pleased |
| 5 | Passed | 12 | Satisfied |
| 6 | Not Judging | 13 | Disappointed |
| 7 | Reserving Judgement | 14 | Very Disappointed |
| 8 | Not Started | 15 | Devastated |

Why every row read 6 before: without `'CVpe'` the CLUB getter serialises the raw
database objectives (builder 0x1A27AF8 -> 0x1A2498C, which stores 6 at +0xB8). With
`'CVpe'` = true it builds evaluated objectives (0x1A27C8C -> 0x1A24FBC, judgement
0x1F03728(objective, 1, 0); 0x1A27E20 -> 0x1A253A0, judgement 0x1CAB9E8 for competition
objectives). 0x1F03728 returns 6 for an objective type that is not judged, 7 before it has
started, else a score band (0x1F03B24): with the performance flag set and an objective
type that has a mood scale, > 799 Delighted, > 749 Very Pleased, > 549 Pleased, > 449
Satisfied, > 299 Disappointed, > 199 Very Disappointed, below that a further type test
(0x1F03880, not decoded) picks the last band; otherwise On Course (score >= 450) or
Struggling.

`club_vision_progress()` / `fm_get_club_vision_progress`, against the owner's screens:
board wage budget On Course, profit Pleased, four contract rules Not Judging, four culture
items Pleased (10/10); supporters Sunderland, Europa League, pressing, possession, set
pieces Pleased, attacking Delighted, entertaining Very Pleased (7/7); five-year plan
latter stages and qualification of the Champions League Pleased, FA Cup Reserving
Judgement, EFL Cup Pleased, Community Shield Passed (5/5). The rows also carry
`VisionObjectivePerformance` (`aZDo`), the sentence of the screen's "i" tooltip, e.g. "The
board are reserving judgment until you have taken charge of a match in this competition."
for the FA Cup and "The board are pleased that the team won the Community Shield this
season.". Later seasons read Reserving Judgement (2031/32 challenge for the title,
2033/34 win it) or Not Judging. ~5 s, 16 random draws (shared with the existing
CLUB read).

"Challenge for the FA Cup" is an objective of the evaluated list (competition builder
0x1A27E20); the raw `CvBo` never had it.

## Squad happiness in one call: "who is unhappy and why"

`squad_happiness()` / `fm_get_squad_happiness` reads every player of every team of the
club with three slot-13 passthrough keys each (`Pohl` overall, `pthn` playing time,
`Mora` morale) on one warm VM, no input transfer, and words from the front end's
collections; the reasons (`HPNe` HappinessNegatives, `dafe` morale text) are read only for
the unhappy players (overall below Content or playing time Concerned or worse). Measured
11 Nov 2026, load 130-200, `nice -n 10`, single process, warm VM: list of 66 players 1.6
CPU-s; whole call with reasons for 12 players 5.9 CPU-s (9.9 s wall). One
`player_status` (the earlier per-player tool) costs 3.4-3.9 CPU-s on the same warm VM.
`club_vision_progress` 0.7-1.9 CPU-s.

Reference save: overall words Delighted 20, Very Happy 28, Happy 13, Content 2, Slightly
Unhappy 2, Unhappy 1. Lewis Miley (overall -20 Content, playing time -56) and Jay Robinson
(-36 Slightly Unhappy, playing time -100) both read playing time **Alienated**: the
"feel alienated" on the Squad screen is the playing-time word, which the earlier band
classifier never looked at. Very Happy + Delighted = 48 per player against the game's own
47 (`ptvl`); the band words are the game's, so the one-player difference is in the
exclusions of the `nohp` count (virtual +0x4E8, +0x90 == 5), not in the words. Eleven
players read playing time -20, which the collection words "Concerned" (the band is
inclusive at -20). `HPNe` came back as an empty list for all twelve; not verified against
the screen.

## Happiness words

`OverallHappinessDataCollection` gives the word for `Pohl` (HierarchyOverallHappinessLevel),
bands by inclusive maximum: -81, -61, -41, -21, 19, 39, 59, 79, 100 (translation ids
31051, 31052, 31053, 45526, 45525, 45524, 31058, 45523, 31060).
`PlayingTimeHappinessDataCollection` does the same for playing-time happiness.
`collection_text(vm, name, value)` returns the word for any collection.

## Re-sweep with the views' parameters

`scripts/fmdb_ui_frontend.py --resweep SWEEP_JSON` re-reads every key the earlier sweep
left unset after asking for a screen parameter (171 keys). Each parameter is named from
the plugin table and supplied with the values the views use (`view_values`), or the career
object for object-valued names, through `read_key` (slot-2 context and slot-4 lookups).
Results: see "Re-sweep results" below.

## Re-sweep results

Of the 171 keys the earlier sweep left unset after asking for a parameter (30 handler
types; 11 Nov 2026, load 100-300, two processes), 27 now return values, 89 stay unset with
every value the views use, 7 are unavailable, 6 read a parameter global whose name the
static scan did not recover, and 42 were not tried because the parameter is an object
(person, human, team, club, date, competition) that needs a RECORD or SI_DATE typed value
(9 of the 42 were tried as plain ints before the skip was added and stayed unset).
Handler types with keys now read:

| Type | Handler | Now read / re-read | Keys now read (parameters) |
|---|---|---|---|
| 18 | COMPETITION_TACTIC | 5 / 25 | SelectedTeamInstructionOption (teaminstructionid=1); AddFormationOptions (inpossession=False); TacticsRowHighlightID (draggedcontext=0); FormationNameNoWords (inpossession=False); TacticIconName (playerindex=0) |
| 28 | CLUB | 3 / 12 | BudgetAdjustment (viewid=0); VisionObjectiveList (visionobjectivesetter=1, visionobjectivetype=-1, visionobjectiveyear=1); RecruitmentContractsSpeakTo (selectedobjectlist=0) |
| 28 | COMPETITION | 1 / 4 | WaiverListSpeakTo (selectedobjectlist=0) |
| 28 | PERSON | 1 / 48 | HumanCanMarkSelectedPortalMessagesAsRead (selectedobjectlist=0) |
| 54 | GAME | 4 / 7 | ActiveRuleGroupsCount (gender=-1); JoiningRuleGroupsCount (gender=-1); ActiveRuleGroups (gender=False); ActivePlusJoiningRuleGroupsCount (gender=-1) |
| 61 | MATCH | 1 / 9 | MatchTeam (ishometeam=False) |
| 66 | MULTIPLAYER | 1 / 1 | CanInviteFriend (id=1) |
| 73 | PERSON_SEARCH | 3 / 3 | PlayerSearchFilterWorldClassSimilarPlayersSuggestions (numsimilartosuggestions=7); PlayerSearchFilterHumanClubSimilarPlayersSuggestions (numsimilartosuggestions=7); PlayerSearchFilterPositionRoleSuggestions (numpositionrolesuggestions=1, adjustplayersearchsuggestionsforcurrentfilter=False) |
| 88 | RULE_GROUP | 1 / 8 | PossibleDivisionLevels (gender=-1) |
| 93 | SET_PIECE | 3 / 3 | AddRoutineDropdown (setpiecetype=0, setpiecescenario=1); ModifyRoutineDropdown (setpiecetype=0, setpiecescenario=1); SelectedRoutineTemplates (setpiecetype=0, setpiecescenario=1) |
| 104 | SQUAD_PLANNER | 1 / 1 | CurrentFullSquadPositionPlan (positionmask=1) |
| 110 | STATIC_STRING | 1 / 2 | TransferTypeString (stringid=1) |
| 128 | TEAM_TRAINING | 2 / 2 | TrainingWorstRatings (number=1); TrainingBestRatings (number=1) |

The 34 handler types that read nothing build per-row sub-handlers (edit-session rows, DB
summaries, match-player rows); only one key among them reads a parameter (type 67,
NATIONAL_SQUAD_SELECTION_EDIT_SESSION, not unset but unavailable earlier), so the re-sweep
does not change them.

## Data Hub analytics (13 November 2026, build 27.0.1.2503222)

Live save: Newcastle United, manager Cesar Jules, 5 Jan 2031. Addresses in this section are
27.0.1's; the code holds no new address.

The Data Hub's team and player blocks (`TeamAnalyticsBlock_8x4/12x8/16x8/20x8`,
`PlayerAnalyticsBlock_*`) bind `Team.TeamAnalytics` (`uvRT`) and `PlayerAnalytics` (`fGjn`) of
TEAM_UI_HANDLER. Both read empty in every sweep, and the ledger blamed screen parameter
`boolean` (0x56D1168). The parameter was not the cause.

**Why they read empty.** The server getter (slot 2, 0x5C4254; the `uvRT` case at 0x5C6E20)
takes two object arguments from its context bag, its fourth argument, and returns an empty list
when either is missing (0x5C6E7C, 0x5C6E98 -> 0x5CC078):

| Data key | Object | View parameter the client turns into it |
|---|---|---|
| `Hhum` | the human manager | `human` |
| `mCLv` | the team asking for the report | `teamrequestingreport` |

The client's parameter slot (slot 2, 0x58C910; `uvRT` at 0x58D974) makes that translation
through 0x658C34 `(request, parameter global, bag, data key, 1)`. The server reads each argument
as a RECORD typed value and takes its `dref` (0x658554 / 0x6587AC -> 0x11BC514). The view
passes the objects in a typed value of its own (traits from 0x783C70) that was not decoded:
run with a RECORD in its place, slot 2 writes both keys with the null id.

**The route.** `ui_recipes_analytics.ObjectContextKeyReader` skips slot 2 and hands every server
computation a context bag `{Hhum: RECORD{'110 ': 28, dref: manager}, mCLv: RECORD{'110 ': 28,
dref: managed team}}`; the game's client code then unpacks each chart's observation blob
(`Obsv`) into records. Both arguments are needed: with one missing the list stays empty.

**Parameters and their legal values.**

| Parameter | Read by | Values |
|---|---|---|
| `boolean` | client get slot, both keys | 1: sentences in the first person ("We gained most possession around our penalty area"); 0: the team by name ("Newcastle ..."). Same numbers either way |
| `selectedtabindex` | client get slot, `fGjn` only | 0 every chart, 1 goalkeepers, 2 defenders, 3 midfielders, 4 attackers; 5 and above answer as 0 |

**What comes back.** One `DataHubVisualisationsReference` record (`q7pH`) per chart:
`VisualisationCategory`, `VisualisationSubCategory`, `AnalystPerson` and `ObservationData`, whose
shape depends on the chart. The managed team returned 28 team charts and 6 player charts;
Arsenal, read as another team, returned 9.

| Kind (`PrismID`) | Category | Record | Charts on the reference save |
|---|---|---|---|
| `zone_map` | 2 | `ZoneMapReference` (`zi2R`): `PitchZonesList` of six `{SubjectStatValue, PitchZoneIntensity}`, `PitchZoneIntensityBarMax` | sub-category 0 Possession Gained, 1 Possession Lost, 2 Passes attempted, 3 Defensive Actions |
| `first_contact_zone_map` | 12 | `FirstContactZoneMapReference` (`IHFl`): three zones | 0 opposition box, 1 own box |
| `scatter_graph` | 1 | `ScattergraphReference` (`WpNP`): `CombinedRecordList` of `{Team or Player, ScatterChartData {x, y}}`, both axes with label, minimum, mean and maximum, four quadrants | 20 team charts (Possession, Passing, Pressing intensity, Pitch Tilt, ...), every player chart |
| `polygon` | 3 | `PolygonObservationReference` (`A94L`): `DataPointList` of statistic, value, comparison, minimum, maximum | General Performance, Team Attacking, Team Defending |

Every observation also carries `GraphType` (the chart's name), `PerformanceSummary`,
`PerformanceSummaryExtended`, `TimeFrame` ("This Season"), `Competition` and
`VisualisationPinData` (`PrismID`, pinned, preferred).

**Zone layout.** `SubjectStatValue` is the percentage of the team's events in the zone (the six
add up to 100; the view prints it as `[%fraction#1-.0]%`); `PitchZoneIntensity` is the bar level,
1 to 7. `ZoneMapBlock` draws the list left to right over a horizontal pitch in its
`...zone-map-template-defensive-actions-6-col` frame, so the zones are six columns along the
length. Which end is which comes from the game's own sentences: on Possession Gained and
Defensive Actions the fullest zone was the first and the sentence names "our penalty area"; on
Possession Lost it was the sixth and the sentence names "the opposition's penalty area". The
width of a column was not read: two columns to a third is an approximation. First-contact zones
run near post, centre, far post: both charts' sentences give their three percentages in that
order.

Possession Gained on the reference save: 34.2, 20.9, 23.1, 12.6, 7.8, 1.4 per cent from the
defended end; "81 possession gains per game, compared to an average team, with 79 per game."
Possession Lost: 14.2, 5.0, 12.4, 21.6, 19.8, 27.0; 89 a game against 92.

**Calls.**

* `fm_get_ui_screen(screen: "team_analytics")`: the zone maps and first-contact maps in full,
  the other charts by name. `chart: "possession gained"` (words of a name, kind or prism id)
  returns the matching charts in full, `chart: "all"` every chart; `team: "team:<index>"` reads
  another team. 0.2 to 0.6 s; no random draws.
* `fm_get_ui_screen(screen: "player_analytics" | "person_analytics" | "opposition_analytics" |
  "match_analytics")`: see "The rest of the Data Hub" below.
* `fm_ui_read(handler: "TEAM_UI_HANDLER", inputs: {dref: "managed_team"}, keys: ["uvRT"],
  params: {boolean: 1}, context: {Hhum: "managed_manager", mCLv: "managed_team"})`: the raw
  records. Two additions made this call possible: `context` (object arguments by data key) and
  naming a database record's handler by its class (type 28 builds the class of the object in
  `dref`, so it has no type number of its own; `fm_ui_read` could not build one before).

Ledger: `uvRT` and `fGjn` move from needs_parameter to reads, and 18 keys of the returned
records from unreached to reads (`ledger.SCREEN_READS`; `scripts/fmdb_ledger.py
--apply-screen-reads` marks them in the packaged ledger without a sweep). UI keys read: 4,463
-> 4,483 of 7,720.

Not read here: `PitchZoneIntensityBarCount` (no record returned it), `TeamMatchVisualisationData`
(the per-match pass, shot and position maps of the fixture record) and `KeyFindingsVisualList`
(the opposition report's findings). A chart for one chosen match or another time frame was not
found: every chart came back seasonal. The data collections that turn category numbers into
icons (`DataAnalysisPerformance*CategoryDataCollection`) are front-end only and are not needed:
each chart carries its own name. `PerformanceSummaryState` (1 to 4 seen) is returned as a number;
its wording was not decoded.

### The rest of the Data Hub

With the manager and the team in the context, four more sets of charts read. Each was empty in
every sweep.

| Screen | Key and handler | What it returns on the reference save |
|---|---|---|
| `player_analytics` | TEAM `VisualisationDropDownData` (`FyDK`) with flag argument `1H7p` false (view parameter `isteamvisuals`; true lists the 28 team charts again) | the Data Hub's "Ask for" catalogue: 35 player scatter graphs in the game's groups (General 4, Defensive 4, Creating 8, Scoring 6, Possession 11, Goal Keeping 2). `on_data_hub` marks the six that `PlayerAnalytics` (`fGjn`) shows |
| `person_analytics` | PERSON `FyDK`, the handler built on the player | one player's charts: for Anthony Gordon 16, six polygons against his position (General Performance, Attacking - Wingers ...) and ten scatter graphs |
| `opposition_analytics` | TEAM `OppositionReportVisuals` (`rijN`) | the report's findings as charts: for Arsenal the team's General Performance polygon and five standout players' polygons |
| `match_analytics` | FIXTURE handler (type 50) built from a row of TEAM `DataHubLastMatchFixtureDropdown` (`GfON`, the last three matches): `ActionZonesVisualisation`, `HomeShotMap` / `AwayShotMap`, `HomePassMap` / `AwayPassMap`, `HomeAveragePositionMap` / `AwayAveragePositionMap` | Sunderland v Newcastle, 4 January 2031: possession by third for each side; shots by 14 locations with expected goals (Sunderland 7 shots, 0.78 xG); the eleven who played most together with each pass combination; average positions overall, in possession and out of possession. For the latest match TEAM `LastMatchAnalysis` (`xlO9`, screen parameter `id`; the same answer for every value tried) adds the analyst's sentence, the xG story (12 shots with time, expected goals and score) and the momentum chart; it is published only when it names the same teams and date as the list's first row |

`match_analytics` returns the match records under the game's own property labels
(`ui_recipes_analytics.labelled`): references named, colours dropped. The average-position map
turns both sides to defend the negative `YaxisData` end. `FixtureDate` inside
`TeamMatchVisualisationData` is a date-time typed value (kind 27) the reader does not decode; the
screen takes the date from the fixture record.

`fm_get_ui_screen` gains `match` (1 = the latest of the three). Ledger: 64 more keys read
(`FyDK`, `rijN`, `xlO9`, six match chart keys and the fields of their records); UI keys read
4,547 of 7,720.

Still not read: the heat map itself. FIXTURE `HomeHeatMap` / `AwayHeatMap` read screen parameter
`person` and TEAM `HeatMap` reads `id` and `person`; both stayed empty with a player's UI id as an
integer, so they need the object typed value the view passes (the open item under "Not done").
The player lists and default player beside them read. `PostMatchAnalysisKeyFindings` and the
attacking and defensive match analysis points were empty for the latest match. The xG table stops
at its record: `XGTableBlock` expects a `datahubxgtable` record (`KFsk`: `ObservationData`,
`XgTableLists`), no property of any record schema refers to it, and its keys (`XgTableLists`,
`FullXgTableList`, `TopTwoXgTableList`) stayed empty on the TEAM and COMPETITION handlers with the
context; the handler that builds it was not found. Not attempted: the MATCH handler's
`MatchMomentum` (the momentum chart itself reads through `LastMatchAnalysis`).

Files: `fm_live_mcp/fmdb/ui_recipes_analytics.py`, `tests/test_fmdb_ui_analytics.py`,
`tests/test_fmdb_ui_analytics_live.py`, `tests/fixtures/team_analytics_newcastle_2031_01_05.json`.

## Not done, with the next route

* Object-valued screen parameters (42 keys: person, human, team, club, date, competition).
  The Data Hub analytics (above) show the route that works: find the data key the client's
  slot 2 writes for the parameter and hand the server a context bag holding a RECORD typed
  value (traits registry + 0xB8, a vector of `{key, typed*}`) with `{'110 ': 28, 'dref': id}`
  under that key; `fm_ui_read` takes such a bag as `context`. Still open: the typed value the
  view itself passes (traits from 0x783C70 on 27.0.1), which would let slot 2 run unaided, and
  an SI_DATE typed value from `ui_recipes_news.SI_DATE_TRAITS_RVA` for the date parameters.
* Six parameter globals without names (TRANSFER_ROOM lists): their initialiser does not use
  the `stp x0, x19, [x8]` pattern; next route: follow the hash at the global back to the
  string by the other store patterns.
* The 34 silent handler types: rows of parent lists. Next route: read the parent list key,
  take each row's UiRecord as the sub-handler's record (the way `transfer_offer_row` does).
* Unhappy predicate 0x1FB2010 and the 48 vs 47 count: not decoded.
* Agreed playing time "-" and CONTRACT wage "N/A": the Player Contract card binds
  `person.FullContract` (`ctrc`, as the earlier lane read) with view parameters
  `isonmainscreen`, `selected_tab_index`, `slider_min`; not re-read with them.
* Fixture venue `KmOX`: no view binds it. The match screens bind `selectedfixture.Stadium`
  (`90  ` of the fixture record `fixt`), but the factory builds no client handler for a
  fixture-table (0x35) dref. The venue is already read through the calendar's fixture
  reference (`ui_recipes_news.fixture_detail`, FIXTURE +0x28), e.g. "Estadio de La
  Cerámica" for 10 Dec.
* Training unit membership, board members' year joined: no view binds either by those
  names (`DateJoined` `kS8Q` exists only in the manager-history record). Not found.
* Youth intake level and feedback: need `std::random_device`, which the virtual lane is
  modelling; no change here.
* Transfer offer rows: `transfer_offer_row()` reads every property of the row schema
  `Q2DC` (37 properties: fee and clause strings, status, type, wage, ...) through handler
  134. Untested: no offer exists on the reference save.
* Brief item 4 screens (player search, scouting centre, press conference, team
  talk, staff search, job centre, club and competition history, rankings, awards, finances
  by month, sponsorship, attendance, transfer window, youth and reserves, international,
  manager history, hall of fame, social feed): the table names their views, expected
  records, parameters and bound properties (`fm_ui_frontend`, e.g. view="DeadlineDay",
  search="SeasonTicketList"); no shaped recipes were written, except the Data Hub's analytics
  (above). The re-sweep reads the
  PERSON_SEARCH suggestion lists and the TEAM_TRAINING best and worst ratings.
* Cost work asked by the orchestrator: done for the new squad read (list/narrative split,
  one warm VM, no per-item rebuild of the list handler beyond one build per player, CPU
  reported). Not done: the id-plus-content-fingerprint cache (results still go through
  `recipe_read`'s per-game-date cache), the split for the older recipes (inbox, player
  status), and any FastVM port (performance lane).
* Who copies a client's slot-2 bag into 0x56D38C0 in the running game: not traced.
