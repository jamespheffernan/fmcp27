"""Explicit host-only enrichment of an immutable native period observation.

The old observation/capture ID and finalized links are never modified. A report
must pass normal link_retained epoch/pin checks before consulting this separate
metric witness. No capture, current retained byte or game read creates a witness.
"""
from datetime import datetime, timezone
from ._os_compat import O_NOFOLLOW, current_uid, group_or_other_access, open_fd, sync_directory
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from .match_period_observations import canonical, digest, make_observation, validate_observation

MAX_BYTES = 65536
POLICY = 'original_terminal_possession_period_attestation_v1'


def build(original_terminal_bytes, parent):
    """Reproduce the parent from its pinned original, then derive new fields."""
    from .retained_possession_periods import possession_period_fingerprint
    validate_observation(parent)
    if (parent.get('capture_method') != 'verified_retrospective_authentic_bundle'
            or not parent.get('cross_observation')):
        raise ValueError('Reviewed authentic terminal parent observation required')
    if type(original_terminal_bytes) is not bytes or len(original_terminal_bytes) > 4 * 1024 * 1024:
        raise ValueError('Invalid bounded original terminal bytes')
    terminal_sha = hashlib.sha256(original_terminal_bytes).hexdigest()
    if terminal_sha != parent.get('seed_provenance', {}).get('terminal_sha256'):
        raise ValueError('Original terminal SHA differs from immutable parent')
    terminal = json.loads(original_terminal_bytes)
    if not terminal.get('verified_readset') or terminal.get('displayed_period') != 'FullTime':
        raise ValueError('Verified original terminal source required')
    source = dict(terminal['raw_source'])
    source['events'] = bytes.fromhex(source['events']['hex'])
    source['vectors'] = [bytes.fromhex(vector['hex']) for vector in source['vectors']]
    expected = make_observation(terminal['save'], terminal['fixture'], terminal['bound_playback'],
        terminal['period_split'], source, terminal['process_load_epoch'],
        datetime.fromtimestamp(terminal['observed_at_unix'], timezone.utc).isoformat())
    fields = ('career', 'fixture', 'official_match_unique_id', 'process_load_epoch', 'observed_at',
              'fingerprint_cursor', 'attempt_prefix', 'period_markers', 'intervals', 'clock_domain',
              'boundary_policy', 'source_hashes', 'pass_event_fingerprint', 'pass_period_report_fingerprint')
    for field in fields:
        if parent.get(field) != expected.get(field):
            raise ValueError('Original terminal cannot reproduce immutable parent: ' + field)
    payload = dict(schema=1, policy=POLICY, parent_capture_id=digest(parent),
        original_terminal_sha256=terminal_sha, parent_event_source_sha256=parent['source_hashes']['events'],
        fingerprint=possession_period_fingerprint(source['events'], parent['fingerprint_cursor']),
        provenance='derived_only_from_pinned_original_terminal_not_current_retained_source',
        original_observation_modified=False, existing_links_modified=False, fresh_match_observation=False)
    document = dict(attestation_id=digest(payload), attestation=payload)
    validate(document, parent)
    return document


def validate(document, parent):
    from .retained_possession_periods import validate_fingerprint
    if type(document) is not dict:
        raise ValueError('Invalid possession period attestation document')
    payload = document.get('attestation')
    if (type(payload) is not dict or document.get('attestation_id') != digest(payload)
            or type(payload.get('schema')) is not int or payload.get('schema') != 1 or payload.get('policy') != POLICY
            or payload.get('parent_capture_id') != digest(parent)
            or payload.get('parent_event_source_sha256') != parent.get('source_hashes', {}).get('events')
            or not payload.get('original_terminal_sha256')
            or payload.get('original_terminal_sha256') != parent.get('seed_provenance', {}).get('terminal_sha256')
            or payload.get('provenance') != 'derived_only_from_pinned_original_terminal_not_current_retained_source'
            or payload.get('original_observation_modified') is not False
            or payload.get('existing_links_modified') is not False
            or payload.get('fresh_match_observation') is not False):
        raise ValueError('Possession period attestation parent/provenance differs')
    validate_fingerprint(payload['fingerprint'], parent.get('fingerprint_cursor'))
    return payload['fingerprint']


def _path(root, parent_id):
    if not isinstance(parent_id, str) or len(parent_id) != 64 or any(c not in '0123456789abcdef' for c in parent_id):
        raise ValueError('Invalid parent capture ID')
    root = Path(root)
    if not root.is_absolute():
        raise ValueError('Absolute period observation root required')
    return root / 'possession-period-attestations-v1' / (parent_id + '.json')


