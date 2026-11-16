# Active playback-prefix heat maps

`active_heatmap.project(source,bound,actors,fixture,*,prefix_verification,team_native_id,person_native_id=None,method='sample_density',grid='compact')` performs no memory reads or game calls. It consumes the same private source packet used by current-match spatial means. The wrapper must finish its initial capture, independently reselect/recheck the fixed prefix and canonical actors/fixture, and verify the ending process/career epoch before calling this projector.

The internal verification receipt must carry `state=verified_fixed_prefix_under_monotonic_same_match_playback`, the same official match ID and fixed cursor, matching selected sample count, a monotonic verification cursor, and true `canonical_actor_ids_rechecked`/`same_match_ownership_rechecked`. These are caller receipts, never public tool arguments. For interpolated maps the caller also invokes `live_tracking_heatmaps.verify_native_heatmap(read,base)` during the native source check. Source fixture identity must equal the canonical participating teams/date/competition.

The source is clipped again at `start_tick+index*24 <= fixed cursor`. Future points, future entrants and future phase suffixes cannot change the projection. Unknown past actor slots remain explicit partial coverage rather than named zero values. Neither full-time scores, raw addresses, future engine aggregates nor unconsumed names are returned.

The public `heat_map` shape matches retained spatial maps: compact13×20 by default; native65×100 requires a player. Sample density returns integer `counts_by_length_then_width`; interpolated returns `mean_intensity_by_length_then_width` plus per-map quantile/smoothing metadata. The former counts observed position samples, including repeated/zero pairs. The latter reconstructs the native movement algorithm and can retain a final centreward exit transition; it is not a displayed UI pixel oracle. Neither establishes finding space, on-pitch duration, physical units or human left/right.

The existing no-argument current spatial request is unchanged by this pure module. The separate wrapper owner adds optional selectors after release110.

Frozen actual Lille capture at cursor4559 validates22 players/4158 selected samples. This pure-projector control supplies an expected bookend receipt in its test harness; it does not claim a new live bookend. Two fresh runtime attempts returned unavailable because there was no unique current viewable client; no historical substitute was used.
