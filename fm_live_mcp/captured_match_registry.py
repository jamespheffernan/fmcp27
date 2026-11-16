"""Explicit local CLI registration of existing historical match exports.

The MCP exposes source IDs, never filesystem paths. This small catalog contains
only references chosen by a user or an explicit export --register-capture flag.
It never scans a directory and never copies or changes a capture.
"""
import argparse
from ._os_compat import change_time_ns, open_fd, O_NOFOLLOW
from contextlib import contextmanager
from datetime import datetime, timezone
from ._filelock import lock_exclusive
import json
import os
from pathlib import Path
import re
import stat
import sqlite3
import tempfile

REGISTRY_PATH = Path.home() / '.local/share/fm-live/captured-match-sources.json'
MAX_REGISTRATIONS = 64
MAX_REGISTRY_BYTES = 1024 * 1024


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', value):
        raise ValueError('source_id must use 1–80 lowercase letters, digits or underscores, starting with a letter')


def _sha256(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('sha256 must be an exact lowercase SHA256 digest')


def _regular_file(path, limit):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
        raise ValueError('Capture registry must be a bounded regular file, not a symlink')
    return info


def load_registrations():
    """Reload on each request; absence is empty, corruption fails closed."""
    try:
        before = _regular_file(REGISTRY_PATH, MAX_REGISTRY_BYTES)
    except FileNotFoundError:
        return {}
    raw = REGISTRY_PATH.read_bytes()
    after = REGISTRY_PATH.lstat()
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, change_time_ns(info))
    if identity(before) != identity(after):
        raise ValueError('Capture registry changed during read; retry')
    document = json.loads(raw)
    if not isinstance(document, dict) or document.get('version') != 1:
        raise ValueError('Unsupported capture registry format')
    entries = document.get('sources')
    if not isinstance(entries, dict) or len(entries) > MAX_REGISTRATIONS:
        raise ValueError('Capture registry source budget exceeded')
    for source_id, entry in entries.items():
        _identifier(source_id)
        if not isinstance(entry, dict):
            raise ValueError('Invalid capture registration')
        _sha256(entry.get('sha256'))
        path = entry.get('path')
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError('Registered capture path must be absolute')
        if not isinstance(entry.get('career'), dict) or not isinstance(entry.get('scope'), dict):
            raise ValueError('Registered capture requires verified career and scope')
    return entries


@contextmanager
def _locked_registry():
    parent = REGISTRY_PATH.parent
    parent.mkdir(parents=True, exist_ok=True)
    if not stat.S_ISDIR(parent.lstat().st_mode):
        raise ValueError('Capture registry parent must be a real directory')
    lock_path = parent / (REGISTRY_PATH.name + '.lock')
    descriptor = open_fd(lock_path, os.O_RDWR | os.O_CREAT | O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError('Capture registry lock must be a regular file')
        lock_exclusive(descriptor)
        yield
    finally:
        os.close(descriptor)


def check_registration_id(source_id):
    from .captured_match_sources import SOURCES
    _identifier(source_id)
    if source_id in SOURCES:
        raise ValueError('Built-in capture source IDs cannot be replaced')
    if source_id in load_registrations():
        raise FileExistsError('Capture source ID is already registered; choose a new ID')


def register_capture(path, source_id, sha256, *, label=None):
    """Pin a verified original; neither an existing ID nor capture is replaced."""
    from .captured_match_sources import EXPECTED_CAREER, _open_capture, registration_scope
    check_registration_id(source_id)
    _sha256(sha256)
    if label is not None and (not isinstance(label, str) or not 1 <= len(label) <= 200 or any(ord(c) < 32 for c in label)):
        raise ValueError('label must contain 1–200 printable characters')
    path = Path(path).expanduser().absolute()
    # Check the supplied leaf before resolving platform aliases such as /var.
    if path.is_symlink():
        raise ValueError('Register the regular original capture, not a symlink')
    path = path.resolve(strict=True)
    draft = {'path': str(path), 'sha256': sha256, 'label': label or source_id}
    with _open_capture(path, source_id, sha256, registration=draft) as (_, provenance):
        draft['career'] = {key: provenance['captured_save'][key] for key in EXPECTED_CAREER}
        draft['scope'] = registration_scope(provenance)
        draft['table_counts_at_registration'] = provenance['counts']
        draft['registered_at_utc'] = datetime.now(timezone.utc).isoformat()
    with _locked_registry():
        entries = load_registrations()
        if source_id in entries:
            raise FileExistsError('Capture source ID is already registered; choose a new ID')
        if len(entries) >= MAX_REGISTRATIONS:
            raise ValueError('Capture registry source budget exceeded')
        if any(entry['path'] == str(path) for entry in entries.values()):
            raise FileExistsError('This capture original is already registered')
        # Recheck the exact original while publishing its immutable registration.
        with _open_capture(path, source_id, sha256, registration=draft):
            entries[source_id] = draft
            encoded = (json.dumps({'version': 1, 'sources': entries}, indent=2, ensure_ascii=False) + '\n').encode()
            if len(encoded) > MAX_REGISTRY_BYTES:
                raise ValueError('Capture registry byte budget exceeded')
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=REGISTRY_PATH.parent, prefix='.capture-registry-', delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                # Existing catalog updates are serialized. Capture source IDs and
                # original files remain immutable; only this manifest is replaced.
                if REGISTRY_PATH.exists() or REGISTRY_PATH.is_symlink():
                    _regular_file(REGISTRY_PATH, MAX_REGISTRY_BYTES)
                os.replace(temporary, REGISTRY_PATH)
                temporary = None
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    return {'source_id': source_id, 'capture_id': sha256, 'career_id': provenance['career_id'],
            'registration_kind': 'explicit_local_cli', 'registered_at_utc': draft['registered_at_utc'],
            'date_coverage': provenance['date_coverage'], 'counts': provenance['counts'],
            'path': str(path), 'original_unchanged': True,
            'claim': 'Pinned historical capture, not the current game or last disk save. Missing fields and unavailable sides remain unknown.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    register = commands.add_parser('register', help='Explicitly register one existing export; no copy or overwrite')
    register.add_argument('path', type=Path)
    register.add_argument('--source-id', required=True)
    register.add_argument('--sha256', required=True, help='Expected SHA256 of the original export')
    register.add_argument('--label')
    commands.add_parser('list', help='List built-in and explicitly registered historical captures')
    args = parser.parse_args(argv)
    try:
        if args.command == 'register':
            result = register_capture(args.path, args.source_id, args.sha256, label=args.label)
        else:
            from .captured_match_sources import catalog_sources
            result = catalog_sources()
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(2, str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
