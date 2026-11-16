---
name: fm-playing-time-dynamics
description: Review promises, agreed playing time and observed use, and the dressing room, then propose a minutes plan. Use for rotation priorities, playing-time complaints, unhappy players, promises, leaders, hierarchy, social groups or dressing-room questions.
---

# Playing time and dynamics

## Read the commitments first

Before advising on any player's minutes, read what you have promised and what he was promised in his contract:

- `promise` (worked statement 3 in `fm-db`): every active promise with the player, the title ("Fair increase in playing time", "Find loan move for player"), the date made, the deadline, days left and the player's view of progress (`status_text`, as the Promises screen words it). A plan that cuts the minutes of a player with an active playing-time promise breaks it: say so and give the deadline.
- Agreed playing time (squad status: Star Player, Important Player, Regular Starter, Squad Player, ...) is the `squad_status` column of `player_view` and `contract_view` for your club's players: one statement for the whole squad. `fm_get_player_status` (`player: "person:<idx>"`) adds the player's own view of his playing time, one player per call.

## Measure the use

Minutes and starts come from SQL: the last five matches per player (worked statement 15), or this season by competition from `player_season_stats` (`starting_appearances`, `minutes`). State the window. A promise of "a fair increase" has no number: compare his starts since the promise was made (`match.date >= made_on`) with his starts before it.

## Read how they feel

- Playing-time happiness and the other complaints, as the game words them: `player_happiness_reason` naming the squad (worked statement 4). `level` is the playing-time happiness (-100 alienated, 0 neutral, 100 delighted); `happiness_level` the overall happiness. Quote the sentence.
- Who is unhappy across the whole club in one call: `fm_get_squad_happiness` (all teams; reasons for the unhappy ones). Say how many players were covered and whether reserves and youth were included.
- Open concerns: `player_concern` with `ongoing = 1` (dates; the reason is a code, so quote the happiness lines for the words).

Morale alone is not happiness, and a playing-time concern is not overall unhappiness unless the overall level says so.

## The dressing room

- Leaders and influence: `squad_hierarchy` for the first team (worked statement 5): tiers `team_leader`, `highly_influential`, `influential`, `other`, with the stored influence. `key_personnel` marks the screen's key personnel. If `stale = 1` the game will recompute the list when the screen opens: say the order may change.
- Social groups: `social_group`: `core`, `secondary_1`, `secondary_2` and `other`, the players in no group (new arrivals, or players who do not fit). `reasons` is the screen's sentence for each group; `dressing_room_atmosphere` the team's atmosphere level.

An isolated player is one in `other`, especially with low influence and a playing-time complaint. A leader's unhappiness spreads: check the team leaders' happiness lines before anyone else's.

## Turn it into a minutes plan

Load `fm-season-planning` for the fixture windows and `fm-squad-planning` for role cover. When the way out is a changed agreement, a loan or a sale, load `fm-contracts-loans`; when the question is who on the staff handles the conversation or the player's development, load `fm-staff-planning`. For each player in question give: his promise (if any) and deadline, his agreed status, his minutes in the window, his happiness line, and the opportunity you propose (a named fixture, a role, a substitute appearance) with whose minutes it costs. When two players need the same minutes, name the conflict and who yields. When a promise cannot be kept, say so plainly and give the least damaging option (a loan, a frank conversation, a transfer). The tools do not change playing time, hold conversations or make promises; the user does that in the game.
