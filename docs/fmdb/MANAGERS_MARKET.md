# Market manager singletons

`fm_live_mcp/fmdb/sources/managers_market.py` turns thirteen native manager singletons into collection
tables; `fm_live_mcp/fmdb/mgr_walk.py` holds the walker. Numbers are from the Newcastle career on
13 December 2030, read on 12 November 2026 (load average 4 to 11).

## How each manager is read

Each manager is a plugin global that holds a pointer to one heap object. `mgr_walk.root` reads the
pointer and refuses the object unless its first word is the plugin base plus the manager's primary
vtable. Containers are libc++ `std::vector`s; `mgr_walk.vector` checks begin <= end <= capacity and the
element stride. Element fields are declared per table as (column, offset, kind, meaning) and decoded
by plain reads: record pointers are resolved to snapshot `idx` values through the live database tables
(-1 when the pointer is not a record of the declared table), packed dates use the day bits only (the
seven bits above the day are flags), `pidx` fields are u32 PERSON table indexes checked against the live
table. Nothing is emulated and nothing is written.

Object sizes come from the constructors (the size passed to operator new, or the fields the constructor
initialises). Element layouts come from the functions named in each column's meaning. Where no function
was traced, the meaning gives the offset and type and says the role is inferred, or "not established".

All tables are lazy and use content invalidation: the fingerprint is the decoded rows themselves
(0.02 to 0.28 s per check).

## What each manager holds

| Manager | Root | Object | Containers (live count) | Table |
|---|---|---|---|---|
| AGENT_MANAGER | 0x56B6188 | 0x68 bytes (0x250FE84) | +0x08 empty; +0x38 86 consecutive u32 values (an id range); +0x50 empty | inventory only |
| CONTRACT_MANAGER | 0x56A64C8 | about 0x118 bytes (0x25F880C) | +0x18 156 {person index, date}; +0x60 2 objects (club, vector); +0x78 498 {person index, date, code}; +0x90, +0xA8, +0xC0, +0xD8, +0xF8 empty on this date | `contract_manager_entry` |
| PLAYER_BUYIN_MANAGER | 0x5734818 | 0x18 bytes (0x250FE84) | none: two vtables and a message id. Player buy-in is chemistry state on the players | inventory only |
| SCOUT_MANAGER | 0x56A6AB0 | (0x2AA27C0) | +0x20 7 scouting assignments; +0x80 84 dated player entries | `scout_player_assignment`, `scout_manager_entry` |
| JOB_CENTRE_MANAGER | 0x56A57A0 | 0x30 bytes (0x278A5E8) | +0x18 143 JOB_ADVERT | `job_advert` |
| FEEDER_CLUB_MANAGER | 0x56B6190 | 0x48 bytes (0x266CB74) | +0x18 empty; +0x30 156 groups of clubs (349 members) | `feeder_club_group` |
| BOARD_TAKEOVER_MANAGER | 0x56B5430 | 0x48 bytes (0x25E6D8C) | +0x18 25 club entries; +0x30 | `board_takeover_entry` |
| FINANCE_MANAGER | 0x56B5428 | 0x30 bytes (0x268ACAC) | +0x18 -> stadium groups (1 entry); +0x20 -> 1 db::FACILITY_UPGRADE; +0x28 -> one 0x90-byte element of six vectors | `finance_stadium_entry`, `facility_upgrade` |
| FAN_DAY_MANAGER | 0x5732638 | (0x1AC400C) | +0x60 36, +0x80 8, +0xA0 12, +0xC0 8, +0xE0 10, +0x100 10 entries | inventory only |
| PITCH_CONDITION_MANAGER | 0x56B6180 | 8 bytes (0x250FE84) | none: the object is its vtable. Pitch condition is held elsewhere | inventory only |
| TRAINING_CAMP_MANAGER | 0x56A8700 | (0x2C89EAC) | +0x18 171 camps | `training_camp` |
| BACKROOM_ADVICE_MANAGER | 0x56A4F40 | (0x25D6598) | +0x20 30 {FourCC, vector<u8>}; +0x38 79 entries with two typed values; +0x50 118 dated club entries | `backroom_advice_entry` |
| HUMAN_NON_PLAYER_MANAGER | 0x56A6890 | (0x26DCB80) | +0x18 1 pointer into the human manager's PERSON record (class HUMAN_NON_PLAYER, +0x20) | `human_non_player` |

