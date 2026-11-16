"""Discoverable read-only live pair-overlap entry point."""
from typing import Annotated, Any
from mcp.types import ToolAnnotations
from pydantic import Field

from .match_pair_overlap import MatchPairOverlapReports


def register_live_pair_overlap_tools(mcp, bridge):
    reports=MatchPairOverlapReports()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_report_live_player_pair_overlap(
        session_id: str,
        team_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295, description='Canonical native team ID from live team/fixture tools; not a database index.')],
        first_person_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295, description='First canonical PERSON native_id from fm_find_save_players, roster identities or retained_players.canonical_person_id; not a name/index.')],
        second_person_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295, description='Different second canonical PERSON native_id, discovered through the same live identity tools.')],
        date_from: Annotated[str, Field(pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$', description='Inclusive explicit fixture date; season bounds are not inferred.')],
        date_to: Annotated[str, Field(pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$', description='Inclusive explicit fixture date.')],
        competition_native_id: Annotated[int | None, Field(strict=True, ge=1, le=4294967295, description='Optional canonical competition ID from live competition/fixture tools.')] = None,
        include_goals: Annotated[bool, Field(strict=True, description='Optionally reconcile full fixture/player scoring evidence and report certain/possible scoring during overlap; equal-minute boundaries remain ambiguous.')] = False,
    ) -> dict[str, Any]:
        """Measure how much two named players actually shared the pitch in one fresh active-career scope. Resolve names to canonical PERSON native IDs first. Intersect separately verified native entry/exit intervals for the selected team; shared match listings and adjacent substitution handoffs are not overlap. Every selected stored-result fixture reports its reason, source intervals, unknown/missing player state and lower/upper native-minute bounds. Uses one bounded scoped capture (at most128 retained results) and consumes all pages. Native minute labels omit elapsed stoppage duration; roles, exact time, tactical effectiveness and match completion remain unproved. Optional scored-goal context requires source policy, final-score and complete player-credit reconciliation; no full-match xG/action attribution. No exported-file fallback, game functions, UI actions or game writes."""
        return reports.report(bridge,session_id,team_native_id,first_person_native_id,
                              second_person_native_id,date_from,date_to,competition_native_id,include_goals)
