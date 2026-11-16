# Live retained pass networks

`fm_report_live_pass_network` reports repeated directed player pairs for1–16 explicitly selected live historical fixture references and one canonical native team ID. Select the intended last two fixtures through retained-match discovery; the report captures those fixtures once rather than scanning league-wide player records. `minimum_matches` defaults to2; use1 for a single fixture.

The default ranking is `counter_reconciled_completed_passes`. `official_map_count` is a separate, explicit alternative. Each pair includes both counts and its per-fixture contributions. Missing retained sources remain unknown; they cannot create zero-valued repeat evidence. The result reports selected fixtures, source states, canonical player IDs, captured save and omitted cutoff ties.

## Source contract

Official managed HomePassMap/AwayPassMap property keys4c744b74/55497755 reach native29f46c,1a4ec8 and1a5368. The native renderer selects category7, independently registered as CBE_END_PASS_COMPLETED at489b188 with literal52da373. It reads side byte28 and source/related player slots27/29. Native4893cec accumulates directed pair keys as source_slot×26+related_slot. The renderer builds a player network and average positions; it is not a complete per-pass origin/destination route product.

The reader reuses the shared retained-CBE owner/coach, fixture/calendar membership and native-key checks. One epoch-stamped `capture_live` packet supplies the canonical historical player slots and official individual counters. Eight additional exact native spans guard the pass-map consumers and named event category. Addresses and raw pointers remain private.

The official map includes category7 records carrying an additional mask8 flag. Its action meaning is unknown. The mask8-excluded subset is published as completed passes only when every captured individual's official completed-pass counter agrees exactly. Matching only a team sum is insufficient. Raw official-map counts remain separate; no open-play, throw-in, pressure or phase label is assigned to the flag.

Shot count/SOT/xG oracle results from the shared reader are retained independently under `fixture_shot_oracle`. A failed shot xG arithmetic control does not become a failed or successful pass control. Pass availability requires its own individual-counter and canonical-identity reconciliation.

## Verified live control

The active2November2030 save supplied Southampton–Forest135904 on26October (Premier League) and Burnley–Southampton136157 on29October (Carabao Cup). Both sides of both fixtures supplied80 exact individual completed-pass counter checks:

| Fixture | Side | Official map records | Counter-reconciled completed passes |
|---|---:|---:|---:|
|Forest135904|Southampton|531|522|
|Forest135904|Forest|569|565|
|Burnley136157|Burnley|520|512|
|Burnley136157|Southampton|559|548|

Southampton's repeated counter-reconciled combinations include Assignon→Fellows38 (15+23), Quarshie→Harwood-Bellis35 (15+20), and Prass→Adli34 (24+10). The last pair has37 official-map records, so conflating the two measures changes the result.

Burnley's Southampton shot side has a preserved two-ULP shot-xG sum discrepancy under the shared reader's unchanged one-ULP threshold. Every pass counter still reconciles. This is an explicit independent-domain control, not a widened shot tolerance.

## Limits

No per-pair attempted-pass stream, completion percentage, complete trajectory, pitch-third, pressure cause, phase, assist relation or tactical role is established. Full-match passing combinations do not prove where Southampton played out, why a pass failed, or whether pressing a player will work. Multiple fixture-reference aliases for one native match are rejected rather than counted as repeated use. Unresolved identities cannot become named pairs.

`capture_retained_pass_networks` is the reusable batch API for discovery and future additive exports. It accepts the same private epoch-stamped frame packet as the shared shot reader, avoiding duplicate capture. `decode_pass_network` and `summarize_pass_network` are pure functions; dry fixtures contain the actual two-match control.