`market_manager_container` lists every container above with its live element count and the table that
decodes it. The ledger's guesses are corrected here: PLAYER_BUYIN_MANAGER has nothing to do with
transfers, and PITCH_CONDITION_MANAGER and PLAYER_BUYIN_MANAGER hold no state.

## Tables

| Table | Rows | First: CPU s (wall) | Manager view | Checked against |
|---|---:|---:|---|---|
| `market_manager_container` | 35 | 0.00 (0.01) | never | |
| `job_advert` | 143 | 0.25 (0.49) | public | contracts: none of the 50 "Manager First Team" adverts (job code 16) has a main-contract job-16 holder at the advertising team; 107 of 133 status-0 adverts are vacant, 9 of 10 status-1 adverts have a holder |
| `scout_player_assignment` | 7 | 0.10 (0.30) | own club | the Scout Players list (SCOUT_PLAYER_PRIORITIES_UI_HANDLER key sj22, `fm_get_scouting`): 7 of 7 players, same order |
| `scout_manager_entry` | 84 | with the above | own club | 11 of the 84 players are among the 60 recommended players of the recruitment focuses |
| `contract_manager_entry` | 654 | 0.00 (0.00) | never | 497 of 498 `+0x78` entries index a player or player-staff record; 353 of those 497 have a main contract expiring by 30 June 2031 |
| `feeder_club_group` | 349 | 0.01 (0.01) | public | `club_affiliate`: 182 of the 193 non-first members are current affiliations of the group's first club |
| `board_takeover_entry` | 25 | 0.00 (0.00) | never | |
| `training_camp` | 171 | 0.07 (0.18) | own club | |
| `backroom_advice_entry` | 118 | 0.00 (0.04) | own club | |
| `finance_stadium_entry` | 1 | 0.01 (0.03) | own club | |
| `facility_upgrade` | 1 | 0.10 (0.12) | own club | element class by RTTI |
| `human_non_player` | 1 | 0.08 (0.22) | never | the element lies inside the PERSON record of class HUMAN_NON_PLAYER |
| `contract_offer` | 0 | 0.07 (stdio) | own club | |
| `contract_manager_list` | 2 | 0.07 (stdio) | never | |
| `agent_demand` (market_state.py) | per named player | ~0.5 s a player | public | the panel's lines agree with the object's wage and contract-end fields (live test) |

The first figure of `facility_upgrade` and `human_non_player` includes the RTTI inventory of the plugin
(`ledger.rtti_inventory`) that the class column needs, built once per engine cache.

## Labels and their evidence

