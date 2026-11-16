"""Optional installed NATION labels, separate from serialized career names.

Pinned native provenance: game_plugin SHA256
774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1.
1197AE4 selects language table 9; 13F6BA8 reads its native-ID key and uses
10A19E0 to compare NATION+0C. 13F5BBC copies full/short/abbreviation strings
to NATION+18/+20/+28 and raw language flags to+1F6/+1F7. D7660C reads the
optional u8-counted string/u16/u8 vector. This is installed baseline enrichment;
runtime language choice and career/custom/licensing override precedence are
not established. No label is inferred from a numeric country code.
"""
import hashlib
from ._os_compat import change_time_ns, open_fd, O_NOFOLLOW, O_NONBLOCK
import os
from pathlib import Path
import stat
import struct

from . import build_paths
from . import snapshot_catalog as catalog

# The installed build's database resource (run time; FMCP_PLUGIN_PATH names the installed plugin).
DEFAULT_RESOURCE = build_paths.installed_app() / (
    'Contents/PlugIns/game_plugin.bundle/Contents/Resources/shared/data/'
    'database/db/2600/2600_fm/lang_db.dat'
)
COMPONENT = 'lang_db/8_9.dat'
OUTER_HEADER = bytes.fromhex('03017461642ea00f8d0e0700')
COMPONENT_HEADER = bytes.fromhex('03017461642e8d0e')
MAX_COMPONENT = 1024 * 1024
MAX_ROWS = 10000
MAX_TEXT = 8192


def _parse_labels(data):
    if len(data) > MAX_COMPONENT or data[:8] != COMPONENT_HEADER:
        raise ValueError('Unsupported NATION language component source; expected 3725')
    cursor = 8

    def take(size):
        nonlocal cursor
        if size < 0 or size > len(data) - cursor:
            raise ValueError('Truncated NATION language component')
        result = data[cursor:cursor + size]
        cursor += size
        return result

    def uint(size):
        return int.from_bytes(take(size), 'little')

    def text():
        size = uint(4)
        if size > MAX_TEXT:
            raise ValueError('NATION language text exceeds budget')
        return take(size).decode('utf-8')

    count = uint(4)
    if not 1 <= count <= MAX_ROWS:
        raise ValueError('NATION language row count outside budget')
    labels = {}
    for _ in range(count):
        native_id = uint(4)
        if not native_id or native_id in labels:
            raise ValueError('Missing or duplicate NATION native ID')
        name = text()
        name_flag = uint(1)
        short_name = text()
        short_flag = uint(1)
        abbreviation = text()
        text()  # Native+30 text; not a country display-name field.
        for _ in range(uint(1)):
            text()
            take(3)  # Native auxiliary u16 and raw u8 flag.
        labels[native_id] = {
            'name': name, 'short_name': short_name, 'abbreviation': abbreviation,
            'name_flag': name_flag, 'short_name_flag': short_flag,
        }
    if cursor != len(data):
        raise ValueError('Trailing NATION language component bytes')
    return labels


