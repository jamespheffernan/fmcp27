"""Check archived-statistics instruction spans against the pinned native ARM64 build."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import (archive_stat_references, archived_player_statistics,
                        player_statistics, stats_archive)

from fm_live_mcp import build_paths  # noqa: E402

PLUGIN = build_paths.pinned_path(build_paths.PLUGIN_IN_APP)   # the pinned build (EXPECTED)
EXPECTED = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
SLICE = 0x5ED4000
MODULES = (player_statistics, archived_player_statistics, archive_stat_references, stats_archive)


def main():
    modules = {}
    with PLUGIN.open('rb') as executable:
        digest = hashlib.file_digest(executable, 'sha256').hexdigest()
        if digest != EXPECTED:
            raise ValueError('Unsupported game plugin hash')
        for module in MODULES:
            spans = module.NATIVE_SPANS
            entries = spans.items() if isinstance(spans, dict) else spans
            count = checked = 0
            for rva, raw in entries:
                expected = bytes.fromhex(raw) if isinstance(raw, str) else raw
                executable.seek(SLICE + rva)
                if executable.read(len(expected)) != expected:
                    raise ValueError(f'{module.__name__} instruction span changed at {rva:#x}')
                count += 1
                checked += len(expected)
            modules[module.__name__] = {'instruction_spans': count, 'bytes_checked': checked}
    print(json.dumps({
        'verified': True, 'plugin_sha256': digest, 'modules': modules,
        'instruction_spans': sum(row['instruction_spans'] for row in modules.values()),
        'bytes_checked': sum(row['bytes_checked'] for row in modules.values()),
        'scope': 'Offline instruction layout only; no live source, reference encoding or UI equivalence check.',
        'native_execution': False,
    }))


if __name__ == '__main__':
    main()
