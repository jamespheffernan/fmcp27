"""Public adapter for prospectively witnessed retained lateral width."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .retained_period_width import report


def register_retained_period_width_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_report_retained_lateral_width_by_period(
        session_id: str,
        fixture_ref: Annotated[str, Field(min_length=1, max_length=128)],
        team_native_id: Annotated[int, Field(strict=True, gt=0)],
    ) -> dict[str, Any]:
        """Compare each selected team's original roster players' sample-weighted mean absolute lateral native coordinate across independently witnessed normal halves of one exact retained result. Select a canonical home or away TEAM ID. Requires an existing prospective spatial-only host witness binding complete observed raw XY pairs, actual possession bytes, canonical actors and native terminal period stops; a shot/pass/possession-only period witness cannot authorize width. Returns all-sample, in-possession and out-of-possession means with each player's observed sample denominator, zero-pair and terminal zero-tail coverage; missing streams or unclassified phases remain explicit. Missing or mismatched spatial witnesses return periods=null, never guessed 45-minute halves. Uses native coordinate units; metres, human left/right, elapsed minutes, on-pitch coverage, synchronous participation and tactical causation are unproved. Reads existing host observations only: no host save, linkage, finalization, import or new capture publication. Game access stays read-only, with exact fixture, actor, native-clock and process/save source rechecks; no game-memory/save writes, game calls, UI or disk-save fallback."""
        return report(bridge, session_id, fixture_ref, team_native_id)
