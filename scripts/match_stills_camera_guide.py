"""Optional composition guide: uv run --with matplotlib this.py SCENE OUT.png.

The drawing lives in fm_live_mcp.match_stills_camera_guide; Enhance Mode calls it directly.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fm_live_mcp.match_stills_camera_guide import render


if __name__ == '__main__':
    render(json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2]))
