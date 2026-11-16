# Match-day, match-engine and competition-service managers

Module: `fm_live_mcp/fmdb/sources/match_state.py` (lazy collection tables, built on first reference).
Measured on 12 Nov 2026 against the Newcastle career on 13 Dec 2030, game idle after West Ham v
Newcastle, load average 6 to 13.

## Roots

| Manager | Route (plugin RVAs) | Class check |
|---|---|---|
| MATCHDAY_MANAGER | global 0x56A49F0 | vtable 0x55F6980 |
| PLAY_FIXTURE_MANAGER | global 0x56A4A00 | 0x55F7630 |
| simatch::MATCH_MOMENTUM_MANAGER | global 0x56A66E0 | 0x56A06E8 |
| simatch::MATCH_PLAYER_RATINGS_MANAGER | global 0x56C35A0 | 0x56A01C8 |
| simatch::MATCH_SYSTEM | global 0x573C8B0 | 0x569F240 |
| simatch::TRANSLATABLE_MANAGER | global 0x56A4BF0 | 0x55A3828 |
| simatchshared::MATCH_APPEARANCE_SYSTEM | global 0x56A9690 | 0x56A1E00 |
| simatchshared::MATCH_TEAM_KIT_SYSTEM | global 0x56A7F90 | 0x56A1D98 |
| simatchshared::PLAYER_INSTRUCTIONS_MANAGER | global 0x5734828 | 0x5669110 |
| simatchshared::STAT_DISTRIBUTION_MANAGER | global 0x573C8A8 | 0x56A08C0 |
| sicomps::COMP_HOSTS_MANAGER | global 0x56BF8D0 | 0x566CFB0 |
| sicomps::TV_MANAGER | global 0x56BF8E8 | 0x566D6C8 |
| NETWORK_COMPETITION_MANAGER | global 0x56A6888 | 0x55F7050 |
| GAME_COMP_MANAGER | global 0x56A4B90 (GAME_RULE_GROUP_MANAGER) +0x158 | 0x55DC600 |
| GAME_SQUAD_MANAGER (sicomps::SQUAD_MANAGER) | competition manager +0x58 | 0x55DE078 (base 0x567A0E8) |
| GAME_STADIUM_MANAGER (sicomps::STADIUM_MANAGER) | competition manager +0x50 | 0x55DE108 (base 0x567A1B0) |

How the squad and stadium managers were found: neither is held by a global. Their constructors
(0x1BFBF5C, 0x1AC51E0) are called only from two factory functions that no code calls directly; the
factories are slots 5 and 6 of the GAME_COMP_MANAGER vtable (data 0x55DC628/0x55DC630).
sicomps::COMP_MANAGER's constructor 0x3BAC420 calls its own slots 5, 6, 8, 7 and 9 and stores the
results at +0x50, +0x58, +0x60 (GAME_NATIONAL_TEAMS), +0x68 (GAME_FRIENDLY_MANAGER) and +0x70
(GAME_DISCIPLINE). The competition manager itself was found two levels from plugin data: global
0x56A4B90 (and 0x56D57D0) -> GAME_RULE_GROUP_MANAGER +0x158.

## Tables

| Table | Rows (13 Dec 2030) | First build | What it is |
|---|---|---|---|
| `player_registration_marker` | 52,383 for 66,033 player records | 1.0 s | competition registration markers per player |
| `squad_manager_entry` | 1,002 (189 keyed by a competition) | under 0.1 s | GAME_SQUAD_MANAGER records, fields not decoded |
| `comp_host_record` | 82 | under 0.1 s | host-selection record per international competition |
| `comp_host_nation` | 515 | under 0.1 s | NATION lists of the other host records |
| `match_momentum_weight` | 48 | one read | momentum table |
| `match_rating_weight` | 66 (3 entries x 22) | one read | rating model multipliers |
| `match_screen_team_stats` | 2 per resident match client | a few reads | team statistics the match screen shows |
| `native_manager` | 16 | under 0.1 s | root, class and vector sizes of every manager above |

