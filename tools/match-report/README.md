# Offline retained-match report

`render_match_report.py` builds a single offline HTML analytical report from checked JSON evidence. It reads files only: it never attaches to Football Manager or invokes game code. The bundled renderer is included, so rendering needs Python 3.10+ but no npm installation.

```sh
python3 tools/match-report/render_match_report.py \
  --postgame /absolute/postgame.json \
  --passes /absolute/named-pass-edges.json \
  --averages /absolute/actual-average-positions.json \
  --heatmaps /absolute/native-heatmaps.json \
  --halves /absolute/retrospective-half-verification.json \
  --output /absolute/report.html \
  --receipt /absolute/render-receipt.json
```

Optional `--pass-attempts` adds reconciled attempt availability, without plotting unverified ball paths. Optional `--orientation-proof` adds independently checked match-specific controls; it does not promote tracking direction into a general semantic claim.

The current source adapter expects the verified batch-163/166/168 schemas. `prepare(postgame, passes, averages, heatmaps, halves, pass_attempts=None, orientation_proof=None)` returns a normalized report dictionary and rejects inconsistent fixture identities, totals, missing actor joins and half boundaries. `render(data, output)` writes the canonical HTML and returns its path/size/SHA256 receipt. Source fingerprints are embedded in the report and its downloadable JSON. Supporting evidence remains in its original projects.

## Interpretation

- Shot circles use actual xG and independently bound attacked-goal orientation. Circle area represents xG.
- Directed passing connections use checked completed-pass counts and actual stored player mean coordinates. They are connections, not observed ball routes. Full-match means can combine different playing intervals; they do not describe a simultaneous XI or tactical formation.
- Tracking axis 0 is lateral/width and axis 1 longitudinal/length. Physical metres, human left/right and signed attacking direction are not asserted. Pitch markings are schematic.
- Official stored means include real zero observations and post-exit zero padding. Defaults use tracked streams without trailing zero pairs when those pools are provided. The 90-minute comparison subset and full official stored-reference alternatives remain explicit. No individual zero observation is silently removed; sample counts are not minutes or time shares.
- Heat maps reconstruct the traced native interpolation, quantile normalization and smoothing algorithm. They have not been compared with the rendered game UI. Clean team pools combine eligible raw grids once before processing. Each selected map is normalized independently: intensity is not comparable across players, teams or periods.
- Half splits use proved native period boundaries from retrospective observations of the same fixture. They do not claim a single historical live snapshot. A selected heat segment is assigned by its current sample tick; its previous endpoint may precede the boundary. Native ticks are not displayed as minutes.
- Player detail preserves all retained rows, including unused players. Unsupported or unqualified ratings remain null; source form values and qualifications remain available in JSON.

The HTML embeds gzip-compressed report data and all JavaScript/CSS. A modern browser with `DecompressionStream` support is required; no network requests, source files, local server or application installation are needed to open the result.

## Rebuild and verify

```sh
npm ci --prefix tools/match-report
npm run build --prefix tools/match-report
node tools/match-report/verify_report.mjs /absolute/report.html /absolute/evidence-directory
```

The verification script uses an isolated headless Google Chrome process, exercises all four views, half/team filters, pitch zoom, keyboard heat inspection and JSON download, and checks a 390px mobile viewport. It records errors, network requests, timings and screenshots without opening the user's browser or game screen.

## Fresh capture adapter and comparison controls

For the current combined retained-source capture schema:

```sh
python3 tools/match-report/render_match_report.py \
  --capture /absolute/capture-observed.json \
  --heatmaps /absolute/native-heatmaps-with-clean-pools.json \
  --output /absolute/report.html --receipt /absolute/receipt.json
```

`prepare_capture(capture_path, heatmaps_path)` checks the native epoch receipt and reuses the same normalizer for full team/player statistics, named native spatial data and pass connections. Source fragments and original capture hashes are retained. Without `--halves`, only the full match is available; no half is inferred from clock gaps or orientation. Newcastle's Lille source has 17 strict Lille shots and 10 separately guarded source-observed Newcastle attempts. The latter are opt-in, counts/actors verified, native xG unreconciled; no strict tolerance is widened. The default remains strict rows only.

