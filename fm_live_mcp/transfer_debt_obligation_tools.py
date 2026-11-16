"""Read-only retained transfer schedule gross sides and native net query."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .live_transfer_debt_obligations import get_club_transfer_debt_obligations


def register_transfer_debt_obligation_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_club_transfer_debt_obligations(
        session_id: Annotated[str, Field(min_length=1, max_length=128)],
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
        club_ref: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
    ) -> dict[str, Any]:
        """Read retained transfer schedule obligations for your active coach's club, coach_name from fm_get_save, or club_ref from fm_find_clubs. Returns checked financial owner, recorded payer/recipient clubs and outgoing/incoming rows, separately derived gross outgoing and gross incoming amounts in whole GBP, and the original signed native TransferDebt net. Gross sides reconcile with net, with any self-club native contribution explicit. The complete native prefix ends at its first null; aliases and outside-prefix scope are preserved. This is retained schedule state, separate from proposed offers and club bank loans. Native unit amount/count, dates and interval codes are retained; next due date, paid/arrears state, contingent triggers, complete future cash flow and full liabilities remain unknown. Missing source is unavailable; observed empty is native zero. Process/build/save/date, canonical club selection and consumed sources are rechecked. No native game calls, refresh, UI, game writes or save-file fallback."""
        return get_club_transfer_debt_obligations(bridge, session_id, coach_name, club_ref)
