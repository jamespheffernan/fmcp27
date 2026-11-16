"""Read-only simultaneous positional cover for the editable XI and bench."""
from datetime import datetime, timezone
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field, StrictInt, StrictStr

from . import bench_cover_source, players
from .simultaneous_bench_cover import solve_cover


def report_bench_cover(bridge, session_id, outgoing, minimum_rating=15,
                       minimum_condition_percent=None, require_clear_injury_flag=False, coach_name=None):
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        read, save, _ = bridge._world_state(process, tables)
        coach = bridge._select_coach(save, coach_name)
        captured = bench_cover_source.capture(read, tables[0] - players.RVA[0], coach, tables,
                                             expected_current_date=save['current_date'])
        bridge._current(session_id)
        public_save = bridge._public_save(save)
    result = solve_cover(captured, outgoing, minimum_rating, minimum_condition_percent, require_clear_injury_flag)
    sheet = captured.get('sheet') or {}
    return {**result, 'source_state': captured['source_state'], 'coverage': captured.get('coverage'),
            # Where the editable selection's bench ends (fm_get_managed_team_sheet); not a submitted squad.
            'bench_boundary': {key: sheet.get(key) for key in (
                'role_boundary_state', 'bench_end', 'bench_boundary_source',
                'bench_boundary_unavailable_reason', 'bench_fixture')},
            'coach': coach['name'], 'observed_save': public_save, 'saved_file_fallback': False,
            'observed_at': datetime.now(timezone.utc).isoformat(), 'atomic': False}


def register_simultaneous_bench_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_report_simultaneous_bench_cover(
        session_id: str, outgoing: Annotated[list[StrictStr | StrictInt], Field(min_length=1, max_length=11)],
        minimum_rating: Annotated[int, Field(strict=True, ge=1, le=20)] = 15,
        minimum_condition_percent: Annotated[float | None, Field(ge=0, le=100)] = None,
        require_clear_injury_flag: Annotated[bool, Field(strict=True)] = False, coach_name: str | None = None,
    ) -> dict[str, Any]:
        """Can the current bench replace these picked starters at once while preserving both working phase positions? Supply outgoing starter names or original zero-based team-sheet slot indices. Each incoming PERSON can cover one vacancy. Compares general position familiarity on a 1–20 scale in possession AND out of possession, with an optional stored condition floor. Returns the number of distinct verified complete plans. Injury flags and condition are reported; set require_clear_injury_flag to filter on a checked clear native flag. Distinguishes unresolved coverage from insufficient distinct cover. Roles, medical or competition clearance and match substitution rules are separate. Read-only, no lineup changes or disk save."""
        return report_bench_cover(bridge, session_id, outgoing, minimum_rating,
                                  minimum_condition_percent, require_clear_injury_flag, coach_name)
