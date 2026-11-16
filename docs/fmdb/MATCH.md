# Match data in the snapshot

`fm_live_mcp/fmdb/sources/matches.py` adds nine collection tables and one view, and
`fm_get_match` shapes one match. Everything is read from live memory, from the game's own
temporary match archive files, or by emulating shipped code; nothing runs in the game process.

## What the game holds

| Level | 10 Dec 2030 | 13 Dec 2030 | Where |
|---|---|---|---|
| Result | 106,150 (2026, 2028-2030) | 134,105 (2027-2030) | FIXTURE_RESULT records (vtable 0x5672E00) in the fixture manager's year buckets |
| Result and goal events | 74,864 | | result +0x78: 16-byte records `<i person, i second person, u32, u8 side, u8 kind, u8 minute, u8 added>` |
| Statistics frame | 4,958 | 4,771 (dated 2027-08-16 to 2030-12-12; 4,414 of them in 2030) | MATCH_STATS_MANAGER (0x56B5570) +0x20 banks, one per `Temporary/pks_N.obs`; zstd MATCH_STATS60/FIXTURE31 frames |
| Full event stream | 37 retained records | 34 | human manager +0x188 (own team), +0x170 (opponents), +0x1A0 (other): CBE records with 56-byte events and per-side 48-byte shot vectors |
| Competition season statistics | 54,312 rows | 54,515 | COMP +0xB0 runtime, +0x390 GAME_COMP_STATS, +0x1278 PERSON_COMP_STATS rows (stride 0xAC) |

Which calendar years are resident changes: on 10 Dec the 2026 bucket was resident and 2027 was
not; on 13 Dec 2027 is resident and 2026 is not. The archive keeps fewer frames after more
matches were played (4,958 to 4,771): the game discards frames of older matches. 31,284 results
had no goal-event vector on 10 Dec; scorers are unknown there (the game did not store them).

## Tables and when they change

`match.idx` is the match identity: `YYYYMMDD * 100000 + home team idx` (a team plays at most once
a day: 0 collisions in 134,105 results; 66,021 teams). It is the same in every snapshot and in a
full rebuild, so a table that adds a match computes its idx without reading another table. The
earlier idx (row number of one pass) is gone; tables built with it are not carried into a new
snapshot (`layout` token) and are built again on first reference.

Every match table is `append`. A refresh (`new_rows`) first passes a gate: nothing is read while
the fixture fingerprint (bucket vectors of the main and linked years, 0.1 s) or, when that moved,
the result fingerprint (pointers of the resident results, 0.6 s) equals the one at which the table
was last brought up to date in this process. Unplayed fixture records being replaced or moved
change the first and not the second, so browsing the calendar or a match in progress costs 0.7 s
a reference at most and never a rebuild. When results were added, the light index (record
pointers, keys, team words of every result, about 2.5 s) says which matches are new.

| Table | Identity (replace key) | A refresh reads | Stored rows when the game drops data |
|---|---|---|---|
| `match` | idx, detail_level (idx) | results not stored, and results of the last 7 days again (`TAIL_DAYS`): a row is replaced only when its detail level rose (a frame or retained record bound after the result was stored) | stay; detail_level is the deepest data stored for the match, never lowered |
| `match_event` | match_idx, source (same) | result vectors of matches with a vector and no `result_vector` rows; frame events of matches without `statistics_frame` rows dated at most 7 days before the newest match holding frame rows | stay |
| `match_team_stats` | match_idx | frames (decoded to the totals) of matches it does not hold, dated at most 7 days before its newest match | stay after the frame is discarded |
| `match_player_stats` | match_idx | the same frames decoded in full | stay after the frame is discarded |
| `match_shot`, `match_pass` | match_idx | retained records bound to a match it does not hold | stay after the retained record is dropped |
| `match_event_stream` | retained_list, date, owner_team_native_id | retained records it does not hold | stay |
| `player_season_stats` | competition_idx, season, person_idx, row_digest (the first three) | every PERSON_COMP_STATS row (9 MB read); only rows whose 172 bytes changed are computed | rows of a season the game resets stay (with their season) |
| `player_season_rates` | ... row_digest, rates_state (competition_idx, season, person_idx) | the keys of every row, and the 67 getter values of the rows the statement reads (below) | as player_season_stats |
| view `team_season_stats` | (view over `match`) | nothing: aggregated from `match` on read | follows `match` |

A frame is archived when its match is played, so older matches never gain one; a frame whose
result is not resident when the match is first seen (its year paged out) is bound only by a full
rebuild. A row of a match stored at full detail and since discarded by the game is still in the
table; a full rebuild of the same day would not have it (the differential below therefore runs
between two states with nothing discarded).

