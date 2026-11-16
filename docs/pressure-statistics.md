# Pressure attempts and statistical completion

Retained player rows expose `pressures_attempted`, `pressures_completed`, `pressure_completion_percentage_computed` and `pressure_completion_state`. They are individual stored counts; possession wins remain separate. A native statistical pressure completion does not prove a possession regain, an escaped opponent, a failed tactical press or an action location.

## Independent native proof

The supported individual property getter exposes PressuresCompleted from native `+ed`; it does not expose PressuresAttempted. The new attempted field uses a separate named writer chain:

1. QME_STAT_MANAGER constructor `4ad3bf8/4ad3ff4` binds literal `pressures_attempted` at `52db4f5` to its string member `+2e0`.
2. Name lookup `4956450..4956480` compares that exact member; `49568d0` returns native stat ID12.
3. Producer `49adb54..49adb64` requests ID12 and retains its result in w28; `49adc34` stores w28 into the individual statistics byte `+ec`.
4. The parallel `pressures_completion` member `+2e8` maps to ID13 and its result writes `+ed`, independently matching the existing named PressuresCompleted getter.
5. Serializer `4ad2dd4/4ad2dd8` writes the four-byte block beginning at native `+ec`. The checked u32-PERSON wire placement is160 for attempts and161 for completions; wide PERSON references add four.

`evidence/batches/native-pressure-statistics-176/named-writer-proof.json` records30 exact instruction controls, official metadata binding and the QME_STAT_MANAGER RTTI name. `verify_named_writer.py` reproduces those checks against the installed binaries without executing game functions.

The event statistics consumer independently increments native `+ec` for action kind28 and `+ed` for its completed result13. The CBE converter maps action kind28 to generic category0, discarding that distinction. Neither CBE touches nor incomplete passes can therefore become located failed-pressure events from this proof.

## Rate and availability

A row rate is `100 * completed / attempted`. Missing counters produce `unavailable_missing_pressure_counters`; zero attempts produce `undefined_zero_pressure_attempts`; completed greater than attempted produces `unavailable_completed_exceeds_attempted`. Each has a null rate. Genuine zero completions with positive attempts produce0%. Unsigned byte values remain0..255 counts; no inferred wrap correction is applied.

Aggregate rates use the ratio of sums after checking every selected row's availability and counter relationship. They never average row percentages or silently discard unknown rows. `fm_rank_live_match_players` supports `metric=pressures_completed, normalization=per_100_pressure_attempts`; total/per90 rankings also support the new attempted count. The existing450-minute default for normalized rankings remains, so an explicit single-fixture comparison must choose its minimum minutes.

The fields travel through `fm_get_match_data_columns`, live/scoped retained-player queries, SQLite exports and `player_match_analysis`. New exports preserve nulls and per-row states. Older registered originals remain unchanged: explicit new pressure-field requests return null with `unknown_not_in_registered_capture` availability. Their raw children are not silently redecoded. New physical columns containing absent counters remain null rather than zero.

## Genuine Lille control

The retained frame136941 is Lille–Newcastle on6November2030. All43 canonical player rows match the raw381,750-byte frame's child boundaries and hashes. Lille totals52 attempted and13 completed statistical pressures:25%. Newcastle totals49 and11:22.44897959%. These are sums of individual fields, without a separately serialized team pressure oracle.

Lille's Ernest Poku recorded3/4 in60 native minutes; Tiago Santos2/2 in60. Newcastle's Luiz Henrique recorded3/3 in60 and Shea Charles2/2 in90. Karetsas supplied the largest Newcastle attempted count,10, with one completion. These small denominators support measured workload/completion descriptions; they do not establish which tactical press was effective or how it was beaten.

The exact canonical rows and frame provenance are frozen in `tests/fixtures/lille_pressure_players.json.gz` and the batch's `lille-pressure-control.json`. The ordinary manager question should compare volume, minutes and statistical completion while preserving the distinction from possession regains.
