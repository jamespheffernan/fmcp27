# Paired in-possession width

`fm_compare_retained_player_width(session_id,fixture_ref,person_a_native_id,person_b_native_id)` compares two distinct canonical team players in one exact retained result. It answers who supplied recorded width while both have samples, rather than comparing unmatched whole-match means.

The source reuses canonical retained fixture/team/actor validation and full-fixture individual completed-pass counter closure. It checks the build-pinned lateral-axis consumers and retained tracking source, then recaptures the complete tracking/event/pitch source and verifies the load epoch before returning. The game remains read-only. It has no paths or caller timing boundaries.

Only exactly equal tracking ticks coincide; unaligned starts are not rounded, interpolated or matched to the nearest point. The actual possession byte at tick//24 must equal that same fixture side. Missing bytes beyond the stream are uncovered, not clamped. Unclassified255, other bytes and opponent possession are counted separately. Width means the absolute lateral coordinate of each point, not the absolute coordinate of a mean that can cancel when a player changes flank. Comparison ties use the exact stored integer magnitude.

The all-sample denominator preserves known zero pairs. Separate nonzero and in-bounds nonzero sensitivity views expose the effect of removing these samples; removal does not prove the points invalid or produce a corrected official position. Per-player full-stream trailing zero counts, first tail ticks, unmatched counts, coincident sample range and phase coverage remain explicit. Co-recorded samples do not establish shared on-pitch minutes or continuous play. No overlapping run, marking, space-created or tactical-cause claim follows from width.

With proved pitch bounds, the bounded sensitivity view also counts points where both players occupy the same analytical outer width third: abs(axis0)>=half_width/3 and their lateral signs agree. This is a reproducible analytical threshold, not an official tactical role or a human left/right label. Both coordinate units and forward sign remain unproved.

## Genuine Lille control

The immutable source is latest-match-export-167 retained-source-observed.json and capture-observed.json: Lille–Newcastle6November2030, retained key136941. All43 canonical player rows and every full-fixture completed-pass counter close against the same event source. The fixture freezes source hashes and source bytes in tests/fixtures/lille_paired_width.json.gz; the reproducible control script and report are evidence/batches/retained-paired-width-186/verify_lille.py and lille-comparison.json.

Both Newcastle pairs have946 coincident ticks and459 classified in-possession ticks. Diouf–Robinson has188 in-possession ticks with either zero pair, including176 with both zero. The bounded nonzero view contains264 points: Diouf wider169 (64.02%), Robinson95 (35.98%), no ties; mean absolute lateral widths19.883 and18.703 native units. Both occupy the same analytical outer third190/264 (71.97%).

Costa–Henrique also has459 possession ticks, but176 have Henrique's zero tail. All-sample Costa wider342/459 (74.51%) therefore exaggerates the paired difference. The bounded nonzero view has269 points: Costa152 (56.51%), Henrique113 (42.01%), four ties (1.49%); mean widths20.406 and20.032 native units. Both occupy the same analytical outer third217/269 (80.67%).

A supported manager answer is that Diouf supplied the more consistently outer recorded position of his pair, while Costa's advantage over Henrique was smaller once zero tails are exposed. The same-side outer-third counts show simultaneous sampled width under this threshold; they cannot establish redundant runs, whether a player was marked, or which tactical instruction should change.

Ordinary prompt: “In Lille, when Diouf and Robinson were both recorded in possession, who supplied more width? Compare Costa and Henrique on the same basis and show the zero-tail caveat.” Resolve these names to canonical IDs from the exact selected fixture; do not substitute current squad slots.
