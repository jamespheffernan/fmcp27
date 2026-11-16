---
name: fm-tactical-analysis
description: Diagnose a tactical problem, assess a setup or recommend match adjustments using squad, phase-role and match evidence. Use for tactical analysis, opposition plans and post-match lessons.
---

# Evidence-based tactical analysis

## Establish the decision

Identify the user's goal, match state and preferred style from the conversation. Ask only for missing information that changes the recommendation. For an immediate decision at half time or in play, follow "During a match" below; the `fm-live-investigation` halftime workflow covers observations the user supplies instead of a live read.

For a broader diagnosis, bind the managed club, game date and requested fixture or date range using `fm-tools`. Keep the running career, saved archive and recorded match evidence separately dated. A replay can share teams, date and fixture ID; match the score and capture/source identity before using its events.

Give FM27 UI advice in the user's available role and player-instruction vocabulary. A role in Football Manager 27 has no duty. Each player has one role in possession and one role out of possession, and that is all the game shows. Never write a role with Defend, Support or Attack after it. To change how a player moves, describe the intended movement and choose a verified role or player-instruction adjustment. Native `native_available` and raw PI states0–3 establish neither visible UI choices nor effective match instructions. Preserve a conflicting user observation as unresolved evidence.

When advice promises exact file-compatible roles, load `fm-create-tactic` and check the source-bound `fm_tactic_file` native catalog before finalizing that table. Preview the complete intended layouts and roles when moving beyond the source layout. A remembered role name or global catalog entry does not establish that the role is legal in the intended phase/position. In Code Mode, retain the source path/hash and requested slots’ legal roles using the compact projection in `fm-create-tactic` before storing catalog state. Conceptual football advice does not require manufacturing a file.

## During a match

When the user is playing a match now, the match's own state replaces the stored tactic and the pre-match figures. Read it before advising; each item below is something the save holds, so do not list it as unknown.

1. **The tactic in use:** `fm_get_ui_screen(screen: "tactics")`, `fields.tactic.in_match`: name, mentality, named team instructions, both phases' roles, period and score. Recommend a change only against this. Proposing the mentality or an instruction the match already has is an error.
2. **Score, statistics and ratings:** `fm_get_match(team)`. Its team statistics are the match screen's; while the match runs they can include play just beyond the picture.
3. **Substitutions made:** `fm_get_current_match(include_player_changes: true)` (deferred: `tool_search`). `player_changes.changes` rows of kind `SUBSTITUTION` name who came on and off, with the match tick. Count them for substitutions used; the number allowed is a competition rule you have not read unless you read it.
4. **Condition now:** `fm_get_current_match_player_physical` (deferred). It answers while the match is paused and withholds itself while play runs; when it withholds, say that condition needs the match paused, and do not present pre-match condition as current.
5. **Who is on the pitch:** the starting eleven adjusted by the substitution rows. Minutes in `fm_get_match` confirm it.
6. **One player's involvement, supply and position** (a striker who looks isolated, a midfielder the play goes around): three deferred reads of the match so far. A claim that a player is isolated, bypassed or out of position rests on these reads, not on his pass and shot counts.
   - **Links:** `fm_get_current_match_pass_network`. `sides[].pairs` counts completed passes from one named player to another. Total his rows as passer and as recipient, place both totals among his teammates', and name who finds him and who does not. The pairs carry his `person_native_id` and the side carries `team.native_id` for the two reads below.
   - **Where:** `fm_get_current_match_pass_events` with `team_native_id` and either `from_person_native_id` (add `pass_outcome: "all"` to include his failed passes) or `to_person_native_id`; follow `next_cursor` to the end. Each pass has the game's pass-map point with its pitch third and central or outer channel, measured towards the goal his team attacks. The point is where the pass was played from: his own passes locate him on the ball, passes to him locate where his supply starts. In a match the reader has no reception points; the finished match has them (below).
   - **Position:** `fm_get_current_match_spatial`. Each player's mean position overall, in possession and out of possession; `native_axis_1` runs the length of the pitch, and the goalkeeper's row marks the team's own end. Compare his in-possession mean with the teammates meant to play near him. `heatmap_team_native_id` with `heatmap_person_native_id` adds his heat map.

   A side or player whose `state` is not `available` was not named by the reader: report it as not read, never as zero. "Build the evidence" below says what links, event points and position means cannot establish.

   After the final whistle these three reads answer `unavailable` and the finished match holds the same evidence. Take its `fixture_ref` from `fm_list_retained_match_data` (it expires within minutes; list again when a read says so). `fm_get_retained_match_spatial` with `fixture_ref`, `team_native_id` and `person_native_id` gives average positions by possession, his heat map and `passing_outlets`: every receiver with his suppliers. `fm_get_retained_pass_events` pages every located pass with its minute. On a completed pass `field_position.sampled_path_endpoint` is where the recipient took the ball, with its own third and channel: filter the rows by `recipient_name` and count those thirds and channels to say where he received it.

