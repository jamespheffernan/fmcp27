# Retained individual progressive passes

`progressive_passes` is FM's official `ProgressivePasses` property, an unsigned
byte count in a boundary-checked parent-version 60 retained player record.
Zero is a recorded count; an absent source row/frame remains unavailable/NULL.

The indexed IL2CPP 39 literal 15692 resolves to `ProgressivePasses`. Managed
registration RVA `0xab76b4` passes property key `0x6161476c` to the property
registry. The individual exporter loads native `player+0xf1` at `0x205288`
and binds that value to this exact key at `0x20529c`. The generic individual
getter compares the same key at `0x266d70`, loads `+0xf1` at `0x266d80`,
constructs the integer variant at `0x2670dc`, copies it to the caller's output
at `0x267130` and returns success at `0x26713c`.

Native reader `0x4ad2910` serializes the six-byte `+0xf0` block after the
version 60 nine-byte `+0xbe` block (`0x4ad2e18..0x4ad2e40`). The `+0xf1`
byte is wire 186 for a four-byte PERSON index, wire 190 for the legacy eight-byte
PERSON encoding. The helper preserves the full unsigned 0..255 domain.
`native-player-progression-proof.json` freezes source hashes and 21 exact
instruction guards. The reproducible research scripts and fresh full live
payloads are in the canonical project's ignored evidence directory:
`evidence/batches/live-match-review-142/player-progression/`.

## What this supports

Both explicit and scoped live match queries can select the typed integer;
SQLite `retained_players` and `player_match_analysis` retain it. Column
provenance exposes the official key and limits. It is suitable for comparing
FM-defined progressive-pass totals and explicit per 90 arithmetic over known
played minutes.

It does **not** establish FM's exact distance/angle classifier, final-third
entries, progressive carries, action origin/destination, the role played at
that time, opportunities or a tactical cause. No independent serialized team
oracle is claimed. `OpenPlayFinalThirdPasses` has a separate official key and
native individual field, but its label alone cannot distinguish passes into
versus within the final third. Do not substitute that field for entries.
Third-completion properties were found on a separate four-argument container
exporter; no retained-player linkage is proved.

## Fresh live control and ordinary question expectation

On the open Newcastle career dated 2 November 2030, nine resident Premier League
matches through 28 October yielded 360 player rows, all with tag 2 PERSON references.
All 360 independently exposed raw six-byte segments agree with the new byte
projection (observed count range 0..14). Both PERSON widths are fixture-tested;
legacy width was not observed in this live sample.

For current CM/DM suitability >=16 and at least 270 known played minutes:

| Player | Progressive passes | Minutes | Per90 |
|---|---:|---:|---:|
| Adam Wharton |56|671|7.5112|
| Chema Andrés |26|285|8.2105|
| João Neves |32|635|4.5354|
| Jacob Ramsey |25|495|4.5455|
| Shea Charles |24|720|3.0000|

For “who progresses possession, Wharton or Chema?”, distinguish Wharton's
sustained volume from Chema's higher rate over a smaller sample. Wharton also
recorded 24 key passes (16 open play) and 1.6743 xA, compared with Chema's 2 key passes
and 0.2423 xA. Those chance-creation measures are separate evidence, not a count
of final-third entries. Fetch current club/loan/position/readiness again before
an ordinary recommendation. The historical aggregates cover every played role.
Finneran/Santos have no source rows in this scope; unknown duration rows for
Miley/Fabbian are not asserted to be zero-minute appearances.

This source change is prepared for a later release; installation and an
ordinary-prompt acceptance run are separate from these source/control tests.
