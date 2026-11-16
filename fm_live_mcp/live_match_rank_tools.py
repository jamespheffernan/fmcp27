"""Bounded, named action rankings from the active native career only."""
from typing import Annotated, Any, Literal
from mcp.types import ToolAnnotations
from pydantic import Field

from .live_match_player_ranking import LiveMatchPlayerRanks, metric_catalog

Metric = Literal[
    'dribbles_made', 'progressive_passes', 'passes_attempted', 'passes_completed', 'key_passes',
    'open_play_key_passes', 'chances_created', 'shots', 'shots_on_target',
    'goals', 'assists', 'crosses_attempted', 'crosses_completed',
    'open_play_crosses_attempted', 'open_play_crosses_completed',
    'tackles_attempted', 'tackles_completed', 'interceptions', 'clearances',
    'aerial_duels_attempted', 'aerial_duels_completed', 'possession_won',
    'possession_lost', 'pressures_attempted', 'pressures_completed', 'fouls_committed',
    'yellow_cards_received', 'red_cards_received',
]


def register_live_match_rank_tools(mcp, bridge):
    ranks = LiveMatchPlayerRanks()
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @mcp.tool(annotations=read)
    def fm_get_live_match_rank_metrics() -> dict[str, Any]:
        """Discover named additive match ranking metrics and allowed normalizations without reading or attaching to the game. Progressive passes are the official FM count; no carries, distance threshold, final-third entry or played-role interpretation is proved. Per100passattempts is an activity ratio, not accuracy."""
        return metric_catalog()

    @mcp.tool(annotations=read)
    def fm_rank_live_match_players(
        session_id: str,
        competition_native_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)],
        date_from: Annotated[str, Field(pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')],
        date_to: Annotated[str, Field(pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')],
        metric: Metric,
        normalization: Literal['total', 'per90', 'per_100_pass_attempts', 'per_100_pressure_attempts'] = 'per90',
        minimum_minutes: Annotated[int | None, Field(strict=True, ge=0, le=1000000)] = None,
        team_native_id: Annotated[int | None, Field(strict=True, ge=1, le=4294967295)] = None,
        limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 10,
        cursor: str | None = None,
        highlight_person_native_ids: Annotated[list[Annotated[int, Field(strict=True, ge=1, le=4294967295)]] | None, Field(max_length=8)] = None,
    ) -> dict[str, Any]:
        """Rank players across a fresh competition/team date scope using one checked live capture, without downloading thousands of player rows. Select a named count from fm_get_live_match_rank_metrics. Supply up to8 highlight_person_native_ids to return their ranks or exact exclusion reason even outside the limit. Default minimum minutes is450 for normalized rankings and0 for totals; the applied cutoff is returned. Sum all records before the threshold, retaining real zero-minute actions. Only independently proved unused bench null minutes count as zero; unknown active minutes/metrics, identities and missing historical team sides remain explicit and unclassified. Group canonical player IDs by historical fixture team ID/index, never current club or roster. Progressive_passes additionally supports100*sum(count)/sum(pass_attempts), not accuracy; unknown/zero pass denominators are withheld. Pressures_completed supports per_100_pressure_attempts as100*sum(completions)/sum(pressure attempts); missing,zero or inconsistent denominators remain unavailable. These are native statistical pressures, not possession regains, locations, beaten presses or proof a tactical press worked. Exact competition ranks include every cutoff tie: follow next_cursor with identical selectors for remaining fixed100-row pages, reusing capture_id without recapture. Cursor expires after5minutes or career reload. Native scope is at most512fixtures with bounded per-window accumulation; larger ranges fail explicitly. Materialized/retained coverage and actual match completion remain qualified, never presumed season-complete. No saved/exported fallback, role or eligibility claim."""
        return ranks.rank(bridge, session_id, competition_native_id, date_from, date_to, metric,
                          normalization, minimum_minutes, team_native_id, limit, cursor, highlight_person_native_ids)
