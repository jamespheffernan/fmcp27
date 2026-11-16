---
name: fm-recruitment
description: Compare recruitment candidates with an incumbent and a spending plan. Use for a shortlist, named transfer targets, succession candidates, what a target would want, affordability or choosing whom to pursue.
---

# Recruitment decisions

## Define the job and the pool

Name the role the signing must do in the user's tactic, the incumbent and internal cover (load `fm-squad-planning` when the gap itself is in question), and the horizon: starter now, successor in a year or two, or a development signing. Turn the role into three to five football requirements (a goalkeeper successor who must command the box and play out; a left-back who must overlap and defend the far post). They are judgement: say so.

The pool is the user's named candidates, the club's scouted players, or a search the user asked for. Say which, and how many players it covered.

## Search with what the manager knows

Other clubs' players come from the manager view (guide `fm-db`, worked statements 26 and 27):

1. Positions from the full view (`player_view.position`, public), filtered by age and club.
2. Rank the `idx` list in the manager view on `m_scouted_player_view` (or `m_player_view` for unscouted players the club knows of): by the sure bounds of the requirements (`<attr>_min`), stars (`current_ability_stars_min`, `potential_ability_stars_max` for a development signing), and `unknown_n`.
3. Wages and contract expiry of other clubs' players are public: filter a wage cap with `wage < N` and read `contract_expires` (a contract ending within 18 months lowers the fee). Their transfer values, position ratings and clauses are not visible: never filter or rank on them from full data.

Report ranges as ranges and ability as stars. A candidate with many unknown attributes is a scouting assignment, not a signing: say which attributes to scout.

## Compare the football case against keeping the incumbent

Put the candidates and the incumbent in one table with the same columns: age, club, stars, the requirement attributes (ranges for candidates, exact for your player), this season's minutes and the per-90 numbers that matter from `player_season_stats` (public). Name one advantage and one weakness of each, and the route to minutes for each. Distinguish an immediate upgrade, a younger successor and a development option.

## What he would want, and can you afford it

For each serious candidate read `agent_demand` naming him (manager view `m_agent_demand`, worked statement 7). It is what his agent says on the game's panel today: the player's interest ("Very Interested", "No interest", ...), the selling club's fee range (`fee_min`-`fee_max`), the wage range he would want from you (`wage_min`-`wage_max`, pounds a week), the contract end he wants, and lines on squad status, role and promises he would ask for. Quote the ranges as ranges, never a midpoint, with the date. "No interest" or a line saying the club will not sell ends the case for now: say so and move to the next candidate.

Test the top of each range against your club: `club_finance.transfer_budget_finance_Cntb` for the fee and `remaining_wage_budget_weekly` for the wage (own club, worked statement 7). A deal is affordable for sure only when both tops fit; when only the bottoms fit, say what has to give (a sale, a lower wage offer, a loan with an option). Signing-on and agent fees, bonuses and instalments are not in the demand: name them as unknown.

The promises an agent lists ("will expect to be considered among the most noteworthy players") become promises you make: check them against `promise` and the incumbent's role before recommending.

## Registration

A signing must be registered to play. For a competition with a registration rule (the Champions League, a domestic league's quota) read `fm_get_ui_screen(screen: "squad_registration", competition: "comp:<idx>")` for the spaces left, the homegrown counts and the deadline, and `competition_registration` for who holds the places now (worked statement 9). Say whether the candidate fits a free place, would push someone out, or counts against a homegrown minimum.

## Recommend the next step

One action: pursue a named candidate (with the fee and wage ceiling that keeps it affordable), scout a named candidate further (which attributes), monitor a successor until a named date, or promote or keep the internal option. Give the deciding comparison, the agent's ranges and the budget result, and what would reverse it: a higher demand, lost interest, an injury to the incumbent, a registration place that is not free. The tools do not make enquiries, bids or offers; the user does that in the game.