Pair the two teams’ heat/position/network views with the comparison button. Heat maps retain separate normalization and explicit selected-stream coverage. Player tables expose every retained typed match counter, including discipline, open-play crosses, possession lost and aerial attempts; every metric is sortable. All numeric team source fields are accessible below the headline table, with original field names and qualifications. JSON retains those fields and the full verification scope.

## Pressure and key-pass enrichment

Add `--pressures /absolute/lille-pressure-control.json` and `--key-passes /absolute/live-lille-control.json` to the combined-capture command. Both are optional and require `--capture`.

`add_pressure_evidence(data, capture_path, pressures_path)` binds the fixture, original raw-frame SHA256, every canonical player/slot/minutes and all 43 raw-child byte hashes. It checks attempts/completions, preserves undefined zero-denominator rates, and recomputes pooled side ratios. The action panel ranks pressure attempts by total/per90 or completion percentage, with a minutes filter. Statistical pressures do not establish regains, escaping the press, location or tactical causation.

`add_key_pass_evidence(data, capture_path, key_passes_path)` binds the same frame and complete canonical roster, verifies official actor counters, and retains explicit partial-side and mismatched-actor states. Official key-pass/open-play-key-pass/xA totals remain separate from marked native-event annotations. Supplier filtering exposes only supported completed-pass recipients; other annotated categories remain unknown recipient/location. It never supplies an annotation-to-shot/goal/assist link. Missing or withheld annotations remain null/unavailable, not zero.

Run `python3 tools/match-report/test_evidence_guards.py` for six focused source/denominator guards. Run `node tools/match-report/verify_actions.mjs /absolute/report.html /absolute/evidence-directory` to verify pressure denominators/minutes/ranking, every creator selection, withheld and unknown recipient states, JSON export and mobile overflow. This uses isolated headless Chrome and no game/UI interaction.


Combined captures may now accept `--halves /absolute/verified-retrospective-period-packet.json`. The same shot-by-shot and period-boundary validation applies; a fixture identifier alone never licenses reuse of a prior playthrough’s period markers. The capture adapter embeds its observation timestamp, raw-frame fingerprint and original source-capture hash in the downloadable report data and source details.

The football readout derives average xG per shot and pass completion from checked team totals, and names the highest official key-pass contributors. It makes no territorial-control, formation, tactical-cause or separately defined big-chance assertion. Nine source guard tests now include contradictory key-pass closure and missing supported annotations.

## Observed-run report with mixed source scopes

`render_observation_report.py` renders the distinct observed-run schema when no native RESULT has been published. It never calls the retained-result adapter or recasts the observed SQLite as a native match-statistics frame. Supply `--terminal`, `--spatial`, `--passing`, `--database`, `--session-evidence`, `--output`, `--receipt`; optional `--locations` and `--shot-actors` enrich the same immutable sources.

Terminal observations must be strictly FullTime with current=max, byte-verified CBE events, internally closing period chances and matching terminal pass-event bytes/cutoff/fixture. Every named unordered pair must close its period denominator. The database's embedded terminal/positions/pass source-document hashes and shot/pass row counts must agree; its embedded terminal-continuity receipt must bind the exact terminal document and all earlier shot-semantic witnesses.

Spatial snapshots remain earlier independent observations. A concrete document-pair receipt must pin the full configured response hash, actual process PID/start, native terminal epoch, career/save and source identity. Compact means/grids are checked against the full configured calls. This is same-running-session evidence, **not** cross-source spatial byte/epoch identity or a causal join. Without the receipt, the adapter withholds rendering rather than borrow another playthrough's maps. Source ticks remain explicit in methods and JSON; manager-facing map labels keep the earlier-snapshot distinction visible.

Optional pass points verify raw event hash, cursor, original same-owner actor packet guard and every named period-pair count. They are native completed-pass map event points, not release/reception locations or ball trajectories. Optional actor sidecars must match all original event fields, source bytes, client/engine, UID, cutoff and original roster slot/side. They add names to the report only; the immutable observed database's legacy null actor fields are unchanged.

