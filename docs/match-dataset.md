# Retained match SQLite dataset

Run `python -m fm_live_mcp.match_dataset --capture FIXTURES.json --player-rows PLAYER_ROWS.csv --team-totals TOTALS.json --retained-players PLAYERS.jsonl --output matches.sqlite`.

Inputs are explicit capture paths, so the exporter works for any save. Optional selectors are `--team-id` (native team ID), `--date-from`, `--date-to`, and `--competition-id` (native competition ID). Output must be a new path. The exporter never contacts the game or opens archives.

`build_connection(capture, player_rows=(), source='capture', **filters)` exposes the same relational projection in memory. The caller closes the returned SQLite connection. Optional keyword inputs `team_totals` and `retained_players` add verified frame projections.

Tables: `fixtures`, `events`, `player_matches` (roster form-ring rows), `player_fixture_candidates`, `retained_players` (all frame rows including opponents), `team_totals`, `coverage`, `metadata`. Every source row preserves `raw_json`. Fixture refs remain session scoped. Native match keys, canonical IDs and source-local words remain separate fields.

Player form joins require matching date, competition native ID, own team database index and opponent native ID. `join_state` reports unique, ambiguous or unmatched; the `joined_player_matches` view includes only unique candidate joins. A unique candidate is a relational match within this capture, not proof that the source ring has a native fixture pointer. All ambiguous candidates remain queryable. Frame joins require a unique native match key. Unresolved frame person/team words are never silently converted into canonical identities.

```sql
SELECT competition, count(*) AS fixtures, sum(home_score + away_score) AS goals
FROM fixtures GROUP BY competition;

SELECT f.date, f.home_team, f.away_team, t.side_index,
       t.shots, t.shots_on_target, t.expected_goals
FROM fixtures f JOIN team_totals t USING (fixture_id) ORDER BY f.date;

SELECT player, sum(minutes), count(*)
FROM joined_player_matches GROUP BY person_index ORDER BY sum(minutes) DESC;

SELECT identity_state, count(*) FROM retained_players GROUP BY identity_state;
```

Null is unknown, never zero. Raw event codes, clock words, second actor words and unnamed wire fields retain source semantics; this export does not invent event labels or assists. Missing loaded fixtures, uncaptured players and totals remain coverage gaps. Database indices apply only within their source save snapshot. Existing stored score components are preserved in raw JSON; convenience score columns use source `final_score` excluding penalties.

Add `--raw-frames RECEIPTS.json` to embed complete decompressed match frames. The receipt has `records[]` entries with `key`, `raw_path`, `raw_sha256`, and `raw_length`. The exporter validates the hash, byte length, decoded internal match key and unique fixture join. `raw_frames.raw` is a SQLite BLOB, so future decoders can reanalyze the complete source offline; `source_json` preserves the capture receipt. The API also accepts bytes directly as `raw`. No unrelated files are searched.

Add `--player-metrics METRICS.jsonl` to preserve field-specific metric projections keyed by fixture, side, person word and slot. Each row remains in `player_metrics.raw_json`; its field registry should accompany the capture. Shots/targets conserved against team totals carry stronger evidence than fields without an independent aggregate oracle. Exact duplicate fixture records remain separate and make candidate joins explicitly ambiguous.

`player_match_analysis` is the ready-to-query player view: fixture date/teams/score, canonical person/name, stored minutes/goals/assists/rating, and nine named action fields. Metrics join on exact fixture, native key, side, player word and stored slot. Missing metrics remain NULL with `action_source_state='not_captured'`. Unknown minutes remain NULL; zero minutes remain zero with `minutes_state='zero_stored_minutes'`, which does not infer bench/nonappearance semantics. Aggregate all observed attempts and xG before dividing by `NULLIF(sum(minutes),0)`; known zero-minute rows may contain attempts. Require an adequate total stored-minute threshold, and report unknown duration coverage.

## Refresh directly from the open game

Use the installed package's supported live source adapters, with an explicit senior team native ID and date interval:

