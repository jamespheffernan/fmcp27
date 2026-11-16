# People-side native managers

Seventeen native manager singletons that hold squad, morale, dynamics, development, injury and honours state, and the people state their screens show. Code: `fm_live_mcp/fmdb/mgr_walk_people.py` (layout, live checks), `fm_live_mcp/fmdb/sources/managers_people.py` (eight manager tables) and `fm_live_mcp/fmdb/sources/people_state.py` (`promise`, `player_attribute_history`, `squad_hierarchy`, `social_group`, `player_happiness_reason`, `player_concern`). Tests: `tests/test_fmdb_managers_people.py`, `tests/test_fmdb_people_state.py` (offline) and the matching `*_live.py` files.

## How a manager is read

The world constructor `0x250FE84` creates each manager with `operator new(size)` and either calls its constructor or stores the vtables inline, then writes the object pointer to a global in the plugin's data segment. That allocation size bounds the object: nothing past it belongs to the manager. Every manager starts with its primary vtable, a second vtable (the base at +8) and a 32-bit id at +0x10.

For each manager the walker reads the global, checks that the object carries the class's RTTI vtable, reads the whole object, and checks each declared container:

- a libc++ vector is (begin, end, capacity) with begin <= end <= capacity, 8-aligned heap pointers and at most 64 MB;
- a libc++ map or set is (begin node, root, size), with the begin node pointing at the header when empty.

Elements of pointer vectors are classified by the vtable of the object they point at (Itanium RTTI name) or, for database records, by the table whose pointer list holds them. All reads are plain reads. Nothing is emulated except during the investigation described below.

## What each manager holds

Sizes come from the allocation at the address given. Element counts are from 13 Dec 2030 on the reference save.

| Manager | Bytes (alloc site) | Holds |
| --- | --- | --- |
| INTERACTION_MANAGER | 0x160 (0x2510508) | +0xF8: 1,770 interaction items (see below). +0x18..+0xC0: eight lists of 0x90-byte records (9,169 / 378 / 620 / 177 / 3,384 / 3,081 / 256 / 1,097); 91 code sites take the address of +0x18. +0xD8: 622 team-meeting comment rule objects (`TM_*` classes). +0x110: 6,823 records of 0x78 bytes, read by the person screen's TransferConfidence and SupportersFeedback getters. +0x128: empty vector. +0x140: 5,280 bytes of inline records. +0x158: a counter. |
| MORALE_MANAGER | 0x30 (0x2510044) | Five 32-bit values at +0x18..+0x28; no containers. |
| DISPUTE_MANAGER | 0x30 (0x251020C) | Three words at +0x18..+0x28, zero on this save; no containers. |
| DYNAMICS_PIVOTAL_MOMENTS_MANAGER | 0x50 (0x25106F0) | Two maps (+0x18, +0x30), both empty on this save, and a packed date at +0x4C. |
| TEAM_TALK_MANAGER | 0x48 (0x2510394, inline) | Two maps (+0x18, +0x30) with one entry each. |
| TEAM_BLEND_MANAGER | 0x18 (0x25102F0) | No instance state: vtables and id only. |
| AWOL_MANAGER | 0x60 (0x2510124) | +0x18: 36 pointers into an array of 24-byte records. +0x30: empty. +0x48: one pointer. |
| PERSON_PROGRESSION_MANAGER | 0x18 (0x2510450) | No instance state: vtables and id only. |
| INJURY_MANAGER | 0x150 (0x25100A4) | +0x70: 1,825 injury cases (see below). +0xB8: 1,086 records; the person screen's InjuryRiskFactors getter reads them at +0x4. +0xD0: 61,925 16-byte records from 2028-11-30 to 2030-12-13 for 1,082 people (523 of them clubless, 332 retired); role not established. +0x88, +0xA0, +0x100: empty. +0x31 is read by MatchLoadDescription. |
| REGENERATION_MANAGER | 0x1B0 (0x2510064) | Newgen templates: `db::PLAYER_HEIGHTS_TEMPLATE` lists (+0x20: 74, +0x38: 16), `db::NON_PLAYER_TENDENCY_TEMPLATE` (+0x68: 2,619), and other generation tables (+0x50, +0xA8, +0xC0). |
| RETIREMENT_MANAGER | 0x118 (0x2510664) | +0x18 (220) and +0x30 (909): per-person, per-season entries (see below). +0x78 and +0x90: their sorted (person index, pointer) indexes, which the person screen binary-searches. +0x108: the `OBJECT_STORAGE<RETIRED_PERSON_DATA>`. |
| AWARD_MANAGER | 0xD8 (0x25101AC) | +0x18: 413 award-period objects (YEAR 280, TEAM 61, GOAL 33, MONTH 25, CLUB 14 `_AWARD_DATA`). +0x30: 206 `db::AWARD` records. +0x48: 54 entries; +0x90: 228 entries. |
| HALL_OF_FAME_MANAGER | 0x48 (0x251024C) | +0x18: 6,357 managers' Hall of Fame entries. +0x30: the human manager's own entry. |
| ACHIEVEMENTS_MANAGER | 0x20 (0x2510470) | No containers; +0x18 points into the image (a static table). |
| OFFICIAL_STATS_MANAGER | 0x20 (0x1AC4358) | No containers. Created by 0x1AC400C, not by the world constructor. |
| SIMULATED_STATS_MANAGER | 0x78 (0x251022C) | +0x48 (18,523) and +0x60 (4,436): `db::TEAM` pointers. +0x18 (43) and +0x30 (1): records. |
| STATS_OUTPUT_MANAGER | 0x8 (0x251026C) | No instance state: vtable only. |

