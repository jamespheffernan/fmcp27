# Approved captured shot sample

`fm_list_captured_match_sources` includes the explicit source
`premier_league_2030_10_26_shots`. It reads the delivered Premier League matchday
sample from 26 October 2030, captured from the 2 November career state. Its registered
SHA256 is `ae9929753c2094a875e93a6bb1e77bfa535323b1dc264e6b0c112b349e800792`.
The registration checks that exact original, the existing career identity,
six fixtures on the selected date/competition, and the approved table counts.
It does not scan Reference or select newly found exports.

The sample contains 42 statistical shots, one separate own-goal marker and 12 side
coverage rows. Four sides are available; eight are unretained and retain NULL
counts. The three additional query tables are `shots`, `shot_map_coverage` and
`own_goal_markers`. Sources without an optional table continue to report it as
unavailable rather than returning an invented zero.

First obtain the catalog's capture/career pins. Then query fixtures to establish
home/away identities and query `shots` with the same pins/selectors. A team filter
selects whole fixtures and returns both sides. Shot results include the coverage
for all matching fixture sides, so an empty attempt list cannot silently stand
for zero. Shot defaults preserve `raw_json`, including the checked actor and its
identity state. Own-goal marker beneficiary and event sides remain separate.
Optional penalty columns appear only if they exist in that registered export.

For example, “In the exported Oct26 shot sample, who took Southampton's best
chance v Forest?” selects the Southampton–Nottingham Forest fixture and its
home side. Among 12 reconciled Southampton attempts, Christian Kofane has the
highest native per-attempt xG, 0.6867012977600098. Raw clock units, pitch
orientation and outcome remain outside this claim.

Every query uses a read-only SQLite transaction with hash/career pins and
unchanged-file checks. No live attachment, game fallback, arbitrary SQL or
caller-selected path is involved. Pagination retains the same source hash and
selectors; changed originals require a new approved registration.
