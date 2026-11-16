"""Read-only stored club facility query registration."""
from typing import Annotated, Any
from mcp.types import ToolAnnotations
from pydantic import Field

from .club_facilities import get_club_facilities


def register_club_facility_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_club_facilities(
        session_id: str,
        club_ref: Annotated[str, Field(min_length=1, max_length=128, description='Canonical live club_ref from fm_find_clubs; resolve shared names by native identity.')],
    ) -> dict[str, Any]:
        """Read one canonical club's own stored training facilities, youth facilities, youth coaching and youth recruitment levels. Obtain club_ref from fm_find_clubs and distinguish identically named clubs by canonical native identity. The editor scale is0..20 for training and-1..20 for the youth fields; signed-1 is unassigned and zero remains stored. Missing secondary source returns null with a reason, never zero. These own stored levels differ from native effective properties that may follow affiliates, sharing or inferred defaults. No stars, descriptive quality bands, training-ground links, investment, development impact or youth-intake prediction. Canonical table/type/identity and consumed bytes are rechecked; no UI, native execution, save-file decoding or game writes."""
        return get_club_facilities(bridge, session_id, club_ref)