### Attribute history

`PERSON_PROGRESSION_MANAGER` is a 24-byte object with no fields after its id; it stores no history. The history the development screen draws is stored per player and read by the person server:

- `AbilityProgressHistory` (APrH) on `PLAYER_TRAINING_UI_HANDLER` (get 0x41C3A8, compare 0x41C788) and on `PERSON_UI_HANDLER` (0x3D6D88 / 0x3DA500) is computed from the data key `PpAH`, which `PERSON_UI_HANDLER_SERVER` builds in 0xD3E6F0 (case at 0xD3EB3C).
- That server first asks 0x11B5510 for the context variable `Hhum`: the human the screen is drawn for, looked up in the vector at global 0x56D38C0 (entries `{u32 key, typed*}`). The live vector is empty between UI calls, which is why every sweep binding returned null. The reader gives the VM copy one entry, a RECORD `{'dref': human UI id}`, after the handler is built. Nothing is written to the game.
- The server then checks the human's club against the player's (0xD3EB4C..0xD43930). Players of other clubs come back null: the game's own fog of war.
- The value is a record `{disa, atrs: [{valu, atrs: 47 bytes, srTT: 3 bytes}, ...]}`, oldest first. In memory each snapshot is a 0x44-byte record: the 47 attribute bytes at +0x0, `valu` at +0x3C and a u32 at +0x40. The server loop at 0xD472A0..0xD472F4 reaches the records through the club object (+0x18 vector), then a per-player object (+0x18 vector of record pointers), and formats each record in 0xD5A270. On the reference save, Miley has 18 snapshots at 0x44-byte stride, Diouf has 5 and the 66 squad players read have 5 to 18 each.
- Byte i of a snapshot is native attribute field i (`knowledge_codes.FIELDS` order: the 11 goalkeeping fields, then technical, mental and physical fields). The newest snapshot equals the editor getter `PDxx` for all 47 attributes of 5 players (235 of 235). Each index also matches one PLAYER record offset on all 66 players read.
- `valu` is the list APrH returns (on Lewis Miley, 18 values). Its units are not established: the newest value is 207 to 224 times current ability on 5 players. The u32 at +0x40 and the `srTT` bytes are not decoded (`srTT` is `01 xx xx`; on Anthony Gordon `xx` is 0x10 in May to July 2030 and November to December 2030 and 0x11 or 0x12 otherwise; meaning not established).
- No snapshot date is stored: there is one snapshot per month and the newest stands for the current month. The history getter (PLAYER_TRAINING_UI_HANDLER 0x41C800..0x41FEE4) takes a window start (`PcSd`, default the game date minus 11 months), counts whole months to the game date with 0x42ECC1C and keeps the newest max(months + 1, 6) snapshots. Emulated on their own: 0x42ECC1C(2030-04-10, 2030-12-13, unit 1) = 8, (2029-12-13, 2030-12-13) = 12; 0x42EC72C(2030-12-13, 11) = 2030-01-13. The table's `month` column is the game month minus (entries - 1 - entry).

