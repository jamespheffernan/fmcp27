# Core procedure

## Route the question

| Question | Start with | Guide |
| --- | --- | --- |
<!-- fm:if fm_db_query -->
| Search, ranking or shortlist of other clubs' players | `view: "manager"` on `m_scouted_player_view` or `m_player_view` (wages public); positions from the full view first | `fm-db`, `fm-recruitment` |
| What a target would want, can I afford him | `agent_demand` for him (ranges, interest), `club_finance` for the budget | `fm-recruitment` |
| My squad: depth, tiers, ages, wages, attributes | `fm_db_query` on `player_view` with `team_idx = (SELECT team_idx FROM _managed)` | `fm-squad-planning` |
| Contracts expiring, renewals, wage structure, loan terms | `contract_view` / `player_view` for my club (loan terms: `role = 'loan'` rows) | `fm-contracts-loans` |
| Season statistics, form, per 90, league percentiles | `fm_db_query` on `player_season_stats` (one row per player and competition) | `fm-db` |
| Career by season, past injuries, transfers, league finishes, past winners | history tables, naming the people or club | `fm-db` |
| Last matches, ratings, why a player rated as he did | `match`, `match_player_stats`, `match_team_stats`; the loaded match: `match_rating_component`, `match_momentum`, `fm_get_match` | `fm-db`, `fm-tactical-analysis` |
| Fixtures, results, league tables | `fm_get_calendar`, `fm_get_league_table`; analysis: `fixture_view`, `match`, `standing_view` | `fm-season-planning` |
| Registration for a competition | `competition_registration`; rules and deadline: `fm_get_ui_screen(screen: "squad_registration", competition: "comp:<idx>")` | `fm-season-planning` |
| Promises, leaders, social groups, complaints | `promise`, `squad_hierarchy`, `social_group`, `player_happiness_reason` | `fm-playing-time-dynamics` |
| Income, expenditure, sponsors, debt, budgets | `club_finance_breakdown`, `club_finance_month`, `club_finance` | `fm-club-finance` |
| Attribute progress | `player_attribute_history`, naming the players | `fm-training-development` |
| Transfer offers, injuries, news | `fm_db_query` on `transfer_offer_view`, `player_injury_view`, `news_item`; inbox text: `fm_get_inbox` | none |
<!-- fm:end -->
<!-- fm:unless fm_db_query -->
| Save-wide search or shortlist | deferred: `fm_query_save_players`, `fm_find_save_players` | `fm-recruitment` |
| Squad lists, contracts, wages | deferred: `fm_get_club_squads`, `fm_get_team_squad`, contract tools | `fm-contracts-loans` |
<!-- fm:end -->
| Board confidence, signings feedback | `fm_get_board_confidence` | none |
| Board expectations, club vision, objectives | `fm_get_club_vision_progress` (each objective with the screen's judgement) | none |
| Inbox, things to deal with | `fm_get_inbox` (`unread_only`; `items` for bodies) | none |
| Agreed playing time (squad status) of my players | `fm_db_query`: `squad_status` in `player_view` or `contract_view` (your club's players) | `fm-playing-time-dynamics` |
| Who is unhappy and why | `fm_get_squad_happiness` (whole club, one call); one player: `fm_get_player_status` | `fm-playing-time-dynamics` |
| Next match: XI, tactics, opposition | `fm_get_calendar` for the opponent; `fm_get_ui_screen(screen: "tactics")` for my prepared tactics (each slot's name, mentality, named team instructions, positions and roles); SQL for availability and the opponent's results and players | `fm-tactical-analysis` |
| A match I am playing now (in play or at half time) | `fm_get_ui_screen(screen: "tactics")`: `fields.tactic.in_match` is the tactic in use now (null when no match is loaded); `fm_get_match(team)` for score, team statistics and ratings; deferred: `fm_get_current_match(include_player_changes: true)` for the substitutions made, `fm_get_current_match_player_physical` for condition now; for one player's involvement, supply and position (pass map, average position, heat map), `fm_get_current_match_pass_network`, `fm_get_current_match_pass_events` and `fm_get_current_match_spatial` | `fm-tactical-analysis` |
| Shot maps, pass maps of earlier matches, retained or observed matches | `fm_get_match` (shot map); deferred retained-match and observed-run tools | `fm-tools` |
| A Data Hub chart (team or player analytics: possession gained or lost, zones, scatter comparisons) | Read it, never ask the user to describe it: `fm_get_ui_screen(screen: "team_analytics")` gives the game's own zone maps and sentences (`chart: "<name>"` for a scatter graph or polygon; screens `player_analytics`, `person_analytics`, `opposition_analytics` and `match_analytics` for players, one player, an opponent's report and a recent match's shot, pass and position maps). By player, match and half: deferred `fm_list_retained_match_data`, then `fm_get_retained_possession_events` per match | `fm-tools` |
| "Can you see X?" | `fm_coverage(search: "...")` | none |
| Other screens | `fm_get_ui_screen` (training, negotiations); deferred: `fm_get_scouting`, `fm_get_transfer_activity`, `fm_get_medical_centre`, `fm_get_finance_projections`, `fm_get_youth_intake` | the matching guide |

"Deferred" tools are declared by `tool_search` (search with the tool's name) and callable from Code Mode at any time.

## Identities

- Resolve a named player, club or match to one `idx` before reading details. When a name matches several records, choose by club, age and position and say which you chose.
- "My squad" is the first team (`team_idx`); reserves and youth (`club_idx`) are reported separately and included only when the question is about the club. Loaned-out players stay on the club's books: say whether they are counted.

## Completeness

- A list is complete only when its query covered the whole population: check `truncated` and `row_count`. If you stop early, say which subset you checked.
- Unknown stays unknown: never turn a NULL into zero; sum numerators and observed denominators before computing a rate.

## Calculations

- Joins, filters, sums, per 90 figures and percentiles go in SQL (or Code Mode), never in your head. Return the deciding rows, not whole tables.
- Per 90: `x * 90.0 / minutes`, only for players with at least 450 minutes unless you say otherwise. League percentile: `PERCENT_RANK() OVER (ORDER BY x)` over players of the same position group and competition season.

## Manager knowledge

- Rank scouting candidates by what is known for sure (`<attr>_min`, `current_ability_stars_min`) and list the most uncertain attributes as the reason to scout further.
- Name the view in the answer: "manager's knowledge" or "full save data".

## Finish

The answer names the game date, the data view, coverage and material unknowns.
