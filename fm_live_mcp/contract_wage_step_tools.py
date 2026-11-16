"""Read-only registration for stored appearance-linked main-wage scenarios."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .live_contract_wage_steps import get_contract_wage_steps


def register_contract_wage_step_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_contract_wage_steps(
        session_id: str,
        player_ref: Annotated[str, Field(min_length=1)],
    ) -> dict[str, Any]:
        """Compare one checked regular/combined player's current weekly main-contract wage with every stored club-league/international appearance-linked wage target (kinds13/19). Use a fresh player_ref from a same-attachment roster or search. Returns GBP/week target differences, thresholds including unavailable states, repeated entries, native getter selection and a per-player largest positive stored-target difference. Steps are independent scenarios, not additive; selected_by_native_property does not establish activation. Does not evaluate appearances-to-date, remaining progress, which step applies, future contracts, annual wage rises, bonuses, loan contributions, payroll, payment due or budget headroom. Lower targets are not observed savings. Complete roster population and deduplication are separate; virtual-player contract sources are unsupported. Read-only, non-atomic, source/lifetime rechecked; no native game calls, writes, profile generation or disk-save substitution."""
        return get_contract_wage_steps(bridge, session_id, player_ref)
