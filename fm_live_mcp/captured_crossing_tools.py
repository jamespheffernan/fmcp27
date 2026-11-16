"""Named captured-live crossing reports; never dispatch to a current game."""
from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field


CLAIM_SCOPE = (
    'Historical captured-live export only. Dataset capture time and the source career date '
    'are separate. This report does not establish the current loaded career, current squad, '
    'availability, tactical assignments or the actual next opponent. No automatic live fallback.'
)


def report_captured_crossing(source_id: str, *, expected_capture_id: str,
                             competition_id: int, team_id: int,
                             date_from: str, date_to: str,
                             expected_career_id: str | None = None,
                             venue: str = 'all', leaders: int = 10,
                             minimum_minutes: int = 0, leader_sort: str = 'attempted') -> dict:
    """Read a pinned named source through the shared read-only source authority."""
    from .captured_match_sources import open_source
    from .match_crossing_report import report_connection, ReportUnavailable

    with open_source(source_id, expected_capture_id=expected_capture_id,
                     expected_career_id=expected_career_id) as (db, provenance):
        try:
            report = report_connection(
                db, competition_id=competition_id, team_id=team_id,
                date_from=date_from, date_to=date_to, venue=venue,
                leaders=leaders, minimum_minutes=minimum_minutes, leader_sort=leader_sort)
            state = 'available'
        except ReportUnavailable as error:
            report = {'unavailable_reason': 'required_report_fields_not_captured',
                      'missing_fields': error.missing_fields}
            state = 'unavailable'
    # Full column/field registries remain discoverable through the source catalog.
    source = {key: value for key, value in provenance.items()
              if key not in ('available_tables', 'field_provenance')}
    truncated = []

    def bounded(value, path='report'):
        if isinstance(value, dict):
            return {key: bounded(item, f'{path}.{key}') for key, item in value.items()}
        if isinstance(value, list):
            if len(value) > 100:
                truncated.append({'path': path, 'total_rows': len(value), 'returned_rows': 100,
                                  'cutoff_ties_may_be_truncated': True})
            return [bounded(item, f'{path}[{index}]') for index, item in enumerate(value[:100])]
        return value

    report = bounded(report)
    return {'state': state, 'evidence_kind': 'historical_captured_live_export',
            'source_id': source_id, 'dataset_source': source,
            'claim_scope': CLAIM_SCOPE, 'current_game_verified': False,
            'response_bounds': {'maximum_rows_per_list': 100, 'truncated_lists': truncated},
            'report': report}


def register_captured_crossing_tools(mcp) -> None:
    """Register one bounded typed report; source discovery lives in the shared catalog."""
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                          openWorldHint=False))
    def fm_report_captured_match_crossing(
        source_id: Annotated[str, Field(pattern=r'^[a-z0-9_]{1,80}$')],
        expected_capture_id: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')],
        competition_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)],
        team_id: Annotated[int, Field(strict=True, ge=1, le=4294967295)],
        date_from: Annotated[str, Field(min_length=10, max_length=10, pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')],
        date_to: Annotated[str, Field(min_length=10, max_length=10, pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')],
        expected_career_id: Annotated[str | None, Field(pattern=r'^[a-f0-9]{64}$')] = None,
        venue: Literal['all', 'home', 'away'] = 'all',
        leaders: Annotated[int, Field(strict=True, ge=1, le=20)] = 10,
        minimum_minutes: Annotated[int, Field(strict=True, ge=0, le=100000)] = 0,
        leader_sort: Literal['attempted', 'completed', 'accuracy'] = 'attempted',
    ) -> dict[str, Any]:
        """Report historical crossing volume, accuracy and named contributors from one named exported live-match dataset. Discover source_id, expected_capture_id, career, capture/source dates, available columns and competition IDs through fm_list_captured_match_sources first. Require explicit inclusive dates and a native team/competition ID from that source. Home/away filters are venue, never delivery flank. Counts preserve source coverage, unavailable fields and all-cross versus separately proved open-play distinctions; no left/right delivery oracle is implied. The read-only pinned export cannot answer current-squad, availability or current-next-opponent claims, and never attaches or silently falls back to the game. Responses cap every report list at100rows and disclose any truncated cutoff ties. No caller paths or SQL."""
        return report_captured_crossing(
            source_id, expected_capture_id=expected_capture_id,
            expected_career_id=expected_career_id,
            competition_id=competition_id, team_id=team_id,
            date_from=date_from, date_to=date_to, venue=venue,
            leaders=leaders, minimum_minutes=minimum_minutes, leader_sort=leader_sort)
