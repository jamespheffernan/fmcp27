---
name: fm-contracts-loans
description: Compare player contracts, loan terms and wage contributions. Use for loan costs, purchase options, release or extension clauses, renewals or stored transfer offers.
---

# Contracts and loans

## Bind the players and decision

Read `fm-tools` and `fm-live-investigation` through `fm_read_skill` for attachment, identity and population rules. Establish the running career, simulation date and selected club. For “What do Newcastle pay for our loaned-out players, what terms/options are stored, and which terms should affect my next decision?”, cover outgoing loans and distinguish their recorded rates from actual payments and complete obligations.

Use the club's squad groups and their roster reads, with club links, to discover players; a managed-team vector alone does not cover the whole club. Keep duplicated team memberships separate from unique people. For serious cases call `fm_get_player` with `include_clubs`, `include_wage`, `include_contract_dates` and `include_contract_status`. Use `profile_policy: "available"` when canonical `native_identity` is needed to join independently issued references. Compare same-attachment PERSON index and both identity words, normalising `random_id: null` to the primary identity; names display the result, not the join.

Classify observed outgoing loans from the contract/current club links and native On Loan flag, then inspect their agreements. Preserve disagreement among the flag, parent, borrowing and current club. A stored loan object can remain when the current club differs or an affiliation suppresses the flag. Keep these cases separately qualified rather than forcing them into the active-loan group. Complete when the discovered population, exclusions, unresolved links and coverage limits are explicit; club rosters and contribution records do not establish every loan-related object in the save.

## Read four separate sources

Inspect the current tool schemas and keep these sources in separate columns or sections:

| Source | Read | What the observation establishes |
| --- | --- | --- |
| Main employment contract | `fm_get_player` options above, then `fm_get_contract_terms(player_ref=...)` | Main weekly wage, dates/status and stored main-contract clauses |
| Stored loan agreement | `fm_get_loan_contract(player_ref=...)` | Parent/borrowing/current clubs, signed/end dates, playing/unused wage and monthly-fee terms, purchase conditions and clause flags |
| Transfer-manager wage contributions | `fm_get_wage_contributions` for the selected club | Recorded payer, recipient, person, weekly rate and paid-until date, with source totals |
| Stored proposed transfer offer | `fm_query_transfer_offers` when the question concerns an offer | Stored offer object and supported proposed terms; acceptance and payment obligation remain unestablished |

Call `fm_get_wage_contributions` even when the roster review found no outgoing loans: contributions can concern former players or people now recorded as staff. Follow its player references to establish club/loan context before attributing a row to a current outgoing loan. Leave unresolved people and non-loan contributions visible. Choose `coach_name` or `club_ref`, mutually exclusive; `all_clubs: true` is a separate mode used alone. The selected-club response supplies incoming, outgoing and net-outgoing weekly totals. It checks the complete native list within its bound and rejects overflow rather than silently truncating. An empty checked list means no entries there, not no loan costs.

For each relevant player read the main terms and loan agreement independently. `no_current_loan` means no object in the checked current auxiliary slot; it does not erase a separately recorded contribution. Basic main-contract terms, virtual-player limitations, rejected reads and unavailable fields remain distinct. Complete when each requested source has either a checked result or its precise unavailable state, without losing useful results from other sources.

## Compare the recorded rates

Report currency, period, party and basis beside each amount. Main-contract wages and contribution rates are whole GBP per week on the supported live path. Loan `playing_weekly_wage_gbp` and `unused_weekly_wage_gbp` are separate stored rates paid by the borrowing club; playing/unused monthly fees remain GBP per month. A future purchase or buy-back fee is a separate cash term, not a recurring wage. Keep playing and unused branches side by side: the reader does not establish which branch currently applies, substitute a default for an unspecified unused value or provide a payment schedule.

Show main wage, borrower wage terms and contribution rows separately. A contribution can overlap another source's economic meaning; do not add it to a loan wage or deduct it from the main wage as though the sources formed a complete ledger. “Main wage minus borrower wage” is at most an explicitly assumed playing/unused scenario after verifying the same player, parties and weekly basis; it is not the observed current bill. Explain the offset assumption and leave other costs unpriced. Prefer recorded source rates when that assumption is unproved.

Sum only entries with a proved common source basis, currency, period and paying/receiving party relationship. For contributions use the returned selected-club direction and totals; `both` contributes to both incoming and outgoing, with zero net effect. For a loan-only subset report its included row count and unresolved/non-loan exclusions, keeping distinct contribution entries separate even for one person. Deduplicate roster memberships before any per-player sum. Preserve the source-wide total beside a subset total so it cannot masquerade as complete payroll. Weekly, monthly, one-off, conditional and proposed amounts stay separate; annualisation or conversions are labelled arithmetic scenarios with explicit timing assumptions.

