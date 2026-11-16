"""Verify the current-statistics decoder's instruction spans against the native build."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import current_player_statistics, player_statistics

from fm_live_mcp import build_paths  # noqa: E402

PLUGIN = build_paths.pinned_path(build_paths.PLUGIN_IN_APP)   # the pinned build (EXPECTED)
EXPECTED = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
SLICE = 0x5ED4000


def main():
    spans = list(player_statistics.NATIVE_SPANS)
    spans.extend((rva, bytes.fromhex(raw)) for rva, raw in current_player_statistics.NATIVE_SPANS.items())
    with PLUGIN.open('rb') as executable:
        digest = hashlib.file_digest(executable, 'sha256').hexdigest()
        if digest != EXPECTED:
            raise ValueError('Unsupported game plugin hash')
        for rva, expected in spans:
            executable.seek(SLICE + rva)
            if executable.read(len(expected)) != expected:
                raise ValueError(f'Statistics instruction span changed at {rva:#x}')
    print(json.dumps({'verified': True, 'plugin_sha256': digest,
                      'instruction_spans': len(spans), 'bytes_checked': sum(len(raw) for _, raw in spans),
                      'scope': 'Offline instruction layout only; no live statistics or UI equivalence check.',
                      'native_execution': False}))


if __name__ == '__main__':
    main()
