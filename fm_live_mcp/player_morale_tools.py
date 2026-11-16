"""Read-only current career-morale registration."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .live_player_morale import get_player_morale


def register_player_morale_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_player_morale(
        session_id: str,
        player_refs: Annotated[list[Annotated[str, Field(min_length=1)]],
                               Field(min_length=1, max_length=100,
                                     json_schema_extra={'uniqueItems': True})],
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
    ) -> dict[str, Any]:
        """Read stored career morale for1–100 distinct player_refs on the selected active coach's native TEAM roster. Obtain refs from fm_get_managed_squad(profile_policy='available'); select coach_name from fm_get_save when needed. Regular ACTUAL_PLAYER rows return the native signed code and pinned English definition on the1–20 scale, higher better. Negative codes retain the formatter's Scouting Required label; zero and values above20 remain outside_named_scale with null labels, without claiming Abysmal from the formatter's fallback. Combined/virtual records retain checked identity with unsupported_record_kind and null morale. Preserve every requested row. This is the career getter's mode0 stored value, separate from match morale, overall happiness, complaints, playing-time satisfaction, team cohesion and manager support; do not infer their causes or recommendations from this value alone. No native refresh or scouting mask executes. Roster membership may include loans and does not prove whole-club coverage. Reads are non-atomic with consumed-byte, build, process, save, coach, roster and reference rechecks. No profiles are generated; no game functions, writes, UI or saved-file fallback."""
        return get_player_morale(bridge, session_id, player_refs, coach_name)
