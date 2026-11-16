import gzip
import json
import struct
from pathlib import Path

import pytest

from fm_live_mcp import saved_match_statistics_wire as wire
from fm_live_mcp.saved_match_player_actions import decode_player_actions, field_registry

FIXTURES = Path(__file__).parent / 'fixtures'
CONTROL = json.loads((FIXTURES / 'player_actions_b142.json').read_text())


@pytest.mark.parametrize('control', CONTROL)
def test_independent_native_named_team_shot_totals(control):
    key = control['key']
    raw = gzip.decompress((FIXTURES / f'player_actions_b142_{key}.bin.gz').read_bytes())
    prefix = wire.fixture_prefix(raw)
    fixture = wire.continue_fixture(raw, prefix['end'], wire.parse_person, wire.fixture_extra)
    assert fixture['fields']['scalar_u32'][0] == key
    stats = wire.stats_prefix(raw, fixture['end'])
    at = stats['end']
    for expected in control['teams']:
        side = wire.side(raw, at, parse_child=wire.player, parse_collection=wire.collection)
        at = side['end']
        assert side['fields']['0x5c_raw_reference'] == expected['team_index']
        actions = [decode_player_actions(raw[c['start']:c['end']]) for c in side['children']]
        for field in ('shots', 'shots_on_target'):
            assert sum(row[field] for row in actions) == expected[field]
        team_xg = struct.unpack('<f', bytes.fromhex(side['fields']['0x60_float_raw']))[0]
        assert sum(row['expected_goals'] for row in actions) == pytest.approx(team_xg, abs=1e-5)
        assert all(row['shots_on_target'] <= row['shots'] for row in actions)
        assert all(row['passes_completed'] <= row['passes_attempted'] for row in actions)
        assert all(row['tackles_completed'] <= row['tackles_attempted'] for row in actions)
        assert all(row['open_play_key_passes'] <= row['key_passes'] for row in actions)
        assert sum(row['expected_assists'] for row in actions) <= team_xg + 1e-5
        for child, row in zip(side['children'], actions):
            if int.from_bytes(bytes.fromhex(child['reference']['raw']), 'little') == 13009:
                if key == 132100:
                    assert (row['key_passes'], row['open_play_key_passes'], row['chances_created']) == (3, 2, 2)
                    assert row['expected_assists'] == 0.41468608379364014
                else:
                    assert (row['key_passes'], row['open_play_key_passes'], row['chances_created']) == (0, 0, 0)
                    assert row['expected_assists'] == 0.0


def test_reference_width_preserves_all_unsigned_counts():
    narrow = bytearray(195)
    narrow[0] = 2
    for index, metadata in enumerate(field_registry().values()):
        narrow[metadata['wire_offset_u32_person']] = 255 - index
    wide = bytes([1]) + bytes(8) + bytes(narrow[5:])
    assert decode_player_actions(bytes(narrow)) == decode_player_actions(wide)
    assert decode_player_actions(bytes(narrow))['shots'] == 255
    assert all(value == 0 for value in decode_player_actions(bytes([2]) + bytes(194)).values())


@pytest.mark.parametrize('child', [b'', None, bytearray(195), bytes([2]) + bytes(92), bytes([1]) + bytes(96)])
def test_rejects_missing_or_truncated_children(child):
    with pytest.raises(ValueError):
        decode_player_actions(child)


@pytest.mark.parametrize('tag,delta', [(2, 0), (1, 4)])
def test_expected_goals_is_unscaled_and_independent_of_shots(tag, delta):
    child = bytearray(199)
    child[0] = tag
    struct.pack_into('<f', child, 25 + delta, 1.375)
    values = decode_player_actions(bytes(child))
    assert values['expected_goals'] == 1.375
    assert values['shots'] == 0


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), -0.25])
def test_expected_goals_rejects_invalid_native_floats(value):
    child = bytearray(195)
    child[0] = 2
    struct.pack_into('<f', child, 25, value)
    with pytest.raises(ValueError, match='expected goals'):
        decode_player_actions(bytes(child))


def test_zero_expected_goals_preserved_for_unused_or_no_shot_row():
    child = bytes([2]) + bytes(194)
    assert decode_player_actions(child)['expected_goals'] == 0.0
    assert decode_player_actions(child)['expected_assists'] == 0.0


@pytest.mark.parametrize('tag,delta', [(2, 0), (1, 4)])
def test_native_named_creator_fields_and_float_units(tag, delta):
    child = bytearray(199)
    child[0] = tag
    for field, offset, value in [('key_passes', 88, 7), ('open_play_key_passes', 176, 3), ('chances_created', 57, 2)]:
        child[offset + delta] = value
    struct.pack_into('<f', child, 191 + delta, 1.625)
    result = decode_player_actions(bytes(child))
    assert (result['key_passes'], result['open_play_key_passes'], result['chances_created']) == (7, 3, 2)
    assert result['expected_assists'] == 1.625
    assert field_registry()['expected_assists']['official_property_label'] == 'ExpectedAssists'


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), -0.25])
def test_expected_assists_rejects_invalid_native_floats(value):
    child = bytearray(195)
    child[0] = 2
    struct.pack_into('<f', child, 191, value)
    with pytest.raises(ValueError, match='expected assists'):
        decode_player_actions(bytes(child))
