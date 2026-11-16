#!/usr/bin/env python3
"""Export a committed source snapshot without private history or local evidence.

Usage: python3 scripts/export_public.py /absolute/path/to/empty-directory [REF]
The export is a review candidate, not an automatic publication or secret scan.
"""
from __future__ import annotations

import argparse
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

SOURCE_DIRS = frozenset({
    'adviser', 'docs', 'fm_live_mcp', 'fm_live_write', 'native',
    'packaging', 'scripts', 'site', 'tests', 'tools', '.github',
})
ROOT_FILES = frozenset({
    '.gitignore', 'README.md', 'CHANGELOG.md', 'CONTRIBUTING.md',
    'LICENSE', 'LICENSE.md', 'pyproject.toml', 'uv.lock',
    'HOST_PERIOD_EVIDENCE.md', 'RETAINED_PAIRED_WIDTH.md', 'RETAINED_PASS_PERIODS.md',
})
PRIVATE_PARTS = frozenset({
    '.git', '.claude', '.impeccable', '.venv', 'node_modules',
    'evidence', 'sessions', 'tmp', '.cache', '.wrangler', '__pycache__',
})
PRIVATE_SUFFIXES = ('.pem', '.key', '.p8', '.p12', '.mobileprovision', '.fm', '.fm.bak', '.log')


def publishable(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        return False
    if path.parts[0] not in SOURCE_DIRS and name not in ROOT_FILES:
        return False
    if any(part in PRIVATE_PARTS for part in path.parts):
        return False
    if path.name.startswith('.env') and path.name != '.env.example':
        return False
    if name.endswith(PRIVATE_SUFFIXES):
        return False
    if name.startswith(('site/public/download/', 'adviser/evals/out/')):
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('ref', nargs='?', default='HEAD')
    args = parser.parse_args()
    dest = args.destination.resolve()
    if dest.exists() and any(dest.iterdir()):
        parser.error('destination must be empty; existing work is never overwritten')
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.check_output(
        ['git', 'rev-parse', '--verify', args.ref + '^{commit}'], cwd=root, text=True,
    ).strip()
    dest.mkdir(parents=True, exist_ok=True)
    count = total = 0
    process = subprocess.Popen(['git', 'archive', revision], cwd=root, stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
            for member in archive:
                if not publishable(member.name) or member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError(f'non-regular public file requires review: {member.name}')
                content = archive.extractfile(member).read()
                target = dest / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
                count += 1
                total += len(content)
        if process.wait() != 0:
            raise RuntimeError('git archive failed; do not publish this export')
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.terminate()
            process.wait()
    print(f'Exported {count} files ({total:,} bytes) from {revision} to {dest}')
    print('Review and scan this directory before committing it to the public repository.')


if __name__ == '__main__':
    main()