Names, dates, scoreboard, half summaries, largest chance and passing-pair readouts are derived from supplied data. The chosen Forest edition is tied to exact terminal/event/epoch and configured-document fingerprints; identical fixture UID/date alone is insufficient. Tracking direction remains unproved, while shot/pass event attacked-goal normalization is separately source-bound.

`verify_observation_report.mjs` exercises both teams/all periods, all five views, passing denominators, Baas→Enciso's 28-event actual control, named Evanilson original-slot regression, JSON export, full Fit pitch, zoom and mobile width in isolated headless Chrome. No foreground window, native game call, game input or game write is used.
## Complete pass-event location layer

Build a checked offline packet from the original same-capture CBE and native player frame:

```sh
python3 tools/match-report/build_pass_location_source.py \
  --capture /absolute/capture-observed.json \
  --cbe-source /absolute/retained-source-observed.json \
  --output /absolute/pass-location-source.json
```

Add `--pass-locations /absolute/pass-location-source.json` to the capture render command. The optional layer verifies the complete event-buffer hash, exact fixture and frame, original-slot canonical roster, raw player child bytes and every player's attempted/completed counters including zero rows. Legacy raw XY fields cannot enable it. The installed native pass-map binding spans are checked offline by the builder; no game attach or input is used.

Filters select team, player, completed/incomplete events, equal pitch third and central/outer width channel. These are official native pass-map event locations, not proved ball-release points, intended destinations or trajectories. Attacking direction uses the proved source flag; native lateral axes have no human left/right label and physical units remain unasserted. Outside-pitch points stay in denominators and are not moved onto the pitch. Completion percentages use all selected team/player/zone attempts regardless of the outcome display filter. No period, pressure cause or receiver for incomplete events is inferred.

For Lille–Newcastle136941 the full1,697-event buffer yields945 pass events: Lille404/452 completed (one outside-pitch incomplete location), Newcastle429/493. All43 player rows close. Run `python3 tools/match-report/test_pass_location_evidence.py` and `node tools/match-report/verify_pass_locations.mjs /absolute/report.html /absolute/evidence-directory` for identity/tamper/missingness controls and headless team/player/outcome/third/channel, inspection, download and mobile checks.

## Refresh an observed report after retained data materializes

`refresh_retained_report.py` binds a fresh retained capture/database to the prior independently observed edition. Supply `--capture --heatmaps --halves --pass-locations --observations --shot-proof --database-receipt --output --receipt`. It requires the exact independently closed shot/capture/terminal fingerprints, checks every actual shot tuple and canonical actor, verifies the new immutable database hash, and attaches the complete counter-checked retained pass layer. Pressure ratios use all captured typed rows and their real attempts; no missing row is filled with zero.

The default edition uses the fresh full-match player records, full-time tracking and verified shot halves. A separate coverage tab preserves the original final-whistle half passing and earlier snapshot maps. Retained pass periods remain unassigned; the shot-only bridge is never promoted to a retained pass or tracking-half bridge. The refresh adapter forcibly selects `full_match` tracking even if a working heat file contains experimental clipped projections.

Default spatial views include all tracked streams without a trailing zero tail, regardless of played minutes. Official stored references expose every tracked player, including explicitly warned padding artifacts. A 90-minute comparison subset remains optional. The heat data may provide `unpadded_teams`: pool each eligible player's original raw cells, then apply the same verified normalizer once; do not remove individual zero observations. The Forest full-time snapshot has 16/16 Newcastle streams and 13/15 Forest streams in this default pool, with all 31 individual maps/reference means accessible. Native reconstruction remains unverified against the rendered UI; within-map intensity does not compare absolute volume.

`verify_retained_refresh.mjs` checks all player/pass filters, incomplete-event denominators, pressure rates/minimum minutes, preserved half views and mobile width. `verify_full_spatial.mjs` checks default/all-reference/individual tracking coverage, zero-tail warnings, possession phases, paired maps and absence of unsupported tracking-half controls. `verify_report.mjs` checks shot halves, view switching, downloads, fit and mobile rendering; it waits for actual filtered React output rather than reading stale marks during a transition.

