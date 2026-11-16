# Resolve a native player statistic by its official property name

B142 creator-statistics work established a reusable static lookup from the managed front end to a stored native player field. This avoids guessing a field name from its distribution, nearby enum value, or season aggregate. No game functions or UI input are needed.

The frozen worked example lives in `evidence/batches/live-match-review-142/player-expected/frontend/` in the research checkout. `verified.json` pins the metadata, GameAssembly and game-plugin hashes, actual instruction bytes, property IDs, wire offsets and source checks.

1. Read the installed `Resources/Data/il2cpp_data/Metadata/global-metadata.dat` header. This build uses IL2CPP metadata39. Its string-literal table is an indexed concatenated UTF8 pool, not a sequence of zero-terminated strings. The table has32127 offsets for32126 literals; adjacent offsets delimit each literal. Searching only zero-terminated plugin strings missed `ExpectedAssists`, `KeyPasses`, `OpenPlayKeyPasses` and `ChancesCreated`.
2. Locate the literal's encoded runtime usage in the matching ARM64 GameAssembly slice. For this build the encoded u64 value is `(5 << 29) | (literal_index << 1) | 1`. Parse the Mach-O fat header and segment mapping rather than treating a whole-file byte offset as an RVA. Resolve ADRP+ADD references; check register writes between instructions to exclude false cross-instruction matches.
3. Follow the usage into its property registration. The generated registration method at `0xa296bc` pairs a numeric property key with the actual label literal. Read the complete argument flow through the registration call. In this build key wrapper `0x400e818` is a single `ret`, preserving the numeric input. Mere proximity to a string initializer is insufficient.
4. Find the exact key in the matching native game plugin. The native UI player exporter constructs a typed value from the actual player object, then inserts that value under the key. Verify the load, variant constructor and keyed insertion together. The float constructor `0x4403f88` stores the input s0 unchanged; keyed insertion `0x43f72e4` stores the key and value variant. Native property getter `0x266bb4..0x266bc8` separately recognizes the ExpectedAssists key and reads player+24.
5. Trace that same native object field through the supported wire reader/writer. Account for narrow and wide PERSON references, native field block reordering and field widths. A native object offset is not a wire offset. Record raw units; do not carry integer-display100x rounding into a directly stored float.
6. Corroborate on retained sources without using those values to invent the name. Check finite/nonnegative floats, zero preservation, reference widths and actual unavailable-source behavior. Test team conservation only where the native semantics justify it. Keep failed aggregate assumptions in the receipt.

## Proved individual creator fields

| API field | Official label | Property key | Native field | u32 PERSON wire byte | Encoding |
|---|---|---|---|---:|---|
| expected_assists | ExpectedAssists | 0x49675367 | +0x24 | 191 | Unscaled float32 |
| key_passes | KeyPasses | 0x6949686f | +0xbc | 88 | Unsigned byte |
| open_play_key_passes | OpenPlayKeyPasses | 0x47767a57 | +0xbd | 176 | Unsigned byte |
| chances_created | ChancesCreated | 0x30485a6f | +0xa0 | 57 | Unsigned byte |

Add4 to wire offsets for wide PERSON references. `ExpectedAssists` is FM's credited aggregate, not proof of a causal player skill. The separately named OpenPlayKeyPasses field supports the open-play share of key-pass counts; it does not establish an open-play xA split.

In102 distinct retained frames (including91 league frames), all4135 player rows had finite nonnegative xA; open-play key passes never exceeded key passes. Summed player xA did not exceed team xG on all204 sides, including182 league sides. This is a bound, not an xA team-conservation oracle. The individual ChancesCreated sum equalled the team property with the same label on only31/204 sides; those entity-specific properties must not be treated as interchangeable aggregates.
