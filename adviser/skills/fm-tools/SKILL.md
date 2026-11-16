---
name: fm-tools
description: Choose and use pi-fm tools for live careers, saved archives, recorded matches, calculations and file output. Use before gathering evidence or saving a report.
---

# Using pi-fm tools

## Choose the evidence source

1. Identify the question and the records needed to answer it. Default to the running career; use a named save or archive when requested. For historical matches, distinguish retained career results, captured tables and observed match runs. Load `fm-live-investigation` with `fm_read_skill` for the detailed query and identity rules.
2. Inspect the available tool descriptions and schemas rather than guessing arguments from a remembered tool name. Reader updates change field coverage. In Code Mode, use `ALL_TOOLS` for discovery and `tools.mcp__fm_live__*` for calls. Game access stays read-only. Six exact registered tools declare host writes: the recorder, current-match and shot-origin reads that preserve period observations, and the three retained period reports that finalize local links. A false annotation permits only those bounded host effects.
3. For live records, call `fm_status`, `fm_attach`, then `fm_get_save` sequentially. Keep the returned session and entity references within that attachment. After a restart, resume or save change, refresh them before further queries.
4. Choose the smallest supported query that covers the question. Finish its pagination with unchanged selectors, including empty pages, before calling a roster, search or ranking complete. Report the checked subset if interrupted.

## Route the question

| Need | Starting point |
| --- | --- |
| Training calendar and stored individual focus | `fm_get_managed_training`, `fm_get_player_individual_training`; load `fm-training-development` for code and coverage rules |
| Current XI, bench and phase roles | `fm_get_managed_team_sheet`, `fm_get_managed_tactical_assignments` |
| Available squad and current injuries | `fm_get_next_match_squad`, `fm_get_player_injury_status`; check club/loan state and bans separately |
| Current international duty and estimated return | `fm_get_player_international_duty` with distinct selected-roster refs; keep false, unavailable and outside-scope separate |
| Player search and profiles | `fm_find_save_players`, `fm_get_player`; `fm_query_save_players` for filtered recruitment |
| What the manager sees of players' attributes (fog of war) | `fm_get_manager_visible_attributes` with checked refs and the attributes asked about; exact, range, unknown and unavailable stay separate from the stored full-information values; load `fm-recruitment` |
| Contracts and spending | Contract, loan and wage-contribution tools; club finances and budget checks |
| Season or date-range performance | `fm_get_match_data_columns`, then `fm_query_match_scope` with projected fields |
| Explicit request to record this match | `fm_record_current_match`; follow the capture branch below |
| Exact completed match | Resolve fixture identity/result; inspect retained coverage and `fm_list_observed_match_runs` when available |
| Retained shots withheld only by strict xG | Follow `fm-live-investigation`’s `include_source_observed: true` fallback; keep qualified counts/actors separate from verified xG |
| Half-by-half passing or accuracy | Resolve the exact retained fixture, then inspect `fm_report_retained_pass_network_by_period` for attempted and completed passes with verified period coverage |
| One player's pass links, pass map or position in the match being played | `fm_get_current_match_pass_network`, `fm_get_current_match_pass_events`, `fm_get_current_match_spatial`; follow step 6 of "During a match" in `fm-tactical-analysis` |
| Located current incomplete passes | `fm_get_current_match_pass_events` with `pass_outcome="not_completed"` or `"all"` when advertised; follow `fm-live-investigation` for event-point and denominator limits |
| A Data Hub chart; where possession is won or lost | "Read a Data Hub chart" below: `fm_get_ui_screen(screen: "team_analytics")` for the game's own chart; `fm_get_retained_possession_events` per match for players, matches and halves |
| Possession won/lost by half and player | `fm_report_retained_possession_by_period` for one exact retained result with an independent possession witness and native period stops |
| Historical captures | `fm_list_captured_match_sources`, then a pinned captured query |
| Explicit saved archive | `fm_list_saved_careers`, then file queries with `expected_snapshot_id` |
| Native tactic templates or files | `fm_tactic_file`; call `{action:"schema"}` for its registered JSON contract when CodeMode's declaration is opaque; follow `fm-create-tactic` |
| Interactive match report with heat maps, passing and player stats | `fm_match_report` when listed; select one exact retained result or pinned catalog fixture |
| Text report, note or skill draft | `fm_write_text` |

These names are entry points, not a frozen inventory. If a tool is missing, report that limitation and use another source only when it answers the same question with stated coverage.

