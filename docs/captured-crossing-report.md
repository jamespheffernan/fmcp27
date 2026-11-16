# Captured crossing reports

Use `fm_list_captured_match_sources` to discover approved historical live-match exports. Copy the selected `source_id` and current `capture_id`; retain its `career_id` when the workflow needs a career pin. Discovery identifies competitions, actual fixture coverage, requested capture scope and the career date observed during capture. These dates can differ: an export scoped through28October can have been collected on29October.

Call `fm_report_captured_match_crossing` with the named source, `expected_capture_id`, explicit native competition/team IDs and inclusive canonical YYYY-MM-DD dates. Optional `venue` is all/home/away; it does not select the flank of a cross. `leader_sort` selects attempted/completed/accuracy, `leaders` is1–20 and `minimum_minutes` retains a visible denominator restriction. No arbitrary path, SQL or live session argument is accepted.

The report reads the shared validated SQLite connection in a read-only transaction and rechecks source fingerprint after the report finishes. A changed export rejects the result. Missing crossing fields return `state: unavailable` with exact table/column gaps and retained source provenance. They never become zero or trigger a live fallback.

Team crossing totals reconstruct the native player-counter aggregate. They are not an independent serialized team oracle. All-cross and separately proved open-play player counts remain separate, with unknown origin/destination/flank and current tactical assignments. The report cannot establish the current squad, player availability or actual next opponent.

Every report list is capped at100rows. `response_bounds.truncated_lists` records original and returned counts and warns that cutoff ties may be truncated. Full field/column provenance remains discoverable in the source catalog rather than repeated in each report.
