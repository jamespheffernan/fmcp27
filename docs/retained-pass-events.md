# Retained pass attempts

`fm_get_retained_pass_events` pages one exact historical result selected by its live `fixture_ref`. It reads the active HUMAN-owned retained CBE source, the same fixture’s official player rows and canonical identities. It does not require a resident match client, game input or saved-file fallback.

First request `offset=0, limit=500`; supply its `source_id` as `expected_source_id` on every later page. A changed source or reload rejects pagination. `total_count` is known only when both sides reconcile. Unavailable side counts are null; no rows is not evidence of zero attempts.

Each available side requires every captured player’s attempted and completed counters to match its event selection. This is separate from shot reconciliation. A completion-oracle or actor-identity failure withholds that side’s rows; an attempted-counter mismatch also withholds them even if team totals happen to match.

## Native meaning

The official CBE converter `48930AC` maps engine event kind12 uniquely into CBE categories6–11. Its outcome lookup is `[7,10,10,11,6,10,9,10,8]`, with other outcomes mapping to10. Category7 has the independent native label `CBE_END_PASS_COMPLETED`. Specific failure reasons for6/8/9/10/11 remain unknown.

The same engine kind12 enters the statistics branch at `493C9B4` (dispatch table `54052EC`, entry12). Bit5 of the engine event’s flags skips the attempt writer. CBE construction copies this selection to event flag mask8. The remaining branch calls `493F4E0`: every event increments named team/player attempt fields, and success1 alone increments completion fields. The ordinary outcome path derives success from engine outcome byte69 equal to0. Linked-event handling is retained by the native converter; the adapter additionally requires exact per-player count closure.

The resulting rows distinguish `completed` and `not_completed`. Only completed rows expose recipients, through the previously proved category7 official pass-map actor-slot consumer. An incomplete row’s secondary byte is not labelled a target or interceptor.

Installed native CBE name registrations and metadata39 do not supply a proved official failure label for6/8/9/10/11. The native `Passes Incomplete` registration is an aggregate selector16, not a CBE failure code or cause. Code10 also collapses several upstream outcome values, so it cannot be reversed into a specific reason. `specific_failure_reason` and `tactical_cause` remain null. `player_counters[*].incomplete_native_category_counts` provides exact numeric-category counts only after full individual counter closure; these codes must not be renamed interceptions, out-of-play, pressure or poor decisions.

## Geometry limits

CBE56 bytes0–23 are a native vector header, not inline coordinates. The constructor builds a bounded sequence of XY samples from linked engine events. Embedded floats18/1C are the native event location also consumed by official pass-map averaging. The adapter copies nested samples under readset checks and rechecks the source, pitch geometry and load epoch afterward.

`native_path_start_*` and `native_path_end_*` mean the first and last stored samples. Their football origin/destination meaning and physical units remain unproved. `origin_destination_state=not_proved`, units null, phase null and displayed time null preserve those limits. They must not be treated as verified trajectories or intended destinations.

`field_position` separately projects the official pass-map event location. The shared direction-bit producer, official pass-map getter/normalizer and attacked-goal predicate prove attack-relative longitudinal direction. Equal length thirds and central-versus-outer width bands are explicit analytical bins, not official FM location names. Locations outside native pitch half-extents stay unclassified. These are event locations, not proved ball-release points; human left/right and physical units remain unknown.

`pass_field_summary` is computed from the complete counter-qualified fixture before pagination. It includes attempted, completed and not-completed counts and rates per side, third, width band and six third/band cells. Rates use attempted passes in that same cell; zero-attempt rates are null. Unavailable sides stay null, and unclassified locations retain their own counts. Never derive a whole-match zone denominator from one event page. Pitch geometry participates in source identity and fresh source rechecks.

## Current controls

The captured 2 November2030 Newcastle–Southampton result136523 has1,800 native events. Exact native pass selection returns1,043 attempts: Newcastle446 with388 completed and58 not completed; Southampton597 with524 completed and73 not completed. All40 player attempt and completion counters close. Every returned attempt has three stored XY samples. Existing Forest/Burnley controls independently close80 additional player counters.

