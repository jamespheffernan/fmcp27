# Perceived ability stars

`fm_live_mcp/knowledge_stars.py` returns the current-ability and potential-ability stars the selected manager sees for a player, by running the game's own star methods in the emulator (`fm_live_mcp/fmdb/vm.py`) on copied live memory.

## API

| Function | Returns |
| --- | --- |
| `perceived_ability(bridge_or_session, player_keys, *, coach_name=None)` | Per player: `current` and `potential`, each `{state, min_half_stars, max_half_stars, min_stars, max_stars}`, plus `report_present` |
| `perceived_ability_squad(bridge_or_session, *, coach_name=None)` | The same for the manager's own squad, with names |

Player keys are the `knowledge_bulk` keys: PERSON index, `('ordinal', n)`, `('address', primary)` or a `player_ref`.

`state` is `exact` (one value), `range` (a band, the low-to-high stars the game draws), `unknown` (the game returns 0xFFFF and shows no stars) or `unavailable` (the emulator refused, with `detail`). Half-star units run 1 to 10 (0.5 to 5 stars); the game's internal bins are these plus 10.

No CA or PA number leaves the emulator. The hidden values are read only by the game code running inside it.

## Which game code runs

The game exposes the two answers as methods of `GAME_ACTUAL_PLAYER` (vtable RVA `0x55DEF88`): slot 40, RVA `0x1F8660C` (current) and slot 41, RVA `0x1F86BC0` (potential). Both take the player primary in `x1`, ignore `x0` and return a u16 (low byte = lowest bin, high byte = highest bin). The module checks both slots in the live vtable before it runs them.

Their branches, read from the ARM64 slice:

1. Viewer context `0x1F82DEC`: the current HUMAN and current TEAM from the UI context registry (global vector `0x56D38C0`, looked up by `0x11B5510` under `'Hhum'` and `'Ttea'`), and an observer from `0x12C1578(human)+0xD8`.
2. A stored scout report for this viewer (`0x12D9E40(human, player, 0, 1)`; national teams use `0x12DA3D0`): current = report `+0x3D`, potential = report `+0x30` then `+0x82`.
3. Else an observer from the player's stored-team relation (`0x17800DC`, `0x1096BD0`, slot `0x658`): `0x14EA848` gives the observer-adjusted ability, `0x14EB040` turns it into the current-ability range and `0x14FDFB4` the potential range. The comparison squad is the viewer's team: the baseline is `0xE0327C(team's club, player position, 8, 0)` capped at 35,000, and the fog gate is original H (`0x23871F0`, slot `0x62` / `0x63`, no report argument) for the HUMAN found through that team.
4. Else, when `0x56D2CA0` slot `0x1A0` or `0x20EE608` says the club knows the player, slot 42 (`0x1F86898`) or slot 43 (`0x1F86ED8`): the staff assessments of the current team's club (`0x1F85D2C`, `0x20BA2C8`). This is the own-squad path.
5. Else 0xFFFF.

The UI caller `0xE13B34` named in the earlier evidence is a club-level helper (it is reached from `GAME_CLUB` slot 23 and `GAME_TEAM` slot 8): it picks a club's player through `0xE13D6C` and returns that player's potential stars, with the club's first team as the comparison squad and the club's role-`0xA3` staff (`0x15A5AA8`) as observer. It confirmed the argument order of `0x14EA848`, `0x14EB040` and `0x14FDFB4` but is not what a player profile uses.

## The viewer context

While no screen is being built, the UI context registry is empty, and both methods then return 0xFFFF for everyone. The emulator gets a private registry with two entries, built the way the game stores them: a sicore RECORD typed value with one `'dref'` entry whose int32 is `table << 24 | database index` (`0x111344C` resolves people table 1 to the HUMAN's PERSON and teams table 24 to the managed TEAM). The module checks that `0x1F82DEC` then resolves to the selected coach and his team. This is the one modelling choice: the manager is looking at the game with his managed team selected. Viewing from another team (for example the U21 side) is not modelled.

## Results on the live save (Newcastle, 10 December 2030)

| Set | Players | exact | range | unknown | refused | Time |
| --- | --- | --- | --- | --- | --- | --- |
| Managed squad | 29 | 28 CA / 28 PA | 1 PA (Simon Greenwood 4.0-5.0) | 0 | 0 | 2.1 s |
| Fixed 28 all_actual ordinals | 28 | 1 | 1 | 26 | 0 | 1.3 s |
| Every player in the manager's report vector | 3,193 | 1,518 | 1,675 | 0 | 0 | 13.2 s |

About 2,000 to 4,000 emulated instructions per method call.

A player the manager has no report on and whose club the manager's staff do not cover shows no stars, even when his attributes are partly known (the attribute fog and the star display are separate decisions). The direct chain the earlier evidence replayed (`0x14EB040` with the player's own team as comparison squad) gives higher stars than the game shows, because it compares the player with his own club.

## Verified and not verified

Verified: the methods, their slots and their branches by disassembly; the emulated context resolves to the selected coach and team; every own-squad player and every reported player gets a star value, with no emulator refusal.

Awaiting the owner's check on the screen: that these values are the stars the profile and squad screens draw, the half-star mapping (bin 11 = 0.5 star, bin 20 = 5 stars) and the choice of the managed team as the current team.

Not modelled: viewing with another team selected, and screens that pass their own comparison team to `0x14EB040` (for example the search-filter rules `0x1249D40` / `0x124ED10`).