Retry a live-match read once when it answers "Game state changed during read". If a read stays unavailable, name that one item as not read.

Keep in-play advice to changes the user can make in under a minute: a substitution, a mentality step, one or two instructions or roles. Say what to watch for and when to revert.

## Build the evidence

1. Read the prepared tactics with `fm_get_ui_screen(screen: "tactics")`: `fields.tactic.prepared.slots` gives each stored slot's name, mentality, named team instructions and both phases' positions and roles. A stored slot is not proof of what a match is using; `fields.tactic.in_match` is. For the named players in each slot of the tactic being edited read both phases of `fm_get_managed_tactical_assignments` (deferred: `tool_search`). Preserve per-phase positions, stored base roles and unresolved slots. Request personal overrides when assessing individual instructions. Current editable assignments do not prove how the team played in an earlier match.
2. Read the relevant players' attributes and position familiarity. For immediate personnel changes, refresh current club/loan state, injury status and readiness for serious candidates. Familiarity and an injury flag alone do not establish eligibility. Keep each simultaneous change assigned to a different available player.
3. Query the smallest relevant match sample. Discover supported columns, then request fixture, team and retained-player rows together where possible. Follow the investigation guide's pagination and identity joins. Record usable matches, missing rows, dates, opponents and minutes before calculating rates.
4. Use shots and xG for chance volume/quality when supported; xA and key passes for creation; completion counts with attempts for passing or aerial comparisons. Label each metric by what it measures: aerial duels are not defended crosses, and key-pass share is not xA share. Event maps need verified coordinate orientation and coverage before describing left/right, territory or location.
5. For before/after or first-/second-half comparisons, require supported period boundaries and a shared clock domain. If they are unavailable, keep the halves unknown and use the whole-match sample. Separate the timing of an actual tactical change from a guessed explanation of the result. Keep raw native clocks in their returned units. Report a displayed match minute only when a verified conversion is available.

6. For one player's performance in the match loaded in the game, read his rating components (`match_rating_component`, worked statement 1 in `fm-db`): the base rating, then each term with its count and the points it added or took away (time in position, passes, tackles, key passes, goals conceded while on the pitch, mistakes). The biggest terms say what the rating rewarded or punished; compare two players in the same role by the same terms. Components exist only while the match is loaded; for an archived match use his `match_player_stats` line.
7. For the flow of the loaded match, read `match_momentum` (worked statement 2): one value per five minutes, positive for the home side. Tie a swing to an event (a goal, a substitution, a red card from `fm_get_match`) only when the minutes match, and say it is a reading of the curve.

For a retained-match width comparison, use `fm_get_retained_match_spatial` and its `lateral_width` rows. The derived `mean_absolute_lateral_native` takes absolute lateral coordinates before averaging, so switching flanks does not cancel. Preserve each player's in/out/all sample counts, missing-stream states, unknown possession bytes and zero-tail coverage. Stored zero tails remain included; sample counts are not on-pitch minutes. Players' own sample populations can differ, so describe the result as observed tracking width rather than a synchronous comparison or a fair minutes-adjusted ranking. Native units, metres, human left/right, receiving space and tactical cause are distinct; physical units and human left/right remain unproved. Keep missing rows visible and avoid replacing mean absolute width with the absolute signed average position.

For average positions, inspect each row's sample denominator, possession scope, cursor and zero-tail coverage. A mean of native tracking samples is neither a trajectory nor a simultaneous team shape, and the samples do not establish time on the pitch. A substitute's deeper mean does not prove that he stayed deep or never reached the box. Compare matching populations where available and keep the unmatched scope explicit.

