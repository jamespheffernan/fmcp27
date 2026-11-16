# Manager view (fog of war over the fmdb snapshot)

The manager view runs the same SQL as the snapshot, restricted to what the selected manager knows in-universe. Two modules implement it:

- `fm_live_mcp/fmdb/knowledge_store.py` keeps the manager's knowledge in `<cache>/fmdb/<save key>/knowledge.sqlite`, keyed by PERSON index, for one save and coach, with the input fingerprint of every row.
- `fm_live_mcp/fmdb/manager_view.py` opens the snapshot read-only, attaches that store, creates masked `m_*` views and installs a SQLite authorizer that denies reads of the unmasked tables.

`fm_live_mcp/fmdb/knowledge_codes.py` holds the verified mapping between the knowledge engine's 47 attribute fields and editor FourCC codes.

## What the view guarantees

- Every attribute value comes from `knowledge_bulk` (mode `cells`, the path `visible_attributes_bulk` runs). The store and the view never read an attribute byte from the game, and never pass a base-table attribute column through. The engine's firewall is unchanged.
- Rows are the snapshot's players of the native player list. With a game attached, a statement's knowledge columns are computed for the rows it reads (see "What a statement computes"). Without one, rows are the players with a current knowledge row, and `m_coverage` and `prepare_manager_query` say how many players that leaves out.
- Each of the 47 attributes appears as four columns:
  - `<attr>`: the value when the cell is exact, else NULL;
  - `<attr>_min`, `<attr>_max`: the bounds (equal to the value when exact, NULL when unknown or unavailable);
  - `<attr>_state`: `exact`, `range`, `unknown` or `unavailable`.

  When the base already has the attribute (`passing` in `player_view`, `passing_Ppas` in the `player` table), the masked view keeps that column name; otherwise it adds the canonical name (`free_kick_taking`). `m_attribute_columns` lists the column for each field in `m_player_view`.
- Knowledge columns appended to every row: `scouted`, `k`, `sources`, `ca_gate`, `pa_gate`, `own_club`, `h_score`, `node_score`, `report_score`, `exact_n`, `range_n`, `unknown_n`, `unavailable_n`, `unavailable_reason`, `current_ability_stars_min`, `current_ability_stars_max`, `current_ability_stars_state`, `potential_ability_stars_min`, `potential_ability_stars_max`, `potential_ability_stars_state`, `in_player_search`, `knowledge_date`.
- Perceived ability stars (0.5 to 5.0 in 0.5 steps) are what the game shows instead of CA/PA, so they appear for any player. The state is `exact`, `range`, `unknown` (the game shows no stars), `unavailable` (the emulator refused) or `not_computed`.
- Every other column follows the policy below. Columns the policy does not classify are NULL.
- The caller cannot read the unmasked tables through the connection (see Enforcement).

## Views and tables on a manager connection

| Name | Content |
| --- | --- |
| `m_player_view` | `player_view` rows with knowledge, masked |
| `m_scouted_player_view` | `m_player_view` where `scouted = 1` (FOW node, report or own roster) |
| `m_player`, `m_person` | the base `player` / `person` tables, masked the same way (when present) |
| `m_columns` | every masked column: view, name, editor code, policy, field, note |
| `m_attribute_columns` | the 47 fields: name, 1..20 code, 1..100 code, column in `m_player_view` |
| `m_coverage` | key/value coverage at connection time (see Coverage) |
| `kn.knowledge_player`, `kn.knowledge_attribute`, `kn.knowledge_wide` | the knowledge store itself (readable) |
| `m_<name>` for every other table and view | collection tables, core tables and curated views, masked by their policy (see "Every other table and view") |
| `m_tables` | every masked view and withheld object: scope, rule, reason |
| `_fields`, `_tables`, `_snapshot` | snapshot metadata (readable) |

## Masking policy

**This table is policy, not proven game behaviour.** It errs toward withholding. "Own club" means the engine's own-club branch (`knowledge_player.own_club = 1`), the players whose 47 attributes the game shows exactly.

