"""Bounded, read-only FMF8 snapshot inventory; never reads large payloads."""
from contextlib import contextmanager
from ._os_compat import change_time_ns, open_fd, O_NOFOLLOW, O_NONBLOCK
import ctypes
import ctypes.util
from dataclasses import dataclass
import hashlib
import datetime
import json
import os
from pathlib import Path
import stat
import struct

MAGIC = bytes.fromhex('0201666d662e080000')
FRAME = bytes.fromhex('28b52ffd')
MAX_TABLE_PACKED = 1024 * 1024
MAX_TABLE_RAW = 4 * 1024 * 1024
DEFAULT_DIRECTORY = Path.home() / 'Library/Application Support/Sports Interactive/Football Manager 27/games'


def _decompress(data, capacity):
    library = ctypes.util.find_library('zstd')
    if not library:
        raise ValueError('Zstandard library unavailable; install libzstd')
    lib = ctypes.CDLL(library)
    lib.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    lib.ZSTD_decompress.restype = ctypes.c_size_t
    lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
    lib.ZSTD_isError.restype = ctypes.c_uint
    lib.ZSTD_findFrameCompressedSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    lib.ZSTD_findFrameCompressedSize.restype = ctypes.c_size_t
    if lib.ZSTD_findFrameCompressedSize(data, len(data)) != len(data):
        raise ValueError('Invalid or trailing compressed frame')
    output = ctypes.create_string_buffer(capacity)
    size = lib.ZSTD_decompress(output, capacity, data, len(data))
    if lib.ZSTD_isError(size) or size > capacity:
        raise ValueError('Invalid or oversized compressed frame')
    return output.raw[:size]


def _stamp(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, change_time_ns(value))


def _page(offset, limit):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('Invalid pagination; limit must be 1..500')


def _directory(directory):
    result = Path(directory if directory is not None else DEFAULT_DIRECTORY).expanduser().resolve(strict=True)
    if not result.is_dir():
        raise ValueError('Selected save directory is not a directory')
    return result


@dataclass(frozen=True)
class Component:
    path: str
    start: int
    compressed_size: int
    uncompressed_size: int