For phase-role or player-instruction advice, load `fm-tactical-analysis` for the native/UI limits. A role in Football Manager 27 has no duty. Each player has one role in possession and one role out of possession, and that is all the game shows. Never write a role with Defend, Support or Attack after it. A file-authoring role entry is `{phase, position_index, role}`. Native role labels, `native_available` and raw PI states0–3 do not establish visible UI choices or effective instructions. Give manual advice through the user's actual role and PI controls, preserving their reported UI limits; follow `fm-create-tactic` for exact file encoding.

For a current-match read when the user requests no saved observation, set `fm_get_current_match`'s `persist_host_observations=false` when its actual schema supports it. This skips only its two automatic period/spatial stores and their context/index writes; check both returned capture reasons for `disabled_by_request`. It is not a general no-host-writes guarantee for other tools. Preserve an unsupported option as a capability gap rather than silently using the default host persistence.

## Read a Data Hub chart

Read the chart the user is looking at; never ask them to describe it.

- **The game's own chart.** `fm_get_ui_screen(screen: "team_analytics")` returns the Data Hub's team charts for the season in the league. By default it gives the four zone maps in full (Possession Gained, Possession Lost, Passes attempted, Defensive Actions) and the two set-piece first-contact maps, and names the rest in `other_charts`. Each zone map has `zones`: six columns along the pitch, column 1 at the end the team defends and column 6 at the opposition's, with `percent` of the team's events in each and the bar `intensity` the game draws. `summary_extended` is the game's own reading ("81 possession gains per game, compared to an average team, with 79 per game"). Quote the percentages and that sentence. Two columns make about a third; the game states no column width, so call thirds approximate.
- **The other charts.** `chart: "<words of its name>"` returns one in full, `chart: "all"` every one: scatter graphs place all the division's teams on two named axes with the division's minimum, mean and maximum and the quadrant labels; polygons give each statistic beside the division's comparison value. `team: "team:<index>"` reads another team, which holds a shorter set.
- **Players, an opponent, one match.** The same tool, by `screen`: `player_analytics` lists every player scatter graph the Data Hub offers for the squad (35, by group; names until `chart` picks some); `person_analytics` with `person: "person:<index>"` gives one player's polygons against his position and his scatter graphs; `opposition_analytics` with `team` gives the charts of that team's report (its general polygon and its standout players); `match_analytics` gives one of the last three matches (`match: 1` is the latest): possession by third for each side and both shot maps by location with expected goals, and with `chart: "pass map"` or `"average positions"` the pass combinations and each player's average position overall, in and out of possession. The latest match adds the analyst's `summary`, the xG story (every shot's time, expected goals and the score) and, with `chart: "momentum"`, the momentum chart.
- **Which players, which matches, which half.** The chart is a season total. For the detail, `fm_list_retained_match_data` lists the matches that still hold events: about the user's last five, plus the next opponent's. For each, call `fm_get_retained_possession_events(fixture_ref, team_native_id)` from one Code Mode script. Every event names the player and carries `period`, `defended_end` and `length_fraction_from_own_goal` (0 = own goal line, 1 = the opposition's); each side carries `anchor_thirds`, won and lost by third with the `unplaced` count. `orientation` gives the tick at which the sides change ends. The position is the anchor the game stored with the event, which the reader has not proved to be the exact spot of the turnover: state that in one line and give the split.
- State the sample of anything built from events ("394 regains over your last 5 matches") beside the season chart's own figures. Older matches keep totals only: `player_season_stats` by team, `match_player_stats` per match.
- A chart the user will want again is a tool: save it with `fm_toolbox`, returning a `pitch` or `stacked_bar_chart` section.

## Record an observed match

When the user asks to record this match or preserve the current observation, call `fm_record_current_match` once with the fresh session. It writes an immutable host SQLite and local registry entry; its `readOnlyHint=false` describes that host write, not permission to mutate the game. Report the returned capture/source identity and verified prefix coverage only after a successful receipt. An unavailable source means nothing was captured. This is one bounded observation: background recording and automatic repeated captures are not started. Continue historical reads through the observed-run discovery/query tools.

When that recording also needs incomplete pass locations and the schema advertises the option, set `include_incomplete_passes=true` (default false). Require `registered=true`, then discover the exact source and query its advertised `pass_attempt_events` using the receipt's `source_id` and `sha256` as `capture_id`. Keep `completed_pass_events` separate. Old recordings without captured attempt coordinates remain unsupported; follow `fm-live-investigation` for native event scope and unknown recipients/reasons.

## Read international duty and witnessed periods

For current international-duty questions, pass each fresh selected-roster reference to `fm_get_player_international_duty`. Report the native duty/travel gate, reason and estimated-return date together. A false gate is a checked negative for this predicate; an unavailable or outside-current-TEAM row is unknown. Loaned-out players can remain on the native roster. This is one availability input, with no full eligibility, physical whereabouts or guaranteed actual return claim.

For possession won/lost by half, resolve the requested retained fixture, then use `fm_report_retained_possession_by_period`. Preserve its exact original actor population, checked zeros, native intervals, side totals and unassigned events. A player selector keeps full-side totals; missing witnesses stay unavailable. The report's counts do not establish pressure success, paired turnovers, on-pitch minutes or a tactical cause. It may finalize local period-link metadata after the existing epoch checks; it does not create a new historical observation.

## Calculate without losing provenance

Use Code Mode to paginate, join verified identities and calculate totals in JavaScript. Check every result for `isError` before consuming it. Keep dependent calls sequential. Return the deciding evidence, counts, date range and missing values, not entire raw tables. Sum numerators and observed denominators before computing rates; preserve unknown values rather than turning them into zero. Code Mode has no Node, filesystem, network or extra model API; file output goes through the dedicated tool.

## Generate an interactive match report

Use this branch only when `fm_match_report` is listed. If absent, the HTML generator is not installed: state that limit and provide a source-backed text summary rather than claiming a report file.

For “give me an interactive report for our last match”, resolve the latest completed match from fresh live result records first. Check its date, ordered team IDs, competition and final score. Call `fm_match_report` with `source="retained"`, those exact selectors, the native match key when returned, and the loaded career’s name/creation date/version from `fm_get_save`. The host starts its own attachment and rechecks the selection; opaque session/fixture references are not transferable.

For an explicitly selected historical capture, use `fm_list_captured_match_sources`, query that exact source/capture pin for the desired `fixture_id`, then call `fm_match_report` with `source="captured"` and those catalog pins. Preserve the historical capture date in your answer. Source kind, fixture identity and score must answer the user’s selected game; unavailable live data does not authorize silently substituting another playthrough.

For an unsaved current match or a half-time report, capture a verified observation with `fm_record_current_match`, then require `registered=true`. Use `fm_list_observed_match_runs` to discover that exact returned source/capture, and query its `fixtures` table with `fm_query_observed_match_run`. Call `fm_match_report` with `source="observed"`, those source/capture pins and `fixture_id` equal to the exact stringified `official_match_unique_id`. An existing explicitly selected observed recording can skip the recorder. The generated report keeps each recorded section's own scope: a prefix stays a prefix, earlier tracking stays earlier tracking, and unknown score, shot tables, periods and retained player statistics remain unavailable. Inspect the successful receipt before linking its HTML. A failed or unavailable recorder does not authorize another fixture or playthrough.

A retained report can offer separately labelled source-observed attempts when their complete counts and canonical actors qualify but strict xG does not. Its optional map checkbox preserves the xG qualification; official aggregate totals and the default strict shot collection remain separate. A missing or unqualified collection stays unavailable.

The tool derives the HTML from the verified source, including supported heat maps, positions, passing and player statistics. When the user requests a filename and the actual schema advertises `filename`, pass one safe `.html` leaf, for example `"Newcastle Liverpool match report.html"`; it stays under Agent Outputs. Omit it for the deterministic default. Caller directories, filesystem paths, HTML and source JSON remain unavailable; existing different content is refused. Missing fields/maps stay unavailable. Read the successful receipt, then return its absolute report link and material coverage limits. The embedded JSON retains provenance. On failure, preserve the returned artifact state. A null state means publication may have completed. Retry the same verified selectors and filename to recover the immutable report, or correct a stale selector when the source changed.

## Save text

Use `fm_write_text` with `path` and the complete `content`. Project-relative paths stay in the pi-fm project. For a report outside the project use `~/Agent Outputs/YYYY-MM-DD — Descriptive title.md`, using the actual report date. Include the career/snapshot date separately in the report. Supported suffixes are `.md`, `.txt` and `.csv`, up to 1 MiB of UTF-8 text. Existing files, symlinks, hidden paths and dependency folders are refused; choose a new versioned filename rather than retrying the same collision. There is no general file reader or editor.

For CSV, quote cells containing commas, quotes or newlines and double embedded quotes. For a skill draft, use a named folder under `skills/` and a `SKILL.md` with `name` and `description` frontmatter. Writing a draft does not activate it: the launcher loads only its explicit bundled guides, which must be updated by the coding lead to include a new skill. Restart pi-fm to reload changed bundled guides.

Check the tool result before claiming the file exists and link its returned absolute path. Text exports are reports, not importable `.fmf` tactics. Use `papercut` only for recurring harness friction, with no secrets or private player dumps.

Completion: the answer identifies its source, coverage and material unknowns; any saved artifact has a successful tool receipt and an absolute path.
