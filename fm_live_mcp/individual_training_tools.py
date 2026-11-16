"""Read-only stored individual focus and club-intensity registration."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .live_individual_training import get_player_individual_training


def register_individual_training_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_player_individual_training(
        session_id: str,
        player_refs: Annotated[list[Annotated[str, Field(min_length=1)]],
                               Field(min_length=1, max_length=100,
                                     json_schema_extra={'uniqueItems': True})],
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
        include_default_resolution: bool = False,
        include_role_position: Annotated[bool, Field(strict=True)] = False,
    ) -> dict[str, Any]:
        """Read stored individual additional focus and club training intensity for1–100 distinct player_refs on the selected active HUMAN coach's native TEAM roster. Obtain refs from fm_get_managed_squad; select coach_name from fm_get_save when needed. Returns checked identities/names, separate raw/signed codes, pinned English definition names and explicit missing-child/unset/unknown states. club_training_intensity is independent of the optional focus child: named choices are Half, Normal, Double and No pitch or gym work. RawFF/-1 is native_default_resolution_requested, a concrete stored default-resolution request with applied_intensity null; do not label it an observed applied setting or treat it as missing. Unsupported combined/virtual rows retain identity with null fields. Preserve every requested row, including zeros and unknowns. Native roster membership can include loans; it does not establish whole-club coverage, current training control, effective training or actual applied intensity, workload, attendance, recommendation or development outcome. Non-atomic source reads are rechecked with process/build/save/coach/roster context. Set include_default_resolution=true to reconstruct what a stored FF request resolves to at current stored condition from an existing selected HUMAN/TEAM policy. The optional default_intensity_resolution is separate from the stored selection and actual applied intensity/workload; explicit selections return not_requested. Unsupported TEAM-selection branches, missing direct policy or unsupported record kinds remain unavailable. Set include_role_position=true to append separate stored native IP role/position masks and signed codes plus the stored signed OOP code. Preserve captured empty vectors and native zero results. A missing OOP child carries the native audit fallback50 with raw_code null; a present stored50 keeps source_state present_child. Human-readable role/position labels are null because this training namespace is unproved; never translate these signed codes through FMF tactic enums. These selections do not prove applied/effective training, training-screen population or assignment dates. No native default-resolver invocation, policy creation, medical override, profile generation, game calls, writes, UI or saved-file fallback."""
        options={'include_default_resolution':include_default_resolution}
        if include_role_position is not False:
            options['include_role_position']=include_role_position
        return get_player_individual_training(bridge, session_id, player_refs, coach_name,**options)