For a completed match with a retained side withheld only by xG reconciliation, follow `fm-live-investigation`’s qualified retained-shot fallback. Its separately qualified counts, actors and recorded outcomes can support a whole-match description while verified attempt xG stays unavailable. Keep official aggregate xG separate from observed native attempt values, and own-goal markers separate from statistical shots.

Use shots and key-pass recipients to describe attacking output. Zero shots do not count box arrivals or prove that a player never entered the area. Completed-pass links establish recorded sender/receiver connections; without located events they do not establish forward/backward direction or where the pair combined. A pass-map point is where the pass was played from, so final-third/channel counts and pass maps count passes played from a zone. Reception locations come only from a finished match's `sampled_path_endpoint`. Neither establishes runs, shot supply or the effectiveness of circulation.

## Turn observations into a tactical test

For each material problem, connect:

- **Observation:** the returned record or explicitly user-supplied pattern, with sample and limits.
- **Hypothesis:** the football mechanism that could explain it, and any plausible alternative such as opponent strength, game state or a small sample.
- **Adjustment:** a specific phase, player/unit and role or instruction change. Use verified game labels where available; otherwise describe the football action without inventing a UI label.
- **Trade-off:** which space, passing option, defensive cover or player demand the adjustment sacrifices.
- **Checkpoint:** what should improve, what would contradict the hypothesis and when to reassess or revert.

Consider in-possession spacing and progression, out-of-possession pressure and cover, and the transition between them. For example, an aggressive wide player may improve width while exposing the outside centre-back after a turnover; verify that the observed pattern supports this explanation rather than prescribing an automatic formation change.

Before presenting a tactical change, compare it with the supported baseline and state what would actually differ. For a past match, inspect advertised `recorded_tactical_snapshots` through `fm_list_observed_match_runs` and `fm_query_observed_match_run` when available. Keep the source/capture pins, fixture identity, observation window and replay/incarnation limits; one resident-settings observation is neither kickoff nor a complete effective-role history. Current editable assignments cannot replace that missing history. If the baseline is unproved, make the comparison conditional. A role already selected expresses an intention; repeating it as a new adjustment does not explain why the intention failed.

When asked how to get more attackers into the box, lead with one proposed in-possession pattern. Name who supplies width and the ball, who occupies the last line, who makes the second or far-side run, who arrives late centrally, and who retains cover while the attack develops. Explain how the runs complement one another; count proposed assignments separately from observed arrivals. If the striker drops to link, identify the runner replacing his last-line presence. If the No.10 becomes a supporting creator, explain which other player supplies the lost box run. Out-of-possession roles alone do not establish the cover retained while attacking or the immediate turnover protection.

Check delivery timing as well as the number of nominal attacking roles. Early crossing, directness and tempo can be part of a hypothesis that delivery precedes supporting runs; recorded selections alone do not prove that mechanism. Compare waiting for an existing runner with assigning an earlier runner, explain which would change the supported baseline, and name the lost opportunity or transition cost. More attacking roles are not the automatic remedy for low box output.

Choose the players from the relevant attributes, familiarity and verified phase-role options. High vision does not rule out attacking movement. If the historical setup or simultaneous movement is unknown, present the pattern as a counterfactual test rather than a reconstruction of what happened. Give the defensive cost and a checkpoint; box shots and key-pass recipients are output proxies, while actual box occupation requires supported timed positional evidence.

If a native role check refuses, name the exact phase, slot, actual position and requested role, then explain the returned native legal roles. A changed role changes the plan: identify the revision and football cost, and validate it before calling the plan file-compatible. Never describe an automatic substitution or a different role as matching the agreed request. Source/native failures without a validation diagnostic are not evidence for a guessed alternative.

Prefer the fewest changes that test the hypothesis. Treat results as evidence, not causal proof or a guaranteed engine exploit. A proposed adjustment is advice, not a change applied to FM. When asked for an importable tactic, pass the agreed design to `fm-create-tactic` and state any edits the file tool cannot encode.

For penalty-taker order or a proposed corner/free-kick routine, load `fm-set-pieces` and keep stored orders separate from conditional routine advice.

Completion: give the recommendation first, the deciding evidence, the football mechanism and cost, and a measurable next check. Mark unsupported claims as unknown rather than filling the gaps with tactical certainty.
