---
name: fm-db
description: Worked SQL for the save snapshot beyond the schema card - histories, rating components and momentum, promises, hierarchy and social groups, registration, agent demands, finance breakdowns, attribute progress, contracts, season statistics and percentiles, tables, offers, injuries, fixtures, and the manager view with stars, ranges and public wages.
---

# SQL over the save snapshot

The schema card in the prompt lists the tables by question, their main columns and the joins. This guide adds the rules and a worked statement for each kind of question. Every statement below ran through `fm_db_query` on the Newcastle career on 13 December 2030 in the view it names (full unless the line above it says `view: "manager"`).

## Rules

- One statement per call. Name the columns you need and `LIMIT` the rows (25 or fewer for an answer); never `SELECT *`.
- Columns marked `*` on the card are computed by the game when a statement names them. Filter and sort on stored columns first (club, team, age, attributes, `pos_*`, stored statistics) and name computed columns only for the rows you return. `position` over the whole save takes a minute the first time; over one club or a list of `idx` it takes seconds.
- Tables marked "name the rows" are computed for the people, club, competition or award the statement names: `WHERE person_idx = 123`, `person_idx IN (...)`, or `person_idx IN (SELECT idx FROM player_view WHERE team_idx = ...)`. A statement that would reach more than 400 people is refused with an error that says so: narrow it, never retry it unchanged.
- Pass user text through `params` (`WHERE name LIKE ?`), never pasted into the SQL.
- Check `truncated`. When true the answer covers only the returned rows: narrow the filter before calling a list complete.
- Names repeat. Resolve a person, club or competition to its `idx` once and use the `idx`.
- Quote `snapshot.game_date`. Each statement checks the stored rows against the game first and re-reads what changed; `fm_db_refresh` is not needed. The first statement that names a table builds it (a second to about 25 seconds for the match tables); later ones take well under a second.
- A NULL is unknown, never zero.
- Money is in pounds; `wage`, `weekly_wage`, `wage_min`/`wage_max` are pounds a week.
- "This season" in `player_season_stats` is the latest `season` of your own team's rows: `season = (SELECT MAX(season) FROM player_season_stats WHERE team_idx = (SELECT team_idx FROM _managed))`.
- Aggregate in SQL: `COUNT`, `SUM`, `AVG`, `ROUND(x * 90.0 / minutes, 2)` for per 90, `PERCENT_RANK() OVER (...)` for percentiles. Return the deciding rows, not the population.

## The manager's knowledge

In the manager view (`view: "manager"`) every table is read as `m_<name>` (`m_player_view`, `m_contract_view`, `m_fixture_view`); a bare name is refused and the error names the `m_` view. `_managed` is readable there under its own name; your own players are also `own_club = 1`. The policy follows what the game shows a manager:

- Public for every club: fixtures, results, tables, match and season statistics, histories, injuries, names, ages, clubs, and a player's wage and contract expiry (the game shows both on his profile).
- Your club only: contract clauses and `clause_count`, squad status, a club's balance, budgets and finance tables, transfer offers, registration, scouting assignments, promises. Another club's rows read NULL or are absent.
- Masked: other clubs' players' attributes are `<attr>` (exact, else NULL) with `<attr>_min`/`<attr>_max` (range, NULL unknown); ability is stars, `current_ability_stars_min`/`_max` and `potential_ability_stars_min`/`_max`, 0.5 to 5 in half steps.
- Withheld: other clubs' players' transfer values, `pos_*` ratings, traits, condition and ability numbers.

`m_scouted_player_view` holds the players the club has scouted, `m_player_view` every player it knows of; knowledge columns are `scouted`, `own_club`, `exact_n`, `range_n`, `unknown_n` (of the 47 visible attributes), `knowledge_date`.

| The user means | Filter |
| --- | --- |
| at least 15 for sure | `tackling_min >= 15` |
| could be 15 or more | `tackling_max >= 15` |
| known exactly | `tackling IS NOT NULL` |
| 3 stars or better for sure | `current_ability_stars_min >= 3` |
| could have 4-star potential | `potential_ability_stars_max >= 4` |
| earns under 40,000 a week (public) | `wage < 40000` |