### Promises

The Promises screen is `PERSON_UI_HANDLER` bound to the human manager. Its keys are not attributed to any class in the registry because get_property hands them to the helper 0x3C7CCC: `HumanActivePromisesMadeList` (zWLF), `HumanPlayerPromises` (cyPm), `HumanCompletedPromisesMadeList` (vP71), `HumanBoardPromises` (tcoS), `HumanOtherManagerPromises` (bfN3), `HumanActivePromisesCount` (tIxI). The helper formats the server data keys `Hppm`, `Hmpm` and `Hbpm` through 0x441638, which also serves the row keys (`InteractionPromiseTitle` qEjH, `...Description` Iv5a, `StartDate` PcSd, `EndDate` Pced, `...StatusText` adP2, `...Ongoing` dxI2, `...DurationText` HuBD and others). The person-side `PromisesMadeByManager` (Pmbm) also reads: Miley returns his one promise and Diouf his. The earlier empty result was not reproduced.

Each screen row is one INTERACTION_MANAGER +0xF8 item. The player is +0x20 and the human is +0x18 on manager-made items; the start is +0x38 and the end +0x3C. The u16 at +0x4E is the promise kind. The title formatter 0x24419A4 dispatches on it: kind - 1 indexes the u16 table at 0x53B90A6 (248 entries), each target loads a translation id into w1 for 0x43DB8B8, and the English text comes from the language file. 135 kinds have a title, for example 1 "Fair increase in playing time", 2 "Offer a new contract", 3 "Sell player", 16 "Will send player on intensive language course", 25 "Find loan move for player", 53 "Abandon plans to retire at end of season", 57 "Don't sell player", 74 "Register in [comp] squad", 243 "Increase playing time to ... upon return from loan". Kinds 7, 9 and 10 go to the default branch 0x2443BFC, which has no title of its own.

On 13 Dec 2030 the screen lists 4 active promises and no completed, board or other-manager promises:

| Player | Kind | Title | Made | Deadline | Status text |
| --- | --- | --- | --- | --- | --- |
| Lewis Miley | 25 | Find loan move for player | 2030-11-04 | 2031-02-04 | Pleased that efforts to find him a loan move are on track to succeed |
| Chema Andrés | 1 | Fair increase in playing time | 2030-11-07 | 2031-01-06 | Pleased with his playing time |
| Jay Robinson | 1 | Fair increase in playing time | 2030-11-24 | 2031-01-23 | Hoping that his playing time will improve soon |
| El Hadji Malick Diouf | 1 | Fair increase in playing time | 2030-12-12 | 2031-02-10 | Looking forward to more playing time within the next few months |

How this compares with the hand-built tools: `fm_get_player_concern_history(include_promises=true)` reads the same items from each player's own vector (PLAYER +0x278 +0xA8), with the same kinds and dates. It also holds a kind-7 item dated 2030-07-31 to 2031-01-27 for Robinson and Andrés. The screen does not list that item, and 14 Newcastle players have one like it. The hand-built tool has no titles or states. `fm_get_player_status` reads Pmbm through the same handler. Newcastle's seven kind-16 items have the player at +0x18 and the human at +0x20, the reverse of manager-made items, and appear on no screen list read so far.

## Tables

All eight tables are lazy: each is built on first reference and rebuilt only when its fingerprint (manager object bytes plus the element bytes it reads) changes. Times are first references through `fm_db_query` on 13 Dec 2030, with a load average of about 6.

