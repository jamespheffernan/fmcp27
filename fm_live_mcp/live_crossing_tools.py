"""Typed active-career report tool, with no historical-file dispatch."""
from typing import Annotated, Any, Literal
from mcp.types import ToolAnnotations
from pydantic import Field
from .live_crossing_report import LiveCrossingReports


def register_live_crossing_tools(mcp, bridge):
    reports = LiveCrossingReports()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_report_live_match_crossing(
        session_id: str,
        team_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)],
        date_from: Annotated[str, Field(pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')],
        date_to: Annotated[str, Field(pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')],
        competition_native_id: Annotated[int | None, Field(strict=True, ge=1, le=4294967295)] = None,
        fixture_ref: str | None = None,
        venue: Literal['all', 'home', 'away', 'matchup'] = 'all',
        leaders: Annotated[int, Field(strict=True, ge=1, le=20)] = 10,
        minimum_minutes: Annotated[int, Field(strict=True, ge=0, le=100000)] = 0,
        leader_sort: Literal['attempted', 'completed', 'accuracy'] = 'attempted',
    ) -> dict[str, Any]:
        """Fresh active-save crossing benchmark and named selected-team/opponent suppliers, including separately proved open-play counts. Attach and find the current matchup through live fixture tools first. Supply its fixture_ref and venue=matchup to recheck teams/date/competition and derive the selected team's home/away comparison. Dates are explicit: native season date ranges are not inferred. Enumerates bounded competition result pages and captures totals and canonical players together once; a native reload rejects the report. Missing backing/groups and missing player sides stay explicit. No captured-file, last-save or historical SQLite fallback. No delivery flank, current role, complete-save history or match-completion inference."""
        return reports.report(bridge, session_id, team_native_id, date_from, date_to,
                              competition_native_id, fixture_ref, venue, leaders,
                              minimum_minutes, leader_sort)
