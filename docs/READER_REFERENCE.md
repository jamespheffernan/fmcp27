# Reader reference

Technical notes and verification history. Paths and captured game states in older entries refer to the development machine; use the [README](../README.md) for current installation steps. Local evidence linked below is not included in the public repository.

## Read current international duty

Use `fm_get_player_international_duty(session_id, player_refs, coach_name=None)` for distinct references from the selected manager's native roster. It returns the current national-assignment/travel gate, the native reason and the official native estimated-return date where supported. False, unavailable, unsupported virtual and outside-current-TEAM rows remain separate. Dates are estimates; this gate does not establish full match eligibility or physical whereabouts. Process, build, save, manager, roster and consumed bytes are rechecked without expanding profiles or invoking the game.

## Compare possession events by witnessed period

Use `fm_report_retained_possession_by_period` with one exact retained fixture. The report requires original host-observed native period stops, an independently bound possession-event witness and full-fixture counter agreement for every original player, including zeros. It returns possession won/lost by player and side in those intervals. Missing witnesses remain unavailable; boundary events remain unassigned. These counts do not establish pressing success, on-pitch minutes or tactical effects.

The three retained period reports can persist finalized local host links. Current-match and shot-origin reads can preserve bounded private host observations; the explicit recorder writes a local capture. These six tools declare `readOnlyHint=false` for their host effects. The separate training setter declares `readOnlyHint=false` and `destructiveHint=true` for its game-memory edit.

## Read stored concern history

Use `fm_get_player_concern_history(session_id, player_refs, coach_name=None, include_templates=False, include_promises=False)` with 1–100 fresh, distinct references from `fm_get_managed_squad(profile_policy="available")`. Each regular player's result follows the canonically owned main `FULL_CONTRACT` whose club matches that player's current team club. It preserves all native slots up to ten, newest first, including repeated records and null slots. Dates, reason/category codes, linked scalars and unknown flags retain their stored values.

A verified null or empty ring returns zero and `[]`. Missing or unsupported contract/current-club contexts return null records and counts. Combined and virtual records retain checked identity with unsupported history. The native unset-end marker does not establish current unhappiness, active promises, satisfaction or fulfilment. These bounded records do not describe the whole career or club, and do not attribute past events to the present manager.

Raw history works independently of English. Set `include_templates=true` for compiled, unrendered English first templates. Placeholders remain literal; context-dependent descriptions retain null text and keys. This option verifies the existing pinned resource before and after the read and rejects unavailable or changed resources. It never creates or materializes English and does not establish the loaded UI language or rendered complaint text.

Set `include_promises=true` to add `promise_inventory` for each player: the exact native PLAYER-linked promise vector in physical order, with repeated entries retained. An absent vector, an empty vector and an unsupported (combined or virtual) record stay distinct. Each entry keeps the native kind, category and linked-scalar codes, the raw start and end dates and the end-marker flag. Both native person links are returned neutrally with match flags against the selected manager and the vector owner; promiser, recipient and subject stay null because the roles depend on the viewer. Active, ongoing, fulfilled, overdue, required targets and `active_count` are not evaluated and stay null. The vector is neither a complete manager-wide promise population nor a list made only by or about that player. With `include_templates=true`, native kinds 1, 16, 25, 69 and 120 also carry their compiled unrendered English template; other kinds, including kind 7, stay unmapped rather than guessed. The decoder rests on one genuine passive capture (29 roster slots, 22 entries) and the original native source spans; it has had no separate live reader run.

The query rechecks process/build, loaded career/date, selected coach/team/roster, reference bindings and consumed bytes after the scope's final callbacks. Reads remain non-atomic. It invokes no game functions, expands no profiles and uses no saved-file fallback.

## Read stored individual training focus and club intensity

Use `fm_get_player_individual_training(session_id, player_refs, coach_name=None, include_default_resolution=False)` with 1–100 distinct references from the selected manager's native roster. It returns each checked identity and stored additional-focus code, with a pinned English definition for codes0–32. Zero is Quickness Rehab;255/-1 is unset. Other values stay unknown. Missing children and present unset children remain distinct. Combined/virtual records preserve identity with explicit unsupported focus.

The reader verifies and rechecks process/build/save/date, canonical HUMAN/TEAM ownership, native roster membership and consumed bytes. Stored roster membership can include loans; it establishes neither whole-club coverage nor current training control. The independent `club_training_intensity` field reads the regular PLAYER stored club byte: 0 is Half Intensity, 1 Normal Intensity, 2 Double Intensity and254/-2 No pitch or gym work. Raw255/-1 requests native default resolution; this is a concrete stored request. Set `include_default_resolution=true` to reconstruct its native default at the current stored condition from an existing selected HUMAN/TEAM policy. The separate `default_intensity_resolution` returns the resolved definition, `not_requested` for explicit selections, or an unavailable reason for unsupported TEAM selection or missing direct policy. Applied intensity remains unknown. Other codes remain unknown; combined/virtual records return null. Missing additional-focus children do not hide the club setting. Effective training, role/position assignment, applied intensity, workload, attendance and development outcomes remain unproved. The tool changes nothing in the game.

## Compare stored tracking width

`fm_get_retained_match_spatial` includes `lateral_width` for every selected canonical player, overall and by possession. It takes absolute native lateral coordinates before averaging, so switching flanks does not cancel. Each row carries its own sample count, zero-tail coverage and unknown possession-byte counts. A missing stream stays unknown; a centreline sample remains zero. The measure uses native units, includes stored post-exit zero tails, and does not establish on-pitch minutes, metres, human left/right or a simultaneous comparison between players.

`fm_report_retained_lateral_width_by_period` compares one selected fixture team's original players across native normal-half intervals. It requires a prospective spatial-only host witness binding complete observed tracking, actual possession bytes, canonical actors and native terminal stops. A current-match query can preserve that witness only when FullTime/EndOfGame, the playback cursor and buffered maximum agree and all source checks succeed. Existing shot, pass or possession observations cannot backfill it. Missing or mismatched witnesses return unavailable periods. The report reads host records without saving, linking or finalizing them; current-match queries retain their existing host-write annotation. Each player and period has its own sample denominator, with zero pairs, terminal zero tails and unclassified phases exposed. No 45-minute split, elapsed minutes, on-pitch coverage or tactical cause is inferred.

## Financial decoding

Use `fm_get_club_stadium_rent(session_id, coach_name=None)` for the selected active manager's club recorded stadium rent in whole GBP per year. Missing finance stays unavailable, typed base finance returns its separate native literal zero, and concrete finance preserves signed cash. This stored value does not establish a lease obligation, payment schedule, amount due or future liability. It is separate from weekly wage and transfer budgets.

Use `fm_get_club_committed_wage_spending(session_id, coach_name=None)` for the selected active coach's club current and committed wage spending in whole GBP per week. It explicitly recomputes native payroll in owned memory, then evaluates the native committed-wage arithmetic using the same inputs. It never enters or simulates the game's thread/HUMAN refresh decision. Unsupported monetary inputs reject the whole query. These totals do not establish every staff/bonus/tax cost, a complete future liability schedule, remaining budget or affordability.

Use `fm_get_club_finances` with `include_ffp_projection=true` to read FM’s pass/fail result for each competition in the selected club’s finance report. Each row includes the signed amount FM assesses and its applicable minimum when available. The decoder replays the pinned ARM64 calculation in a private Unicorn VM using stored spending, verifies the competition and club identities, and rechecks the live input bytes. An unsupported calculation returns an explicit unavailable state.

Set `include_details=true` to read the scouting budget, ticket prices, stored season ticket holders, loan payment schedules and recorded FFP events. Loan amounts describe the original debt. Each schedule identifies whether FM includes it in FFP.

Use `fm_get_player` with `include_transfer_prices=true` for a regular player’s last fee, stored valuation and asking-price input, and FM’s contextual valuation and asking-price properties. A negative native code has a null amount. A returned asking price can include a valuation fallback. These properties do not predict whether a bid will be accepted.

Use `fm_get_saved_club_starting_finances` with the archived club index and snapshot ID for historical debt and optional FFP entries. Currency is unresolved for these starting records.

Use `fm_get_contract_wage_steps` with one fresh regular/combined `player_ref` to compare the current weekly main-contract wage with every stored league-game or international-appearance wage target. Each clause retains its threshold, repeated entries, native getter selection and signed target-minus-current GBP/week difference. These are independent scenarios; alternative steps are not additive. A per-player maximum positive difference is an envelope over stored targets, not payroll, activation, remaining appearances or budget exposure. Basic/no-contract and unavailable sources remain explicit.

## Inspect stored personal tactical records

Set `include_personal_overrides=True` on `fm_get_managed_tactical_assignments` to inspect the selected working creator’s bounded personal position records. The default remains off. Each assignment keeps its base role and adds an explicitly qualified personal-record result; root context describes the current readable maps.

Exact-mask/nonzero lookup and strict in-possession role lookup are reported separately because native callers can apply different policies. Absent records, inactive first matches, stored positive records, policy differences and unavailable sources remain distinct. Returned data is address-free: activation, mask, ordinal and stored role encoding only. This does not decode all individual instructions, establish effective role overrides or prove global absence of personal instructions.

## Read both picked tactical phases

Call `fm_get_managed_tactical_assignments(session_id, coach_name=None, phase="both")` after attaching. It reads the current owned working edit session and returns both phases’ original slot order, named position masks and stored base roles. A role in Football Manager 27 has no duty; each phase has its own role. Use `phase="in_possession"` or `phase="out_of_possession"` for one subset. The out-of-possession pairing follows the verified native working-creator remap, including its explicit fallback; it is not an assumed same-index pairing.

Unknown masks/roles, empty or duplicate people and malformed/unproved mappings remain explicit or fail closed. The tool creates or applies nothing and does not establish effective individual role overrides, foreground display, submission, eligibility or a played lineup. The existing in-possession-only view remains available.

## Read picked in-possession positions

Call `fm_get_managed_in_possession_positions(session_id, coach_name=None)` after attaching. It pairs the existing editable XI’s original eleven slots with the owned working tactic’s stored in-possession position masks and base roles. Named positions and roles follow verified compiled English branches; unknown masks/roles, empty slots and duplicated people remain explicit.

The tool reads an existing edit session and creates or applies nothing. Missing creators or an unproved selection boundary are unavailable/partial states. It does not establish out-of-possession pairing, individual effective role overrides, foreground display, match submission, eligibility or a played-match lineup.

Recorded tactical samples use a versioned semantic policy and pinned native guards. Historical producer-source digests remain provenance: harmless formatting changes do not invalidate an approved recording. Changes to native or portable semantics require an explicit policy version; modified artifacts and unknown policies remain refused.

## Plan the next live fixture

Use `fm_get_next_match_squad(session_id, coach_name=None, window_days=35, position_minimum=15, max_fixture_pages=20)` after attaching. It reads the current simulation date, managed roster and existing resident fixture groups in one native observation. It finishes every group/slot of earlier calendar days and the earliest candidate day. `selection_complete` describes that prefix; `window_fully_scanned` is separate. Remaining-window cursors open with `fm_find_fixtures` using the returned criteria and same session.

The result separates canonically verified current-club members, away players and unknown club links. Incoming loans can remain at the managed club. Position cover uses the stated stored0–20 rating threshold and excludes away players from the cover summary while retaining every roster slot. Stored condition/sharpness percentages, signed fatigue, injury records and personal bans remain separately qualified. Empty ban or injury lists do not establish registration, active suspension applicability, medical clearance or eligibility. No starting XI is selected.

For current Premier League registration predicates, use
`fm_get_managed_league_age_exemptions(include_registration=true)`. The pending
manager-context guard accepts the verified literal kind23 getter alongside its
previously checked kinds. Unknown getters and kind19 remain unavailable, and
changed native bytes reject the read. A returned registration predicate remains
separate from age exemption, the complete submitted list and fixture eligibility.

Same-day scored/result rows remain candidates: live time-of-day, completion and operational cancellation/postponement are unproved. Unknown kickoff times and ties stay explicit. Missing years/unloaded groups and page budgets make the candidate unconfirmed. All consumed source bytes and roster/fixture/club identities are rechecked before session-bound references are published; changes reject the response, and failed publication restores reference caches. No disk-save data or native refresh functions are used.

## Optional names for saved histories

| Tool | Opt-in | Name source |
|---|---|---|
| `fm_get_managed_tactical_assignments` | Both picked working-tactic phases with verified out-of-possession remap, position labels and stored base roles |
| `fm_get_managed_in_possession_positions` | Current picked XI’s verified in-possession slot positions and stored base roles, with explicit unknown/ambiguous mappings |
| `fm_get_next_match_squad` | One live observed fixture candidate, canonical current-club/loan roster partition, position cover, stored health and recorded bans with explicit eligibility uncertainty |
| `fm_get_saved_staff_history` | Same-pin typed PERSON non-playing histories, qualified dates/roles, same-file TEAM/CLUB names and distinct missing/no-key/empty states |
| `fm_find_saved_transfer_offers` | Source-scoped two-vector stored-offer search by original PERSON/TEAM indices, preserved objects/paging and raw state/qualified loan terms |
| `fm_get_saved_player_starting_history` | `include_names=true` | Exact same-save identity pairs and checked owning-club membership. |
| `fm_get_saved_player_injury_history` | `include_installed_names=true` | Verified installed English database baseline, separately attributed from saved data. |

Both flags default to `false`. Opting in preserves raw identities and row order. Historical display names, career language and user/editor overrides are not inferred. Missing injury resources keep the saved rows available; ambiguous career identities remain unnamed.

## Compare saved current statistics

Use `fm_compare_saved_current_player_statistics` with a filename, its exact `expected_snapshot_id`, and 1..32 PERSON indices from `fm_get_saved_club_squads`. The source is the save's serialized current statistics, separate from retained form and archived/starting playing history. `category_code` defaults to 1 (League); the native codes are 0 Non Competitive, 1 League, 2 Cup, 3 Continental, 4 International and 5 Overall (Club). These are primary categories per PERSON. Selecting a Newcastle roster does not establish that every primary League bucket is Newcastle-specific, and the source does not establish a numeric season year. Do not sum overlapping categories.

`minimum_minutes` defaults to 270. Every selected person retains starts, substitute appearances, total appearances, goals, assists, signed minutes and raw compact counters when stored. A null category and a fully checked absent current entry stay distinct from stored zero. Byte 255 counters remain unavailable. One complete component pass checks all owner keys and rejects duplicate owners; duplicate requests are evaluated once. Exact rational G+A/90 ordering preserves tied competition ranks. `eligible` means meeting the statistical ranking criteria, never fixture, registration or transfer eligibility.

The checked 28-person Newcastle cohort has 13 rows meeting 270 minutes in its primary League category. Jacob Ramsey has 5 goals and 3 assists in 495 minutes (16/11 G+A/90); Nick Woltemade has 5+2 in 497 (90/71); João Neves has 2+1 in 565 (54/113). These are pinned-source benchmark observations, not live-save or team-attribution claims.

Names remain separately qualified saved suffix witnesses. In this cohort PERSON 13009 has both the Anthony Gordon identity witness 28116386/28116386 and another suffix candidate, so the statistics response leaves its selected display name null. Keep its exact numeric rank and resolve the name independently through a checked same-pin PERSON/profile identity if needed; never choose a witness because its name seems familiar. Incomplete and unavailable name states likewise do not erase exact numeric statistics. Unsupported source variants, corrupt bounds, changed snapshots and duplicate owners fail explicitly.

## Compare retained saved-player form

Use `fm_compare_saved_player_form` with a filename, snapshot ID and up to 32 PERSON indices. Supply the stored `team_index` from the same snapshot’s club-squad result, inclusive `date_from`/`date_to` bounds, and a positive `minimum_observed_minutes`. An optional `competition_index` filters the exact stored COMP word. Every selected person retains an explicit eligible, below-minimum or unavailable state.

The comparison uses goals, assists and minutes from the same supported statistical rows. Missing statistics contribute neither numerator nor denominator; stored zero minutes remain present. Results show observed and missing coverage, retained date ranges, exact-ratio ranks and all ties. Distinct serialized rows remain distinct, including duplicate dates. This describes retained form rows; it does not establish complete season coverage, senior-squad membership, match completion or general best-player performance. The row’s separate team word is not the group-owner filter.

## Search saved fixture results

Use `fm_find_saved_fixture_results` to ask: “Which retained Newcastle records have stored Kick Off dates from 2029-01-01 through 2030-10-23, and what scores are stored?” Supply `filename`, `expected_snapshot_id`, the original `team_index` from a same-pin saved club-squad result and inclusive `date_from`/`date_to` values. The index belongs to TEAM_BASE, not CLUB or a native ID. Either ordered side may match; side order is preserved without assigning home/away labels.

Each source row keeps its original container/ordinal, byte span/hash and ordered canonical TEAM identities, with source-backed owner CLUB names when available. `FIXTURE_RESULT` rows return separate normal-time, extra-time, penalty and aggregate score channels. Each cell retains raw/signed bytes and a nullable value: zero is a score, FF is unset and other negative codes remain unmapped. A bare `FIXTURE` has no RESULT score block, rather than zero scores. Scores and RESULT presence do not establish completion, winner, actual played date or actual venue. The date selector is native FIXTURE+4C stored Kick Off; the separate+48 word remains unlabelled.

Default scope is retained base, initial and declared outer FIX_MAN groups. Set `include_historical=true` to search separately indexed historical frames, retaining their frame/group metadata and decompressed offset space. Storage years are not kickoff-date filters. Preserve duplicate physical occurrences within and across scopes. Historical storage that was not requested, unavailable storage and a fully read empty scope remain distinct; an empty retained result does not prove full-save absence. Wire reference profiles remain conditional.

Set `include_competition=true` for batch same-file FIXTURE_NAME→COMP/STAGE_NAME identities. FIXTURE_NAME indices are not COMP indices. The table has a unique complete structural conjunction; the sequential PERSON predecessor and runtime globals remain unproved. Names omitted from the source remain null, and three stage-name slots do not acquire guessed round/leg meanings. Stored stadium indices are references, not proof of actual venue.

Use `offset`, `limit` (default50, maximum500) and `next_offset` with identical selectors and the same pin. Rows stay in serialized scope order and are never deduplicated by date, teams or key. Small complete results are reused within one server process after rechecking the archive pin on every page; the cache retains at most500 matching rows per entry and two serialized entries of at most4MiB each. Larger or byte-heavy results keep the bounded cold scan. A restart can require another scan. Current-source acceptance checked116 retained rows including an extra-time contrast, a penalties contrast and one bare FIXTURE, plus a positively returned historical record. These checks do not establish every source layout or native-loader acceptance.

## Read stored match-player goals and assists

Use `fm_find_saved_fixture_results` to select a TEAM/date record, then pass that row's `archive_key`, an original same-snapshot `person_index`, `filename` and `expected_snapshot_id` to `fm_get_saved_match_player_statistics`. The query reads the exact indexed retained match and checks both complete player-stat side sections before returning stored goals and assists. Stored zero remains zero. Missing retained keys or player rows are explicit unavailable states; duplicate keys or duplicate subject rows fail. No live game attachment is needed.

For the checked main Newcastle snapshot, Gordon PERSON13009 has1goal/0assists at key135195,0/0 at132398 and0/1 at129861. The indices and keys require that snapshot's pin; they are not portable IDs. Stored rows do not establish appearances, match completion, minutes or eligibility. Later match-event data remains unparsed, and the conditional native factory profile is reported. The query preserves file-local PERSON references without resolving a player identity anew; use the same pin as the original roster/person discovery.

## Read a retained saved league table

