"""Read-only UCL registration inputs for explicit canonical references."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .ucl_registration import get_player_ucl_registration


def register_ucl_registration_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_player_ucl_registration(
        session_id: Annotated[str, Field(min_length=1, max_length=128)],
        fixture_ref: Annotated[str, Field(min_length=1, max_length=256)],
        player_refs: Annotated[list[Annotated[str, Field(min_length=1, max_length=256)]],
                               Field(min_length=1, max_length=32, json_schema_extra={'uniqueItems': True})],
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
        include_fixture_suspension: bool = False,
    ) -> dict[str, Any]:
        """Read current UCL registration inputs for 1–32 explicit existing player_refs.

        Supply one explicit stored UCL fixture on a later calendar date. Get fresh
        refs from root player/squad queries and fixture discovery; coach_name comes
        from fm_get_save, defaulting to its selected active HUMAN/TEAM.
        No current-XI/bench or historical-selection default is used.

        Returns native registered-to-play(mode1) and the supported requirement14
        age/club-history exemption separately. A positive first requirement14 skips
        requirement26. Otherwise returns that conditional native clause and one shared
        aggregate over stored player occurrences, preserving duplicates and native order.
        Each goalkeeper's own current-club rule stays separate from the target UCL rule.
        Medical no-record, checked empty, expired and unavailable sources stay distinct;
        true26 is not medical clearance. False clauses never establish exclusion.
        Unsupported canonical virtual/combined sources remain unknown rows.
        Opt in with include_fixture_suspension=true to add each row's separate ordinary
        mode0 suspension predicate for the fixture and a fixture_eligibility_evidence
        reading. Suspension never counts as registration, a native-false registration
        predicate can coexist with an exemption, and unknown stays unknown. Neither
        clears nor excludes a player. Omitting it preserves the existing response.
        Current-input registration coverage is true-or-null, never full fixture
        eligibility or a submitted squad list. Current read date and fixture date
        are separate; future application requires unchanged applicable inputs.

        Rebinds process/build/world/save/date/coach/TEAM/person/fixture/phase and
        verifies consumed bytes after the final callback. Reads remain non-atomic.
        No game calls, writes, refresh, generation, UI or saved-file fallback.
        """
        return get_player_ucl_registration(bridge, session_id, fixture_ref, player_refs, coach_name,
                                           include_fixture_suspension)
