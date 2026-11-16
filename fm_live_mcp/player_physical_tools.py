from typing import Any
from mcp.types import ToolAnnotations
from .current_player_physical import current_player_physical


def register_player_physical_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_current_match_player_physical(session_id: str, coach_name: str | None = None) -> dict[str, Any]:
        """Read official in-client player condition and sharpness for the current manager's already selected XI/bench identity intersection. Numbers are released only with a fresh fixture-bound client and observed equal engine/playback frontiers; otherwise all player rows are withheld, never replaced by ahead-of-view simulation values. Native integer percentages and separately derived fractional percentages are explicit. Equal frontiers do not prove exact displayed publication, pixel parity or the active XI. Selection is the existing editable manager sheet, not a played lineup or future entrant list. No condition value establishes injury clearance, safe playing minutes, fatigue, future fitness or match eligibility. For pre-match stored condition/sharpness/fatigue and injury records use fm_get_managed_squad(include_health=true) or fm_get_next_match_squad; use the separate injury-status/medical-return tools for their supported scope. No saved-file fallback, UI, game functions or writes."""
        return current_player_physical(bridge,session_id,coach_name)