| Table | Rows | First reference | Manager view |
| --- | --- | --- | --- |
| people_manager | 17 | 0.8 s (including the walk) | never: internal structure |
| people_manager_container | 58 | 0.7 s | never |
| people_manager_element | 128,049 | 1.0 s | never |
| interaction_item | 1,770 | 0.9 s | own club, through `team_28_club_idx` / `team_30_club_idx` |
| award_schedule | 413 | 1.0 s | public |
| hall_of_fame_entry | 6,358 | 0.8 s | public |
| injury_case | 1,825 | 0.7 s | public |
| retirement_entry | 1,129 | 0.7 s | never: plans are internal until announced |
| promise | 4 | 2.1 s (one handler read per human) | own club (`club_idx`) |
| player_attribute_history | 18 per player at most | under 0.1 s per player after a 0.5 s VM build | own club (`club_idx`); the game itself returns nothing for other clubs |
| squad_hierarchy | 26 | 1.65 s through MCP (one TEAM handler read, shared with social_group) | own club (`club_idx`); the game answers "Failed to get data" for other clubs |
| social_group | 26 | 0.5 s through MCP after squad_hierarchy | own club (`club_idx`) |
| player_happiness_reason | 1 to 3 per player | 0.57 s through MCP for 4 players | own club (`club_idx`, the player's current club) |
| player_concern | up to 10 per player | 0.33 s through MCP for 2 players | own club (`club_idx`) |

`promise` is content-invalidated by the interaction items and the game date. `player_attribute_history` is computed for the players a statement names, as the history tables are (`HISTORIES.md`: at most 400 per statement, kept until the game date changes). Through `fm_db_query` on the MCP stdio server at load average 9: the first `promise` reference took 22.7 s, including a snapshot rebuild; a two-player `player_attribute_history` statement took 1.1 s. Under `view='manager'` every collection table of this lane, `interaction_item` and the four new tables included, is refused ("access to main.<table>.<column> is prohibited"). That is the manager-view layer, not these tables.

Views: `interaction_item_view` (names and team), `hall_of_fame_view` (names and nation).

### interaction_item (INTERACTION_MANAGER +0xF8)

These are 0x60-byte items with a reference count at +0x0. A person's list holds pointers to the same items; the list code increments the count with `ldadd` when it copies a pointer. The person screen's ActivePromisesCount and HappinessNegatives getters read the items through two functions:

- 0xCDB374 filters a person's list. It skips items with status +0x56 = 6, treats a null +0x10 with status 0 specially, and compares the packed date at +0x38 with a date argument.
- 0x2476034 processes an item. It returns early when bit 0 of +0x53 is set, dispatches on the u16 type at +0x4E (it branches on 8, 17 and 243), resolves +0x20 as the item's person, and reads +0x18, +0x28 and +0x30.

On the managed club, +0x18 is the human manager on items about a player and the player on items about the manager. The u16 at +0x4E (`kind_code`) is the promise kind of the title dispatch 0x24419A4 ("Promises" above). `kind_title` gives its game title. Counts on this save: 9 (1,406, no title), 10 (177, no title), 1 Fair increase in playing time (85), 3 Sell player (36), 53 Abandon plans to retire (17), 7 (14, no title), 16 language course (10), 2 Offer a new contract (10), 57 Don't sell player (6), 74 Register in squad (6), 25, 37, 215 (1 each). `start_date` (+0x38) and `end_date` (+0x3C) equal the Promises screen's StartDate and EndDate on every listed promise. The address column was dropped; `interaction_item_view` uses the new names.

Kinds without a title (a scan of the plugin for `ldrh [x, #0x4E]` followed by a compare finds only these consumers):

- **7** (14 Newcastle players, 2030-07-31 to 2031-01-27, `kind_value` 1 or 2): 0x24890EC takes a person, filters his list through 0xCDB374 and returns the i8 at +0x44 of his kind-7 item. Two callers use it: the happiness computation 0x20ABDB4 (value > 0 sets bit 35 of its factor mask, < 0 sets bit 36) and the person server 0x234C0A8, which publishes it as data key `sqbs`; the PERSON client reads `sqbs` in 0x235881C, called from the `Pnfo` branch of 0x376980. No screen list shows the items; the value is a per-player happiness factor. What the screen calls it is not established.
- **16** (7 Newcastle items; player at +0x18, human at +0x20; `kind_value` 7 on all): read by 0x1F5CCC0, which matches +0x18 to the person and reads +0x44. Not on the Promises screen lists (`zWLF`, `vP71`, `tcoS`, `bfN3`, `cyPm`) nor the player's `rq49` / `Pmbm` / `W2VE`.
- **9** (none at Newcastle): on team 25,329 the manager is +0x18, the player +0x20, `kind_value` is 6, 15, 27, 29 or 56 and pairs one-to-one with `value_4c` 6001, 6004, 6000, 6005, 6002. They are not promised squad numbers: two players of that team share 27, and `PlayersWithPromisedSquadNumbers` (vPK:) is empty there and at Newcastle. `IssueLinkedPromises` (87Lq) and `PlayersWithLinkedPromises` (plnp) answer null on both teams.
- **10**: no consumer comparing +0x4E with 10 was found.

### squad_hierarchy and social_group (Squad > Dynamics)

A read hook on TEAM_UI_HANDLER `HierarchyTeamLeaders` for Newcastle found the stored list. The server function 0x225C4F0 reads it from a cache on the human manager: team +0x80 (the manager's NON_PLAYER subobject, person + 0x20) -> +0x388 -> +0xFE8, a vector of 0x20-byte entries indexed by the team's position in its club's team list (club +0x18). An entry is vector<item*> plus the date it was computed (+0x18, 2030-12-06 on 13 Dec 2030). The server uses the entry while that date is later than the game date minus 8 days (0x225CBA0..0x225D384) and recomputes it otherwise. An item (0x30 bytes, refcounted) holds 14 signed 16-bit factors at +0x4..+0x1E, the influence at +0x24 and the person at +0x28. 0x225D89C sorts items into tiers: influence >= 9000 team leader, >= 7500 highly influential, >= 6000 influential, else other. The influence equals the factor sum on 18 of 26 players; on six it is capped at 8999 (sums 9,006 to 13,119), on Kobel it is 14,113 for a sum of 13,702 and on Simon Greenwood 5,512 for 6,890. Which factor is which is not established.

Only the human manager's entry holds the list: following the same path from every team's manager gives 26 items for Newcastle and 0 or 2 for 13 other teams, whose managers are not human (on those classes +0x388 is another field), and for AI teams the TEAM server answers "Failed to get data" to every hierarchy data key. The table reads only teams whose manager is a HUMAN_NON_PLAYER. Social groups are not stored: the server builds them from each player's relationship list (the pointer at person +0x2E0, 16-byte records with a type byte at +0xA, sign at +0xB and strength at +0xC) every time the screen is drawn. `social_group` therefore reads the server's data key `sgEd` (groups `clin` 0 to 3, members `clpl`) and the labelled reasons keys.

Checked against `fm_get_squad_dynamics` (`ui_recipes_more.squad_dynamics`) on 13 Dec 2030: the same members in each tier (3 team leaders Livramento, Kobel, Gordon; 11 highly influential; 7 influential; 5 other) and in each social group (9, 8, 6, 3). Every stored influence gives the tier the screen shows.

### player_happiness_reason and player_concern

A read hook on PERSON `HappinessPositives` for Jay Robinson shows what the list is made from: his two promise items (through 0xCDB374 and 0x2476034), his concern ring (0x150B3E0..0x150B460) and injury and transfer state. The texts are computed when drawn and are not stored as a list. The game's stored happiness state is the concern ring: player primary +0x2F0 (the main FULL_CONTRACT, whose +0x8 is the person) -> +0x30 -> ring (count +0x0, ten slot pointers +0x8, head +0x58) of 28-byte records: start +0x0, end +0x4 (1900-01-01 while open), reason u16 +0x16, category +0x19. `player_happiness_reason` holds what the screen shows; `player_concern` holds the ring. Robinson's open concern (reason 652, category 12) started on 2030-11-24, the day the playing-time promise was made; Chema Andrés's started on 2030-11-06. The reason-code texts and the meaning of `reason_code` in the screen rows (8 on injury texts, 10 on speculation texts) are not decoded. No strength is stored in either; the ring's scalars are raw.

Checked: `player_concern` equals `player_concern_history_source.inspect` (the decoder behind `fm_get_player_concern_history`) record for record on the promised players and on Livramento (10 records); `player_happiness_reason` equals `fm_get_player_status`'s happiness_positives, happiness_negatives and playing_time_happiness on two players.

### hall_of_fame_entry (HALL_OF_FAME_MANAGER +0x18 / +0x30)

Each entry has a person at +0x18 (none on 4,316 entries: people no longer in the database), a nation at +0x20, a birth date at +0x48 and points at +0x54. The entry's own vector at +0x0 holds 0x48-byte sub-records.

- **Birth date (+0x48):** equals `person.date_of_birth` on 1,162 of the 1,168 entries where both are set. It is also set on 852 entries whose person record has none.
- **Points (+0x54):** inferred. The top of the list is Guardiola 6,816, Ferguson 5,533, Ancelotti 4,978, Mourinho 3,491, Gallardo 3,304 and Luis Enrique 3,269. The human manager's entry has 679.

### injury_case (INJURY_MANAGER +0x70)

There is one 16-byte record per person: two packed dates at +0x0 and +0x4, then the PERSON table index at +0x8. The person is established: 1,817 of the 1,825 people have a current injury in `player_injury`. The roles of the two dates are not established. On Newcastle: Gordon 2030-12-05 / 2030-12-20, Ramsey 12-01 / 12-21, Miley 11-30 / 12-23, Robinson 12-09 / 12-15, Higgins 12-11 / 12-16, Shima 12-11 / 12-14.

INJURY +0xB8 is not the Medical Centre's risk assessment: it holds one 16-byte record per person (1,086 people: packed date +0x0, PERSON index +0x4, u16 +0x8, u8 +0xA in 1..3, u8 +0xB, zero +0xC), and only one Newcastle player has one (Lewis Miley: 2030-12-23, 93, 2, 24), while the Medical Centre (`fm_get_medical`) puts 13 Newcastle players in the high group and one in increased. 108 people have both a +0xB8 record and an injury case; on 101 of them the record's date equals the case's `date_4` (Miley's case is 2030-11-30 / 2030-12-23). The roles are still not established.

### retirement_entry (RETIREMENT_MANAGER +0x18 / +0x30)

Each entry is 24 bytes: a PERSON table index, a u32, three packed dates and a flag word. The first two dates are season bounds (2030-05-28 to 2031-06-29, or 2030-01-01 to 2031-01-0x). Mean ages are 34.6 (list_18) and 36.3 (list_30), and list_30 holds 387 non-players. These look like retirement consideration lists, but that is inferred. No Newcastle player is on either list.

### award_schedule (AWARD_MANAGER +0x18)

Each row is one award-period object: the award at +0x8, a u32 at +0x10 and four packed dates at +0x18..+0x24. On observed rows the first two dates bound the period: 2030-08-17 to 2031-05-10 for league-season awards, monthly spans for MONTH_AWARD_DATA. The person screen's ContractRenewalDecisionStaffAdviceReason getter reads +0x18, +0x1C and +0x24.

## How it was established

- **Allocation sizes:** disassembly of the world constructor around each constructor call or inline vtable store.
- **Code that uses each root:** ADRP+LDR cross-references to each global, mapped to the vtable slots of the functions that reach them (for example PERSON_UI_HANDLER_SERVER slot 2, SAVE_SYSTEM slot 2).
- **Which screen keys read which container:** a classic `UiHandlerVM` with a Unicorn read hook over every container and element range, run while reading all 664 `PERSON_UI_HANDLER` keys for a Newcastle player and the human manager. This found the readers of INTERACTION +0xF8 and +0x110, INJURY +0xB8 and +0x31, RETIREMENT +0x78 / +0x90 and AWARD +0x18. The function addresses come from the program counters of those loads.
- **Cross-checks:** the Hall of Fame against person birth dates (SQL above), injury cases against `player_injury`, retirement person indexes against ages and classes.

## Not established

- What the screen calls kinds 7, 9 and 10 and the status byte +0x56 values other than 0 (consumers above).
- The `valu` unit, record +0x40 and `srTT`.
- The names of the 14 influence factors; the concern reason-code texts.
- The INJURY_CASE date roles. `date_4` is the same day (2030-12-20) for injuries that started on different days, so it is not a per-injury return date; it may be the next evaluation date. Not established.
- The contents of the eight 0x90-byte lists and +0x110.
- The INJURY +0xB8 and +0xD0 layouts.
- The DYNAMICS maps, which are empty here.
- The TEAM_TALK map entries.
- The AWOL records.
- The RETIRED_PERSON_DATA storage.
- The MORALE and DISPUTE scalars.

Next routes:

- Influence factors: disassemble the per-player builder 0x225DB0C, which the server calls when it recomputes the list; each factor is one store into the item.
- Kind 7: follow `sqbs` into `Pnfo` (`otfl` flag bytes) and the happiness factor bits 35 and 36 into the text table the Happiness panel uses.
- Concern reason texts: find the formatter that takes the ring's u16 reason (500..1362) to a translation id, as 0x24419A4 does for promise kinds.
- INJURY +0xD0: compare the 16-byte records with `player_injury_history` on players whose history is short.
- INJURY +0x70 dates: the global 0x56A82A0 is loaded by 18 functions (0x1ADDC98, 0x20ABDB4, 0x26E4034, ...); find the one that writes +0x4 of these records.
