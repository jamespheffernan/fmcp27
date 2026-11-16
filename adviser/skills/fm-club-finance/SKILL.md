---
name: fm-club-finance
description: Assess club finances, FFP, debt, recorded stadium rent, current or committed wages and transfer or wage headroom. Use for affordability decisions or comparisons with another club.
---

# Club finance

## Bind the club and decision

Read `fm-tools` and `fm-live-investigation` through `fm_read_skill` for attachment and identity rules. Establish the loaded career, current date and managed club. For another club, resolve its exact `club_ref` with `fm_find_clubs`; use that reference for every finance check. Complete when the selected club and decision are explicit: a finance overview, FFP question, or specified proposed fee and wage.

## Read the relevant finances

Call `fm_get_club_finances`. For FFP or debt questions request `include_details: true`; for an FFP verdict also request `include_ffp_projection: true`. Inspect the current schema and returned availability reasons. Keep each competition's verdict, native rule labels, calculation state and date separate. The projection privately replays a pinned native calculation from stored inputs; it does not run game code in FM or refresh spending. Preserve an unsupported branch as unknown.

Show balance, current transfer budget, total weekly wage budget and remaining weekly wage budget in their returned units. Distinguish stored transfer budget from the current available figure. Base finance records may expose only balance. For figures from `fm_get_club_finances`, state that its stored spending has not been recalculated.

For current and committed weekly wage spending, call `fm_get_club_committed_wage_spending` for the selected active coach's club, using `coach_name` from the current save when necessary. Report its returned GBP/week amounts and label them as host-recomputed native spending. Payroll and commitment arithmetic share the same checked inputs; the game itself is unchanged. The original game-thread refresh decision is unverified. Preserve a rejected monetary branch as an unknown whole commitment total, rather than substituting a roster sum or a partial contribution. Other-club selection is unsupported on this route. Keep these recomputed figures distinct from the stored spending behind the budget tool's remaining wage room. Equality of current and committed totals establishes neither a complete future liability schedule nor every staff, bonus or tax cost.

For recorded stadium rent, call `fm_get_club_stadium_rent` for the selected active manager's club, using `coach_name` from the current save when necessary. This route does not select another club. Keep whole GBP per year separate from weekly wages and transfer budgets. Distinguish a concrete stored zero, a typed base-finance literal zero and missing-finance unavailability. The value is stored without refresh; it does not establish a lease obligation, payment schedule, amount due or future liability.

Original principal, native remaining-debt calculations and projected payments are separate observations. Use the obligation branches below when the question needs them. FFP inclusion is a rule input, not proof of payment. Keep club-linked manager records distinct from the projected competition verdict. Complete when every requested figure or verdict has its source, date or clock, currency/period and availability state.

## Read the requested obligation family

Discover the current tools before using these branches. If a named route is absent, report that missing capability; it does not mean the club has no obligations. These routes default to the active coach's club and can select `coach_name` from the save or a canonical `club_ref`, mutually exclusive. Retain the selected club and actual financial owner rather than assuming their identities coincide.

For bank-loan debt, call `fm_get_club_debt_obligations`. Report original principal, stored repayment terms and `remaining_debt` separately. Its named RemainingDebt report covers at most the first ten physical loan slots; preserve source/outside-report counts and each amount's state. A returned calendar-based amount can be usable while its English source label remains unmapped. Keep the label unknown without discarding that amount. This native calculation is not an actual-payment ledger, arrears balance, payoff quote or exact lender identity. A stored zero does not prove settlement; a missing source is not zero.

For retained transfer instalments, call `fm_get_club_transfer_debt_obligations`. Show each recorded payer/recipient, direction, stored unit amount, remaining native count and amount state. Preserve repeated rows and the native first-null prefix boundary. Keep derived gross outgoing, gross incoming, any self-club contribution and the original signed native net distinct; report their supplied reconciliation. A net zero can hide gross outgoing and incoming commitments. These are retained schedule values, separate from proposed offers and bank loans. Their date/interval fields alone do not establish the next payment date, actual paid state or a complete liability ledger.

When the payment-calendar tool is listed and the decision needs payment timing, call `fm_get_club_transfer_payment_schedule`. Report next projected native date/time, remaining native payment count, last projected date and call-argument amounts under their returned source states. The projection assumes unchanged retained inputs and normal native clock advancement; unsupported clocks, disabled processing, failed admission or an exact current processing tick can remain unavailable. Preserve an unknown timezone. Native cash-call arguments use unit times interval, while the separate native debt figures use unit times remaining counter; these amounts can differ and must not be substituted or added together. A projected opportunity does not establish that cash was paid, is overdue, or equals the recipient's net receipt.

When the contingent-clause tool is listed and material to the decision, call `fm_get_club_contingent_transfer_clauses`. Its population is the selected payer's retained APPEARANCE_MONEY_INFO family, not every bonus, clause or incoming receivable. Preserve payer/recipient, literal person reference, native event-kind code, amount, progress and target. English event meanings and full person/contract/match eligibility remain unestablished. A counter reaching a target does not prove admission, triggering, a due payment or cash paid. Keep unpriced contingent exposure separate from recurring schedule sums.

Use `fm-contracts-loans` for a player's main contract, loan agreement, wage contributions or proposed offer. Do not add overlapping views of the same economic term into one total. A combined financial recommendation must state the included families, units, dates and unresolved costs; none of these bounded sources establishes complete future cash flow or all liabilities.

## Test a proposed commitment

Use `fm_check_transfer_budget` for a specified upfront fee and `fm_check_wage_budget` for a specified additional weekly wage. Report both results and remaining amounts; a null result remains unknown. For several signings, compare the combined upfront fees and combined additional wages against the same club's budgets once, rather than approving each against the full budget independently. Name assumptions about outgoing wages or receipts; count them only when the source establishes their budget effect.

The comparisons cover those two components. Full deal affordability also needs fees, instalments, bonuses, existing and future commitments, seller terms and board approval, which may be unavailable. A positive budget comparison or current FFP verdict does not settle the whole offer or future compliance. Treat a hypothetical sale or wage saving as a scenario, with its assumed amount and timing.

## Make the football decision

Load `fm-squad-planning` when the decision involves signings, renewals, sales or loans. Connect each proposed cost to the role it fills, alternatives already at the club and the minutes available. Use `fm-tactical-analysis` when a tactical change could address the same need. Give a recommendation at the strength the evidence supports: for example, “the upfront fee fits; preserve wage headroom until the contract cost is known.” Keep football judgment separate from decoded finance facts and arithmetic. Real-world competition rules require a dated external source; do not substitute them for the career's native rules.

Completion: answer the decision first, give each requested source and its coverage/units, include budget and per-competition FFP checks when material, identify unpriced commitments, and name the next fact that could change the recommendation. Guidance loading alone does not establish any club's financial position.