| Column class (editor codes) | Non-own-club player | Own-club player | Reason |
| --- | --- | --- | --- |
| Identity: `idx`, `uid`, `class` | pass | pass | row identity |
| The 47 visible attributes (`Paab` ... `Pnft`, 1..20) | knowledge cell | knowledge cell (exact) | from `knowledge_bulk` only |
| Names: `duni Pfna Psna Pcna PAfn PAna PAcn PnRV Pfln PShN dbnm`, person type `Ptyp`, gender `Pife` | pass | pass | shown on any profile |
| Date of birth and age `Pdob Page`; height `Phes Phei` | pass | pass | profile header |
| Nationality and birthplace `Pnti Pnat P2ni PNRs Pnbi Prbi Pcbi` | pass | pass | profile header |
| Club, loan club, on loan, squad number `Pcti Ptaj PLcl Pion Psnu` | pass | pass | profile header and squad lists |
| Position string `Ppos Ppsr` | pass | pass | profile header |
| International caps and goals `Piap Pigl Puia Puig` | pass | pass | profile header |
| Current / potential ability and derivatives `PCAB ERCL ERCA PCRD PRDF PPAB PPMX PPAR PPPA PkCA PkPA` | NULL | NULL | never shown as numbers; the star columns carry what the game shows |
| Hidden attributes `PCON Pdir Pimp Pipr Pver` and their 1..100 twins | NULL | NULL | never shown |
| The 1..100 attribute family `PD**` (47 visible + feet `PDlf PDri`) | NULL | NULL | the UI shows 1..20 only |
| Raw foot ratings `Plft Prft` | NULL | NULL | the UI shows a word |
| Raw reputation `PCRP PHRP PWRP PCRI PHRI PWRI PSCR PGRP` | NULL | NULL | the UI shows a band; band thresholds are not mapped |
| Personality values `Pada Pamb Pcvy Ploy Ppre Ppro Pspo Ptem` | NULL | NULL | the UI shows a personality word |
| Staff-role preference ratings `PP**`; role/position score lists `PRLS ORLS PRSS PBrI Porl`; attribute lists `PATL PWEI`; `PRjm PRae PFDv` | NULL | NULL | internal or derived from hidden values |
| Editor bookkeeping `rdui NDBC FDBC ReAR PeTR` | NULL | NULL | not game data |
| Current contract wage and expiry `Pcwg Pcex` (and the extras `Pcww Pced`); favoured and disliked people and clubs `Pfvp Pdsp Pfvc Pdsc` | pass | pass | on every profile: see "Evidence" (PERSON panel list) |
| Everything else with an editor code: contract clauses, bonuses, transfer value, condition, sharpness, fatigue, bans, position familiarity ratings `Pgoa`..`Pace`, best roles, traits `PM**`, squad status | NULL | pass | visible for own players; withheld for others where no evidence says otherwise |
| Derived view columns with no editor code | NULL, except the names in `PUBLIC_UNCODED` (`name`, `club_name`, `nation_name`, `age`, `date_of_birth`, `position`, ...) | same | unclassified columns are withheld |
| Season statistics (snapshot extras holding `{valu, numb}` records: appearances, minutes, goals, assists, average rating, xG, xA, cards, passes, tackles, ...), form `Pfrm`, starts/substitute appearances `Posa Posu Poap`, short position text `Ppss`, nationalities `PNal` | pass | pass | shown on any player's profile and statistics pages |
| `player.is_virtual` (`c:is_virtual`), `team.club_idx` (`c:club_idx`) and the `idx` of a referenced club/team/nation | pass | pass | row identity and club membership |
| Current injuries `injr`, `x:injuries`, `x:injury_days_remaining`, `x:has_injury_record` | pass | pass | CanViewFitnessInfo is in the PERSON panel list of every player; `player_injury` is public |
| Morale `Pmor`; wage range `PcwR`, contract start `PcSd`; position ratings `PPra Ppsa`; contract job `Pcjo`; `PRCF`; derived `x:condition_stored` | NULL | pass | own-player panels (CanViewPlayerDevelopment, CanViewPlayingTimeInfo ...) or no evidence |
| Every other snapshot extra (labels inferred: injury risk `InRs`, feet ratings `Pfot`, unlabelled keys) and any other `x:`/`c:` column | NULL | NULL | meaning not proven; withheld |

The codes live in `manager_view.PUBLIC_CODES`, `NEVER_CODES`, `PUBLIC_UNCODED`, `EXTRA_PUBLIC_CODES` and `EXTRA_OWN_CLUB_CODES`. Snapshot extras (getter keys outside the editor catalog, `extras.EXTRA_FIELDS`) default to NULL unless listed; editor codes keep the own-club default.

How a column gets its policy (`column_policy`):

- A base-table column maps to its editor code through `_fields`.
- A view column is classified from its select expression in the view's SQL. A plain reference (`p."passing_Ppas" AS "passing"`) takes that column's policy; a visible attribute stays an attribute under the view's name.
- A derived expression takes the strictest policy of every base column it reads. A raw attribute inside an expression counts as `never`, because the expression would expose the stored value. Examples: `name` (from `Pfna`, `Psna`, `Pcna`) and `age` (from `Pdob`) are public; `squad_status` (an `_enum_labels` lookup on `PMsq`) is own-club; `(passing + pace) / 2` is never.
- Columns of referenced tables (`team`, `nation`, ...) are public only for name codes (`Tlna`, `Nnam`, ...); anything unresolved is `never`.

Naming differs between the base table and the curated view. In the snapshot's `player` table the plain names belong to the 1..100 family (`passing` is `PDps`) and the 1..20 values carry the code suffix (`passing_Ppas`). So in `m_player`, `passing` is NULL and the knowledge cell is `passing_Ppas`. The curated `player_view` aliases the 1..20 columns to plain names, so in `m_player_view` the knowledge cell is `passing`. `m_attribute_columns` gives the column for each field.

### Collection tables (`fmdb/sources`, `COLLECTIONS.md`)

### Every other table and view (collection tables, core tables, curated views)

Naming rule: every table and view of the full schema is served as `m_<name>` (`m_fixture_view`, `m_contract`, `m_club_view`, `m_standing_view` ...). The bare names stay denied on a manager connection, so a statement that names `contract_view` means the stored data and is refused there, and the error names the `m_` view to use. Bare names were not made aliases: a temp view named `fixture` would shadow the table inside the copied view bodies (they resolve names when a statement runs) and the same SQL would silently mean different data in the two views.

`manager_view.catalog` lists every object from the snapshot's metadata; `m_tables` (view, base, kind, scope, rule, reason, collection_tables) shows each with its scope, and `fm_db_schema(view="manager")` gives one line per view (`views`) and the reason for each withheld object (`withheld`). Scopes:

| Scope | Rows | Columns | Source of the policy |
| --- | --- | --- | --- |
| `public` | every row | every column as stored | `manager` of the collection table or view |
| `own_club` | every row | `public_columns` on every row, the rest only on the manager's club's rows | `manager` with `public_columns` |
| `own_rows` | only the manager's club's rows | every column | `manager` scope `own_club` without `public_columns` |
| `core` | every row | identity, names and links on every row; other columns (editor-code policy) only on the club's rows; raw reputation, CA/PA and the person `never` codes never | core table or curated view whose main table is `club`, `team` or a staff table |
| `core_public` | every row | identity, names and links; everything else withheld | other core tables (`nation`, `competition`, `stadium`, `city` ...) |
| `never` | none (not created) | | `manager` scope `never`, or refused by the checks below |

