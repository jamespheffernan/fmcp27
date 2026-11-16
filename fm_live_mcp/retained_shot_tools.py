"""Conditional selected-fixture retained shot-map discovery and read tool."""
from typing import Annotated, Any, Literal
from mcp.types import ToolAnnotations
from pydantic import Field
from .live_retained_shots import get_retained_shot_map
from .retained_shot_quality import report_shot_quality


def register_retained_shot_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_retained_shot_map(
        session_id: str, fixture_ref: str,
        coach_index: Annotated[int | None, Field(strict=True, ge=0, le=63)] = None,
        offset: Annotated[int, Field(strict=True, ge=0, le=2048)] = 0,
        limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 100,
        expected_source_id: Annotated[str | None, Field(pattern=r'^[a-f0-9]{64}$')] = None,
        include_source_observed: Annotated[bool, Field(strict=True)] = False,
        projection: Literal['legacy_reconciled', 'source_proven'] = 'legacy_reconciled',
    ) -> dict[str, Any]:
        """Read shot events for one exact live result fixture_ref from fm_find_fixtures. Explicit projection=source_proven returns one paged attempts collection with native_xg_value, the original frontend XgValue, independently of credited aggregate xG. It preserves valid event/count/actor/outcome/coordinate fields with explicit partial coverage and per-field unknowns. Official aggregate xG remains separate; credited per-attempt contribution is null because the checked retained representation does not store it. No aggregate-equality admission or invented contribution applies in source_proven. Source IDs bind projection/version: changing projection restarts paging; never reuse another projection's offset/pin. include_source_observed is legacy-only and cannot combine with source_proven. Omitted projection=legacy_reconciled preserves the existing shots/expected_goals and strict quality contract below. Retention is conditional: unavailable/null owner caches, ambiguous source bindings and unreconciled sides remain explicit, never zero or a blanket whole-save claim. Both side attempt counts, native goal/saved category target counts and float32 xG sums must reconcile with the exact active-bank fixture. Official OwnGoal markers remain separate from shots, preserving actor/event side versus beneficiary side. Statistical rows expose exact native end outcomes goal,missed_target,hit_woodwork,saved,blocked; unknown codes stay null. Hit Woodwork is a terminal category, not all intermediate contacts. Statistical rows include a source-proved penalty flag; non_penalty_unspecified does not mean open play, corner or free kick. Official native location bins may be available; metric distance and human left/right remain unproved. Coordinates are unnormalized native x/y with unresolved units/viewpoint; actor names require canonical side+stored-player-slot joins, and raw clock words have unproved units. Half assignment requires source-verified named period boundaries bound to this exact fixture and a proved shared event-clock domain. Record order, sorted raw times, coordinates and changing attacking ends are not period evidence; without that linkage first/second-half statistics remain unknown while whole-match figures stay usable. Body part follows official native head/feet shot groups; unsupported types remain unclassified. These are headed shots, not aerial duels. Assist and delivery locations remain unresolved. coach_index selects the current active coach list; omit to search all checked active coaches. Opt in include_source_observed only for a separate collection whose complete rostered player counts/actors close while xG aggregates disagree; native_expected_goals is NOT promoted to verified expected_goals or rankings. Continue next_offset with expected_source_id to reject source changes. Does not run game functions, load an archive, use a saved-file fallback or control the screen."""
        return get_retained_shot_map(bridge, session_id, fixture_ref, coach_index,
                                     offset, limit, expected_source_id, include_source_observed, projection)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_report_retained_shot_quality(
        session_id: str,
        fixture_refs: Annotated[list[str], Field(min_length=1, max_length=16)],
        team_native_id: int, perspective: Literal['for', 'against'],
        threshold: Annotated[float, Field(ge=0, le=1)] = 0.20,
        player_limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 15,
        coach_index: Annotated[int | None, Field(strict=True, ge=0, le=63)] = None,
    ) -> dict[str, Any]:
        """Compare chance quality for or against one team across exact live result fixtures. Returns verified per-fixture and pooled shot counts, xG, best chance xG, number reaching your xG threshold, penalty and non-penalty splits, and canonical shooters ranked by xG. Includes header, feet and unclassified chance quality and terminal outcomes on each available side. A missing side has null metrics. Pooled totals cover only available sides. Non-penalty includes other set pieces. Own goals are separate from attempts. Use fm_get_retained_shot_map for individual events."""
        return report_shot_quality(bridge, session_id, fixture_refs, team_native_id,
                                   perspective, threshold, player_limit, coach_index)
