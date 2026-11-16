import io
import struct

import pytest

from fm_live_mcp import saved_national_containers as records
from fm_live_mcp.saved_component_stream import Reader


def _u32(value):
    return struct.pack('<I', value)


def _named(version):
    texts = [b'Cup', 'é'.encode(), b'']
    wire = bytes([version]) + b''.join(_u32(len(t)) + t for t in texts) + bytes(13)
    if version >= 2:
        wire += bytes(4) + _u32(2) + bytes(14 + 5)
    wire += bytes(4 + (5 if version >= 5 else 0) + 19)
    return wire + bytes((version >= 3) + (version >= 4) + (version >= 6))


def record(ordinal=0, *, positive=False, versions=(6,),
           secondary_versions=(-1, 1, 2, 3), nation_index=0,
           team_indices=None, native_id=1234, secondary_id=4321):
    wire = bytearray(bytes(14))
    offsets = {}

    def mark(name):
        offsets[name] = len(wire)

    mark('pairs')
    wire.extend(struct.pack('<i', 1 if positive else 0))
    wire.extend(bytes(8 if positive else 0))
    wire.extend(bytes(33))
    mark('properties')
    if positive:
        # Map owns a vector containing the registered four-byte extension32.
        wire.extend(_u32(1) + b'abcd' + b'\x01\x0b' + _u32(1)
                    + b'\x01\x20' + _u32(99))
        wire.extend(_u32(1) + b'\x01\x12' + bytes(2))
    else:
        wire.extend(bytes(8))
    for name, stride in (('short_ring', 2), ('float_ring', 4)):
        mark(name)
        wire.extend(_u32(2 if positive else 0) + bytes(2 * stride if positive else 0))
    mark('initial_refs')
    wire.extend(bytes([1 if positive else 0]) + bytes(4 if positive else 0))
    mark('group_refs')
    wire.extend((b'\x01' + bytes(4)) * 20 if positive else bytes(20))
    mark('trailing_refs')
    wire.extend(struct.pack('<h', 1 if positive else 0) + bytes(4 if positive else 0))
    for index in range(2):
        mark(f'named_count{index}')
        wire.extend(struct.pack('<h', len(versions) if positive else 0))
        if positive:
            for version in versions:
                wire.extend(_named(version))
    mark('optional_presence')
    wire.append(1 if positive else 0)
    if positive:
        wire.append(255)
        mark('optional_count')
        wire.extend(struct.pack('<i', 2) + bytes(18))
    mark('pointer_count')
    wire.extend(struct.pack('<h', 1 if positive else 0) + bytes(9 if positive else 0))
    for index in range(2):
        mark(f'middle_vector{index}')
        wire.extend(_u32(1 if positive else 0) + bytes(18 if positive else 0))
    mark('middle_signed')
    wire.extend(struct.pack('<h', 1 if positive else 0) + bytes(14 if positive else 0))
    mark('middle_items')
    wire.extend(_u32(1 if positive else 0) + bytes(10 if positive else 0))
    wire.extend(bytes(5))
    mark('secondary_presence')
    wire.append(1 if positive else 0)
    if positive:
        wire.extend(_u32(3))
        mark('secondary_count')
        wire.extend(_u32(len(secondary_versions)))
        for version in secondary_versions:
            wire.extend(struct.pack('<h', version))
            wire.extend(bytes(6 + (2 if version >= 2 else 1) + 1 + (version >= 3)))
    wire.extend(bytes(11))
    mark('nation_reference')
    wire.extend(_u32(nation_index))
    wire.extend(bytes(5))
    for index, stride in enumerate((9, 8, 8)):
        mark(f'tail_signed{index}')
        wire.extend(bytes([1 if positive else 0]) + bytes(stride if positive else 0))
    wire.extend(bytes(45))
    for index in range(3):
        mark(f'tail_fixed{index}')
        wire.extend(bytes([2 if positive else 0]) + bytes(8 if positive else 0))
    wire.extend(bytes(27))
    # Shared17B1018 base: five references,16/28byte vectors, exact ordinal.
    wire.extend(bytes(3))
    for index in range(5):
        mark(f'base_vector{index}')
        count = len(team_indices) if index == 0 and team_indices is not None else (1 if positive else 0)
        wire.extend(bytes([count]) if index < 2 else struct.pack('<h', count))
        if index == 0 and team_indices is not None:
            wire.extend(struct.pack('<' + 'i' * count, *team_indices))
        else:
            wire.extend(bytes(4 if positive else 0))
    wire.extend(bytes([1 if positive else 0]) + bytes(16 if positive else 0))
    mark('base_details')
    wire.extend(struct.pack('<h', 1 if positive else 0) + bytes(28 if positive else 0))
    mark('identity')
    wire.extend(struct.pack('<III', ordinal, native_id, secondary_id))
    return bytes(wire), offsets


