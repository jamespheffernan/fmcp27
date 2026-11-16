"""Read-only tool registration for supported native current delegates."""
from typing import Annotated,Any
from mcp.types import ToolAnnotations
from pydantic import Field
from .live_current_staff_responsibilities import get_club_current_staff_responsibilities


def register_current_staff_responsibility_tools(mcp,bridge):
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
    def fm_get_club_current_staff_responsibilities(
        session_id:Annotated[str,Field(min_length=1,max_length=128)],
        coach_name:Annotated[str|None,Field(min_length=1,max_length=256)] = None,
        club_ref:Annotated[str|None,Field(min_length=1,max_length=128)] = None,
    )->dict[str,Any]:
        """Query current native staff delegates for a club's own stored responsibility slots. Defaults to your active coach's club; select coach_name from fm_get_save or club_ref from fm_find_clubs. Returns stored references separately from current delegates and each native-selected canonical TEAM context. Emulates the original native responsibility-list query with default candidate generation disabled and human delegates allowed (consumer flags 0,1); includes supported CLUB overrides and eligibility. Unsupported paths remain unavailable, never silently unassigned. A native null return is separately labelled. Preserve description placeholders, unknown codes, null slots and duplicates. Checks at most 128 own source slots; a larger source is explicitly unavailable. This is not a complete UI responsibility population, edit-session state, generated default candidates, coaching stars, workload or suitability. Rechecks all consumed bytes after final process/build/save/context callbacks. Runs original ARM64 only inside a private emulator, with private stack writes only; no function call in the game process, game write, UI control, refresh or save-file fallback."""
        return get_club_current_staff_responsibilities(bridge,session_id,coach_name,club_ref)
