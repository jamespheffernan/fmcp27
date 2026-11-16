"""Game-build files of the Mac package: collect them when packaging, seed them on a player's Mac.

The reader carries the addresses of game build 27.0.0.2493426 in its source. For any later
build it needs that build's address map, anchors, front-end registry files and read plans,
which scripts/fm_update_build.py derives from the preserved files of the pinned build. A
player has no pinned build to derive from, so the package ships the derived files of the
builds it supports under builds/, laid out like the reader's cache:

    builds/anchors/<plugin sha256>.addresses.json
    builds/anchors/<plugin sha256>.json
    builds/anchors/<plugin sha256>.ui_frontend.json.gz
    builds/anchors/<plugin sha256>.ui_registry.json.gz
    builds/plans/<plugin sha256>.v2.json

    python seed_builds.py collect <cache>/fmdb <plugin sha256> <package>/builds
        (scripts/package_mac.sh) copies them out of the packager's cache. The files record
        absolute paths under the packager's home folder; those are replaced by a marker so
        that no user name ships.

    python seed_builds.py scrub <package>/fm_live_mcp/fmdb/data
        (scripts/package_mac.sh) replaces the packager's home folder in the reader's shipped
        data files, where recordings list the files they read, with /Users/player.

    python seed_builds.py seed <package>/builds <cache>/fmdb <package commit>
        (fmcp27-mcp, at every start; a no-op once done) writes them into the player's cache
        with the marker replaced by the player's home folder. The anchors files are written
        again when the package commit changes; a plan file is written only when the player
        has none, because the reader extends it on the player's Mac.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path

MARKER = '@FMCP27_HOME@'
ANCHOR_SUFFIXES = ('.addresses.json', '.json', '.ui_frontend.json.gz', '.ui_registry.json.gz')
PLAN_SUFFIX = '.v2.json'
STAMP = '.fmcp27-package'


def _read(path: Path) -> str:
    raw = path.read_bytes()
    return (gzip.decompress(raw) if path.suffix == '.gz' else raw).decode('utf-8')


def _write(path: Path, text: str) -> None:
    raw = text.encode('utf-8')
    if path.suffix == '.gz':
        raw = gzip.compress(raw, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + f'.partial{os.getpid()}')
    partial.write_bytes(raw)
    os.replace(partial, path)


def _json_fragment(text: str) -> str:
    """`text` as it appears inside a JSON string (quotes and backslashes escaped)."""
    return json.dumps(text)[1:-1]


def collect(cache: Path, sha256: str, out: Path) -> int:
    home = _json_fragment(str(Path.home()))
    pairs = [(cache / 'anchors' / f'{sha256}{suffix}', out / 'anchors' / f'{sha256}{suffix}')
             for suffix in ANCHOR_SUFFIXES]
    pairs.append((cache / 'plans' / f'{sha256}{PLAN_SUFFIX}', out / 'plans' / f'{sha256}{PLAN_SUFFIX}'))
    missing = [str(source) for source, _ in pairs if not source.is_file()]
    if missing:
        print('seed_builds: this game build has no derived files in the cache; run '
              'scripts/fm_update_build.py --installed first. Missing:\n  ' + '\n  '.join(missing), file=sys.stderr)
        return 1
    user = Path.home().name
    for source, target in pairs:
        text = _read(source).replace(home, MARKER)
        if user and user in text:
            print(f'seed_builds: {source.name} still names the packaging user after the home folder was replaced',
                  file=sys.stderr)
            return 1
        json.loads(text)
        _write(target, text)
    return 0


def scrub(folder: Path) -> int:
    """Replace the packager's home folder in the reader's own data files (recorded file lists)."""
    home = _json_fragment(str(Path.home()))
    for path in sorted(folder.glob('*.json')) + sorted(folder.glob('*.json.gz')):
        text = _read(path)
        if home in text:
            _write(path, text.replace(home, '/Users/player'))
            print(f'seed_builds: replaced the home folder in {path.name}', file=sys.stderr)
    return 0


def seed(builds: Path, cache: Path, commit: str) -> int:
    if not builds.is_dir():
        return 0
    stamp = cache / 'anchors' / STAMP
    current = stamp.read_text().strip() if stamp.is_file() else ''
    home = _json_fragment(str(Path.home()))
    for source in sorted((builds / 'anchors').glob('*')):
        target = cache / 'anchors' / source.name
        if current != commit or not target.is_file():
            _write(target, _read(source).replace(MARKER, home))
    for source in sorted((builds / 'plans').glob('*')):
        target = cache / 'plans' / source.name
        if not target.is_file():
            _write(target, _read(source).replace(MARKER, home))
    if current != commit:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(commit + '\n')
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 5 and argv[1] == 'collect':
        return collect(Path(argv[2]), argv[3], Path(argv[4]))
    if len(argv) == 5 and argv[1] == 'seed':
        return seed(Path(argv[2]), Path(argv[3]), argv[4])
    if len(argv) == 3 and argv[1] == 'scrub':
        return scrub(Path(argv[2]))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
