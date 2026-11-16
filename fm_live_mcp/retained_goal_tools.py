from typing import Annotated, Any
from mcp.types import ToolAnnotations
from pydantic import Field

from .retained_goal_combinations import report_goal_combinations


def register_retained_goal_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_report_retained_goal_suppliers(session_id: str,
        fixture_refs: Annotated[list[str], Field(min_length=1,max_length=16)],
        team_native_id: Annotated[int, Field(strict=True,gt=0)],
        scorer_person_id: Annotated[int, Field(strict=True,gt=0)]) -> dict[str, Any]:
        """Find who can be verified to have assisted one scorer across selected results from the running career.
        Discover the exact 1–16 RESULT fixture_refs first. Use the scorer's canonical PERSON ID and participating team.
        Bounds use full individual goal/assist totals. A nonzero minimum is guaranteed under the single-assist/no-self-assist
        model, while a maximum alone is only possible. Report unassisted and unknown separately. The separate official
        GoalscorersString timeline has a second person named Player2. Never use that field alone to assert a credited assist,
        a final pass or a shot provider. Explain unavailable fixture coverage and small samples when advising on partnerships."""
        return report_goal_combinations(bridge, session_id, fixture_refs, team_native_id, scorer_person_id)