The first statement on a snapshot built before this module cannot see the tables: collection
tables are created at snapshot build. A snapshot rebuilt after the merge has them (42 s here,
including the rebuild).

### player_registration_marker

Who is registered for which team. RegisteredPlayers (SQUAD_REGISTRATION_EDIT_SESSION_UI_HANDLER,
key 'rply') calls PLAYER virtual +240 = D32054 with the team and the rule selector; D32054 reads
the PERSON +0x48 holder of the player's common subobject (ACTUAL_PLAYER primary +0x278), a vector
of 16-byte relations `<Q entity, H, B transport, B kind, B selector, B metadata, H>`, and admits
kinds 25 to 29 and 56 with transport 4 (a TEAM pointer). Kind 25 is committed, 26 a pending
addition, 27 a pending removal (`player_registration_source`, which documents the edit and
finalisation code). The table keeps every admitted marker in vector order; the newest exact marker
for a team and selector is the one D32054 uses.

Checked: for every (player, selector) of the busiest team, the newest marker equals
`player_registration_source.project` for that team and selector (live test). Newcastle (team 545):
25 players with kind 25 and selector 8, the Premier League rule (Adam Wharton, Anthony Gordon,
Silas Huber, ...; the hand-built source also counted 25 committed on 13 Nov 2030), 24 with selector 0,
17 with selector 19, 23 kind-56 markers.

Every player record is read, by D32054's own route: both player classes have D32054 at vtable
+0x240, and D32054 takes its subobject at `this + *(vtable - 0x20)` (0xD32080..0xD32088), which is
0x278 for ACTUAL_PLAYER and 0x370 for ACTUAL_PLAYER_AND_NON_PLAYER, then the holder at +0x48
(0xD3208C). 66,033 records (62,741 + 3,292), 52,383 markers.

### competition_registration_rule, registration_verdict, view competition_registration

A competition's selector is its current registration rule's: COMP +0xB0 runtime, rule index
runtime +0x49 into the bank runtime +0x388 -> +0x1F0 -> +0x60, selector rule +0x125, rule
competition id +0x108 (the route `ucl_registration_source.rule_context` reads for the Champions
League). 1,454 competitions have a runtime: 1,002 have selector -1 (no registration selector),
320 share selector 8 (Premier League, rule competition id 11, and most domestic leagues and cups),
and the others are: 0 UEFA Champions/Europa/Conference League; 2 CONMEBOL Libertadores and
Sudamericana; 4 MLS (5 competitions); 6 OFC Champions League; 13 A-League (4); 15 Recopa; 18 CAF
Champions League and Confederation Cup; 21 Libertadores Sub-20; 22 three Brazilian state leagues;
23 CONCACAF Champions Cup; 27 FIFA Club World Cup; 28 eleven cups and youth leagues; 43 UEFA
Women's Champions League; 44 four FIFA intercontinental play-offs; 45 to 50 the women's
continental and club cups. Selector 19 (17 Newcastle markers) is on no current rule.

`registration_verdict` evaluates D32054 mode 1 (newest marker with the team, transport 4 and the
selector, or kind 56; true for 25/26) for every player, team and rule selector it has a marker for
(154,786 rows, 0.6 s). The view `competition_registration` joins it to the competitions using that
selector in which the team has a fixture in the competition's current season (the newest
`fixture.season_code` of that competition). Newcastle: Premier League 25 registered of 50 rows,
Champions League 24 of 49. Before 12 Nov 2026 the view took any season and also listed the Europa
League (it shares selector 0): Newcastle's 21 Europa League fixtures are all of seasons 2028 and
2029 (18 Jan 2029 to 22 May 2030); it has none in 2030, which has 226. The game
stores no reason for a player not being registered; a false verdict is not an exclusion (age
exemptions are separate, `player_registration_source`). Players with no marker for the team do not
appear.

### squad_manager_entry