"The manager's club" is `_managed.club_idx` (`_managed` holds his team idx, club idx and name; it is
readable in the manager view under its bare name and as `m__managed`, the one stored table the
authorizer lets through, because nothing in it is hidden from him); its teams are the `team` rows whose `club_idx` is that club, its people the `person` rows contracted (`Pcti`) to one of those teams. An own-club policy names how a row is the manager's (the schema fields are documented on `sources.MANAGER_SCOPES`): `own_club_column(s)` (club idx, any of them), `own_person_column`, `own_team_column`, `own_club_via 'table.column'` (`<table>_idx` names a row whose column is the club), or `own_club_rule` (an SQL condition over the row). A resolved view without the column inherits its table's rows through `idx` (`transfer_offer_view`). A view whose own rows cannot be told apart is withheld (`interaction_item_view`; use `m_interaction_item`).

Checks before a view is created (otherwise it is `never` with the reason): a collection view may not read a person column the policy withholds (CA/PA, hidden attributes, personality, raw reputation, a raw 1..20 attribute) anywhere, joins and filters included, and a `public` view may not read a person's own-club-only column either; a curated core view may not join or filter on such a column; a base view may not read other views. A column of a `public_columns` view is public only when every column its expression reads is public (the policy table's public columns, public collection tables, name and link columns of core tables), so `contract_view.squad_status` and the loan fees stay own-club. A base table with an index on a column that is not public on every row is scanned `NOT INDEXED`, so a covering-index scan cannot order rows by a withheld value.

How a statement on these views is answered:

- A statement whose every `m_` view is `public` and that reads no player knowledge is checked on a masked connection (`EXPLAIN` under the authorizer: a bare table or a withheld view is refused there) and then run by the full path with each `m_<name>` written as `<name>` (`tools.manager_public_query`). The rows are the same by definition, and collection tables, statement-dependent tables and on-demand cells are built exactly as for the full statement, at the same cost.
- Any other statement: the collection tables it names are built or refreshed first (`sources.refresh_for_query`, as the full path), then the masked connection runs it. Only the views the statement names are created (`only`, about 0.03 s), and a statement that reads no player view computes no knowledge (`_prepare_without_knowledge`). On-demand cells of core tables that a generic view shows (team, competition, club, person names, staff attributes) are recorded as `need(idx, 'ref:...')` for the rows the masked statement read and computed by `tools.manager_prewarm_refs`, for the columns the statement names.
- Statement-dependent tables (`person_*` histories, `player_season_rates`): `sources.dry_run_connection` takes a `ManagerStatement` and returns a masked connection (`open_dry_run`) on which the source's own setup statements (its key table and the temp view that shadows its table) run without the authorizer and the caller's statement runs under it. The keys it computes therefore depend only on what the manager sees: `loan_fee > 100` over another club's contracts reads NULL in the dry run. If knowledge computed for the statement can widen the keys, the tables are checked once more after the knowledge pass.

### Timings (live, through the MCP stdio server, 12 November 2026, load average 8 to 13)

Wall seconds of `fm_db_query`, the full statement then the same statement on the `m_` views, third round (the first round includes building the tables on first reference, the same for both):

| Statement | Full | Manager |
| --- | ---: | ---: |
| Premier League table from `standing_view` | 0.09 | 0.14 |
| `count(*), sum(home_goals)` over `fixture` | 0.04 | 0.08 |
| Newcastle home fixtures from `fixture_view` (names) | 0.09 | 0.14 |
| `count(*)` of `match_player_stats` for a team | 0.03 | 0.08 |
| `fixture_all` joined to `match_player_stats`, grouped | 0.08 | 0.13 |

The manager path adds 0.04 to 0.06 s: reading the catalog and compiling the statement on a masked connection before the full path runs it. A first reference that builds a table costs the same on both paths (`fixture_all` loads the archived years: 310 s full; the manager statement after it 259 s, because `fixture_history` retries the archive groups that failed to load, see COLLECTIONS.md). A statement on own-club views (`m_contract_view` of one club with its loan fees) took 0.16 to 2.4 s, the extra being on-demand person names; a mixed statement with `m_player_view` 2.6 to 3.2 s (knowledge pass).

### Evidence: the game's own panel lists

The game decides which profile panels it shows with one list builder per record type; the front end asks the server for the list (`vcvp`) and tests membership. Emulated on live data (13 December 2030, Newcastle United) by calling the shipped functions in a UI VM:

- PERSON `0x3B1B8C` (`vcvp` in PERSON_UI_HANDLER_SERVER slot 2 at `0x3F50B0`; the client reads it for `CanViewCurrentContract` at `0x37F2CC`). Its gates are virtual calls on the person (`+0x510`, `+0x520`, `+0x4D8`, `+0x4E8`) and the person's flags at `+0x18`; the human manager argument is used only after `CanViewCurrentContract` is decided.
- CLUB `0xD725C` (keys `wFnR`, `aIj6`, `V9LC`, `s0d0`, `Hb3Q` are materialised only there and in the client getters).
- TEAM `0x5B8F30`.

