from typing import Annotated, Any
from pydantic import Field
from mcp.types import ToolAnnotations
from .retained_pass_periods import report


def register_retained_pass_period_tools(mcp,bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,openWorldHint=False))
    def fm_report_retained_pass_network_by_period(
        session_id:str,
        fixture_ref:Annotated[str,Field(min_length=1,max_length=128)],
    )->dict[str,Any]:
        """Compare who combined after halftime in one exact retained result. Uses host-captured verified native period stops, a previously captured witness for event IDs, actors/recipients, categories, native clocks and the decoder selection mask0x8, canonical historical actors and every individual full-fixture attempted/completed counter. Returns directed and two-way pairs, sent/received counts, period completed-pass denominators and pair shares for both sides. Strict full-flags/raw-source continuity is reported separately and is never relabelled if unconsumed flags change. The report-specific witness does not certify other native flags, coordinates or annotations. Missing or changed consumed fields stay unknown; a retained query never creates its own historical witness. Boundary ties/crossings remain unassigned; no caller-provided half clocks, 45-minute inference or saved fallback. Pair share is not pair completion rate; no independent period aggregate oracle, routes, pressing or tactical-cause claim. Read-only game access; may finalize local host period linkage."""
        return report(bridge,session_id,fixture_ref)
