"""Optional active pass-event projection; registration is release-owner controlled."""
from typing import Any, Literal
from mcp.types import ToolAnnotations
from .active_pass_network import current_pass_network
from .active_pass_locations import current_pass_events


def register_active_pass_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_current_match_pass_network(session_id: str) -> dict[str, Any]:
        """Show named native completed-pass links strictly before one checked active playback cursor. Requires a currently bound active client, exact fixture/side/original-roster actor joins and fresh immutable event-selection reprojection while that same match progresses. Future/end-cursor ties are withheld. A side with unresolved consumed actors withholds its pair table. Counts describe selected native category7 events excluding unlabelled mask8 records; official passes-completed totals, attempted-pass denominators and completion percentages are unknown. No current formation-slot guesses, rendered minute, live/replay exclusion, coordinates, phase, assist, tactical-causality, older result or file fallback. An absent active client stays unavailable."""
        return current_pass_network(bridge, session_id)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_current_match_pass_events(session_id: str, team_native_id: int | None = None,
            from_person_native_id: int | None = None, to_person_native_id: int | None = None,
            limit: int = 50, cursor: str | None = None,
            pass_outcome: Literal['completed','not_completed','all'] = 'completed') -> dict[str, Any]:
        """Locate current native pass-map EVENT points at one verified playback cutoff. Default pass_outcome=completed preserves named category7 directed links and withholds unresolved sides. Choose not_completed to locate native incomplete pass attempts, or all for both outcomes, with equal-third/channel summaries and explicit sender gaps. Native categories6..11 excluding mask8 are the attempt family; only7 has a proved recipient. Other secondary bytes never become intended recipients, failure reasons or possession-loss events. Recipient filters require completed mode. Each coordinate is the native event-map point: where the pass was played from. Reception points, intended destinations and trajectories are not read at a playback cutoff (after the match fm_get_retained_pass_events gives each completed pass its reception point); units and human left/right remain unknown. Events require start<=end<fixed cursor; future/end-cursor ties are withheld. No resident attempted-minus-completed subtraction or fixed-prefix counter reconciliation supplies these locations.1..100 rows per page; repeat identical selectors/limit/outcome with next_cursor within120seconds. Reload, relink, rewind or changed consumed bytes invalidate it. No displayed-minute, active-XI, replay-exclusion or tactical-cause claim."""
        return current_pass_events(bridge, session_id, team_native_id=team_native_id,
            from_person_native_id=from_person_native_id, to_person_native_id=to_person_native_id,
            limit=limit, cursor=cursor, pass_outcome=pass_outcome)