```sh
python -m fm_live_mcp.export_live_matches --team-id 688 --date-from 2030-07-01 --date-to 2030-10-28 --output /absolute/path/new-matches.sqlite
```

Replace every selector and output with the desired scope. Optional `--competition-id` restricts competition. `--team-id` is a native club/team identity, not a database index or display name; discover it through `fm_find_clubs` or fixture identities. The command checks resident coverage, continues empty fixture pages, excludes reserve/youth teams, captures at most 500 matches in batches of at most 16 and refuses existing outputs. Missing years and missing active-bank frames stay explicit. It embeds verified raw frames, canonical retained players, nine action columns, team totals, events and source receipts. It checks the save before/after capture and detaches automatically. It does not collect separate roster form-ring rows; the complete retained frame player table is the live source. A changed native load, unrecoverable byte changes, unsupported data and exhausted budgets fail without a partial output.

The live export defaults to the selected club's senior side. Opponent team types never narrow that selection: reserve, youth or unknown opponents remain included when the selected club's senior side is known. Use `--include-youth-reserves` to include the selected club's other team types. Native team IDs identify the owning club across senior/reserve/youth records; database index plus native type distinguishes those teams.

For competition-wide comparisons omit the team selector and supply a competition ID; at least one of team or competition is required. Example Premier League matchweek export:

```sh
python -m fm_live_mcp.export_live_matches --competition-id 11 --date-from 2030-10-25 --date-to 2030-10-27 --output /absolute/path/matchweek.sqlite
```

Competition-only mode defaults to contests with at least one known senior side and retains every opponent type. `--include-youth-reserves` includes other selected competition records too.

`retained_players.expected_goals` and `player_match_analysis.expected_goals` expose the retained individual match xG float. The named view accepts an exact-identity optional metric projection or the embedded player row. NULL remains unavailable and stored zero remains zero. Team-side xG sums provide an independent conservation check, with float32 rounding tolerance. Expected assists use their own decoded source field; an open-play xA split is unavailable.

Team totals additionally retain nullable attempted/completed passes, corners, the signed native possession time counter (units unknown), native-computed possession share and its availability state. Negative/overflow possession inputs remain unavailable; pass completion with zero attempts remains NULL. Computed percentages are decoded native calculations, with no claim that they match a displayed UI value.

Optional decoded goal-crossing records populate `goal_crossings`; every record's coverage is retained even if it has zero crossings. Geometry keeps unresolved units/viewpoint explicit, and credited-player crossings do not establish complete shot or scoreline coverage. `retained_players` and `player_match_analysis` preserve typed participation intervals/native labels plus expected assists, key passes, open-play key passes and chances created. These creator fields are independent stored counters; no subset invariant is inferred.

`entry_state_policy` must be supplied explicitly to derive `sub_entry_context` from captured events/players. Without a verified source policy the table stays empty. Derived rows retain unknown scores and same-minute ambiguity, plus their full raw result.
During normal simulation progression, scoped captures first use strict 14-day windows. Only a volatile window splits into single-day windows with small strict pages and bounded retries. A failed byte recheck retries the same page; an expired cursor discards and restarts only the current day. Earlier complete windows remain captured. Every native byte, route, source-file and identity guard stays active. Date/save-count changes are recorded as first/last observed save states; cross-day results are explicitly non-atomic. A native load-epoch or stable career change rejects the capture and requires a new attachment.

Team crossing attempts/completions and completion percentage are nullable. `crossing_counts_state` distinguishes an available native aggregate from signed-16 overflow or inconsistent individual counters. These team values reconstruct the native sum of stored individual counters; they are not an independent serialized team oracle. Zero attempts yield an unavailable completion percentage rather than zero percent.

## Crossing comparisons

Run the reusable report against an exported `.91` schema without opening the
career or attaching to FM:

```sh
fm-match-crossing-report --database /absolute/path/to/league.sqlite \
  --competition-id 11 --team-id 713 --date-from 2030-08-01 \
  --date-to 2030-10-28 --venue away --leader-sort attempted --leaders 5
```

