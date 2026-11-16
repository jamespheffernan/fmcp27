"""Bounded discoverable national-team entrypoint, reusing the checked roster reader."""
from typing import Annotated, Any
from mcp.types import ToolAnnotations
from pydantic import Field
from .live_national_squads import find_national_teams


def register_live_national_squad_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_find_national_teams(
        session_id: str,
        name: Annotated[str | None, Field(min_length=1, max_length=100)] = None,
        nation_native_id: Annotated[int | None, Field(strict=True, ge=1)] = None,
        record_budget: Annotated[int, Field(strict=True, ge=1, le=16)] = 16,
        next_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Discover named live nations' national-team containers and all their ordered teams, including First Team/U21/U20/U19/U18 when the installed team-type enum names them. Name matches nation short name or abbreviation; combine with exact nation_native_id, or omit to enumerate. Follow every next_cursor with identical name, ID and record_budget, even on empty pages. Returns canonical container/nation/TEAM identities, raw type codes and editor type labels, explicit unknown gender, stored roster counts and fresh team_ref. Then call fm_get_team_squad(team_ref, profile_policy='available') for complete ordered current international roster members and exact PERSON names; optionally request profiles, health and club links. This reads stored national membership, not players merely sharing nationality, match XI, eligibility, call-up date or international-duty absence. Great Britain can list an England-owned team: listed-container membership and canonical owner are separate fields. Known zero roster counts remain zero; missing nation references and unknown labels remain explicit. No UI, game functions, generated data or saved-file fallback."""
        return find_national_teams(bridge, session_id, name, nation_native_id, record_budget, next_cursor)
