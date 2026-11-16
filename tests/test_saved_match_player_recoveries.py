import gzip
from pathlib import Path

import pytest

from fm_live_mcp import saved_match_statistics_wire as wire
from fm_live_mcp.saved_match_player_recoveries import decode_player_recoveries, recovery_field_registry

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.mark.parametrize('tag,delta', [(2, 0), (1, 4)])
def test_possession_fields_and_completed_pressures_preserve_native_bytes(tag, delta):
    child = bytearray(166)
    child[0] = tag
    child[151 + delta] = 11
    child[152 + delta] = 17
    child[160 + delta] = 9
    child[161 + delta] = 4
    assert decode_player_recoveries(bytes(child)) == {
        'possession_won': 11,
        'possession_lost': 17,
        'pressures_attempted': 9,
        'pressures_completed': 4,
    }


def test_zero_and_unsigned_maximum_are_counts_not_missing_records():
    child = bytearray(162)
    child[0] = 2
    assert all(value == 0 for value in decode_player_recoveries(bytes(child)).values())
    for offset in (151, 152, 160, 161):
        child[offset] = 255
    assert all(value == 255 for value in decode_player_recoveries(bytes(child)).values())


@pytest.mark.parametrize('child', [None, b'', bytearray(162), bytes([2]) + bytes(160), bytes([1]) + bytes(164)])
def test_absent_or_truncated_row_is_unavailable_not_zero(child):
    with pytest.raises(ValueError):
        decode_player_recoveries(child)


@pytest.mark.parametrize('key', [132100, 135566])
def test_complete_fixture_projection_preserves_reference_width_and_zero_substitutes(key):
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
            row = decode_player_recoveries(raw[child['start']:child['end']])
            assert set(row) == {'possession_won', 'possession_lost', 'pressures_attempted', 'pressures_completed'}
            assert all(0 <= value <= 255 for value in row.values())
            if int.from_bytes(bytes.fromhex(child['reference']['raw']), 'little') == 13009:
                expected = (2, 5, 1) if key == 132100 else (0, 11, 0)
                assert tuple(row[field] for field in ('possession_won', 'possession_lost', 'pressures_completed')) == expected
            count += 1
    assert count >= 40
    assert recovery_field_registry()['pressures_attempted']['native_writer_rva'] == '0x49adc34'
    assert 'pressure_regains' not in recovery_field_registry()