`python -m fm_live_mcp.match_crossing_report` accepts the same arguments. Dates
must be canonical `YYYY-MM-DD`. `--venue home|away|all` is relative to each
historical club-team side, so a selected club's away sample compares with the
other clubs' away samples. `--team-index` separates reserve/senior groups sharing
a native club ID; the report never merges different historical team indices.

The report provides attempts/completions per match, pooled completion percentage,
crosses per100 attempted passes, exact competition ranks, and per-match selected
team/opponent counts. Rank1 means the highest observed value, including the most
crosses faced for opponent metrics. Missing pairs do not enter complete-data
ranks; known subtotals remain separate. Zero attempts have null accuracy. Source
metadata and exact observed samples qualify comparisons: an exported subset does
not prove whole-league or completed-match coverage.

Named leaders have separate all-cross and open-play categories. Choose
`--leader-sort attempted|completed|accuracy` explicitly; percentages use pooled
counts. Equal metric values receive ranks1,1,3, and cutoff ties are retained with
native IDs as stable ordering keys. No subset relationship between the two
native crossing categories is inferred. `--minimum-minutes` applies after all
stored counters, including zero-minute rows, have been summed. Missing active
minutes leave per90 unknown. A missing whole player side leaves the affected
player leaderboard unavailable rather than inventing zero contributions.

For programmatic use, `report_connection(db, **selectors)` reads the caller's
pinned connection; `crossing_report(path, **selectors)` opens one read-only SQLite
transaction. `report_requirements()` and `missing_report_fields(db)` provide
machine-readable schema checks. A source without crossing columns returns an
explicit unavailable response, with no game fallback or source refresh.

## Fresh live player action rankings

Use `fm_get_live_match_rank_metrics` to discover the fixed count catalog without
attaching or collecting data. `fm_rank_live_match_players` takes one fresh
competition/team date-scope capture, then returns a compact ranking instead of
thousands of player rows. It never opens a captured export or disk career file.

Select `normalization=total` or `per90`. Progressive passes additionally support
`per_100_pass_attempts`:100 times summed progressive passes divided by summed
attempted passes. This measures progressive-pass activity relative to passing
volume; it is not accuracy, success, carries or an established distance threshold.
With no explicit minimum, totals use0minutes and normalized ranks use450minutes.
The returned `minimum_minutes`, exact fractions and cutoff make those choices
visible. Sum all observed counters before applying that threshold, including real
zero-minute actions. Only proved unused-bench null minutes contribute a known
zero; unknown active minutes withhold per90. A known minute lower bound that
already meets the cutoff may qualify totals/per100 despite other unknown minutes.

Player groups use canonical PERSON ID plus the historical fixture TEAM native ID
and database index. Names never establish identity, and transfers/reserve groups
are not pooled into a current club. Defined exclusions (known below-minimum or
zero-denominator groups) are distinct from uncertain metrics/minutes/identities.
Missing historical player sides withhold the affected team groups. Materialized
fixture and backing coverage qualify the population; match/season completeness,
current roster, role and eligibility are not inferred.

Exact competition ranks are1,1,3. `limit` selects rows before all cutoff ties;
consume every `next_cursor` to obtain tied rows beyond the fixed100-row page.
Pages reuse one `capture_id`, are immutable for five minutes, and expire on a
career/load change. Up to eight `highlight_person_native_ids` return their ranks
outside the limit or a known exclusion reason. Neither paging nor highlights
collects another native scope.

The capture budget supports512selected fixtures (including a380-match league
season), with bounded16-fixture native batches and guarded per-window collection.
Raw frame bytes, child hex, unrelated counters and side totals are discarded
before windows accumulate. Larger ranges fail explicitly; unloaded/nonretained
sources remain unknown. The rank cache contains only computed rows/provenance.

## Live comparisons across two date windows

`fm_compare_live_match_windows` compares a selected historical team in one
competition across two explicit date ranges. It establishes one active-career
load epoch and captures the union: overlapping/adjacent ranges merge; disjoint
ranges do not fetch the intervening gap. Source frames, player hex and unrelated
fields are discarded after native checks, before guarded windows accumulate.
The global budget is512selected result records. No disk-save or captured-export
fallback runs.

