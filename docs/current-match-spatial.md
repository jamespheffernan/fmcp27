# Current match spatial prefix

`fm_get_current_match_spatial(session_id)` anchors one exact current fixture and
matching playback cursor. It reads only past position/phase samples, then freshly
reselects the same prefix while permitting monotonic advancement of that same
match. It verifies unchanged past coordinates, effective phase/orientation,
canonical original-slot PERSON identities, fixture, owner and career/process
epoch. Reallocation can move backing buffers; the old buffer is not trusted.
Backward seeks, relinks, changed prefixes and an engine behind the cutoff reject
the result. No global reader/native helper checks are weakened.

Rows group canonical names by exact participating team and return official
stored-sample means for all/in-possession/out-of-possession samples, sample
start/step/count and zero-pair coverage. Unresolved selected player slots stay
explicit. Future entrants and samples are excluded. Null is not zero. No
retained-result or last-save substitute is used when the source is unavailable.

Four pinned official renderer/property spans now establish axis0 as lateral
pitch width and axis1 as longitudinal pitch length. The derived
`lateral_displacement_of_mean_native` is abs(mean lateral coordinate), not mean
absolute displacement: switching flanks can cancel. This supports comparisons
of average width. Forward sign, human left/right and physical units remain
unproved. The source does not establish finding space or receiving opportunity.

Zero pairs and post-exit tails remain in FM's official sample denominator;
sample count does not establish on-pitch time. Instantaneous shape, nearest
opponent, space created and heatmaps remain null. The human displayed minute is
unknown. No score, ended fixture statistics, simulation totals, private addresses
or uncensored actor list is returned.

Live moving controls at Lille–Newcastle on Nov6 verified an anchored13700 prefix
while playback advanced to13703:22named players/12298samples in1.75seconds.
A second fresh query verified15205 with26named tracked players/13900samples in
1.71seconds. End actor identity and fixture/epoch closure passed. These are
same-session optimistic immutable-prefix checks, not an atomic or stationary
whole-memory snapshot. World read sets remain strict; volatile source headers,
unused counters and presentation floats are not misclassified as immutable data.

Dependencies:169b3bd/7730d94 tracking+live control,399af8e/717624c canonical
identity-only actors,4e817ce/b57cd8b prefix revalidation. The axis receipt is
`active-match-person-162/axis-proof/verified.json`. Original frozen4559 live
control remains separate. The first moving development receipt used the earlier
metadata field name `same_readset_spatial_prefix_verified`; the frozen interface
accurately calls the new verification `same_session_spatial_prefix_verified` and
reports its explicit verification scope.

Receipts: `evidence/batches/current-spatial-public-169/`
`moving-live-public.json` and `moving-live-public-second.json`.

## Optional verified-prefix heat map

The default call is unchanged and retains `heatmaps:null`. To opt in, supply
`heatmap_team_native_id` from the participating fixture. Optionally add
`heatmap_person_native_id`. `heatmap_method` is `sample_density` (default) or
`interpolated`; `heatmap_grid` is `compact` (default13x20) or `native` (65x100,
requires one player). Extra native interpolation guards run during the initial
capture only when that algorithm is requested.

The single selected `heatmaps` packet is computed from the **same raw prefix**
after completed actor/fixture/prefix and career/process bookends. There is no
second capture. Sample density counts position samples, not touches; interpolation
reconstructs the native movement algorithm, not an observed UI image. Zero tails,
unresolved actors, small or absent samples and grid normalization remain explicit.
Missing current source returns unavailable heat data with no historical fallback.

The source projector is90e66cb. Frozen actual Lille4559 controls verify the
22-player/4158-sample prefix and requested team grid's2079samples. Hook tests
verify default parity, one capture, end-epoch-before-projection, wrong selectors,
missing source and optional native guards. A new live probe after Lille's client
closed returned checked_empty_viewable_client_inventory and null heat data.
There is **no claimed online positive heatmap end-to-end observation** in this cut.
