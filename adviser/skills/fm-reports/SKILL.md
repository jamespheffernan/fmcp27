---
name: fm-reports
description: Present checked findings as an HTML report with fm_report. Use when the user asks for a report, a shortlist, a comparison or a match review, when the answer runs past about 12 rows, or when it needs a pitch.
---

# HTML reports

## Decide to report

Call `fm_report` when the user asks for a report, a shortlist, a comparison or a match review; when the answer has more than about 12 rows; or when shots, positions, passing or a formation carry it. Shorter answers stay in chat. The report presents evidence already gathered and checked through `fm-tools` and the specialist guide; it never substitutes for that work. Complete when every figure you plan to show traces to a tool result you can name in `sources`.

## Put the answer first

- `summary`: the recommendation or answer in 1–3 sentences, naming the player or option and the deciding fact. Use `**bold**` for names; no other markup works.
- `view`: `"manager"` when values come from `fm_get_manager_visible_attributes` (what the manager's scouting shows), `"full"` for stored values. When a report mixes both, choose the view of its decisive evidence and say which figures come from the other in `caveats`.
- `game_date`: the career date the data describes. `sources`: tool names with dates. `caveats`: the unknowns that could change the decision.

Fog of war stays visible: a range cell is `{min, max}`, a known value is a number, an unknown is `null`. Keep ranges as ranges and unknowns as unknowns; the page draws a band, a tick or a dash and explains them.

## Choose sections

Order them: `kpis` (3–5 headline numbers), the visual that decides, the evidence table, then `text` for actions. Each `title` names what the section shows; each `note` says what to take from it.

| Evidence | Section |
| --- | --- |
| Many candidates or players with attributes | `table` (`range` columns in manager view), `highlight_rows` on the pick |
| 2–6 people to act on | `player_cards` with the role's `key_attributes` and a `use_when` |
| 2–4 named options head to head | `comparison`, `better` set per metric |
| One measure ranked | `bar_chart` with `bars` |
| Several measures in different units | index to a common base (100 = average) on one `bar_chart`, or separate charts |
| A requirement and who covers it (minutes per position, budget per area) | `stacked_bar_chart`: one bar per item with its `target`, one segment per contributor, `bands` for quality (best first), `hatched` for a compromise |
| Change over time | `line_chart`, at most 6 series, `emphasis` on the one that matters |
| Two measures per player | `scatter`, `highlight` the candidates |
| Shots, average positions, pass network, zones, formation | `pitch` |
| Deadlines and dated events | `timeline` with `status` on decisions |

## Spec reference

- Values: money in full units (`6500000`, `currency` defaults to £, `unit: "p/w"` for wages); `percent` on 0–100; dates `YYYY-MM-DD`; `rating` and `range` default to the 1–20 scale.
- Table column: `{key, label, type, align?, unit?, decimals?, scale?: {min?, max?, style: "bar" | "heat", better?}}`; rows are objects keyed by column `key`.
- Pitch coordinates: `x` 0–100 from the team's own goal line to the opponent's, `y` 0–100 from the attacking team's left touchline. With two `teams`, the second is mirrored to attack left. Formation slots use FM labels: GK, DL, DCL, DC, DCR, DR, WBL, DML, DM, DMR, WBR, ML, MCL, MC, MCR, MR, AML, AMCL, AMC, AMCR, AMR, STCL, ST, STCR. `links` join `positions[].id`.
- Shot `outcome`: goal, saved, blocked, off_target, post; `xg` 0–1 sets marker size.
- Caps: 30 sections, 400 rows per table, 12,000 table cells per report, 600 scatter points, 150 shots, 30 positions, 200 links, 150 timeline events. Summarise or split rather than truncating silently.

## Read the result

On success, give the user the absolute `path` from the result with one line on what the report shows. Omit `filename` unless the user named one; a dated name is chosen and existing files are never replaced. An invalid spec writes nothing and lists each problem as `sections[2]:table.rows[4].age: expected a finite number`; correct exactly those fields and call again. Complete when the user has the path, or the remaining problem is named.

## Example: shortlist in manager view

```json
{"title": "Young left-back shortlist", "game_date": "2028-01-14", "view": "manager",
 "summary": "Pursue **Tomás Ferreira**: his pace and positioning ranges match Reid's and he fits the £9M budget.",
 "sections": [
  {"type": "table", "title": "Shortlist as the scouts see it",
   "columns": [{"key": "name", "label": "Player"}, {"key": "value", "label": "Est. value", "type": "money"},
               {"key": "pace", "label": "Pace", "type": "range"}, {"key": "passing", "label": "Passing", "type": "range"}],
   "rows": [{"name": "Tomás Ferreira", "value": 6500000, "pace": {"min": 15, "max": 17}, "passing": 13},
            {"name": "Ilyas Benali", "value": 4800000, "pace": {"min": 14, "max": 18}, "passing": null}],
   "highlight_rows": [0]},
  {"type": "player_cards", "players": [{"name": "Tomás Ferreira", "subtitle": "D/WB (L) · 20",
   "key_attributes": ["Pace", "Positioning"],
   "attributes": {"physical": [{"label": "Pace", "value": {"min": 15, "max": 17}}], "mental": [{"label": "Positioning", "value": 13}]},
   "use_when": "You need a starter who can recover the flank this season."}]}],
 "caveats": ["Interest in joining is the 2 Jan 2028 assessment, not present willingness."],
 "sources": ["fm_get_manager_visible_attributes, 14 Jan 2028"]}
```

## Example: post-match review

```json
{"title": "Kingsmere Town 2–1 Harrowgate Rovers", "game_date": "2028-01-08", "view": "full",
 "summary": "A deserved win on chance quality (2.04 xG to 0.92); keep Holm higher after half-time.",
 "sections": [
  {"type": "kpis", "items": [{"label": "Expected goals", "value": 2.04, "decimals": 2, "delta": 1.12, "delta_label": "more than Rovers"},
                             {"label": "Possession", "value": 56, "type": "percent"}]},
  {"type": "pitch", "title": "Shot map", "teams": [{"id": "kin", "name": "Kingsmere"}, {"id": "har", "name": "Rovers"}],
   "shots": [{"team": "kin", "x": 94, "y": 53, "xg": 0.52, "outcome": "goal", "player": "Okafor", "minute": 78},
             {"team": "har", "x": 88, "y": 52, "xg": 0.31, "outcome": "goal", "player": "Brennan", "minute": 52}]},
  {"type": "line_chart", "title": "How the chances built up", "x_label": "Minute", "y_label": "Cumulative xG",
   "reference_lines": [{"axis": "x", "value": 45, "label": "Half-time"}],
   "series": [{"name": "Kingsmere", "points": [{"x": 0, "y": 0}, {"x": 78, "y": 1.75}, {"x": 90, "y": 2.04}]},
              {"name": "Rovers", "points": [{"x": 0, "y": 0}, {"x": 52, "y": 0.59}, {"x": 90, "y": 0.92}]}]}],
 "sources": ["Retained match source, Kingsmere Town v Harrowgate Rovers, 8 Jan 2028"]}
```
