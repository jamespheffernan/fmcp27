---
name: fm-club-development
description: Prioritise facilities and long-term youth or club development. Use for infrastructure, academy investment, youth pathways or choosing a facilities priority against staffing and minutes.
---

# Club development priorities

## Establish the objective and horizon

Read `fm-tools` and `fm-live-investigation` through `fm_read_skill`. Bind the current career, date, exact club and the user's intended horizon. Distinguish supporting current senior/youth players, developing future intake and an infrastructure proposal. Preserve stated sporting and financial ambitions; do not invent board objectives. Complete when the decision and a credible alternative are explicit.

## Read the club's own stored facilities

Resolve the exact `club_ref` with `fm_find_clubs`, matching canonical identity rather than name alone, then call `fm_get_club_facilities`. Report the four returned fields separately: `training_facilities`, `youth_facilities`, `youth_coaching` and `youth_recruitment`, with each source state and observation date. Training uses the native editor range 0–20; the youth fields admit signed -1 as unassigned. Preserve zero as a stored level. Unassigned, missing-secondary and out-of-range readings have no usable interpreted level.

These are the club's own stored values. Effective facilities may follow affiliations, sharing or defaults and remain unevaluated. Do not translate raw values into stars or quality bands, infer a specific training ground, or treat a lower number in a different facility field as a common-scale investment ranking. A stored level does not supply project cost, capacity, completion date, board permission or development gain. Complete when all four fields and every material source limit are accounted for.

## Connect facilities to an actual pathway

Load `fm-training-development` for the relevant calendar, individual focus/intensity and a named player's minutes pathway. Load `fm-squad-planning` for youth/senior depth and succession, and `fm-staff-planning` when an appointment or capability comparison could address the same objective. Distinguish pre-intake infrastructure from the opportunities and coaching available to players already at the club. Native staff ratings do not establish assignment access, effective workload or growth.

The official [FM26 youth-intake guide, 18 December 2025](https://www.footballmanager.com/the-dugout/developing-and-maximising-your-youth-intakes-fm26) distinguishes pre-intake facilities/recruitment from development after arrival. Use that versioned explanation as context, checked 9 November 2026. It does not validate this FM27 career's effective property, intake distribution, staff influence or an investment return. Do not rename a native youth-coaching field as an established equivalence to every historical UI label.

Compare at least two routes: investigate a named facility proposal, improve an evidenced staffing or minutes bottleneck, or retain the present setup while observing the next cohort. Explain the mechanism as a hypothesis, the displaced priority and the fact that would change the decision. A low facility observation alone does not prove it is the binding constraint. A potential-ability reading or one intake does not establish a predictable development trajectory or a guaranteed golden generation.

## Keep the commitment conditional

Load `fm-club-finance` before recommending a financial commitment. Preserve existing cash/budget, wages and each supported obligations family separately. Project cost, operating cost, approval and future revenue remain unpriced unless sourced. Compare an explicit cost scenario only when the user or a supported source supplies its amount and timing; a wage or transfer budget is not automatically a facilities allowance.

Stored stadium/project records, when relevant, retain their own units, dates and unresolved status. They do not prove that a project is authorised, under construction or affordable. Do not add projected transfer cash, native debt and a hypothetical project into one supposed complete cash forecast. No tool here submits a board request, appoints staff, changes facilities or advances time.

Lead with one priority to investigate or a reason to retain the setup. Give the deciding facility/pathway facts, alternative and opportunity cost, then a review point tied to the user's horizon. At review, compare the same dated sources, actual opportunities and cohort observations; keep unknown effective facilities, causal growth and board decisions explicit. Completion means a useful conditional development decision, not a forecast or a claim that the long-term domain is fully decoded.
