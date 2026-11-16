---
name: fm-training-development
description: Review upcoming training, recovery balance and development pathways. Use for training calendars, stored individual focus or club intensity, positional retraining, player development priorities or choosing between first-team minutes, youth football and a loan.
---

# Training and development

## Read the relevant calendar

Read `fm-tools` and `fm-live-investigation` through `fm_read_skill`. Bind the running career, simulation date and managed club. Use `coach_name` from `fm_get_save` when several human managers are active. Inspect the current tool schema before calling `fm_get_managed_training`.

The default window starts on the simulation date and covers seven days. For an upcoming-calendar review, request 14 days unless the user names another horizon; use `start_date` in YYYY-MM-DD form and `day_count` from 1 to 366. Expand only when a named fixture or decision needs it. A historical window still describes stored sessions, not completed training. Complete when the selected manager, date range and returned coverage are explicit.

Keep each returned date and its three slots in stored order. The week-start Monday groups dates; it does not establish session times. Preserve signed `native_code` and `english_definition_name`. Passing Style (0), Rest (300), Recovery (301), Match (500) and Not Available (600) are distinct. Zero is a session code, not missing data. An unknown English name stays unknown; retain its code rather than assigning an effect from memory.

A missing week has null slots and `state: "unavailable_resident_week"`; an unavailable source uses `state: "unavailable_source"`. Check the returned reason and `complete_stored_window`. Preserve those dates in the review. A fully stored window can still contain unknown names or Not Available entries. Neither state establishes a day off.

## Read stored individual focus and club intensity

For a player or roster focus/intensity audit, inspect `fm_get_player_individual_training` and pass 1–100 distinct current `player_refs` from the selected manager's native roster. Preserve every requested identity and returned state. Native roster membership can include loaned-out players; check club/loan state separately before recommending a change you control.

Report `additional_focus.english_definition_name` for `stored_named_focus`. Preserve signed `native_code`: zero is Quickness Rehab, 255/-1 is unset, and other unmapped codes stay `unknown_native_code`. `missing_child` and a present unset child both have unset focus but remain distinct source states. Combined/virtual records return `unsupported_record_kind` with null focus. An error rejects the whole batch; account for it rather than treating the cohort as having no assignments.

Read `club_training_intensity` separately from `additional_focus`. For `stored_named_intensity`, report its English definition: Half Intensity (0), Normal Intensity (1), Double Intensity (2) or No pitch or gym work (254/-2). For `native_default_resolution_requested` (255/-1), report a stored default request. When the question concerns intensity or what that default means, request `include_default_resolution: true` and read `default_intensity_resolution` separately. For `resolved_native_default`, report its English definition and identify it as the native default reconstructed from current condition and an existing selected-manager policy. Preserve `unavailable` and its reason; `not_requested` means the player has an explicit stored choice. Actual `applied_intensity` and workload remain null. Preserve `unknown_native_code`; unsupported combined/virtual records have null intensity. A missing focus child does not hide a readable club setting.

Complete the audit when every requested identity has its returned focus and club-intensity state, grouping only the requested field and retaining unknown/unsupported rows. Applied intensity, medical overrides, workload, attendance, role/position assignment and development outcomes remain unknown. Compare a named selection with a development priority as a coaching judgment; the reader applies no training change.

## Compare positional conversion projects

For a request such as “find positional swap options—players I could train at a new position because their strengths fit”, bind a bounded pool before choosing candidates. Default to the selected managed senior roster and distinguish at-club players, away loans and unavailable profiles. Include other squads or external candidates only when the question calls for them; state each added population and complete its paging through `fm-live-investigation`. An unavailable profile remains unclassified. Complete when every candidate belongs to a named checked pool.

Read current position ratings, foot strength and task-relevant attributes with supported player/profile tools. Load `fm-tactical-analysis` to define the proposed target task in both phases. Compare it with a named familiar role: identify two or three strengths that would transfer, a limiting attribute or physical trade-off, and the actual stored rating for each position. Distinguish existing cover from a conversion experiment using those readings; any selection cutoff is your football criterion, not a native retraining rule. A position rating is neither a learning-speed estimate nor proof of tactical familiarity. If “traits” means preferred moves, preserve their availability separately from attributes.

Check current club/loan links and readiness before proposing an experiment you control. Load `fm-playing-time-dynamics` for an evidenced route to minutes and `fm-squad-planning` for simultaneous cover. Name the familiar-role contribution you would give up, the target-role incumbent whose minutes would change, and whether moving this player would create another gap. The same person cannot supply both positions at once. A strong target profile alone does not establish a spare player, a vacancy or permission to retrain.