`player_season_rates`. 67 emulated getter calls a row (about 7 ms; 400 s for the save). The table
holds a row for every current key; values are computed only for the rows a statement reads. In the
query pre-pass the statement runs once on a read-only connection where `player_season_rates` is a
TEMP view of the current keys and every rate column records its row (`match_season.statement_rows`);
those rows are computed and stored with `rates_state = 'computed'`, the others hold NULL with
`not_computed`. A statement that names players or competitions computes those rows; one that
filters, sorts or aggregates on a rate over the whole table reads every row and computes the save.
A computed row is reused until its digest changes. The digest covers the row's 172 bytes and the
two words of the competition statistics object the getter reads (+0x7B8, +0x808): tracking the
getter's reads on 40 rows x 72 codes found those, constant image words, 8 heap words shared by
every row and about 12 heap words per row that no row byte locates. Those 12 are assumed to change
only when the row does (the player plays); not verified across a match day.

## First build

Profiled at load 16-23 (13 Dec): the result decode took 53 s, 43 s of it in 665,000 single reads
(`fixtures.record` re-proves the record type, re-reads the database table headers and RTTI
strings for every record). `match_archive._BlockReader` now memoises those reads for one pass
and prefetches the teams, fixture names and stadiums of all records in batches, with every check
still run; the whole `match` build (results, goal vectors, frame headers, retained records) is
13.5 s of refresh at load 13. Frames were decoded in full (18 ms a frame, 87 s)
for every table; they are now decoded to the level each table needs (`match_archive.LEVELS`:
header for `match`, the player projection for `match_event`, the team totals for
`match_team_stats` and `match_shot`, all 11 counter decoders only for `match_player_stats` and
`match_pass`), and `match_pass`/`match_shot` decode only the frames of the retained matches.
`match_player_stats` still decodes every frame in full on its first build (about 35 s of CPU); the
wire parser is the hand-built `saved_match_statistics_wire` and was not changed.

## fm_get_match

`match_tool.get_match_live` finds the match in the light result index (kept per fixture fingerprint;
reused without a check for 3 s) and decodes only that match's record, goal events, statistics frame
and retained record with the table row builders. Team names are an emulated getter (3 ms a team;
naming all 66,021 teams took 200 s), so only candidate teams are named: the teams of clubs whose
stored name starts the given name, then clubless teams with a resident result. Names of the match
come from the snapshot in one statement. The rows are shaped by `get_match` over a private
in-memory database with the match tables' columns: the output is the one the tables would give.
A match that is no longer resident is answered from the snapshot match tables.

## Measured (13 Dec 2030, game idle)

Through `tools.db_query` and the registered `fm_get_match` (p1/integration 8613fca merged), each
step a fresh process, private snapshot copy, 12 Nov 2026 about 02:00-02:30 local. Before: the
code at 8613fca. Load is the 1-minute load average when the statement finished (10 cores; other
agents were running). The brief's own figures (merged tree, load about 25) are in brackets.

| Statement | Before: first reference | After: first reference | After: 4 match days new (164 results) | After: new process, nothing new |
|---|---|---|---|---|
| `SELECT COUNT(*) FROM match` | 73.8 s, load 20 [77.6] | 16.8 s, load 13 | 5.5 s, load 20 (164 added) | 1.6 s, load 21 |
| `SELECT outcome, COUNT(*) FROM match_pass GROUP BY outcome` | 77.5 s, load 33 [60.4] | 2.7 s, load 15 | 2.7 s, load 21 (2,092 added) | 3.0 s, load 21 |
| `SELECT COUNT(*) FROM match_player_stats` | 75.7 s, load 33 [72.1] | 40.2 s, load 16 | 2.7 s, load 21 (5,692 added) | 1.5 s, load 21 |
| `SELECT COUNT(*) FROM player_season_stats` | 9.1 s, load 37 [10] | 9.5 s, load 19 | 2.6 s, load 20 (484 rows of one competition) | 2.3 s, load 21 |
| `fm_get_match(team="Newcastle United")` | 359.7 s cold, 169.8 s warm, load 14-17 (match, match_pass, match_player_stats already built) [389] | 5.5 s cold, 1.8 s / 0.7 s warm, load 19 | 4.0 s cold, 0.4 s / 1.0 s warm | |

* The old warm `fm_get_match` was 170 s because `MATCH_SQL` filters on `team.name`, an emulated
  getter computed for all 66,021 teams on every call. The live path names candidate teams only.
