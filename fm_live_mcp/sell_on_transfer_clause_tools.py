"""Read-only selected club retained sell-on clause query."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .live_sell_on_transfer_clauses import get_club_sell_on_transfer_clauses


def register_sell_on_transfer_clause_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_club_sell_on_transfer_clauses(
        session_id: Annotated[str, Field(min_length=1, max_length=128)],
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
        club_ref: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
    ) -> dict[str, Any]:
        """Read the selected club's retained NEXT_SALE_PERCENTAGE_INFO sell-on clause family for your active coach's club, coach_name from fm_get_save, or club_ref from fm_find_clubs. Returns canonical container owner and recorded recipient, literal native person ID pair, signed native base/override percentages, basis amount, basis-used and raw flags. The native cash allocator uses these fields after selecting an eligible existing clause; complete transfer/person/contract admission, selection order and recursive redistribution are not evaluated. Basis-used never establishes settlement or a paid journal. Amount due, next date, actual paid state and final recipient net cash remain unknown. Incoming records in other clubs and synthetic country fallback clauses are not scanned. Observed empty differs from missing source. Process/build/save/date, canonical selection and every consumed source are rechecked. No native call, game write, UI, refresh or save-file fallback."""
        return get_club_sell_on_transfer_clauses(bridge, session_id, coach_name, club_ref)