GAME_SQUAD_MANAGER +0x08 is a vector of 1,002 pointers to 0x30-byte records: +0x00 u32 key (a
competition database index when +0x04 is 0; 189 records), +0x04 u16, +0x06 u16 code, +0x08 u32,
five dates `<u16 year, u16 day>` at +0x0C..+0x1C and one packed date at +0x20. Two records carry
dates: Peruvian Second Tier (8 and 9 Dec 2030) and Under 18 International (28 and 29 Nov 2030).
The meaning of the fields is not decoded. The manager's virtual functions (GAME_SQUAD_MANAGER
slots 2 to 12, 0x1BFC758..0x1C0E584; slot 6 alone is 0x1BFEE2C..0x1C0871C, about 9,700
instructions) were not traced. One lead: slot 6 names the type PERSON_SQUAD_SELECTION_DATA at
0x1C068DC, so the records are likely squad-selection (call-up) windows; next route: emulate slot 6 on
one record and log which fields it compares with the game date. The registered squads themselves
are the markers above, not these records.

Selector 19 (17 Newcastle kind-25 markers) is on no rule of any bank: the `selectors_json` of all
1,454 competitions with a runtime lacks 19, not only their current rules. Of the 17 players, 12
played Newcastle's 2029/30 Europa League matches and 12 the 2030/31 Champions League; 10 other
players of that Europa League squad still at the club have no selector-19 marker, so "the 2029/30
Europa League rule" is not established. Next route: the marker writer (`player_registration_source`
documents the finalisation code) and the rule loader, to find which rule carried 19; or a
competition whose runtime has been freed (8,136 competitions, 1,454 with a runtime).

### comp_host_record, comp_host_nation

COMP_HOSTS_MANAGER +0x08 holds 82 records (0x68 bytes): competition +0x48 (FIFA World Cup 2026,
FIFA Under-20 World Cup 2027, FIFA Arab Cup 2025, Africa Cup of Nations 2025, ...), u16 years at
+0x58/+0x5A/+0x5C (the first is an edition year, the others 1900 in every record), five code bytes
and two vectors (+0x00 pointers to 0x60-byte objects, +0x30 four 8-byte rank entries). +0x20 and
+0x38 hold 0x50-byte records whose +0x18 vector lists NATION pointers. Which list holds bidders,
hosts or rotation candidates is not decoded.

### match_momentum_weight, match_rating_weight

Both managers are model parameters, not per-match state: their bytes are identical in the
half-time capture and between matches. Momentum: 48 entries `<u8 a, u8 b, u16 c, i32 value>`,
c in 0..2 for every (a, b). Ratings: three 0x90-byte entries, each with two vectors, a count (40),
22 float multipliers at +0x30 (1.2, 1.2, 1.1, 1.1, then 1.0) and u32 6700 at +0x88. None of the
codes is labelled.

### match_screen_team_stats, and the half-time question

Round 1 read two candidate sets at half time: the client snapshot (MATCH_STATS embedded at client
+0x08) and the engine's GAME_MATCH_STATS (engine +0x14E90). The match screen shows the engine's:

* MATCH_UI_HANDLER derives from MATCH_STATS_UI_HANDLER (RTTI). The shared get_property
  0x26A17C reads every team statistic from the object its virtual +0x108 returns (0x26A2E4..0x26A2F8),
  then picks the side at +0x68/+0x70 (0x26A458) and reads TotalShots from side +0x16F
  (0x26BC20), ExpectedGoals from +0x60.
* The base class's +0x108 returns null (0x26C8FC). MATCH_UI_HANDLER's (0x2A0D04) locks its
  client (+0xC8, control block +0xD0) and calls 0x48E6DF8, which returns client +0xF8 -> +0x18 ->
  +0x14E90. client +0xF8 -> +0x18 is the GAME_MATCH (`active_match_source`), so the object is the
  engine's GAME_MATCH_STATS, the "simulation" scope.

Checked on the half-time capture: the route resolves to a GAME_MATCH_STATS and decodes to the
simulation values (Newcastle 4 shots, 0 on target, xG 0.24, 211 of 249 passes; West Ham 4 shots,
xG 0.31, 243 of 274); the client snapshot said Newcastle 5 shots and xG 0.63. The full-time capture
and the live game (the West Ham v Newcastle client is still resident) read West Ham 7 shots (2 on
target), xG 0.91, 498 of 557 passes; Newcastle 9 shots (1 on target), xG 1.24, 433 of 500.
Not verified by emulation: that the screen's handler instance is bound to this client (+0xC8).

