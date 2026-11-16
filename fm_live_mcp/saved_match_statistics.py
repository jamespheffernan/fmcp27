"""One pinned retained match key and one file-local PERSON's stored goals/assists.

Row presence is not an appearance. The decoded source ends after both complete
side sections; later match-event collections remain outside this query's scope.
"""
import hashlib

from . import saved_component_stream, saved_match_statistics_index as index_wire
from . import saved_match_statistics_wire as wire, snapshot_catalog
from .saved_fixture_archive_zstd import expand_frame

MAX_COMPONENT_BYTES = 32 * 1024 * 1024
MAX_SELECTED_FRAME_BYTES = 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024
MAX_PLAYER_ROWS = 512


def _integer(value, name):
    if type(value) is not int or not 0 <= value < 2**31:
        raise ValueError(f'Invalid saved match {name}')


def _packed_hash(handle, entry):
    handle.seek(26 + entry.start)
    left = entry.compressed_size
    digest = hashlib.sha256()
    while left:
        raw = handle.read(min(left, 128 * 1024))
        if not raw:
            raise ValueError('Truncated saved match component')
        digest.update(raw)
        left -= len(raw)
    return digest.hexdigest()


def _index(handle, entry):
    accepted = []
    for profile in (False, True):
        try:
            with saved_component_stream.open_component(handle, entry) as reader:
                value = index_wire.parse(reader, manager28_present=profile)
                if reader.source.read(1) != b'' or not reader.source.finished:
                    raise ValueError('Saved match component frame did not finish')
        except index_wire.GeometryError:
            continue
        # Budget/version errors are unresolved, never evidence selecting another profile.
        accepted.append(value)
    if len(accepted) != 1:
        raise ValueError('No unique supported saved match storage profile')
    value = accepted[0]
    if value['manager20_presence_byte'] not in (0, 1):
        raise ValueError('Unsupported saved match manager presence')
    if any(v['wire_version'] != 1 for v in value['vectors']):
        raise ValueError('Unsupported saved match container-vector version')
    if any((c['compressed_flag'], c['index_version'], c['storage_mode'], c['trailer']) != (1, 1, 3, 1)
           for c in value['containers']):
        raise ValueError('Unsupported saved match indexed-storage encoding')
    return value


