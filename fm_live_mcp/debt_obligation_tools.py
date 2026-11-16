"""Read-only owner-bound native remaining-debt query registration."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .live_debt_obligations import get_club_debt_obligations


def register_debt_obligation_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_club_debt_obligations(
        session_id: Annotated[str, Field(min_length=1, max_length=128)],
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
        club_ref: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
    ) -> dict[str, Any]:
        """Read one selected club's named native RemainingDebt loan report in whole GBP. Defaults to your active coach's club; select coach_name from fm_get_save or club_ref from fm_find_clubs. Returns actual financial owner, native source count and first-ten-physical-slot scope, original debt/repayment terms and separately qualified calendar-based remaining debt. Native zero does not establish settlement. Unknown English source labels remain unknown without suppressing proved native arithmetic. Exact lender, payment/arrears state, next payment date, transfer instalments and complete liabilities remain unestablished. Missing source stays unavailable; observed empty stays empty. Canonical CLUB membership, source bytes and process/build/save/date are rechecked. No native game calls, refresh, UI, game writes or save-file fallback."""
        return get_club_debt_obligations(bridge, session_id, coach_name, club_ref)
