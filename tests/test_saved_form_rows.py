import io
import struct

import pytest

from fm_live_mcp import saved_form_rows as form
from fm_live_mcp.saved_component_stream import Reader

# Main snapshot8ff7b7053760..., game_db103228292..103228346. Independently
# frozen B46 row dated2030-07-10:3goals,1assist,100ratingtenths,COMPindex131.
ACTUAL_ROW = bytes.fromhex(
    '01bf72ee07747400008300000000010302000800002600'
    '2d0300040401090300030000004300004364332b0700000002010002584b01'
)


def reader(raw):
    return Reader(io.BytesIO(raw), len(raw))


def group(rows, kind=20, owner=545):
    return bytes([kind, 1]) + struct.pack('<II', owner, len(rows)) + b''.join(rows)


def absent(*, day=191, year=2030, competition=-1):
    return b'\1' + struct.pack('<HHIiBB', day, year, 0xFFFFFFFF, competition, 255, 0)


def test_positive_named_row_exact_group_end_and_unread_suffix():
    raw = b'\1' + group([ACTUAL_ROW])
    source = reader(raw + b'\x01unsupported sibling bytes')
    result = form.read_groups(source)
    assert source.offset == result['end'] == len(raw)
    assert source.u8() == 1
    assert result['group_count'] == result['total_row_count'] == 1
    item = result['groups'][0]['rows'][0]
    assert item['date']['value'] == '2030-07-10'
    assert item['competition_index_word'] == 131
    assert item['team_reference_word'] == 29812
    assert item['stats']['goals'] == 3
    assert item['stats']['assists'] == 1
    assert item['stats']['rating_tenths'] == 100
    assert item['stats']['played_minutes'] == 67
    assert item['stats']['played_minutes_state'] == 'stored'
    assert item['stats']['played_minutes_raw_u8'] == 67
    assert item['stats']['native_rating_nonzero_filter_passes'] is True
    assert result['unread_suffix'] and not result['identities_resolved']


def test_type20_and60_changeover_preserves_duplicate_rows_and_positions():
    raw = b'\3' + group([ACTUAL_ROW] * 21) + group([], 60, 0) + group([absent(), ACTUAL_ROW], 60, 0)
    result = form.read_groups(reader(raw))
    assert result['total_row_count'] == 23
    assert [g['group_index'] for g in result['groups']] == [0, 1, 2]
    assert [g['kind_code'] for g in result['groups']] == [20, 60, 60]
    assert [r['row_index'] for r in result['groups'][0]['rows']] == list(range(21))
    assert result['groups'][0]['rows'][0]['stats'] == result['groups'][0]['rows'][20]['stats']
    assert result['groups'][1]['end'] == result['groups'][2]['start']
    assert result['groups'][2]['rows'][1]['date']['value'] == '2030-07-10'
    assert result['end'] == len(raw)


def test_absent_stats_remain_unknown_and_signed_references_are_raw():
    item = form.read_groups(reader(b'\1' + group([absent()])))['groups'][0]['rows'][0]
    assert item['competition_index_word'] == -1
    assert item['team_reference_word'] == 0xFFFFFFFF
    assert item['stats']['state'] == 'not_stored'
    assert all(item['stats'][key] is None for key in
               ('goals', 'assists', 'rating_tenths', 'played_minutes', 'played_minutes_raw_u8'))
    assert item['stats']['played_minutes_state'] == 'not_stored'


@pytest.mark.parametrize('played', [0, 1, 90, 127, 128, 255])
def test_played_duration_preserves_raw_byte_and_current_producer_bounds(played):
    raw = bytearray(ACTUAL_ROW)
    raw[39] = played  # Sparse wire position for native stats+15/getter38.
    raw[21:23] = b'\xff\xff'  # Native+04 scaled metric is not minutes.
    stats = form.read_groups(reader(b'\1' + group([raw])))['groups'][0]['rows'][0]['stats']
    assert stats['played_minutes_raw_u8'] == played
    assert stats['played_minutes'] == (played if played <= 127 else None)
    assert stats['played_minutes_state'] == (
        'stored' if played <= 127 else 'outside_current_producer_profile')
    assert bytes.fromhex(stats['raw_object_hex'])[0x15] == played