Use `fm_get_saved_league_table` to ask: “What league table and position were stored for Newcastle in this pinned competition stage?” Supply `filename`, `expected_snapshot_id` and the original COMP `database_index` returned by `fm_find_saved_competitions` on that same snapshot. `stage_ordinal` defaults to 0 and selects an original stage slot; it is not a season or round name. The archived member uses the competition’s native primary ID, which differs from its original database index.

Results preserve the serialized row order and stored overall/home/away statistics. Each row resolves its original TEAM reference and separately joins the owner CLUB under the same checked pin. Empty TEAM names and null CLUB names remain explicit. A one-based `stored_overall_position` is returned only when native view 0 and every original position byte agree with the serialized order. Points stay as stored; the query does not recompute deductions or break ties using guessed rules.

This is retained state, not certified current standings. `season_date_range` and `table_effective_date` remain null, and `currentness` remains `unproved`. The native season code does not establish a season interval. The stage calendar participates in date-driven rule processing and can be later than the verified save date; it is not an as-of date for the table. The supported C0 table can be complete while the remaining stage is unread: `complete_C0_table` and `complete_stage` report those scopes separately. Reference/factory profiles remain conditional, without native-loader acceptance.

Absent members, absent original stage slots, unsupported stage/layouts, source frontiers, ambiguous competition identities and exhausted member budgets remain separate states. Non-decoded rows and counts are null; a fully read empty table has an empty row list and count zero. A later requested slot cannot be reached by skipping a preceding unparsed stage body. Each call selects one competition, bounds its member to 2 MiB raw/8 MiB packed and its response to 1 MiB, and validates canonical identities through forward database reads. It requires no game session and performs no recalculation.

## Scout players in a saved archive

Use `fm_find_saved_players` with `filename`, `expected_snapshot_id` and at least one rating or age bound. For example, `criteria: {"attributes.finishing": {"min": 15}, "attributes.acceleration": {"min": 15}, "positions.striker": {"min": 20}}` requests stored finishing and acceleration of at least 15 and striker rating 20. Add `max_age: 23` to use the verified date from that same save and each stored birth date. These are stored source ratings, not scouting visibility, willingness or suitability judgments.

Criteria combine with AND. Supported groups are `attributes`, `positions` and `ability` (`current`/`potential`); bounds use `min`, `max` or both. Missing ratings or birth dates, known predicate rejection and non-player source classes have separate counts. A known failed predicate excludes a row even if another requested field is unavailable. Names can remain unavailable when ratings match. Regular and combined PLAYER records are included; other decoded PERSON classes are excluded from this player query.

Follow every `next_cursor`, including after an empty partial page. Keep the filename, snapshot pin, criteria and age bounds unchanged; `limit` (default 20, maximum 50) and `scan_limit` (default/maximum10,000 original slots per call) may change. A per-page elapsed-work bound can stop sooner. Cursors belong to one server process and expire on restart or incompatible source/query context. Restart without a cursor when it expires. Do not treat a partial empty page or an unsupported source frontier as whole-save absence.

Report `next_original_ordinal`, declared slots and disjoint cumulative categories with the answer. Decoded-slot counts exclude an unsupported frontier; attempted-slot counts include that attempted edge. The current checked Newcastle prefix reaches 101,039 decoded records before unsupported ordinal 101039, rather than the whole declared table. Whole-table completeness flags remain false at that stop. Native loader globals and the structurally placed source header remain qualified independently of the checked contiguous prefix.

## Optional saved-source cache

Set `FMCP_CACHE_DIR` to an absolute private directory to reuse decompressed saved-source bytes within one server process. Its parent must already exist; the directory must belong to your user, have permissions 0700 and be a real directory. An unset, empty or unavailable setting keeps the original in-memory path. No alternate disk directory is chosen. Keep an existing custom value when configuring a launcher.

Every request still reopens the original snapshot, validates its identity and archive directory, and freshly hashes the full compressed database component. A cache entry is created only after complete frame decoding and matching raw-byte digests. Temporary files are unlinked before filling, their writer is closed before publication, and callers borrow read-only mappings. The LRU retains at most two entries totaling 512MiB; active leases cannot be evicted. Restarting the server clears this cache. No player projections, eligibility decisions or native loader assumptions are cached.

This changes source access for saved name searches, consecutive PERSON records and scouting; it does not add tools, change cursors, expand source coverage or alter the game. Controlled Python-backend checks of the 22-match Newcastle scouting query measured 116 seconds without caching, 65 seconds for a first cached query and 45 seconds for a repeated query, with equal full match objects, counts and frontier. These are one-host backend measurements, not installed Pi timings or a general latency guarantee.

## Read consecutive saved PERSON records

Call `fm_get_saved_person_records` with `filename` and `expected_snapshot_id`. It traverses typed records consecutively from the selected archive’s structurally located PERSON header, checking each original ordinal and physical record end. Returned records include the source type, both stored identity words, byte range, record hash and supported names. Native loader settings and the tables preceding that header remain separately qualified; a checked record does not close the whole database’s sequential route.

For example, pass `person_indices: [13009, 38945]` with the Newcastle archive’s own snapshot ID to request those file-local records. Supply 1–32 indices; their order and duplicates are preserved. Omit `person_indices` to page from `offset: 0, limit: 20` (maximum 32). Use `next_offset` for the next fully available page. Explicit indices cannot be combined with a nondefault offset or limit.

Each call advances at most 10,000 new records. If `retry_same_query_to_advance` is true, repeat the identical request on the same server until its records become available or a source frontier is reported. The private process cache retains record ends; each request reopens the pinned file, verifies the complete component digest and reparses requested cached records. A server restart can require traversal again. An unsupported type stops the contiguous prefix and remains explicit as `source_frontier`; unreached records, more work and indices outside the declared table have separate states. None is an empty whole-save search result. `checked_prefix_count`, `declared_person_slots` and the footer state describe how far the traversal actually reached.

JOURNALIST records are supported under the same conditional source profile. Their identities, supported names and raw class-specific values can be returned by `fm_get_saved_person_records`. They advance the checked prefix, allowing later PLAYER records to be reached. Scouting continues to select regular and combined PLAYER classes; journalists count as excluded classes. Local reference identity and ambient loader settings remain unresolved. Subsequent unsupported types still stop at the reported frontier, and a larger checked prefix does not certify the whole PERSON table.

## Read saved staff history

Use `fm_get_saved_staff_history(filename, person_index, expected_snapshot_id, offset=0, limit=50)` with an original same-save PERSON ordinal. The checked ACTUAL_PERSON identity joins the saved native-ID owner map to ordered non-playing history rows. Missing map entries, stored `-1` keys, selected empty histories and unsupported PERSON classes remain separate. Repeat a bounded PERSON lookup only when its coverage says more work remains; use `next_offset` for the next page (maximum200 rows).

Rows preserve joined/left dates, native default markers, raw job codes and unmapped fields. Joined/left precision can be year-only. TEAM native IDs resolve against checked same-file TEAM records and reciprocal owning CLUB names; ambiguous matches remain explicit. English role titles are separately verified build-specific baseline labels. Historical rows do not establish current employment or a complete runtime career.

## Find stored transfer offers

Use `fm_find_saved_transfer_offers(filename, expected_snapshot_id, person_index=..., team_index=..., offset=0, limit=50)` with at least one original PERSON or TEAM index issued for the pinned snapshot. Both selectors combine with AND. PERSON matches common offer PERSON+38; TEAM matches common TEAM+40/+48/+50, with business direction unresolved. Canonical selector membership is explicitly unchecked.

The query completes the first two named transfer-manager offer vectors and preserves stored order, distinct objects, null-slot counts and paging (maximum500). Offer class and state codes stay source-qualified. Proved loan wages use whole base-currency units per week; monthly fees remain separate and currency stays null. Acceptance, scheduled payment, amount due and later manager sections remain unresolved; a zero match proves absence only within the two queried vectors.

## Continue past saved HUMAN records

`fm_get_saved_person_records` and `fm_find_saved_players` can consume the supported source3754/minor9 HUMAN_NON_PLAYER layout while walking original PERSON slots. A HUMAN record exposes its canonical identity, original same-save names and bounded wire-profile summary. Its opaque manager/UI payload is consumed for exact boundaries and is not interpreted as player ratings. Player scouting classifies HUMAN records as excluded and can continue to ordinary and combined PLAYER records later in the table.

The supported profile has explicit local reference conditions, a 32 MiB record-span limit and bounded child/count work. It reuses the existing inherited NON_PLAYER/common codecs, uses zero-copy source views and skips fixed opaque vectors without allocating their rows. Unknown variants stop the prefix; truncated or contradictory records fail. The source-profile qualification remains conditional: native loader globals and football meanings for HUMAN-specific payloads are unproved. This does not change how unavailable or out-of-range names are reported, and it does not make every PERSON class a player.

Queries still advance a bounded number of slots per call. Continue with the returned same-pin cursor, or repeat an exact canonical-person request only when its response says more checked prefix work remains. Empty partial pages remain partial, and the reported footer audit determines declared-table completion.

## Read saved starting playing history

For “What starting playing-history rows are retained for Anthony Gordon?”, call `fm_get_saved_player_starting_history` with the archive `filename`, its original saved `person_index` and the same `expected_snapshot_id`. The query walks checked regular PLAYER records, joins the native PERSON ID to the authoritative same-save starting-history owner map, then reads `pl_hist_ls.dat` and `pl_hist_dt.cmt`. A PERSON index is never substituted for that history key. Repeat an identical request only when `PERSON_coverage.retry_same_query_to_advance` is true.

Optional `years` selects exact stored year values. Filters precede `offset`/`limit` paging (default 50, maximum 200); original entry order and duplicates remain visible. Rows report stored year, appearances, goals and loan flag. Count255 becomes null while0 stays0. Raw transfer-fee values have no proved currency; dates remain raw. TEAM_BASE and COMP references are native identity-word pairs, with unresolved names, not original table indices or club IDs.

Optional `include_names=true` resolves exact TEAM/COMP identity pairs in the same pinned save. TEAM references name the owning CLUB only when its team vector and the TEAM backlink agree, or the backlink is null and a single club vector supplies the owner. COMP names come from stored competition records. Each name carries its source; missing pairs, duplicate identities, conflicting owners and sentinels stay explicit. This does not infer the historical display name or turn native IDs into table indices. The default response remains unchanged.

A selected empty vector returns `available_empty`. Unsupported PERSON classes, an unreached record, a missing native-ID map entry and an outside-table owner key do not establish empty history. The source route requires a unique complete FIXTURE_NAME structural conjunction and three checked adjoining empty tables; positive unsupported neighboring tables stop the query. This is a conditional source profile, not a complete sequential native loader proof. Used frames and packed bytes are rechecked, and cached canonical counts are keyed by the complete database digest. The index validates selected offsets without claiming a global partition check for all other owners.

These are retained starting-history rows, separate from indexed performance statistics and injury events. The initial Newcastle cohort has stored years2012–2025 in saves dated2030; neither a missing later year nor an empty result proves whole-career or current-season absence. Combined and virtual PLAYER classes remain unavailable for this owner route.

## Read retained competition history

Call `fm_get_saved_competition_history` with the original `competition_index` returned by `fm_find_saved_competitions` and its `expected_snapshot_id`. The tool binds the competition's stored history key and reads its retained indexed rows in original order. Optional `years` selects exact native Year values before `offset`/`limit` paging.

Rows expose named Year, Start Year, End Year, First/Second/Third Placed TEAM references and Date Decided, with raw date bits and separate native year corrections. TEAM identities and owner CLUB names are checked in the same snapshot; stored empty TEAM names remain empty. Missing components, negative keys, outside-table keys and checked empty vectors remain distinct. These are retained historical fields, not a current table, automatic season convention, latest-completed season or complete results archive. The query needs no game session or installed language resource.

## Query canonical saved names

Use `fm_query_saved_people_by_name` for a cursor-paged search over complete typed PERSON records in one pinned save. Supply `first_name`, `surname`, `common_name` and/or `any_name`, with exact, prefix or substring matching. Selectors combine with AND; `any_name` searches each decoded stored part or retired literal separately. It does not concatenate parts or invent First/Surname meanings for unclassified literals. Case and combining accents follow the existing NFKD policy; source spelling stays unchanged.

Follow `next_cursor` with identical selectors, including after an empty partial page. A process-private source-bound name index reuses typed work; returned cached matches are reparsed against the freshly checked source. `limit` caps matches and `scan_limit` caps original slots per call. Cursors expire after source/index eviction or server restart. The existing `fm_find_saved_people` fast suffix-candidate query remains unchanged. Every page reacquires and rechecks the original component (or its original packed bytes on an enabled source-cache hit). A 170478-slot no-match scan needs at least18 calls at the default10000-slot cap; elapsed work and match-page limits can require more. Warm name-index scans avoid body parsing except for returned matches. The name index is memory-only; optional existing source caching retains its own external-storage policy.

Record coverage and name coverage are separate. Out-of-range references, undecodable bytes, unresolved inline effective names and virtual records without projected names remain explicit. Even a footer-checked full PERSON traversal cannot establish absence across all possible names or aliases. Retained pointer/literal records do not imply active player or staff status; native loader-global and source-placement qualifications remain visible.

## Read saved injury history

Call `fm_get_saved_player_injury_history` with the archive `filename`, original saved `person_index` and the same `expected_snapshot_id`. The reader binds that regular PLAYER's stored history key, then reads its indexed rows from the same archive. Repeat the identical query only when `PERSON_coverage.retry_same_query_to_advance` is true.

Optional inclusive `date_from`/`date_to` bounds select the stored date. `injury_native_ids` selects canonical INJURY IDs from that file. Filters precede `offset`/`limit` paging; rows preserve original order and duplicates. Unknown dates or references that prevent filtering are counted separately. Injury names, date/event meaning, value units and flags remain explicit. A retained row does not assess current injury, availability, recovery or medical clearance.

Set `include_installed_names=true` to add `installed_injury_label` to each returned row and `installed_injury_labels` source metadata. These optional English names come from the exact verified installed database 2600 resource `lang_db/8_6.dat`, keyed by the same-save canonical injury primary ID. Saved `display_name` remains null. The response identifies the external resource hash, source version and explicit language 8; career locale and user/editor override equivalence are unverified. Missing or unsupported resources leave the saved rows available with explicit label states. The default performs no installed-resource access and needs no installed game.

A checked empty vector returns `available_empty`; a negative native owner key returns `no_history_index`. Missing components, unsupported PERSON classes, unreached records and outside-table owner keys remain unavailable or stopped. These states do not establish whole-career absence. The initial owner route supports regular PLAYER records; combined and virtual classes remain unavailable.

## Read saved historical player statistics

Call `fm_get_saved_player_statistics_history` with `filename`, original saved `person_index` and the same `expected_snapshot_id`. It resolves a regular PLAYER's stored archive-owner key from that exact typed record, then reads the selected save's history list and data components. It uses no game session or active temporary-file offsets. A bounded PERSON traversal may stop before the requested record; repeat the identical query on the same server only when `PERSON_coverage.retry_same_query_to_advance` is true.

Optional nonempty `years` and `category_codes` lists filter before `offset`/`limit` paging. Years are exact stored native values: the season-start/end convention remains unproved. Categories retain their native labels and may overlap; do not sum them. Rows preserve original entry order and duplicates. Stored zero counters remain0, and unavailable byte255 values return null. Signed minutes and rating sums retain the source getter semantics. Advanced-array units remain unverified. TEAM/COMP words are unresolved same-snapshot indices, not live links.

`available` can have zero filter matches. `available_empty` means a checked empty owner vector, while `no_history_index` means the native negative owner key. Unsupported classes, unreached records and invalid owners do not imply empty history. Complete used frames, packed bytes and final snapshot identity are checked before cached progress is published. This initial query supports the proved regular PLAYER owner branch and version7/168-byte rows with the observed reference transport. It does not merge current form or starting playing history, certify native loader settings, or claim complete career history.

## Read opaque saved component bytes

Use `fm_get_saved_career` to list the archive's exact full member paths. Pass one returned path, including the archive root, to `fm_get_saved_component_slice` with the same `filename` and required `expected_snapshot_id`. This opens only a listed archive member; it does not accept an arbitrary filesystem path or guess a member from a basename.

`offset` is a zero-based uncompressed byte position. `limit` defaults to 1024 bytes and is capped at 16384. The response returns `raw_hex`, the exact page bounds, `total_size`, `next_offset`, the whole uncompressed `member_sha256` and `packed_sha256`. Offset equal to the member size returns a verified empty page; an offset beyond it fails. Every call streams and validates the entire selected frame, rechecks packed bytes and final snapshot identity, retaining only the requested page. There is no component-slice cache. Existing decoder limits apply: 512 MiB raw member, 256 MiB packed member and 64 MiB window; unsupported or corrupt members fail explicitly.

These are opaque source bytes. A successful read does not identify fields, owners, dates, currencies or football facts, prove native-loader acceptance, or establish completeness of any history or domain. Use the semantic player/history/fixture tools when they cover your question. Other archive members are not claimed validated by this call.

## Inventory saved fixed-record histories

`fm_get_saved_history_inventory` reports structural counts for16 closed, allowlisted history pairs: awards, injuries, starting player/non-player history, person events, archived player statistics, competition history and retained team/club record families. Use the filename and snapshot pin from `fm_list_saved_careers`. No game session or game_db load is used. Other saved components are outside this inventory's coverage.

Counts distinguish source index entries, unique indexed records, repeated references, negative skipped entries, free records, physical records and unaccounted/overlapping slots. Missing pairs and unsupported profiles have unknown counts, rather than zero. Empty data, an empty owner vector and all-free data are separate states. Complete used index/data frames, packed bytes and final snapshot identity are checked with explicit count/byte/slot budgets.

Supply an exact returned `family` and its source-local `owner_index` to page raw bytes and component-relative extents. Owner ordinals are not PERSON indices or native IDs. Raw entries remain explicitly opaque even for families with partially researched semantics; domain-specific saved-player tools remain primary. Original entry order, repeated offsets and negative-offset holes are preserved. No arbitrary component paths, direct free-slot selection, entity joins or inferred football meanings are exposed.

## Find a person by saved name

Call `fm_find_saved_people` with the saved `filename`, its `expected_snapshot_id`, and at least one of `first_name`, `surname` or `common_name`. Supplied parts are a conjunction in their own name namespaces. For example, `first_name="Kylian", surname="Mbappe", match_mode="exact"` searches the archived first name and surname together; `common_name="Rodri", match_mode="exact"` searches the saved alias and can return several people. Multiword surnames stay in one field.

Choose `exact`, `prefix` or `substring` matching. Comparison normalizes Unicode with NFKD, case-folds and removes combining marks, so accented and unaccented input can match. Outer whitespace is stripped; internal spaces and punctuation remain significant. Returned names preserve the source spelling. The default mode is `exact`. Results are grouped by stored PERSON index in ascending order; each group reports its candidate count and any witness-page limits. Use `offset`, `limit` (default 20, maximum 50) and the returned `next_offset` to continue the same query with the same snapshot pin.

This works from the requested archive on a fresh process without a game session or a prebuilt research index. Results describe the supported name-reference/common-suffix search and its work limits. Keep competing matches and incomplete searches explicit, including different matching names or identity words attached to one stored index. The supported common-body span and name-text bound is8192 bytes; a longer valid body is outside that bounded search, not necessarily corrupt. A complete search within that subset does not establish absence from the whole PERSON population; inline names, compact retired-person forms and other unsupported source forms remain outside it. A unique name candidate alone does not certify a full person record.

Pass a returned `person_index` to `fm_get_saved_player_profiles` with the same filename and snapshot ID. The profile lookup checks its own typed start and can still report unavailable, partial, competing or incomplete evidence. A common alias is not a reason to choose one result silently.

## Saved-player profiles and current contracts

