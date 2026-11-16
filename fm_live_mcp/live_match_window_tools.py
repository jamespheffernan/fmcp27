"""A compact two-window report from checked active-career match sources."""
from typing import Annotated, Any, Literal
from mcp.types import ToolAnnotations
from pydantic import Field
from .live_match_window_comparison import LiveMatchWindowComparisons


def register_live_match_window_tools(mcp,bridge):
    comparisons=LiveMatchWindowComparisons()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
    def fm_compare_live_match_windows(
        session_id: str,
        team_native_id: Annotated[int,Field(strict=True,ge=1,le=4294967295)],
        competition_native_id: Annotated[int,Field(strict=True,ge=1,le=4294967295)],
        baseline_from: Annotated[str,Field(pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')],
        baseline_to: Annotated[str,Field(pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')],
        comparison_from: Annotated[str,Field(pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')],
        comparison_to: Annotated[str,Field(pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')],
        player_metric: Literal['shots','shots_on_target','goals','assists','key_passes','open_play_key_passes','chances_created','progressive_passes','passes_attempted','passes_completed']='open_play_key_passes',
        baseline_minimum_minutes: Annotated[int,Field(strict=True,ge=0,le=1000000)]=450,
        comparison_minimum_minutes: Annotated[int,Field(strict=True,ge=0,le=1000000)]=450,
        minimum_team_matches: Annotated[int,Field(strict=True,ge=1,le=512)]=5,
        sort_direction: Literal['increase','decrease']='decrease',
        limit: Annotated[int,Field(strict=True,ge=1,le=100)]=10,
        cursor: str | None=None,
    ) -> dict[str,Any]:
        """Compare team chance creation in two explicit active-career date windows using one pinned union capture. Returns for/against shots,SOT,xG,pooledxG/shot,creation context,per-match changes and returning-player count/per90 deltas with exact ranks. Both periods must meet their separately returned minute thresholds for a player change; sum zero-minute actions before filtering, and only proved unused bench null minutes count as zero. One-window-only, missing metric/minute/identity/backing and small-team samples remain explicit; unknowns never become zero. Returns only same canonical PERSON+historical TEAM ID/index pairs, not a current roster or season join. Overlapping fixtures are reported and captured once. Direction decrease ranks largest reductions first; increase ranks gains. Consume next_cursor with identical selectors for all cutoff ties in fixed100-row pages; no native recapture, five-minute/reload expiry. At most512unionfixtures; explicit windows, no hardcoded club/season, captured-file/disk-save fallback, played-role or causal-tactics claim."""
        return comparisons.compare(bridge,session_id,team_native_id,competition_native_id,baseline_from,baseline_to,comparison_from,comparison_to,
                                   player_metric,baseline_minimum_minutes,comparison_minimum_minutes,minimum_team_matches,sort_direction,limit,cursor)