def reader(data):
    return Reader(io.BytesIO(data), len(data))


def test_positive_record_preserves_next_record_boundary():
    first, _ = record(ordinal=7, positive=True)
    second, _ = record(ordinal=8)
    value = reader(first + second + b'NEXT')
    assert records.skip_national_container(value, 7, 0) is None
    assert value.offset == len(first)
    records.skip_national_container(value, 8, 0)
    assert value.offset == len(first + second)
    assert value.take(4) == b'NEXT'


@pytest.mark.parametrize('nation_index,expected', [(0, 0), (139, 139), (0xffffffff, None)])
def test_read_identity_nation_and_team_slots_preserve_boundary(nation_index, expected):
    raw, _ = record(7, positive=True, nation_index=nation_index,
                    team_indices=[617, -1, 617, -2], secondary_id=0)
    value = reader(raw + b'NEXT')
    assert records.read_national_container(value, 7, 0) == {
        'database_index': 7, 'native_id': 1234, 'secondary_id': 0,
        'nation_index': expected, 'team_indices': [617, None, 617, -2],
        'unverified_negative_team_indices': [{'native_slot': 3, 'raw_word': -2}],
    }
    assert value.take(4) == b'NEXT'


def test_read_empty_team_population_is_distinct_from_null_nation():
    raw, _ = record(nation_index=0xffffffff, team_indices=[])
    assert records.read_national_container(reader(raw), 0, 0) == {
        'database_index': 0, 'native_id': 1234, 'secondary_id': 4321,
        'nation_index': None, 'team_indices': [],
    }


@pytest.mark.parametrize('word', [0x80000000, 0xfffffffe])
def test_projection_rejects_unproved_negative_nation_but_skip_stays_compatible(word):
    raw, _ = record(nation_index=word)
    with pytest.raises(ValueError, match='negative saved NATION'):
        records.read_national_container(reader(raw), 0, 0)
    value = reader(raw + b'NEXT')
    assert records.skip_national_container(value, 0, 0) is None
    assert value.take(4) == b'NEXT'


def test_read_all_truncations_and_wrong_identity_fail():
    raw, _ = record(7, positive=True, team_indices=[617, -1])
    for end in range(len(raw)):
        with pytest.raises(ValueError):
            records.read_national_container(reader(raw[:end]), 7, 0)
    with pytest.raises(ValueError, match='ordinal mismatch'):
        records.read_national_container(reader(raw), 8, 0)


@pytest.mark.parametrize('version', [0, 1, 2, 3, 4, 5, 6, 255])
def test_named_child_version_branches(version):
    wire, _ = record(positive=True, versions=(version,))
    value = reader(wire + b'NEXT')
    records.skip_national_container(value, 0, 0)
    assert value.take(4) == b'NEXT'


def test_every_positive_record_truncation_fails():
    wire, _ = record(positive=True)
    for end in range(len(wire)):
        with pytest.raises(ValueError):
            records.skip_national_container(reader(wire[:end]), 0, 0)


@pytest.mark.parametrize('name,fmt', [
    ('named_count0', '<h'), ('named_count1', '<h'),
    ('optional_count', '<i'), ('pointer_count', '<h'),
    ('middle_signed', '<h'), ('tail_signed0', '<b'),
    ('tail_signed1', '<b'), ('tail_signed2', '<b'),
    ('base_vector2', '<h'), ('base_details', '<h'),
])
def test_negative_allocation_counts_fail(name, fmt):
    wire, offsets = record(positive=True)
    changed = bytearray(wire)
    struct.pack_into(fmt, changed, offsets[name], -1)
    with pytest.raises(ValueError):
        records.skip_national_container(reader(changed), 0, 0)


def test_negative_prefix_population_counts_take_empty_native_branch():
    wire, offsets = record()
    changed = bytearray(wire)
    struct.pack_into('<i', changed, offsets['pairs'], -1)
    changed[offsets['initial_refs']] = 128
    changed[offsets['group_refs']:offsets['group_refs'] + 20] = bytes([255]) * 20
    struct.pack_into('<h', changed, offsets['trailing_refs'], -32768)
    value = reader(changed + b'NEXT')
    records.skip_national_container(value, 0, 0)
    assert value.take(4) == b'NEXT'


@pytest.mark.parametrize('name,fmt,count', [
    ('short_ring', '<I', 121), ('float_ring', '<I', 121),
    ('tail_fixed0', '<B', 21), ('secondary_count', '<I', 100001),
    ('middle_vector0', '<I', 100001), ('pairs', '<i', 100001),
    ('base_vector2', '<h', 4097),
])
def test_count_budgets_fail_before_vector_read(name, fmt, count):
    wire, offsets = record(positive=True)
    changed = bytearray(wire)
    struct.pack_into(fmt, changed, offsets[name], count)
    with pytest.raises(ValueError, match='bound|budget'):
        records.skip_national_container(reader(changed), 0, 0)


