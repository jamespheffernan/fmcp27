import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import saved_goal_crossings as query

FIXTURES = Path(__file__).parent / 'fixtures'
META = json.loads((FIXTURES / 'goal_crossings.json').read_text())['frames']


def raw(key=135195):
    prefix = 'goal_crossings' if any(f['key'] == key for f in META) else 'saved_match_stats'
    return gzip.decompress((FIXTURES / f'{prefix}_{key}.bin.gz').read_bytes())


def test_named_scorers_endpoint_geometry_and_opaque_appended_extent():
    result = query.decode_frame(raw(), 135195, scoreline=[4, 0])
    rows = result['goal_crossings']
    assert [(r['scorer_person_index'], r['height_band']) for r in rows] == [
        (13009, 'lower_half'), (11178, 'upper_half'), (11178, 'lower_half'), (33495, 'lower_half')]
    assert rows[0]['native_horizontal'] == pytest.approx(2.1892495155334473)
    assert rows[0]['native_height'] == pytest.approx(0.2971271872520447)
    assert all(r['coordinate_units'] is None for r in rows)
    assert all(r['horizontal_viewpoint'] == 'unresolved_native_signed_axis' for r in rows)
    coverage = result['coverage']
    assert coverage['credited_goals_per_side'] == [4, 0]
    assert coverage['complete_scoreline_goals'] is True
    assert coverage['opaque_appended_payload'] and not coverage['whole_payload_wire_parsed']
    assert not coverage['all_attempts'] and not coverage['individual_keeper_attribution']


@pytest.mark.parametrize('key,expected', [(132398, [2, 1]), (129861, [1, 2])])
def test_both_sides_substitute_slot_and_absent_wrapper_profiles(key, expected):
    result = query.decode_frame(raw(key), key, scoreline=expected)
    assert result['coverage']['credited_goals_per_side'] == expected
    assert result['coverage']['player_credit_reconstruction']
    assert result['coverage']['whole_payload_wire_parsed'] == (key == 129861)
    if key == 132398:
        scorer, = [r for r in result['goal_crossings'] if r['side_index'] == 1]
        assert scorer['stored_player_slot'] == 14 and scorer['scorer_person_index'] == 33495


@pytest.mark.parametrize('key,side', [(128408, 0), (131358, 1), (134310, 0), (135904, 0)])
def test_all_four_scoreline_gaps_remain_explicit_without_own_goal_claim(key, side):
    meta, = [f for f in META if f['key'] == key]
    result = query.decode_frame(raw(key), key, scoreline=meta['scoreline'])
    expected = [0, 0]
    expected[side] = 1
    assert result['coverage']['unrepresented_scoreline_goals_per_side'] == expected
    assert not result['coverage']['complete_scoreline_goals']
    assert not result['coverage']['own_goal_reason_proved']
    assert result['coverage']['player_credit_reconstruction']


def test_zero_goals_is_available_without_claiming_all_attempts():
    result = query.decode_frame(raw(129873), 129873, scoreline=[0, 0])
    assert result['source_state'] == 'available' and result['goal_crossings'] == []
    assert result['coverage']['complete_scoreline_goals']
    assert not result['coverage']['all_attempts']


def test_scoreline_absence_is_unresolved_and_inconsistent_scoreline_rejected():
    result = query.decode_frame(raw(), 135195)
    assert result['coverage']['complete_scoreline_goals'] is None
    assert result['coverage']['unrepresented_scoreline_goals_per_side'] is None
    with pytest.raises(ValueError, match='exceed supplied scoreline'):
        query.decode_frame(raw(), 135195, scoreline=[3, 0])
    for value in ([True, 0], [4], [-1, 0], '4-0'):
        with pytest.raises(ValueError, match='scoreline'):
            query.decode_frame(raw(), 135195, scoreline=value)


def test_corrupt_scorer_or_credit_never_publishes_partial_crossings():
    data = raw()
    result = query.decode_frame(data, 135195)
    at = result['goal_crossings'][0]['source_byte_start']
    for delta, value, message in [(14, 255, 'outside stored side'), (13, 255, 'outside stored side'),
                                   (13, 0, 'reconstruct credited player goals')]:
        changed = bytearray(data)
        changed[at + delta] = value
        with pytest.raises(ValueError, match=message):
            query.decode_frame(bytes(changed), 135195)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1.0])
def test_invalid_goal_height_rejected(value):
    data = raw()
    at = query.decode_frame(data, 135195)['goal_crossings'][0]['source_byte_start']
    changed = bytearray(data)
    struct.pack_into('<f', changed, at + 4, value)
    with pytest.raises(ValueError, match='geometry'):
        query.decode_frame(bytes(changed), 135195)


def test_incomplete_tail_wrong_key_and_missing_append_rejected():
    data = raw()
    result = query.decode_frame(data, 135195)
    end = result['coverage']['parsed_until']
    goal_at = result['goal_crossings'][-1]['source_byte_start']
    for stop in range(goal_at, end + 1):
        with pytest.raises(ValueError):
            query.decode_frame(data[:stop], 135195)
    with pytest.raises(ValueError, match='inner key'):
        query.decode_frame(data, 135196)
    with pytest.raises(ValueError, match='fixture key'):
        query.decode_frame(data, True)


def test_all_added_fixtures_have_pinned_source_hashes():
    for meta in META:
        data = raw(meta['key'])
        assert len(data) == meta['size']
        assert hashlib.sha256(data).hexdigest() == meta['sha256']


def test_duplicate_scorer_person_reference_is_not_resolved_by_slot_alone():
    data = raw()
    prefix = query.wire.fixture_prefix(data)
    fixture = query.wire.continue_fixture(data, prefix['end'], query.wire.parse_person,
                                           query.wire.fixture_extra)
    stats = query.wire.stats_prefix(data, fixture['end'])
    side = query.wire.side(data, stats['end'], parse_child=query.wire.player,
                           parse_collection=query.wire.collection)
    child = side['children'][0]
    assert child['reference']['tag'] >= 2
    changed = bytearray(data)
    struct.pack_into('<I', changed, child['start'] + 1, 13009)
    with pytest.raises(ValueError, match='ambiguous'):
        query.decode_frame(bytes(changed), 135195)
