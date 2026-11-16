# Retained player distance

`distance_metres` exposes the stored float for one retained fixture/player row through the existing scoped capture and SQL query. It preserves zero, missing fields and the separate participation/minute states. Negative or nonfinite values reject the capture. The decoder checks the complete version60 player-child extent before reading the field.

## Native name, wire and units

IL2CPP metadata39 literal7435 is `DistanceRan`. ARM64 GameAssembly registration `ab5e50..ab5e94` binds it to key `0x72434e64`; wrapper `400e818` preserves that key. Native property dispatch `266c4c..266c58` selects `2670c0`, which calls `4ad1a2c` with argument1 zero. That getter reads player float `+0x68` and multiplies by float32 `0.001` at `52f6fb4`. Its other branch returns the raw float. Neither branch assigns an unavailable sentinel.

The native default wire reader `4ad2d7c..4ad2d9c` reads that same float through `43548cc`. In the checked version60 stream-bit1 child, it is segment29: byte140 with a u32 PERSON reference, byte144 with a wide reference. The FM26 byte139 lead differs and was not reused.

The installed `PlayerStatsExtendedFactory` row `run` sorts on `binding.DistanceRan` and selects UXML GUID `71c9d105dfada174aafe5e3fd1458c1c`. That GUID resolves to `PlayerMatchRunCell`, path ID `-841567218432356479`, in `ui-visualtreeassets_assets_gameworldvisualtreeassetpreload.bundle`. Its serialized text-binding arguments pass `binding.DistanceRan` to `distance (input in kilometres)`. This declares the getter's output unit; combined with its native multiplication by0.001, it establishes stored metres. The cell's `0.0 km` debug text corroborates the binding but does not establish units alone.

Source pins for the checked FM27 build:

| Source | SHA256 |
|---|---|
| game_plugin | `774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1` |
| GameAssembly.dylib | `d26f882851f26248bb56ca3575fc7759d74aebc21fb9722f44cab29b63c1e654` |
| Gameworld visual-tree bundle | `78bbf2d1f1080799971e0736dcef924a5fa95e2137968f7abf1b5448097206c2` |

Runtime native-byte guards check the property key/branch, scalar getter, scale constant and wire selection in the same read scope as retained-source selection. Static source receipts and reproducible asset extraction live in `evidence/running-statistics-20261108/` in the canonical research checkout.

## Exact retained control and limits

Fresh open-career reads on8November2026 found `Cesar Jules - Newcastle`, current13November2030, save_count428. Exact Lille2–Newcastle3 on6November2030 is retained result136941. Its raw-frame SHA256 is `7b657054e0392b030cc75131d97473b5978f310a000779f3a219f065908dbb3f`. Both complete player sections contain43 canonical rows:23 Lille and20 Newcastle. Newcastle has15 positive distances and5 zero distances whose separate native participation predicates prove unused substitutes; their minutes remain null. Karetsas stores13174.189453125m, Chema12508.89453125m and Costa12489.2685546875m.

These are retrospective full-fixture aggregates. They do not establish current playback distance, sprinting, high-intensity running, effort, energy expenditure or tactical effectiveness. Tracking path lengths and season compact-stat index23 are separate sources. No independent team-distance sum oracle is established. Any normalization must retain the existing native-minute precision limits and require a positive known denominator. This change adds no derived per90 field. Source proofs and frozen tests do not establish installed ordinary-Pi delivery.
