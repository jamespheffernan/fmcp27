# UI handlers for players, club vision and scouting

`fm_live_mcp/fmdb/ui_recipes_person.py` reads the Player, Club Vision, Board, Supporters,
Finances (wages) and Scouting screens through the game's own UI handlers, on top of
`UiHandlerVM` (see `UI_HANDLERS.md`). Build 27.0.0.2493426, live save: Newcastle United,
manager Cesar Jules, 10 Dec 2030. Read-only: shipped code runs on copied memory.

Entry points:

| Function | Screen | Recipe |
|---|---|---|
| `player_status(vm, player)` | Player > Overview / Happiness / Promises / Transfer interest | `{'110 ': 28, 'dref': person id}` -> PERSON_UI_HANDLER; then the `ctrc` record -> CONTRACT_UI_HANDLER (type 19) |
| `club_vision(vm, club=None)` | Club Vision, Board, Supporters, Finances > Wages | `{'110 ': 28, 'dref': club id}` -> CLUB_UI_HANDLER; board members through PERSON |
| `scout_report(vm, person, manager)` | Player > Reports > Scouting | type 75, `{'Pers': person id, 'PbPY': manager person id}` |
| `read_record(vm, type, record, keys)` / `DataReader` | any database-record handler | data-key protocol (below) |

Person id = `1 << 24 | people index`; get it from the PERSON sub-object (ACTUAL_PLAYER
+0x388, player-staff +0x480, manager +0x548) with `vm.object_ref`. The player primary
object itself returns 0. Club id = table 3, team id = table 0x18.

## How the handlers select their object

The previous blocker ("record key that selects the person not found") is the key `'dref'`
(0x64726566). `DATABASE_RECORD_UI_HANDLER` reads it with 0x1B24A0 (`0x77E7D4` has-key,
`0x77F180` u32). Factory type 28 (0x218680) switches on the dref's table type
(0x218688, jump table 0x52E1D80): 1 -> PERSON family (0x219990), 3 -> CLUB_UI_HANDLER
(0x219A00), 0x18 -> TEAM_UI_HANDLER (0x219A3C), 2/7/19/28/47/58 -> base
DATABASE_RECORD. Type 28 with no dref makes no client, which is why the type table lists it
as a gap. Type 106 (SQUAD_SELECTION_PLAYER) is PERSON with a slot 4 thunk
(0x4DDC7C -> 0x376980) and one server override (key 'isse'); it takes the same record.

## Data-key protocol (PERSON, CLUB, TEAM, CONTRACT)

These handlers do not cache transferred inputs (TEAM_CONFIDENCE style). The front end
passes values in the fourth argument of `get_property`:

1. client slot 14 `(this, request, out vector<u32>)` lists the data keys a property needs
   (MoraleString 'dafe' -> ['Pmor']; HappinessPositives 'HPPo' -> ['PHsg', 'PRHP', 'Pclb',
   'Pipl', 'PmOD', 'Pnfo', 'Pspa', 'gDhI']);
2. client slot 13 `(this, u32 key) -> u32` names a data key whose value *is* the property
   ('NULL' otherwise; Morale 'Mora' -> 'Pmor', 'Pohl' -> 'Pohl'); slot 4 returns null for
   these, so `DataReader.get` returns the server value;
3. the server partner's slot 2 computes each data key;
4. the values go into a property bag (insert 0x43F72E4 `(bag, u32 key, typed*)`) and
   client slot 4 formats the property from the bag (lookup 0x43F899C).

With an empty bag slot 4 still answers with defaults ("Abysmal" morale, `[{'name':
'None'}]` lists): that is what the first probe of type 106 returned. `DataReader` returns
`Unavailable` when any data key fails, never a default.

State rule: data values stay in the committed baseline (computed once per handler);
the bag, request and every store of a get are discarded by pinning the baseline before
and restoring it after. Without that, reading HappinessTraining before
HappinessPositives emptied the latter (bag inserts copy typed values and touch the
variant pool, 0x56A4E90).

### Request parameters

Some getters read screen parameters through 0x77E228 `(request, path global, out,
inherit)`, which walks the UI context node at request+0x38 (hash map 0x56A4A98). Our
requests carry no context, so `DataReader.get(key, params={path_rva: int})` answers
named parameters: a code hook at 0x77E240 (after the prologue) sends a supplied parameter
to the shipped success tail 0x77E2CC with an int32 typed value built by 0x4403EC0.
Unsupplied parameters run the original code. Unicorn applies a range hook only to blocks
translated after it is added, so the hook flushes the translation cache of 0x77E228.

