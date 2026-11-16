"""Read-only selected-payer retained contingent transfer clause query."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .live_contingent_transfer_clauses import get_club_contingent_transfer_clauses


def register_contingent_transfer_clause_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_club_contingent_transfer_clauses(
        session_id: Annotated[str, Field(min_length=1, max_length=128)],
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
        club_ref: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
    ) -> dict[str, Any]:
        """Read the selected payer club's retained APPEARANCE_MONEY_INFO transfer-clause family only, for your active coach's club, coach_name from fm_get_save, or club_ref from fm_find_clubs. Returns canonical payer/recipient clubs, literal person reference and checked playing-person names when resolvable, native call amount in whole GBP, event-kind code, progress counter and target. Native kind2 pays each qualified event; kinds0/1/4 use a threshold, while kind3 uses an event increment. Player names use a bounded native ID-pair lookup with canonical PERSON membership; pending native sorting/remapping and nonplaying types stay explicitly unresolved. English event labels and full person/contract/match eligibility are not established. A counter comparison never means a payment is due or paid. Incoming clauses in other clubs, other clause families, next date, actual paid/arrears state and complete liabilities remain unknown. Observed empty is distinct from missing source. Process/build/save/date, canonical selection and every consumed source are rechecked. No native function, game write, UI, refresh or save-file fallback."""
        return get_club_contingent_transfer_clauses(bridge, session_id, coach_name, club_ref)
