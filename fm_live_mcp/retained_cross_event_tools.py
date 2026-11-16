"""Read-only per-event crossings from an exact retained match."""
from typing import Annotated, Any
from mcp.types import ToolAnnotations
from pydantic import Field
from .retained_cross_events import get_retained_cross_events


def register_retained_cross_event_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_retained_cross_events(
        session_id: str, fixture_ref: Annotated[str, Field(min_length=1)],
        team_native_id: Annotated[int | None, Field(strict=True, gt=0)] = None,
        person_native_id: Annotated[int | None, Field(strict=True, gt=0)] = None,
        offset: Annotated[int, Field(strict=True, ge=0)] = 0,
        limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 100,
        expected_source_id: Annotated[str | None, Field(pattern=r'^[a-f0-9]{64}$')] = None,
        coach_index: Annotated[int | None, Field(strict=True, ge=0, le=63)] = None,
    ) -> dict[str, Any]:
        """Inspect individual crossing events in one exact retained RESULT discovered with fm_find_fixtures or fm_list_retained_match_data. Returns named crossers, completed/not-completed outcome, raw native clocks and event coordinates, plus explicitly analytical pitch thirds and central/outer width bands. Counts EVERY player crossing attempt/completion counter including zero players before publishing either side; missing or mismatched coverage stays unknown. Crosses have their own native event family, distinct from passes. Select a participating team and optionally one canonical player. Follow every next_offset with the first source_id and identical selectors. Event points are not proved cross-release, reception or destination locations. Recipients, specific failure reasons, open-play event split, shot/goal links, physical units, human left/right, displayed minutes and simultaneous box occupation remain unknown. No near-event joins, current-playback substitute, saved-file fallback, game functions or game writes."""
        return get_retained_cross_events(bridge, session_id, fixture_ref, team_native_id=team_native_id,
                                        person_native_id=person_native_id, offset=offset, limit=limit,
                                        expected_source_id=expected_source_id, coach_index=coach_index)
