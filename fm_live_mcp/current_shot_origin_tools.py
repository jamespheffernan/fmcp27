from typing import Any
from mcp.types import ToolAnnotations

from .current_shot_origins import current_shot_origins


def register_current_shot_origin_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
    def fm_get_current_match_shot_origins(session_id: str) -> dict[str, Any]:
        """Explain where current-match chances originated through one checked playback cursor. Returns both teams' shot and on-target counts by thirteen official native origin zones and inside/outside-area groups. Uses the same checked active shot/event source and integer reconciliation as fm_get_current_match, with own-goal markers excluded. Group xG remains null when its side fails strict xG reconciliation; verified count-zero is distinct from unknown source. Native fallback bin12 includes boundary gaps and is not definitely outside the area. Native Left/Right labels do not establish the viewer's left/right, metres, shot angle or finding space. Only source-verified period intervals receive half breakdowns. No future attempts, full-time totals, historical substitute or screen access. Returns unavailable if the active client/playback source is absent. The shared current-match read can persist bounded private host period observations; game access remains read-only."""
        return current_shot_origins(bridge, session_id)
