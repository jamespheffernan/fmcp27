"""Optional verified English injury labels, separate from saved names.

Pinned codec provenance: game_plugin SHA256
774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1.
119A39C selects language table 6;132B218 reads primary-ID keys through
10A4DC8 (INJURY+C).132B0F4 applies its strings to INJURY+18/+20,
exposed as Inam/Isnm. D7660C consumes auxiliary text/u16/u8 rows.
Only the exact source 3725/database 2600 English resource verified with
this codec is accepted. Runtime locale/override equivalence is unproved.
No installed binary or resource is required for core saved-data queries.
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
COMPONENT = 'lang_db/8_6.dat'
OUTER_HEADER = bytes.fromhex('03017461642ea00f8d0e0700')
COMPONENT_HEADER = bytes.fromhex('03017461642e8d0e')
VERIFIED_COMPONENT_SHA256 = '8dee25bb6514fd8c9aace6b0accc00713f4efec9cb8874ff39de813724ee13cd'
NATIVE_CODEC_PLUGIN_SHA256 = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
MAX_COMPONENT = 1024 * 1024
MAX_ROWS = 10000
MAX_TEXT = 8192


def _parse_labels(data):
    if len(data) > MAX_COMPONENT or data[:8] != COMPONENT_HEADER:
        raise ValueError('Unsupported INJURY language component source; expected 3725')
    cursor = 8

    def take(size):
        nonlocal cursor
        if size < 0 or size > len(data) - cursor:
            raise ValueError('Truncated INJURY language component')
        result = data[cursor:cursor + size]
        cursor += size
        return result

    def uint(size):
        return int.from_bytes(take(size), 'little')

    def text():
        size = uint(4)
        if size > MAX_TEXT:
            raise ValueError('INJURY language text exceeds budget')
        return take(size).decode('utf-8')

    count = uint(4)
    if not 1 <= count <= MAX_ROWS:
        raise ValueError('INJURY language row count outside budget')
    labels = {}
    for _ in range(count):
        native_id = uint(4)
        if not native_id or native_id in labels:
            raise ValueError('Missing or duplicate INJURY native ID')
        name = text()
        name_flag = uint(1)
        sentence_name = text()
        sentence_flag = uint(1)
        for _ in range(uint(1)):
            text()
            take(3)  # Native auxiliary u16 and raw u8 flag.
        labels[native_id] = {
            'name': name, 'sentence_name': sentence_name,
            'name_flag': name_flag, 'sentence_name_flag': sentence_flag,
        }
    if cursor != len(data):
        raise ValueError('Trailing INJURY language component bytes')
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
            raise ValueError('Required installed language component lang_db/8_6.dat missing')
        entry = selected[0]
        if not (4 <= entry.compressed_size <= MAX_COMPONENT and
                12 <= entry.uncompressed_size <= MAX_COMPONENT):
            raise ValueError('INJURY language component exceeds bounded profile')
        packed = read(38 + entry.start, entry.compressed_size)
        if packed[:4] != catalog.FRAME:
            raise ValueError('Invalid INJURY language component frame')
        data = catalog._decompress(packed, entry.uncompressed_size)
        if len(data) != entry.uncompressed_size:
            raise ValueError('INJURY language component length mismatch')
        if hashlib.sha256(data).hexdigest() != VERIFIED_COMPONENT_SHA256:
            raise ValueError('Installed English INJURY resource differs from the verified build baseline')
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
            'header_hex': data[:8].hex(),
        }


def load_english_injury_labels():
    """Return optional baseline metadata and labels keyed by INJURY primary ID.

    Missing/inaccessible resources are unavailable; malformed, replaced or
    unsupported resources are unsupported. Both return empty labels, so optional
    enrichment cannot invalidate a saved-data query. Flags remain raw bytes.
    """
    metadata = {
        'source': 'installed_database_baseline', 'database_version': '2600',
        'language_id': 8, 'language': 'English', 'resource_component': COMPONENT, 'source_major': 3725,
        'verified_component_sha256': VERIFIED_COMPONENT_SHA256,
        'native_codec_plugin_sha256': NATIVE_CODEC_PLUGIN_SHA256,
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
