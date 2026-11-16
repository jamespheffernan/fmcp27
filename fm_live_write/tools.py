"""The edit tools of the write module (one so far), registered only when the module is loaded."""
from typing import Annotated, Any, Literal
from mcp.types import ToolAnnotations
from pydantic import Field
from .training_editor import set_player_training_intensity


def register_training_edit_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                         idempotentHint=False, openWorldHint=False))
    def fm_set_player_training_intensity(
        session_id: str,
        player_ref: Annotated[str, Field(min_length=1)],
        intensity: Literal['half', 'normal', 'double', 'rest', 'default'],
        expected_raw_code: Annotated[int, Field(strict=True, json_schema_extra={'enum': [0, 1, 2, 254, 255]})],
        coach_name: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """EDIT the running FM27 career: set ONE ordinary managed player's stored club training intensity. Get player_ref from fm_get_managed_squad and expected_raw_code from a fresh fm_get_player_individual_training. Choices: half0, normal1, double2, rest254 (no pitch/gym), default255 (native policy). Supports only verified direct managed training TEAM membership, not loans, virtual or player/staff records. Rechecks build, career, coach, identity, owner and all consumed bytes before and after a single-byte write; independently rereads the selection. dry_run validates without writing. Returns a durable receipt. Non-atomic: if an error reports a performed or unknown write, inspect fresh state and NEVER retry automatically. This changes stored game memory, not a text report; applied workload, medical overrides, training effects and save-to-disk persistence are unverified. Requires an explicit user editing task; do not use to implement unsolicited training advice."""
        return set_player_training_intensity(bridge, session_id, player_ref, intensity,
                                             expected_raw_code, coach_name, dry_run=dry_run)
