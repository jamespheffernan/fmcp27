"""Read-only Manager-visible (fog of war) attribute registration."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .knowledge_manager_visible import MAX_PLAYERS, get_manager_visible_attributes


def register_manager_visible_attribute_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_manager_visible_attributes(
        session_id: str,
        player_refs: Annotated[list[Annotated[str, Field(min_length=1)]],
                               Field(min_length=1, max_length=MAX_PLAYERS,
                                     json_schema_extra={'uniqueItems': True})],
        fields: Annotated[list[Annotated[str, Field(min_length=1, max_length=64)]] | None,
                          Field(min_length=1, max_length=47)] = None,
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
    ) -> dict[str, Any]:
        """Read what the selected manager sees of 1–28 ordinary players' attributes (fog of war), not their stored values. player_refs come from fm_find_save_players, fm_get_managed_squad or other player-listing tools; fields are compiled attribute names such as "Passing", "Finishing" or "Aerial Reach" (default all 47; use fm_get_player for the full-information values, which this tool never replaces). Each player-field is exactly one of: exact (value, the manager knows it), range (minimum and maximum, the scouting range), unknown (the manager sees nothing), or unavailable with a reason: compact/virtual or other unsupported record kinds, or a source check that failed, with detail. A hidden attribute byte is read only after the game's own H state for that player and field shows it is known, through a byte-level firewall; a failed or inconsistent read rejects the whole call, never returns a guess. The results come from the game's native report selection, H state and Range code, replayed and compared offline against the original code for one manager, club and date; the response states that scope and whether this context matches it. Not perceived stars, CA/PA or report contents, not a Manager search-population check, and no report freshness claim. Cost is about 0.13 s per player-field, at most 700 per call, so all 47 fields suit up to 14 players and one field suits 28. Reads are non-atomic with two final physical fences; no game writes or functions run, and the default tools stay full-information."""
        return get_manager_visible_attributes(bridge, session_id, player_refs, fields, coach_name)
