"""Public offline club search through real FMF/Zstandard temporary snapshots."""
import inspect
import os
import struct

import pytest

from fm_live_mcp import saved_club_records, saved_club_search, snapshot_catalog
from test_saved_club_records import record
from test_saved_database_header import sample, text
from test_saved_database_tables import table
from test_snapshot_catalog_public import compress


def club(index, native_id, secondary_id, *, name='Newcastle United', short_name='Newcastle', kind=0):
    body = record(ordinal=index, kind=kind, name=name, short_name=short_name)
    body = body[:-12] + struct.pack('<III', index, native_id, secondary_id)
    return struct.pack('<b', kind) + body


def database(rows, *, header=None, footer=None, flags=0):
    prefix = (sample(positive=True) if header is None else header)
    prefix += table(77, 2, auxiliary=1) + table(43, 3, auxiliary=1)
    footer = struct.pack('<IBI', 0, 1, 17) if footer is None else footer
    return prefix + struct.pack('<IB', len(rows), flags) + b''.join(rows) + footer


def snapshot(path, payload):
    """One root game_db component with a real compressed archive directory."""
    packed = compress(payload)
    directory = text('career') + struct.pack('<I', 1)
    directory += text('game_db') + text('.dat')
    directory += struct.pack('<5Q', 0, len(packed), len(payload), 0, 0) + struct.pack('<I', 0)
    directory_offset = 26 + len(packed) + len(snapshot_catalog.MAGIC)
    path.write_bytes(snapshot_catalog.MAGIC + struct.pack('<Q', directory_offset - 18)
                     + bytes(9) + packed + snapshot_catalog.MAGIC + compress(directory))
    return path


@pytest.fixture
def clubs_snapshot(tmp_path):
    rows = [
        club(0, 688, 123),
        club(1, 20000222, 0),
        club(2, 42, 42, name='Straße Athletic', short_name='SA'),
        club(3, 0, 99, name='', short_name=''),
        club(4, 101, 303, name='National Competition League', short_name='NCL', kind=12),
    ]
    return snapshot(tmp_path / 'clubs.fm', database(rows))


def search(path, **kwargs):
    return saved_club_search.find_clubs(path.name, directory=path.parent, **kwargs)


def test_duplicate_names_preserve_distinct_same_file_ids(clubs_snapshot):
    result = search(clubs_snapshot, name='NEWCASTLE')
    assert result['source'] == 'on-disk save snapshot' and result['filename'] == 'clubs.fm'
    assert result['population'] == 'complete_saved_CLUB_table_including_league_body_clubs'
    assert result['total_club_slots'] == 5 and result['matched_count'] == 2
    assert [(r['database_index'], r['native_id'], r['secondary_id']) for r in result['clubs']] == [
        (0, 688, 123), (1, 20000222, 0)]
    assert [r['name'] for r in result['clubs']] == ['Newcastle United', 'Newcastle United']
    assert result['saved_metadata']['status'] == 'unknown'
    assert result['database_format'] == {'serializer_version': 4000, 'source_major': 3754, 'source_minor': 9}
    assert result['next_offset'] is None and len(result['snapshot_id']) == 64


@pytest.mark.parametrize('criteria,indices', [
    ({'name': 'ncl'}, [4]),
    ({'name': 'strasse'}, [2]),
    ({'name': 'newcastle', 'native_id': 688}, [0]),
    ({'name': 'newcastle', 'native_id': 42}, []),
    ({'native_id': 0}, [3]),
])
def test_short_name_unicode_and_combined_filters(clubs_snapshot, criteria, indices):
    result = search(clubs_snapshot, **criteria)
    assert [r['database_index'] for r in result['clubs']] == indices
    assert result['matched_count'] == len(indices)
    if indices == [4]:
        assert result['clubs'][0]['record_kind'] == 'league_body_club'
    if indices == [3]:
        assert result['clubs'][0]['name'] is result['clubs'][0]['short_name'] is None


def test_pagination_counts_matches_and_retains_native_order(clubs_snapshot):
    first = search(clubs_snapshot, name='Newcastle', limit=1)
    second = search(clubs_snapshot, name='Newcastle', offset=first['next_offset'], limit=1,
                    expected_snapshot_id=first['snapshot_id'])
    assert first['matched_count'] == second['matched_count'] == 2
    assert first['total_club_slots'] == second['total_club_slots'] == 5
    assert first['next_offset'] == 1 and second['next_offset'] is None
    assert [first['clubs'][0]['native_id'], second['clubs'][0]['native_id']] == [688, 20000222]
    assert first['snapshot_id'] == second['snapshot_id']
    terminal = search(clubs_snapshot, name='Newcastle', offset=2,
                      expected_snapshot_id=first['snapshot_id'])
    assert terminal['clubs'] == [] and terminal['matched_count'] == 2 and terminal['next_offset'] is None


