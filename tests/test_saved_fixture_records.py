import hashlib
import io
import struct

import pytest

from fm_live_mcp.saved_component_stream import Reader
from fm_live_mcp import saved_fixture_records as wire


def fixture(*, date=0x07ee0001, other=0x07ed0002, first=7, second=8, marker=0):
    team = lambda index: bytes([marker]) + struct.pack('<i', index) + (struct.pack('<I', 900 + index) if marker and index != -1 else b'')
    return (b'\x1f' + struct.pack('<iiH', 3, 4, 0) + team(first) + b'\0\0'
            + team(second) + b'\0\0' + struct.pack('<II', date, other) + bytes(28))


def result(common=None, scores=bytes.fromhex('010305ff020204ff'), count=0):
    return b'\x1f' + struct.pack('<I', 123) + scores + bytes(12) + struct.pack('<I', count) + bytes(count * 16) + (fixture() if common is None else common)


def reader(data):
    return Reader(io.BytesIO(data), len(data))


def group(rows, *, year=2030, stored=None):
    if rows is None:
        return struct.pack('<HB', year, 0)
    data = struct.pack('<HBII', year, 1, len(rows), 0)
    for bucket, has_result, body in rows:
        data += struct.pack('<iB', bucket, has_result) + body
    return data + struct.pack('<iI', -1, len(rows) if stored is None else stored)


def manager(initial=(), outer=(), base=()):
    return (bytes.fromhex('03017461642e0500') + bytes(10) + struct.pack('<I', len(base))
            + b''.join(base) + group(initial) + struct.pack('<I', len(outer))
            + b''.join(group(rows) for rows in outer))


def test_fixture_side_order_date_field_and_variable_team_transport():
    for marker in [0, 1]:
        data = fixture(first=8, second=-1, marker=marker)
        row = wire.read_record(reader(data), False)
        assert row['end'] == len(data)
        assert [r['database_index'] for r in row['team_references']] == [8, None]
        assert row['stored_kickoff_date'] == '2030-01-01'
        assert row['raw_fixture_date48'] == 0x07ed0002
        assert row['date4c']['source_offset'] == 25 + (4 if marker else 0)
        assert row['score_channels'] is None
        assert row['record_sha256'] == hashlib.sha256(data).hexdigest()


def test_result_four_separate_channels_and_zero_is_a_score():
    row = wire.read_record(reader(result(scores=bytes.fromhex('000405ff010306ff'), count=2)), True)
    assert [c['value'] for c in row['score_channels']['normal_time']] == [0, 1]
    assert [c['value'] for c in row['score_channels']['extra_time']] == [4, 3]
    assert [c['value'] for c in row['score_channels']['penalties']] == [5, 6]
    assert [c['value'] for c in row['score_channels']['aggregate']] == [None, None]
    assert row['archive_key'] == 123 and row['result_detail_count'] == 2
    for raw in range(256):
        cell = wire.score_cell(raw)
        assert cell['value'] == (raw if raw < 128 else None)
        assert cell['state'] == ('unset_ff' if raw == 255 else 'unmapped_negative_code' if raw >= 128 else 'stored_score_value')


def test_all_truncations_reject_and_unknown_versions_markers_reject():
    for data, kind in [(fixture(), False), (result(count=2), True)]:
        for n in range(len(data)):
            with pytest.raises(ValueError):
                wire.read_record(reader(data[:n]), kind)
    with pytest.raises(ValueError):
        wire.read_fixture(reader(b'\x1e' + fixture()[1:]))
    bad = bytearray(fixture()); bad[11] = 2
    with pytest.raises(ValueError):
        wire.read_fixture(reader(bytes(bad)))
    with pytest.raises(ValueError):
        wire.read_result(reader(result(count=wire.MAX_DETAIL_ROWS + 1)))


def test_retained_groups_duplicate_preservation_and_stop_boundary():
    rows = [(0, 1, result()), (0, 1, result())]
    data = manager(rows, [None, [], [(2, 0, fixture())]], [fixture()])
    r = reader(data + b'UNPARSED HISTORICAL')
    found = []
    coverage = wire.read_retained(r, found.append)
    assert coverage['end'] == len(data)
    assert coverage['scanned_records'] == 4
    assert coverage['outer_group_count'] == 3
    assert [row['container'] for row in found] == ['base', 'initial', 'initial', 'outer_2']
    assert found[1]['record_sha256'] == found[2]['record_sha256']
    assert [row['original_group_row'] for row in found] == [0, 0, 1, 0]
    assert coverage['groups'][1]['presence'] == 0
    assert coverage['groups'][2]['row_count'] == 0
    assert r.take(8) == b'UNPARSED'


def test_stored_count_and_outer_budget_and_component_header_fail_closed():
    for data in [manager(initial=None)[:-4] + struct.pack('<I', wire.MAX_GROUPS + 1),
                 bytes.fromhex('03017461642e0500') + bytes(10) + struct.pack('<I', 0) + group([], stored=1) + bytes(4),
                 b'bad header']:
        with pytest.raises(ValueError):
            wire.read_retained(reader(data), lambda row: None)