When no viewable client is resident the table is `unavailable` with "no match loaded: ...". The
pinned bytes of 0x48E6DF8 are compared before every read.

## Momentum (`match_momentum`)

MatchMomentum (key 0x39533448) in MATCH_UI_HANDLER get_property 0x29A3AC (case at 0x29B034) calls
0x299B5C with the side. That takes the client's engine +0x14A58 (0x48E6E20), its +0x440 event store
(0x48DA88C), and calls 0x4898A94(momentum manager, store), which returns a vector of 8-byte segments
`<f32 value, u32 end tick>`, one per 5 minutes. 0x4899854 shows the value for side 0 and its negation
for side 1 (0x4899980..0x489998C). The table emulates 0x4898A94 (bytes pinned) on the loaded match:
18 segments at full time of West Ham 2-1 Newcastle (0.23 s, load 11). Emulated on the captures, the
half-time series has 9 segments and only the first four non-zero (-0.043, 0.722, 0.281, -0.283); at
full time the first three are unchanged and the fourth is 0.190. Screen parameter 0x56D16B8 ("team")
is not what selects the side here: the side comes from 0x29B068 (`sxtb w2, w23`).
Archived matches keep no momentum: the store hangs off the engine. `match_momentum` and
`match_rating_component` carry `match_idx` (the identity of `match.idx`: YYYYMMDD * 100000 + home team
idx, from the screen statistics' fixture date and home team) and `date`, so the loaded match joins to
`match` once the game archives its result (until then `match` has no row for it).

## Match ratings (`fmdb/match_rating.py`, `match_rating_component`, `fm_get_match`)

The rating a player has during a match is a weighted sum of his match statistics, computed by the
updater 0x4560B60 (723 instructions, traced line by line). It is not a list of events: the 40-byte
entries at MATCH_PLAYER +0x1AC0 are position spells, not event records.

What the updater reads and does, for one simatch::MATCH_PLAYER `pl` (integer arithmetic 32-bit,
floats float32, rounding half away from zero, all as the instructions do):

1. Model entry: the first 0x90-byte entry of MATCH_PLAYER_RATINGS_MANAGER +0x08 whose +0x8C
   (packed build 26.8.4.29) does not exceed GAME_MATCH +0xA2C. Base = entry +0x88 (6700), else
   GAME_MATCH +0xA74 x 10.
2. Position spells, `<u16 code, ..., u32 ticks +0x20>`; 240 ticks a minute, 21,600 in 90 minutes.
   Code bit 13 drops a spell; bits 6..12 are a signed position code f. The total time T sums the spells
   whose f passes mask 0x16B7EFFF (f < 0, bit f + 31) or 0xFEDED (f >= 0, bit f).
3. For each position bit p (0..58) in the union of table 0x53FCBA8[f + 31]: t_p is the time of the
   spells with bit p in table 0x53FCD40[f + 31]; the entry's std::map at +0x18 (end node +0x20, key
   +0x20, value +0x28) gives the row index for key 1 << p; the row is 52 i16 weights at entry +0x00 +
   0x68 x index (35 rows, the 1,820 weights of `match_rating_weight`'s vectors).
4. S_p = sum of weight x input over the GAME_MATCH_PLAYER_STATS counters (MATCH_PLAYER +0x1880;
   `TERMS` lists the 32 inputs and their row offsets), plus assists beyond the first, goals below
   expected goals (x100, only when negative), one or two yellow cards. acc += round(t_p / T x S_p).
5. Time-weighted terms, x min(t_p, 21600) / 21600, truncated: row +0x00 (negative for every
   position in the captures: a deduction the other terms must make up), row +0x42 when GAME_MATCH +0x154F0 bit 2 is set
   and he conceded none, row +0x50 x (5 - saves - conceded) for the keeper positions (mask
   0x20000000001001) while that is below 5.
6. Goal items, MATCH_PLAYER +0x1AA8, 16 bytes `<u64 position bit, u32 tick, u8 kind, u8 total goals,
   u8 flag>`: row +0x02 each (+0x18 instead when flag bit 0), +0x04 / +0x06 for kind 1 / 2, +0x0C for
   every item after the first, and +0x08 (+0x0A when scored in the last 2,400 ticks) when it is the
   latest goal of the match and leaves the scorer's side level or one ahead.
7. Multiplier m: one of the entry's 22 floats, chosen by the team's expectation (team +0x34FC,
   truncated: k) against the on-pitch goal difference (stats +0xD1 - +0xD2) and by the sign of acc
   (`_multiplier_offsets`; the live entry has 1.2, 1.2, 1.1, 1.1, 1.0 ...). When T < 21,600:
   m = 1 + T / f32[0x53FCA6C] x (m - 1).
8. Rating = clamp(base + round(m x acc), 0, 10000) at +0x1D58. +0x1D64 = that less
   d^2 x min(minutes, 90) / 60 when the team is behind by d (team +0x34A8 - +0x34AC) and he played 21
   minutes. Stats +0x82 = (rating + 5) / 10 (the hundredths the statistics frame archives; the
   analytics string "player_rating"), +0xB3 = (rating + 500) / 1000. +0x1DE0 = the tick.

A player whose +0x1880 is null is not rated: the updater dereferences it unconditionally.

Checked: the mirror equals the emulated updater (PropertyVM, unmodified code), rating and second
word, for every player with a statistics object in the half-time capture (44, 22 of them on the
pitch), the full-time capture (44) and the loaded live match (44; West Ham 2-1 Newcastle, 13 Dec 2030,
97 minutes). The breakdown sums to the recomputed rating; the residual is the per-position and final
rounding (under 0.001).

Stored versus recomputed: the updater runs per player at events, so the stored rating can lag. In the
half-time capture the 11 Newcastle players were last updated 28 ticks before the others and differ by
0.001 to 0.006; in the full-time capture three substituted Newcastle players differ by 0.001 to 0.003
from the value their unchanged inputs give now. Which input changed after their last update is not
established. `stored_rating` is what the screen shows; `recomputed_rating` is what the components sum to.

### Names of the terms

The game's own names, where it has one: MATCH player statistics get_property 0x20493C sets a FourCC
property key right after loading each offset (labels from the UI registry: Goals +0x8B, Conceded
+0x8C, Assists +0x9F, ShotsBlockedDefending +0x9C, FoulsAgainst +0xA4, GoalMistakes +0xD0, ...), and
the analytics function 0x2F0F828 writes strings beside its loads ("goals_scored", "assists",
"sub_on_min" +0xAF, "sub_off_min" +0xAA, "player_rating" +0x82). Inferred, with the evidence in
`LABELS`: +0xE8/+0xEA (passes completed: equal to +0xBB for every outfield player in both captures;
+0xE4/+0xE6 equal +0xBA), +0xD1/+0xD2 (team goals for and against while on the pitch: consistent with
the 2-1 score and the substitution minutes in the full-time capture). Unlabelled, offset only: +0x8D,
+0x8E, +0x8F, +0x9D, +0x9E, the float +0x28 (non-zero for a few attacking players, up to 0.58), and
MATCH_PLAYER +0x1C48, +0x1BBC and the six bytes used only in mode 4 (all zero in both captures). A
whole-image scan for loads of these offsets near a C string or a registry FourCC found none.

### What the tools give

* `match_rating_component` (lazy, checked on every reference, about 0.2 s): while a match is loaded,
  one row per player and term with the count and the contribution in rating points, plus `base` and
  `rounding` rows; `SUM(contribution)` per player equals `recomputed_rating`. Unavailable with the
  reason when no match is loaded.
* `fm_get_match`: the players of the loaded match carry `rating_breakdown` (stored and recomputed
  rating, base, multiplier, positions with minutes and weight row, components with label and name
  source, rounding). When the game has not archived a result for the loaded match yet and it is the
  newest match of the filter, the answer has `state: loaded` with the engine's score, team statistics
  and players (1.8 s here); for any other match `coverage.rating_breakdown` says what is not stored.

### What archived matches keep

The final rating only. The statistics frame (serializer 0x4AD2910) writes GAME_MATCH_PLAYER_STATS runs:
the counters and the stored hundredths (+0x82, wire 136). It writes nothing of the MATCH_PLAYER: no
position spells (+0x1AC0), goal items (+0x1AA8), team expectation (team +0x34FC) or model entry. Those
exist only while the match is loaded: MATCH_PLAYER objects hang off the GAME_MATCH sides and no result
or frame points to them, and the West Ham match's objects are the only ones resident now. Without the
spells the position rows and the time shares are unknown, and without the expectation the multiplier
is unknown, so an archived rating cannot be split exactly. The archived counters times a guessed
position row would be an estimate; the tools do not offer one.

## Not read

* simatch::COMMENTARY_SYSTEM (vtable 0x56A02A0) and simatch::EMOTION_SYSTEM (0x56A0308) exist
  only during a match: the half-time capture has two of each, pointed to from non-polymorphic
  match records next to a NON_SIM_AI pointer (for example 0x7A9AB6CE90, after an ACTUAL_PLAYER
  pointer). Their constructors (0x4A92B88, 0x4A93C20) have no direct callers. Next: walk the
  GAME_MATCH to those records during a match.
* TV and prize money. TV_MANAGER (0x20 bytes) holds one vector of televised-fixture items that
  0x3BAE194 frees after processing; it is empty between matches. Its methods (0x4055188,
  0x40553D8, 0x4055BAC) take a fixture and check its date, teams and competition (+0x20). TV money
  is not stored there; competition prize money reads through COMPETITION_UI_HANDLER (PrizeMoney).
* Per-player match instructions: PLAYER_INSTRUCTIONS_MANAGER holds none. Its constructor
  (in 0x250FE84, at 0x2510710) allocates 0x18 bytes: two vtables and, at +0x10, the message id 0x802
  that the base 0x7681B4 (vtable 0x54ED858) registers with the dispatcher at 0x56A49B8. Slot 2
  (0x38F240C) switches on message +0x20 (0, 1, 2) to 0x38F2B28, 0x38F2440, 0x38F356C. Bytes past
  +0x18 belong to other allocations (a Steam interface name string). The stored player
  instructions are the tactic's: the hand-built `player_instruction_source` reads them from the
  working tactic creator (+0x120 in possession, +0x440 out of possession, 72-byte position records,
  selected option bits); `fm_get_managed_tactics` is that route. Not done: a collection table over it.
* MATCHDAY_MANAGER: +0x18 82 db::SCORELINE pointers, +0x50 7 sicomps::FIXTURE pointers, +0xE0 13
  competitions (12 ACTUAL_COMP, 1 FRIENDLY_COMP): the day's fixtures. PLAY_FIXTURE_MANAGER: +0x08 31
  and +0x20 32 FIXTURE_TO_PLAY_QUICK. MATCH_APPEARANCE_SYSTEM: +0x08 4,238 shared pointers to
  MATCH_PERSON_APPEARANCE_INPUT (16-byte shared_ptr pairs), +0x20 16,952 bytes. MATCH_TEAM_KIT_SYSTEM:
  two MATCH_TEAM_KIT_INPUT (the loaded match's teams) and two colour-word pairs. GAME_STADIUM_MANAGER:
  +0x08 15,873 words pointing into an array of 16-byte items, +0x20 804 24-byte items (not
  polymorphic). TRANSLATABLE_MANAGER, MATCH_SYSTEM and STAT_DISTRIBUTION_MANAGER hold no vector in
  their first 0x100 bytes. Classes from the vtables of the first entries (13 Dec 2030, West Ham match
  loaded); the item fields are not decoded, and which of these are cleared after the match was not
  traced.
## Tests

`tests/test_match_state.py` (offline; the capture tests skip without the captures and the
installed plugin), `tests/test_match_state_live.py`, `tests/test_match_rating.py` (offline: helpers,
multiplier selection, a synthetic player) and `tests/test_match_rating_live.py` (mirror equal to the
emulated updater on both captures and the loaded match, component sums, momentum).
