import gzip
from pathlib import Path

import pytest

from fm_live_mcp import saved_match_statistics_wire as wire
from fm_live_mcp.saved_match_player_crosses import decode_player_crosses, cross_field_registry

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.mark.parametrize('tag,delta', [(2, 0), (1, 4)])
def test_individual_crossing_offsets_and_open_play_bucket_sum(tag, delta):
    child = bytearray(171)
    child[0] = tag
    for offset, value in [(89, 12), (90, 7), (159, 4), (164, 6), (165, 2), (166, 3)]:
        child[offset + delta] = value
    assert decode_player_crosses(bytes(child)) == {
        'crosses_attempted': 12,
        'crosses_completed': 7,
        'open_play_crosses_attempted': 10,
        'open_play_crosses_completed': 5,
    }


def test_unsigned_buckets_preserve_zero_and_do_not_wrap_the_sum():
    child = bytearray(167)
    child[0] = 2
    assert all(value == 0 for value in decode_player_crosses(bytes(child)).values())
    for offset in (89, 90, 159, 164, 165, 166):
        child[offset] = 255
    result = decode_player_crosses(bytes(child))
    assert result['crosses_attempted'] == result['crosses_completed'] == 255
    assert result['open_play_crosses_attempted'] == result['open_play_crosses_completed'] == 510


@pytest.mark.parametrize('child', [None, b'', bytearray(167), bytes([2]) + bytes(165), bytes([1]) + bytes(169)])
def test_missing_or_truncated_row_is_not_a_zero_crossing_record(child):
    with pytest.raises(ValueError):
        decode_player_crosses(child)


@pytest.mark.parametrize('key', [132100, 135566])
def test_full_match_rows_preserve_both_side_bindings_and_crossing_bounds(key):
    raw = gzip.decompress((FIXTURES / f'player_actions_b142_{key}.bin.gz').read_bytes())
    prefix = wire.fixture_prefix(raw)
    fixture = wire.continue_fixture(raw, prefix['end'], wire.parse_person, wire.fixture_extra)
    assert fixture['fields']['scalar_u32'][0] == key
    stats = wire.stats_prefix(raw, fixture['end'])
    at = stats['end']
    count = 0
    for team in prefix['fixture_fields8_10_team_references']:
        side = wire.side(raw, at, parse_child=wire.player, parse_collection=wire.collection)
        at = side['end']
        assert side['fields']['0x5c_raw_reference'] == team['index_word']
        for child in side['children']:
            row = decode_player_crosses(raw[child['start']:child['end']])
            assert 0 <= row['crosses_completed'] <= row['crosses_attempted']
            assert 0 <= row['open_play_crosses_completed'] <= row['open_play_crosses_attempted']
            assert row['open_play_crosses_attempted'] <= row['crosses_attempted']
            assert row['open_play_crosses_completed'] <= row['crosses_completed']
            count += 1
    assert count >= 40
    assert cross_field_registry()['open_play_crosses_attempted']['native_offsets'] == ['0xdf', '0xe0']