| Sample | Panels for that record |
| --- | --- |
| Every person (own player 8209, Arsenal 9186 unscouted and 11008 scouted, Leeds 1528 scouted, free agent 1495, staff 370, 152, 1112, free-agent staff 4) | CanViewCurrentContract, CanViewFavouredClubs, CanViewFavouredPeople, CanViewNationalities, CanViewPersonalInfo, CanViewCareerStats, CanViewBiography, CanViewMilestones, CanViewRelationshipInfo, CanViewCareerPlans |
| Every player, any club, scouted or not | CanViewAgent, CanViewDisciplineRecord, CanViewFitnessInfo, CanViewForm, CanViewHomegrownStatus, CanViewNationalTeamInfo, CanViewPerformanceInfo, CanViewPlayerAttributes (masked by knowledge), CanViewPlayerTraits, CanViewPositionalAbilities, CanViewSeasonStats, CanViewTransferStatusInfo |
| Own players only | CanViewPlayerInjuryRisk, CanViewPlayerPromises, CanViewPlayerDevelopment, CanViewPlayingTimeInfo, CanViewIndividualTraining, CanViewHierarchyPosition, CanViewSocialGroup, CanViewWorkPermitStatus, CanViewPlayerTargets, CanViewPlayerPerformance |
| Every staff member, any club or none | CanViewNonPlayerAttributes, CanViewNonPlayerReport, CanViewCoachingBadges, CanViewStaffHistory |
| Every club (414 own, 329, 397, 3284) | CanViewTransferHistory, CanViewFavouredPersonnel, CanViewRivals, CanViewAffiliates, CanViewFacilities, CanViewHonours, CanViewRecords, CanViewManagerHistory, CanViewHistoryReport, CanViewLandmarks |
| Own club only (414) | CanViewContracts, CanViewTransferClauses, CanViewTransferActivity, CanViewStaffTransferActivity, every CanViewFinances*, CanViewBoardDetails, CanViewClubVision, CanViewSupportersDetails, CanViewRecruitmentBudgets, youth panels |
| Every team (545 own, 460) | CanViewSquad, CanViewStaffList, CanViewSchedule, CanViewStats, CanViewTeamCompetitions, CanViewPreviousMeetings |
| Own team only (545) | CanViewInjuries, CanViewSquadRegistration, CanViewSquadNumbers, CanViewTactics, CanViewTraining, CanViewDynamics, CanViewCaptains, CanViewScouting |