## player_status

Fields: name, morale (string and 0..20 value), overall happiness level (`Pohl`),
happiness positives/negatives (text + importance), training and international happiness,
playing-time happiness (text and level), hierarchy influence, promises (text, dates,
progress, the player's view), board requests, transfer status/value links, transfer
confidence (`Vvsx`: fee, wage, board and supporter reaction), interested clubs (active,
all, rumoured, with stance text), contract weekly wage; from CONTRACT: actual squad
status ("Regular Starter"), contract status and type, set for release.

Coverage: the default set is 47 keys (34 value, 13 unset for Gordon); 4-18 s per player
with contract (first player pays the page faults), 0 RNG draws. All 664 PERSON slot-4 keys
on one player: 293 value / 368 unset / 6 unavailable, 327 s (run before the baseline
fix; the unavailable keys are SecondPersonalAchievementsCount, SecondTeamAchievementsCount,
ThirdTeamAchievementsCount, ThirdPersonalAchievementsCount: null dereference;
FavouredClubs: `std::__next_prime` external; HumanTransferInOutList: VM heap exhausted).
Opt-in key `U4XF` HumanTransferRumours draws the RNG (126 draws) and took ~100 s.

Not delivered: agreed squad status (`iag9` reads "-") and CONTRACT wage ("N/A") with the
record PERSON returns (`Ctyp` 0, `PbPY` null, also with the manager id); `Pohl`/`Mora`
ints come from slot 13 passthrough; `HappinessRecentChange` and reactions are unset.

### Validation against the Squad screen

| Item | Screen | Read | Result |
|---|---|---|---|
| Very happy, first team | 23 | `Pohl` > 59 over the first-team roster: 23; CLUB `zCj2` HappyPlayersCount `cwnt` 23 | match |
| Very happy, club | 47 | CLUB `zCj2` `ptvl` 47 and TEAM data `nohp` 47; `Pohl` > 59 over all 66 club players: 48 | game key matches; per-player count +1 |
| Unhappy, club | 3 | TEAM data key `noup` = 3 | match (game key) |
| Unhappy, first team | 0 | not separated by any key read | not verified |
| Managerial support | Very good | TEAM `A1kN` ManagerialSupportFeedback `KfsX` "Very good" | match |
| Club atmosphere | Very good | `ClubAtmosphereFeedback` has no handler; TEAM `gTJS` level 6, data `Tdra` 60 | not verified |

The threshold comes from the game: the 'nohp' computation (CLUB object getter
0x1FAF4D8, loop at 0x1FB18F8) counts a player when the signed byte at +0x5A of the object
his virtual +0x3C0 returns is > 59 (0x1FB1974), skipping objects whose virtual +0x90
returns 5 and players whose virtual +0x4E8 is true. Those two exclusions are not
reproduced, which explains at most the +1. The unhappy predicate behind `noup`
(0x1FB2010) was not decoded; four reserves "are concerned" about playing time.

## club_vision

`ViOl` (VisionObjectiveList, 0xB9FAC) takes three request parameters: owner 0x56D1A08
(1 board -> data 'CvBo', 2 supporters -> 'Cvso'), filter 0x56D1A18 and flag 0x56D1A28.
Filter values mapped on this save: 0 all, 1 contract rules, 2 actionable without
contract rules, 3 actionable + culture, 4 culture, 5 competitions of the current season
(flag 1), 6 the screen's "Actionable" list, 7 as 5. Each objective: name (`cvon`), raw
importance 0..10 (`coip`), season (`Viys`), hint, category, id, setter, state, type,
linked competition. Importance words are a band table inferred from this save (1/3
Favoured, 4-6 Preferred, 7 Desired, 10 Required); 2, 8 and 9 were not observed.

Other fields: board and supporter culture text (`G4M5`, `aEhV`), board members (`TCsO`
data list -> PERSON `iSnm`, `b9r7` job title, `natY`), supporter influence (`CsbR`),
chairman status, the full wage summary (`6MU6`), happy players. 11 s; 16 RNG draws
(data `CvBo` 8, `Cvso` 8: objective text). 24 parameter answers.

### Validation (each ground-truth item)

Board, actionable (objective / importance): all 6 match in order and importance.
Board, culture: 4/4 match. Supporters, actionable: 2/2 match (Sunderland Desired, Europa
League Required). Supporters, culture: 5/5 match. Supporter influence Low: match.
Expectations (7): supporters' "all" list has 7: match.
5-year plan, current season: 4 of 5 match (Reach latter stages UCL Required, Qualify UCL
Required, EFL Cup Favoured, Community Shield Favoured); **"Challenge for the FA Cup /
Preferred" is missing** from every filter; later seasons present (2031/32 Challenge for
the PL title, 2032/33 Work towards winning the PL, 2033/34 Win the PL, 2034/35 Continue to
win the PL, plus "Cesar Jules' contract expires" 2032/33).
Judgements (On Course, Pleased, Not Judging, Reserving Judgement, Passed, Delighted, Very
Pleased): **not available**. Every objective's judgement byte (objective +0xB8, set as
`cvop` by 0xD564C -> 0xD8238) reads 6, and `aZDo` (0x1A26C88) is a linked name, not a
judgement. The board's per-objective evaluation was not located.
Wages: committed £258,727,924, budget £284,229,244, all six squad-status rows (count and
total) match exactly.
Board members: Al-Rumayyan Chairperson Saudi, Hopkinson Managing Director Canadian,
Reuben Director English, Alhagbani and Rezeeq Directors Saudi: names, roles and
nationalities match; year joined not read.

