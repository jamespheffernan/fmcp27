"""Body-part projection controls independent of delivery, xG and event flags."""
import gzip
import json
from pathlib import Path
import struct

import pytest
from fm_live_mcp import live_retained_shots as shots

CONTROLS = json.loads(gzip.decompress((Path(__file__).parent / 'fixtures/retained_shot_maps.json.gz').read_bytes()))


def control(key):
    row = next(row for row in CONTROLS if row['key'] == key)
    return row, [bytes.fromhex(v) for v in row['vectors']], bytes.fromhex(row['events'])


def test_actual_southampton_headers_keep_own_goal_separate():
    row, vectors, events = control(135904)
    result = shots.decode_attempts(vectors, events, row['teams'])
    assert result['state'] == 'available'
    assert [s['body_part_counts'] for s in result['side_coverage']] == [
        {'head': 2, 'feet': 9, 'unclassified': 1},
        {'head': 2, 'feet': 9, 'unclassified': 0},
    ]
    forest_headers = [s for s in result['shots'] if s['side_index'] == 1 and s['is_header']]
    assert [s['event_id'] for s in forest_headers] == [587, 1142]
    assert all(s['native_category_code'] == 2 for s in forest_headers)
    assert sum(s['expected_goals'] for s in forest_headers) == pytest.approx(0.14244413003325462)
    marker, = result['own_goal_markers']
    assert marker['body_part'] is None and marker['is_header'] is None


def test_actual_burnley_header_and_penalty_are_distinct_and_bad_side_stays_unknown():
    row, vectors, events = control(136157)
    result = shots.decode_attempts(vectors, events, row['teams'])
    header, = [s for s in result['shots'] if s['is_header']]
    penalty, = [s for s in result['shots'] if s['is_penalty']]
    assert header['event_id'] == 1219 and header['expected_goals'] == 0.008244780823588371
    assert penalty['event_id'] == 1984 and penalty['body_part'] is None and penalty['is_header'] is None
    assert result['side_coverage'][0]['body_part_counts'] == {'head': 1, 'feet': 4, 'unclassified': 1}
    assert result['side_coverage'][1]['body_part_counts'] == {'head': None, 'feet': None, 'unclassified': None}


@pytest.mark.parametrize('native_type', [3, 4, 11, 12, 255])
def test_unmapped_type_stays_unknown_without_withholding_valid_count(native_type):
    row, vectors, events = control(132398)
    changed = bytearray(vectors[0]); changed[44] = native_type; vectors[0] = bytes(changed)
    result = shots.decode_attempts(vectors, events, row['teams'])
    assert result['side_coverage'][0]['state'] == 'available'
    first = next(s for s in result['shots'] if s['side_index'] == 0 and s['record_index'] == 0)
    assert first['body_part'] is None and first['is_header'] is None
    assert first['body_part_state'] == 'native_type_unclassified'
    assert result['side_coverage'][0]['body_part_counts']['unclassified'] == 1


def test_body_part_does_not_follow_event_flags_or_xg():
    row, vectors, events = control(135904)
    changed = bytearray(events)
    for offset in range(0, len(changed), 56):
        struct.pack_into('<H', changed, offset + 48, 0xffff)
    original = shots.decode_attempts(vectors, events, row['teams'])
    altered = shots.decode_attempts(vectors, bytes(changed), row['teams'])
    assert [s['body_part'] for s in altered['shots']] == [s['body_part'] for s in original['shots']]
    assert shots._body_part(2) == shots._body_part(7) == shots._body_part(10) == 'head'
    assert all(shots._body_part(t) == 'feet' for t in (0, 1, 5, 6, 8, 9))


def test_absent_source_body_part_counts_are_null():
    assert all(row['body_part_counts'] == {'head': None, 'feet': None, 'unclassified': None}
               for row in shots._empty_sides({}, 'unavailable_not_retained'))
