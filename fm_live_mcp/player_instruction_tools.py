"""Stored instruction provenance, never a game action or effective-match verdict."""
from typing import Any, Literal
from mcp.types import ToolAnnotations
from .player_instruction_source import capture


def register_player_instruction_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_managed_player_instructions(
        session_id: str,
        coach_name: str | None = None,
        phase: Literal['both', 'in_possession', 'out_of_possession'] = 'both',
    ) -> dict[str, Any]:
        """Read the picked XI's stored player-instruction provenance in the active manager's existing working tactical edit payload. Separate position/role-key selected bits, stored per-person records under exact/strict lookup policies, and narrowly supported native role-rule defaults. Native PI_GET_FORWARD_OFTEN22 and PI_HOLD_POSITION23 are separate choices. Empty personal maps prove no per-person record in this creator; they do not prove no base selections or role-implied instruction. A clear stored bit does not imply that behavior is absent: a supported native role rule may select it. Role-rule cases currently cover IP D(R)/D(L) Wing-Back versus Full-Back only; unknown cases remain unavailable. Effective base/personal/role/shift precedence, applied match instructions, movement and observed screen state remain unknown. A missing working edit source stays unavailable; no stale snapshot, prepared-tactic substitution, edit-session creation or native getter call. Read-only; never changes tactics."""
        return capture(bridge, session_id, coach_name, phase)
