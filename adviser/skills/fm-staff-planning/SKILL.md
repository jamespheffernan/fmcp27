---
name: fm-staff-planning
description: Compare coaching and recruitment staff capabilities and prioritise appointments. Use for staff strengths, weaknesses, succession, renewals or named staff candidates.
---

# Staff planning

## Establish the employed population

Read `fm-tools` and `fm-live-investigation` through `fm_read_skill` for attachment, identity and population rules. Bind the running career, simulation date and exact club before comparing staff. Use the selected `coach_name` for a human manager or resolve another club with `fm_find_clubs` and use its `club_ref`; these selectors are mutually exclusive. Inspect the current staff tool schema.

Call `fm_get_club_staff` with `include_attributes: true` and `include_job: true`. Keep its unique `count`, `native_vector_counts`, `team_manager_links` and coverage limitation distinct: vector and manager-link counts overlap and must not be added into a headcount. Every returned person has checked native membership and a contract to the club. This covers three native staff vectors plus team managers; equality with every UI staff category and complete board/support coverage remain unproved. A rejected read is unavailable evidence, not an empty department.

Group people by the decoded `contract.job.title` and its team scope. Preserve first-team, reserve and youth roles separately, and retain combined player/staff records. A manager or director appearing in the list establishes employment and the returned title, not coaching assignments, scouting assignments or delegated responsibilities. Keep `unmapped_native_job` and a null title as unclassified; their ratings remain usable as individual observations, but they cannot establish coverage of a named department. Complete when the answer's population and unclassified roles are explicit.

## Compare capabilities for the actual question

For “Where are Newcastle strongest/weakest in coaching and recruitment staff, and which appointment should I prioritise?”, compare both functions before choosing a priority. Build a compact comparison of named people, exact roles/team scope and the few stored ratings that decide each judgment. Establish strongest and weakest **within the checked population and stated function**; a league-wide or save-wide ranking requires a separate comparable population.

Select relevant ratings by the proposed football task. These are comparison lenses, not verified FM effect formulas:

| Proposed task | Stored ratings to inspect together |
| --- | --- |
| A coaching emphasis | Relevant `attributes.attacking`, `defending`, `possession`, `technical`, `tactical`, `fitness`, `goalkeeping` or `set_pieces`; compare `motivating` and `determination` alongside it |
| Youth coaching/development support | Relevant coaching ratings, `working_with_youngsters` and `people_management` |
| Assessing current recruits | `judging_player_ability`; compare `judging_player_potential` if succession/development matters |
| Recruitment analysis | `analysing_data`, alongside the assessment ratings relevant to the proposed task |
| Proposed staff selection or negotiation support | `judging_staff_ability` or `negotiating`, according to the decision; verify responsibility separately |

Use exact returned field names and values. `attributes.attacking` describes a stored coaching rating; `tendencies.attacking` describes a preference. Keep tendencies, board ratings and personality separate from coaching capability. Native scaling is already applied; these underlying values may differ from role-filtered or visibility-filtered UI values. Preserve valid zeros and unavailable states.

Compare the named ratings side by side rather than manufacturing coaching stars, aggregate quality scores or fixed “elite/poor” thresholds. A higher task-relevant rating supports a relative comparison; it does not prove actual effectiveness, scouting accuracy, development gains or an FM27 mechanic. Keep trade-offs visible when one person leads one rating and another leads a second. A specialist with a higher rating in another team scope is evidence of capability there, not proof they can serve the first team.

For focused filtering use `fm_query_club_staff`, with a justified `job_contains` and optional `sort_by`. It sorts one rating descending and returns full match counts, returned counts and `truncated`; its result is not an overall suitability ranking. Broad substrings can mix scopes and roles. Job filtering rejects unmapped titles; use the unfiltered club read to report the uncertainty. If the 100-result maximum still truncates, compare the full `fm_get_club_staff` population instead of treating the limited result as complete. Thresholds, when useful for a requested comparison, are explicit selection criteria, not game rules.

## Choose the next appointment

Prioritise one task and role from the observed gap, its importance to the club's immediate football objective and the alternatives already employed. Load `fm-training-development` when deciding which coaching or development emphasis matters; use `fm-squad-planning` when recruitment needs depend on squad construction. A low rating alone does not establish a vacancy or justify replacing a person. An absent role in the checked source means “no decoded incumbent found here”, with population limits attached.

Compare the proposed appointment with a concrete alternative: retain the current setup, consider a suitable existing employee subject to role/assignment permission, or address the other function first. State the expected mechanism as football judgment: for example, strengthening the named assessment task or supporting the identified coaching emphasis. Name the opportunity cost: another staff need remains, an existing strength is displaced, or extra spending is required. Keep actual responsibility delegation, coaching stars, workload, assignment access, board-permitted headcount and willingness to change role unknown unless separately evidenced. Staff ratings and job titles do not supply these facts.

An appointment priority can be useful without a verified external candidate. Describe the target role and which named ratings should improve on the incumbent. For a named candidate, use `fm_find_staff`, complete every search cursor with the same name, resolve ambiguity, then request `fm_get_staff` with attributes, job and club. This is a name search, not a save-wide staff attribute search. Contract employment, an absent contract or a stored expiry does not establish availability, interest, compensation or permission to hire.

When renewal risk or cost could change the choice, read the serious alternatives' contract dates/status and weekly main-contract wages using the supported options. Fixed expiries, computed expiries and unavailable/basic states remain distinct. `fm_query_club_staff_contracts` lists unclassified people separately; they are not confirmed nonmatches. A past fixed expiry does not predict departure. Weekly wages are GBP main-contract amounts, excluding bonuses and other costs; `fm_query_club_staff_wages` sums only the checked list, not complete payroll. Use `fm_get_contract_terms` for material stored clauses, preserving unavailable/unmapped terms and unevaluated activation conditions.

Load `fm-club-finance` before recommending a financial commitment. Treat proposed wage, compensation and other appointment costs as scenarios until verified. A club wage-budget reading alone does not establish a staff-specific allowance, an offer's approval or all-in affordability. The connected tools read evidence; they do not appoint, dismiss, renew or delegate.

## Give a bounded recommendation

Lead with the priority and deciding reason. Follow with the strongest and weakest observed functions, named incumbents, role-relevant rating comparisons, mechanism and trade-off. Label decoded native facts, arithmetic, football judgment and any sourced FM mechanic separately. An FM effect claim needs current authoritative evidence; otherwise retain it as a hypothesis without a numerical promise.

Finish with the material unknowns and the evidence that could reverse the choice: an existing employee's verified assignment and capacity, permission to add the role, a candidate's interest and full cost, or a changed football priority. Use available passive reads first; identify an unsupported fact without requiring an unsolicited manual screen check. Completion means the original question has a supported comparison and conditional priority, with source coverage and unknown assignment/workload preserved. Reading this guide proves neither current staff quality nor appointment outcomes.
