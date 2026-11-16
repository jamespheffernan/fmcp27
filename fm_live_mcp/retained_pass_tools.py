"""Compact selected-fixture pass-network report; no arbitrary file dispatch."""
from typing import Annotated,Any,Literal
from mcp.types import ToolAnnotations
from pydantic import Field

from .live_retained_passes import capture_retained_pass_networks,summarize_pass_network


def register_retained_pass_tools(mcp,bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
    def fm_report_live_pass_network(
        session_id: str,
        team_native_id: Annotated[int,Field(strict=True,ge=1,le=4294967295,description='Canonical native team ID, not a database index.')],
        fixture_refs: Annotated[list[str],Field(min_length=1,max_length=16,description='Exact1–16 live historical fixture_refs, preferably selected through retained-match discovery. Pass only the intended last two fixtures for a two-match comparison.')],
        minimum_matches: Annotated[int,Field(strict=True,ge=1,le=16,description='Require a positive selected metric in at least this many selected available fixture sources; use1 for a single fixture.')] = 2,
        leaders: Annotated[int,Field(strict=True,ge=1,le=50)] = 10,
        ranking_basis: Literal['counter_reconciled_completed_passes','official_map_count'] = 'counter_reconciled_completed_passes',
        coach_index: Annotated[int|None,Field(strict=True,ge=0,le=63)] = None,
    ) -> dict[str,Any]:
        """Show which named directed player pairs combined repeatedly in selected live retained fixtures. Discover exact refs for the managed team or scouted opponent first; capture only that selection, with no league-wide player scan. Reuses one frame packet and the checked HUMAN-owned retained CBE source. Pass availability uses its own individual-counter oracle; shot checks never substitute for pass-counter checks. Official pass-map counts include a separate unlabelled mask8 subset. Only call the mask8-excluded subset completed passes after every captured individual's official completion counter reconciles; expose both counts and coverage separately. Fixture source_coverage includes each canonical player's official attempted/completed counters; passes_not_completed is their arithmetic difference, never a decoded failed-pass event or receiver. Canonical source actors and related recipients are historical roster-slot joins, never current position guesses. Missing retained sources stay unknown. No pair attempted-pass count, completion rate, route geometry, defensive-third, pressure, phase, assist or tactical-causality claim; no saved-file fallback or game writes."""
        options=dict(minimum_matches=minimum_matches,leaders=leaders,ranking_basis=ranking_basis)
        # Validate all report selectors before any live capture.
        summarize_pass_network({'records':[],'captured_save':None},team_native_id,**options)
        captured=capture_retained_pass_networks(bridge,session_id,fixture_refs,coach_index=coach_index)
        return summarize_pass_network(captured,team_native_id,**options)