`job_advert` (JOB_ADVERT, vtable 0x55F3F90, 0x40 bytes, created in 0x278AF00): the team (+0x20) is the
create argument; 0x2500E50 sets the competition (+0x28, the team's +0x50), a u16 from the competition
(+0x30) and the league position (+0x32, 1 + the index 0x3AA90B4 returns); +0x34 is the current date at
creation; +0x38 is the creation date plus a few days and becomes the current date when 0x332FA78 sets the
status (+0x3E) to 2; +0x3C is the job code, the contract job enum (see the check above); `job_title`
converts it with `staff_jobs` and the team type. The vector at +0x08 is empty on every advert.

`scout_player_assignment`: player +0x00, scout +0x08 (a club scout on every entry: inferred to be the
assigned scout), team +0x10 (the human team), date +0x20. `scout_manager_entry`: player +0x00, team
+0x10, two dates +0x28/+0x2C; what the list is for is not established.

`contract_manager_entry`: `+0x18` entries are {u32 PERSON index, date}, all dated within a week of the
current date; `+0x78` entries are 16-byte {u32 PERSON index, date, u32 code, u32}. The dates are on or
after the current date and most players' contracts end at the season's end: inferred to be scheduled
contract events. Codes 5, 7, 14, 18, 22 are not mapped.

`feeder_club_group`: one vector<CLUB*> per group; the first club and the clubs it is affiliated with
(Manchester City's group holds New York City FC, Melbourne City FC, Lommel SK, Mumbai City FC, ESTAC
Troyes, Palermo, Bahia, NYCFC Academy and Girona). The game holds 16,523 affiliations in club records;
the 156 groups here are a subset whose selection rule is not established.

`training_camp`: team +0x00, city +0x20, local region +0x28, nation +0x30, two dates +0x38/+0x3C
(inferred start and end). `board_takeover_entry`: club +0x00, the number of db::CLUB_VISION_OBJECTIVE
objects in the vector at +0x08 (counted, not decoded), two dates, two u32 values. `backroom_advice_entry`:
club +0x00, date +0x10, two u16 values, the count of the vector at +0x18. `finance_stadium_entry`: club,
stadium, date +0x18 and three u32 values; the capacity reading of +0x20 and +0x30 is inferred.
`facility_upgrade`: club +0x08 and date +0x10 of each db::FACILITY_UPGRADE.

## Round 3: finances, sponsors, loans and affiliations (`sources/market_state.py`)

The Finances screens are not stored in FINANCE_MANAGER: the game builds them in CLUB_UI_HANDLER (the
DATABASE_RECORD handler, type 28, for the club). `market_state.py` runs that handler for each managed club
in the UI VM on copied live memory (`history_read.UiReader`, the route `fm_ui_read` and the sweep use) and
shapes its keys into tables. Numbers from 12 November 2026, Newcastle United (club 414), 13 December 2030;
load average 8 to 10.

| Table | Rows | First query (wall) | Manager view | Keys |
|---|---:|---:|---|---|
| `club_finance_breakdown` | 152 | 0.7 s (the handler, once for all five tables) | own club | IncomeBreakdown{This,Last}{Month,Season} (17 categories), ExpenditureBreakdown... (21) |
| `club_finance_month` | 360 | with the above | own club | FinanceBalanceHistory, TotalIncomeGraph, TotalExpenditureGraph, FinanceWage/ScoutingExpenditureHistory, FinanceTransferBudgetRemainingHistory: 60 months, Dec 2025 to Nov 2030 |
| `club_sponsorship` | 11 | with the above | own club | SponsorshipsData |
| `club_debt_loan` | 2 | with the above | own club | DebtsAndLoansData |
| `club_affiliation_detail` | 3 | with the above | own club | AffiliatedClubsDetailsList: the game's description of each link and its sentences on what each side gets |
| `club_affiliation` (view) | 16,523 | 16 s the first time (the club list column Cafl is computed on demand for every club), then 0.8 s | public | club.current_affiliations |

All are lazy; the finance tables use game-date invalidation. Amounts are pounds (item key ptvl); display
columns keep the screen's own formatting. Labels of item keys are the UI registry's where it has one
(Percentage, MonthToMonthPercentage, SponsorshipValuePerSeason, OriginalDebt, RemainingDebt,
PayablePerMonth, GraphPointY); the fourth loan amount (key " juQ") has no registry label.

Affiliations. `club_affiliation` labels every item of the editor list Cafl with the editor catalog's field
names and the Affiliation Type enum (CAfT); code 21 has no catalog label (406 links), its `type` is NULL.
Each link is stored on both clubs (Is Main Club true on the parent's copy), except Regional Academy links
(95, parent side only): 16,523 = 2 x 8,214 + 95. Why FEEDER_CLUB_MANAGER holds only 156 groups: the groups
are parents and the clubs they share a board with. All 175 parent-side Normal Affiliated Club and Feeder Team
links with Same Board lie inside a group; 20 of the 196 group links lack Same Board; outside the groups no
such link has it. The groups are therefore multi-club ownership groups (Manchester City's holds the City
Football Group clubs). The selection rule is inferred from the data; the code that fills +0x30 is not traced.

## Round 4: agent demands, the contract manager's queue and offers

### `agent_demand`: what a player would ask for (market_state.py)

The agent demands panel (PERSON_UI_HANDLER key PlayerAgentDemands, '1NxK') is drawn by the client getter
0x3D9920 (case 0x3DAA40) from three server data keys: 'PPaD' (the demands object, serialised), 'Ptoa'
and 'PypR' (round 3 read the first as 'Ptao': the immediate is 0x50746F61, 'Ptoa'). The getter calls
0x3E9618 -> 0xD6D1B0, the line writer: for each demand it calls GAME_AGENT_PLAYER_DEMANDS slot 11
(0x1FA0AE0), a wrapper that tail-calls 0x24419A4, a 248-case switch on the line's type code that words
the line. So 0x24419A4 is the wording function, not the computation (the round 3 confusion). The server
answers 'PPaD' in GAME_PLAYER slot 9 (0x20BB788, case at 0x20BEA20) only when the human's store holds a
demands object for that player (vector at human object +0x388 -> +0xCC8, searched at 0x20BEB10); otherwise
the value is empty, which is why round 3 read empty records for Gordon and Caicedo.

The computation is 0xD6B0E0(obj, context, player, club, w4, 4) on a 0x210-byte object (ctor 0xD6AE68;
the game's wrapper 0x12DE8DC allocates, computes and stores it). `player` is the person record's vtable
+0x668 result (as the daily pass passes it at 0x260D47C); `club` must have a human manager on its first
team. `agent_demand` runs ctor and computation in the UI VM on copied live memory, serialises the object
with 0x204DCA4 (what the server does at 0x20CCA2C) and reads PlayerAgentDemands with 'PPaD' answered by
it: every line is the game's own wording. Context 2 (the scouting context of 0x396E170, also deadline-day
agent offers 0x12DD648) is used; 3 is the contract manager's daily pass, 1 the transfer-status context
(0x276EEA8, a shorter set of lines). Object fields the line writer reads: agent +0x1B8, person +0x1BC,
player's club +0x1C0, fee range +0x1C4/+0x1C8 (pounds), wage range +0x1D0/+0x1D4 (pounds a week), offer
date +0x1F0, contract end +0x1F8.

Rows are computed for the players a statement names (at most 60; `WHERE person_idx = ...`), about 0.5 s a
player (9.4 to 11.5 million instructions); the computation draws 300 to 380 random numbers, and the same
lines came out under the copied, private and isolated random states. Measured on 12 Nov 2026 (load
average 9 to 12) through the MCP stdio server: Caicedo and Gordon in one statement 23.9 s including the
snapshot rebuild for the new table; a statement selecting by `person.name` took 198 s (the name filter
is computed for the dry run), so select by `person_idx`.

| Player | Lines (13 Dec 2030, for Newcastle) |
|---|---|
| Moisés Caicedo (Chelsea) | Interested. Chelsea will want between £180M and £241M (next-sale clause); star player; wage £21.71M to £26.63M a year; contract until 30 June 2033; win the Champions League in the next couple of seasons; would likely gain a work permit |
| Anthony Gordon (Newcastle, renewal) | Very Interested. Among the most noteworthy players; wage £16.62M to £20.59M a year; contract until 30 June 2033; left winger, winger role |
| Alexander Isak (Liverpool) | Would not be interested in joining Newcastle (prefers a club better known in Europe); Liverpool unwilling to sell |

Not in the panel: bonuses, clauses and the agent fee. They are asked for in the negotiation itself
(CONTRACT_EDIT_SESSION); the contract part of the demands object (+0x18, initialised by 0x14AD870,
serialised by 0x14B82C0) is not decoded. Next route: the function that opens a contract negotiation from
a demands object (callers of 0xD6AE68 that also build CONTRACT_EDIT_SESSION, for example 0x3028ADC and
0x302BEC8) run in the VM, then the contract_negotiation screen on that session.

### CONTRACT_MANAGER +0x78: deferred contract terminations

The +0x78 entries are 12 bytes {u32 index, packed due date, u8 reason} (allocated with 0xC bytes by
0x2624C04 and 0x2624D5C; the reader's former `u32_0c` was past the allocation). The daily pass 0x260AFA4
sorts the queue (0x264CEA8) and pops each entry whose date has arrived (0x260CC38): reason 7 indexes the
club table (global 0x56D2D28) and goes to 0x2623CE8 (CLUB_RETAINED_LIST_PUBLICATION_NEWS,
PLAYERS_ABOUT_TO_BE_RELEASED_WARNING_NEWS); every other reason indexes the person table and goes to
0x26248BC(manager, contract, person, reason), the contract-termination function. 0x2624C04 queues reason
7 (retained-list publication); 0x2624D5C queues the reason it is given and is called only from 0x262AF58,
the step of 0x26248BC that defers a termination that cannot happen yet (30 days later, or at a computed
date). The reason is therefore what the original caller passed to 0x26248BC. Callers with a constant
reason: 13 (0x26004AC, contract offer accepted: HUMAN_NON_PLAYER_CONTRACT_OFFER_NEWS), 14 (0x25A1A18),
34 (0x2A96D60, retirement: REGENERATION_RETIRED_NEWS), 33 (GAME_SQUAD_MANAGER slot 3), 16 (0x2A638F4,
youth trial contracts), 29/30 (0x2D2645C, renewal suggestion / loan back), 20, 17 and 1 (0x26122B4, mutual
termination and youth pro-contract paths). Reasons 5, 18 and 22 reach 0x26248BC through callers that pass
a variable (0x19BE920, 0x26122B4); their names are not established. On 13 Dec 2030: 18 on 458 entries
(due 14 Dec 2030 to 24 Feb 2031), 14 on 35, 22 on 3, 5 and 7 on one each (7: Shanghai Shenhua).

`contract_offer` exposes +0x90 (person +0x10, club +0x18, status +0x24): 0 rows on 13 Dec 2030.
`contract_manager_list` exposes +0x60 (two per-club objects: clubs 17999 and 1243, vectors of 1 and 3) and
+0xD8 (empty).

`transfer_offer` remains the store of club-to-club offers.

### Field meanings

`job_advert`: `human_placed` (+0x3D, formerly `flag_3d`) is the create call's flag: 1 from
PLACE_JOB_ADVERT_ACTION_UI_HANDLER_SERVER slot 7 and ADD_JOB_ADVERT_TO_REPLACE_NON_PLAYER_RESPONSE slot 11,
0 from the AI callers (0 on all 143 adverts). `closing_date` (+0x38, formerly `date_38`) is the date
0x278B948 returns at creation (AI adverts get three more days) and becomes the appointment date at status
2; on or after `created` on all 143. The tables no longer show native element addresses (`object`).

### Other clubs' affiliation type 21

The game's language file (`example.ltf`) lists fifteen names with the comment "club affiliation type";
fourteen are the editor labels already used. The fifteenth, "Women's Club" (KEY-598374, feature FM-20375,
the same feature as "Opposite Gender Club", code 25), has no code in the editor catalog. Code 21 is the
only code without a label, but its 406 parent-side links join clubs to local and youth partners
(Beijing Guo'an to five Beijing clubs, SKN St. Pölten to Union Sportclub Markersdorf, Palmeiras to
Ibrachina), not to women's sides, so the pairing is not supported and `type` stays NULL. The plugin has no
immediate of any type-name key except 293066 and 293074 (0xEBD7C0): the code-to-name mapping is not in
code. Next route: the editor's enum definition in `editor.fmf` around CAfT, which may carry hidden values.

## Not read yet, and the next route

* Meanings not established: job advert +0x30 (u16 from competition +0x188); contract-termination reasons
  5, 18, 22 (variable callers 0x19BE920, 0x26122B4); CONTRACT_MANAGER +0x18 entries; scout entry +0x80
  list; takeover u32 values and dates; camp +0x48/+0x4C; advice u16 values. Next: for each, the function
  that writes the field (the creator) and the news item that consumes it (BOARD_TAKEOVER_*_NEWS,
  TRAINING_CAMP_*_NEWS, BACKROOM_ADVICE_* classes).
* Containers counted but not decoded: AGENT_MANAGER +0x38; BACKROOM_ADVICE_MANAGER +0x20 and +0x38;
  FINANCE_MANAGER +0x28; every FAN_DAY_MANAGER vector; BOARD_TAKEOVER_MANAGER +0x30; the vectors of the
  CONTRACT_MANAGER +0x60 objects.
* Agent demands: bonuses, clauses and agent fee (see above). Squad manager records (task of this lane in
  MATCH_STATE.md) were not reached in round 4.
* Manager view: the policies are declared; the manager connection exposes collection tables only once the
  manager view adds masked views for them (COLLECTIONS.md).

## Facts to check on a game screen (13 December 2030)

* Moisés Caicedo's profile, agent demands for Newcastle: Interested; Chelsea want £180M to £241M; wage
  £21.71M to £26.63M a year; contract until 30 June 2033; wants to win the Champions League soon.
* Anthony Gordon, contract renewal: wage £16.62M to £20.59M a year, until 30 June 2033, left winger role.
* Alexander Isak would not be interested in joining Newcastle; Liverpool unwilling to sell.
* Shanghai Shenhua: a retained-list event (reason 7) is due on 16 Dec 2030; the news of their retained list or
  of players about to be released should follow on that day.

* Recruitment > Scouting > Scout Players: Tayyarcan Alaeddinoğlu, Mads Enggård, Andrey Borodin, Ismaël
  Gharbi, Lennart Karl, Willy Kambwala (scout Moritz Steidten) and Moisés Caicedo (scout Peter Clark).
* Job centre: Athletic Club advertised for a first-team manager on 12 December 2030; Córdoba C.F. on
  9 December; KVC Westerlo and Royal Antwerp FC on 7 December.
* Atlanta United FC: a facility upgrade completing on 4 June 2031.
* Al-Nassr: work on King Saud University Stadium completing on 1 July 2032 (20,315 to 26,004, inferred
  as capacities).
* Finances > Income, this season (Newcastle): Players Sold £205.8M (55%), Sponsorship £181.6M (48%), TV
  Revenue £77.8M (20%), Investments £55.1M, Season Tickets £40.7M; this month Sponsorship £95.73M.
* Finances > Sponsors: Main Kit £25M per season, 5 years, to 27 May 2034; Kit Manufacturer £21.25M, 5 years;
  Shirt Sleeve £9.63M, 7 years; Club Membership (53,749 members) £2.48M.
* Finances > Debts: Mortgage Loan, original £40.8M, remaining £11.17M, £586K a month, 1 Dec 2025 to
  29 Nov 2032.
* Newcastle's affiliations: Larne ("Financial benefits for both teams": Newcastle have first option to buy
  Larne's players, long-term deal, shared scouting) and Ashington ("A mutually beneficial relationship"; the
  link ends if the clubs play in the same division).
* St. Pölten's club profile: AKA St. Pölten NÖ, "A local partnership in which players are loaned."
