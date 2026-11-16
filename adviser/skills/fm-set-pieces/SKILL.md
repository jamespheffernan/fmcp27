---
name: fm-set-pieces
description: Review penalty-taker order and propose bounded dead-ball changes. Use for penalties, corner or free-kick plans, attacking or defending set pieces and choosing takers.
---

# Set-piece decisions

## Define the decision and evidence

Read `fm-tools` and `fm-live-investigation` through `fm_read_skill`. Bind the career, date and selected coach. Distinguish a stored penalty-order audit, a proposed routine and a diagnosis of a named match. A current setting does not reconstruct an earlier routine. Preserve dated user observations as such; resolve exact fixtures and supported events when the question concerns results. Complete when the set-piece type, team and intended decision are explicit.

## Review the supported penalty order

Call `fm_get_managed_penalty_takers`. Preserve the stored priority order, null sentinels, duplicates, unresolved identities and current-club/loan links. An empty checked list differs from an unavailable source. Pending working-edit overrides remain unknown; the first stored entry is not a verified final match taker or last scorer.

Read `fm_get_managed_team_sheet` independently when today's selection matters. Join canonical PERSON identities through the shared live protocol, preserving unmatched rows. Report the stored order and the editable selection separately. Neither list establishes who is currently on the pitch or fully eligible for the fixture.

For a recommendation, compare serious options with supported `fm_get_player` ratings: `penalty_taking`, with `finishing` and `composure` as additional considerations. Keep unclassified profiles and ties visible. Use current-club/loan state and supported injury/readiness checks before proposing immediate use. Compare retaining the current priority with one named alternative; explain the deciding strength and trade-off rather than inventing a success formula or an aggregate score. A small penalty sample does not establish a stable conversion ability.

The [Sports Interactive FM2024 tactics manual](https://community.sports-interactive.com/sigames-manual/football-manager-2024/tactics-r4960/) identifies those ratings as penalty-selection considerations. This is an older-version heuristic, checked 9 November 2026, not proof of FM27 weighting, current UI behaviour or a guaranteed outcome. Career observations and current tool contracts remain authoritative for the actual stored list and available fields.

Complete when every stored slot is accounted for and the answer gives either a justified retained order or a conditional proposed change, its alternative and a review point. The tools do not change takers or choose shootout participants.

## Build a conditional wider routine

Corners and free-kick taker orders and complete routines are not established by the penalty-order source. Use supported profile ratings to compare the requested delivery task; do not label the comparison as a decoded routine, assignment or current taker order. For a user-described routine, identify delivery, target/decoy movement, second-ball coverage and protection after a turnover. Load `fm-tactical-analysis` for how these jobs connect to the wider team. Name one small proposed change and the defensive or attacking opportunity it costs.

For match evidence, inspect the actual field catalogue and exact retained source. A supported penalty flag identifies penalties. `non_penalty_unspecified` does not distinguish open play, corners or free kicks. A headed shot, total corner count or aerial duel alone cannot prove a routine's success or failure. Keep actor, event, coordinate and period limits attached; no guessed locations or inferred half boundaries.

If the decisive routine or event context is unavailable, give a conditional football test from the user's observations and name the missing fact. Do not invent a selectable FM27 instruction or claim that a tactic file encodes set-piece routines. Load `fm-create-tactic` only for the distinct supported file request and preserve its actual schema limits.

Finish with the proposed or retained plan, the observed baseline, mechanism and cost, and the next supported observation that would preserve or reverse it. Suggested setup, observed result and causal effect remain separate. Full routines, effective assignments, game application and engine outcomes remain required source/evaluation work.
