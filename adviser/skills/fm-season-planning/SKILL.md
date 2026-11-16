---
name: fm-season-planning
description: Plan a dated run of fixtures across competitions. Use for fixture congestion, rotation windows, competition priorities, registration for a competition, or verifying stage and standings context.
---

# Season and competition planning

## Define the window and team

Use the user's horizon in calendar dates from today's game date (`(SELECT game_date FROM _snapshot)`); "the next six weeks" is 42 days. The first team is `(SELECT team_idx FROM _managed)`; reserves and youth are other teams of the same club. Keep the user's competition priorities; without them, a provisional objective (keep role cover through the busiest stretch) is judgement and labelled as such.

## The fixtures

`fixture_view` holds the seasons in memory with names (worked statement 21 in `fm-db`): date, competition, home and away team, score once played. Filter by your `team_idx` and the window; `home_goals IS NULL` is still to be played. `fm_get_calendar` gives the same next fixtures with kick-off times. Older seasons are in `fixture_history_view` (its first use takes minutes; avoid it for planning).

A future fixture is the game's current schedule, not a promise: cup ties beyond the next round are not generated until the draw.

## Competition context

- League position and the gap above and below: `standing_view` (worked statement 20) or `fm_get_league_table` for the screen's table.
- Past winners and your own past finishes, for setting a target: `competition_history` and `club_league_history` (worked statement 11).
- The board's expectation for each competition: `fm_get_club_vision_progress`.

## Registration

Before planning minutes in a competition with a registration rule (the Champions League, the Premier League squad of 25), check who can play:

1. `competition_registration` for the first team and the competition (worked statement 9): `registered = 1` is registered; `0` or no row is not. The game stores no reason.
2. `fm_get_ui_screen(screen: "squad_registration", competition: "comp:<idx>")` for the rules (homegrown minimums, age exemptions, as the screen words them), the spaces left and the next deadline or window.

A player who is not registered and not exempt cannot be planned into that competition until the next window: say so, with the date.

## Congestion and rotation windows

Sort the fixtures by date and give the gap in days from the previous one. A gap of three days is three calendar days, not 72 hours of recovery. Mark clusters (three or more matches in eight days) and the matches the user's priorities make lowest. For each cluster name the units most exposed (from `fm-squad-planning`: positions with one accomplished player) and the rotation candidates with their minutes so far (`match_player_stats`), injury state (`player_injury_view`) and condition (`player_view.condition`, own club). Check active playing-time promises (`promise`) before resting or starting someone: a cluster is often the place to keep one.

## Give one priority and a review point

Lead with one priority tied to the dates ("rotate both full-backs for the cup tie; keep the back four for the league match four days later"). Give the dated schedule, the cluster facts, the registration constraint if any, and the rotation plan with its trade-off. Name a review point (after the next named fixture, or before the registration deadline) and what would change the plan: an injury, a cup draw, a registration window. The tools do not pick the team or change the schedule.