For a practical squad question such as “Which players have the strongest passing, and when do their stored current contracts expire?”, get the PERSON indices from `fm_get_saved_club_squads`. Pass 1–32 indices, `filename` and the same `expected_snapshot_id` to `fm_get_saved_player_profiles`. Use `fields=["attributes.passing", "ability", "positions"]` for a compact comparison, or omit `fields` for all supported groups: outfield attributes, positions, goalkeeping, hidden attributes, feet and signed current/potential ability codes. Results preserve requested order and report each person's availability separately. Compare available values, retain ties and account for partial, unavailable, competing and incomplete candidates.

The attribute, goalkeeper, hidden and foot ratings come from the stored PLAYER rating block and its separately stored scale flag; positions use their direct native scale. Missing scale leaves affected ratings null while usable positions and ability remain explicit. Signed potential codes remain signed codes rather than guessed fixed potential or ranges. Each result carries field availability and source/scale context. This query follows locally corroborated regular-player starts in the selected file; it does not certify the whole PERSON record or native loader acceptance.

Set `include_current_contract=true` to add the supported current-contract projection. This option is off by default. It reads the first serialized current-contract slot reached from the checked ACTUAL_PERSON seam, not all offers or historical contracts. Stored signing/expiry dates, status and club-extension options keep their source scope. Dynamic expiry stays unavailable without its independent date anchor, and stored extension options do not prove activation. A missing or unsupported contract remains explicit and does not erase usable ratings.

`current_contract.weekly_wage` reports the stored primary weekly amount, its raw signed value, currency, availability state and source offset. Nonnegative values are whole native base-currency units; zero remains a stored zero. GBP is reported only after the same pinned archive supplies one native currency 86 row named United Kingdom Pound at a stored rate of 1.0. An unverified base currency stays explicit, and negative stored codes keep a null usable amount without an invented sentinel meaning. These are primary-contract wages, including for loaned-out players such as Sanusi and Shahar, not the borrowing club's contribution or total club payroll. Bonuses, auxiliary loans, offers, transfer value, affordability and renewal likelihood are not added to the amount.

## Saved-player form

Call `fm_get_saved_player_form` with `filename`, one `person_index` from a saved squad, and the same `expected_snapshot_id`. This disk query works with the game closed. It requires one locally corroborated regular-player start after completing the bounded candidate and neighbour searches. Incomplete searches, competing starts and unavailable starts remain explicit; the query does not select a candidate by its name or expected statistics.

Use `offset` and `limit` to page the stored rows in serialized group order. The default limit is 50; supported limits are 1–500. Continue `form.next_offset` with the same file, PERSON index, snapshot ID and limit. Each page reports the complete decoded group summaries and total stored row count. A group’s `stored_group_team_index` is an unresolved original same-snapshot `TEAM_BASE` table index (null for `FFFFFFFF`); compare it only with a team’s `database_index` returned by the pinned saved-club-squad query. This group-owner index does not assign a team to each row. Rows retain dates, unresolved team and competition reference words, and stored goals, assists, rating tenths and `stats.played_minutes` when statistics are present. Missing statistics keep played minutes null with `played_minutes_state="not_stored"`. Present zero duration remains zero; it does not mean an unused substitute or identify a starter. Played minutes use the native event-minute clock, without a match-completion or stoppage-time precision claim. The current producer stores 0–127; bytes outside that profile give null played minutes and `played_minutes_state="outside_current_producer_profile"`, while `played_minutes_raw_u8` preserves the stored byte. Native zero-rating rows remain present with an explicit filter flag; duplicates and stored order are preserved. Empty fully decoded groups retain their summaries and differ from an absent section.

`form.state` distinguishes available rows, a checked absent section, an unsupported decoding stop, incomplete candidate searches, competing candidates and unavailable starts. An unavailable or stopped result is not an empty form history. These are stored form rows in a conditional reference profile, not reconstructed fixtures, proof of a completed match, a chronological “last five” view or an aggregate ranking. Complete form groups do not certify the whole PLAYER/PERSON record, native loader acceptance or the unread form suffix. Team and competition words remain unresolved.

## Find clubs in saved career files

Use `fm_find_saved_clubs` with a filename from `fm_list_saved_careers`. This query works with the game closed. It reads the saved full name, short name, database slot, native ID, secondary ID and record kind for ordinary clubs and league bodies. The verified database format has serializer version 4000, source 3754 and minor version 9. Unsupported layouts or invalid rows raise an error.

The optional `name` filter matches a case-insensitive substring of either stored name. The optional `native_id` filter selects an exact ID. Supply both to check an identity or omit both to page through the table in stored order. A page reports the total matches after scanning the entire table. Use `next_offset` and pass the returned `snapshot_id` as `expected_snapshot_id` to keep later pages on the same file. Distinct records can share both names. Empty stored names are returned as null.

## Find competition records and currency rates in a saved file

Use `fm_get_saved_club_squads` with the filename, exact club native ID and snapshot ID from the saved club search. Each team includes its native ID, type code, roster size and ordered player references. Roster sizes count stored slots, including nulls. You can compare teams by native ID across dated snapshots. Player indices apply only to their own file.

Use `fm_find_saved_teams` to browse teams or search for roster overlap. For example, take the member indices for one team from `fm_get_saved_club_squads`, remove nulls and duplicates, then pass them as `person_indices` with the same filename and `expected_snapshot_id`. Select `owner_kind="national"` to see which national-team rosters also list those members. Each match gives the PERSON index and its zero-based position on the other roster. A stored roster entry alone cannot establish a dated call-up.

Set `include_nation_context=true` to return the country linked from each saved national team's owner. Filter by `nation_native_id` to find that country's teams. The installed English name has its own source metadata. If that resource is missing, the saved identity remains available. Some teams appear in more than one national container's team list. The query follows the owner recorded on the team and reports any other containers listing it.

Use `fm_find_saved_competitions` to filter the selected saved career by native ID, signed competition type code, gender and stored extinct flag. The row includes its native IDs, reputation, level and inline name state. The four tested careers omit inline full and short names in all 8,134 records. Their installed language database is a separate source. Omit all filters to include records with unnamed competitions or unrecognized codes.

Set `include_saved_state=true` on `fm_find_saved_competitions` to answer “Which competitions in this snapshot have a stored state component and season code?” The default remains false. Each selected row gains `saved_state` from that same archive's `rgman/comp_<signed-native-id>.dat` component, using the native ID word's signed 32-bit filename form. It reports the component path, stream version and native season discriminator when the fixed prefix is supported. `decoded`, `no_season_code`, `absent` and `unsupported_layout` remain distinct. This reads only a fixed component prefix; its suffix is not validated. The code does not establish a season date range or currentness, stage/table inventory, schedule or champion. Keep the opt-in, filters and snapshot pin consistent across pages.

Use `fm_find_saved_currencies` with a substring of the primary stored name (for example `Euro`) or an exact native ID. The rate is stored in currency units per GBP. Set `include_history=true` for each stored year and rate in sequence. Duplicate years, unusual rates and the underlying float bits remain available. The selection is bound to the saved snapshot and its reported date. For both tools, use a filename from `fm_list_saved_careers`. Continue with the same filters, `next_offset` and the pinned `expected_snapshot_id`. Large currency histories can be paged across records.

## Competition queries

Use `fm_find_competitions` with `name` to search stored names, short names and abbreviations, or `native_id` to look up an identity from a loan condition. String matching uses Unicode case-insensitive substrings. `nation` matches the stored short name or abbreviation; `continent` matches its name or abbreviation. `type_code` selects a native competition type, `gender` accepts male/female, and `is_extinct` selects the stored flag. All selectors combine. Omit every selector to enumerate all native competition records, including unnamed ones. Pass a returned `competition_ref` to `fm_get_competition` for a fresh read that rechecks identity and table membership.

Continue every `next_cursor` with identical selectors, including after empty pages. Each call examines at most `record_budget` records (default and maximum 1,000) and returns at most `max_matches` rows (default 20, maximum 100). `start_index`, `next_index`, `scanned_records` and `stop_reason` describe each page. Results follow native database order. `complete_table_scan` is true only when one call covers the entire table; a completed sequence ends with a null cursor. References expire on detach, save/build changes or cache eviction.

The live census decoded all 8,134 competition records. It preserved 188 records with absent name/short-name strings and 1,319 with absent abbreviations. Missing names remain null; empty strings remain empty. Stored names can differ from localized or generated UI names. Current competition activity and broader competition rules remain undecoded. Resident fixtures use the dedicated tools below. Runtime stages and stored league tables use the dedicated tools below. Direct division assignments are available through the team query below. Reads remain non-atomic. Reproduce the census with `scripts/survey_competitions.py` and public enumeration/search/readback checks with `scripts/verify_competitions.py`.

Pass a `competition_ref` to `fm_get_competition_teams`. Choose `assignment: "current"`, `"next"`, `"secondary"` or `"next_secondary"`. Next-season lists use the corresponding current assignment when the next pointer is absent; each result reports `used_current_assignment_fallback`. These are direct stored division links. They do not establish cup or stage participation, registration or eligibility, and they do not aggregate child competitions. An empty assignment list is not proof of no participants.

Results include native and optional random IDs, the signed native team-type code, owner identity and `team_ref`. Club owners have stored names; national-team containers have a checked nation link. National containers use their own 502-record table, also exposed in the database catalog. Use the team reference with `fm_get_team_squad` or `fm_query_team_players`. These responses add `team` for competition-derived references; `club` is null for national or ownerless teams. Native team-type labels remain undecoded. Names can use unaligned string storage.

The assignment query scans at most 200,000 team records and returns at most 100 matches per call. Continue each `next_cursor` with the same competition reference and assignment, including after empty pages. The verification save contains 66,019 team records: 62,433 ordinary teams and 3,586 national teams. Premier League returned 20 current assignments. All four assignment modes matched an independent table census; national and youth examples opened checked rosters. Reproduce these checks with `scripts/survey_team_assignments.py`, `scripts/verify_team_assignment_layout.py` and `scripts/verify_competition_teams.py`.

Use `fm_get_competition_registrations` for the separate native Registered Teams list. Each row includes a team with a roster reference, a nation, `year` and `registration_identifier` (the editor’s Info field). Year codes 0 and 65535 mean unspecified; negative Info values also mean unspecified. Both raw codes remain available. The identifier’s competition-specific use remains undecoded. Null record slots are counted and skipped; repeated teams remain separate entries.

The optional `year` filter matches a stored year exactly. Omit it to include unspecified records. Continue each cursor with the same competition reference and year filter; `max_matches` is 1–100 and `record_budget` is 1–1000. This is a stored competition configuration list, not proof of current participation, player registration or eligibility. The validation save has 398 records across 33 competitions: 384 have unspecified years, and 14 specify 2025. Its later last-saved date does not make those registrations current. The census found 302 ordinary-team and 96 national-team rows, with three absent nation links. `scripts/verify_competition_registration_layout.py`, `scripts/survey_competition_registrations.py` and `scripts/verify_competition_registrations.py` reproduce the native proof, census and public-query checks.

Each result includes `context` with nation, continent, parent competition, reputation, level, type, gender and extinct flag. Linked records have checked identities and table membership. Parent links contain identity and names without recursive expansion. Nation names use the stored short-name property; localized nation-name formatting is excluded. `fm_get_database_catalog` now also counts continents.

For England’s men’s top division, use `nation: "England"`, `type_code: 0`, `gender: "male"`, `is_extinct: false`. The verification save returned Premier League (native ID 11), level 1 and reputation 187. England’s women’s top division has type 0 and gender female. Other type codes include 1 for domestic divisions, 2 for the main domestic cup, 3 for the league cup and 21 for club champions cups. A false extinct flag does not establish that a competition runs this season.

Type and gender objects retain `native_code`, a nullable name and a state. The installed editor supplies 39 type labels; 21 live records use unmapped codes 30, 40 or 41, and 166 have an unspecified type. Level follows the native property: stored code 100 returns null, otherwise the signed code plus one. The live census found 1,560 unspecified levels and ten zero values; zero is preserved without claiming a meaningful pyramid tier. The census also found 7,675 nation links, 8,025 continent links, 3,731 parent links, 715 female competitions and 2,513 extinct flags. `scripts/verify_competition_context_layout.py` checks the native getters, resource labels, 251 nations and seven continents.

## City queries

Use `fm_find_cities` to search stored city names, or omit selectors to enumerate the table. `name` uses Unicode case-insensitive substrings. `nation` matches the stored national short name or abbreviation; `nation_native_id` selects an exact identity. Other selectors are `native_id`, `minimum_attraction` (0–20), `is_deleted` (the stored DELE flag), `local_region_native_id`, `language_native_id` and `weather_native_id`. The region selector follows the native reverse city relationship. The language selector uses only the direct city field; a null field does not fall back to regional languages. All selectors combine. Each call examines at most 1,000 records and returns at most 100 matches. Continue every cursor with identical selectors, including after empty pages. Results follow native database order.

Pass a returned `city_ref` to `fm_get_city` for fresh fields. Stadium search and readback also return city references. Names, coordinates, population category, attraction and nation/language/local-region/weather summaries come from stored native fields. Population is a category rather than a current headcount. Weather identifies a database record; it does not describe current conditions. Linked geographic summaries contain checked IDs and stored names. Open `language_ref` or `local_region_ref` with their detail tools. Open `weather_ref` with `fm_get_weather_profile` for the stored periods described below.

Altitude returns `native_value`, `unit: null` and `state: "unit_unverified"`. The census contains values from -1,312 to 16,390, outside the editor's stated bounds; the reader preserves them without inventing a unit or clamping them. Unknown population codes and invalid coordinates remain explicit. City references bind to identity and canonical table membership. Ordinary fields and geographic links refresh; changed identities, save/build changes, detach and cache eviction expire references.

Reproduce the native proof with `scripts/verify_city_layout.py`, the independent raw censuses with `scripts/survey_cities.py` and `scripts/survey_city_linked_records.py`, and public-query comparisons with `scripts/verify_cities.py`. Reads remain non-atomic.

The 0.30.0 city validation compared all 58,329 public records with an independent raw census and checked 82 readback cases. A combined name/nation/deletion filter covered the full table; five additional filter checks covered bounded prefixes of 2,330–3,000 records each, including empty pages. The full test gate passed 1,724 tests. Stadium relationship validation covered all 25,891 records, including 25,891 city links, 5,152 owner-club links and 2,181 nearby-stadium links. Six relationship readback cases and a fixture → St. James’ Park → Newcastle traversal passed.

## Language and local-region queries

Use `fm_find_languages` to enumerate languages or filter by name, native ID, nation name/abbreviation, nation ID, maximum difficulty, minimum influence and the native deletion predicate. Names use Unicode case-insensitive substrings. All selectors combine. `fm_get_language` refreshes a returned reference, including references from city fields and region language entries.

Language details expose stored nation, difficulty, influence and family/group/subgroup classifications. The installed editor supplies 109 family labels, 22 group labels and 24 subgroup labels. Live records also contain codes absent from those dictionaries, including family 0; these retain `native_code`, `name: null` and `state: "unmapped"`. Native `DELE` means family equals -1. Ratings do not predict a player's fluency or learning time.

Use `fm_find_local_regions` to enumerate regions or combine name, native ID, nation name/abbreviation, nation ID, minimum population and direct `weather_native_id` filters. `fm_get_local_region` opens a search or city reference. Details include stored population, nation/weather summaries and the complete stored language list. Each entry preserves its native order, language reference and percentage. Percentages can total above 100; keep each value separately. Null languages, duplicate entries and out-of-range percentages remain explicit. The reader rejects malformed vectors or vectors with more than 1,000 allocated entries instead of returning a partial list. Population freshness is unverified; zero remains stored. Weather identifies a database record rather than current conditions.

For a region's cities, call `fm_find_cities(local_region_native_id=...)` and continue every cursor. The native implementation also derives this relationship from the city table. Region results do not embed an incomplete city list. Language and region references bind to identity and canonical membership. Ordinary fields and linked targets refresh; child references bind independently. Save/build changes, detach and cache eviction expire references.

Both searches return at most 100 matches and examine at most 1,000 records per call, in native table order. Follow every cursor with identical selectors, including empty pages. The 0.31.0 test gate passed 1,814 tests. Public comparisons matched all 126 languages, 2,523 regions, 1,503 region-language entries and geographic links across 58,329 cities. Ten complete filter scans passed, including all 47 cities in Newcastle’s region. A separate direct-language city filter matched the first 3,000 examined records; that check was bounded. `scripts/verify_language_region_layout.py` checks native spans and editor definitions; `scripts/survey_language_regions.py` records an independent raw census; `scripts/verify_language_regions.py` compares public results and city links with the censuses. Reads remain non-atomic.

## Weather profiles

Use `fm_find_weather_profiles` to enumerate the weather table or combine a Unicode case-insensitive name substring with a native ID. Open a returned `weather_ref` with `fm_get_weather_profile`. City and local-region weather summaries also carry references. To enumerate their direct stored relationships, call `fm_find_cities(weather_native_id=...)` or `fm_find_local_regions(weather_native_id=...)` and follow every cursor. A null city link does not fall back to a regional profile.

Each profile contains four periods in native order. Start days remain native integers because calendar conversion and season names are unverified. Wind, precipitation and temperature categories retain signed stored weights and totals; the reader never normalizes them. Values outside 0–100 remain explicit. Category labels come from the installed editor. Its temperature ranges differ from the runtime generation tables, so the labels must not be used as generated temperature intervals.

Day/night variance preserves its raw signed value. Native value 100 returns `value: null` and `state: "not_specified"`; other values retain `unit: null` and `state: "unit_unverified"`. The native getter returns a null property for 100, and a runtime path substitutes 10. The query reports the stored state without applying that runtime default. These profiles do not establish a forecast, current weather or match conditions.

The 0.32.0 test gate passed 1,858 tests. Public comparison matched all 373 profiles (1,492 periods), weather links across all 58,329 cities and all 2,523 local regions, including 549 region links and 1,974 null region links. The completed comparison includes 29 profile readbacks and linked-target readbacks; it preserves all 272 unspecified variance values. Four weather filters and complete reverse-link filters passed, including 1,249 cities and four regions using the sampled profile. Searches examine at most 1,000 records and return at most 100 matches per call. Continue all cursors with identical selectors, including empty pages. References bind to native identity and canonical table membership; ordinary fields refresh. Reads remain non-atomic. `scripts/verify_weather_layout.py` checks all 88 period fields, editor labels/bounds and the null sentinel; `scripts/survey_weather_profiles.py` records an independent raw census; `scripts/verify_weather_profiles.py` compares public profiles and geographic links with the censuses.

## Stadium queries

Use `fm_find_stadiums` with `name` to search stored names and continental names by Unicode case-insensitive substring. Other selectors are `native_id`, `minimum_capacity`, `is_extinct` and `is_training_ground`. All selectors combine; minimum capacity compares the stored total capacity. Omit selectors to enumerate the table. Each call scans at most 1,000 records and returns at most 100 matches. Continue every `next_cursor` with identical selectors, including after empty pages. Results follow native database order.

Pass a returned `stadium_ref` to `fm_get_stadium` for fresh details. Fixture results also contain a nullable `stadium` summary with a usable reference. Both routes recheck the stadium's runtime type, native identity and canonical table membership. Identity or membership changes expire references; ordinary field changes refresh on readback. Save/build changes and detach discard references.

Stadium search and readback include nullable `city`, `owner_club` and `nearby_stadium` links. Open their references with `fm_get_city`, the club tools, or `fm_get_stadium`. Owner-club links do not establish legal ownership, and nearby-stadium links do not prove distance, groundsharing or fixture allocation. Nearby stadiums remain summaries, so cycles do not expand recursively. A changed link refreshes on readback; each returned child reference binds independently to its target record.