The manager's knowledge is computed for the rows a statement reads. A statement over most of the save can come back with `status: "building"` and no rows: call `fm_db_query` again with the same SQL after about 30 seconds (once or twice); narrowing the statement (age, `scouted = 1`, a club) avoids it.

Report ranges as ranges ("13-16") and ability as stars ("3.5 stars", "3-4.5 stars"), never as a number or a midpoint. Rank by the sure bound and say how many attributes are unknown. A filter the manager cannot apply (another club's transfer value, a position rating) is not applied from full data: say it is hidden and use what is known.

## Worked statements: the new questions

1. Why did a player get that rating? The components of the match loaded in the game (`fm_get_match(team: "Newcastle United")` names it: here West Ham 2-1 Newcastle on 13 December). The base rating is the model's starting point; each term adds or takes away points.

```sql
SELECT p.name, r.stored_rating, r.label, r.count, ROUND(r.contribution, 2) AS points
FROM match_rating_component r JOIN player_view p ON p.idx = r.person_idx
WHERE r.person_idx = (SELECT idx FROM player_view WHERE name LIKE ? AND team_idx = (SELECT team_idx FROM _managed))
ORDER BY ABS(r.contribution) DESC LIMIT 12
```
<!-- params: ["%Neves%"] -->

When no match is loaded the table is empty and `fm_get_match` says `rating_breakdown: not stored`: explain from `match_player_stats` (passes, tackles, shots, xG, minutes) and say the components are gone.

2. How the loaded match swung: momentum per five minutes (positive favours the home side).

```sql
SELECT end_minute, ROUND(home_value, 2) AS home_momentum FROM match_momentum ORDER BY segment
```

3. Promises I have made and which are at risk. `days_left` is days to the deadline; `status_text` is the player's view as the Promises screen words it.

```sql
SELECT p.name, pr.title, pr.made_on, pr.deadline, pr.days_left, pr.status_text
FROM promise pr JOIN player_view p ON p.idx = pr.player_idx
WHERE pr.list = 'active'
ORDER BY pr.days_left
```

A promise of playing time is at risk when the player's recent minutes do not match it: check his last five matches (worked statement 15) and his playing-time line (statement 4); "Pleased" in `status_text` means on track.

4. Who is unhappy with his playing time, and why, as the screen words it. `level` is the playing-time happiness (-100 alienated to 100 delighted) and `happiness_level` the overall happiness on the same scale; `sign = 'negative'` rows are the other complaints.

```sql
SELECT p.name, h.sign, h.level, h.happiness_level, h.reason_text
FROM player_happiness_reason h JOIN player_view p ON p.idx = h.person_idx
WHERE h.person_idx IN (SELECT idx FROM player_view WHERE team_idx = (SELECT team_idx FROM _managed))
  AND (h.sign = 'negative' OR (h.sign = 'playing_time' AND h.level < 0))
ORDER BY h.level LIMIT 25
```

Open concerns are `player_concern` rows with `ongoing = 1` (the reason is a code: quote the happiness lines for the words).

5. The leaders of my dressing room and who is isolated: the hierarchy tiers (`team_leader`, `highly_influential`, `influential`, `other`) and the social groups (`core`, `secondary_1`, `secondary_2`, `other` = in no group).

```sql
SELECT p.name, p.age, h.tier, h.influence, g.group_name
FROM squad_hierarchy h JOIN player_view p ON p.idx = h.person_idx
LEFT JOIN social_group g ON g.person_idx = h.person_idx AND g.team_idx = h.team_idx
WHERE h.team_idx = (SELECT team_idx FROM _managed)
ORDER BY h.influence DESC
```

`social_group.reasons` gives the screen's sentence for each group; `dressing_room_atmosphere` is the team's atmosphere level.

6. A player's career season by season, club competitions together (`scope_name` also splits League, Cup, Continental, International).

```sql
SELECT s.year, t.name AS club, s.appearances, s.goals, s.assists, ROUND(s.average_rating, 2) AS rating
FROM person_season_statistics s JOIN team t ON t.idx = s.team_idx
WHERE s.person_idx = (SELECT idx FROM player_view WHERE name LIKE ? AND team_idx = (SELECT team_idx FROM _managed))
  AND s.scope_name = 'Overall (Club)' AND s.appearances > 0
ORDER BY s.year
```
<!-- params: ["%Gordon%"] -->

`person_playing_history` has the moves (fee, loan, joined and left dates); `person_career_totals` the totals and the most significant milestone; `player_injury_history` past injuries with days out.

7. What a scouted target would want to sign for us. One row per line of the agent's answer; the fee and wage ranges repeat on every line. Interest "No interest" leaves the ranges NULL. `view: "manager"`

```sql
SELECT a.person_idx, p.name, a.interest, a.fee_min, a.fee_max, a.wage_min, a.wage_max, a.contract_end, a.line
FROM m_agent_demand a JOIN m_player_view p ON p.idx = a.person_idx
WHERE a.person_idx = (SELECT idx FROM m_scouted_player_view WHERE name LIKE ?)
```
<!-- params: ["%Bergvall%"] -->

Then test it against the budget (own club):

```sql
SELECT transfer_budget_finance_Cntb AS transfer_budget, remaining_wage_budget_weekly, wage_budget_weekly
FROM club_finance WHERE idx = (SELECT club_idx FROM _managed)
```

Quote both ends of each range; the deal is affordable for sure only when the top of the fee range fits the transfer budget and the top of the wage range fits the remaining weekly wage budget.

8. This season's income and expenditure by category (own club; also `this_month`, `last_month`, `last_season`).

```sql
SELECT direction, category, amount, percent_of_operating_total
FROM club_finance_breakdown WHERE period = 'this_season' AND amount <> 0
ORDER BY direction DESC, amount DESC
```

Balance month by month: `club_finance_month` with `series = 'balance'`; sponsorship deals: `club_sponsorship`; loans: `club_debt_loan`.

9. Who in my first team is not registered for the Champions League. A player with no registration marker has no row, so start from the squad. The rules, the deadline and the age exemption are on `fm_get_ui_screen(screen: "squad_registration", competition: "comp:637")`.

```sql
SELECT p.name, p.age, p.position, r.registered
FROM player_view p
LEFT JOIN competition_registration r ON r.person_idx = p.idx AND r.team_idx = p.team_idx
  AND r.competition_idx = (SELECT idx FROM competition_view WHERE name = 'UEFA Champions League')
WHERE p.team_idx = (SELECT team_idx FROM _managed) AND COALESCE(r.registered, 0) = 0
ORDER BY p.age
```

10. Which of my young players improved most in the last six months, across the first team, reserves and youth: the sum of the 1-20 attributes now against six months earlier, from the monthly snapshots (1-100 scale, so divide by 5).

```sql
WITH h AS (
  SELECT person_idx, month, (SELECT SUM(value) FROM json_each(attributes)) / 5.0 AS total
  FROM player_attribute_history
  WHERE person_idx IN (SELECT idx FROM player_view WHERE club_idx = (SELECT club_idx FROM _managed) AND age <= 21)),
cur AS (SELECT person_idx, total FROM h WHERE month = (SELECT MAX(month) FROM h)),
past AS (SELECT person_idx, total FROM h WHERE month = strftime('%Y-%m', (SELECT game_date FROM _snapshot), '-6 months'))
SELECT p.name, p.age, t.name AS team, ROUND(cur.total - past.total, 1) AS gain
FROM cur JOIN past USING (person_idx) JOIN player_view p ON p.idx = cur.person_idx JOIN team t ON t.idx = p.team_idx
ORDER BY gain DESC LIMIT 10
```

One attribute as the screen shows it: `ROUND(json_extract(attributes, '$.passing') / 5.0)`; quote whole numbers, not the fractions the division leaves. Players with fewer than six months of snapshots (new signings) drop out of the join: say so.

11. Who won the league in each of the last five seasons.

```sql
SELECT h.season, t1.name AS champions, t2.name AS runners_up
FROM competition_history h
JOIN team t1 ON t1.idx = h.first_team_idx LEFT JOIN team t2 ON t2.idx = h.second_team_idx
WHERE h.competition_idx = (SELECT idx FROM competition_view WHERE name = 'Premier League')
ORDER BY h.entry LIMIT 5
```

A club's own finishes: `club_league_history` (`season`, `competition_name`, `position`, `teams`); award winners: `award_history` naming the award (`award.name`).

12. Another club's highest earners (wages are public). `view: "manager"`

```sql
SELECT name, age, position, wage, contract_expires
FROM m_player_view WHERE club_idx = (SELECT idx FROM m_club_view WHERE name = 'Arsenal')
ORDER BY wage DESC LIMIT 5
```

13. When a rival player's contract runs out. `view: "manager"`

```sql
SELECT person_name, club_name, weekly_wage, expires_date, clause_count
FROM m_contract_view WHERE person_idx = (SELECT idx FROM m_player_view WHERE name LIKE ?) AND role = 'main'
```
<!-- params: ["%Saka%"] -->

`clause_count` is NULL for another club's player: his clauses (release clause included) are not shown to the manager.

## Worked statements: squad, statistics, matches, money

14. Contracts expiring within two years, first-team players, with wage and age (for 12 months write `'+12 months'`; an empty result means none expire in the window).

```sql
SELECT p.name, p.age, p.position, c.weekly_wage, c.expires_date
FROM contract_view c JOIN player_view p ON p.idx = c.person_idx
WHERE c.club_idx = (SELECT club_idx FROM _managed) AND p.team_idx = (SELECT team_idx FROM _managed)
  AND c.role = 'main'
  AND date(c.expires_date) BETWEEN (SELECT game_date FROM _snapshot) AND date((SELECT game_date FROM _snapshot), '+24 months')
ORDER BY c.expires_date
```

15. Average rating and minutes over my last five matches, per player (form, and a check on playing-time promises).

```sql
WITH last5 AS (
  SELECT idx FROM match WHERE (SELECT team_idx FROM _managed) IN (home_team_idx, away_team_idx)
  ORDER BY date DESC LIMIT 5)
SELECT p.name, COUNT(*) AS games, SUM(s.started) AS starts, SUM(s.minutes) AS minutes, ROUND(AVG(s.rating), 2) AS avg_rating
FROM match_player_stats s JOIN player_view p ON p.idx = s.person_idx
WHERE s.match_idx IN (SELECT idx FROM last5) AND s.team_idx = (SELECT team_idx FROM _managed) AND s.minutes > 0
GROUP BY p.idx ORDER BY avg_rating DESC
```

16. Per 90 and league percentile: my players' progressive passes and tackles won per 90 against every Premier League player with 450 minutes or more this season.

```sql
WITH pl AS (
  SELECT s.person_idx, s.team_idx, s.minutes,
         s.progressive_passes * 90.0 / s.minutes AS prog90, s.tackles_won * 90.0 / s.minutes AS tackles90
  FROM player_season_stats s JOIN competition_view c ON c.idx = s.competition_idx
  WHERE c.name = 'Premier League' AND s.season = (SELECT MAX(season) FROM player_season_stats WHERE team_idx = (SELECT team_idx FROM _managed)) AND s.minutes >= 450),
ranked AS (
  SELECT *, PERCENT_RANK() OVER (ORDER BY prog90) AS prog_pct, PERCENT_RANK() OVER (ORDER BY tackles90) AS tackles_pct FROM pl)
SELECT p.name, p.position, r.minutes, ROUND(r.prog90, 2) AS prog90, ROUND(100 * r.prog_pct) AS prog_pctile,
       ROUND(r.tackles90, 2) AS tackles90, ROUND(100 * r.tackles_pct) AS tackles_pctile
FROM ranked r JOIN player_view p ON p.idx = r.person_idx
WHERE r.team_idx = (SELECT team_idx FROM _managed)
ORDER BY r.minutes DESC LIMIT 15
```

17. My last five matches with each starter's rating.

```sql
WITH last5 AS (
  SELECT idx, date, home_team_idx, away_team_idx, home_goals, away_goals FROM match
  WHERE (SELECT team_idx FROM _managed) IN (home_team_idx, away_team_idx)
  ORDER BY date DESC LIMIT 5)
SELECT l.date, ht.name AS home, l.home_goals || '-' || l.away_goals AS score, at.name AS away,
       p.name AS player, s.minutes, s.rating
FROM last5 l
JOIN team ht ON ht.idx = l.home_team_idx JOIN team at ON at.idx = l.away_team_idx
JOIN match_player_stats s ON s.match_idx = l.idx AND s.team_idx = (SELECT team_idx FROM _managed) AND s.started = 1
JOIN player_view p ON p.idx = s.person_idx
ORDER BY l.date DESC, s.rating DESC LIMIT 25
```

18. Goals and xG against: what my team concedes per match this season.

```sql
SELECT COUNT(*) AS matches, SUM(CASE WHEN m.home_team_idx = t.team_idx THEN m.away_goals ELSE m.home_goals END) AS conceded,
       ROUND(SUM(o.expected_goals), 1) AS xg_against, ROUND(AVG(o.shots), 1) AS shots_against_per_match,
       ROUND(AVG(t.possession_pct), 1) AS possession
FROM match_team_stats t
JOIN match_team_stats o ON o.match_idx = t.match_idx AND o.side <> t.side
JOIN match m ON m.idx = t.match_idx
WHERE t.team_idx = (SELECT team_idx FROM _managed) AND m.date >= '2030-07-01'
```

19. Failed passes by outcome in my most recent full-detail match, per player (`match_pass` holds retained full-detail matches only).

```sql
SELECT p.name, COUNT(*) AS passes, SUM(mp.completed) AS completed,
       SUM(mp.outcome = 'intercepted') AS intercepted, SUM(mp.outcome = 'blocked') AS blocked,
       SUM(mp.outcome = 'out_of_play') AS out_of_play
FROM match_pass mp JOIN player_view p ON p.idx = mp.person_idx
WHERE mp.match_idx = (SELECT MAX(match_idx) FROM match_pass WHERE match_idx IN (
        SELECT idx FROM match WHERE (SELECT team_idx FROM _managed) IN (home_team_idx, away_team_idx)))
  AND p.team_idx = (SELECT team_idx FROM _managed)
GROUP BY p.idx ORDER BY passes - completed DESC LIMIT 15
```

20. The league table.

```sql
SELECT position, team_name, played, won, drawn, lost, goals_for, goals_against, goal_difference, points
FROM standing_view
WHERE competition_idx = (SELECT idx FROM competition_view WHERE name = 'Premier League')
ORDER BY position
```

21. My next five fixtures (`fm_get_calendar` gives the same with kick-off times; use SQL to join them to results or form). `fixture_view` holds the seasons in memory; older seasons are in `fixture_history_view`, whose first use takes minutes.

```sql
SELECT date, competition_name, home_team, away_team
FROM fixture_view
WHERE (SELECT team_idx FROM _managed) IN (home_team_idx, away_team_idx)
  AND date >= (SELECT game_date FROM _snapshot) AND home_goals IS NULL
ORDER BY date LIMIT 5
```

22. Transfer and loan offers involving my club (`amount_raw` is the fee in pounds).

```sql
SELECT o.offer_type, o.person_name, o.buying_team, o.selling_team, o.state_code, o.amount_raw
FROM transfer_offer_view o
WHERE (SELECT club_idx FROM _managed) IN (
  (SELECT club_idx FROM team WHERE idx = o.buying_team_idx), (SELECT club_idx FROM team WHERE idx = o.selling_team_idx))
ORDER BY o.idx DESC LIMIT 15
```

23. Injured players at my club.

```sql
SELECT i.person_name, p.position, i.injury, i.started
FROM player_injury_view i JOIN player_view p ON p.idx = i.person_idx
WHERE p.club_idx = (SELECT club_idx FROM _managed)
ORDER BY i.started DESC
```

24. My loanees and how they are doing at their loan clubs this season. A loanee's `club_idx` is the loan club; `contracted_club_idx` is the club that owns him.

```sql
SELECT p.name, p.age, p.position, p.loan_club, SUM(s.appearances) AS apps, SUM(s.minutes) AS minutes,
       SUM(s.goals) AS goals, ROUND(SUM(s.average_rating * s.appearances) / NULLIF(SUM(s.appearances), 0), 2) AS rating
FROM player_view p
LEFT JOIN player_season_stats s ON s.person_idx = p.idx AND s.season = (SELECT MAX(season) FROM player_season_stats WHERE team_idx = (SELECT team_idx FROM _managed))
WHERE p.contracted_club_idx = (SELECT club_idx FROM _managed) AND p.on_loan = 1
GROUP BY p.idx ORDER BY minutes DESC
```

25. Depth: accomplished players (rating 15 or more) per position in my first team.

```sql
SELECT SUM(pos_goalkeeper >= 15) AS gk, SUM(pos_defender_central >= 15) AS dc,
       SUM(pos_defender_left >= 15 OR pos_wing_back_left >= 15) AS dl,
       SUM(pos_defender_right >= 15 OR pos_wing_back_right >= 15) AS dr,
       SUM(pos_defensive_midfielder >= 15) AS dm, SUM(pos_midfielder_central >= 15) AS mc,
       SUM(pos_attacking_midfielder_central >= 15) AS amc, SUM(pos_attacking_midfielder_left >= 15) AS aml,
       SUM(pos_attacking_midfielder_right >= 15) AS amr, SUM(pos_striker >= 15) AS st
FROM player_view WHERE team_idx = (SELECT team_idx FROM _managed)
```

26. Scouting with the manager's knowledge, in two steps. Position is public, so the candidates come from the full view (the first statement that names `position` across the save computes it, about a minute; later ones take seconds), then the manager view ranks them by what is known for sure.

```sql
SELECT idx FROM player_view
WHERE age <= 23 AND club_idx <> (SELECT club_idx FROM _managed) AND position LIKE '%D (%L%'
```

Then rank them on what the club knows: `WHERE idx IN (...)` takes the `idx` values from the first statement, written in as integers (here a subquery stands in so the example runs). Wages are public, so a wage cap filters here. `view: "manager"`

```sql
SELECT idx, name, age, club, wage, current_ability_stars_min, current_ability_stars_max,
       potential_ability_stars_min, potential_ability_stars_max,
       pace_min, pace_max, tackling_min, tackling_max, crossing_min, crossing_max, unknown_n
FROM m_scouted_player_view
WHERE idx IN (SELECT idx FROM m_scouted_player_view WHERE age <= 23 AND own_club = 0) AND wage < 60000
ORDER BY potential_ability_stars_min DESC, COALESCE(tackling_min, 0) + COALESCE(pace_min, 0) DESC
LIMIT 15
```

A manager-view statement that names `position` over the whole save computes it for every player and can return NULL positions after 20 seconds: take positions from the full view as above, or name the club or the `idx` values.

27. What the club knows of one named player. `view: "manager"`

```sql
SELECT idx, name, age, club, wage, contract_expires, scouted, knowledge_date, exact_n, range_n, unknown_n,
       current_ability_stars_min, current_ability_stars_max, potential_ability_stars_min, potential_ability_stars_max,
       passing, passing_min, passing_max, decisions_min, decisions_max, tackling_min, tackling_max
FROM m_player_view WHERE name LIKE ?
```
<!-- params: ["%Hjulmand%"] -->

## When SQL is the wrong tool

Board grades, club vision judgements, inbox text and the screen's league table come from the screen tools. A player's agreed playing time is `squad_status` in `player_view` and `contract_view` for your club's players. Tactics, squad registration rules and training read through `fm_get_ui_screen`; finance projections and FFP, observed or live matches use the specialised tools (find them with `tool_search`; `fm_coverage(search: ...)` says which tool reads a field).
