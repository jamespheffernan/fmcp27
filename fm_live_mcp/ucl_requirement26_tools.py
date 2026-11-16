"""Private SDK qualification registrar; do not register a second public UCL tool."""
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .ucl_requirement26_transport import get_player_ucl_requirement26


def register_ucl_requirement26_tools(mcp, bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    def fm_get_player_ucl_requirement26(
        session_id: Annotated[str, Field(min_length=1, max_length=128)],
        fixture_ref: Annotated[str, Field(min_length=1, max_length=256)],
        player_refs: Annotated[list[Annotated[str, Field(min_length=1, max_length=256)]],
                               Field(min_length=1, max_length=32, json_schema_extra={'uniqueItems': True})],
        coach_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
    ) -> dict[str, Any]:
        """Read current native UCL requirement26 for 1–32 explicit existing player_refs.

        Supply a fresh canonical fixture_ref for a stored UCL fixture on a later
        calendar date; coach_name optionally chooses an active coach from fm_get_save.
        There is no current-selection or historical-list default. The native clause
        checks goalkeeper-position rating and the managed club's ordered stored
        occurrences. Every current goalkeeper CLUB/TEAM/COMP/runtime/rule is bound
        separately; no PL registration source is substituted for the UCL selector.

        Returns native requirement26 true/false/null, the shared current aggregate,
        medical source distinctions and current-club rule provenance. False never
        establishes fixture exclusion; true never establishes medical clearance,
        registration submission or complete fixture eligibility. Duplicate stored
        occurrences retain native counting; requested aliases retain separate rows.
        Unsupported branches and compact requested position getters remain unknown,
        without profile generation. Future application requires unchanged applicable
        inputs. Full source and identity rebind plus consumed-byte fences follow the
        last callback. Reads remain non-atomic. No game calls, writes, UI or fallback.
        """
        return get_player_ucl_requirement26(bridge, session_id, fixture_ref, player_refs, coach_name)