The list does not change with knowledge (9186 unscouted and 11008 scouted at the same club get the same list). The value behind the contract panel was checked too: PERSON `ContextContractWeeklyWage` (`QNVC`, server data key computed without the manager's context) formats Szoboszlai's (Arsenal) exact wage, "£9.17M p/a", value 176,406 a week, equal to `contract.weekly_wage`. The knowledge-dependent values the game shows as estimates are the transfer value (`TransferValueRangeScouting*`) and the scouted wage demand (`ScoutedMaxWage` reads `Pmxd`, "-" for every sample), not the current wage. Scripts: `cache-r3-mview/work/vcvp.py` (list builders), `wagekeys.py` (contract keys).

### Policy table (collection tables and views)

| Table or view | Scope | Evidence or reason |
| --- | --- | --- |
| `contract`, `contract_view` | own_club; public columns idx, person, role, class, teams, club, squad number, expiry, weekly wage, signed date | CanViewCurrentContract for every person; `QNVC` formats another club's exact wage. Loan fees, clause count and squad status stay with the club (CanViewContracts and CanViewTransferClauses own club only) |
| `contract_clause`, `contract_clause_view`, `contract_clause_labelled` | own_rows (through `contract.club_idx`) | CanViewTransferClauses: own club only |
| `fixture`, `fixture_history`, `fixture_coverage`, `competition_stage`, `standing` and views | public | CanViewSchedule and CanViewTeamCompetitions for every team; league tables are competition screens |
| `match`, `match_event`, `match_team_stats`, `match_player_stats`, `match_shot`, `match_pass`, `player_season_stats`, `player_season_rates`, `team_season_stats`, `match_screen_team_stats` | public | CanViewStats for every team, CanViewSeasonStats and CanViewPerformanceInfo for every player |
| `match_event_stream` | never | engine stream, not a screen (module) |
| `transfer_offer`, `transfer_offer_view` | own_rows (any of the team clubs) | CanViewTransferActivity: own club only. Offers between other clubs once reported: open question |
| `player_injury`, `player_injury_view`, `injury_case`, `player_injury_history` | public | CanViewFitnessInfo and CanViewCareerStats for every player; the team injury list (CanViewInjuries) is own team only and is not a table here |
| `news_item` | own_rows (`source = 'inbox'`) | the manager's inbox (module) |
| `person_playing_history`, `person_non_playing_history`, `person_career_spells`, `person_career_totals`, `club_league_history`, `hall_of_fame_entry`, `hall_of_fame_view`, `award_schedule` | public | CanViewCareerStats, CanViewStaffHistory, CanViewHonours, CanViewRecords for every person and club |
| `person_favourite` | public | CanViewFavouredClubs and CanViewFavouredPeople for every person (was own_club) |
| `club_favourite_person` | public | CanViewFavouredPersonnel for every club (was own_club) |
| `club_rival`, `club_affiliate`, `feeder_club_group` | public | CanViewRivals, CanViewAffiliates for every club |
| `person_nationality` | public | CanViewNationalities for every person |
| `player_position` | own_rows (`player_idx`) | CanViewPositionalAbilities is shown for every player, but whether the panel's ratings are exact for an unscouted player was not established: withheld (open question) |
| `club_finance`, `finance_stadium_entry`, `facility_upgrade`, `training_camp`, `backroom_advice_entry`, `scout_manager_entry`, `scout_player_assignment` | own_rows | CanViewFinances* and the board, youth and recruitment panels: own club only |
| `player_registration_marker`, `registration_verdict`, `competition_registration` | own_rows | CanViewSquadRegistration: own team only |
| `competition_registration_rule` | public | competition rules (module); no predicate found |
| `job_advert` | public | job centre lists every vacancy (module); no predicate checked |
| `interaction_item` | own_rows (team clubs) | CanViewPlayerPromises: own players only. `interaction_item_view` withheld: it has no club column and no idx |
| `board_takeover_entry`, `contract_manager_entry`, `market_manager_container`, `human_non_player`, `people_manager*`, `retirement_entry`, `squad_manager_entry`, `comp_host_*`, `match_momentum_weight`, `match_rating_weight`, `native_manager`, `virtual_player` | never | internal state (module declarations) |

Core tables: identity, names and links public everywhere; for the manager's club (`club`, `club_view`, `club_labelled`), his teams (`team`) and his staff (`non_player`, `staff_view`, `official`, `journalist`, `agent`), the other editor-code columns too. Staff attributes of the Non-Player Attributes panel (coaching, mental, knowledge, medical: `STAFF_PUBLIC_CODES`) are public for every staff member (CanViewNonPlayerAttributes for staff of every club and free agents); staff CA/PA (`Ncra`, `Npta`) and raw reputation are never shown. `person_labelled` and `player_labelled` are withheld (use `m_person`, `m_player`).

### Open questions for the owner

- Transfer value: the game shows a range that depends on scouting knowledge (`TransferValueRangeScoutingKnowledge`, `TransferValueRangeScoutingString`); the view withholds other clubs' values instead of computing the range.
- Position ratings, player traits and condition of other clubs' players: their panels are in the list for every player, but the panels' own rendering (exact or masked) was not emulated. Withheld.
- Transfer offers between other clubs: not shown as an activity list (CanViewTransferActivity own club only); whether a reported offer appears elsewhere (news, rumours `cvtr`) is not established. Withheld.
- Reference values of other records (stadium capacity, competition reputation, city population, club facilities as 1..20): the screens show words or bands for several of them; no mapping. Withheld.
- The CONTRACT_UI_HANDLER fields of another club's player (bonuses, release clauses on the contract panel) were not emulated field by field; only the wage (`QNVC`) was.

## Enforcement

SQLite expands a view inside the caller's statement and reports every base-column read to the authorizer, tagged with the innermost view or CTE name. A CTE named like a public view receives the same tag, so a tag alone proves nothing. The connection therefore uses two layers of views:

1. a private view per masked base, `_mv_<16 hex>_<public name>`, named with a per-connection random token. It contains the masking expressions over a copy of the base's own `SELECT` (the view body from `sqlite_master`, so its base reads carry the private tag);
2. the public `m_*` view, `SELECT * FROM <private view>`.

The authorizer allows:

- `SELECT`, recursive CTEs and functions (except `load_extension`, `readfile`, `writefile`, `edit`, `fts3_tokenizer`, `sqlite_dbpage`, `zipfile`);
- reads of the public views, the `kn` knowledge schema, snapshot metadata and `json_each`/`json_tree`;
- reads of a private view only from a public view, and reads of `main` tables only from a private view;
- table-level access with no column (SQLite reports `count(*)` and unused tables of a flattened join that way, without view context; it carries no column value).

It denies everything else: direct or subquery reads of `player`, `person`, `player_view` or any other base table, reads of `sqlite_master`, `sqlite_temp_master` and `sqlite_schema` (in every schema), every PRAGMA (including `pragma_*` table functions), ATTACH, DETACH and all writes. Building a connection fails if a base view depends on other views, because their reads would carry the inner view's public name.

The token cannot be read through SQL. `check_sql`, which `prepare_manager_query` applies, also rejects anything but a single `SELECT`/`WITH`/`VALUES` statement (so no `EXPLAIN`) and any identifier containing `_mv_`, so a CTE cannot be named after a private view even by a caller who learned the token elsewhere.

`tests/test_fmdb_manager_view.py` tries these bypasses; each is denied:

- `SELECT current_ability FROM player`, `SELECT * FROM player`, `person`, `player_view`, `main.player`;
- scalar, `IN`, `EXISTS` and correlated subqueries on `player` inside queries on `m_player_view`;
- `FROM (SELECT current_ability FROM player)`;
- CTEs reading `player`, including CTEs named `m_player_view`, `m_scouted_player_view` and `player_view`;
- a join of `m_player_view` with `player`, and a `UNION` with `player`;
- `count(*) ... WHERE current_ability > 100`, `ORDER BY current_ability`, `rowid`, `max(potential_ability)` on `player`;
- `sqlite_master`, `sqlite_temp_master`, `temp.sqlite_master`, `sqlite_schema`, `kn.sqlite_master`;
- `pragma_table_list`, `pragma_table_info(...)`, `PRAGMA table_list`, ATTACH, DETACH;
- `CREATE TEMP TABLE/VIEW`, `INSERT`, `DELETE`;
- a top-level read of the private view by its real name (authorizer), and a CTE named after it (`check_sql`).

The same tests confirm that `SELECT *`, CTEs, subqueries, window functions and joins between masked views work, that `current_ability` reads as NULL through every shape, and that `EXPLAIN` and `EXPLAIN QUERY PLAN` output never contains the private prefix.

### Two saves that differ only in masked values

`tests/test_fmdb_manager_view_leaks.py` builds two snapshots with the same players and public data and different hidden data: CA/PA, hidden attributes, raw reputation, personality, the stored attribute values behind unknown and range cells, the wage, contract, value and condition of other clubs' players, and a rival club's cash balance. Both carry indexes on hidden columns. The knowledge is the same for both. It then runs about 3,400 statements over every column of every masked view (filters, `IN`/`EXISTS`/scalar subqueries, `ORDER BY`, `GROUP BY`, `HAVING`, aggregates, window functions, self-joins on equality and inequality, set operations, `LIMIT`/`OFFSET`, type and string functions) and requires the same columns, rows and row order on both, and the same on-demand need set. It found two leaks; both are closed:

- **Row order and `LIMIT` followed a hidden index.** SQLite may scan a base table through any index that covers the columns a statement uses. With an index on `current_ability` present, `SELECT idx FROM m_scouted_player_view WHERE ...` returned its rows in CA order, and `LIMIT` kept the lowest-CA players. The private views now drive the scan from a knowledge-store table in PERSON index order (`CROSS JOIN` fixes the join order) and look the base row up by `idx`. Real snapshots carry no index on a hidden `player` or `person` column today, so they were not exposed; an index added later would have been.
- **The fingerprint tables were readable.** The authorizer allowed every table of the `kn` schema. `knowledge_input` and `knowledge_group` hold addresses and digests of consumed bytes, some of them values the policy hides (raw reputation scalars). They and `_knowledge_meta` are now denied to the caller.

Filters on masked columns never selected rows by hidden value: a masked column is NULL (or the own-club `CASE`) inside the view, so a predicate on it sees NULL. The fixture also holds a collection table of every policy kind (public fixtures and a statement-dependent history table; contracts with a withheld loan fee on other clubs' rows and an index on it; clauses, offers, inbox and club finance whose other-club rows differ in number and value; a `never` table; a view declared public that reads a withheld person column) and the core `club` table with a rival's cash balance and reputation. The battery runs over every masked view `m_tables` lists, and the bypass list adds the bare collection tables and views, CTEs named like their masked views, joins, subqueries and unions with them, `_source_tables`, `sqlite_temp_master` and `pragma_index_list`; `_managed` and `m__managed` must read the same on both saves, and a join from `_managed` to a hidden column is refused. `test_fmdb_manager_view_tables.py` checks the dry run of a statement-dependent table on both saves (same keys; a statement that names a bare table computes nothing). On-demand computation is not a side channel either: which players a statement asks knowledge for depends on public columns and stored knowledge only, and the test compares those need sets.

Not covered: the emulated-on-demand snapshot columns of `p2/ondemand` did not exist in this tree. A public column that is NULL until some other query computes it would let a manager-view statement see which rows the full view has touched; whether that reveals a hidden value depends on what drives that computation. The masked views should read such columns only through a function that computes them for the rows the manager statement itself reaches.

## Knowledge store

`knowledge.sqlite` (WAL; written in short `BEGIN IMMEDIATE` transactions):

| Table | Content |
| --- | --- |
| `knowledge_player` | `idx` PK, `k`, `node_score`, `report_score`, `own_club`, `sources`, `scouted`, `h_score`, `ca_gate`, `pa_gate`, `exact_n`, `range_n`, `unknown_n`, `unavailable_n`, `unavailable_reason`, `category`, `node_present`, `report_present`, the six star columns, `in_player_search`, `tier`, `game_date`, `computed_at`, `epoch`, `stars_epoch` |
| `knowledge_attribute` | `(idx, field)` PK, `code`, `state`, `value`, `min`, `max`, `reason` |
| `knowledge_wide` | the same cells pivoted per player (`<attr>`, `_min`, `_max`, `_state`); the view joins this |
| `knowledge_input` | per player the fingerprint of the inputs its evaluation consumed: `spans`, `digest`, `groups`, `facts` (`docs/knowledge-bulk.md`, "Inputs, fingerprints and incremental calls") |
| `knowledge_group` | the outcome groups those fingerprints refer to, with their own spans, facts and outcome |
| `knowledge_seed` | the named population with its seed flags (FOW node, report, own roster) |
| `knowledge_universe` | every player PERSON index of the native all_actual vector |
| `knowledge_fields` | the 47 field/code pairs |
| `_knowledge_meta` | identity (save key, save name, coach, club, capture options), the current epoch, the fingerprint context, timings |

`k` is contextual K as the engine reports it. For own-club players the cells capture never evaluates K, the node score or the report score, so those columns are NULL there. When every field threshold is zero the cells capture has no H score; the store then takes the CA/PA gates from one `player_knowledge_summary` capture of those players, and such a row gets no fingerprint.

### Epochs replace the game-date key

A row is not valid "for a game date". It is current when it was computed or confirmed in the store's current epoch. A new epoch starts when the game date moves, when the caller asks for one, or when the current one is older than `EPOCH_SECONDS` (20 s), so a match or a signing inside one date is seen by the next query. A new epoch deletes nothing. `KnowledgeBuilder.ensure(idxs)` (`ensure_knowledge(target, store, idxs)`) makes rows current: it gives the engine the stored fingerprints of the rows that are not, the engine evaluates the players whose inputs changed and confirms the rest, and the store rewrites only the evaluated rows. `lacking_knowledge(store, idxs)` lists the rows a call would touch.

Another save, coach or capture option drops every row. Another game process keeps the rows but voids their fingerprints, because fingerprints hold addresses; the next use evaluates them again. A store written by another schema version is dropped and rebuilt when opened.

There are no tiers, no `stale_*` tables and no background fill. The `tier` column remains as a label (1 named population, 2 asked for, 3 other). The detached `knowledge_store fill` process and its pid and log files are gone; `python -m fm_live_mcp.fmdb.knowledge_store ensure [--all]` brings rows up to date in the foreground when an operator wants that.

### Stars and Player Search

`ensure_stars(idxs)` fills the star and Player Search columns for current rows and marks them with `stars_epoch`. Stars are computed for the named population and for players with a FOW node, a report or own-club context; other players keep `not_computed` (1,000 sampled returned unknown). Player Search admission is computed for the named population and for explicitly requested indices. These columns have no fingerprint: the emulated star code reads hidden values through whole pages, so they are computed again in each epoch for the rows that read them.

## What a statement computes

`prepare_manager_query(engine, sql, bridge_or_session=..., params=..., max_rows=...)` computes nothing in advance. It opens the masked connection with a need function (`open_manager_connection(need=set())`). In that mode a masked view covers every snapshot row of the player universe, and each expression that depends on a knowledge row calls the need function when the row is not current; the function records the PERSON index and yields NULL. The statement is run the way `query.fetch` will run it (same batches, same stop at `max_rows`), the recorded players are brought up to date, and the statement runs again, until a run records none. `ManagerQuery.complete` is True when the last run needed nothing, and the message states how many players were evaluated and how many were confirmed.

- A statement that reads only public columns (`name`, `age`, `club`, ...) computes nothing.
- `m_scouted_player_view` is a private view of its own over `knowledge_seed`, so a statement on it reaches the named population only.
- A statement that evaluates a knowledge column for every row (`ORDER BY passing_min` over `m_player_view`) needs the whole save: minutes the first time, the cost of confirming fingerprints afterwards.
- `scouted` comes from `knowledge_seed`, so `WHERE scouted = 1` alone computes nothing. With a second, knowledge-reading term SQLite may evaluate that term first and ask for more rows than the result holds; the answer is the same, the work is not. Read `m_scouted_player_view` for the named population.
- Without a bridge the stored rows of the current epoch are used as they are, and `complete` reports whether they cover the named population or the universe.

The caller must fetch with the `max_rows` it passed (or pass none): rows beyond the probed ones would show NULL knowledge.

## Coverage and timings (live, Newcastle United, 13 December 2030)

Machine load 50 to 80 during these runs (other work on the same host); CPU seconds are this process and its helpers.

| Step | Players | CPU s | Wall s |
| --- | --- | --- | --- |
| Named population read (`seeds`) | 3,607 | 1.1 | 2.1 |
| Named population, nothing stored | 3,607 evaluated | 10.1 | 14.8 |
| Named population, new epoch, nothing changed | 3,607 confirmed | 1.9 | 3.4 |
| Stars and Player Search for the named population | 3,607 | 14.4 | 41.4 |
| First statement of a session on `m_scouted_player_view` (knowledge filter), empty store | 3,607 evaluated, 2 passes | 13.1 | 20.0 |
| The same statement in a new epoch, nothing changed | 3,607 confirmed | 3.8 | 4.9 |
| Save-wide statement on public columns (`age <= 17 AND club LIKE 'Real%'`) | none | 1.1 | 1.3 |
| Save-wide statement, public filter then knowledge filter (`age <= 18 AND passing_min >= 13 ... LIMIT 20`) | 9,868 evaluated | 26.9 | 32.6 |
| Whole store on frozen pages of 10 December (engine, SQLite, stars for 3,555) | 66,043 | 206.3 | 285.4 |

The tiered builder took 58 s for the named population (119 s with stars and Player Search), 23 minutes for the whole save, and started again from nothing every game day.

## Field pairing

Verified live by `knowledge_codes.verify_field_codes` (`python -m fm_live_mcp.fmdb.knowledge_store pair`): on all 29 own-club players, where every cell is exact, the PropertyVM getter of each of the 106 `attribute`-typed `play` codes was compared with the engine's exact value. Every field matched exactly one 1..20 code (blob byte 1 equals the value) and exactly one 1..100 code (round(x / 5) equals the value). All 47 are paired; no field is unpaired. The 1..20 codes without a knowledge field are `PCON`, `Pdir`, `Pimp`, `Pipr`, `Pver`.

| Field | 1..20 | 1..100 | Field | 1..20 | 1..100 |
| --- | --- | --- | --- | --- | --- |
| Aerial Reach | Paab | PDae | Aggression | Pagg | PDag |
| Command Of Area | Pcoa | PDca | Anticipation | Pant | PDan |
| Communication | Pcom | PDcm | Bravery | Pbra | PDbr |
| Eccentricity | Pecc | PDec | Vision | Pcre | PDvs |
| Handling | Phan | PDhn | Decisions | Pdec | PDdc |
| Kicking | Pkic | PDkc | Determination | Pdet | PDde |
| Reflexes | Pref | PDrf | Flair | Pfla | PDfl |
| Rushing Out (Tendency) | Prou | PDro | Leadership | Pinf | PDld |
| Punching (Tendency) | Pttp | PDtp | Off The Ball | Potb | PDmv |
| Throwing | Pthr | PDth | Positioning | Ppsn | PDpt |
| One On Ones | Pooo | PDoo | Teamwork | Ptwr | PDtm |
| Crossing | Pcro | PDcr | Work Rate | Pwkr | PDwr |
| Dribbling | Pdri | PDdr | Composure | Pcmp | PDcp |
| Finishing | Pfin | PDfn | Concentration | Pcnt | PDcc |
| Heading | Phea | PDhd | Acceleration | Pacc | PDac |
| Long Shots | Plsh | PDls | Agility | Pagi | PDal |
| Long Throws | Plth | PDlt | Balance | Pbal | PDbl |
| Marking | Pmar | PDmr | Pace | Ppac | PDpc |
| Passing | Ppas | PDps | Stamina | Psta | PDsm |
| Penalty Taking | Ppen | PDpn | Strength | Pstr | PDst |
| Free Kick Taking | Pfrk | PDfk | Jumping Reach | Pjum | PDjm |
| Tackling | Ptac | PDtk | Natural Fitness | Pnft | PDnf |
| Technique | Ptec | PDtc | First Touch | Pfrs | PDft |
| Corners | Pcor | PDcs | | | |

`tests/test_fmdb_knowledge_live.py` repeats the pairing, builds tier 1, and compares `m_player_view` with `visible_attributes_bulk` for 50 scouted players: 2,350 of 2,350 cells equal (1,653 exact, 539 range, 158 unknown), plus the summary columns against `player_knowledge_summary` for 30 players.

## Range-aware filters

`manager_view.range_filter(kind, attribute, x)` returns the predicate; `RANGE_FILTERS` lists them for tool descriptions:

| Kind | SQL | Meaning |
| --- | --- | --- |
| `sure_at_least` | `"<attr>_min" >= x` | the manager knows it is at least x |
| `could_be_at_least` | `"<attr>_max" >= x` | at least x is consistent with what the manager knows |
| `sure_at_most` | `"<attr>_max" <= x` | known to be at most x |
| `could_be_at_most` | `"<attr>_min" <= x` | at most x is consistent |
| `exact` | `"<attr>" IS NOT NULL` | exact value known |
| `known` | `"<attr>_min" IS NOT NULL` | exact or range |
| `unknown` | `"<attr>_state" = 'unknown'` | nothing known |

## Use from `fm_db_query` (`view="manager"`)

```python
from fm_live_mcp.fmdb import manager_view as mv

q = mv.prepare_manager_query(engine, sql, bridge_or_session=(bridge, session_id), coach_name=None)
rows = q.connection.execute(sql).fetchall()     # the same SQL that was checked
result = dict(rows=..., coverage=q.coverage, complete=q.complete, message=q.message, notes=q.notes)
q.connection.close()
```

- `engine` may be the snapshot lane's `Engine` (paths from `cache_root()/save_info().save_key`, live date from `save_info().game_date`), a snapshot path, `(snapshot, knowledge)` or `{'snapshot': ..., 'knowledge': ...}`.
- With `bridge_or_session` the call binds the store to the attached save and coach, decides the epoch, reads the named population and computes what the statement reads (see "What a statement computes"). `require_idx` rows are made current first, with stars and Player Search. Pass the `params` and `max_rows` the fetch will use.
- `ManagerViewError` carries the reason when the SQL is not a single query, when knowledge is missing or from another date, or when the snapshot cannot be masked.
- `q.coverage` holds `knowledge_rows` (current rows), `stored_rows`, `scouted_rows`, `universe_players`, `universe_players_covered`, `snapshot_rows`, `snapshot_rows_covered`, `tier1_complete` (the named population is current), `tier3_complete` (the universe is current), `unavailable_rows`, `game_date`, `epoch`, `snapshot_game_date`, `live_game_date`, and `on_demand` (`passes`, `evaluated`, `confirmed`, `stars`, `seconds`). `fill_running` is always False. When `q.complete` is False, `q.message` starts with `PARTIAL:`; the tool should show it with the rows.
- A query is treated as limited to scouted players when it reads `m_scouted_player_view` (and no other masked player view), or filters `scouted = 1` with no `OR`.

## Limits

- Without `native=True`, about 1.7% of players have every attribute `unavailable` (three unproven contextual-K branches). With it (the default), none of the 66,043 players has.
- A row is as fresh as its epoch: at most `EPOCH_SECONDS` old when a statement reads it.
- Fingerprints hold addresses. After a game restart every row is evaluated again on first use.
- Stars are run with the managed team as the viewer's team (see `docs/knowledge-stars.md`); on this save 10 of the 66 own-club players return `unavailable` (`unexpected_star_bins` from `knowledge_stars.decode_stars`); every player of the managed squad has stars. Players outside the named population without a node or report hold `not_computed`. `ca_gate` and `pa_gate` remain the H states of the star gates, a separate decision.
- The policy table is a judgement about the game's UI, not a replay of it.
- Masking relies on `_fields` and on parsing the base view's select list. A base view built from other views is refused, and a column whose expression reads nothing resolvable is NULL unless its name is in `PUBLIC_UNCODED`.
- The private-view token protects a connection only while the caller cannot read the schema; callers must run SQL through `prepare_manager_query` (which applies `check_sql`) and must not remove the authorizer.
- The snapshot's `player` table holds 78,782 rows; the native player list (the knowledge universe) holds 66,043. Snapshot rows outside that list never get a knowledge row and never appear in the manager view; the coverage message counts them.
- Verified on one save, coach and date.

## Runs against real snapshots

- The snapshot lane's test snapshot (`fmcp-source-cache/test-snapshot/fmdb/<save key>/snapshot.sqlite`, built 10 December 2030, `player` table only) opened read-only with the live knowledge store: `m_player` built in about 0.1 s, `SELECT count(*) FROM m_player` in 0.17 s over 23,555 covered rows, own-club cells equal the knowledge store (for example `finishing_Pfin = 17` exact), and `SELECT current_ability FROM player`, the CTE named `m_player_view` and `SELECT acceleration FROM player` were denied.
- A copy of that snapshot with a catalog-shaped `person` table and `team`/`nation` name tables, with the snapshot lane's committed `views.create_views` run on it (114-column `player_view`): all 47 attributes classified as attributes (Free Kick Taking under the lane's `free_kicks`), CA/PA, hidden attributes, feet, reputation and personality `never`, wage, contract, condition and position ratings `own_club`, and name, age, nationality, club, position, height, squad number and caps `public`.
