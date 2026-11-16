"""Current retained-match discovery without guessed fixture queries."""
from typing import Annotated, Any, Literal
from mcp.types import ToolAnnotations
from pydantic import Field
from .retained_match_discovery import list_retained_match_data


def register_retained_match_discovery_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_list_retained_match_data(
        session_id: str,
        scope: Literal['managed', 'next_opponent', 'managed_and_next_opponent', 'team'] = 'managed_and_next_opponent',
        team_native_id: Annotated[int | None, Field(strict=True, ge=1, le=0xffffffff)] = None,
        coach_index: Annotated[int | None, Field(strict=True, ge=0, le=63)] = None,
        offset: Annotated[int, Field(strict=True, ge=0, le=16384)] = 0,
        limit: Annotated[int, Field(strict=True, ge=1, le=16)] = 16,
        expected_source_inventory_id: Annotated[str | None, Field(pattern=r'^[a-f0-9]{64}$')] = None,
    ) -> dict[str, Any]:
        """List which previous matches currently retain individual shot maps or pass networks, with named date/teams/competition and canonical fixture_refs usable by the corresponding read tools. Default searches your managed team and its earliest observed next-opponent candidate; same-day completion and kickoff uncertainty remain explicit. scope=team requires an exact team_native_id; coach_index chooses one current active coach. Reads retained entry dates first, resolves them with bounded bulk fixture lookups, and independently verifies shot and pass availability against each exact fixture source. Missing/null/ambiguous or unreconciled data remains explicit and never becomes zero or whole-career coverage. Results include projection-specific source IDs and availability; source presence alone is not verified analytical data. Continue next_offset with expected_source_inventory_id. Does not load a replay, call game functions, read general saved files, schedule exports or control the screen."""
        return list_retained_match_data(bridge, session_id, scope, team_native_id, coach_index,
                                        offset, limit, expected_source_inventory_id)
