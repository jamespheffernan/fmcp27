# Live national squads

`fm_find_national_teams` discovers named nations' canonical national-team
containers and their ordered teams. Search `name` (nation short name or
abbreviation), exact `nation_native_id`, or enumerate without either. Read every
`next_cursor` with identical filters and `record_budget` (1–16), even when a page
has no matches. Cursors bind session, process, career/load identity, table root
and selectors. Every page rechecks its consumed native bytes.

Pass a returned `team_ref` to `fm_get_team_squad` with
`profile_policy="available"` for exact PERSON identities, names and ordered
stored membership. Optional club/profile/health reads retain their existing
semantics. Native type labels use the already checked editor `tmty` enum;
unmapped types and gender stay unknown. Do not infer gender from player names
or container order. A zero roster is a checked empty vector, not a missing read.

The container's listed membership and a team's canonical owner are distinct:
Great Britain lists an England-owned U23 team in the live control. Both are
preserved. Membership is not nationality, match XI, eligibility, a call-up date,
international-duty absence or medical clearance. No disk-save fallback is used.

Fresh live controls scanned all502 container slots in32 pages for England and
returned14teams/177ordered roster entries in9.00seconds, including known-empty
teams. Every roster count matched discovery and every individual roster had
unique native PERSON IDs. First-team controls include Aaron Ramsdale and Trent
Alexander-Arnold in one container, Hannah Hampton and Naomi Layzell in another;
this is an identity control, not a gender decoder. Great Britain's six stored
team entries were independently checked, including cross-owner membership.

Receipts: isolated research worktree
`evidence/batches/live-national-squads-161/verified.json`,
`registered-route-control.json`, `container-controls.json`, `roster-controls.json`.