def load(root, parent):
    path = _path(root, digest(parent))
    for directory in (Path(root), path.parent):
        try:
            info = directory.lstat()
        except FileNotFoundError:
            return None
        if (not stat.S_ISDIR(info.st_mode) or directory.is_symlink()
                or info.st_uid != current_uid() or group_or_other_access(info)):
            raise ValueError('Unsafe possession period attestation directory')
    try:
        descriptor = open_fd(path, os.O_RDONLY | O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError('Unsafe possession period attestation file') from error
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != current_uid()
                or group_or_other_access(info) or info.st_size > MAX_BYTES):
            raise ValueError('Unsafe possession period attestation metadata')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(descriptor)
        current = path.lstat()
        if (len(raw) > MAX_BYTES or (info.st_ino, info.st_size, info.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns)
                or current.st_ino != info.st_ino):
            raise ValueError('Possession period attestation changed during read')
    finally:
        os.close(descriptor)
    document = json.loads(raw)
    validate(document, parent)
    return document


def _publication_bytes(path):
    """Read one bounded private regular file without following a final symlink."""
    descriptor = open_fd(path, os.O_RDONLY | O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != current_uid()
                or group_or_other_access(before) or before.st_size > MAX_BYTES):
            raise ValueError('Unsafe artifact publication file')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(descriptor)
        current = Path(path).lstat()
        if (len(raw) > MAX_BYTES or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError('Artifact changed during publication readback')
        return raw
    finally:
        os.close(descriptor)


def _sync_publication_directory(directory):
    sync_directory(directory)


def publish_new_artifact(path, raw):
    """Publish only complete fsynced bytes, atomically and without overwrite.

    The hard-link is the commit point. Before it, failures remove only our
    unpublished staging inode. After it, a complete final may remain on failure;
    retry verifies identical bytes and is idempotent. Final paths are never
    unlinked: a raced replacement must never be deleted by rollback.
    """
    path = Path(path)
    if not path.is_absolute() or type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('Invalid bounded artifact publication')
    directory = path.parent.lstat()
    if (not stat.S_ISDIR(directory.st_mode) or path.parent.is_symlink()
            or directory.st_uid != current_uid()):
        raise ValueError('Unsafe artifact publication directory')
    try:
        existing = _publication_bytes(path)
    except FileNotFoundError:
        pass
    else:
        if existing != raw:
            raise ValueError('Existing artifact differs; never overwrite')
        _sync_publication_directory(path.parent)
        return False
    descriptor, name = tempfile.mkstemp(prefix='.possession-period-artifact-', dir=path.parent)
    staging = Path(name)
    own = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, 'wb', closefd=False) as stream:
            if stream.write(raw) != len(raw):
                raise OSError('Incomplete artifact staging write')
            stream.flush()
            os.fsync(stream.fileno())
        if _publication_bytes(staging) != raw:
            raise ValueError('Artifact staging readback differs')
        current = staging.lstat()
        if (current.st_dev, current.st_ino) != (own.st_dev, own.st_ino):
            raise ValueError('Artifact staging inode changed')
        try:
            os.link(staging, path, follow_symlinks=False)
        except FileExistsError:
            created = False
        else:
            created = True
        if _publication_bytes(path) != raw:
            raise ValueError('Artifact final readback differs; final left untouched')
        _sync_publication_directory(path.parent)
        return created
    finally:
        os.close(descriptor)
        try:
            current = staging.lstat()
        except FileNotFoundError:
            pass
        else:
            if (current.st_dev, current.st_ino) == (own.st_dev, own.st_ino):
                staging.unlink()


def write(root, parent, document):
    """Explicit append-only host import; never called by the game read route."""
    validate(document, parent)
    path = _path(root, digest(parent))
    for directory in (Path(root), path.parent):
        directory.mkdir(parents=directory == Path(root), exist_ok=True, mode=0o700)
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or directory.is_symlink()
                or info.st_uid != current_uid() or group_or_other_access(info)):
            raise ValueError('Unsafe possession period attestation directory')
    created = publish_new_artifact(path, canonical(document))
    if load(root, parent) != document:
        raise ValueError('Possession period attestation readback differs')
    return dict(state='imported' if created else 'already_imported', path=str(path), attestation_id=document['attestation_id'])
