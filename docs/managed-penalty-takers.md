# Managed penalty priorities

`fm_get_managed_penalty_takers(session_id, coach_name=None)` reads the current managed-team stored penalty priority list. It follows the checked active HUMAN and team relationship into the tactics manager's owner container and native TEAM-index tree. The ordered entries are native PERSON references, resolved through the same live canonical PERSON table. Current-club and loan links are returned separately from priority membership.

The official frontend properties `SetPiecePenaltyTakersList` and `PrimaryPenaltyTaker` supply the named semantic bridge. The native `HUMAN_NON_PLAYER_MANAGER_remove_penalty_takers_no_longer_at_club` route traverses the managed payload's ordered vector. The reader pins the installed native source spans and uses the existing build/save/type/owner checks; it never invokes those functions.

`priority` starts at1 and `stored_slot_index` starts at0. Empty vectors remain available empty lists. Native null references, duplicates and unresolved PERSON references retain their slots. A player on loan is not silently filtered out. An unavailable manager, owner or team source differs from an empty assigned list.

The result explicitly leaves pending working-edit penalty overrides unknown. The first stored priority is not a confirmed final match taker, match eligibility decision or prediction of a shootout. Corners and free-kick taker orders remain unsupported. Compare the names with the independent `fm_get_managed_team_sheet` response by PERSON database index and both native identity words; do not infer selection from list membership or attribute rankings.
