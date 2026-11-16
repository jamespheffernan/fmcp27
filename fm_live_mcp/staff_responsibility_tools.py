"""Read-only registration for canonical own stored responsibility records."""
from typing import Annotated, Any
from mcp.types import ToolAnnotations
from pydantic import Field
from .live_staff_responsibilities import get_club_staff_responsibilities


def register_staff_responsibility_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_club_staff_responsibilities(
        session_id: Annotated[str, Field(min_length=1, max_length=128)],
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
        club_ref: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
    ) -> dict[str, Any]:
        """Read a club's own stored staff-responsibility records and canonical stored PERSON references. Defaults to your active coach's club; select coach_name from fm_get_save or club_ref from fm_find_clubs. Includes physical-slot accounting, native responsibility/team-type/reference-mode codes and pinned English description templates. Preserve template placeholders and unknown descriptions or references. Managed context reports the selected coach and TEAM's own native type code; stored team-type codes are not a complete squad/UI mapping. These are stored references, not verified effective delegation: affiliation inheritance, default job selection, outer eligibility/suppression and current edit-session changes remain unevaluated. A missing own source is unavailable, while an observed empty vector is empty; duplicate and null slots remain explicit. Does not infer current employment, coaching stars, workload or suitability. Rechecks canonical CLUB/PERSON membership, all consumed bytes and process/build/save/date after the last context callbacks. No game writes, native game calls, refresh, UI control or save-file fallback."""
        return get_club_staff_responsibilities(bridge,session_id,coach_name,club_ref)
