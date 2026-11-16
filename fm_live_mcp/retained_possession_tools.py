"""Read-only possession won/lost event coverage for one selected retained fixture."""
from typing import Annotated,Any
from mcp.types import ToolAnnotations
from pydantic import Field
from .retained_possession_events import get_retained_possession_events


def register_retained_possession_tools(mcp,bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
    def fm_get_retained_possession_events(
        session_id:str,fixture_ref:Annotated[str,Field(min_length=1)],
        team_native_id:Annotated[int|None,Field(strict=True,gt=0)]=None,
        person_native_id:Annotated[int|None,Field(strict=True,gt=0)]=None,
        offset:Annotated[int,Field(strict=True,ge=0)]=0,
        limit:Annotated[int,Field(strict=True,ge=1,le=500)]=100,
        expected_source_id:Annotated[str|None,Field(pattern=r'^[a-f0-9]{64}$')]=None,
        coach_index:Annotated[int|None,Field(strict=True,ge=0,le=63)]=None,
    )->dict[str,Any]:
        """Read named possession-won and possession-lost events for one exact retained result fixture from fm_find_fixtures. Checks every player's independently stored PossessionWon/PossessionLost counters including zero players before publishing a side. Source-native event anchors are preserved as raw coordinates (native_x across the pitch, native_y along it, centred on 0); exact possession-transition points, metres and human left/right are not proved. orientation gives the period boundary ticks and the end each side defends in each period, from the game's own orientation profile and published only where the side's deepest tracked player agrees; each event then carries period, defended_end and length_fraction_from_own_goal (0 = own goal line, 1 = the opposition's), and each side anchor_thirds (won and lost by equal third of the length, with the unplaced count). These totals are NOT completed-pressure regains or proof the press was played through; no opposing winner/loser or pressure linkage is inferred. Pressure attribution remains null. Missing retention/counter closure stays unavailable, not zero. Select participating team_native_id, optionally its person_native_id. Page with source_id pin. Uses current resident retained source only; no UI, game calls, writes or saved-file fallback."""
        return get_retained_possession_events(bridge,session_id,fixture_ref,team_native_id=team_native_id,
            person_native_id=person_native_id,offset=offset,limit=limit,expected_source_id=expected_source_id,coach_index=coach_index)
