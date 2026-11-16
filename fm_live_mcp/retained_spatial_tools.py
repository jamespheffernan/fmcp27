from typing import Annotated, Any, Literal
from mcp.types import ToolAnnotations
from pydantic import Field

from .retained_spatial_report import capture_spatial, spatial_view


def register_retained_spatial_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_retained_match_spatial(
        session_id: str, fixture_ref: str,
        team_native_id: Annotated[int, Field(strict=True, gt=0)],
        person_native_id: Annotated[int | None, Field(strict=True, gt=0)] = None,
        grid: Literal['compact', 'native', 'none'] = 'compact',
        method: Literal['interpolated', 'sample_density'] = 'interpolated',
        coach_index: Annotated[int | None, Field(strict=True, ge=0, le=63)] = None,
    ) -> dict[str, Any]:
        """Analyze observed player movement, team shape and passing combinations for one exact retained match result. Returns the named players' average positions overall and by possession, plus a team or player heat map derived from sampled tracking and the top ten directed completed-pass links. Choose grid=none for a quick shape or passing comparison, compact for a 13 by 20 density grid, native for the 65 by 100 grid. Source is the active HUMAN-owned retained CBE, not a saved-file export. Default player heat maps reconstruct the guarded native movement interpolation, smoothing and normalization; rendered UI parity and its current selection/settings have not been observed. Compact grids average native cells. Separate sample_density counts recorded positions and is not the native interpolated heat map. A team map pools its players. Intensity scales are independent per map. method=sample_density counts positions instead. Examine zero-tail coverage and recorded minutes before interpreting substituted players' positions or midfield density. Use lateral_width for each player's sample-weighted mean(abs(lateral_native)) overall and in/out of possession, with each sample denominator and zero-tail coverage. This derived measure takes absolute values before averaging, so switching flanks does not cancel. Its possession subsets require actual 0/1 bytes without end-byte clamping; missing/255/other bytes remain unknown. Players use their own samples, not shared on-pitch minutes or synchronous populations; physical units and human left/right remain unproved. Use passing_outlets to see who received the most completed passes, their share of all team completions, every supplier with a positive completed-pass count in suppliers, and every joint-leading supplier in leading_suppliers. Suppliers are complete for each receiver and sorted by descending count then canonical PERSON ID; the top-ten connection limit does not truncate them. A known zero receiver has an empty suppliers list; unavailable or incomplete named networks remain unknown. Receiver counts cover the full named team network and keep the team denominator when filtering one player. A high-volume recipient suggests a player to watch; totals alone cannot prove the effect of pressing them. Passing edges count connections, not routes between endpoints. Requires a fixture_ref for the selected result. Unavailable tracking remains unknown."""
        source = capture_spatial(bridge, session_id, fixture_ref, coach_index=coach_index,
                                 include_native_heat_map=(grid != 'none' and method == 'interpolated'),
                                 native_team_id=team_native_id, native_person_id=person_native_id)
        return spatial_view(source, team_native_id, person_native_id, grid=grid, method=method)