## scout_report

PLAYER_REPORT is cache style (inputs `anli`, `scri`, `scrp`, ~0.35 s; reading ~1 s; 0
RNG). On three players from the manager's report vector (HUMAN+0x110; +0x128 gave none: Burrows,
Gelhardt, Aasgaard): 33 values / 22 unset / 0 unavailable. Returned: recommendation
("Last Resort", "Only sign Gelhardt as a last resort."), grade, pros and cons with text
(e.g. "Strong penalty taker.", "Doesn't have the greatest jumping reach."), report date
and scout (`XwEJ`), analyst report state, CA/PA star ranges (MinV/MaxV), scouted
positions, best role, transfer info, training feedback, squad comparison. The handler
applies the manager's knowledge itself: ability is a range, unknown transfer data reads
"Unknown", own squad players are exact (MinV = MaxV), an own player reads "Scouting
Required".

## TEAM_CONFIDENCE fee (`K0qE`)

`K0qE` is the `cash` field (+0x30, int32) of the TRANSFER record; the entry builder
0x148C30 also sets GuaranteedFee `QhuE` (+0x34) and PotentialFee `lsUe` (+0x38). The
TEAM_CONFIDENCE list entry is built by 0x5B9740 from it (`cash` -> `K0qE` via int32
0x4403EC0). PERSON `Vvsx` (TransferConfidence) gives the same numbers: Huber 5,340,963,
guaranteed 0, potential 0; Riad 20,588,228, 0, 0. So add-on clauses are not in the figure.

Money is stored in GBP (GBP rate 1.0 in every year of the currency table), and the game
formats it to three significant figures (13,533,791 -> "£13.5M" in the server-built
transfer headline). So 5,340,963 would read £5.34M; the screen's £5.25M is a different
number. Both sellers use other currencies: Huber came from FC Zürich (Swiss Franc, current
rate 1.0884/GBP), Riad from VfL Wolfsburg (Euro, 1.1571/GBP). The ratios 0.983 and 0.996
differ, so no single rate explains both. The likely explanation: `K0qE` is the GBP amount
fixed at the transfer date and the screen converts the fee agreed in the seller's
currency at today's rate. This is not verified: the TjWO formatter runs in GameAssembly,
not the plugin, and the original-currency amount was not found. Present `K0qE` as "fee
recorded at signing, GBP" and do not expect it to equal the screen.

## Blockers

* Judgements of vision objectives: see above (0xD564C reads objective +0xB8 = 6).
* FA Cup objective: absent from `CvBo`; not located.
* CONTRACT agreed squad status / wage: "-" / "N/A" through the `ctrc` record.
* `noup` unhappy predicate (0x1FB2010) not decoded; `nohp` exclusions (virtual +0x4E8,
  +0x90 == 5) not reproduced.
* Unresolved text tokens: some strings keep the game's `person#1` / `nation#1`
  placeholders (e.g. "Managerial Supportperson#1"); the substitution needs front-end data.
* TEAM_CONFIDENCE `TjWO` failed once ("write to shipped code") when read after many
  PERSON reads on the same long-lived VM; a fresh VM reads it (existing live test).
  Long-lived VMs mix pages copied at different times.

## Edits to shared files

None: the protocol, parameter hook and recipes live in `ui_recipes_person.py`.