* Other first references after: `match_event` 27.0 s, `match_team_stats` 26.8 s, `match_shot`
  2.8 s, `match_event_stream` 1.6 s, `team_season_stats` (view) 3.9 s including the `match` check;
  `player_season_rates` for the 46 players of one match 4.0 s (54,515 key rows written, 41 rows
  computed), the same statement again 0.6 s. After the 4 simulated days: `match_event` 2.3 s,
  `match_team_stats` 2.8 s, `match_shot` 2.2 s, `match_event_stream` 2.0 s.
* "Nothing new" in a new process pays the result fingerprint and the light index once; in the
  same process a check costs the fixture fingerprint (0.1 s) while nothing moved.
* The simulated new results: `match_differential simulate --since 2030-12-10 --competition 7`
  deleted the rows of matches dated 10-12 Dec from every match table and the Premier League rows
  of `player_season_stats`; no real day tick happened during this work (the game stayed on
  13 Dec 2030).

Differential (`python -m fm_live_mcp.fmdb.match_differential compare`, after the incremental
refresh of the simulated days): every table identical to a full rebuild, row for row
(`match` 134,105, `match_event` 365,758, `match_team_stats` 9,542, `match_player_stats` 197,611,
`match_shot` 486, `match_pass` 23,970, `match_event_stream` 61,159, `player_season_stats`
54,515). The `fm_get_match` answer of the live path equals the old table path's answer field for
field apart from the idx values (Villarreal 0-2 Newcastle, 10 Dec: 46 players, 15 shots,
125 failed passes).

## Fingerprints

With the game idle the fixture fingerprint (0.1-0.2 s) and the result fingerprint (0.5-1.1 s)
did not change in 40 samples over 13.5 minutes (79,530 fixture records, 134,105 results). What
moved the fingerprint in the `cache-accept` run (a 223.7 s rebuild at 02:20 with the game date
unchanged) was not observed here: the owner was not playing during this work. Either cause the
brief names (an unplayed fixture record replaced or moved, the calendar touched, a match in
progress) changes the fixture fingerprint only; the tables now go on to the result fingerprint
and stop there, and even a changed result fingerprint (a reload: every pointer moves) costs one
light index pass and adds nothing, because rows are identified by date and team, not pointers.

## Immutability evidence

* Stored versus fresh: the `match` table of `cache-accept` (old code, built 01:23 UTC) and a
  fresh decode about an hour later agree on every compared column for all 134,105 results (key,
  scores, penalties, aggregate, half time, attendance, referee, competition, season, stadium,
  goal-events state, detail level), and `match_player_stats` (minutes, rating, goals, passes
  completed, xG) and `match_pass` rows agree for every match. Same game date: this shows the
  decode is stable, not that a result survives a day tick unchanged.
* The game drops detail: 4,958 frames on 10 Dec, 4,771 on 13 Dec after more matches were played;
  37 retained records on 10 Dec, 34 on 13 Dec; whole calendar years page in and out (2026 then,
  2027 now). So `detail_level` of a stored match can be deeper than what the game still holds,
  and the frame and retained tables keep matches the game has discarded.
* Not verified: whether any field of a result changes after it is stored (no day tick during the
  work). `TAIL_DAYS` re-decodes the last 7 days on every refresh after a match was played and
  replaces a `match` row whose detail rose; other tables take a frame only for a match they do not
  hold yet.

## Loader contract additions (sources/__init__.py)

* `SourceTable.replace_key`: in an `append` refresh, stored rows with the same values there are
  deleted before an added row is inserted (`supersede`).
* `SourceTable.layout` and the `_source_tables.layout` column (added to older files by
  `ensure_state_columns`): rows are carried into a new snapshot only when the token is unchanged.
* `SourceTable.check_interval`: per-table override of `CHECK_INTERVAL_S` (0: every reference).
* `current_statement()` and `refresh_for_query(..., statement=(sql, params, path))`: the
  statement being prepared. `tools.db_query` does not pass it yet; until it does,
  `current_statement` reads `sql`, `params` and `path` from the calling `tools.db_query` frame.

## Checks against the owner's screens

* Newcastle 0-0 Sheffield United (PL, 7 Dec), 1-2 Liverpool (PL, 30 Nov), 4-1 Nottingham
  Forest (PL, 11 Nov), 4-2 Paris SG (UCL, 26 Nov), Olympiacos 2-2 Newcastle (UCL, 23 Oct): all
  in `match`; the PSG match has half time 2-2, attendance 52,126, referee Aleksei Toom.
* Premier League 2030 from `team_season_stats`: Arsenal 38 points from 16, Newcastle 31 from
  15, fourth (10 Dec).
