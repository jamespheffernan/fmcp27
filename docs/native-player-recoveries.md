# Possession-win comparison through ordinary match queries

`possession_won`, `possession_lost` and `pressures_completed` are native individual stored counters. Live retained-player captures include them with per-field provenance; `fm_get_match_data_columns` exposes their exact labels and limits without attaching to the game. Both `fm_query_match_scope` and `fm_query_match_data` can project the fields from `retained_players`. SQLite exports retain nullable INTEGER columns and expose them in `player_match_analysis`.

Example ordinary prompt:

> Across our retained Premier League games through 28 October, which Newcastle midfielder has won possession most often in total and per 90? Require at least 270 minutes for the rate comparison, show the minutes, and tell me whether that alone supports pressing more.

The caller should resolve the requested date/team/competition scope, request canonical identity/name, minutes and the three counters, and combine rows by canonical identity. Determine midfielder eligibility from a separately observed CM/DM position rating of at least 16; identify the date of that position observation. Calculate per-90 rates from summed counts and summed minutes, using unrounded values for ordering and ties. Do not make a one-minute sample the rate winner. Preserve missing counters and minutes as unknown rather than zero.

The frozen nine-game control in `tests/fixtures/newcastle_recoveries_nine_game.json` contains 180 Newcastle retained rows and nine source-frame hashes. It reproduces:

- Shea Charles leads total possession wins: 73 in 720 minutes, 9.125 per 90.
- Chema Andrés leads the rate among candidates with at least 270 minutes: 35 in 285, exactly 210/19 per 90 (about 11.05).
- Lewis Miley (24 minutes) and Giovanni Fabbian (104) do not meet that rate threshold.

The position observation is from 2 November; the retained game sample ends on 28 October. These minutes and events cover every played role. Charles can also play centre back, so these are not proved midfield-only recoveries.

`PressuresCompleted` is the official property label. It is not an established pressure-regain count. The attempted-pressure field has no verified supported individual binding, so no pressure-success percentage is available. Do not add tackles, interceptions or completed pressures to possession wins as if they were distinct additional recoveries. The data do not attribute events to a location, pressing instruction or counterfactual tactical change; these counts alone do not justify increasing pressing intensity.

Zero counters in an observed retained row remain zero. A row without captured recovery fields remains NULL with `action_source_state='not_captured'`; it is not a zero-recovery match. Existing captured databases need an explicitly authorized replay before their stored schema gains these columns. The query-schema change does not silently modify older user datasets.