The retained LOSC Lille–Newcastle result136941,6 November2030, was freshly read on native date11 November. All43 individual controls close945 attempts: Lille452/404 completed and Newcastle493/429 completed. Newcastle has64 not-completed passes. Its middle/outer event-location cell has27 of181 attempts not completed(14.9%); attacking/outer has17 of73(23.3%). The larger count and higher rate answer different questions. All493 Newcastle events are located; one Lille event outside native pitch extents stays unclassified. Alberto Costa, Chema Andrés, Luiz Henrique and Jay Robinson tie with8 not-completed passes each. The data does not distinguish specific failure causes.

The optional tool adds no SQLite schema or overwrite behavior. Snapshot/export owners can consume the exact rows with their fixture/source metadata and must retain the geometry limits.

## Later findings (11 to 14 November 2026)

The sections above predate two pieces of work and are superseded where they differ.

* Failed passes are decoded (`fmdb/match_pass_decode.py`): outcome (intercepted, blocked, out_of_play, not_completed_other), the opponent who won the ball, the displayed minute and second, and the path from the pass location to the linked event. `specific_failure_reason`, `won_by_*`, `displayed_minute` and `origin_destination_state` carry them.
* The mask8 events are throw-ins: 143 of 143 captured ones start on the touchline. Rows also carry `restart` (corner, free_kick or null) and the game's `key_pass`, `chance_created` and `assist_marked` markers.
* The event location is where the pass was played from, and a completed pass's last path sample is where the recipient took the ball: see "Where the point is" below. The "not proved ball-release points" statements above are superseded.
* The same event records are written into the save and can be read with the game closed: `fm_list_saved_match_event_streams` and `fm_get_saved_match_passes` (docs/saved-match-passes.md).

## Where the point is (14 November 2026)

The event location (`native_event_x/y`, `field_position.native_pass_map_location`) is the place the pass was played from. `field_position.location_semantics` is `official_pass_map_event_location; pass_origin_proved` and `field_position.ball_release_location` repeats the point.

* **Restarts.** A restart is played from a place the laws fix. Throw-ins: 143 of 143 on the touchline. Corners: 71 of 72 at a corner flag. Kick-offs, in Burnley v Newcastle of 7 January 2031 (0-1), read from the save: three of its 1,134 passes and throw-ins start within 0.75 of the centre spot, all at (-0.5, 0.0). They are the first pass of the match (Broja, 1:00), the first pass of the second half (Woltemade, 46:01) and a Burnley pass at 89:21 (Dennison). The match's 21 throw-ins all start on the touchline (|x| 34.12 to 34.58) and none ends there.
* **The ball's path.** The location equals the first sample of the stored path on every pass (23,881 of 23,881 in 23 matches).
* **It is not the reception.** In the first 900 passes of the Burnley match, 758 completed passes are followed at once by a pass from their recipient. The recipient's next pass starts within 2 units of the first pass's location on 2 of the 758 (median distance 13.3).

The last path sample of a completed pass is where the named recipient took the ball. The game's event builder ends the path at the event the pass links to and writes that event's actor as the recipient (`fmdb/match_pass_decode.py`). On the same 758 pairs the recipient's next pass starts within 2 units of that last sample on 404 and within 5 on 579 (median 1.7); the rest is the distance he carried the ball. `field_position.sampled_path_endpoint` gives the sample with its attack-relative coordinate, pitch third, channel and `semantics`:

| Native category | `semantics` | Evidence |
|---|---|---|
| 7 completed | `reception_by_named_recipient` | builder code; 404 of 758 within 2 units of the recipient's next pass |
| 8 intercepted | `opponent_won_ball` | 1,142 of 1,188 end exactly at the opponent's possession-won event |
| 9 blocked | `opponent_blocked_or_cleared` | 91 of 96 end exactly at the opponent's event |
| 10 other | `engine_target_point` | builder copies the engine's target point |
| 11 out of play | `out_of_play` | every path ends outside the pitch |

The in-match reader (`fm_get_current_match_pass_events`) reads the event location only, so it gives where each pass was played from and no reception point. Physical units remain unlabelled; the pitch half-extents read 34.0 by 52.5 in this match, which is a 68 by 105 pitch if the unit is the metre. `origin_destination_state` on the rows is unchanged by this section.
