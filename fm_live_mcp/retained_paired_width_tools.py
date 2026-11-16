from typing import Annotated,Any
from mcp.types import ToolAnnotations
from pydantic import Field
from .retained_paired_width import report


def register_retained_paired_width_tools(mcp,bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
    def fm_compare_retained_player_width(
        session_id:str,fixture_ref:Annotated[str,Field(min_length=1,max_length=128)],
        person_a_native_id:Annotated[int,Field(strict=True,gt=0)],
        person_b_native_id:Annotated[int,Field(strict=True,gt=0)],
    )->dict[str,Any]:
        """Who supplied in-possession width when two named team players were recorded together? Select two canonical PERSON IDs in one exact retained result. Compares absolute lateral coordinates at exactly coincident native tracking ticks with the same actual possession byte, not separate whole-match means. Returns each player's wider/tied counts and mean absolute width, denominators and zero-pair/post-exit-tail coverage. All-sample values retain zeros; nonzero and in-bounds sensitivity views expose bias without treating removed points as invalid. With proved pitch bounds, reports both in the same analytical outer width third. Missing, unaligned or non-overlapping streams remain unknown. Co-recorded samples do not establish shared on-pitch minutes, overlapping runs, marking, space created or tactical effect; units and human left/right unproved. Reuses canonical historical actors and full-fixture completion-counter validation. Read-only game access; no caller time boundaries or saved-file fallback."""
        return report(bridge,session_id,fixture_ref,person_a_native_id,person_b_native_id)
