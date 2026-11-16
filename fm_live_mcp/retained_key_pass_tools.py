"""Read-only full-event key-pass coverage for one selected retained fixture."""
from typing import Annotated,Any
from mcp.types import ToolAnnotations
from pydantic import Field
from .retained_key_passes import get_retained_key_pass_annotations


def register_retained_key_pass_tools(mcp,bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
    def fm_get_retained_key_pass_annotations(
        session_id:str,fixture_ref:Annotated[str,Field(min_length=1)],
        team_native_id:Annotated[int|None,Field(strict=True,gt=0)]=None,
        person_native_id:Annotated[int|None,Field(strict=True,gt=0)]=None,
        offset:Annotated[int,Field(strict=True,ge=0)]=0,
        limit:Annotated[int,Field(strict=True,ge=1,le=500)]=100,
        expected_source_id:Annotated[str|None,Field(pattern=r'^[a-f0-9]{64}$')]=None,
        coach_index:Annotated[int|None,Field(strict=True,ge=0,le=63)]=None,
    )->dict[str,Any]:
        """Show where native key-pass annotations are recorded and which named players supplied whom in one exact retained RESULT fixture from fm_find_fixtures. Counts mask2 annotations over ALL CBE event categories and checks EVERY independently stored player KeyPasses counter including zero players before pagination. Read full_side_key_pass_counter_closure and player_checks: a missing side denominator stays partial, while individually reconciled creators can retain explicitly limited views. Only exact event-ID joins to independently whole-side counter-qualified completed passes supply canonical recipients and official pass-map event locations/analytical thirds. Other annotated categories keep recipient and location unknown, even if their raw bytes look plausible. Locations are not proved ball-release points; units and human left/right remain unknown. A key-pass annotation is NOT a uniquely linked shot, assist or goal provider: no proximity join, delivery pattern or causality is asserted. Complete source/category counts, withheld actors and unknown location coverage remain visible. Select team_native_id to scope one participating team; a player also requires that team. Page with the first source_id; totals remain null for a selected unreconciled population. Current-game playback prefixes, disk saves, broad scans, game calls and writes are not used."""
        return get_retained_key_pass_annotations(bridge,session_id,fixture_ref,team_native_id=team_native_id,
            person_native_id=person_native_id,offset=offset,limit=limit,expected_source_id=expected_source_id,coach_index=coach_index)