def test_ordinal_and_subtype_rejections():
    wire, _ = record(ordinal=1)
    with pytest.raises(ValueError, match='ordinal mismatch'):
        records.skip_national_container(reader(wire), 0, 0)
    for ordinal, kind in ((-1, 0), (True, 0), (2_000_000, 0), (0, 1), (0, True)):
        value = reader(wire)
        with pytest.raises(ValueError):
            records.skip_national_container(value, ordinal, kind)
        assert value.offset == 0


def test_property_variant_and_cumulative_work_rejections(monkeypatch):
    wire, offsets = record(positive=True)
    changed = bytearray(wire)
    changed[offsets['properties'] + 9] = 255
    with pytest.raises(ValueError, match='variant'):
        records.skip_national_container(reader(changed), 0, 0)
    monkeypatch.setattr(records, 'MAX_RECORD_ITEMS', 10)
    with pytest.raises(ValueError, match='item budget'):
        records.skip_national_container(reader(wire), 0, 0)


def test_nonone_optional_markers_skip_native_children():
    wire, offsets = record()
    changed = bytearray(wire)
    changed[offsets['optional_presence']] = 2
    changed[offsets['secondary_presence']] = 255
    value = reader(changed + b'NEXT')
    records.skip_national_container(value, 0, 0)
    assert value.take(4) == b'NEXT'


def test_named_text_limits_are_cumulative(monkeypatch):
    wire, _ = record(positive=True)
    monkeypatch.setattr(records, 'MAX_TEXT_BYTES', 2)
    with pytest.raises(ValueError, match='text.*byte budget'):
        records.skip_national_container(reader(wire), 0, 0)
    monkeypatch.setattr(records, 'MAX_TEXT_BYTES', 8192)
    # Each text fits by itself; two named children exceed the shared record cap.
    monkeypatch.setattr(records, 'MAX_RECORD_TEXT_BYTES', 8)
    with pytest.raises(ValueError, match='text.*byte budget'):
        records.skip_national_container(reader(wire), 0, 0)


def test_invalid_named_utf8_rejected():
    wire, offsets = record(positive=True)
    changed = bytearray(wire)
    changed[offsets['named_count0'] + 2 + 1 + 4] = 255
    with pytest.raises(ValueError, match='UTF-8'):
        records.skip_national_container(reader(changed), 0, 0)


SAVES = [
    ('Cesar Jules - Newcastle (v02).fm', 'ef221d1ec222494e8f3d874dad27a1190e124d2d096d74f17338ca477f8bf5d5', 25788862, 27873672),
    ('Cesar Jules - Newcastle (v03).fm', '1d31d9563e5d6e009aff780c3df7875b5c851d7e4a3e416e5088d8b339b0115f', 25788666, 27873616),
    ('Cesar Jules - Newcastle.fm', '8ff7b7053760d72f9389fbe8ef36b00a46a3a08cb40a477234006df2330d70d3', 25789682, 27874480),
    ('last save overwrite backup.fm', 'f305511fdb53971561a4bed140e05979237d8651ecd28a2dce5844fb48f6a0b7', 25764156, 27847349),
]


@pytest.mark.parametrize('filename,snapshot_id,start,end', SAVES)
def test_actual_pinned_container_identities_nation_indices_and_backlinks(filename, snapshot_id, start, end):
    from collections import Counter
    from fm_live_mcp import snapshot_catalog as catalog
    from fm_live_mcp.saved_component_stream import open_component
    if not (catalog.DEFAULT_DIRECTORY / filename).is_file():
        pytest.skip('Private pinned save unavailable')
    with catalog.checked_snapshot(filename) as (handle, entries, identity):
        if catalog.snapshot_id(identity) != snapshot_id:
            pytest.skip('Private save changed since the pinned corpus verification')
        entry, = [x for x in entries if x.path.count('/') == 1 and x.path.endswith('/game_db.dat')]
        with open_component(handle, entry) as value:
            value.skip(start)
            assert (value.u32(), value.u8()) == (502, 0)
            rows = [records.read_national_container(value, i, value.u8()) for i in range(502)]
            assert value.offset == end - 9
            assert (value.u32(), value.u8(), value.u32()) == (0, 1, 2000169732)
            assert value.offset == end
            assert rows[139]['database_index'] == 139
            assert (rows[139]['native_id'], rows[139]['secondary_id'], rows[139]['nation_index']) == (765, 765, 139)
            assert 617 in rows[139]['team_indices']
            # Distinct container identity shares this NATION index. No ID shortcut.
            assert (rows[390]['native_id'], rows[390]['nation_index']) == (2000169621, 139)
            assert Counter(row['nation_index'] for row in rows) == Counter({i: 2 for i in range(251)})