def _parse_table(table, payload_size):
    cursor = 0
    entries = []
    seen = set()
    def take(n):
        nonlocal cursor
        if n < 0 or cursor + n > len(table):
            raise ValueError('Truncated archive directory')
        value = table[cursor:cursor+n]
        cursor += n
        return value
    def uint():
        return struct.unpack('<I', take(4))[0]
    def name(allow_empty=False):
        size = uint()
        if size > 1024:
            raise ValueError('Archive name exceeds budget')
        value = take(size).decode('utf-8')
        if ((not value and not allow_empty) or value in ('.', '..') or
                any(c in value for c in '/\\') or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError('Invalid archive relative name')
        return value
    def walk(parents):
        if len(parents) >= 8:
            raise ValueError('Archive directory depth exceeds budget')
        part = name()
        path = parents + (part,)
        key = '/'.join(path)
        if key in seen:
            raise ValueError('Duplicate archive path')
        seen.add(key)
        count = uint()
        if count > 5000 or len(entries) + count > 10000:
            raise ValueError('Archive component count exceeds budget')
        for _ in range(count):
            filename = name() + name(allow_empty=True)
            full = '/'.join(path + (filename,))
            start, packed, raw, _, _ = struct.unpack('<5Q', take(40))
            if full in seen or not packed or start + packed > payload_size:
                raise ValueError('Duplicate or out-of-bounds archive component')
            seen.add(full)
            entries.append(Component(full, start, packed, raw))
        children = uint()
        if children > 100:
            raise ValueError('Archive child count exceeds budget')
        for _ in range(children):
            walk(path)
    walk(())
    if cursor != len(table) or not entries:
        raise ValueError('Trailing or empty archive directory')
    end = 0
    for entry in sorted(entries, key=lambda row: row.start):
        if entry.start != end:
            raise ValueError('Archive payload gap or overlap')
        end += entry.compressed_size
    if end != payload_size:
        raise ValueError('Archive payload length mismatch')
    return tuple(sorted(entries, key=lambda row: row.path))


@contextmanager
def checked_snapshot(path, *, directory=None):
    """Yield (open handle, immutable components, identity); verify again on exit."""
    root = _directory(directory)
    selected = Path(path).expanduser()
    if not selected.is_absolute():
        selected = root / selected
    # Do not resolve the leaf: symlinks and replacement names are rejected.
    if selected.parent.resolve(strict=True) != root or selected.suffix.lower() != '.fm':
        raise ValueError('Snapshot must be a direct .fm file in the selected directory')
    with os.fdopen(open_fd(selected, os.O_RDONLY | O_NOFOLLOW | O_NONBLOCK), 'rb') as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or _stamp(selected.stat(follow_symlinks=False)) != _stamp(before):
            raise ValueError('Snapshot is not a stable regular file')
        def read(at, size):
            handle.seek(at)
            value = handle.read(size)
            if len(value) != size:
                raise ValueError('Truncated snapshot')
            return value
        header = read(0, 26)
        if header[:9] != MAGIC:
            raise ValueError('Unsupported snapshot archive version')
        table_offset = struct.unpack_from('<Q', header, 9)[0] + 18
        packed_size = before.st_size - table_offset
        if table_offset < 35 or not 1 <= packed_size <= MAX_TABLE_PACKED:
            raise ValueError('Archive directory outside bounded file range')
        packed = read(table_offset, packed_size)
        table = _decompress(packed, MAX_TABLE_RAW)
        entries = _parse_table(table, table_offset - 35)
        if read(table_offset - 9, 9) != MAGIC:
            raise ValueError('Archive footer mismatch')
        for entry in entries:
            if entry.compressed_size < 4 or read(26 + entry.start, 4) != FRAME:
                raise ValueError('Invalid component frame prefix')
        identity = dict(device=before.st_dev, inode=before.st_ino, size=before.st_size,
                        mtime_ns=before.st_mtime_ns, ctime_ns=change_time_ns(before),
                        directory_sha256=hashlib.sha256(table).hexdigest())
        try:
            yield handle, entries, identity
        finally:
            if (_stamp(os.fstat(handle.fileno())) != _stamp(before) or
                    _stamp(selected.stat(follow_symlinks=False)) != _stamp(before) or
                    read(0, 26) != header or read(table_offset, packed_size) != packed):
                raise ValueError('Snapshot changed during request')


def check_filename(path):
    if not isinstance(path, str) or not path or Path(path).name != path or '/' in path or '\\' in path:
        raise ValueError('Snapshot name must be a single basename')


def snapshot_id(identity):
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def inspect_snapshot(path, *, directory=None, offset=0, limit=100, prefix=None, expected_snapshot_id=None):
    """Page sorted relative paths. Prefix matches literal path starts; offset indexes matches."""
    check_filename(path)
    _page(offset, limit)
    if prefix is not None and (not isinstance(prefix, str) or len(prefix) > 8192 or
            prefix.startswith('/') or '\\' in prefix or any(p in ('.', '..') for p in prefix.split('/'))):
        raise ValueError('Invalid component prefix')
    with checked_snapshot(path, directory=directory) as (handle, entries, identity):
        current_id = snapshot_id(identity)
        if expected_snapshot_id is not None and expected_snapshot_id != current_id:
            raise ValueError('Snapshot identity changed between pages')
        metadata = _metadata(handle, entries)
        filtered = [row for row in entries if prefix is None or row.path.startswith(prefix)]
        return dict(source='on-disk save snapshot', filename=Path(path).name, identity=identity,
                    snapshot_id=current_id, next_offset=offset+limit if offset+limit < len(filtered) else None,
                    total=len(entries), filtered_total=len(filtered), offset=offset, limit=limit,
                    components=[dict(path=row.path, compressed_size=row.compressed_size,
                                     uncompressed_size=row.uncompressed_size) for row in filtered[offset:offset+limit]],
                    archive_root=entries[0].path.split('/')[0], saved_metadata=metadata)


def discover_snapshots(directory=None, *, offset=0, limit=50):
    _page(offset, limit)
    root = _directory(directory)
    names = sorted(p.name for p in root.iterdir() if p.suffix.lower() == '.fm')
    rows = []
    for name in names[offset:offset+limit]:
        try:
            value = inspect_snapshot(name, directory=root, limit=1)
            rows.append(dict(filename=name, status='verified', identity=value['identity'], snapshot_id=value['snapshot_id'], component_count=value['total'], saved_metadata=value['saved_metadata']))
        except (ValueError, OSError, UnicodeError) as error:
            rows.append(dict(filename=name, status='unavailable', reason=str(error)))
    return dict(directory=str(root), total=len(names), offset=offset, limit=limit,
                next_offset=offset+limit if offset+limit < len(names) else None, snapshots=rows)


class SnapshotChangedError(ValueError):
    """Previously consumed snapshot bytes changed during this request."""


# Game versions whose save_game_summary.dat has the layout below (checked on a save written by each:
# 27.0.1 writes the same serializer prefix, version text, lists, people and packed date).
SUMMARY_VERSIONS = frozenset({'27.0.0+2493426', '27.0.1+2503222'})


def _summary(data):
    # Native serializer v31 prefix, sourced in managed-training-15/lead/metadata.py.
    if data[:8] != bytes.fromhex('03017461642e1f00'):
        raise ValueError('Unsupported saved summary serializer')
    cursor = 8
    def take(n):
        nonlocal cursor
        if cursor+n > len(data):
            raise ValueError('Truncated saved summary')
        value = data[cursor:cursor+n]
        cursor += n
        return value
    def uint(n):
        return int.from_bytes(take(n), 'little')
    def string():
        size = uint(4)
        if size > 8192:
            raise ValueError('Saved summary string exceeds budget')
        value = take(size).decode('utf-8')
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Invalid saved summary text')
        return value
    string()
    version = string()
    if version not in SUMMARY_VERSIONS:
        raise ValueError('Unsupported saved summary game version')
    count = uint(4)
    if count > 256:
        raise ValueError('Saved summary list exceeds budget')
    for _ in range(count):
        string()
    take(7)
    people = []
    for _ in range(uint(1)):
        people.append(dict(person_display_name=string(), team_display_name=string(),
                           team_native_id=int.from_bytes(take(4), 'little', signed=True)))
    packed = uint(4)
    year, day = packed >> 16, packed & 511
    if not 1850 <= year <= 2200 or not 1 <= day <= 366:
        raise ValueError('Invalid saved simulation date')
    date = datetime.date(year, 1, 1) + datetime.timedelta(days=day-1)
    if date.year != year:
        raise ValueError('Invalid saved simulation day')
    return dict(status='verified', source='same-file save_game_summary.dat',
                game_version_text=version, saved_simulation_date=str(date), summary_people=people)


def _metadata(handle, entries):
    root = entries[0].path.split('/')[0]
    rows = [row for row in entries if row.path == root+'/save_game_summary.dat']
    try:
        if len(rows) != 1:
            raise ValueError('Missing or ambiguous saved summary component')
        row = rows[0]
        if not 1 <= row.uncompressed_size <= 16384 or row.compressed_size > 16384:
            raise ValueError('Saved summary exceeds bounded reader budget')
        handle.seek(26+row.start)
        packed = handle.read(row.compressed_size)
        data = _decompress(packed, row.uncompressed_size)
        if len(data) != row.uncompressed_size:
            raise ValueError('Saved summary length mismatch')
        result = _summary(data)
        # Re-read the bounded source bytes as well as checking file identity on exit.
        handle.seek(26+row.start)
        if handle.read(row.compressed_size) != packed:
            raise SnapshotChangedError('Saved summary changed during request')
        return result
    except SnapshotChangedError:
        raise
    except (ValueError, UnicodeError) as error:
        return dict(status='unknown', reason=str(error))
