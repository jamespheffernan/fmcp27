"""Read-only managed-roster main-contract expiry tool registration."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .live_player_contract_expiry import get_managed_player_contract_expiry


def register_player_contract_expiry_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_managed_player_contract_expiry(
        session_id: str,
        expires_on_or_before: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')],
        coach_name: str | None = None,
        limit: Annotated[int, Field(ge=1, le=100, strict=True)] = 100,
        unclassified_limit: Annotated[int, Field(ge=0, le=256, strict=True)] = 100,
        offset: Annotated[int, Field(ge=0, le=256, strict=True)] = 0,
        expected_source_id: Annotated[str | None, Field(pattern=r'^[a-f0-9]{64}$')] = None,
    ) -> dict[str, Any]:
        """Find verified fixed main-contract expiries on or before required YYYY-MM-DD, earliest first, including already expired dates. Select one active coach from fm_get_save; scans every selected TEAM native membership slot (max256), retaining duplicates, nulls and loaned-out players. Returns an all-slot manifest, exact scanned/classified/matched/returned/truncated counts and bounded unclassified_players for dynamic/basic/no-contract/virtual/known unsupported slots. Continue next_offset with expected_source_id; changed sources reject continuation. Request unclassified_limit=256 for all unclassified details. Omitted unclassified rows remain counted, never confirmed nonmatches. Main-contract and current-club identities are separate. This is not whole-club coverage. Does not evaluate loan expiry, future agreements, extension/clause activation, renewals or departures. No profile generation, attribute decoding, game calls, writes or disk-save fallback. Non-atomic; source/lifetime rechecked; malformed sources reject the whole result."""
        return get_managed_player_contract_expiry(
            bridge, session_id, expires_on_or_before, coach_name, limit, unclassified_limit, offset,
            expected_source_id)
