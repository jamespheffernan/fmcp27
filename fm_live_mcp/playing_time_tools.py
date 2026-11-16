"""Explicit read-only agreed-playing-time query."""
from typing import Annotated, Any
from mcp.types import ToolAnnotations
from pydantic import Field

from .playing_time import get_player_playing_time


def register_playing_time_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_player_playing_time(
        session_id: str,
        player_refs: Annotated[list[str], Field(min_length=1, max_length=100)],
    ) -> dict[str, Any]:
        """Read stored agreed playing time for 1–100 canonical actual/combined player_refs from live player discovery or rosters. Returns the current main-contract native code plus compiled English fallback title (e.g. Important Player, Regular Starter). Equal titles may have distinct native codes. Unmapped/contextual codes, null contracts and basic contracts retain explicit unknown states. Virtual players are unsupported. This reads the agreement, not actual usage, minutes, happiness, promised minutes/starts, fulfilment or selected localized/custom PLAYER_TYPE names. Main-contract context does not establish a loan-team agreement. Active player and club promise collections remain null/not_decoded. Canonical PERSON membership, reference identity, contract owner/type/accessor and consumed bytes are rechecked. No UI, native calls, game writes or saved-file fallback."""
        return get_player_playing_time(bridge, session_id, player_refs)