def test_form_getters_preserve_255_and_zero_without_compact_sentinel_rules():
    raw = bytearray(ACTUAL_ROW)
    raw[24] = raw[28] = raw[40] = 255
    item = form.read_groups(reader(b'\1' + group([raw])))['groups'][0]['rows'][0]
    assert [item['stats'][k] for k in ('goals', 'assists', 'rating_tenths')] == [255] * 3
    raw[40] = 0
    stats = form.read_groups(reader(b'\1' + group([raw])))['groups'][0]['rows'][0]['stats']
    assert stats['rating_tenths'] == 0
    assert stats['native_rating_nonzero_filter_passes'] is False
    assert stats['rating_zero_reason'] == 'not_established'


def test_dates_preserve_default_invalid_flags_and_leap_days():
    rows = [absent(day=1, year=1900), absent(day=0), absent(day=366, year=2029), absent(day=366, year=2032), absent(day=191 | 0x7200)]
    dates = [r['date'] for r in form.read_groups(reader(b'\1' + group(rows)))['groups'][0]['rows']]
    assert [d['state'] for d in dates[:3]] == ['native_default_sentinel', 'unmapped_packed_value', 'unmapped_packed_value']
    assert dates[3]['value'] == '2032-12-31'
    assert dates[4]['value'] == '2030-07-10'
    assert dates[4]['unmapped_low_word_flags'] == 0x7200


def test_zero_groups_stops_after_count():
    source = reader(b'\0\xff')
    assert form.read_groups(source)['end'] == 1
    assert source.u8() == 255


def test_every_truncation_including_changeover_fails_without_partial_result():
    raw = b'\2' + group([ACTUAL_ROW]) + group([absent()], 60)
    for cut in range(len(raw)):
        with pytest.raises(ValueError):
            form.read_groups(reader(raw[:cut]))


@pytest.mark.parametrize('offset,value', [(1, 19), (2, 2), (11, 2), (25, 2), (26, 2)])
def test_unsupported_types_versions_and_presence(offset, value):
    raw = bytearray(b'\1' + group([ACTUAL_ROW]))
    raw[offset] = value
    with pytest.raises(ValueError):
        form.read_groups(reader(raw))


def test_hostile_counts_and_aggregate_budget(monkeypatch):
    with pytest.raises(ValueError, match='budget'):
        form.read_groups(reader(b'\1\x14\1' + struct.pack('<II', 0, 0xFFFFFFFF)))
    monkeypatch.setattr(form, 'MAX_TOTAL_ROWS', 3)
    raw = b'\2' + group([absent()] * 2) + group([absent()] * 2, 60)
    with pytest.raises(ValueError, match='budget'):
        form.read_groups(reader(raw))


@pytest.mark.parametrize('kwargs', [{'source_major': True}, {'source_major': 3753}, {'source_minor': 8}, {'reference_profile': 'raw64'}])
def test_explicit_source_and_reference_profile_guards(kwargs):
    with pytest.raises(ValueError):
        form.read_groups(reader(b'\0'), **kwargs)


def test_independent_real_879_row_minutes_oracle_when_selected():
    """Opt-in acceptance uses original source bytes and an independent oracle."""
    import hashlib
    import json
    import os
    from pathlib import Path

    oracle_path = os.environ.get('FM_SAVED_FORM_MINUTES_ORACLE')
    source_path = os.environ.get('FM_SAVED_FORM_MINUTES_SOURCE')
    if not oracle_path or not source_path:
        pytest.skip('No independent saved-form minutes corpus selected')
    oracle = json.loads(Path(oracle_path).read_text())
    count = present = absent_count = zero = 0
    with Path(source_path).open('rb') as source:
        assert hashlib.file_digest(source, 'sha256').hexdigest() == oracle['component_raw_sha256']
        for person in oracle['people']:
            for section in person['groups']:
                for expected in section['rows']:
                    source.seek(expected['start'])
                    raw = source.read(expected['end'] - expected['start'])
                    assert hashlib.sha256(raw).hexdigest() == expected['sha256']
                    stream = reader(raw)
                    actual = form._row(stream, expected['row_ordinal'])
                    assert stream.offset == actual['end'] == len(raw)
                    stats = actual['stats']
                    assert stats['played_minutes'] == expected['minutes']
                    assert stats['played_minutes_state'] == expected['stats_state']
                    if expected['stats'] is None:
                        absent_count += 1
                        assert stats['played_minutes_raw_u8'] is None
                    else:
                        present += 1
                        assert stats['raw_object_hex'] == expected['stats']['raw_object_hex']
                        assert stats['played_minutes_raw_u8'] == expected['stats']['getter_ordinal38_value']
                        zero += stats['played_minutes'] == 0
                    count += 1
    assert (count, present, absent_count, zero) == (879, 627, 252, 1)
