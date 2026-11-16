"""Read-only registration for one selected club's recorded annual stadium rent."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .live_club_stadium_rent import get_club_stadium_rent


def register_club_stadium_rent_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_club_stadium_rent(
        session_id: Annotated[str, Field(min_length=1, max_length=128)],
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
    ) -> dict[str, Any]:
        """Read the selected active HUMAN coach's canonical CLUB recorded stadium rent (native Csry) in whole GBP per year, separate from weekly wages and transfer budgets. Use coach_name from fm_get_save when several active coaches exist. Missing finance returns unavailable amount/currency; typed base finance returns its distinct native literal zero; concrete finance preserves signed32 cash, without interpreting negative values as credits or refunds. This is stored data without refresh, not an amount due, payment schedule, legal lease, future liability, outstanding balance, payroll or affordability verdict. Process/build/save/date, canonical HUMAN/TEAM/CLUB ownership and consumed source bytes are rechecked. No roster/profile/attribute expansion, native game invocation, game write, UI, calculation refresh or saved-file fallback."""
        return get_club_stadium_rent(bridge, session_id, coach_name)