## On-demand host command

`scripts/run_match_report.sh` accepts one bounded JSON selector object on stdin and returns one JSON receipt. It uses the installed project's `.venv/bin/python`; install the script and the report modules together. The adviser exposes `fm_match_report` only when this fixed regular backend is present. The model supplies selectors, never source bodies, HTML, output paths, process-local references or shell commands.

- `source: "retained"` requires career name/creation date/version, fixture date, ordered home/away native IDs, competition native ID and checked final score; the native match key is optional. The host opens its own read-only attachment, uniquely rediscovers an exact RESULT, checks score/key and process/career epoch, and detaches. Historical source fallback is forbidden.
- `source: "captured"` requires registered catalog `source_id`, immutable SHA256 `capture_id` and exact `fixture_id`; optional `career_id` must match. The report visibly labels historical capture provenance and preserves its original observation timestamp.

The fixed publisher creates an exclusive content-hashed, self-contained HTML original directly in `~/Agent Outputs`. It refuses symlink parents/files and modified filename collisions, and reuses only byte-identical originals. Publication runs in a subprocess denied network and writes outside that output directory. Source/coverage/renderer receipt metadata is computed before publication. A failed publication attempt reports `artifact_created: null`, since the child may have written before its receipt was lost; retrying identical selectors is safe. Prepublication failures report `false`.

`test_general_report.py` checks selector boundaries, changed/ambiguous results, missingness, output immutability and postwrite timeout ambiguity. `verify_general_report.mjs` checks a supplied captured or missing-section report in headless Chrome for provenance, embedded source hash, missing-map text, undefined values and absence of network/browser errors. Existing `verify_report.mjs` and `verify_full_spatial.mjs` exercise interaction, verified shot halves, downloads, mobile width and all tracking references. A captured report test does not certify the live attachment path.

### Observed recordings before a retained result exists

`source: "observed"` selects an immutable original from `fm_list_observed_match_runs`: supply its exact `source_id`/`capture_id`, then set `fixture_id` to the stringified `official_match_unique_id` from that pinned source's `fixtures` query. Optional `career_id` is checked against the embedded captured career. The generator never attaches to the game for this source kind. An authorized current-match recording is a separate `fm_record_current_match` operation; only registered receipts can be selected here.

The registered observed adapter keeps all available typed catalog tables and their independent scopes. Prefix recordings can omit score, shots and periods; these remain unknown. Completed-pass events do not establish attempts or accuracy. Event-derived shot counters remain distinct from retained PLAYER statistics. No current tactic is used for a historical source. Earlier spatial data stays earlier spatial data even when another source document records terminal events.

Portable prefix tracking can produce an unsmoothed sample-density map on the combined recorded sample extent, with zero pairs and tails preserved. Its bounds are explicitly not pitch dimensions, and its samples do not establish minutes or physical distance. Existing captured density tables retain their original grid/scope. An optional shot map requires captured pitch geometry plus a proved attacked-goal flag in every selected shot record; otherwise only the typed records are shown.

Run `test_observed_report.py` for generic different-career prefix/missingness, fixture/career pins, source-document mutation, future-sample rejection and additive score-versus-ended-shot boundary checks. Run `verify_observed_catalog.mjs FILE EVIDENCE_DIRECTORY` for all table counts, team filtering, source-preserving downloads, unknown prefix sections, density/optional shot maps and mobile width in isolated headless Chrome. A synthetic prefix fixture is a consumer check, not positive active-match runtime proof. Activate the backend before applying the companion host schema/guide patch, so an installed v1 backend is never advertised as supporting `observed` prematurely.

## Publication failures

The fixed publisher creates reports exclusively and never overwrites different existing content. If writing, flushing, synchronizing or checking the new file fails, publication fails and no ready receipt is returned. A partial or uncertain artifact may remain. Error cleanup never unlinks the public canonical filename, because a concurrent actor may have replaced it. The generator preserves `artifact_created:null` when publication was attempted but its outcome is uncertain; a failure is not proof that no file exists. Identical complete bytes can be reused on a later successful request; different or partial content remains a collision.