def decode_frame(raw, fixture_key, person_index):
    """Validate both complete sides before exposing any selected statistics."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_EXPANDED_BYTES:
        raise ValueError('Saved match expanded-frame budget exceeded')
    _integer(fixture_key, 'fixture key')
    _integer(person_index, 'PERSON index')
    prefix = wire.fixture_prefix(raw)
    fixture = wire.continue_fixture(raw, prefix['end'], wire.parse_person, wire.fixture_extra)
    if fixture['fields']['scalar_u32'][0] != fixture_key:
        raise ValueError('Retained match inner key differs from requested storage key')
    stats = wire.stats_prefix(raw, fixture['end'])
    teams = [team['index_word'] for team in prefix['fixture_fields8_10_team_references']]
    at = stats['end']
    selected = []
    counts = []
    all_rows = 0
    for side_index in range(2):
        side = wire.side(raw, at, version=60, parse_child=wire.player, parse_collection=wire.collection)
        if side['fields']['0x5c_raw_reference'] != teams[side_index]:
            raise ValueError('Retained match side differs from its fixture TEAM reference')
        at = side['end']
        counts.append(side['child_count'])
        all_rows += side['child_count']
        if all_rows > MAX_PLAYER_ROWS:
            raise ValueError('Saved match player-row work budget exceeded')
        for slot, child in enumerate(side['children']):
            reference = child['reference']
            subject = int.from_bytes(bytes.fromhex(reference['raw']), 'little')
            if subject != person_index:
                continue
            width = 4 if reference['tag'] >= 2 else 8
            goals_offset = child['start'] + 1 + width + 2 + 5 + 5 + 3
            assists_offset = child['start'] + 1 + width + 2 + 5 + 5 + 8 + 16 + 12 + 2 + 1
            selected.append({'side_index': side_index, 'stored_player_slot': slot,
                             'team_index': teams[side_index], 'person_index': subject,
                             'goals': raw[goals_offset], 'assists': raw[assists_offset]})
    if len(selected) > 1:
        raise ValueError('Requested PERSON has multiple retained player-stat rows')
    return {'source_state': 'available' if selected else 'unavailable',
            'unavailable_reason': None if selected else 'no_stored_player_row',
            'stored_player_row_count': all_rows, 'player_rows': selected,
            'coverage': {'ordered_team_indices': teams, 'stored_rows_per_side': counts,
                         'complete_side_sections': True, 'parsed_until': at,
                         'raw_frame_bytes': len(raw), 'unparsed_tail_bytes': len(raw) - at,
                         'whole_payload_wire_parsed': False,
                         'scope': 'one indexed retained match, both stored player-stat side sections',
                         'wire_profile': 'MATCH_STATS60/FIXTURE31/GAME_MATCH_PLAYER_STATS_stream_bit1',
                         'historical_runtime_factory_overrides_proved': False},
            'appearance_state': 'unresolved', 'completion_state': 'unresolved'}


def get_player_statistics(filename, fixture_key, person_index, *, expected_snapshot_id, directory=None):
    """Read one exact retained storage key, preserving unavailable and zero values."""
    snapshot_catalog.check_filename(filename)
    _integer(fixture_key, 'fixture key')
    _integer(person_index, 'PERSON index')
    if (not isinstance(expected_snapshot_id, str) or len(expected_snapshot_id) != 64
            or any(c not in '0123456789abcdef' for c in expected_snapshot_id)):
        raise ValueError('Supply the exact expected_snapshot_id for the fixture key and PERSON index')
    with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
        pin = snapshot_catalog.snapshot_id(identity)
        if pin != expected_snapshot_id:
            raise ValueError('Saved match snapshot identity differs from expected_snapshot_id')
        root = entries[0].path.split('/')[0]
        candidates = [e for e in entries if e.path == f'{root}/match_stats_cfg.dat']
        if len(candidates) != 1:
            raise ValueError('Saved snapshot requires one root match_stats_cfg.dat')
        entry = candidates[0]
        if not (0 < entry.uncompressed_size <= MAX_COMPONENT_BYTES
                and 0 < entry.compressed_size <= MAX_COMPONENT_BYTES):
            raise ValueError('Saved match component size budget exceeded')
        before = _packed_hash(handle, entry)
        index = _index(handle, entry)
        matches = [(container, row) for container in index['containers']
                   for row in container['indices'] if row['key_i32'] == fixture_key]
        if len(matches) > 1:
            raise ValueError('Retained match key has multiple physical storage entries')
        if matches:
            container, row = matches[0]
            if not 1 <= row['length'] <= MAX_SELECTED_FRAME_BYTES:
                raise ValueError('Saved match selected compressed-frame budget exceeded')
            offset = container['payload_start'] + row['offset']
            with saved_component_stream.open_component(handle, entry) as reader:
                reader.skip(offset)
                packed = reader.take(row['length'])
            raw = expand_frame(packed)
            result = decode_frame(raw, fixture_key, person_index)
            storage = {'container_ordinal': container['container_ordinal'],
                       'entry_ordinal': row['ordinal'], 'key': row['key_i32'],
                       'compressed_sha256': hashlib.sha256(packed).hexdigest(),
                       'raw_sha256': hashlib.sha256(raw).hexdigest()}
        else:
            result = {'source_state': 'unavailable', 'unavailable_reason': 'no_retained_match_key',
                      'stored_player_row_count': None, 'player_rows': [],
                      'appearance_state': 'unresolved', 'completion_state': 'unresolved',
                      'coverage': {'scope': 'complete checked retained match storage index only',
                                   'complete_storage_index': True, 'full_save_absence_proved': False}}
            storage = None
        if _packed_hash(handle, entry) != before:
            raise ValueError('Saved match component changed during query')
        result = {'filename': filename, 'snapshot_id': pin, 'fixture_key': fixture_key,
                  'person_index': person_index, **result,
                  'source': {'component': entry.path, 'component_packed_sha256': before,
                             'manager28_present': index['manager28_present'], 'storage': storage,
                             'original_same_snapshot_PERSON_reference': True,
                             'canonical_PERSON_identity_resolved_here': False}}
    return result
