# Current-match shot-origin zones

`fm_get_current_match_shot_origins(session_id)` groups the checked playback shot prefix into thirteen native origin zones and four area groups. It calls the existing current-match report once, requests shot events, and omits tactical plans. It returns no cumulative client/simulation totals or provisional score.

## Coverage and novelty

Existing `fm_get_current_match(include_shot_events=True)` already exposes each attempt's native origin bin, official name and area group. An agent can group those rows. This tool adds a reusable aggregation with conserved integer counts, per-metric confidence, fallback handling and unknown-location coverage. It discovers no new native field.

The retained match dataset already exposes tackles, interceptions, clearances, aerial duels, possession wins/losses and pressures. Current spatial reports expose stored-sample means by possession and optional heat maps. Instantaneous team width/length still requires a verified simultaneous on-pitch population; a mean-position envelope cannot supply that claim. Shot-origin grouping therefore fills a bounded current-analysis gap without treating tactical instructions or post-exit tracking tails as current team shape.

## Source contract

The tool consumes only linked statistical attempts ending strictly before the checked playback cursor. Native event identity, ordered side and both integer counters retain their existing reconciliation guards. Zone grouping uses `retained_shot_location` and its pinned native renderer predicates `4895ac8..48963dc`, renderer order `1a366c` and official property table `52e0c5c`. Source geometry comes from CBE half-extents; no metres, shot angle or human left/right claim is added.

Bins0–5 are inside the area; bins6–11 are outside. Bin12 remains `outside_area_or_native_fallback`: exact boundary gaps can reach that native fallback, so it cannot establish a long-range attempt. Missing classification stays in `unclassified`, preserving the full selected denominator. Zone counts under partial classification describe assigned bins; unknown shots may belong to any zone.

OwnGoal49 markers stay outside every statistical shot-origin group. Count-zero requires a reconciled source and an empty selected group. Unreconciled counts remain null. Group xG stays null when the side's strict one-ULP xG check fails, including empty groups. Verified native first/second-half intervals alone receive period groups; unassigned event IDs remain explicit.

## Actual controls

The verified moving Lille–Newcastle source at native cursor15064 contains eight home attempts and seven away attempts. Lille has six inside-area and two outside-area attempts. Newcastle has five inside-area and two outside-area attempts, including four native six-yard-box origins. The raw CBE event/vector fixture is `tests/fixtures/lille_active_shot_origin_source.json.gz`. It was reconstructed only from bytes consumed and rechecked in `live-match-report-consistency-170/verified-candidate-readset.json`; the existing typed source guards replay against those bytes. It introduces no later live read or synthetic event.

A fresh call through the registered candidate MCP tool, using the configured native helper and a new live Bridge session, returned `available` for Newcastle–Nottingham Forest on11November2030 at cursor12906. Newcastle had ten attempts, eight inside and two outside; Forest had three attempts, two inside and one outside. The verified first-half groups contained8/3 attempts; the second-half prefix contained2/0. The call took1,122ms. Evidence: `evidence/batches/current-shot-origin-zones-174/fresh-tool-call.json`.

That candidate call preceded a metadata-only provenance-field addition. Its grouping logic is unchanged and covered by tests. A final runtime recheck found no running game and made no positive-current claim. The source is staged on its branch; installation and configured connector discovery belong to the release owner.

The focused tests cover conservation, source-zero versus null, strict xG independence, unknown locations, native fallback, own-goal exclusion, wrong side, duplicate event IDs, equal/future end times, mismatched native names/groups, tool registration and one-capture behavior. The parent report keeps its non-atomic snapshot policy and monotonic playback anchor semantics.
