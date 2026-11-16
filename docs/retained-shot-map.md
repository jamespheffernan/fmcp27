# Selected live retained shot maps

`fm_get_retained_shot_map` accepts an exact live result `fixture_ref` from `fm_find_fixtures`. It checks the canonical fixture, current load epoch, native owner/coach membership, ordered retained CBE lookup and active-bank team oracle. There is no saved-file or archive-load fallback. Retention may be absent or null; neither means zero shots.

Statistical attempts and official `OwnGoal` markers are separate collections. An own-goal marker retains the event/actor side and beneficiary side; it is not a personal statistical shot or a personal goal. In the default `projection="legacy_reconciled"`, each released side must reconcile statistical shot count, native goal/saved target count and float32 attempt xG to within exactly one ULP of the independent team oracle. A missing/ambiguous event link, duplicate event reference across either vector, side mismatch or failed reconciliation leaves that side unavailable with nullable counts and explicit diagnostics. No record is heuristically dropped to repair totals.

Coordinates are unnormalized native x/y. Units, human viewpoint and pitch normalization remain unresolved. The canonical `actor` mapping requires exact fixture side, stored slot and matching canonical TEAM index/native ID; unresolved actors stay unknown. Raw native clock words have no converted time units. Final pass, assister, pressure and normalized shot quality are not inferred.

Paging uses `next_offset` plus `expected_source_id`. The pin includes native epoch, exact fixture signature, raw team-oracle hash, retained records/events and canonical actors. A changed source rejects continuation. The normal response caps100statistical shots per page and100own-goal markers, explicitly reporting marker truncation; the internal batch API returns all bounded rows for exports.

`capture_retained_shot_maps(bridge,session_id,fixture_refs,fixture_captures=None,coach_index=None)` accepts1–64refs and returns one packet for each, including unavailable packets. Its optional private packet reuse requires the checked `_live_capture_epoch`, exact scope/key/hash and fresh native fixture revalidation; the stamp never enters MCP/export metadata. This avoids rescanning the retained bank for every exported fixture.

`native_shot_type` preserves shot48+2C. Statistical rows classify exact native type4 as `is_penalty=true`/`shot_situation=penalty`, through the official NonPenaltyExpectedGoals exclusion chain. Other types are `non_penalty_unspecified`, not open play or an inferred set-piece class. Own-goal markers have null penalty/situation fields. The saved penalty control136157/event1984 independently matches Matteo Pérez Vinlöf totalxG0.8267761468887329 and non-penaltyxG0;120other player controls retain total=non-penaltyxG.

`body_part` is `head` for native shot types2/7/10 and `feet` for0/1/5/6/8/9, through the official WithHeadShotType/WithFeetShotType renderer count groups. Other types retain null body part and null `is_header`; per-side `body_part_counts` reports head, feet and unclassified separately, or nulls when that side cannot reconcile. Own-goal markers are not classified as shots. These fields do not count aerial duels or establish an aerial weakness from a small retained sample.

### Native terminal shot outcomes

Released statistical attempts expose `outcome`: `goal`, `missed_target`,
`hit_woodwork`, `saved`, or `blocked`, from the official end-shot registry
489B1B0 and linked event56+0x2A. Unmapped codes retain a null outcome and raw
category. This is an exclusive terminal category: `hit_woodwork` does not count
every intermediate post contact before another outcome. Own-goal49 markers
remain separate from statistical attempts. Penalty classification is an
independent dimension; a saved penalty has outcome `saved`.

Side `outcome_counts` cover all released attempts before pagination. They are
null for an unavailable side, and zero for a reconciled known-zero side. The
existing shot/SOT/xG availability guards remain mandatory. In particular the
Burnley–Southampton control releases the saved penalty but withholds the other
side whose xG differs by two float32 ULP; outcome labels do not weaken that gate.


## Explicit source-proven attempt projection

Call `fm_get_retained_shot_map` with `projection="source_proven"` to request the separately defined native attempt contract. It returns one primary paged `attempts` collection, not a second overlapping `shots` or `source_observed_shots` collection. `offset`, `limit`, `next_offset` and `total_available_attempts` refer to that collection. Own-goal markers remain separate with their own explicit cap/truncation state. `include_source_observed` belongs only to the legacy projection and cannot combine with this mode.

`native_xg_value` is the unscaled float32 emitted by the original frontend under the official `XgValue` property. It comes from retained shot48+0x20, copied from model source+0x2c. Native source guards verify the original exporter, float constructor, payload builder/writer and distinct aggregate arithmetic before this mode reads the source. A finite value in[0,1] has `native_xg_value_state="verified_native_ui_xg_value"`. This compiled-source proof is not observation of the live rendered UI.

The original aggregate producer adds context-adjusted source+0x30 into team/player xG. The retained payload/wire does not preserve that adjusted contribution: distinct reachable contributions can have the same complete retained payload and serialized bytes. Therefore `credited_expected_goals_contribution` is null with `not_retained_in_checked_shot_representation`. No zero-context assumption or conversion fills it in. `official_expected_goals` retains its independent team source. `native_float32_xg_value_sum` describes the retained values, with an explicit population scope, and is not an official aggregate. The legacy one-ULP comparison remains diagnostic metadata in this mode, not admission of a source-proved field.

Unique linked event/side membership, original record indices/hashes, native outcome/type/penalty/body-part fields, raw clock words and supported coordinates/location remain usable independently. An invalid native value or coordinate becomes null with its own state while other supported fields remain. Rejected event links retain their record identity and known stored native value in diagnostics; they are not promoted into statistical attempts. Unresolved canonical actors stay explicit without erasing known source events/values. `complete_side` requires every statistical record link and both independent integer counters to close. Partial valid rows and their counts/subtotals retain partial scope; they do not become whole-match totals. Unsupported backing/source identity remains unavailable.

The existing source/fixture/career/native owner checks still apply. The source-proven `source_id` binds the original source fingerprint plus projection/version; `native_source_id` retains the underlying fingerprint. Keep the same projection and returned `expected_source_id` on continuation. Changing projection starts a fresh query at offset0; a legacy pin is not a source-proven continuation pin. Missing source/counts remain unknown, distinct from a checked empty source.

Omitting `projection` preserves the legacy response, opt-in observed collection, one-ULP gate and existing quality-report/ranking behavior. New consumers should label rankings/summaries of `native_xg_value` by that metric and obtain credited team/player aggregate xG separately. The current report/adviser compatibility increment remains frozen; migrating them to this explicit contract is a separate reviewed release, not a silent reinterpretation of existing `expected_goals`.