Details include both stored names, coordinates, five capacity fields, pitch type/condition/rates, dimensions, stadium condition, environment, owner type, facility flags and built/rebuilt/required-pitch-relay dates. Dimensions are metres decoded from native tenths; default, international, minimum and maximum values remain separate. Used and all-seater capacities at or below zero are unspecified. Zero seating is a stored value. Unknown enum codes remain explicit. National-team usage retains the stored senior/U21/U19 categories, from No Matches through the native match-importance groups. These categories do not establish fixture allocation or eligibility. Dates preserve valid native years, including source outliers such as 2932; invalid dates retain their raw year/day without an invented date.

Stadium details reached from historical fixtures describe the current stored stadium record; they do not reconstruct its name or capacity on the match date. Capacity does not establish attendance or match suitability. The stored covered flag does not describe the current roof position. The native UI may choose international pitch dimensions or continental names according to context; these tools return the separate stored fields. Stadium sides, capacity changes and construction plans remain unfinished.

`scripts/verify_stadium_layout.py` checks the native fields, editor labels and metric formatter. `scripts/survey_stadiums.py` records an independent raw census. `scripts/verify_stadiums.py` compares public enumeration, filters and readbacks with that census, then compares fixture pages with fresh independent native reads. All work uses background memory reads and offline installed-resource analysis.

The 0.29.0 stadium release checked all 25,891 stadium records and 66,802 resident fixtures across 2030 and 2027, plus 1,648 passing tests. Each fixture year covered all 365 calendar days. The 2027 archive had 48 unloaded groups, which remain unavailable; these counts cover resident records. The game advanced during verification, so the combined scan is not one atomic save snapshot.

## Currencies and conversion

Use `fm_find_currencies` to enumerate stored currency records or combine a Unicode case-insensitive name substring and native ID. Results contain `currency_ref`, a stored name and the current stored exchange rate in currency units per GBP. Find European Euro by name or native ID 28, United Kingdom Pound by 86 and United States Dollar by 87. These are native IDs, not ISO codes. Continue every cursor with identical selectors, including empty pages. Calls examine at most 1,000 records and return at most 100 matches.

Use `fm_get_currency` to read a currency's complete historical year/rate vector. Entries retain native order, duplicate years, zero rates and invalid years. Float values retain their original 32-bit representation; non-finite values return null with explicit state. Three additional serialized text fields retain native offsets and unverified meanings. They are research data, not proven ISO codes or formatting prefixes/suffixes. Names retain stored strings rather than native localization overrides. Malformed history vectors or allocations above 2,048 entries fail without returning a partial history.

Use `fm_convert_currency` with two currency references and a plain decimal string such as `"1000000"` or `"-250.50"`. The result applies `amount * to_rate / from_rate` to current stored game rates. It returns a decimal string with 50 significant digits, rounding once after exact rational arithmetic. Negative amounts support balances; zero, negative or non-finite rates return an explicit unavailable result. Both identities, both rates and the native GBP basis are checked in the same read. Existing budget-comparison tools continue to accept GBP.

Stored conversion does not reproduce currency display rounding, historical-rate interpolation or runtime formatter overrides. Rates belong to the game, not current real-world markets. The observed runtime table has 66 slots: 64 match loaded records and two retain rates without a matching database record. Database presence alone therefore does not establish UI selectability. References refresh ordinary fields and expire after identity/membership/save/build changes, detach or cache eviction.

The 0.34.0 gate passed 2,002 tests. Live MCP comparison matched all 173 records and readbacks, all 9,410 historical entries, six complete filtered scans and 347 conversion cases. Raw records matched before and after verification on 27 October 2030. `scripts/verify_currency_layout.py` checks native field/history routes, conversion direction and the installed editor's GBP basis. `scripts/survey_currencies.py` reads an independent raw census; `scripts/verify_currencies.py` compares every public record/history and conversions in both directions against the stored rates.

## Stadium changes

Use `fm_find_stadium_changes` to enumerate stored change records. Combine `native_id`, `team_native_id`, `stadium_native_id` and `type_code` selectors. The stadium selector matches any current, new or alternative stadium link. Find a stadium's ID with `fm_find_stadiums`. Follow every cursor with the same selectors, including after empty pages; calls scan at most 1,000 records and return at most 100 matches.

Open `stadium_change_ref` with `fm_get_stadium_change` to refresh fields. Nullable team references open rosters with `fm_get_team_squad`; stadium references open details with `fm_get_stadium`. Missing teams or current stadiums do not exclude records. Links can change independently of the parent identity, and each child reference remains bound to its own record.

Details retain separate start, leave and latest-move dates, capacities, attendance estimates, training/youth levels, stadium condition and the potential-move flag. Type labels come from the installed editor; type 2 remains unmapped. Signed -1 is unspecified and zero remains stored. Rental cash, development fund and expected season tickets keep raw values with unknown units/scales. The editor marks both rental cash and season tickets with `store_pence`, so a ticket count or currency conversion is not established. Move likelihood is a stored level, not a verified probability. These records do not establish whether a project is active or complete, when construction finishes, or which stadium a team currently uses.

The 0.33.0 gate passed 1,927 tests. Public verification matched all 36 records and all 36 readbacks, opened 18 team links and 54 stadium links, and passed ten complete filtered scans. The raw records stayed unchanged across verification on 27 October 2030. The native verifier checks 21 property routes, date packing, signed null sentinels, table/record RTTI and editor labels. `scripts/survey_stadium_changes.py` records a raw census; `scripts/verify_stadium_changes.py` compares all public fields, readbacks and filtered scans, opens linked teams/stadiums, and checks that the native records stayed unchanged across validation.

## Fixtures and stored results

Use `fm_get_fixture_rules(session_id, fixture_ref)` for one resident fixture returned by `fm_find_fixtures` or `fm_get_next_match_squad`. It returns separate home/away declared named and used substitute caps and the native stoppage limit. Unknown stoppage sentinels remain null. These limits do not confirm individual eligibility or additional stage restrictions; extra-time substitute additions remain unknown.

The same query reads that fixture’s effective stored draw rules. Supported patterns distinguish extra time, penalties after ninety minutes and a replay; unfamiliar combinations retain their raw flags with an unavailable combined decision. The checked Newcastle–Arsenal Fourth Round fixture declared nine named substitutes, five used in three stoppages, and penalties after ninety minutes without extra time or a replay. Other rounds can differ. These are current stored settings, not standard rules inferred from a competition name. Changed fixture identity or source bytes require a fresh search.

Call `fm_get_fixture_coverage` to see the resident calendar years and each year’s materialized and unavailable groups. `main_year` is the fixture manager’s stored year; it does not establish the current game date. Missing years and unloaded groups remain unavailable. These tools never trigger archive loading.

Use `fm_find_fixtures` with a listed `year`, optional `team_native_id` or `competition_native_id`, and inclusive `date_from`/`date_to` bounds in `YYYY-MM-DD` format. All selectors combine. Team IDs come from the existing squad, competition-team and standings tools; competition IDs come from competition queries. In the validation save, Newcastle’s team ID is 688 and the Premier League’s competition ID is 11. For example, `year=2030`, `team_native_id=688`, `date_from="2030-09-01"`, `date_to="2030-09-30"` selects the resident September fixtures involving Newcastle.

Each row contains home/away team references, a stored competition reference, a nullable stadium summary/reference, date, native record kind and scores. Use its `stadium_ref` with `fm_get_stadium`. A changed venue pointer or venue identity expires the fixture reference; repeat the search. `days_from_current_date` is the calendar-day difference from the response’s `save.current_date`: zero means the same date, positive means a later date, and negative means an earlier date. This does not establish kickoff countdown, match completion or match eligibility. `record_kind="result"` selects result objects; it does not prove completion. `record_kind="fixture"` selects base fixture objects. Normal-time, extra-time, penalties and aggregate pairs preserve absent values as null. `final_score` follows the native extra-time-then-normal-time fallback and excludes shootout goals. Aggregate values remain separate; half-time scores remain undecoded. Null opponents and competitions stay explicit.

`kickoff_time` contains `time` as HH:MM, `state`, `native_code` and `timezone`. The timezone is null because the stored clock’s timezone has not been established. Codes 1–72 map to 06:00–23:45 in quarter-hour steps; code 127 maps to 17:55. Code zero returns `no_time_code`, the native unset-date sentinel returns `unset_date`, and codes 73–126 return `unmapped_time_code`; these states keep time null. Do not infer midnight or UTC from a null field. A changed kickoff time expires the fixture reference; repeat the search.

Set `include_stage: true` on `fm_find_fixtures` or `fm_get_fixture` to add `stage_link`. It resolves the top-level runtime stage only when the native fixture and runtime season codes match. Use the linked `stage_ref` with `fm_get_standings` when `standings_available` is true. Shared runtimes retain their actual competition owner. Different seasons, absent runtimes, negative/out-of-range slots, null slots and empty stages return explicit unavailable states. Group-child resolution and historical stages remain unfinished. The exposed season codes are native discriminators; their start/end dates are not decoded. A changed runtime season code expires stage references.

`fixture_name` is null when the stored fixture-name link is absent. Otherwise, it contains its native ID/index, three `stage_names` slots and an optional `secondary_competition`. Each nonnull name slot exposes its native ID/index, `name`, `short_name` and `plural_name`; null strings and empty strings remain distinct. For example, Newcastle’s Carabao Cup record contains “Third Round” and its Champions League records contain “League Phase.” Slots retain stored order and null entries; they have no fixed stage/round/leg roles. These are stored components, not a generated or localized display name, and do not prove runtime-stage membership. Use a secondary competition’s native ID with `fm_find_competitions`. Changes to component pointers expire the fixture reference; text changes refresh on readback.

Continue every `next_cursor` with identical selectors, including after an empty page. Page limits may change. `record_budget` bounds records, `bucket_budget` bounds day/group slots, and `max_matches` bounds returned rows. Keep `include_stage` identical across cursor pages. Ordering is calendar day then native group/slot, not kickoff time. `reached_resident_range_end` means that the requested resident range was scanned; it does not establish full-save coverage. The selected year’s unavailable group indices accompany every page. During simulation, calendar replacement can expire cursors; restart the affected query with a narrow date window.

Pass a `fixture_ref` to `fm_get_fixture` for a fresh read. References recheck the year inventory, bucket, raw fixture identity and database links. A changed route or identity requires a fresh search. Stored score changes can be refreshed without changing identity. Team references open roster/player queries; competition references open competition details and runtime stages. Historical stage reconstruction remains unfinished.

`scripts/verify_fixture_layout.py` checks native traversal and score formatters. `scripts/survey_resident_fixtures.py --year YEAR` records an independent census of loaded groups; `scripts/verify_fixtures.py` compares public queries with the census. The validation census contains 32,438 records in all 66 groups for 2030, and 19,350 results in 18 loaded groups for 2025, with 48 archived groups unavailable. The archive count is partial.

## Competition stages and standings

Pass a `competition_ref` to `fm_get_competition_stages`, then pass a `stage_ref` with `standings_available: true` to `fm_get_standings`. The catalog includes top-level stages and league children of group stages. `path` contains zero-based vector slots; it does not name a round or season. `runtime_competition` identifies the actual owner when several database competitions share runtime state. Null slots, absent runtimes and empty vectors remain distinct. Cup and cup-group contents remain undecoded.

Each table row includes its stored position, team identity and roster reference, plus `overall`, `home` and `away` statistics. These expose played, wins, `draws_or_penalty_wins`, losses, `penalty_losses`, goals for/against/difference and points. Played can include games carried from another stage. The native draw counter also counts penalty wins; penalty losses have their own counter. `point_rules` exposes the stored awards for six result categories. Points may include adjustments, so do not reconstruct them from generic scoring rules.

Rows retain native stored order. Home and away statistics use that same order. An unknown sorting view returns null positions and its raw `native_order_view_code`. An unassigned team remains an explicit row. Stored order does not prove freshness, season, finality or eligibility. No game function runs to refresh a table.

The catalog accepts at most 1,024 slots and rejects larger structures explicitly. Each table returns every stored row. References bind runtime ownership, stage identity and the route through the vectors; changed membership requires a fresh reference. Reads recheck consumed bytes before returning rows or publishing references, but remain non-atomic. `scripts/verify_league_stage_layout.py` verifies native getters, sorting and point-rule paths; `scripts/survey_competition_stages.py` captures the native census; `scripts/verify_competition_stages.py` compares public queries with it.

Public MCP checks matched all 1,452 runtime-linked competition catalogs and all 417 distinct league tables in the verification save: 3,201 rows, seven unassigned teams and 162 shared-runtime links. Every overall/home/away field, point rule, stored position and team identity matched the independent census. Ordinary and national-team references opened checked rosters. The full test suite passed 1,471 tests.

## Save-wide recruitment queries

Use `fm_query_save_players` to search regular and combined player/staff records without knowing their names or clubs. `minimum_attributes` and `maximum_attributes` accept the 36 outfield attribute names. `minimum_profile` and `maximum_profile` accept the profile paths below. Bounds are inclusive: 0–200 for ability and 0–20 for other ratings. Optional `born_on_or_after` and `born_on_or_before` use YYYY-MM-DD. These dates avoid assuming a current game date or age. `name_contains` adds the existing full/common-name substring filter.

For example, search with `born_on_or_after: "2010-01-01"`, `minimum_profile: {"ability.potential": 170, "positions.striker": 15}`, `minimum_attributes: {"pace": 15}` and `maximum_profile: {"hidden_attributes.injury_proneness": 12}`. This returned 19 records in the verification save. It does not establish their prices, interest, availability or scouting visibility.

Results contain full profiles and checked `player_ref` values in native database order. They are not a global ranking. Continue every `next_cursor` with the same criteria and name, including after empty pages. `record_budget` bounds the person records examined per call; `max_matches` bounds returned candidates, including `unclassified_players`. Unknown required fixed potential stays unclassified after known failures are excluded. Virtual, retired and staff-only record types are counted but not searched. Reads remain non-atomic across and within pages.

Live verification traversed 170,220 person records, including 65,899 regular/combined players. A current-ability threshold of 190 found six players; five smaller pages returned exactly the same records as one full scan. Exact queries covering all 78 numeric fields plus birth date matched independently read regular and combined player/staff profiles. Native tests use a disposable process for direct/fifths scaling, negative potential, birth dates, malformed inputs and continuation. Run `scripts/verify_recruitment.py` to repeat the live checks. This does not establish complete decoding of every person subtype or every field in the save.

## Player profiles and squad selection

Set `include_profile: true` on `fm_get_player`, `fm_get_managed_squad` or `fm_get_team_squad`. Each player gains a `profile` object. Defaults preserve the existing 36-attribute response. Regular players, combined player/staff and identity-checked cached virtual players use the same verified profile fields.

| Profile group | Fields and meaning |
| --- | --- |
| `ability` | `current` and `potential` use the native 0–200 scale. These are underlying values, not scout stars or perceived potential. Negative potential codes return a null fixed potential, their native code, and an editor-defined range when mapped. |
| `positions` | Fourteen 0–20 ratings: goalkeeper; left/central/right defender; defensive midfielder; left/central/right midfielder; left/central/right attacking midfielder; striker; left/right wing-back. Keys use underscores, such as `defender_central` and `wing_back_left`. |
| `goalkeeping` | `aerial_reach`, `command_of_area`, `communication`, `eccentricity`, `handling`, `kicking`, `one_on_ones`, `reflexes`, `rushing_out`, `tendency_to_punch`, `throwing`. |
| `hidden_attributes` | `consistency`, `dirtiness`, `important_matches`, `injury_proneness`, `versatility`. Higher values are not uniformly desirable. |
| `feet` | Numeric `left` and `right` strength ratings. |
| `personality` | Direct 0–20 `adaptability`, `ambition`, `controversy`, `loyalty`, `pressure`, `professionalism`, `sportsmanship` and `temperament`. |

Ratings follow the native scaling flag: fifths convert to 1–20; direct values retain 0–20. Position and personality ratings remain direct. Virtual controversy follows the native getter’s fixed zero; `personality_native_defaults` identifies that field. Other virtual personality ratings come from the existing checked cache. The decoder preserves potential ranges without converting them to a fixed estimate. Scouting masks, perceived ratings, tactical role scores, match availability and selection eligibility are outside these fields.

`fm_query_team_players` accepts `minimum_profile` alongside existing attribute and loan filters. Use field paths such as `ability.current`, `positions.goalkeeper`, `goalkeeping.reflexes`, `hidden_attributes.consistency`, `feet.left` and `personality.professionalism`. `sort_by` accepts those paths or an existing outfield attribute. Minima are inclusive; ability bounds are 0–200 and other bounds 0–20. Results sort descending, with full match counts and truncation. A range-coded potential appears under `unclassified_players` when the query needs fixed potential.

For example, use `minimum_profile: {"positions.goalkeeper": 15, "goalkeeping.reflexes": 14}`, `sort_by: "ability.current"` and `loan_status: "not_on_loan"` to compare the team’s qualifying goalkeepers. Use `minimum_profile: {"ability.potential": 160}` and `sort_by: "ability.potential"` for a potential-based shortlist. Virtual players stay excluded unless `include_virtual: true`.

Installed editor labels and native getters establish all 42 profile fields, including virtual delegates. A background survey checked 65,899 regular/combined records; every one used fifths scaling. Live verification covers all 79 Newcastle roster entries, including 13 cached virtual profiles, fresh readback and selection queries. No foreground UI comparison was performed for these added fields.

## Personality queries

Use `minimum_profile: {"personality.professionalism": 15, "personality.pressure": 14}` and `sort_by: "personality.ambition"` with `fm_query_team_players`. These filters can combine with position, ability, outfield-attribute and loan criteria.

Staff reads include personality when `include_attributes: true`. For `fm_query_club_staff`, use `minimum_personality: {"professionalism": 15}` and `sort_by: "personality.pressure"`; combine them with staff-attribute minima and `job_contains`. All minima are inclusive and sorting is descending. Higher values are not uniformly desirable, particularly for controversy. These numeric ratings do not supply a personality description, mentoring recommendation or predicted development.

`verify_personality_layout.py` checks installed labels, property paths, native getters and virtual delegates. `verify_personality.py` checks fresh reads for 79 roster entries and 93 staff, agreement between both routes to a combined player/staff record, and 15 query cases. The checks use background memory reads; no foreground UI comparison was performed.

## Stored club finances

Call `fm_get_club_finances` for your managed club, or pass `club_ref` from `fm_find_clubs`. Choose either `club_ref` or `coach_name`. The response exposes `balance`, `weekly_wage_budget` and `stored_transfer_budget` in whole GBP. Negative balances and transfer-budget values are preserved. `weekly_wage_budget` is the total weekly budget.

`remaining_weekly_wage_budget` follows the native `Cwrb` property: total budget minus its stored wage-spending aggregate, with a zero-budget special case. The object returns `amount`, `weekly_spending_used`, `state`, `reason` and `freshness: "stored_without_refresh"`. Overspending produces a negative amount. Missing/base finance records, inactive game routing, spending refresh markers and arithmetic overflow produce explicit unavailable results. The calculation reads the game's aggregate; it does not sum main contracts. Its detailed components and freshness since the last game recalculation remain unverified.

Call `fm_check_wage_budget` with `additional_weekly_wage_gbp` to compare an additional amount against that remaining budget. It returns `fits_remaining_wage_budget` and `budget_after_additional_wage`, both null when unavailable. You supply the additional cost; the tool does not calculate bonuses, loan contributions, future commitments or complete offer affordability.

Call `fm_get_wage_contributions` to inspect the live transfer manager's weekly wage contributions. It defaults to your club; choose `club_ref`, `coach_name`, or `all_clubs: true` for the whole native list. Each record supplies the paying club, receiving club, person, whole-GBP weekly amount and stored `paid_until` date. Club and person references support further queries, including staff references for former players who now have staff records. Results sort by amount descending and return incoming, outgoing and net outgoing totals for a selected club. An empty result means no entries in this list, not no loan costs or other commitments.

