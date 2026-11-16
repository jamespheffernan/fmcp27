"""State selection uses one real compressed archive and canonical COMP IDs."""
import inspect
import io
import struct

import pytest

from fm_live_mcp import saved_competition_state as state, saved_world_search, snapshot_catalog
from test_saved_database_header import text
from test_saved_world_search import competition, world_database
from test_snapshot_catalog_public import compress


def prefix(code=2030, header=state.HEADER):
    data = bytearray(header + bytes(49 - len(header)))
    data[20:22] = struct.pack('<H', code)
    return bytes(data)


def archive(path, comps, members):
    files = [('game_db.dat', world_database(comps))] + list(members.items())
    payload = bytearray()
    tree = {}
    for filename, raw in files:
        folder, _, leaf = filename.rpartition('/')
        packed = compress(raw)
        tree.setdefault(folder, []).append((leaf, len(payload), len(packed), len(raw)))
        payload.extend(packed)

    def directory(name, rows, children=()):
        result = text(name) + struct.pack('<I', len(rows))
        for leaf, start, packed, raw in rows:
            stem, ext = leaf.rsplit('.', 1)
            result += text(stem) + text('.' + ext) + struct.pack('<5Q', start, packed, raw, 0, 0)
        return result + struct.pack('<I', len(children)) + b''.join(children)

    children = [directory(name, rows) for name, rows in tree.items() if name]
    table = directory('career', tree.get('', []), children)
    table_offset = 26 + len(payload) + 9
    path.write_bytes(snapshot_catalog.MAGIC + struct.pack('<Q', table_offset - 18)
                     + bytes(9) + payload + snapshot_catalog.MAGIC + compress(table))
    return path


def query(path, **kwargs):
    return saved_world_search.find_competitions(path.name, directory=path.parent, **kwargs)


def test_default_unchanged_and_primary_id_bound_paths(tmp_path):
    path = archive(tmp_path/'state.fm', [competition(0, 11), competition(1, 100101)], {
        'rgman/comp_11.dat': prefix(2030), 'rgman/comp_100101.dat': prefix(2032),
        'other/comp_11.dat': prefix(99), 'rgman/comp_1.dat': prefix(88)})
    baseline = query(path)
    assert all('saved_state' not in row for row in baseline['competitions'])
    selected = query(path, include_saved_state=True)
    rows = selected['competitions']
    assert [r['saved_state']['native_season_code'] for r in rows] == [2030, 2032]
    assert rows[1]['saved_state']['component_path'] == 'career/rgman/comp_100101.dat'
    for row in rows:
        del row['saved_state']
    assert selected == baseline


def test_absent_unknown_short_zero_and_high_code_are_distinct(tmp_path):
    path = archive(tmp_path/'state.fm', [competition(i, i+1) for i in range(5)], {
        'rgman/comp_2.dat': prefix(header=state.HEADER[:6]+b'\x0a\x02'),
        'rgman/comp_3.dat': b'no', 'rgman/comp_4.dat': prefix(0),
        'rgman/comp_5.dat': prefix(65535)})
    rows = [r['saved_state'] for r in query(path, include_saved_state=True)['competitions']]
    assert [r['status'] for r in rows] == ['absent', 'unsupported_layout', 'unsupported_layout',
                                         'no_season_code', 'decoded']
    assert rows[1]['stream_version'] == 522 and rows[2]['stream_version'] is None
    assert [r['native_season_code'] for r in rows] == [None, None, None, 0, 65535]


def test_supported_truncated_prefix_fails_only_when_selected(tmp_path):
    path = archive(tmp_path/'state.fm', [competition(0, 1), competition(1, 2)], {
        'rgman/comp_1.dat': state.HEADER, 'rgman/comp_2.dat': prefix()})
    query(path)
    query(path, include_saved_state=True, native_id=2)
    with pytest.raises(ValueError, match='extent'):
        query(path, include_saved_state=True, native_id=1)


def test_pagination_pin_and_strict_bool(tmp_path):
    path = archive(tmp_path/'state.fm', [competition(0, 1), competition(1, 2)], {})
    first = query(path, include_saved_state=True, limit=1)
    second = query(path, include_saved_state=True, limit=1, offset=first['next_offset'],
                   expected_snapshot_id=first['snapshot_id'])
    assert second['competitions'][0]['native_id'] == 2
    with pytest.raises(ValueError, match='identity'):
        query(path, include_saved_state=True, expected_snapshot_id='stale')
    for value in (0, 1, None, 'true'):
        with pytest.raises(ValueError, match='selection'):
            query(path, include_saved_state=value)
    assert inspect.signature(saved_world_search.find_competitions).parameters['include_saved_state'].default is False


def test_prefix_input_and_page_budgets():
    handle = state._PrefixHandle(io.BytesIO(bytes(131073)))
    assert len(handle.read(131072)) == 131072
    with pytest.raises(ValueError, match='budget'):
        handle.read(1)
    reader = state.StateReader(None, {}, 'career')
    for _ in range(500):
        assert reader.read(1)['status'] == 'absent'
    with pytest.raises(ValueError, match='budget'):
        reader.read(1)


def test_changed_archive_rejected_after_component_read(tmp_path, monkeypatch):
    path = archive(tmp_path/'state.fm', [competition(0, 11)], {'rgman/comp_11.dat': prefix()})
    original = state.StateReader.read

    def changed(self, native_id):
        result = original(self, native_id)
        # Retain a parseable archive, but alter its identity during the request.
        replacement = path.with_suffix('.replacement')
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
        return result

    monkeypatch.setattr(state.StateReader, 'read', changed)
    with pytest.raises(ValueError, match='changed'):
        query(path, include_saved_state=True)


def test_only_selected_page_members_are_touched(tmp_path, monkeypatch):
    path = archive(tmp_path/'state.fm', [competition(i, 100+i) for i in range(4)], {})
    seen = []
    original = state.StateReader.read

    def selected(self, native_id):
        seen.append(native_id)
        return original(self, native_id)

    monkeypatch.setattr(state.StateReader, 'read', selected)
    result = query(path, include_saved_state=True, offset=1, limit=2)
    assert seen == [101, 102] and result['matched_count'] == 4
    assert result['next_offset'] == 3


def test_unknown_prefix_does_not_claim_suffix_validation(tmp_path):
    path = archive(tmp_path/'state.fm', [competition(0, 11)], {
        'rgman/comp_11.dat': prefix() + bytes(200000)})
    result = query(path, include_saved_state=True)['competitions'][0]['saved_state']
    assert result['scope'] == 'fixed prefix only'
    assert set(result) == {'status', 'component_path', 'stream_version', 'native_season_code', 'scope'}


def test_filename_uses_native_signed32_format_not_secondary_id(tmp_path):
    path = archive(tmp_path/'state.fm', [competition(0, 0xFFFFFFFF, secondary_id=11)], {
        'rgman/comp_-1.dat': prefix(2032), 'rgman/comp_4294967295.dat': prefix(12),
        'rgman/comp_11.dat': prefix(99)})
    row = query(path, native_id=0xFFFFFFFF, include_saved_state=True)['competitions'][0]
    assert row['saved_state']['component_path'] == 'career/rgman/comp_-1.dat'
    assert row['saved_state']['native_season_code'] == 2032


def test_empty_unknown_member_is_not_a_claimed_current_header(tmp_path):
    path = archive(tmp_path/'state.fm', [competition(0, 1)], {'rgman/comp_1.dat': b''})
    result = query(path, include_saved_state=True)['competitions'][0]['saved_state']
    assert result['status'] == 'unsupported_layout'
    assert result['native_season_code'] is None
