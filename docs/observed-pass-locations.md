# Optional observed-run pass-map query

The existing `fm_list_observed_match_runs` / `fm_query_observed_match_run` API exposes an optional **completed_pass_event_locations** view for explicitly attested captures. No input schema changes, new path/SQL parameters, database writes or game attachment are needed. Base tables and their original nulls remain unchanged.

Discover the source and its exact capture pin first. Request the optional view only when advertised. Use `side_index=1` for Forest in this fixture, then request sender/receiver names or canonical IDs, period, event ID, native clocks and point fields. Continue every next_cursor; select/filter the desired pair in codemode. Both directions can be read from one source capture. The adapter retains the original 200-row/128KiB and pinned paging limits.

Rows include canonical sender/receiver IDs, original stored actor slots, source event ID, start/end native ticks, captured period, native event XY, native attack-direction flag, attack-relative longitudinal coordinate and absolute lateral distance. Equal longitudinal thirds and central/outer width channels are analytical bins. **A point is an official pass-map event point, not a proved ball-release or reception location.** No destination/trajectory, units, human left/right, displayed minute, role, current lineup or tactical effect is inferred.

## Integrity gate

An explicit optional policy pins native decoder version/plugin SHA, terminal document SHA, canonical actor-document SHA, raw event SHA, official match ID and expected completed-event count. Newly registered captures receive no location semantics without such a policy. The current policy attests the already verified Forest terminal source; it does not generalize by filename or club name.

For every open, the immutable registered SQLite fingerprint is checked by the existing source adapter. The projector verifies the embedded terminal raw SHA, native fixture/match/cutoff, finite pitch geometry and all canonical source actors against the stored actor table. Every selected native category7 event excluding mask8 must agree with the complete base event set: event ID, side, sender/receiver original slot and name, start/end clock, period and terminal source. Source intervals must agree with stored periods; an open source interval is clipped at the original capture cutoff. Unknown boundary crossings stay unknown. Any mismatch disables only this optional derivation, with an explicit catalog reason.

The view is a parameterized `SELECT ... FROM json_each(?)` relation. No CREATE, TEMP, ATTACH or writes are used. Private raw documents, memory pointers and derivation rows are withheld from the discovery catalog. Queries return only selected validated fields plus compact derivation provenance.

## Concrete control

The approved database SHA remains8e8a4d436d01525f20730c53b5abeaf67d75f8a762413e6da9ceb090236de873. Its terminal document9ee6e05d... contains the exact event bytesf6e4bfdd... already verified in the185point projection. All1,020completed rows agree: Newcastle508(223first/285second), Forest512(286first/226second). Baas→Enciso28event points fall14defensive/13middle/1attacking and25outer/3central. These bins describe the event points, not where Enciso received the ball. Original database fingerprint/nulls are preserved.

The test suite includes independent portable native bytes, all1,020row paging, canonical source joins, clock/ID/actor/side/period/hash/native-policy tampering, missing policies, selector/cursor guards and base-table continuity. Ordinary installed acceptance follows release activation; source tests are not presented as installation or model acceptance.

## Optional named shot chances

The sibling `named_shot_chances` view independently replays the attested terminal shot source, checks original-roster match/fixture/ownership and earlier native event prefix, and matches every stored shot field before resolving the primary actor. The approved actual source resolves27of27shot takers. The underlying `shots.actor_name` column remains null. Missing actors or names remain null in the derived view; a named shooter is not a proved supplier/assister. This view is separately optional: a pass projection failure does not disable a valid shot projection, or vice versa. Normal source/capture pins and query row/byte/paging limits apply to both.
