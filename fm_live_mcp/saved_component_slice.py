"""Pinned, opaque byte slices of exact listed archive members.

No field grammar, entity identity or football meaning is inferred. Every request
streams its entire selected member to a validated EOF and rechecks packed bytes;
only the requested bounded page is retained. There is no resident source cache.
"""
from . import saved_component_stream, snapshot_catalog
from .saved_player_history import _component

MAX_PAGE_BYTES = 16 * 1024
# Eight directory names plus a stem+extension, each bounded to1024 bytes by
# checked_snapshot; eight separating slashes. Do not narrow listed path scope.
MAX_MEMBER_PATH = 10 * 1024 + 8


def _member_path(value):
    if (type(value) is not str or not value or len(value) > MAX_MEMBER_PATH or
            '\\' in value or any(ord(c) < 32 or ord(c) == 127 for c in value) or
            any(part in ('', '.', '..') for part in value.split('/'))):
        raise ValueError('Supply the exact full relative member path listed by the saved career')
    return value


def get_component_slice(filename, member_path, expected_snapshot_id, *, offset=0,
                        limit=1024, directory=None):
    """Return verified source bytes only; component validation is not semantic decoding."""
    snapshot_catalog.check_filename(filename)
    _member_path(member_path)
    if type(expected_snapshot_id) is not str or not expected_snapshot_id:
        raise ValueError('Supply the saved snapshot ID')
    if (type(offset) is not int or not 0 <= offset <= saved_component_stream.MAX_RAW_SIZE or
            type(limit) is not int or not 1 <= limit <= MAX_PAGE_BYTES):
        raise ValueError('Invalid saved component byte offset or page limit')
    with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
        pin = snapshot_catalog.snapshot_id(identity)
        if pin != expected_snapshot_id:
            raise ValueError('Snapshot identity changed since component slice request')
        matches = [entry for entry in entries if entry.path == member_path]
        if len(matches) != 1:
            raise ValueError('Saved component path is missing or ambiguous; use the exact listed member path')
        entry = matches[0]
        if offset > entry.uncompressed_size:
            raise ValueError('Saved component byte offset is outside the declared member')
        receipts = {}
        with _component(handle, entry, receipts) as reader:
            reader.skip(offset)
            raw = reader.take(min(limit, reader.size - offset))
            reader.skip(reader.size - reader.offset)
        receipt = receipts[member_path.rsplit('/', 1)[-1]]
        stop = offset + len(raw)
        result = {
            'filename': filename, 'snapshot_id': pin, 'member_path': member_path,
            'state': 'verified_opaque_source_bytes', 'offset': offset, 'limit': limit,
            'returned_byte_count': len(raw), 'end_offset': stop,
            'next_offset': stop if stop < entry.uncompressed_size else None,
            'total_size': entry.uncompressed_size, 'raw_hex': raw.hex(),
            'member_sha256': receipt['raw_sha256'], 'packed_sha256': receipt['packed_sha256'],
            'component_validation': receipt,
            'source_qualification': {
                'archive_membership': 'exact_full_path_in_checked_saved_archive_directory',
                'byte_offsets': 'zero_based_uncompressed_member_bytes',
                'validation_scope': 'entire_selected_member_frame_and_packed_bytes; final_snapshot_identity',
                'semantic_state': 'opaque; no_field_or_entity_or_football_meanings_decoded',
                'other_members_validated': False,
            },
            'limits': {'max_page_bytes': MAX_PAGE_BYTES,
                       'max_member_raw_bytes': saved_component_stream.MAX_RAW_SIZE,
                       'max_member_packed_bytes': saved_component_stream.MAX_PACKED_SIZE,
                       'max_decoder_window_log': saved_component_stream.MAX_WINDOW_LOG},
        }
    return result