Read the stored additional focus through the branch above when supported. Treat its named selection as context for the proposed objective; it does not reveal a role/position retraining assignment. Unset, missing-child, unknown-code and unsupported results stay visible and do not establish that the player has no training. Suggest a selectable focus only from supported English definitions; otherwise name the coaching objective. Additional focus, team sessions and a position change are separate decisions. Their effects, required intensity, learning time and attribute growth remain unproved. Load `fm-staff-planning` only if a coaching-capability comparison would change the decision; a staff rating cannot supply assignment access or workload.

Recommend one candidate and target task, with a concrete alternative of retaining the familiar role. If asked for several candidates, compare them on the same criteria and preserve the weaker option's cost. Propose a bounded manual experiment only subject to readiness, eligibility and actual minutes; never claim a change was applied. Name a checkpoint for refreshed position ratings, participation and role fit, plus the fact that would make you abandon the conversion. Complete when the answer gives a priority, the role/minutes trade-off and a conditional review point without promising a retraining outcome.

## Review recovery balance

Summarize the dated sequence before recommending changes. Count explicit Rest and Recovery separately, identify their positions around Match entries, and flag runs of observed days with neither. State the denominator: requested days, days with all three stored codes, unknown slots/names and Not Available slots. Describe a run across a missing date as incomplete. Slot counts measure the schedule's composition, not workload or intensity.

Resolve fixture dates from supported fixture tools before calling a Match slot a particular opponent, kickoff or congestion problem. When the judgment depends on player readiness, inspect current health, stored condition/sharpness/fatigue, recent participation and club/loan state for the relevant players. Dates, source limits and unavailable readings stay attached to those facts. The calendar alone does not establish individual exposure, attendance, medical clearance or training completion.

Offer a practical conditional change. For example, if the calendar has several observed days without Rest or Recovery before a verified match, recommend reviewing one named date and slot for a recovery-oriented alternative, subject to current readiness and the other sessions that day. If explicit recovery already surrounds the match, preserve it provisionally and focus the review on a named football priority. Explain which planned activity the alternative would displace and what evidence could reverse the advice. Use verified session names; describe an objective when the appropriate selectable session is unknown. These are coaching judgments, not measured FM27 effects or changes applied to the game.

## Measure attribute progress

`player_attribute_history` holds one snapshot of every attribute per month for each player (statement-dependent: name the players, a team or the club's young players). `attributes` is JSON on the 1-100 scale: divide by 5 for the 1-20 scale the screens show. Worked statement 10 in `fm-db` sums the attributes now against six months earlier; for one attribute use `json_extract(attributes, '$.<name>')`. Report the gain in 1-20 points over a stated window, and the attributes that moved most for the role in question. A player with fewer snapshots than the window (a new signing) has no comparison: say so. Progress over a few months is small and uneven; a gain of one or two points in total is noise, not a trend. Compare a player's progress with his minutes (`player_season_stats`) and age before crediting training, a loan or a mentor.

## Build a development pathway

For facilities, academy investment or the balance between infrastructure, staff and minutes, load `fm-club-development`.

For a named player, establish the intended role, current strengths, limiting attributes, position familiarity, club/loan state, contract horizon and evidenced recent minutes. Load `fm-tactical-analysis` when the role needs defining and `fm-squad-planning` when competition for minutes or succession matters. Potential and personality ratings are context, not a promised growth curve; a single profile cannot establish a development trajectory.

Choose one priority and compare concrete routes: a defined first-team role, youth/reserve opportunities where evidenced, or a loan with a suitable intended role. Give each route a plausible source of minutes, the player or unit competing for them, and the fact still needed to choose. A loan's promised role and future minutes remain proposals until verified. Load `fm-club-finance` only when the recommendation creates a fee, wage or contract commitment.

Connect a team session to that priority only as a proposed emphasis. Read the stored additional focus through the branch above when it affects the recommendation. Read stored club intensity through the same branch when relevant. Mentoring, coaching workload, applied intensity and progression over time remain separate unknowns. Propose any focus or mentoring change for a manual in-game decision and explain the objective; a stored focus does not establish its effect. Load `fm-staff-planning` when a development priority depends on coaching capability or a proposed appointment. Staff ratings can inform a comparison when supported; they do not establish training effectiveness.

Finish with the action to take, the deciding dated schedule/player facts, any calculated counts, and the football judgment as separate claims. Name a review point, such as after the next two verified fixtures: check actual participation, readiness and comparable attribute observations before retaining or revising the pathway. Advice should remain useful when some evidence is unavailable; state which recommendation is conditional and which next observation would change it. Loading guidance or passing harness tests proves neither development outcomes nor reduced injury risk.
