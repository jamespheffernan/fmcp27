from typing import Annotated, Any
from pydantic import Field
from mcp.types import ToolAnnotations

from .current_frame_report import current_frame_report


def register_current_frame_tools(mcp, bridge):
    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, openWorldHint=False
        )
    )
    def fm_get_current_match_frame(
        session_id: str,
        person_native_id: Annotated[
            int | None, Field(strict=True, ge=1, le=4294967295)
        ] = None,
        include_proximity: Annotated[bool, Field(strict=True)] = False,
        include_native_goal_area: Annotated[bool, Field(strict=True)] = False,
    ) -> dict[str, Any]:
        """Capture one coherent already cached current playback frame endpoint. Returns native player XY and ball XYZ at exact local parameter1.0, with canonical names only for same-match original-side/slot actors independently present in a nonempty tracking prefix through this tick. A selected person without that prior-recorded evidence has positions withheld. Default returns compact prior-recorded actors; person_native_id selects one canonical PERSON native ID. Missing or duplicate endpoint samples stay null: no interpolation, nearest-time substitution or future frame fallback. Frame tick, observed/verification cursors, source ID and census/identity coverage are explicit. Immutable selected bytes, canonical fixture/actor/TEAM and process/career bookends are rechecked while the same match may advance; eviction, backwards seek, relink and changed bytes reject. include_proximity requires one selected person and adds planar ball/opponent separation in native world-coordinate units, checking unnamed/unexposed typed player entities as uncertainty. include_native_goal_area adds the provider-owned native pitch bounds and, for each side in an ordinary playing half (native periods FirstHalf/SecondHalf), the native positive/negative-Y goal it attacks at this same frame, with the native goal-end strip and its intersection with the pitch as exact rectangles (strict and inclusive edges stated; the native strip has no goal-line cap). It is geometry only: it classifies no player or ball sample, and a sample inside a rectangle is not an active player, box arrival or sustained box support. Unsupported periods (including shootouts), absent cache hits or unreconciled pitch setup return unavailable states, not defaults; retained shot or pass coordinates cannot use this basis because their periods are not frame-bound. Physical metres, current on-pitch population, marking, pressure, receiving a pass, possession, rendered pixels and live-versus-replay are unproved. The typed entity census can include substitutes. This is an instantaneous native frame product, separate from fm_get_current_match_spatial's recorded-sample averages. No score/final totals, saved-file fallback, game functions, UI actions or game writes. An absent current client/playback/cache/unique exact frame returns unavailable, not zero players."""
        return current_frame_report(
            bridge, session_id, person_native_id, include_proximity, include_native_goal_area
        )
