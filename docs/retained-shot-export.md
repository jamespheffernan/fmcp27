# Optional normalized shot-map export

The normal live export command with `--include-shot-map` writes optional schema2.
Schema1 remains the default and has no shot tables. Schema2 revision2 is an
additive extension: all existing `shots` and `shot_map_coverage` columns keep
both their values and ordinals. Metadata `shot_map_schema_revision` identifies
the optional-table revision independently of the main `schema_version`.

New `shots` columns preserve supplied event ID/category, body part/header and
state, exclusive terminal outcome and state, official geographic bin/label/group
and state, and the native attacked-goal direction. `shot_attempt_analysis` joins
these fields to fixture names/date/competition and the side's source state.
`shot_map_coverage` appends the source pitch half-extents in unverified native units.

`shot_field_coverage` records each fixture side's location/body-part/outcome
coverage separately. `complete` means every attempt has a known classification;
`partial` gives known/unknown attempt counts; `unclassified` means the supplied
source explicitly could not classify those attempts. `not_captured` distinguishes
missing source fields. `unavailable_source` keeps both counts NULL. For a true
zero-shot side, complete zero field counts require an explicit corresponding
capture policy; an empty legacy packet cannot establish feature availability.

Legacy packets are never retrospectively decoded or enriched by this writer.
Missing fields stay NULL even when an old native category/type is present.
Existing files are refused by the normal atomic export publication. Historical
captured sources keep their original bytes and hashes, and need separate source
registration to expose a newly captured file.

Own-goal markers remain separate from attempts. Penalty selection is independent
of body part and terminal outcome. A penalty can have unknown body part. Woodwork
means the exclusive retained end state, not every intermediate woodwork contact.
Location bin12 includes native boundary fallthrough; `outside_area` only covers
bins6–11. Coordinate units, metric distance and human left/right viewpoint remain
unavailable. See `retained-shot-location.md` for the location proof and limits.

Example current-career capture (new output path required):

```sh
.venv/bin/python -m fm_live_mcp.export_live_matches \
  --team-id 713 --date-from 2030-10-26 --date-to 2030-10-29 \
  --include-shot-map --output /absolute/new/southampton.sqlite
```

Query classified attempts, retaining their source coverage:

```sql
SELECT date,home_team,away_team,side_index,body_part,is_header,outcome,
       official_location,location_group,expected_goals,shot_source_state
FROM shot_attempt_analysis
ORDER BY date,side_index,record_index;
```

## Separate source-observed candidates

Add `--include-source-observed-shots` explicitly together with
`--include-shot-map` to retain count/actor-verified candidates which failed the
strict aggregate xG gate. The optional schema revision is then3. No observed row
is inserted into `shots`; its strict side remains unavailable with NULL counts.

`source_observed_shots` stores original ordinals, event/actor identity, native
coordinates, classifications, and `native_expected_goals` (there is deliberately
no `expected_goals` column). Every row carries
`verification_scope=source_observed_counts_actors_verified_xg_unreconciled`, plus
team/player/non-penalty xG ULP diagnostics. These are observed native values;
strict xG totals, tolerance, rankings and verified-shot coverage remain unchanged.

`source_observed_shot_coverage` preserves independent complete-player count
closure, zero-shot player coverage, original mismatch diagnostics, and explicit
false promotion/tolerance-widening flags. `source_observed_field_coverage`
separately describes known/unknown location/body/outcome values. Strictly
available sides need no additional candidate collection; unavailable candidate
verification keeps NULL counts and no candidate rows. Source-observed rows are
never a fallback that fills missing rows in strict shot analysis.