def test_enumeration_includes_unknown_names_and_raw_equal_secondary(clubs_snapshot):
    rows = search(clubs_snapshot)['clubs']
    assert [r['database_index'] for r in rows] == list(range(5))
    assert rows[2]['secondary_id'] == rows[2]['native_id'] == 42
    assert rows[3]['name'] is None and rows[3]['short_name'] is None
    assert all(set(r) == {'database_index', 'native_id', 'secondary_id', 'record_kind', 'name', 'short_name'} for r in rows)


def test_dynamic_metadata_and_two_files_are_not_borrowed(tmp_path):
    one = snapshot(tmp_path / 'a.fm', database([club(0, 1, 2)], header=sample(positive=False, late_version=1)))
    two = snapshot(tmp_path / 'b.fm', database([club(0, 3, 4)], header=sample(positive=True, late_version=10)))
    a = search(one); b = search(two)
    assert a['clubs'][0]['native_id'] == 1 and b['clubs'][0]['native_id'] == 3
    assert a['snapshot_id'] != b['snapshot_id']
    assert a['filename'] == 'a.fm' and b['filename'] == 'b.fm'


def test_replaced_snapshot_rejects_old_page_pin(clubs_snapshot):
    first = search(clubs_snapshot, limit=1)
    replacement = snapshot(clubs_snapshot.with_name('replacement.fm'), database([club(0, 900, 901)]))
    os.replace(replacement, clubs_snapshot)
    with pytest.raises(ValueError, match='identity changed'):
        search(clubs_snapshot, offset=1, limit=1, expected_snapshot_id=first['snapshot_id'])
    current = search(clubs_snapshot)
    assert current['snapshot_id'] != first['snapshot_id'] and current['clubs'][0]['native_id'] == 900


@pytest.mark.parametrize('bad_tail', ['truncated_row', 'unsupported_kind', 'wrong_ordinal', 'truncated_footer', 'large_footer'])
def test_late_failure_prevents_early_matching_page(tmp_path, bad_tail):
    rows = [club(0, 688, 123), club(1, 2, 3, name='Unmatched', short_name='U')]
    footer = None
    if bad_tail == 'truncated_row':
        rows[1] = rows[1][:-4]
        footer = b''
    elif bad_tail == 'unsupported_kind':
        rows[1] = b'\x03' + rows[1][1:]
    elif bad_tail == 'wrong_ordinal':
        rows[1] = rows[1][:-12] + struct.pack('<III', 55, 2, 3)
    elif bad_tail == 'truncated_footer':
        footer = b'\0\0'
    else:
        footer = struct.pack('<I', 100001)
    path = snapshot(tmp_path / 'late.fm', database(rows, footer=footer))
    with pytest.raises(ValueError):
        search(path, name='Newcastle', native_id=688, limit=1)


def test_source_change_at_final_row_rejects_completed_page(clubs_snapshot, monkeypatch):
    original = saved_club_records.read_club
    replacement = snapshot(clubs_snapshot.with_name('next.fm'), database([club(0, 7, 8)]))
    def replace_after_real_decode(reader, ordinal, kind):
        result = original(reader, ordinal, kind)
        if ordinal == 4:
            os.replace(replacement, clubs_snapshot)
        return result
    monkeypatch.setattr(saved_club_records, 'read_club', replace_after_real_decode)
    with pytest.raises(ValueError, match='changed during request'):
        search(clubs_snapshot, name='Newcastle', limit=1)


def test_public_mcp_wrapper_is_offline_and_has_no_session(clubs_snapshot, monkeypatch):
    from fm_live_mcp import server
    monkeypatch.setattr(snapshot_catalog, 'DEFAULT_DIRECTORY', clubs_snapshot.parent)
    monkeypatch.setattr(server.bridge, '_current', lambda *a, **kw: pytest.fail('offline query accessed game session'))
    monkeypatch.setattr(server.bridge, '_run', lambda *a, **kw: pytest.fail('offline query ran game helper'))
    assert 'session_id' not in inspect.signature(server.fm_find_saved_clubs).parameters
    result = server.fm_find_saved_clubs(clubs_snapshot.name, name='Newcastle', native_id=688, limit=1)
    assert result['matched_count'] == 1 and result['clubs'][0]['native_id'] == 688
    assert 'session_id' not in result


@pytest.mark.parametrize('kwargs', [
    {'native_id': True}, {'native_id': -1}, {'native_id': 1 << 32},
    {'name': ''}, {'name': '   '}, {'offset': True}, {'offset': -1}, {'limit': 0}, {'limit': 501},
])
def test_public_argument_bounds_fail_without_needing_a_snapshot(tmp_path, kwargs):
    with pytest.raises(ValueError):
        saved_club_search.find_clubs('missing.fm', directory=tmp_path, **kwargs)