The contribution reader checks every list entry within a 1,024-record bound and rejects overflow instead of truncating. Unknown person types keep their financial record with an explicit unavailable identity. Native creation, property and save-serialization routines establish the record fields; the finance updater establishes the payer and weekly units. No current-date payment eligibility, full loan-cost breakdown or foreground UI comparison is claimed. Reproduce the checks with `scripts/verify_wage_contribution_layout.py` and `scripts/verify_wage_contributions.py`.

The stored transfer budget precedes native availability rules. `current_transfer_budget` contains `amount`, `state`, `reason` and evidence. The verified normal-career property path checks game mode, native club relationships and the native rule that maps positive budgets below £500 to zero. Unsupported alternative-mode, dated-global-rule and manager-adjustment branches return null with reasons. Base finance records expose only their balance and have no native current-budget property; missing fields remain null and listed in `unavailable_fields`. A null finance pointer produces `no_finance_record`, with null amounts rather than zero. Unknown types or changed getters fail the query.

Call `fm_check_transfer_budget` with `upfront_fee_gbp` to compare one upfront fee with the current budget. It returns `fits_current_transfer_budget` and `budget_after_upfront_fee`; both remain null for unavailable budgets. This is arithmetic, not a complete offer-affordability decision. Wages, signing/agent fees, instalments, conditional payments, pending offers, seller demands, registration and board approval are outside the calculation.

Native-code and resource verification traces the club finance pointer, both finance types, balance and wage property getters, the remaining wage-budget calculation, the raw transfer-budget branch and the supported current-budget adjustment route. Live stdio checks cover managed/selected clubs, repeated readback, fee and wage comparisons, and reference rejection. No foreground UI comparison is claimed. Optional details include live loan terms and the native scouting budget. Staff/bonus/tax breakdowns, complete future commitment schedules and UI currency formatting remain unverified. The separate committed-wage tool recomputes current and committed native totals. Run `scripts/verify_club_finance_layout.py`, `scripts/verify_transfer_budget_layout.py`, `scripts/verify_wage_budget_layout.py` and `scripts/verify_club_finances.py` to reproduce these checks.

## Stored health and injury records

Set `include_health: true` on `fm_get_player`, `fm_get_managed_squad` or `fm_get_team_squad`. The `health` object contains `condition` and `match_sharpness` in native 0–10000 units, signed native `fatigue` (higher means more fatigued), `injury_record_count`, and `injuries` with a name, sentence name and `started` date. Zero remains zero. Fatigue accepts the full signed 16-bit storage range; the editor’s narrower −500 to 1000 editing range does not define every possible stored value.

These readings use `state: "stored_without_refresh"`. Native condition, sharpness and fatigue getters can refresh internal data; this reader never executes that refresh. The UI condition property can also return an unavailable sentinel for an injured player. Stored readings therefore do not promise equality with freshly calculated UI values. Injury-vector presence can include injuries that permit participation and does not establish match eligibility or training clearance. Recovery dates, treatment details and medical forecasts remain unfinished.

Virtual players return `state: "partial_virtual"`: condition and sharpness are null and listed in `unavailable_fields`. Their native getters supply fixed zero for fatigue and injury-record count; `native_defaults` identifies those values. Virtual condition and sharpness require a different calculation, which remains undecoded.

Use `minimum_health: {"condition": 9000, "match_sharpness": 9000}`, `maximum_health: {"fatigue": 0}` and `injury_records: "without_records"` with `fm_query_team_players`. `injury_records` also accepts `any` or `with_records`. `sort_by` accepts `health.condition`, `health.match_sharpness` or `health.fatigue`, descending. Health bounds are inclusive and combine with existing attribute/profile/loan filters. Required unknown values appear under `unclassified_players` after records that fail known criteria are excluded.

The database catalog now includes 136 typed injury definitions. Background verification covers 79 roster entries, 13 virtual states, six named injury records, combined player/staff and 20 health-query cases. Four injury records belong to the senior vector and two to youth vectors. These are native-record checks without foreground UI validation. Layout and live verification scripts are `verify_player_health_layout.py` and `verify_player_health.py`.

## Contract dates and expiry queries

Set `include_contract_dates: true` on `fm_get_player`, `fm_get_staff` or `fm_get_club_staff`. Player reads return `contract_dates`; staff reads return `contract.dates`. Fields are `joined`, `last_signed`, `expires`, `state` and `evidence`. Staff date requests also return the contract club. Default responses omit dates.

A `fixed_expiry` state supplies all three dates. A `basic_contract_fields_unavailable` state supplies the person’s joined date and leaves signing/expiry null. `dynamic_expiry` supplies a computed expiry plus `expiry_anchor_date`. It follows the native getter: advance the anchor year, preserve the ordinal day, and clamp day 366 when the following year has 365 days. This differs from a calendar anniversary around leap years. The anchor is the getter’s date source; its wider meaning as a game clock is not established. `no_contract` means the native contract pointer is null. Invalid dates fail the read. Virtual-player dates remain unsupported; these fields describe the main contract, not a loan’s end date.

Call `fm_query_club_staff_contracts` with `expires_on_or_before: "2031-06-30"` to find fixed expiries, earliest first. Select another club with `club_ref`, or another active manager with `coach_name`. The query returns full match counts, truncation and every unclassified staff member separately; unclassified members are not confirmed nonmatches. Computed dynamic expiries stay in `unclassified_staff` because this query selects fixed commitments. The date is inclusive and can include already expired contracts. Renewals and departure predictions are outside this query.

Live stdio checks on 6 November 2026 verified date readback for 93 Newcastle staff and 28 managed-squad players, the combined player/staff layout, both Liverpool lists, and expiry filters. Newcastle had 17 fixed staff expiries by 30 June 2031, 92 fixed contracts in total, and one basic contract. These checks use native getter semantics and fresh memory reads; they do not establish foreground UI equivalence. The dynamic calculation is verified against installed instructions and every valid date in 1850–2199. No dynamic contract was found in the supported records during the person-table survey, so a live dynamic-record comparison remains unavailable. Stored clauses are available through `fm_get_contract_terms`; activation rules and future contracts remain unfinished. Stored loan agreements are available through `fm_get_loan_contract`.

## Current contract status

Set `include_contract_status: true` on `fm_get_player`, `fm_get_staff` or `fm_get_club_staff`. Player reads return `contract_status`; staff reads return `contract.status` and include the contract club. Fields are `title`, `native_code`, `state` and `evidence`. Defaults omit status.

The verified labels are Part Time (0), Full Time (1), Amateur (2), Youth (3) and Non-Contract (4). A non-contract agreement is distinct from a null contract pointer. Basic contracts return `basic_contract_status_unavailable`; null pointers return `no_contract`. Unlabelled codes retain their signed native value with `unmapped_native_status` and a null title. The live survey found 14 full contracts with code 10; its meaning remains unresolved.

These fields describe the current contract’s `Pcst` status. Specialized league contract types use a separate property and remain unsupported. Virtual-player status remains unsupported. Native fresh-read checks cover Newcastle staff, managed players, both routes to a combined player/staff record, all five labels and code 10; they do not establish foreground UI equivalence.

## Weekly contract wages

Set `include_wage: true` on `fm_get_player`, `fm_get_staff` or `fm_get_club_staff`. Player reads return `wage`; staff reads return `contract.wage` and include the contract club. The object supplies `amount`, `currency: "GBP"`, `period: "week"`, `state` and `evidence`. A null contract pointer yields `state: "no_contract"` and null amount/currency. Zero is retained; negative amounts or changed ownership/units fail. Virtual-player wages remain unsupported.

Call `fm_query_club_staff_wages` to rank the checked staff list by weekly amount, highest first. `minimum` and `maximum` are inclusive GBP-per-week bounds. The response reports full match counts, truncation, and sums across the checked roster and all matches before limiting. For example, `{"minimum":5000,"maximum":14000,"limit":5}` returns the five highest amounts within those bounds.

These are stored weekly main-contract amounts. They exclude bonuses, clauses, loan contributions and UI currency/period rounding. A roster sum is not a club wage budget, actual payroll, net pay or total employment cost. Native cash semantics and the live base-currency record establish GBP; no foreground UI comparison was performed. The database catalog now also counts the 173 live currency records.

## Contract cash bonuses

Set `include_contract_bonuses: true` on `fm_get_player`, `fm_get_staff` or `fm_get_club_staff`. Player reads return `contract_bonuses`; staff reads return `contract.bonuses` and include the contract club. Defaults omit these fields.

The object contains `currency: "GBP"` and six entries under `bonuses`: `appearance_fee`, `goal_bonus`, `assist_bonus`, `clean_sheet_bonus`, `unused_substitute_fee` and `international_cap_bonus`. Each entry supplies `amount`, `state` and `matching_entry_count`. Stored zero remains zero. An absent entry returns a null amount with `not_present`. Duplicate entries follow the native getter's first-match rule and retain their count.

`native_entry_count` counts every entry in the checked main-contract vector; `other_entry_count` counts entries outside these six kinds. Those other entries are not decoded. Basic contracts return `basic_contract_bonuses_unavailable`; null contract pointers return `no_contract`. Virtual-player bonuses remain unsupported. Invalid ownership, dispatch, vector bounds, currency or negative known amounts reject the query.

These are stored cash terms, not weekly estimates or payment totals. Qualification rules and UI visibility remain unfinished; stored loan agreements have a separate query. The broader stored-entry query below adds clause fields. `scripts/verify_contract_bonus_layout.py` checks installed editor labels and native property dispatch, vector traversal and cash selection. `scripts/verify_contract_bonuses.py` checks Newcastle's player and staff queries, repeated readback, combined player/staff parity, strict arguments and expired sessions without using the foreground UI.

## Stored loan agreements

Call `fm_get_loan_contract` with a checked `player_ref`. It returns the agreement in the native auxiliary loan slot: parent club where available, borrowing club, current club, signed date and end date. `current_club_relationship` makes differences explicit. A stored agreement does not establish that the loan is active today; the game can keep a loan object while the player is elsewhere or suppress its On Loan flag for an affiliation.

The cash fields distinguish playing and unused weekly wages paid by the borrowing club, playing and unused monthly fees, and a future buy-back fee. Amounts use whole GBP. `not_specified` with a null amount differs from stored zero. Unused amounts are stored terms; the tool does not substitute a default, calculate an overall cost or infer actual payments.

The `purchase` object supplies the initial future fee and the native total, including the getter’s additional fee components. It names optional, mandatory and match-count conditions, with the native threshold and matches-played counter. `competition_condition` names the source competition, achievement and qualification target where present. Supported achievements are winning, promotion, avoiding relegation, qualification and avoiding a fine. Stored competition names may differ from localized UI names. Stage-name composition and unmapped achievement codes remain explicit as unavailable. The trigger value for this branch is now `competition_condition`. `trigger_satisfied` stays null. Components retain their signed native parameter; they are not a decoded payment schedule. Integer overflow returns an unavailable total.

The `clauses` object supplies thirteen booleans for the stored loan clauses: recall, early-termination restriction, cup participation, playing against the parent club or its B team, playing for the parent club or its reserves, playing for the parent club in cups, training with the parent club, work-permit loans, affiliate salary-cap exemption, and restrictions against the parent club in cups or in continental competitions. Each flag is independent. A general permission and a narrower restriction can both be set. These clauses do not establish that recall or match selection is allowed today.

`clause_flags.source` identifies the native base or override word. A nonzero override replaces the whole base word. Hex fields preserve the selected flags and unmapped bits. The fresh census found 903 agreements with the recall clause, 133 with the termination restriction, 372 allowing play against the parent club and 106 allowing play against its B team. All 1,127 had cup participation set; none used an override. Native instructions and isolated tests establish override behavior and the eight clauses absent from this census; no live examples of those states were observed.

A null holder or null current slot returns `no_current_loan`; other auxiliary contract types and virtual players fail explicitly. Team types, contract owners, paired-team club identities, club-team membership, player identity and consumed bytes are rechecked. Different reserve/senior teams can share a club. Missing main contracts leave the parent club unavailable without discarding a verified loan object.

The 6 November 2026 census decoded all **1,127 LOAN_CONTRACT objects** found among supported player records in the 170,220-entry person table, including 23 combined player/staff records. It separately counted 2,918 empty current slots and one other auxiliary contract type. Those totals do not establish every loan-related record in the save. Fresh stdio checks covered sample players spanning every observed purchase branch, all 66 regular/combined Newcastle players and 13 explicit virtual-player rejections. The four known Newcastle loans all store an end date of 30 June 2031.

The same census found 12 competition-linked purchase conditions and decoded all 12: six for winning, one for promotion, three for avoiding relegation and two for qualification. Jaroš and Arthur Augusto name qualification for the UEFA Europa League from Serie A; Charlie Hughes names promotion from the Championship. No avoid-fine condition or stage-name reference was observed. Native code and isolated tests cover the avoid-fine branch and explicit incomplete states. `scripts/verify_loan_competition_layout.py` checks the competition lookup, name properties, condition serialization and achievement labels.

Reproduce the background checks with `scripts/verify_loan_contract_layout.py`, `scripts/survey_loan_contracts.py` and `scripts/verify_loan_contracts.py`. Recall windows, stage-name composition, competition-trigger satisfaction, future loans and actual payment schedules remain unfinished. No foreground UI interaction was used for this release.

## Main-contract terms and clauses

Call `fm_get_contract_terms` with exactly one `player_ref` or `staff_ref`. To inspect a club's staff together, set `include_contract_terms: true` on `fm_get_club_staff`; each record gains `contract.terms`. The single-person tool returns identity, observation time and `contract_terms`.

`terms` preserves every mapped entry in native order. Each entry has `kind`, `values`, `entry_index`, `native_kind`, `native_flags`, `selected_by_native_property` and `unavailable_fields`. Repeated landmark bonuses and appearance thresholds remain separate entries. The selected flag follows the native property getter: lowest signed parameter for its defined parameter kinds, otherwise first match; ties keep the first entry. `unmapped_entries` preserves the raw value, parameter and flags of other kinds. `complete_native_vector` means the whole bounded vector was read, not that every field or contract in the save is decoded.

| Entry group | Decoded values |
| --- | --- |
| Bonuses | Six cash bonuses; seasonal goal, assist and combined bonuses with their thresholds |
| Wage changes | Yearly/promotion/relegation percentages; weekly wages after club or international appearance thresholds |
| Release clauses | General, domestic, foreign, higher-division and continental fees; native active relegation/non-promotion kinds; committee-decided fees |
| Release expiries | Dates computed from the contract's last-signed date and stored day offset, following native mode/default branches |
| Extensions | Club options and promotion extensions in years; final-season game thresholds with promotion/relegation conditions |
| Other terms | Sell-on fee/profit percentages and original fee; sponsor wages, gate receipts and managerial compensation percentages; presence clauses including MLS guarantees and leaving/exploring options |

Cash keys end in `_gbp`; `weekly_wage_gbp` is per week. Percentages and thresholds retain native stored integers without editor-range clamping. Negative parameters produce null values and explicit reasons. Basic contracts return `basic_contract_terms_unavailable`; null main pointers return `no_contract`. Virtual records remain unsupported. `supported_kinds` lists the named kinds this build decodes.

Release-expiry `date` can be null with `native_default` when the native parameter or mode produces its default date. Arithmetic overflow and dates outside the verified range stay unavailable. An entry labelled `active_relegation_release` or `active_non_promotion_release` reflects the native kind; the tool does not independently establish current transfer eligibility. `activation_evaluated` remains false. Native flags, trigger progress, future agreements, actual payments and UI visibility remain unfinished. Stored loan terms have a separate query.

The background survey traversed 170,220 person-table entries and found 74,233 full contracts with 41 distinct entry kinds, all now named by this decoder. Counts are best-effort observations, not an atomic save snapshot or a full-field validation of every contract. The native verifier establishes 44 kinds and 56 fields through installed labels, dispatch and getter code; three supported kinds were absent from this survey. Live samples cover the observed kinds, including a release-expiry calculation for Idrissa Guèye: 936 days after 11 July 2028 gives 2 February 2031.

Run `scripts/survey_contract_terms.py` before `scripts/verify_contract_terms.py` for broad discovery and public-reference readback. Run `scripts/verify_contract_term_layout.py` with Capstone and Zstandard for the native layout proof. These checks use background reads and offline disassembly, without game-function execution or foreground UI interaction.

## Run

Requires macOS, Xcode Command Line Tools, Python 3.12+, and `uv`. Keep the game and target save open.

```sh
uv sync --locked --extra test
sh scripts/build_helper.sh
sh scripts/run_mcp.sh
```

The last command speaks MCP over stdin/stdout; it is not an interactive terminal. On this workstation the dependencies, native reader, and Codex registration are installed. The external volume must remain mounted.

The first attachment may open macOS's **Developer Tools Access** authentication prompt. Complete that prompt on the Mac. If it exceeds the reader's 45-second timeout, call `fm_attach` again after authenticating. The server never collects a password, changes the game signature or suspends the game. The training setter alone writes game memory. `build_helper.sh` builds and signs both the reader and the separate training editor. Fresh MCP connections discover the new tool; an existing connection can retain the earlier tool list until reconnected.

## Connect from Codex

The server is registered as `fm-live`, using:

```sh
codex mcp add fm-live -- /bin/sh "/Volumes/4TB Private/Offloaded/FMCP 27/scripts/run_mcp.sh"
```

Start a new Codex chat or reload MCP connections to pick up the registration. The running chat may retain its earlier tool inventory. The configured launcher was exercised through a real MCP client; appearance in the desktop tool picker is a separate check.

## Roster profile availability

`fm_get_team_squad`, `fm_get_managed_squad` and `fm_get_player` accept `profile_policy: "available"`. The default, `"required"`, retains strict rich-profile reads.

Available policy preserves each checked native roster entry. Regular and combined player/staff records return `profile_state: "stored_direct"`; virtual records with a valid existing cache return `"cached"`. A virtual record with a negative cache index returns `"identity_only"`, its canonical `native_identity`, and null `name`, `display_name`, `birth_date` and `attributes`. Requested `clubs`, `profile` and `health` groups also remain null. `unavailable_fields` and `field_sources` explain those results. Corrupt, mismatched or reused caches still fail the query.

Roster responses account for every slot through `native_slot_count`, `profile_counts`, `unavailable_profile_count` and `complete_base_profiles`. The last field covers the four base profile fields, not optional groups. Checked `roster_context` describes the selected team and owner separately from player contracts, current club and loan status.

Identity-only references support fresh `fm_get_player(..., profile_policy="available")` reads. Requesting required fields while the profile remains absent raises an availability error and preserves the checked reference. Changes to canonical membership or identity invalidate it. Availability can change between calls; observed changes during a query reject that query. Existing rich virtual references retain their stricter cache binding.

Fresh background verification of the loaded save checked all 16 FC Porto entries: 13 regular players, two combined player/staff records and one identity-only virtual entry. Every direct base field matched the frozen 0.37 reader; requested groups and fresh player readbacks agreed. The comparison classified 11 qualifying actual players, two below 450 minutes and three unsupported entries. Newcastle’s existing 28-player comparison retained its results. Independent before/after source observations agreed. Cache transitions and corruption cases were tested in synthetic memory; no live warm virtual profile was generated for acceptance. The full suite passed 2,767 tests. `scripts/verify_virtual_identity_layout.py` checks the installed native identity and cache-sign routes without executing them.

League performance comparisons use available policy and classify unsupported virtual and combined records explicitly. Team filters use available policy and preserve cold entries as explicitly unclassified when required values are unknown. Save-wide player search still excludes virtual records. These tools never invoke game getters or generate profiles.

## Team-player filtering with unavailable profiles

