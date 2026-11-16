"""Read-only native retained transfer payment calendar projection."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .live_transfer_payment_schedule import get_club_transfer_payment_schedule


def register_transfer_payment_schedule_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_club_transfer_payment_schedule(
        session_id: Annotated[str, Field(min_length=1, max_length=128)],
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
        club_ref: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
    ) -> dict[str, Any]:
        """Project retained transfer payments for your active coach's club, coach_name from fm_get_save, or club_ref from fm_find_clubs. Returns checked financial owner, payer and recipient clubs, each next native payment date at08:30, call argument in whole GBP, remaining native payment count and last date under unchanged retained inputs and normal native clock advancement. Separates outgoing, incoming and self-club rows. Native payment call arguments use unit times interval; separate native debt gross/net totals use unit times remaining counter and can differ. Applies original Gregorian calendar, clock, first-month-day, date, counter and prior-removal gates. Exact current processing tick, unsupported clock, disabled processing and failed admission stay unavailable. Actual paid/arrears state, recipient net, timezone, complete cash flow and full liabilities remain unknown. Process/build/save/date, canonical selection and all consumed sources are rechecked. No native function, game write, UI, refresh or save-file fallback."""
        return get_club_transfer_payment_schedule(bridge, session_id, coach_name, club_ref)
