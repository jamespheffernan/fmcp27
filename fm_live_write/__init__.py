"""Game edits for FMCP 27, kept apart from the reader.

The reader (`fm_live_mcp`) is read-only and does not import this package. The server loads it only
when the environment names it: `FMCP_EXTENSIONS=fm_live_write`. It then registers the edit tools
on the same server and marks the bridge so `fm_status` reports that edits are possible.

One edit exists: `fm_set_player_training_intensity` (one managed player's stored club training
intensity; see `training_editor.py`)."""
from .tools import register_training_edit_tools


def register(mcp, bridge) -> list[str]:
    """Called by `fm_live_mcp.server` for an extension named in FMCP_EXTENSIONS."""
    register_training_edit_tools(mcp, bridge)
    if bridge is not None:
        bridge.write_module = True
    return ['fm_set_player_training_intensity']