def _read_resource(path):
    # checked_snapshot requires a .fm file and no leading wrapper. This installed
    # .dat has a verified 12-byte wrapper; reuse its bounded FMF directory codec.
    with os.fdopen(open_fd(path, os.O_RDONLY | O_NOFOLLOW | O_NONBLOCK), 'rb') as handle:
        before = os.fstat(handle.fileno())
        if (not stat.S_ISREG(before.st_mode) or
                catalog._stamp(path.stat(follow_symlinks=False)) != catalog._stamp(before)):
            raise ValueError('Installed language resource is not a stable regular file')

        def read(offset, size):
            if size < 0 or offset < 0 or size > before.st_size - offset:
                raise ValueError('Installed language resource range outside file')
            handle.seek(offset)
            value = handle.read(size)
            if len(value) != size:
                raise ValueError('Truncated installed language resource')
            return value

        header = read(0, 38)
        if header[:12] != OUTER_HEADER:
            raise ValueError('Unsupported installed language resource source/version')
        if header[12:21] != catalog.MAGIC:
            raise ValueError('Unsupported installed language archive version')
        table_offset = 30 + struct.unpack_from('<Q', header, 21)[0]
        table_size = before.st_size - table_offset
        if table_offset < 47 or not 1 <= table_size <= catalog.MAX_TABLE_PACKED:
            raise ValueError('Installed language directory outside bounded range')
        footer = read(table_offset - 9, 9)
        if footer != catalog.MAGIC:
            raise ValueError('Installed language archive footer mismatch')
        packed_table = read(table_offset, table_size)
        table = catalog._decompress(packed_table, catalog.MAX_TABLE_RAW)
        entries = catalog._parse_table(table, table_offset - 47)
        selected = [entry for entry in entries if entry.path == COMPONENT]
        if len(selected) != 1:
            raise ValueError('Required installed language component lang_db/8_9.dat missing')
        entry = selected[0]
        if not (4 <= entry.compressed_size <= MAX_COMPONENT and
                12 <= entry.uncompressed_size <= MAX_COMPONENT):
            raise ValueError('NATION language component exceeds bounded profile')
        packed = read(38 + entry.start, entry.compressed_size)
        if packed[:4] != catalog.FRAME:
            raise ValueError('Invalid NATION language component frame')
        data = catalog._decompress(packed, entry.uncompressed_size)
        if len(data) != entry.uncompressed_size:
            raise ValueError('NATION language component length mismatch')
        labels = _parse_labels(data)
        if (catalog._stamp(os.fstat(handle.fileno())) != catalog._stamp(before) or
                catalog._stamp(path.stat(follow_symlinks=False)) != catalog._stamp(before) or
                read(0, 38) != header or read(table_offset - 9, 9) != footer or
                read(table_offset, table_size) != packed_table or
                read(38 + entry.start, entry.compressed_size) != packed or
                catalog._stamp(os.fstat(handle.fileno())) != catalog._stamp(before) or
                catalog._stamp(path.stat(follow_symlinks=False)) != catalog._stamp(before)):
            raise ValueError('Installed language resource changed during request')
        return labels, {
            'identity': dict(device=before.st_dev, inode=before.st_ino, size=before.st_size,
                             mtime_ns=before.st_mtime_ns, ctime_ns=change_time_ns(before)),
            'directory_sha256': hashlib.sha256(table).hexdigest(),
            'component_sha256': hashlib.sha256(data).hexdigest(),
            'component_compressed_sha256': hashlib.sha256(packed).hexdigest(),
            'component_raw_size': len(data), 'row_count': len(labels),
        }


def load_english_nation_labels():
    """Return optional source metadata and labels keyed by NATION native ID.

    Missing/inaccessible resources are unavailable; malformed, replaced or
    unsupported resources are unsupported. Both return empty labels, so optional
    enrichment cannot invalidate a saved-data query. Flags remain raw bytes.
    """
    metadata = {
        'source': 'installed_database_baseline', 'database_version': '2600',
        'language_id': 8, 'resource_component': COMPONENT, 'source_major': 3725,
        'saved_name_equivalence': False, 'career_display_equivalence': 'unverified',
        'language_selection': 'explicit resource 8; career language is unverified',
    }
    try:
        labels, checked = _read_resource(DEFAULT_RESOURCE)
    except OSError as error:
        reason = f'Installed language resource unavailable: {error.strerror or type(error).__name__}'
        return {'status': 'unavailable', 'reason': reason, 'metadata': metadata, 'labels': {}}
    except (ValueError, UnicodeError, struct.error) as error:
        return {'status': 'unsupported', 'reason': str(error), 'metadata': metadata, 'labels': {}}
    return {'status': 'available', 'reason': None, 'metadata': {**metadata, **checked}, 'labels': labels}
