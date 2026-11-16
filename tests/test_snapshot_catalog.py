import ctypes
import ctypes.util
import struct

import pytest

from fm_live_mcp import snapshot_catalog as catalog


def compress(data):
    lib = ctypes.CDLL(ctypes.util.find_library('zstd'))
    lib.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    lib.ZSTD_compress.restype = ctypes.c_size_t
    out = ctypes.create_string_buffer(len(data)+1024)
    size = lib.ZSTD_compress(out, len(out), data, len(data), 1)
    return out.raw[:size]


def string(value):
    raw = value.encode()
    return struct.pack('<I', len(raw))+raw


def archive(tmp_path, *, names=('a', 'b')):
    payload = compress(b'example')
    table = string('career')+struct.pack('<I', len(names))
    for index, name in enumerate(names):
        table += string(name)+string('.dat')+struct.pack('<5Q', index*len(payload), len(payload), 7, 0, 0)
    table += struct.pack('<I', 0)
    header = catalog.MAGIC+struct.pack('<Q', 26+len(payload)*len(names)+9-18)+bytes(9)
    path = tmp_path/'career.fm'
    path.write_bytes(header+payload*len(names)+catalog.MAGIC+compress(table))
    return path


def test_inventory_pages_identity_and_prefix(tmp_path):
    archive(tmp_path)
    first = catalog.inspect_snapshot('career.fm', directory=tmp_path, limit=1)
    second = catalog.inspect_snapshot('career.fm', directory=tmp_path, offset=1, limit=1,
                                     expected_snapshot_id=first['snapshot_id'])
    assert first['total'] == 2
    assert first['components'][0]['path'] == 'career/a.dat'
    assert second['components'][0]['path'] == 'career/b.dat'
    assert first['next_offset'] == 1 and second['next_offset'] is None
    assert catalog.inspect_snapshot('career.fm', directory=tmp_path, prefix='career/b')['filtered_total'] == 1
    assert first['saved_metadata']['status'] == 'unknown'
    with pytest.raises(ValueError, match='identity'):
        catalog.inspect_snapshot('career.fm', directory=tmp_path, expected_snapshot_id='wrong')


@pytest.mark.parametrize('name', ['../career.fm', '/tmp/career.fm', 'dir/career.fm', 'dir\\career.fm'])
def test_scope(tmp_path, name):
    with pytest.raises(ValueError):
        catalog.inspect_snapshot(name, directory=tmp_path)


def test_discovery_is_nonrecursive_and_resilient(tmp_path):
    archive(tmp_path)
    (tmp_path/'bad.fm').write_bytes(b'bad')
    (tmp_path/'nested').mkdir()
    (tmp_path/'nested'/'ignored.fm').write_bytes(b'bad')
    (tmp_path/'link.fm').symlink_to(tmp_path/'career.fm')
    result = catalog.discover_snapshots(tmp_path)
    assert result['total'] == 3
    assert [row['status'] for row in result['snapshots']] == ['unavailable', 'verified', 'unavailable']


def test_duplicate_rejected(tmp_path):
    archive(tmp_path, names=('a', 'a'))
    with pytest.raises(ValueError, match='Duplicate'):
        catalog.inspect_snapshot('career.fm', directory=tmp_path)


def test_changed_named_file_rejected(tmp_path):
    path = archive(tmp_path)
    with pytest.raises(ValueError, match='changed'):
        with catalog.checked_snapshot(path, directory=tmp_path):
            replacement = tmp_path/'replacement'
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)


@pytest.mark.parametrize('offset,limit', [(-1, 2), (True, 2), (0, 501), (0, False)])
def test_bad_page(offset, limit, tmp_path):
    with pytest.raises(ValueError):
        catalog.discover_snapshots(tmp_path, offset=offset, limit=limit)


def test_payload_gap_and_trailing_table():
    table = string('root')+struct.pack('<I', 1)+string('a')+string('.dat')+struct.pack('<5Q', 1, 4, 4, 0, 0)+struct.pack('<I', 0)
    with pytest.raises(ValueError, match='gap'):
        catalog._parse_table(table, 5)
    with pytest.raises(ValueError, match='Trailing'):
        catalog._parse_table(table+b'X', 5)


def test_missing_directory_is_explicit(tmp_path):
    with pytest.raises(FileNotFoundError):
        catalog.discover_snapshots(tmp_path/'missing')


def test_nested_summary_cannot_supply_metadata(tmp_path):
    path = archive(tmp_path)
    entry = catalog.Component('career/nested/save_game_summary.dat', 0, 4, 4)
    with path.open('rb') as handle:
        assert catalog._metadata(handle, (entry,))['status'] == 'unknown'


def test_unsupported_summary_version():
    payload = bytes.fromhex('03017461642e1f00')+string('name')+string('99.0')
    with pytest.raises(ValueError, match='game version'):
        catalog._summary(payload)
