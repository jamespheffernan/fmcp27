"""Read-only stored concern-history registration."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field


def register_player_concern_history_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_player_concern_history(
        session_id: Annotated[str, Field(min_length=1, max_length=128)],
        player_refs: Annotated[list[Annotated[str, Field(min_length=1)]],
                               Field(min_length=1, max_length=100,
                                     json_schema_extra={'uniqueItems': True})],
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
        include_templates: Annotated[bool, Field(strict=True)] = False,
        include_promises: Annotated[bool, Field(strict=True)] = False,
    ) -> dict[str, Any]:
        """Read stored concern history for 1–100 fresh distinct roster refs.

        Obtain refs from fm_get_managed_squad(profile_policy='available'); select
        coach_name from fm_get_save when needed. Regular ACTUAL_PLAYER records
        expose their canonically owned main FULL_CONTRACT history only when its
        CLUB matches the player's current TEAM CLUB. Return every native slot up
        to ten, newest first, retaining repeats, null slots, raw dates/flags and
        unknown reason/category/scalar values. Verified null/empty rings return
        zero/[]; missing or unsupported contract/current-club contexts return
        null records/counts. Combined/virtual rows preserve checked identity with
        unsupported_record_kind. Native unset-end markers are raw predicates,
        never current unhappiness, active promises, satisfaction or fulfilment.

        Default raw history needs no English resource. Set include_templates=true
        for compiled unrendered English first templates; placeholders stay literal
        and context-dependent wording stays null. This option verifies the existing
        pinned resource before/after and fails if unavailable/changed; it never
        creates English. These bounded stored records are not a complete career/
        club history and do not attribute past events to the present manager.
        Roster membership can include loans. Non-atomic reads recheck process/build/
        save/date, selected coach/TEAM/roster, references and all consumed bytes
        after the scope's last callbacks. No native calls, profiles, game writes,
        UI or saved-file fallback.

        Set include_promises=true to add promise_inventory per player: the exact
        native PLAYER-linked promise vector in physical order (repeats retained;
        absent vector, empty vector and unsupported record kind stay distinct).
        Each entry keeps the native kind, category and linked-scalar codes, raw
        start/end dates and the end-marker flag, with both native PERSON links
        reported neutrally (match flags against the selected manager and the
        vector owner; promiser/recipient/subject stay null because the roles are
        context-dependent). Active, ongoing, fulfilled, overdue, targets and
        active_count are not evaluated and stay null. With include_templates=true
        each entry also gets kind_definition: for native kinds 1, 16, 25, 69 and
        120 the compiled unrendered English template; every other kind (for
        example 7) stays unmapped. The vector is not a complete manager-wide or
        club-wide promise population.
        """
        return bridge.get_player_concern_history(session_id, player_refs, coach_name,
                                                  include_templates=include_templates,
                                                  include_promises=include_promises)