`fm_query_team_players` uses the complete available-profile roster. With the default `include_virtual: false`, virtual entries receive a known type exclusion before field predicates. Regular and combined player/staff entries remain eligible for attribute, profile, health and loan filters. Set `include_virtual: true` to include virtual records; valid missing predicate or sort values appear in `unclassified_players`.

A known failed predicate makes a nonmatch even if another requested value is unavailable. Missing cold groups, range-coded potential and partial virtual health retain their distinct meanings. Malformed structures, invalid scalar types and corrupt native sources remain errors. Unknown values never become zero, a false loan flag or an invented name.

`classifications` contains one entry per native roster row, in native order, with state `match`, `nonmatch`, `typeexcluded` or `unclassified`. `counts` reconciles those four populations to `roster_count`. The existing `matched_count` covers all matches before `limit`; unclassified entries remain complete. `complete_for_included_population` means no included entry remains unclassified, not that every native type or expanded profile is present.

Known rows retain their existing order: descending requested value, then case-folded display name, birth date and stable native order for exact ties. The default order is display name. Unavailable name/date sort fields remain explicitly unclassified. Returned rows retain checked identities, profile states and reusable player references.

Fresh MCP verification covered nine queries against independent frozen-source observations: three FC Porto cases and six Newcastle attribute/name/profile/health/loan controls. The Porto passing ≥15 and vision ≥15 query returned Alan Varela, then Gabri Veiga; 13 entries were known nonmatches. Its cold virtual entry was excluded by default or explicitly unclassified when included. Every one of 89 emitted player references reopened after the queries, and before/after source observations agreed. The full suite passed 2,922 tests. These observations verify the selected populations, not whole-save completeness.

## Team League performance comparison (0.37.0)

Call `fm_compare_team_league_performance` with a checked `team_ref`, for example one returned by `fm_get_club_squads`. The defaults return five players with at least 450 stored current League minutes. The metric is `90 * (goals + assists) / minutes`, ranked with exact rational arithmetic before display rounding. Equal rates prefer more minutes, then native roster order. This is a contribution metric, not a complete assessment of player quality.

The query classifies the complete selected native roster before applying the limit. It reports qualifying, below-threshold, unknown and unsupported counts, plus separate completeness flags for supported players and the whole roster. Zero minutes never form a denominator; missing or negative values remain explicit. Current-team and loan/club context stay separate from roster membership. Native roster membership does not establish UI senior-squad inclusion, ownership or match eligibility.

With `include_history=true`, each selected player carries separate archived League rows in native order. These retain source counts, skipped entries, duplicate rows, native years and checked team/competition context. They never contribute to the current ranking. Set `include_history=false` to return an explicit `not_requested` archive state. `minimum_minutes` accepts 0–32767 and `limit` accepts 1–25.

The collector repeats current-statistics, requested-history, ordered-roster and save reads. A changed source or expired emitted reference rejects the complete comparison. Final player references come from the final roster check; newly created references are removed after a failed collection. These checks cover an observation interval and remain non-atomic. An unavailable individual source remains unclassified; an unreadable roster cannot produce a partial ranking.

## Archived player statistics (0.36.0)

Call `fm_get_player_statistics_history` with a regular actual-player reference. Each indexed archive row retains its native year, category, team and competition context, appearances, minutes, goals, assists, ratings, signed advanced values and unmapped metadata. Team and competition links open the existing roster and competition queries. The reader verifies current person-table membership for references from every search route.

Rows retain stored order and repeated offsets. The response accounts for every native index entry, including skipped negative offsets. `decoded` with zero rows differs from `no_history_index` and `unavailable`; an unreadable or changed source raises an error. Resident archive caches remain explicitly unavailable. The query keeps archived rows separate from current statistics and starting playing history.

The native year has no verified season-start or season-end convention. Stored competition links describe archive context: a Premier League link can accompany a Cup or Continental category. Do not treat that link as the competition in which those category statistics were played. Category totals can overlap; do not sum them indiscriminately. Advanced units remain unverified.

The reader binds its read-only file descriptor to the game's active archive and rechecks file identity, consumed file bytes, memory bindings and linked identities before publishing references. These checks detect observed changes but do not make the read atomic. `scripts/verify_archived_player_statistics_layout.py` checks the pinned native instructions. Fixture tests cover corrupt sources, reference changes, repeated records and verification failures; live acceptance compares independent raw captures with public queries.

## Current player statistics (0.35.0)

Call `fm_get_current_player_statistics` with a regular actual-player reference from a squad or player search. The result includes the checked player, loaded save date, stored current-team identity, available club runtime season year and six named categories: Non Competitive, League, Cup, Continental, International and Overall (Club). Keep these categories separate: Overall (Club) overlaps League, Cup and Continental.

Each resident category supplies starting and substitute appearances, goals, assists, minutes, conceded goals, penalties, cards, clean sheets, Player of the Match counts and the native average-rating calculation. A byte value of 255 returns `null` for the interpreted counter and remains visible in `native_raw`. Signed short values remain signed. A zero rating denominator gives the native formula result `0.0`; its cause is not established.

Advanced statistics retain 68 signed raw values and 45 native field names. Their units and scales remain explicitly unverified, including expected-goal and distance values. A null indirect array uses the native getter's zero defaults with an explicit state. This differs from a missing category or whole resident statistics object, which returns unavailable.

Additional team rows retain their own categories and stored team identities. The reader does not add those rows or merge archived seasons and starting history. The club runtime season year is separate from FM's normalized display season; unsupported runtime branches return an unavailable reason. Virtual and combined player/staff records remain unsupported for this query. No refresh or lazy allocation runs, and the result does not claim complete career history or equivalence with FM's combined history display.

`scripts/verify_player_statistics_layout.py` checks the pinned native instructions. Focused tests cover sentinels, signed fields, source ownership, unavailable states and mutations between reads. Live acceptance compares public results with independent current-source byte captures; fixture-only branches remain distinct from observed live cases.

## Tools

| Tool | Result |
| --- | --- |
| `fm_list_saved_careers` | Local saved-career filenames, checked snapshot identities and supported metadata without a game session |
| `fm_get_saved_career` | One saved career’s metadata and bounded archive-component inventory under its snapshot pin |
| `fm_find_saved_clubs` | Every saved CLUB slot with stored names, original indices and native identities |
| `fm_get_saved_club_squads` | Same-file club teams and serialized PERSON roster references with explicit membership scope |
| `fm_get_saved_person_name_candidates` | Source name candidates for pinned PERSON indices with competing witnesses and bounded corroboration |
| `fm_query_saved_people_by_name` | Cursor-paged canonical typed PERSON names, retained strings/pointers and explicit unresolved-text coverage |
| `fm_find_saved_people` | Pinned first-name, surname and common-name candidate search with explicit matching and source coverage |
| `fm_get_saved_player_profiles` | Stored player ratings, scale and signed ability, with optional owner-checked primary-contract projection |
| `fm_get_saved_player_form` | Pinned stored form groups and original rows with nullable statistics and candidate availability |
| `fm_compare_saved_current_player_statistics` | Pinned primary-category starts/substitutes and exact G+A/90 ranks with full current-source checks and separate name ambiguity |
| `fm_compare_saved_player_form` | Exact goals-plus-assists per90 observed-minute comparisons within a pinned TEAM/date/competition scope |
| `fm_find_saved_teams` | Canonical same-file TEAM identities, owner context and optional PERSON roster overlap |
| `fm_find_saved_competitions` | Canonical saved COMP identities and serialized fields, with optional member availability context |
| `fm_find_saved_currencies` | Stored currency identities, current rates and optional serialized historical rates |
| `fm_get_player_bans` | Stored supported personal and international ban entries with source dates and unknowns preserved |
| `fm_get_player_concern_history` | Bounded stored current-main-contract history for fresh selected-roster refs, with optional unrendered English templates and optional stored player-linked promise inventory |
| `fm_get_player_assessments` | Stored assessment dates, assessors and supported optional joining-interest wording |
| `fm_get_managed_shortlists` | Managed coach’s recruitment lists, retained entries and checked player references |
| `fm_get_managed_training` | Managed team’s stored training calendar, session names and rest days |
| `fm_find_currencies` | Live currency names, native identities, stored rates and supported filtering |
| `fm_get_currency` | Fresh checked live currency details with optional stored historical entries |
| `fm_convert_currency` | Stored-rate currency conversion with explicit source rate and GBP basis |
| `fm_find_weather_profiles` | Stored weather profiles with four native periods and bounded reverse-link filtering |
| `fm_get_weather_profile` | Fresh checked weather-profile periods and available linked context |
| `fm_find_stadium_changes` | Stored move records with team/stadium links, dates and explicit unknown units/status |
| `fm_get_stadium_change` | Fresh checked stadium-change fields and navigable team/stadium references |
| `fm_find_saved_fixture_results` | Pinned TEAM/date fixture-result search with ordered canonical identities, separate score channels, retained/historical scope and bounded repeated pages |
| `fm_get_saved_competition_history` | Same-pin retained First/Second/Third Placed history, native years and Date Decided, with canonical TEAM/CLUB joins |
| `fm_get_saved_league_table` | Pinned retained ordinary league C0 table with same-file TEAM/CLUB identities, guarded stored positions and explicit unknown season/effective date/currentness |
| `fm_find_saved_players` | Pinned, bounded consecutive saved PLAYER rating/age predicates with cursor paging and explicit prefix coverage, unavailable fields and unsupported frontiers |
| `fm_get_saved_person_records` | Consecutive typed PERSON records from a structurally located saved table, with checked ordinals, source bounds, identity words, names and explicit traversal coverage |
| `fm_get_saved_player_starting_history` | Same-pin retained starting playing-history rows for a regular PLAYER, with exact stored-year filters, appearances/goals/loan flags and qualified unresolved native identity pairs |
| `fm_get_saved_player_injury_history` | Same-pin retained injury rows for a regular PLAYER, with stored-date/canonical injury-ID filters and explicit source/current-availability limits |
| `fm_get_saved_player_statistics_history` | Same-pin indexed archived statistics for an original regular PLAYER, with native-year/category filters, preserved zeros/unknowns and explicit owner/source coverage |
| `fm_get_saved_component_slice` | Same-pin exact listed archive member pages, full raw/packed hashes and explicit opaque source qualification |
| `fm_get_saved_history_inventory` | Closed16-family structural indexed/free/physical counts and optional opaque source-local owner bytes, without game_db traversal |
| `fm_status` | Running game processes, installed reader, session state, and explicit capability limits |
| `fm_attach` | Verified memory access and a fresh session token; select `pid` if several games are open |
| `fm_query_save_players` | Save-wide inclusive attribute/profile and birth-date filters, full profiles, explicit unknowns and continuation in database order |
| `fm_find_save_players` | Regular and combined player/staff records matching a full/common name, with membership-checked references and continuation after either limit |
| `fm_find_staff` | Staff-only, human-manager and player/staff name search, with membership-checked references and pagination |
| `fm_get_staff` | Fresh staff identity, optional contract club, stored ratings and native job title; explicit null contract state |
| `fm_get_club_staff` | Deduplicated native club staff lists plus team managers, with optional ratings/job titles and checked contract backlinks |
| `fm_query_club_staff_wages` | Rank weekly staff main-contract wages in GBP, with inclusive thresholds, full counts and sums |
| `fm_query_club_staff_contracts` | Find fixed staff contract expiries by date, with unknown/basic states listed separately |
| `fm_query_club_staff` | Filter club staff by job title and rating minima, then sort by one rating, with full match counts and truncation |
| `fm_find_competitions` | Competition identities, names and context; name/ID/geography/type/gender/extinction filters and complete pagination |
| `fm_get_competition` | Fresh competition identity, names and context with membership checks |
| `fm_get_competition_teams` | Direct current/next/secondary division assignments with club/national-team identity and roster references |
| `fm_get_competition_stages` | Stored runtime stages, shared owners and group-stage league children |
| `fm_get_standings` | Native stored league order, overall/home/away results, point rules and team roster references |
| `fm_get_fixture_coverage` | Resident calendar years and loaded/unavailable fixture groups |
| `fm_find_fixtures` | Date/team/competition filters, stored scores and linked roster/competition references |
| `fm_get_fixture` | Fresh fixture read with route, identity and database-membership checks |
| `fm_find_stadiums` | Stored stadium details with name/ID/capacity/extinct/training-ground filters and bounded pagination |
| `fm_get_stadium` | Fresh stadium details from a search or fixture venue reference |
| `fm_find_cities` | City names, geographic summaries and stored fields, with name/ID/nation/attraction/deletion filters |
| `fm_get_city` | Fresh city fields from a city search or stadium city reference |
| `fm_find_languages` | Stored language fields with name/ID/nation/difficulty/influence/deletion filters |
| `fm_get_language` | Fresh language details from searches, cities or region language entries |
| `fm_find_local_regions` | Stored region fields and complete language lists, with name/ID/nation/population filters |
| `fm_get_local_region` | Fresh region details and navigable language entries from searches or cities |
| `fm_get_competition_registrations` | Stored registration rows with team/nation, year, registration identifier and roster references |
| `fm_find_clubs` | Ordinary clubs matching full/short names, opaque club references and continuation after either limit |
| `fm_get_database_catalog` | Native counts for person/club/team/competition tables, geographic records, stadiums and other supported definition tables; explicit decoding limits |
| `fm_find_players` | Research fallback: scan writable memory for native player records, without establishing current-save membership |
| `fm_get_contract_terms` | Stored main-contract entries, release fees and dates, wage changes, bonuses and extensions |
| `fm_get_loan_contract` | Stored loan dates, playing/unused wages and fees, purchase conditions, thirteen recall/playing clauses and explicit club relationships |
| `fm_get_player` | Fresh name, birth date and 36 outfield attributes; optional club links, contracts and player profile |
| `fm_compare_team_league_performance` | Complete selected-roster classification and exact current League contribution ranking, with separate archived context |
| `fm_get_player_statistics_history` | Indexed archive statistics with native year/category, checked context links and explicit source coverage |
| `fm_get_current_player_statistics` | Resident current-player statistics in six separate categories, with source coverage and unavailable states |
| `fm_search_text` | Exact UTF-8/UTF-16LE matches with context, bounded scan statistics, and continuation cursors |
| `fm_read_anchor` | A bounded byte window that rechecks the original text before returning research bytes |
| `fm_get_save` | Loaded career name, creation date/build, save count, current date, last-saved date and active employed coaches with clubs |
| `fm_get_managed_tactics` | Stored slots, primary trained tactic and both phase positions, with optional mentality, selected team instructions and numeric formation IDs |
| `fm_get_managed_squad` | Active coach’s native roster, attributes and references; optional club links; choose `coach_name` for multiple coaches |
| `fm_get_club_committed_wage_spending` | Host-recomputed current and committed wage spending in GBP/week for the selected active coach club; unknown monetary paths reject the whole total |
| `fm_get_club_finances` | Balance, total and remaining weekly wage budgets, stored and current transfer budgets in GBP with explicit unavailable states |
| `fm_check_wage_budget` | Compare an additional weekly wage with remaining budget from native stored totals |
| `fm_get_wage_contributions` | Live weekly contributions by club or across the save, with payer/recipient/person references and totals |
| `fm_check_transfer_budget` | Compare one upfront fee with the decoded current budget; unavailable budgets remain unclassified |
| `fm_get_club_squads` | Every team in the managed club or a selected `club_ref`, counts, labels where verified, and opaque team references |
| `fm_get_team_squad` | Entire selected roster with strict profiles or explicit available-profile policy and fresh references |
| `fm_query_team_players` | Attribute/profile thresholds, descending attribute or ability sort, and optional loan filtering for a selected team |
| `fm_detach` | Clears the session, player references, anchors and cursors; leaves the game running |

Example sequence:

1. Call `fm_status`, then `fm_attach`.
2. Pass its `session_id` to `fm_find_save_players` with `name: "Nick Woltemade"` or a common name such as `"Chema Andrés"`.
3. When `next_cursor` is present, repeat with the same name and cursor. Defaults are 200,000 person records and 20 matches. Both record-budget and match-limit stops provide continuation. An empty page can precede a matching player.
4. Pass a returned `player_ref` to `fm_get_player` for a fresh read. References belong to one MCP session and expire on detach, reattach, detected identity changes, or retained-state limits.
5. Call `fm_detach` when finished.

The older `fm_find_players` memory scan has no continuation after a match-limit stop; narrow that search. ASCII matching ignores case; non-ASCII spelling and case must match exactly. Player memory scans cover readable writable regions; text searches cover private writable regions. macOS can change a region's sharing classification, so restricting player memory scans to private regions can miss live objects.

Memory-scan calls cover at most 1 GiB of new address ranges. Overlap, candidate records, names and runtime-type checks add bounded reads per candidate. The helper times out after 45 seconds. Reads do not suspend the game and are not atomic snapshots. Rejected candidates and native read failures remain visible in memory-scan results.

For raw research, call `fm_search_text` with `texts: ["Woltemade"]`, then `fm_read_anchor` with a returned `anchor_id`. Text and player cursors are separate.

Sessions reject an exited/restarted process or changed executable. **Reattach after every save change.** World tools bind to native roots and manager/club identities and discard the session when that binding changes. They cannot guarantee detection of every in-place reload. Unbound name searches retain their original research scope. A successful anchor read means only that those text bytes still match. Old UI caches may survive navigation or a save change.

## Managed training schedule (0.42.0)

Call `fm_get_managed_training(session_id=...)` to read the next seven days from the current simulation date. Supply `start_date` in YYYY-MM-DD format and `day_count` from 1 to 366 for another window. Select `coach_name` from `fm_get_save` in a multi-manager career.

Each day includes its date, the Monday that starts its week and the three stored sessions in native slot order. For example, the Newcastle schedule for 29 October 2030 contains Rest, Match and Rest. A Match entry describes the training schedule. Fixture details, session times, attendance and completed training require their own sources.

The reader follows the managed person and team to an existing assigned week. A missing week retains its date with null slots and `state: "unavailable_resident_week"`. If the source is unavailable, every requested date carries `state: "unavailable_source"`. The reader returns an explicit reason and leaves the game’s schedule untouched. `complete_stored_window` indicates whether every requested day had three stored codes.

Each slot retains its signed `native_code`. `english_definition_name` uses the verified FM27 training resource. A missing or changed resource leaves names unavailable. Unknown codes keep null names. Passing Style (0), Rest (300), Recovery (301), Match (500) and Not Available (600) are distinct stored values. The reported order does not establish a clock time for any slot.

## Managed prepared tactics (0.41.0)

Call `fm_get_managed_tactics(session_id=...)` to list the prepared tactics stored for your managed team. Select `coach_name` from `fm_get_save` when the save has several active human coaches. The query follows the canonical managed team and human owner to its existing persistent team entry; it never creates a tactic or editing session.

`slots` preserves every stored slot in native order. Each nonnull slot supplies its exact `name`, `name_state` and `phases.in_possession` / `phases.out_of_possession`. Each phase contains 11 ordered positions with `position_index`, `native_mask`, `name` and `state`. Thirteen verified masks have names such as `GK`, `D(CR)` and `DM(CL)`; other masks retain their native value with `name: null` and `state: "unmapped_native_mask"`. The default response keeps `formation` null. Each flag below independently enables more detail.

Use `include_instructions: true` when comparing setups. Each stored slot gains a `mentality` with its signed native code and English name, plus `team_instructions.selected_options` in native ID order. For example, one Newcastle setup stored Cautious, Regroup and Slow Pace Down. Its attacking copy stored Attacking, Counter-Press and Much Higher Tempo. The list describes settings stored for the whole tactic. Phase applicability, conflicts, effective defaults and player overrides require further decoding.