* Last-five average ratings (club matches, `form_rating`, which is what the game's averages
  use: `player_season_stats.average_rating` is the mean of the stored tenths): Luiz Henrique
  7.50, Jamie Gittens 7.08, Levi Colwill 7.08, Chema Andrés 6.98, Gregor Kobel 6.98, Tino
  Livramento 6.84, Anthony Gordon 6.72 equal the screen. Alberto Costa 7.46 (screen 7.44),
  Jacob Ramsey 7.32 (7.31), Lewis Hall 6.92 (6.91) differ by 0.01-0.02; the hundredths
  average gives Ramsey 7.31 but Hall 6.92, so the screen's rule for these three is not
  established.
* Premier League per-player season counters against the per-match sums: minutes agree for
  483 of 483 players, goals for 481 of 483.

## Known gaps

* Team pass totals in the frames differ from the sum of the players' stored pass counters in
  7,596 of 9,742 sides, by equal and opposite amounts per match (±135..160): the team field's
  meaning is not established; use the player sums.
* Results without a goal vector have no scorers; the game did not store them.
* Weather is not stored on the result or the frame header.
* `match_event` has no booking minutes: frames store yellow-card counts, and the minute only
  for dismissals.
* Event-stream categories other than passes (6..11), shot ends (1..5) and own-goal markers (49)
  are unlabelled; the plugin names only CBE_TOUCH and the CBE_END_* values.
* Code 6 (Team Goals) is a signed byte in the game: a row holding 142 reads -114, as the game
  shows it.

## Failed passes (papercut pc-e07ee852)

`match_pass_decode.py` reads every pass of the retained full-detail matches with the CBE builder
0x488A5A4 and the category function 0x48930AC as the map (field list in the module docstring).

| Category | Outcome | Evidence (23 matches, 824 players) |
|---|---|---|
| 7 | completed | receiver = linked event actor (+0x29), CBE_END_PASS_COMPLETED |
| 8 | intercepted | linked event is an opposing possession-won event (category 52) for 1,187 of 1,188; that player is `won_by` |
| 9 | blocked | linked opposing block (category 25) for 96 of 96; the builder also gives 9 for a linked clearance (engine kind 2) |
| 11 | out_of_play | the path ends outside the pitch half-extents on 458 of 458 |
| 10 | not_completed_other | a goalkeeper save/claim as the linked event (builder 0x488AF44), or no link and engine outcome 1, 2, 5, 7 or above 8; the path end is the engine's intended target point (0x488AF2C) |

* Intended recipient of a failed pass: no player is stored anywhere. The builder writes +0x29 = 0xFF
  (0x488A67C) and fills it with the linked event's actor (0x488AD08) only for category 7 or 12. The
  live engine pass event (captured during West Ham v Newcastle, 13 Dec 2030: the pending window at
  engine+0x14A58+0x178) holds an intended target point at +0x10/+0x14 from creation, but no
  target-player byte (none of its first 0x100 bytes or pointed-to objects equals the receiver slot
  on the completed passes captured). The builder keeps the target point only for category 10;
  for the other categories it is discarded at conversion, so it can be persisted only by sampling
  the engine's pending window during play (`target_x`, `target_y`).
* Origin and destination: the path's first sample equals the pass location on every pass; the last
  equals the linked event's location for 1,142 of 1,188 intercepted, 91 of 96 blocked and 4,105
  completed passes (`end_state`).
* Displayed minute: CBE +0x25 (engine +0x6C) is the elapsed minute; +1 equals the stored goal
  minute on 60 of 62 goals, the other two differ by one. +0x26 is the second.
* Counters: per player, completed + failed-by-type equals the stored attempts and completions for
  824 of 824 players; ball winners' credits never exceed their stored possession_won (824 of 824),
  but exceed their stored interceptions for 72 players, so the game's interceptions counter is not
  the set of passes they cut out.
* Categories named by the stored per-player counters (exact on 652 of 652 players): 26/27 tackle
  won/lost, 28/29 aerial won/lost, 34 dribble, 52/53 possession won/lost, 37/38/39 saves held,
  parried, tipped, 20 yellow card, 12 cross completed.
* Not decoded: phase of play; which of the engine outcomes 1, 2, 5, 7 a category-10 pass had
  (the category function collapses them, and no linked event is converted).

Villarreal 0-2 Newcastle (10 Dec 2030): 1,024 attempts, 899 completed, 56 intercepted, 6 blocked,
45 other, 18 out of play; 46 of 46 players reconcile.

## Pass types, restarts and throw-ins (flags word)

`match_pass_decode.pass_type` names the bits of the event flags word (+0x30); the module docstring
gives the code sites and the checks. Every pass row now carries `restart`, `key_pass`,
`chance_created`, `assist_marked`, `flags` and `counted`.

