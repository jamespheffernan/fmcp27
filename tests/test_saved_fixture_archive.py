import io
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp.saved_component_stream import Reader
from fm_live_mcp.saved_fixture_archive import read_historical, _read_group
from fm_live_mcp.saved_fixture_archive_zstd import expand_frame

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/saved_fixture_archive.json').read_text())['frames']


def compressed(name):
    return bytes.fromhex(FIXTURES[name]['compressed_hex'])


def raw(name):
    return bytes.fromhex(FIXTURES[name]['raw_hex'])


def tail(frames=('first', 'inactive'), keys=None):
    payload = b''.join(compressed(name) for name in frames)
    at = 0
    entries = []
    for i, name in enumerate(frames):
        group, year = keys[i] if keys else (i, 2023)
        size = len(compressed(name))
        entries.append(struct.pack('<IHii', group, year, at, size))
        at += size
    return (b'\1' + struct.pack('<I', len(entries)) + b''.join(entries)
            + struct.pack('<iiBi', -1, len(payload), 3, len(payload)) + payload + b'\1')


def reader(data):
    return Reader(io.BytesIO(data), len(data))


def test_source_backed_group_and_absolute_compressed_provenance():
    data = b'prefix!' + tail()
    source = reader(data)
    source.skip(7)
    rows = []
    coverage = read_historical(source, rows.append)
    assert source.offset == len(data) and coverage['complete_source']
    assert coverage['entry_count'] == 2 and coverage['scanned_records'] == 84
    assert coverage['scanned_classes'] == {'FIXTURE': 0, 'FIXTURE_RESULT': 84}
    assert rows[0]['start'] == 5 and rows[0]['end'] == 95
    assert rows[0]['compressed_frame_start'] == 7 + 5 + 28 + 13
    assert rows[0]['source_offset_space'] == 'historical_frame_decompressed'
    assert rows[0]['team_references'][0]['database_index'] == 1278
    assert rows[0]['score_channels']['normal_time'][0]['value'] == 0
    assert rows[0]['score_channels']['normal_time'][1]['value'] == 4
    assert coverage['completion_state'] == coverage['actual_venue_state'] == 'unresolved'
    assert coverage['frames'][1]['stored_row_count'] is None


def test_absent_and_present_empty_archive_are_distinct():
    absent = read_historical(reader(b''), lambda row: pytest.fail('no row'))
    empty = read_historical(reader(tail(())), lambda row: pytest.fail('no row'))
    assert absent['state'] == 'unavailable' and absent['entry_count'] is None
    assert not absent['complete_source']
    assert empty['state'] == 'available' and empty['entry_count'] == 0
    assert empty['complete_source'] and empty['reached_end']


def test_type0_fixture_and_type1_result_controls():
    rows = []
    coverage = read_historical(reader(tail(('fixture_control', 'result_control'))), rows.append)
    assert coverage['scanned_classes'] == {'FIXTURE': 1, 'FIXTURE_RESULT': 1}
    assert [row['native_type_u8'] for row in rows] == [0, 1]
    assert rows[0]['score_channels'] is None and rows[0]['archive_key'] is None
    assert rows[1]['score_channels'] is not None


def test_row_continuation_preserves_exact_original_order():
    data = tail()
    first, second = [], []
    a = read_historical(reader(data), first.append, row_limit=17)
    assert a['next_cursor'] == {'frame_offset': 0, 'row_offset': 17}
    assert not a['complete_source']
    b = read_historical(reader(data), second.append, **a['next_cursor'])
    assert b['reached_end'] and not b['complete_source']
    assert [r['original_group_row'] for r in first + second] == list(range(84))
    assert len({r['record_sha256'] for r in first + second}) == 84


def test_frame_continuation_and_stored_year_filter_do_not_filter_kickoff():
    data = tail(keys=[(12, 65535), (14, 0)])
    rows = []
    a = read_historical(reader(data), rows.append, frame_limit=1, stored_group_year=65535)
    assert a['reached_end'] and a['complete_filtered_scope'] and not a['complete_source']
    assert len(rows) == 84 and rows[0]['stored_kickoff_date'].startswith('2023-')
    assert not a['index_year_is_kickoff_filter']
    b = read_historical(reader(data), lambda row: None, frame_limit=1)
    assert b['next_cursor'] == {'frame_offset': 1, 'row_offset': 0}


def test_duplicate_index_and_fixture_occurrences_are_preserved():
    data = tail(('result_control', 'result_control'), keys=[(7, 2023), (7, 2023)])
    rows = []
    read_historical(reader(data), rows.append)
    assert len(rows) == 2 and rows[0]['record_sha256'] == rows[1]['record_sha256']
    assert [r['historical_frame_index'] for r in rows] == [0, 1]
    assert [r['native_first_key_match'] for r in rows] == [True, False]
    assert [r['native_key_occurrence'] for r in rows] == [0, 1]


def test_frame_finishes_before_callback_and_bad_count_emits_no_rows():
    rows = []
    with pytest.raises(ValueError, match='count mismatch'):
        read_historical(reader(tail(('bad_count',))), rows.append, row_limit=1)
    assert rows == []
    source = reader(tail())
    read_historical(source, lambda row: rows.append(source.offset))
    assert rows and set(rows) == {source.size}


@pytest.mark.parametrize('change', ['version', 'mode', 'negative_length', 'flag', 'suffix',
                                  'negative_position', 'negative_size', 'zero_size', 'outside'])
def test_invalid_envelope_or_index_fails(change):
    data = bytearray(tail(('first',)))
    header = 5 + 14
    if change == 'version': data[0] = 2
    elif change == 'mode': data[header + 8] = 1
    elif change == 'negative_length': struct.pack_into('<i', data, header + 9, -1)
    elif change == 'flag': data[-1] = 2
    elif change == 'suffix': data += b'x'
    elif change == 'negative_position': struct.pack_into('<i', data, 11, -1)
    elif change == 'negative_size': struct.pack_into('<i', data, 15, -1)
    elif change == 'zero_size': struct.pack_into('<i', data, 15, 0)
    else: struct.pack_into('<i', data, 11, len(data))
    with pytest.raises(ValueError): read_historical(reader(data), lambda row: None)


def test_each_truncation_of_empty_envelope():
    data = tail(())
    for end in range(1, len(data)):
        with pytest.raises(ValueError): read_historical(reader(data[:end]), lambda row: None)


@pytest.mark.parametrize('kwargs', [{'frame_offset': True}, {'frame_offset': -1},
                                   {'frame_offset': 3}, {'frame_offset': 2, 'row_offset': 1},
                                   {'row_offset': 85}, {'frame_limit': 0}, {'row_limit': 0},
                                   {'stored_group_year': -1}, {'stored_group_year': 65536},
                                   {'stored_group_index': True},
                                   {'stored_group_index': 9, 'row_offset': 1}])
def test_bad_cursor_and_filter_inputs_fail(kwargs):
    with pytest.raises(ValueError): read_historical(reader(tail()), lambda row: None, **kwargs)


def test_decompression_controls():
    assert expand_frame(compressed('first')) == raw('first')
    for value in (b'', b'bad!', compressed('first')[:-1], compressed('first') + b'x',
                  compressed('first') + compressed('inactive')):
        with pytest.raises(ValueError): expand_frame(value)


def test_wrong_result_type_and_group_count_or_trailing_bytes_fail():
    data = bytearray(raw('first'))
    data[4] = 0
    with pytest.raises(ValueError): _read_group(data)
    for data in (raw('first')[:-1], raw('first') + b'x', raw('bad_count')):
        with pytest.raises(ValueError): _read_group(data)