The option list accounts for every selected ID from 1 to 83. IDs 64, 74 and 75 have `name: null` and `state: "no_native_label"`. An unknown mentality preserves its signed code. Serialized bit zero appears in `unmapped_serialized_bits` when set. The reader preserves combinations exactly as stored, including simultaneous selections in the same category.

Use `include_formation: true` for the numeric formation ID in each phase. `formation.state` is `recognized` when the game’s first eligible template matches the 11 position masks. It is `no_eligible_template_match` with native ID zero when the search exhausts the eligible templates, or `unavailable_uninitialized_templates` with null ID when the game has yet to initialize the template storage. For a verified packed template and available formatting data, `formation.name` holds the ordinary English name. The name is the text the game's own naming code returns for the template, for each of its symmetric templates (61 shapes, the same on builds 27.0.0 and 27.0.1): for example `4-2-3-1 DM AM Wide` and `4-4-1-1 2DM`. Before 14 November 2026 the reader named only those two shapes on 27.0.0, as `4-2-3-1 DM Wide` and `4-4-1-1 2DM AM`; `docs/builds/27.0.1.md` ("Formation names") explains the correction. Other shapes keep a null name. The native converter can map several masks to one compact position during recognition. Position display labels still require an exact verified mask.

Use `include_roles: true` to add `base_role` to each of the 11 positions in each phase. The result includes the exact stored 64-bit `raw_encoding` as a hexadecimal string, the phase-specific `compiled_english_name` and its native resource key. A role in Football Manager 27 has no duty; each phase has its own role. The stored word also holds internal flag bits that are fixed by the role; they stay inside `raw_encoding` and are not named. An unmatched word keeps its null label. The same word can name a different role in each phase. The English label describes the prepared base selection. Individual player overrides and localized display text remain unresolved.

`primary_trained_tactic` reports the native unsigned index and its interpreted state. A valid nonnull slot gives `state: "selected"` and its zero-based `slot_index`. Other states distinguish `selector_out_of_range`, `selector_beyond_count`, `selected_slot_null` and `source_unavailable`. The native getter accepts only indexes 0–2 below the stored count. The reader never falls back to slot zero. Primary-trained selection does not establish the tactic deployed in a match.

Null slots remain visible as `state: "null_slot"` with null fields. Null and empty names remain distinct; stored Unicode and trailing spaces are preserved. `slot_count`, `nonnull_slot_count` and `null_slot_count` account for the complete observed source. Missing manager storage, owner container or exact team entry gives `source_state: "unavailable"`, an explicit reason, null counts and `complete_stored_slots: false`; this does not prove that the team has no tactics. A valid empty vector has zero counts and complete accounting.

The reader checks build, types, canonical ownership, tree keys, vector bounds and every consumed source byte before returning. Malformed sources, ambiguous ownership or detected changes reject the whole query. Its traversal budgets are implementation limits: 256 owner entries, 64 prepared slots and 64 tree steps. Exceeding them fails explicitly; they are not asserted native cardinality limits. No persistent tactic references or raw memory addresses are published. Reads remain non-atomic.

Current-match assignment, other formation shapes, localized names, familiarity, individual player assignments, effective match instructions and AI team ownership remain open. `unavailable_fields` describes the gaps for the requested detail level.

## Loaded career and managed squad

Call `fm_get_save` after attaching, then `fm_get_managed_squad`. Both verify the exact plugin build and native runtime types. The decoder follows the game root to the active user, manager, contract, team and club, checking reverse links along the way. The save-system root supplies the career name and last-saved date; the game root supplies creation metadata and save count. `current_date` comes from the simulation date anchor used by native Today/Tomorrow fixture labels and next-fixture lookup. It is separate from `last_saved_date`. It carries no current clock time or timezone. Every loaded-save response rechecks the date; a change during reading rejects the result. Day progression between queries keeps the career identity and existing references when their own identities remain valid.

The Newcastle native managed-team vector contains 28 players. It includes some players loaned out, while the game’s squad table can also show youth call-ups. Consequently this result is neither every player owned by the club nor a match-eligibility list. The tool names this scope explicitly and rejects the entire result if a roster record cannot be decoded, rather than dropping it silently. Only active employed human managers are currently supported.

Each consumed world field, relationship, string and roster entry is reread before acceptance. These checks detect changes but do not make reads atomic. References issued by the squad query recheck the save binding on `fm_get_player`. Display names such as Beraldo and Alberto Costa come from the native common-name handle; both player-search tools match full and common names. Missing first/surname handles yield no invented text; a record must still have a readable name.

Structured queries use one helper and one Mach task port for their bounded reads. Each request reads fresh bytes, including the final byte rechecks; the transport caches no game data. The helper closes after success or failure and never reattaches a reused PID. Process identity is checked at query boundaries. Each response has a 45-second deadline; each stream is limited to 100,000 reads and 64 MiB, with at most 16 KiB per read. Malformed, incomplete, mismatched or failed responses reject the query. Scans retain their separate byte/time bounds.

## Global player searches and table counts

`fm_find_save_players` follows the build-verified `DATABASE_TABLE<PERSON>` singleton and scans its pointer vector. Every consumed person index must match its position. It searches regular `ACTUAL_PLAYER` and combined `ACTUAL_PLAYER_AND_NON_PLAYER` records. Staff-only, retired and virtual types contribute to `other_person_records` and are excluded explicitly. Matching candidates receive the same name, birth-date and attribute checks as squad members. Returned references recheck the current person-table slot on every `fm_get_player` call.

Each scan rechecks its consumed pointer chunks and vector header; the Python wrapper then rechecks returned membership, identities and save roots. Cursors bind to the query and table allocation/bounds and reject changed tables. `complete_table_scan` means one call traversed the whole person table; it does not mean every person subtype was searched or that the game was atomically frozen. Complete pagination requires following every `next_cursor`.

In the validation save the table contains 170,220 people, including 62,575 regular players and 3,324 combined player/staff records. `actual_players_examined` includes both supported player types; `player_staff_examined` identifies the combined subset. A complete name search took under a second. `fm_get_database_catalog` also counted 28,022 clubs, 66,019 teams, 8,134 competitions, 924 player types, 251 nations and 25,891 stadiums. These are native entry counts, not promises that every record or field is decoded. All 79 Newcastle roster entries, including 13 virtual players, were independently linked to slots in the person table during research.

## Other clubs and players with staff roles

Call `fm_find_clubs` with a full or short name, then pass a returned `club_ref` to `fm_get_club_squads`. Use its team references with the existing squad and attribute-query tools. Without a club reference, squad listing keeps its managed-club behavior. Choose either `club_ref` or `coach_name`. Identical names can identify different clubs: the validation save has two clubs named Liverpool, whose senior vectors contain 29 and 14 players. Inspect their squads before choosing one.

Club search covers 27,560 ordinary `CLUB` records in this save. The other 462 entries are `LEAGUE_BODY_CLUB` records and remain explicitly excluded. Club references recheck table membership and identity; references for their teams retain that club binding. A changed binding rejects the read.

Combined player/staff records reuse the verified `PLAYING_DATA` layout. Their shared `PERSON_DATA` getters and virtual-base adjustments establish the name and birth-date locations. The decoder checks these getters, both runtime types, both independent identity fields, full record bytes and strings. Contract links also check the different embedded-person address. These records return `record_kind: "player_staff"`; stored staff ratings are available through the staff tools; job titles follow the native contract/team conversion. Mohamed Salah and Ceri Holland matched across independent global-table, squad and contract paths. This validates the native layout and links; neither profile received a new foreground UI comparison.

## Staff identities and club employment

Call `fm_find_staff` with a full or common name, then `fm_get_staff` with a returned `staff_ref`. Set `include_club: true` for the contract club. The reader supports staff-only, human-manager and combined player/staff records. A complete search examined 35,829 supported records in this save: 32,502 staff-only, three human managers and 3,324 combined records. Other person types remain explicitly excluded. `unavailable_name_records` counts records without any name; physically unreadable names reject the query.

`fm_get_club_staff` defaults to your active coach’s club. Pass `club_ref` from `fm_find_clubs` for another club, or `coach_name` for another active coach. It unions three native staff vectors and the club teams’ manager links, deduplicates people, then checks each person’s table membership and contract club. Newcastle returned 93 people, including your manager. Fresh reads of all 93 matched the roster. Both Liverpool clubs also passed the stdio checks.

Staff contract teams can differ within one club: a youth-team contract also links to the club’s first team. The reader accepts full and basic contract types only after runtime-type, owner and both club/team backlink checks. A null contract returns `state: "no_contract"`; other unsupported states fail explicitly. Club staff queries require a contract to the selected club and reject the entire list if any member fails.

These checks establish native identity and employment links. Board/support coverage and equality with every UI staff category remain unverified. Staff fields use shared native person getters and independent table/contract paths; no foreground UI comparison was performed for this release.

Set `include_attributes: true` on `fm_get_staff` or `fm_get_club_staff` to return 23 `attributes`, 12 `tendencies`, four `board_attributes` and eight `personality` ratings. Personality uses the same fields and direct 0–20 scale as player profiles. The field names come from this build’s installed editor definitions. Static native property-getter tracing establishes each byte offset and its scale. Most staff capabilities use fifths-of-a-point encoding rounded and clamped to 1–20. Direct values, including youngsters, authority and adaptability, preserve native zero values.

These are underlying stored ratings. Native getters can suppress a rating based on role or UI visibility; the reader does not apply that suppression. A stored rating does not establish job suitability or coaching stars. `attributes.attacking` is coaching ability; `tendencies.attacking` is tactical preference.

`fm_query_club_staff` accepts `minimum_attributes`, `sort_by` and `limit`, plus the same club selection arguments. For example, `{"minimum_attributes":{"attacking":15,"motivating":15},"sort_by":"determination","limit":5}` filters the checked club list, sorts descending by determination and returns both the full match count and the limited results. Supported filter names are the 23 keys in `attributes`; tendencies and board ratings remain available for inspection. All 93 Newcastle staff passed fresh rating readback through stdio. Staff-only, human-manager and combined player/staff layouts, both Liverpool lists and filtered results also passed. These checks did not use foreground UI automation.


Set `include_job: true` on staff reads to add `contract.job`. It includes an English native title, the source codes and a decode state. On `fm_get_staff`, this also includes the checked contract club. Native team scope distinguishes, for example, `GK Coach First Team` from `GK Coach (U18 Team)`. A missing contract returns `no_contract`; an unsupported native job/team combination returns `unmapped_native_job` with a null title. Neither state is silently treated as a job match.

`fm_query_club_staff` includes job titles and accepts `job_contains`, a case-insensitive title substring. For example, `{"job_contains":"Physio","minimum_attributes":{"physiotherapy":15},"sort_by":"physiotherapy"}` finds matching staff in the selected club. It rejects job filtering when any title is unmapped, so an incomplete decode cannot produce a misleading empty result. Queries without a job filter retain those records and report `unmapped_job_count`.

All 93 Newcastle roles decoded, including the chief doctor’s basic contract and three managers’ team-specific titles. The verifier checked the native conversion over all 65,536 byte-sized job/team combinations and traced 196 resulting labels to the installed English resource. These are native role titles; coaching assignments, workload, clauses and complete UI coverage remain unfinished.

## Player clubs and loans

Pass `include_clubs: true` to `fm_get_player` or `fm_get_managed_squad`. Each regular/combined player then includes `clubs.contract_club`, `clubs.current_club`, `clubs.loan_club` and `clubs.on_loan`. Named clubs have full and short names; missing parent/current teams remain null. `contract_club_state` and `loan_status_reason` explain missing or suppressed states. The option defaults to false to preserve existing responses and avoid the extra reads.

Club reads support full/basic main contracts, absent contracts and absent current teams. Unexpected runtime types, inconsistent owner/team club links and detected changes produce an error. The whole squad query fails if any requested club record fails; it never silently drops a player. A failure during a referenced player read expires that reference.

The decoder follows the player’s main-contract, current-team and auxiliary-contract links independently. Main contracts may be full, basic or absent. Different teams in the same club are accepted when both have valid club backlinks. Current and borrowing clubs can differ. Null auxiliary holders, empty current slots and typed trial contracts produce a false loan flag. A loan object normally produces true; the native getter suppresses it when the borrowing team’s mode byte is zero and its club has an affiliation whose second club points back to that club with kind 18. The response preserves the stored loan club when the flag is suppressed. It does not evaluate dates or match eligibility.

The nearby `+0x130` field is excluded: observed values include former clubs and a national team. Search references retain their original scope even when their club relationships validate; they do not establish membership in the loaded career. Club links do not establish match eligibility, work permits, availability or complete club ownership.

The 6 November census checked all 65,899 supported regular/combined players in the 170,220-person table with no rejections. It found 1,073 true loan flags, 54 affiliation-suppressed loan objects, 2,918 empty auxiliary slots, one trial contract, 4,597 absent main contracts and 411 main contracts whose different team pointers resolve to the same club. These counts cover supported player records, not every person type. The public verifier checks prior failures and loan-filter partitions across Newcastle and the affiliated academy. Reproduce with `scripts/verify_player_club_layout.py`, `scripts/survey_player_clubs.py` and `scripts/verify_player_club_status.py`.

## All club squads and player queries

Call `fm_get_club_squads`, then pass a returned `team_ref` to `fm_get_team_squad`. References bind to the loaded career, team identity and club backlink. The query returns every roster entry or an explicit error; it never silently drops unsupported records. UI call-ups and native membership can differ. Summed roster counts do not prove the number of distinct players owned by a club.

For a passing shortlist, call `fm_query_team_players` with a team reference, `minimum_attributes: {"passing": 15, "vision": 15}`, `sort_by: "decisions"`, and `limit: 5`. The query sorts descending by the selected attribute, then by name and birth date. It reports the full roster count, matched count and truncation. Use `loan_status: "on_loan"` or `"not_on_loan"` to filter the verified native On Loan flag. A stored loan agreement can coexist with a false flag because of the affiliation exception. Virtual players are excluded by default; set `include_virtual: true` to include them. These filters do not assess roles or match eligibility.

Virtual players have compact native records and generated profiles. The reader follows the existing `VIRTUAL_MANAGER` cache only after checking its runtime type, bounds, cache slot and matching player identity. It does not invoke game functions or generate a profile. Required rich reads reject missing profiles. Available policy returns checked stored identity for negative cache indexes; malformed, evicted or reused nonnegative cache slots still fail. The reader never generates profiles or performs UI actions.

Virtual roster records return `record_kind: "virtual"`. For identity-checked cached profiles, optional club information reports `contract_state: "virtual_uncontracted"`, null contract/current clubs, and a separate `roster_club`. Their roster membership does not establish a contract; the two inspected profiles display “Free Agent.” The regular name-search decoder continues to reject generated profile caches and searches actual players only. Use squad tools to find virtual players.

Cached virtual profiles use a distinct identity representation. The ordinary player decoder rejects the non-table index marker (`0xFFFFFFFF`); a separate path accepts a generated profile only when its ID matches the compact virtual record and its cache marker fields match the verified layout. Every consumed pointer and field is rechecked before acceptance.

## Player validation

The decoder checks the plugin's SHA-256 fingerprint, compares its ARM64 Mach-O UUID with the loaded image, and checks the native runtime types before accepting records. Other builds fail explicitly. Addresses come from the running process; no player address or process ID is hardcoded.

The supported plugin fingerprint is `774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1`. The layout in `fm_live_mcp/players.py` identifies `db::ACTUAL_PLAYER` and its embedded `db::PLAYING_DATA`, follows native name handles, binds both independent identity fields, and decodes the birth date and selected attribute bytes. For fifths-mode records, `(raw + 2) // 5`, with a minimum of 1, matched all 72 observed attribute values. Version 0.14.0 also honours the native direct-value mode; its branch is checked against installed code and synthetic tests.

Record bytes and names are reread to reject detected changes. A player reference also retains identity separately from its address, so address reuse by another player fails. The internal identity integers are not exposed as verified database IDs. These checks identify native player objects; retained objects can still outlive a save change. Two profile comparisons validate this layout, not every possible player or game state.

## Verify

```sh
.venv/bin/python -m pytest -q
.venv/bin/python scripts/verify_live.py
.venv/bin/python scripts/verify_players.py
.venv/bin/python scripts/verify_world.py
.venv/bin/python scripts/verify_clubs.py
.venv/bin/python scripts/verify_squads.py
```

The test suite covers malformed records, birth dates, attribute rounding, stale identities, build/UUID rejection, cursor isolation, process changes, Unicode text searches, MCP schemas/errors, and actual Mach reads from disposable child processes. Native tests verify byte-boundary continuation and player-name pointer resolution with a wrong-type rejection.

The verification scripts use the configured launcher's command. `verify_live.py` records text-search evidence in `evidence/live-mcp.json`. `verify_players.py` compares search results and fresh reads against the manually transcribed UI oracle in `tests/fixtures/player_profile_oracles.json`, checks unknown/detached references, and writes `evidence/live-players-mcp.json`. The player oracle belongs to the validation save: after game progression, compare changed values with the UI before updating it.

`verify_world.py` checks the actual stdio save/squad tools against `tests/fixtures/save_ui_oracle.json`, sampled visible names, Woltemade’s profile oracle, fresh references and invalid/detached requests. It writes `evidence/live-world-mcp.json`. The UI count and sampled names do not assert equality with every UI squad row.

`verify_clubs.py` exercises the optional fields through the configured stdio launcher. It checks all 28 managed-roster contract/current club links, rereads the three roster loans, finds Mason Miley separately, and compares all four destinations with `tests/fixtures/player_club_oracle.json`. Evidence is saved locally to `evidence/live-clubs-mcp.json`. These UI oracles describe the captured save state; later transfers or game progression require fresh UI checks.

`verify_squads.py` exercises all four rosters through stdio, compares the visible squad counts and all nine grey U18 names, and checks fresh virtual reads against `tests/fixtures/virtual_profile_oracles.json`. It also compares an attribute-filtered shortlist with the full senior roster and verifies detached-team rejection. Results go to `evidence/live-squads-mcp.json`. The fourth vector’s four records were read and identity-checked, but their team label and profiles have no independent UI comparison yet.

`uv run python scripts/verify_read_transport.py` compares the complete managed roster, including club/loan fields, through both read transports and records timings and matching result hashes in `evidence/live-read-transport.json`. Run it with an unchanged game state. Tests also exercise real Mach stream reads, malformed requests, response validation, timeout cleanup and process changes.

`uv run python scripts/verify_database.py` verifies the typed-table catalog through MCP, checks global Nick Woltemade/Florian Wirtz results against their UI oracles, compares common-name lookup with the squad, and checks match-limit/record-budget pagination and fresh member reads. The single-component-name case is checked against native strings, without a new UI comparison. Evidence goes to `evidence/live-database-mcp.json`.

`uv run python scripts/verify_other_clubs.py` checks club-search pagination, both Liverpool senior rosters, Salah/Holland table and roster agreement, Newcastle managed/global parity, and detached-club rejection. Evidence goes to `evidence/live-other-clubs-mcp.json`.

`uv run python scripts/verify_staff.py` checks staff search pagination, active-manager identity, player/staff agreement, all managed-club staff fresh reads, both Liverpool lists and detached-reference rejection through stdio. Evidence goes to `evidence/live-staff-mcp.json`.

The scripts require one running supported game and available memory access. Local screenshots and game-memory excerpts remain in the git-ignored `evidence/` directory.

For UI validation on this workstation, the standard computer-use click API returned `noWindowsAvailable` while screenshots worked. Peekaboo successfully navigated First Team, Loans and U21 screens using explicit app focus, a pointer move, then a foreground long press and fresh classic capture. Use a fresh `peekaboo see` receipt for the window ID and logical coordinates; screenshot pixel dimensions can differ from logical points. A successful input receipt alone does not verify navigation. The local captures establish the observed screen changes. No game progression, save writes or memory writes were used.