| Flag | Meaning | Check |
|---|---|---|
| 0x008 | throw-in; not a counted pass attempt | 143 of 143 flagged events start on the touchline; 5 of 5,571 unflagged passes do |
| 0x040 | corner | 71 of 72 flagged events start at a corner flag |
| 0x010, 0x020 | free kick (engine flag bit 4 without, with bit 6) | Lille v Newcastle: flagged events per taking side equal the fouls stored against the other side, 10 and 8 |
| 0x002 | key pass marker (engine kind 24) | per player never above the stored key passes |
| 0x400 | chance created marker (engine kind 27, counter +0xA0) | per player never above the stored chances created |
| 0x004 | assist marker (engine kind 0, counter +0x9F) | found on one pass (two copies of one match in the 13 Dec capture); on none of the 5 assists of Lille v Newcastle |

`decode(..., include_uncounted=True)` also returns the throw-ins, with `counted` False. The
`match_pass` table still holds the counted attempts only and has no column for these fields; the
flags of every event are in `match_event_stream.flags`. The markers are set after the event, when
the game finds the record of the pass; a missing marker shows nothing.

The same records are written into the save. `saved_match_events.py` reads them with the game closed
(docs/saved-match-passes.md).

## Live match

Captured during West Ham v Newcastle (Premier League, 13 Dec 2030) in `cache-match/live/`:
`ht1.pages.z` (half time, 22:50:05Z, 41,063 pages reachable from the match client and engine),
`ht1.report.json` (hand-built reports, both statistic scopes), `engine_events.pkl` (1,439 engine
events sampled from the pending window engine+0x14A58+0x178 every 0.05 s, 62' to full time, every
version kept), `watch2.json` (both scopes every ~25 s), `ft1.pages.z` (23:18:55Z, after full time).

* The engine keeps its own event records only in a short pending window (about 8 events); they are
  freed once converted into the stored event records. The intended target point (+0x10/+0x14) and
  the unresolved outcome (255) exist only there.
* At half time the two hand-built scopes disagreed (client snapshot: Newcastle 5 shots, xG 0.63,
  219/258 passes; simulation: 4 shots, xG 0.24, 211/249); in the second half they agreed whenever
  both read. During running play most reads fail with "Game state changed during read".
* The generic routes (keyed getters, match-screen handlers) were not run against the live match:
  play resumed before that step.

## A frame the game has not flushed (14 November 2026)

The game writes a statistics frame into its bank with `fwrite` and does not flush, so the newest
frame's last bytes can sit in the bank FILE's buffer while the disk file lacks them or holds older
bytes there. `match_archive` and `live_match_backing` read the bank with `pread` from a descriptor
of their own, which sees only the disk. On 21 Jan 2031 the newest frame of `pks_3.obs` (key
142293) had its last 2,508 of 3,380 bytes in the buffer: the match had no rows in
`match_team_stats` or `match_player_stats` (no note), and `fm_query_match_data` failed with
"Invalid or oversized compressed frame". The retained shot, key-pass and possession readers call
the same function, `live_match_backing.read_selected_matches` (not run in that state).
The frames carry zstd's content checksum (descriptor 0x04), so wrong bytes fail to decompress;
they did not give other statistics.

Both readers now read what the game would read: the bytes `pread` returns with the unflushed
bytes laid over them (`fmdb/stdio_file.py`). The position is the kernel's file offset of the
game's own descriptor (`proc_pidfdinfo` on the game's pid and the FILE's `_file`), where libc's
flush will write, and the bytes are the game's FILE buffer `[_bf._base, _p)`, read from the
bank's FILE (`store +0x18 > stream +0x18 > +0x18 > +8`, which both readers already walked to for
the descriptor). The reader's own descriptor has no part in it: its offset is the reader's.
`match_archive.banks` takes the bytes with the index (FILE, buffer and offset read twice);
`read_selected_matches` reads them through its read set, so its final `verify` rechecks them, and
rechecks the offset. Bytes that cannot be placed are left out, as before, and a frame that then
fails says why (`frame bounds or header invalid (game file has unflushed write data (...))`).

Checks, the same state: `match_team_stats` gave 2 rows (Lausanne 14 shots, 7 on target, 13
corners; Luzern 5, 4, 7), `match_player_stats` 52, and `fm_query_match_data` the same team
totals. `tests/test_fmdb_game_files.py` makes that state with this machine's libc (a frame larger
than the buffer written inside the file, `__SOFF` clear) and requires the disk alone to give no
frame, the overlay to give the frame, and the frame to be the same after libc's flush.