Stored zero is zero. Loan `not_specified`, null, negative native parameters, unmapped offer cash codes and failed reads remain unknown. Unsupported negative live wage/contribution values can reject a read; report that failure rather than coercing a value. A stored `paid_until` or end date neither proves payment due today nor proves the record has ceased to apply. Complete when every total has its source, included population, units and missing amounts, and the answer states whether actual current cost remains unestablished.

## Compare stored appearance-wage steps

For an appearance-linked main-wage review, call `fm_get_contract_wage_steps` for each unique checked player reference. Cover the requested roster explicitly, including away entries when requested, and retain unavailable/basic/no-contract results. The tool returns every kind13 club-league or kind19 international-appearance target, each stored threshold and native entry index/flags/selection. Preserve repeated entries and unknown thresholds; the getter-selected entry does not establish activation.

Report current weekly main wage, each stored target and its signed `difference_from_current_weekly_main_wage_gbp`, all in GBP/week. These are independent target-minus-current scenarios. A lower stored target is not an observed saving. Keep alternative steps separate; `largest_stored_target_increase_gbp` is one person's maximum positive difference, not a sum of clauses, total payroll or budget exposure. The tool leaves trigger satisfaction, appearances still needed and applicability unknown. Complete when every requested player and every returned step is accounted for with that scope.

## Interpret options without activating them

Keep main-contract `terms` in native order, including repeated kinds and `unmapped_entries`. `selected_by_native_property` identifies the getter's chosen entry; it does not activate a clause or make the other entries disposable. `complete_native_vector` describes this bounded main-contract vector, not every agreement or obligation. Preserve thresholds, percentages, dates and units as returned. Release kinds whose names contain “active” still do not establish transfer eligibility. Negative parameters and native-default expiry dates retain their unavailable reasons; `activation_evaluated` remains false.

For loan purchases report the returned `purchase.trigger`, native fee total and initial fee, match threshold/counter, and competition condition when present. The native total can already include additional components; adding them again double-counts. Preserve component parameters, overflow states, unsupported achievements and undecoded stage names. Report optional, mandatory, after-matches or competition-condition terms as stored descriptions with `trigger_satisfied: null`. A counter reaching a threshold does not establish activation or payment due.

Report recall, termination, training and participation flags as stored clauses. Preserve narrower restrictions alongside general permissions, plus `clause_flags.source` and unmapped bits. A nonzero override replaces the entire base word. Neither `can_be_recalled` nor a participation flag establishes an actionable right, recall window, registration, eligibility or permission today.

For an offer comparison, use verified native PERSON/TEAM/CLUB selectors and continue every `next_cursor` with unchanged selectors and limit. Two proved manager vectors include historical objects. Keep aliased memberships and distinct offer objects explicit; they are not multiple commitments. Raw state codes have no verified English acceptance/active mapping. Only a loan offer's `common_team_40` has a proved proposed-borrower role; other TEAM business directions and raw non-loan amounts remain unresolved. Preserve negative offer codes and unavailable currency; proposed loan wages/monthly fees remain proposals, separate from the current agreement. Complete when each option's stored terms and unevaluated conditions are visible.

## Recommend the next decision

Prioritise the term that most changes the named football or financial choice. Compare keeping the present arrangement with one concrete alternative, such as seeking different cost-sharing in a future negotiation, reviewing a purchase option, planning succession before a fixed main-contract expiry, or investigating a proposed recall. Explain the mechanism and trade-off as judgment: wage relief may compete with the desired role/minutes; a purchase term may affect succession planning. An unsupported activation or recall fact makes that action conditional, not the entire summary unusable.

Load `fm-squad-planning` for role, cover and succession, and `fm-training-development` for the loan's proposed development pathway or evidenced minutes. A stored playing-time/cost term does not prove actual participation or a development outcome. Load `fm-club-finance` before recommending a new financial commitment, using its budget procedure rather than treating recorded rates as savings already available. Candidate availability, future deal terms, board approval and complete obligations need separate evidence. The tools do not renew, recall, exercise options, submit offers or change agreements.

Lead the answer with the recommended next decision and the narrow cost finding the sources support. Give a per-player comparison of main wage, loan branches/dates, contribution payer/recipient and material options. Follow with source-specific totals, the alternative and its trade-off. Finish with the evidence that could reverse the priority: verified current branch/payment treatment, condition activation, actionable recall permission, actual role/minutes, candidate interest or full offer cost. Separate native facts, arithmetic scenarios and football judgment; use current authoritative sources for any substantive external FM mechanic claim. Completion means a useful comparison and decision with the unresolved financial/activation facts attached, not a claim to have established the whole bill.
