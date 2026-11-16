"""Optional process-local immutable spools, with fresh original bytes per lease.

FMCP_CACHE_DIR explicitly enables disk caching. Without a usable private external
configuration the caller retains its original in-memory path; this module never
chooses another disk directory. Cache files are unlinked before publication and
have no writable descriptor. Only pinned, complete, digest-checked frames enter
the LRU. The caller must retain checked_snapshot's entry/exit validation.
"""
import atexit
from ._os_compat import current_uid, group_or_other_access, unlinked_spool
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import mmap
import os
from pathlib import Path
import stat
from threading import RLock

from . import saved_component_stream as stream

MAX_BYTES = 512 * 1024**2
MAX_ENTRIES = 2
_LOCK = RLock()
_ENTRIES = OrderedDict()
_LAST_STATUS = {'state': 'not_used'}


@dataclass
class _Entry:
    data: object
    size: int
    raw_digest: bytes
    users: int = 0


def status():
    with _LOCK:
        return {**_LAST_STATUS, 'entries': len(_ENTRIES),
                'cached_bytes': sum(e.size for e in _ENTRIES.values())}


def _directory():
    value = os.environ.get('FMCP_CACHE_DIR')
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        return None
    try:
        # The configured parent must already exist. No fallback or recursive
        # creation can silently move bulk data onto another filesystem.
        path.mkdir(mode=0o700, exist_ok=True)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != current_uid() or group_or_other_access(info):
            return None
        return path
    except OSError:
        return None


def _packed_digest(handle, component):
    if any(type(n) is not int or n < 0 for n in
           (component.start, component.compressed_size, component.uncompressed_size)):
        raise ValueError('Invalid cached component extent')
    if not (1 <= component.compressed_size <= stream.MAX_PACKED_SIZE
            and 1 <= component.uncompressed_size <= stream.MAX_RAW_SIZE):
        raise ValueError('Cached component exceeds source size budget')
    handle.seek(26 + component.start)
    remaining = component.compressed_size
    digest = sha256()
    while remaining:
        block = handle.read(min(stream.BLOCK_SIZE, remaining))
        if not block:
            raise ValueError('Truncated original cached component')
        digest.update(block)
        remaining -= len(block)
    return digest.digest()


def _evict(required):
    while len(_ENTRIES) >= MAX_ENTRIES or sum(e.size for e in _ENTRIES.values()) + required > MAX_BYTES:
        key = next((k for k, e in _ENTRIES.items() if not e.users), None)
        if key is None:
            raise ValueError('Saved source cache budget is leased; retry later')
        entry = _ENTRIES[key]
        entry.data.close()
        del _ENTRIES[key]


def _create(handle, component, directory):
    # The spool has no name from the start: interruption during decompression
    # cannot leave a large orphan. The independent read-only descriptor
    # remains valid while the sole writer is filled and then closed.
    writer_fd, readonly_fd = unlinked_spool(directory, 'fmcp-source-')
    mapping = None
    try:
        digest = sha256()
        with os.fdopen(writer_fd, 'wb') as output:
            writer_fd = None
            with stream.open_component(handle, component) as reader:
                while reader.offset < reader.size:
                    block = reader.take(min(stream.BLOCK_SIZE, reader.size - reader.offset))
                    output.write(block)
                    digest.update(block)
                if reader.source.read(1) or not reader.source.finished:
                    raise ValueError('Cached source frame did not finish at its declared extent')
        if os.fstat(readonly_fd).st_size != component.uncompressed_size:
            raise ValueError('Cached source spool extent differs')
        mapping = mmap.mmap(readonly_fd, component.uncompressed_size, access=mmap.ACCESS_READ)
        if sha256(mapping).digest() != digest.digest():
            raise ValueError('Cached source spool digest differs')
        entry = _Entry(mapping, component.uncompressed_size, digest.digest())
        mapping = None
        return entry
    finally:
        if writer_fd is not None:
            os.close(writer_fd)
        os.close(readonly_fd)
        if mapping is not None:
            mapping.close()


@contextmanager
def source(handle, component, snapshot_id):
    """Yield a borrowed read-only mapping, or None for the old memory path.

    Original compressed bytes are freshly read and hashed on every enabled
    request, including hits. Snapshot identity alone never authorizes a hit.
    """
    global _LAST_STATUS
    directory = _directory()
    if directory is None:
        with _LOCK:
            _LAST_STATUS = {'state': 'disabled_or_unavailable'}
        yield None
        return
    packed = _packed_digest(handle, component)
    key = (str(directory), snapshot_id, component.path, component.uncompressed_size, packed)
    with _LOCK:
        entry = _ENTRIES.get(key)
        hit = entry is not None
        if entry is None:
            if component.uncompressed_size > MAX_BYTES or MAX_ENTRIES < 1:
                raise ValueError('Saved source exceeds configured cache budget')
            _evict(component.uncompressed_size)
            entry = _create(handle, component, directory)
            try:
                if _packed_digest(handle, component) != packed:
                    raise ValueError('Original cached component changed during creation')
            except BaseException:
                entry.data.close()
                raise
            _ENTRIES[key] = entry
        entry.users += 1
        _ENTRIES.move_to_end(key)
        _LAST_STATUS = {'state': 'hit' if hit else 'created',
                        'directory': str(directory), 'packed_sha256': packed.hex(),
                        'raw_sha256': entry.raw_digest.hex()}
    try:
        yield entry.data
    finally:
        with _LOCK:
            entry.users -= 1


def clear():
    """Release idle spools; never close a mapping during an active request."""
    with _LOCK:
        for key, entry in list(_ENTRIES.items()):
            if not entry.users:
                entry.data.close()
                del _ENTRIES[key]


atexit.register(clear)
