from typing import Annotated, Any, Literal
from pydantic import Field
from mcp.types import ToolAnnotations
from .current_spatial_report import current_spatial_report


def register_current_spatial_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_current_match_spatial(
        session_id: str,
        heatmap_team_native_id: Annotated[int | None, Field(strict=True, ge=1)] = None,
        heatmap_person_native_id: Annotated[int | None, Field(strict=True, ge=1)] = None,
        heatmap_method: Literal['sample_density', 'interpolated'] = 'sample_density',
        heatmap_grid: Literal['compact', 'native'] = 'compact',
    ) -> dict[str, Any]:
        """Read where players have actually been recorded in the current viewable match through one checked playback cursor. Returns same-game canonical names and native tracking sample means for all samples, in possession and out of possession, grouped by exact participating team; selected-prefix sample counts, zero pairs/post-exit tails and unresolved player slots remain explicit. Future samples and future entrants are excluded. Captures anchor one cursor and recheck the same immutable position/phase prefix while the same game advances; backward seeks, source relinks, edited prefixes, actor changes and uncovered engine frontiers reject the result. This is a measured-prefix report, not current tactical formation, on-pitch duration or proof of finding space: nearest-opponent distance, receiving opportunities, space created, forward sign, physical units, human left/right and the displayed human minute remain unproved. Native axis0 is verified lateral pitch width and axis1 longitudinal pitch length; lateral_displacement_of_mean_native is abs(mean lateral coordinate), not mean absolute displacement, so switching flanks can cancel. Known zero pairs are included in FM's official sample denominator. No full-time score, ended fixture statistics, future engine totals, saved-file fallback, game functions or UI actions. If the current client or matching playback source is absent, returns unavailable rather than a retained-result substitute. Optionally request heatmaps from these same verified bytes by supplying heatmap_team_native_id from the participating fixture, with an optional canonical player ID. Default sample_density counts measured position points in a compact13x20 grid; interpolated reconstructs native movement/normalization and is not an observed UI map. Native65x100 resolution requires one player. Zero/post-exit tails, unresolved actors and prefix coverage remain explicit; density is not touches, space created or tactical effect. Default calls retain the existing response with heatmaps null. No extra capture or historical fallback is used. Use fm_get_current_match separately for its independently scoped score/chances and stored manager settings."""
        return current_spatial_report(bridge, session_id, heatmap_team_native_id, heatmap_person_native_id,
                                      heatmap_method, heatmap_grid)
