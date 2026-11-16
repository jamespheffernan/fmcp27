"""Retained possession summaries; read-only game access, persistent host linkage."""
from typing import Annotated, Any
from mcp.types import ToolAnnotations
from pydantic import Field
from .retained_possession_periods import report


def register_retained_possession_period_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
    def fm_report_retained_possession_by_period(
        session_id: str,
        fixture_ref: Annotated[str, Field(min_length=1, max_length=128)],
        team_native_id: Annotated[int | None, Field(strict=True, gt=0)] = None,
        person_native_id: Annotated[int | None, Field(strict=True, gt=0)] = None,
    ) -> dict[str, Any]:
        """Compare possession won/lost by player in independently witnessed halves of one exact retained result. Requires canonical historical actors, complete per-side whole-fixture player counter closure including zeros, host-observed native period stops and a separate possession-event ID/actor/category/clock witness. Never borrows pass-only continuity or guesses 45-minute boundaries. Returns per-period side totals and all original roster actors, with boundary-crossing/tied/unobserved events counted separately. Optional team/player selectors leave full-side totals explicit. Missing witnesses or counter closure stay unavailable. Event counts are not pressure completions, paired opposing turnovers, transition locations, current on-pitch membership, minutes or tactical causation. Can persist finalized local host period-link metadata after normal epoch and existing-pin checks. Creates no new native observation. Game access stays read-only: no game-memory/save writes, game calls, UI, refresh or generation; no disk-save fallback."""
        return report(bridge, session_id, fixture_ref, team_native_id=team_native_id, person_native_id=person_native_id)