## Source

`native/fm_live_helper.c` and its entitlement file originate from:

```text
/Users/jamesheffernan/GitHub/FM26 Deepener/native/fm_live_helper/
Source revision: 20332fff4fa2ec654652db1cc50959203567eaa5
Original C SHA-256: 9f2b602aaf795532a3beb49bb2a3b013d72b052b1092dcd886e0c437e86f435d
```

Local changes add writable-region filtering, byte-budget continuation, loaded-image discovery and native player filtering. The MCP wrapper removes the original reader's fixed confidence score. FM26 research informed the investigation; the FM27 fields exposed here were checked against the running game. Further fields require separate validation.

The transport uses the installed [official MCP Python SDK v1](https://py.sdk.modelcontextprotocol.io/v1/), pinned in `uv.lock` for reproducibility.

`uv run --with capstone --with zstandard python scripts/verify_staff_attribute_layout.py` checks all 39 labels against installed editor resources and traces native property cases, offsets and scaling. `uv run python scripts/verify_staff_attributes.py` verifies optional fields, fresh reads and filtering through stdio. Both write ignored evidence under `evidence/`.

`uv run --with capstone python scripts/verify_staff_job_layout.py` verifies the native contract caller, job getter, conversion matrix and installed labels. The staff-attribute stdio verifier also checks job readback and title filters.

## Generated-person search continuation (0.34.1)

The reported recruitment search returned five players after 45,616 records, then repeatedly failed at person index 47,798 (Darwin Maripán). The native scanner incorrectly required the two PERSON identity fields to match. The installed property dispatcher exposes them independently as `duni` and `rdui`; the latter can be zero or differ from the former. It is not a duplicate-ID validity check. The same assumption affected player and staff decoding.

Player/staff scans and decoders now accept independent values, require a nonzero primary identity and retain both values in references. Table membership, runtime types, record/string rechecks and reference invalidation remain enforced. Ordinary player reads reject the non-table index marker used by virtual profile caches; the separate virtual cache identity checks remain unchanged. Version 0.34.2 extends this correction to clubs and related record types, as described below.

The original query completed across 170,478 person records with ten raw matches. Three match-limited pages and four record-budget pages agreed; all returned profiles passed fresh reads. The previously failing generated player also passed a full-profile read. These matches establish the requested stored attributes, not recruitment eligibility, transfer availability, prices or willingness to join. No UI or game-state mutations were used.

The gate passed 2,021 tests. Four new native pagination cases failed on the old helper and passed on the corrected helper. `scripts/verify_person_identity_layout.py` traces the installed native properties; `scripts/verify_recruitment_continuation.py` replays the query through MCP and checks full traversal, pagination parity and fresh reads. Private receipts remain in `evidence/`.

## Reader assumption audit (0.34.2)

The audit found the same incorrect identity-equality check in club, competition, geography, injury-definition, base-currency, stadium-change and compact virtual-player reads. These decoders now accept independent `duni`/`rdui` values. Saved club, competition and virtual-player references bind both fields. Competition responses include `random_id`, following the existing team/currency convention: null when it equals the primary ID, otherwise the stored value. Native types, primary identities, canonical membership, consumed-byte rechecks and the separate virtual-profile cache checks remain enforced.

Player names now use the same optional-component semantics as staff PERSON data. Null handles, null targets and valid terminated empty strings represent missing components. Malformed strings still fail. Native searches continue past players with no name and count them in `unavailable_name_records`; recruitment counts only those that pass its other criteria. Empty or non-string cursors fail explicitly instead of silently restarting the older player, staff, club and memory search paths.

A read-only census traversed all 18 exposed native tables. All 66,072 supported regular/combined player profiles and 32,518 staff/manager identities decoded successfully in the loaded save, including 362 players and nine staff with unequal IDs. Other person types remain counted separately. The census did not decode every optional contract, injury or finance field. The additional world-record identity cases were demonstrated with regression fixtures and installed RTTI/property evidence; this save's affected world tables used equal IDs.

`scripts/verify_record_identity_layout.py` checks DATABASE_RECORD inheritance and independent native properties. `scripts/survey_reader_assumptions.py` records the census. `scripts/verify_reader_searches.py` compares complete club and staff traversals across page strategies; `scripts/verify_recruitment_continuation.py` replays the original recruitment query through MCP. The search contracts still require every cursor, retain explicit unknown potential, count unsupported person types and make no global-ranking claim. References remain bounded and can expire; virtual profiles require an already-materialized cache.

## Personal recruitment shortlists (0.43.0)

Call `fm_get_managed_shortlists(session_id=...)` to list the coach’s ordinary personal player shortlists and read the current personal selection. To open a different list, pass its `list_index` from `lists`. The index is its position in the full personal collection, so ordinary list indices can have gaps. A null stored name leaves the display title unknown.

Each page returns up to 50 stored slots by default. Set `limit` between 1 and 100 and pass `next_offset` to continue. Entries retain their order and duplicates. A supported player has a reference for `fm_get_player`. A null slot or recognized person without a supported player profile keeps its position with a null reference. Each request rechecks the source independently, so membership can change between pages.

`total_entries` is zero for a selected empty list and null when there is no readable selection. `selection_state` explains the difference. The query reads retained membership. Active monitoring, expiry and scouting report availability remain unknown.

## Stored player assessments (0.44.0)

Call `fm_get_player_assessments(session_id, player_refs)` with one through 100 regular or combined player references. For a shortlist, pass the references returned by `fm_get_managed_shortlists` together. Each input player has a `matches` list. A match records the assessor, stored population date and presence of extra assessment data. Some records describe coaching assessments. A missing assessor or unresolved date has its own state.

Set `include_joining_interest=true` to read each matching assessment’s stored English label and its longer native text template. For example, a compact label of `None` means the game recorded that interest category. A matched assessment with a missing interest field yields `Unknown`. An empty `matches` list means the examined slots held no assessment for that player. The native no-template state has null text. A stored assessment describes the player at the time of that assessment.

The tool checks up to 4,096 physical slots per call. Follow `source.next_source_offset` with the same players and coach until it is null. Empty results on a partial page cover only the examined range. Even a full pass covers the selected manager and team context. Each page checks the current save and the bytes consumed during that request. Completed scouting reports, grades and present-day player interest require separate evidence.

## Stored personal bans (0.47.0)

Call `fm_get_player_bans(session_id, player_refs)` with player references from a current-save search or team squad. For example, find Miloš Kerkez with `fm_find_save_players`, then pass his reference to read the stored ban’s start date and English main text. The query accepts regular players and identifies an unsupported combined player/staff source explicitly. Virtual references are outside the accepted input.

An empty list means the player’s personal ban collection was present and checked. A null list means the source was absent or unsupported. Each physical record retains its native slot. The duration wording currently covers the verified international match-count branches. The tool reports stored discipline. Selecting players for a particular fixture also requires registration and competition rules.

Optionally pass an exact `fixture_ref` from `fm_find_fixtures` or `fm_get_next_match_squad` to read `players[].fixture_suspension.native_suspended`: the official ordinary mode0 suspension predicate projected on that unplayed fixture's canonical stored competition/date. Supported empty sources and a single kind1 record can return true or false; unsupported kinds, gates or current TEAMs outside the fixture stay null. Future results assume the currently recorded bans remain unchanged. The supported native path does not gate on the stored total-minus-served balance. This is a suspension fact; the full outer availability decision and overall fixture eligibility remain unevaluated. Omitting the option preserves the existing response. See [native source proof](native-player-fixture-suspension.md).

## Saved careers on disk (0.45.0)

Call `fm_list_saved_careers()` to list the local FM27 games directory. Each verified file has a name, a snapshot ID, a component count and any supported saved manager and date metadata. Neither offline tool requires `fm_attach` or a running game. The archive reader loads libzstd from the host.

Call `fm_get_saved_career(filename=...)` for an alphabetically ordered page of component paths and compressed and uncompressed sizes. To browse one directory, pass its stored path prefix including the archive root. On the next request pass `next_offset` as `offset`, the same prefix, and the returned `snapshot_id` as `expected_snapshot_id`. The reader rejects a replaced or changed snapshot. A verified archive directory can still have unavailable summary metadata.

The directory identifies stored components. Querying a field inside one requires its own decoder. Saved dates and manager names describe the selected file at save time.

### Reconstructed club injury return estimates

`fm_get_player_injury_return_estimates` reads 1–32 fresh player references and reconstructs supported native remaining-day estimates using current club-selected medical inputs. Calendar dates are a separately labelled arithmetic conversion. Unsupported injury or staff-selection branches retain explicit reasons, and checked empty injury vectors are not zero-day forecasts. Each injury remains separate. This is not a captured medical report, clearance, match eligibility, or guaranteed recovery.

### Resident league goal scorers

`fm_get_league_scorers` ranks the complete supported competition-owned participant pool by its native stored goal counter, without filtering to current club rosters. Cutoff ties are retained. Missing or unsupported competition statistics remain explicit. Stored last-team attribution is separately qualified and does not establish current employment.

### Current player injury-status flags

`fm_get_player_injury_status` reads the current selected XI and bench in one checked pass when player references are omitted, or accepts explicit fresh player references. Named injury records remain separate from native current status flags. Checked false differs from unsupported or unavailable. This observes today’s stored state, without predicting future-fixture clearance or recovery.

`fm_get_managed_league_age_exemptions(session_id, coach_name=None)` checks the native current Premier League age-exemption requirement across the managed club’s Senior, U21 and U18 roster slots. It returns each player’s bound current team, stored birth date, native current age and cutoff age when required, plus the observed competition and cutoff date. Opaque player references support normal profile drilldowns. Roster overlap is retained. Players whose current team belongs to another club are explicitly outside the managed-club context; roster presence alone does not establish loan or current employment status. Other squad types are reported as excluded.

This query supports the pinned Premier League default age requirement and an empty native cutoff-override list. Unsupported rule/date sources, virtual-player age sources and mixed-leap anniversary branches remain unavailable. It evaluates age exemption only: it does not prove submitted squad-list membership, complete registration eligibility or clearance for any future fixture. The native runtime season discriminator is reported without inferring a full season interval. All reads remain passive and non-atomic, with consumed-byte, canonical identity and process rechecks before player references are published.
Opt in `include_registration=True` on this same query to add each row’s exact current native registration predicate (`D32054`, mode1), alongside its independent age exemption. `registration_context` binds the current Premier League competition, native season, TEAM, rule and selector. `registration_counts` keeps native true, native false and unavailable separate. The row retains committed25 versus temporary26/27; native true can include a temporary addition. A native-false youth player may be age-exempt and must not be treated as excluded. Current outside-club players, virtual identities and unsupported native branches remain unknown. This option does not reconstruct the complete official submitted population, date a historical submission or establish fixture eligibility. See [native-player-registration-source.md](native-player-registration-source.md) for source gates and controls. Calls that omit the option preserve the existing response.

### Read a player's recent live match form

Use `fm_get_player_match_form(session_id, player_ref, team_ref=None, mode="confirmed_appearances", limit=5)` for the currently loaded game. A null `team_ref` selects the managed TEAM; a supplied checked team reference selects that exact TEAM, including separate youth or national-team histories.

Each row exposes the stored date, canonical opponent TEAM and competition, goals and minute duration. `confirmed_appearances` requires positive stored duration or a positive substitution-on minute, retaining zero-minute substitutions. `team_entries` also shows rows without statistics. Missing statistics stay null and do not mean unused or zero. `ambiguous_entries_at_or_after_cutoff` and `undated_entries` identify records that could displace a supposedly absolute last-five answer; same-day ties retain reverse native ring order rather than claiming kickoff order.

Coverage is the resident 20- or 60-entry ring for that TEAM. Older entries can be overwritten, and entries can span seasons. These rows do not establish match completion or a unique fixture identity. The current source supports regular ACTUAL_PLAYER records; virtual and combined player/staff owners fail explicitly. No game function, refresh, UI interaction or saved archive is used.

### Match analytics rows

Use `fm_find_fixtures` to select live fixture references; continue every fixture
cursor, including pages with no matches. Call `fm_query_match_data` with up to64
explicit references and a table (`fixtures`, `team_totals`, `retained_players`,
`events`, or `player_matches`). Omit `fields` to discover columns, then request
only fields needed for calculations. For example, `team_totals` supports
`native_match_key`, `side_index`, `shots`, `shots_on_target`, and `expected_goals`.
Follow every returned cursor with identical selectors. Pages retain one capture
for five minutes, validate the career/load epoch, and bound row payloads.

Sources are checked current-session match backing records and resident fixtures;
they are not previous evidence files. Preserve coverage, raw source fields and
identity states. Retained player rows and player form-ring rows are separate:
uncaptured form rings do not mean zero appearances. Raw event codes and clocks
have no inferred labels. Shot locations, per-attempt xG, and set-piece categories
remain unsupported. Stored match data does not prove completion.

### Scoped match analytics

Use `fm_get_match_data_columns` for column discovery: it reads the shared empty
projection schema and never attaches or reads the game. `fm_query_match_scope`
accepts explicit `date_from`/`date_to` and a `team_native_id` or
`competition_native_id`, then captures up to128 selected result records once for
all requested `tables`. Its compact defaults omit raw blobs. The default
`fixtures` and `team_totals` projections skip player identity decoding; include
`retained_players` in the same call for player analysis. Supply `fields` as a map
from table name to column names when you need a specific projection.

Every returned row carries `table` and `row`; `counts` covers the complete
captured projections. Follow every `next_cursor` with identical selectors.
Pages share `capture_id`, `captured_save`, and `observed_at`, remain immutable as
the clock advances, and expire after five minutes or a career reload. Selected
result records and known scores do not prove completion; missing sources and
nullable player identity/usage fields remain explicit.

The scoped selector validates typed fixture dates and canonical team identities
before skipping unrelated records. Selected records retain full identity and
source checks. Player captures use bounded16-fixture streams and reuse canonical
identities only within the same verified readset; team-only captures avoid those
lookups. The native helper request and byte bounds remain unchanged.

### Additional scoped match tables

Request `tables=["goal_crossings"]` for retained credited-player goal-line
endpoints. Each row exposes canonical scorer identity when available,
`native_horizontal`, `native_height`, `height_band`, and explicit unresolved
coordinate units and signed-axis viewpoint. Per-fixture coverage includes zero
crossing records and scoreline goals absent from player credits. These rows do
not describe all attempts, shot origins, or an individual goalkeeper. This table
requires player identity reads even when `retained_players` is not requested.

Request `sub_entry_context` for used substitutes' conservative score-at-entry
states. The pinned native event policy, final score and all stored player goal
credits must reconcile. Unknown codes and residuals preserve unknown states;
events at the entry minute preserve ambiguity. Participation fields in
`retained_players` expose stored native clocks and reconciled entry/exit minute
intervals, with same-minute event ordering explicitly unknown.

Use the free column catalog for team pass attempts/completions, corners, native
possession counters and computed shares, plus player expected assists, key passes,
open-play key passes and chances created. Native possession time units remain
unknown; computed shares are not asserted to equal displayed UI percentages.
Stored creator counters do not establish causal responsibility for a later goal.

`retained_players.distance_metres` and the corresponding `player_match_analysis`
SQL column expose the stored DistanceRan float for one retained fixture/player.
The column catalog supplies its metre unit and native source provenance. Divide
by 1,000 for calculated kilometres; this is a full-fixture aggregate, separate
from current playback, tracking path length and season statistics. Stored zero
remains zero alongside the independently decoded participation/minute states;
missing fields remain null. Negative or nonfinite values reject the capture.
Distance alone does not establish effort, sprinting or tactical effectiveness.
See [native player running](native-player-running.md) for the source proof.

`retained_players.sprints` and the corresponding `player_match_analysis` SQL
column expose FM's stored unsigned-byte Sprints count for one retained fixture.
The column catalog supplies count units and native source provenance. Values
0–255 remain unchanged; zero does not establish participation, and missing data
remains null. Sprint speed thresholds, intensity, duration and effort remain
unproved. See [native player sprinting](native-player-sprinting.md).

`retained_players.open_play_final_third_passes` and its
`player_match_analysis` SQL column expose FM's native OpenPlayFinalThirdPasses
counter for one retained fixture/player. The capture-free column catalog gives
its count unit and source provenance. Known zero remains zero; uncaptured data
remains null. Negative signed counters reject the capture. The native
into-versus-within final-third interpretation remains unproved, so this is not
an entry count, progressive-pass count or progressive-carry measure. See
[native final-third passing](native-player-final-third-passes.md).

`fm_get_retained_match_spatial` with `grid="none"` supplies every positive
completed-pass supplier in each receiver's `passing_outlets.suppliers`, sorted
by count then canonical PERSON ID. Selecting a player preserves the full-team
denominator. `leading_suppliers` retains all leaders; the top-ten connection
summary does not truncate the complete supplier list. Missing or incomplete
networks remain unknown. Low reception volume alone does not prove poor movement
or explain tactical cause.


### Current retained cup history

Use `fm_get_current_player_cup_history` with a checked `competition_ref` and1–32 named `player_refs`. The source exposes the resident native season, each cumulative unsigned-byte PERSON appearance counter and its last-associated TEAM. It does not count appearances for that TEAM; updates can overwrite TEAM while the counter accumulates, and the byte can wrap. A missing row preserves null rather than asserting no appearances.

Optionally provide a matching `fixture_ref` to inspect that retained fixture's phase/rule and the current-source flag1 different-TEAM inner condition, only when the player's current TEAM participates. The response separates `source_date` from `fixture_rule_context.date`: applying current source to a past fixture never establishes historical kickoff status. Other rule branches and overall cup-tied/fixture eligibility remain unevaluated. Non-cup/shared runtime, unsupported people, missing history, duplicate PERSON rows, invalid references and read drift remain explicit or reject the checked batch. No UI, game function, disk save or historical archive is used.

### Rank current league player counters

Use `fm_rank_league_players(session_id, competition_ref, sort_by="starting_appearances", order="ascending", minutes_over=1000, limit=1)` for the fewest native starting appearances among players with **more than** 1,000 stored minutes in one exact competition. Find the reference with `fm_find_competitions`. Supported sort metrics are `starting_appearances`, `minutes` and `goals`; omitted `minutes_over` applies no minutes filter.

Every physical row in the current COMP-owned PERSON pool is checked, including combined player/staff records and players who changed clubs. Primary player League categories and current club rosters are separate sources. Native starting appearances use the official competition getter/label; they do not turn duration-derived initial participants into formal per-match starting XIs.

The complete cutoff tie is retained, with `page_size` 1–100. Follow each `next_cursor` using the returned `source_pin` and unchanged selectors; a changed native source expires the continuation. `returned_complete` is true only after all selected rows and the unknown/anomalous ledger are delivered. Raw signed starts/minutes remain visible with anomaly states; unknown values never become zero. Native season discriminators are not converted into calendar seasons or claims that a season or fixture is complete. Last-associated TEAM does not attribute every accumulated count to that club.

### Compare exact league counters for your squad

Call `fm_get_league_player_statistics(session_id, competition_ref, player_refs)` with up to 100 references from `fm_get_managed_squad` or another live player tool. One complete current competition pool is checked and only requested players are returned, in input order, including duplicates. This supports a squad-wide starts/minutes/goals comparison without retrieving a league ranking page containing every player.

An observed counter can be zero. A missing PERSON row is `not_observed_in_resident_pool` with null counters; an unavailable source is separately labelled. Raw anomalies and null starting-appearance getter prerequisites stay explicit. These are exact competition counters accumulated across clubs, not necessarily Newcastle-only totals after transfers. The native season discriminator does not establish a calendar interval or a completed season. References from available-policy virtual rosters can be checked without creating a generated profile; legacy expanded virtual references must be refreshed.
