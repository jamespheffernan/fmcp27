"""Standalone read-only registration for the checked international-duty gate."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .live_international_duty import get_player_international_duty


def register_international_duty_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_player_international_duty(
        session_id: str,
        player_refs: Annotated[list[Annotated[str, Field(min_length=1)]],
                               Field(min_length=1, max_length=100,
                                     json_schema_extra={'uniqueItems': True})],
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
    ) -> dict[str, Any]:
        """Read the current native national-assignment/travel gate for 1–100 distinct existing player_refs on the selected active HUMAN coach's native TEAM roster. Obtain refs from fm_get_managed_squad and coach_name from fm_get_save. Actual and combined players retain checked identity/name, true/false/unavailable gate, native reason and NATIONAL_TEAM+B8 native_estimated_return when supported. Roster loans whose current PLAYER club TEAM differs stay outside_scope with null gate/date; compact virtual rows stay unsupported without generation. A native gate/reason/estimated date is not complete match eligibility, physical whereabouts, a guaranteed return, or whole-club coverage. All consumed bytes and process/build/world/save/date/coach/roster/reference context are rechecked; reads are non-atomic. No profile/attribute expansion, native game calls, writes, UI or saved-file fallback."""
        return get_player_international_duty(bridge, session_id, player_refs, coach_name)