Team summaries include observed fixture/venue samples, for/against shots,SOT,xG,
pooled xG per shot, passing volume and named creation context per match. Creator
activity per100 attempted passes uses summed numerators/denominators; it is not
accuracy. Missing counters produce null main totals/rates with separate known
subtotals. Player/team shooting sums and canonical side ownership are checked;
only fully checked sides contribute to the reconciliation count.

Returning groups have the same canonical PERSON and historical TEAM native ID
and database index in both windows. Compare a named additive count per90; both
periods must meet their independently returned minute thresholds (default450each).
A player observed in only one window is not assigned a zero rate in the other.
Unused bench null minutes and real zero-minute actions follow the live ranking
policy. Unknown participation/metrics/identities stay distinct from known
below-threshold exclusions. Window ranks and comparison-minus-baseline change
ranks are exact fractions; choose increase/decrease sorting explicitly.

`minimum_team_matches` flags small observed samples and does not establish
statistical confidence. Overlapping fixture counts and source-enumeration gaps
remain explicit. No adjustment for venue/opponent mixture or game state, current
roster/role, completed season, or causal tactical explanation is implied.

`limit` retains all cutoff ties across fixed100-row pages. Follow every
`next_cursor` with identical selectors; pages share `capture_id` and do not fetch
native data again. Five-minute expiry and career reload invalidate the cursor.

## Optional retained shot maps

Add `--include-shot-map` to a scoped live export:

```sh
python -m fm_live_mcp.export_live_matches --team-id 688 \
  --date-from 2030-10-01 --date-to 2030-10-28 --include-shot-map \
  --output /absolute/path/new-shot-matches.sqlite
```

The shot reader reuses each existing checked fixture/frame batch. It does not
recapture a season for every fixture. Each complete capture window includes its
shot packets before it can enter the export. The file appears only after the
SQLite transaction has committed; existing or concurrently created outputs are
preserved. Simulation progress across windows still carries the documented
`cross_day_atomic=false` scope.

The offline `fm_live_mcp.match_dataset` command accepts the same checked packets
through `--shot-maps PACKETS.json` (a list or an object containing `records[]`).
It uses only that explicit input path.

This option adds schema-version2 tables `shots`, `shot_map_coverage` and
`own_goal_markers`, plus the `shot_map_analysis` view. Without the option, the
existing schema and capture behavior remain unchanged. Packets bind through the
same captured fixture reference, date, competition, home/away native IDs and
team database indices, with the native match key checked separately. A reused
native key cannot authorize a shot join on its own.

Every selected fixture has two source-coverage rows. Only `state='available'`
contains reconciled numeric counts, including genuine zero. `not_retained`,
unavailable and uncaptured sources retain NULL counts. Own-goal markers occupy
a separate table and never inflate attempts; their beneficiary and event sides
remain distinct. Every source row and packet retains raw JSON. Coordinates are
raw native values with unverified units/viewpoint; this export does not rotate
them or infer pitch orientation, actors or clocks.

Read a pinned local export without contacting the game:

```python
import sqlite3

with sqlite3.connect('file:/absolute/path/new-shot-matches.sqlite?mode=ro', uri=True) as db:
    db.execute('BEGIN')
    coverage = db.execute('SELECT state, count(*) FROM shot_map_coverage GROUP BY state').fetchall()
    available = db.execute("""
        SELECT date, home_team, away_team, side_index, shot_count,
               shots_on_target, expected_goals, own_goal_marker_count
        FROM shot_map_analysis WHERE state='available'
        ORDER BY date, fixture_id, side_index
    """).fetchall()
```

`shots.native_shot_type`, `is_penalty`, `shot_situation` and
`shot_situation_state` preserve the checked reader's optional penalty projection.
Missing type coverage stays NULL; a known non-penalty remains false and is
labelled `non_penalty_unspecified`, without inferring open play, counterattacks
or another situation. Own-goal markers stay outside this table and have no
statistical penalty classification.
