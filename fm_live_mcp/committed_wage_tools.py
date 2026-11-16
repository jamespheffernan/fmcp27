"""Read-only selected-club current and committed native wage arithmetic."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .live_committed_wage_spending import get_club_committed_wage_spending


def register_committed_wage_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_club_committed_wage_spending(
        session_id: Annotated[str, Field(min_length=1, max_length=128)],
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
    ) -> dict[str, Any]:
        """Recompute selected coach club's native current and committed wage spending in whole GBP per week from fresh retained career inputs. Use coach_name from fm_get_save for multiple coaches. Payroll is recomputed in owned memory before native final arithmetic; original game-thread/HUMAN refresh admission is not entered or simulated. Unsupported monetary inputs reject the whole query without a partial total. This is the native commitment definition, not a complete future-liability schedule, all staff/bonus/tax costs, cash paid, offer activation, remaining budget or affordability. Process/build/save/date, canonical HUMAN/TEAM/CLUB and consumed inputs are rechecked. Native game calls, game writes, UI and disk-save fallback are absent."""
        return get_club_committed_wage_spending(bridge, session_id, coach_name)
