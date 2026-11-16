"""Read-only paged pass attempts from one explicitly selected retained result."""
from typing import Annotated, Any
from mcp.types import ToolAnnotations
from pydantic import Field
from .live_retained_pass_events import capture_retained_pass_attempts


def register_retained_pass_event_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_retained_pass_events(
        session_id: str,
        fixture_ref: Annotated[str, Field(min_length=1, description='One exact live retained RESULT fixture reference; discover it first.')],
        offset: Annotated[int, Field(strict=True, ge=0)] = 0,
        limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 100,
        expected_source_id: Annotated[str | None, Field(min_length=64, max_length=64, description='Use source_id from the first page for every later page.')] = None,
        coach_index: Annotated[int | None, Field(strict=True, ge=0, le=63)] = None,
    ) -> dict[str, Any]:
        """Page canonical named pass attempts/completions from one checked historical retained fixture. Native pass-family categories6..11 exclude unlabelled mask8 events. Every captured player's attempted AND completed counter must reconcile on a side before its rows are returned. Completed category7 recipients are canonical historical roster-slot joins; failed recipient and specific failure reasons remain unknown. field_position locates the official pass-map event with proved attacked-goal direction and explicit analytical equal pitch thirds/central-versus-outer width bins. pass_field_summary uses the complete counter-qualified fixture BEFORE pagination: compare not-completed counts AND attempted-pass denominators/rates by third/channel, preserving unavailable/outside locations separately. Each location is where the pass was played from. field_position.sampled_path_endpoint is where it ended, with its own third, channel and semantics: for a completed pass, where the named recipient took the ball; it is never an intended destination. Units, human left/right, displayed time, phase, pressure and tactical causes are unproved. Native incomplete-category counts per player retain unknown labels. Missing sources and unavailable sides stay unknown; total_count is null unless both sides reconcile. Read source coverage and reuse source_id for later pages. No saved-file fallback, broad scan, game function or game write."""
        return capture_retained_pass_attempts(bridge, session_id, fixture_ref, offset=offset, limit=limit,
                                              expected_source_id=expected_source_id, coach_index=coach_index)
