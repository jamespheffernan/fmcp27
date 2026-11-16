"""Stored inputs plus independent earlier projections; no game or evidence reads."""
import array
import json
from pathlib import Path

import pytest

from fm_live_mcp import player_profile, players, saved_player_ratings as ratings

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/saved_player_ratings.json').read_text())


def instruction_model(raw, flag):
    # Independent W-register arithmetic transcription of D1414C.
    signed = raw if raw < 128 else raw - 256
    if flag < 128:
        return signed
    temporary = (signed * 0x6667 + 0xCCCE) & 0xFFFFFFFF
    signed_temporary = temporary if temporary < 0x80000000 else temporary - 0x100000000
    divided = (signed_temporary >> 17) + (temporary >> 31)
    return min(20, max(1, divided))


def values(out):
    return {group: {name: field['value'] for name, field in out[group].items()}
            for group in ('attributes', 'goalkeeping', 'hidden_attributes', 'feet', 'positions')}


@pytest.mark.parametrize('row', FIXTURE['rows'], ids=lambda r: r['display_name'])
def test_all_28_frozen_stored_profiles(row):
    raw = bytes.fromhex(row['raw69_hex'])
    out = ratings.decode(raw, row['scale_byte'])
    assert values(out) == row['expected']
    assert len(raw) == 69 and len(out['attributes']) == 36
    assert out['stored_scale_byte'] == row['scale_byte']
    assert out['raw_hex'] == raw.hex()
    assert all(field['state'] == 'decoded' for group in row['expected'] for field in out[group].values())


def test_dated_control_differences_are_preserved_not_replaced():
    assert (FIXTURE['saved_date'], FIXTURE['archived_live_date']) == ('2030-10-23', '2030-10-28')
    actual = []
    equal = 0
    for row in FIXTURE['rows']:
        got = values(ratings.decode(bytes.fromhex(row['raw69_hex']), row['scale_byte']))
        for group, fields in got.items():
            for field, value in fields.items():
                archived = row['archived_live'][group][field]
                if value == archived:
                    equal += 1
                else:
                    actual.append((row['display_name'], group, field, value, archived))
    assert equal == 1895
    assert set(actual) == {
        ('Lewis Miley', 'attributes', 'dribbling', 13, 12),
        ('Lewis Miley', 'attributes', 'finishing', 11, 10),
        ('Lewis Miley', 'attributes', 'heading', 12, 11),
        ('Lewis Miley', 'attributes', 'passing', 13, 12),
        ('Lewis Miley', 'attributes', 'first_touch', 14, 13),
        ('Lewis Miley', 'attributes', 'corners', 9, 8),
        ('Lewis Miley', 'attributes', 'teamwork', 14, 13),
        ('Adam Wharton', 'attributes', 'positioning', 14, 15),
        ('Adam Wharton', 'hidden_attributes', 'consistency', 16, 17),
    }


def test_three_genuine_goalkeeper_controls_have_all_11_named_values():
    keepers = [row for row in FIXTURE['rows'] if row['expected']['positions']['goalkeeper'] == 20]
    assert [(r['display_name'], r['identity']['native_id']) for r in keepers] == [
        ('Gregor Kobel', 98040383), ('Matthew Cox', 29235125), ('Silas Huber', 2000111044)]
    for row in keepers:
        out = ratings.decode(bytes.fromhex(row['raw69_hex']), row['scale_byte'])
        assert len(out['goalkeeping']) == 11
        assert values(out)['goalkeeping'] == row['archived_live']['goalkeeping']
    kobel = values(ratings.decode(bytes.fromhex(keepers[0]['raw69_hex']), 128))
    assert {k: kobel['goalkeeping'][k] for k in ('handling', 'kicking', 'reflexes')} == {
        'handling': 16, 'kicking': 12, 'reflexes': 18}


def test_full_u8_arithmetic_against_independent_instruction_transcription():
    for raw in range(256):
        for flag in range(256):
            assert ratings.native_attribute_getter(raw, flag) == instruction_model(raw, flag)


@pytest.mark.parametrize('flag', [0, 1, 127, 128, 129, 255, None])
def test_each_raw_byte_supported_domain_and_signed_result(flag):
    for raw in range(256):
        block = bytes([raw]) * 69
        out = ratings.decode(block, flag)
        field = out['attributes']['passing']
        assert field['raw_u8'] == raw
        assert field['raw_signed8'] == (raw if raw < 128 else raw - 256)
        if flag is None:
            assert field['state'] == 'scale_unavailable'
            assert field['value'] is None and field['native_getter_value'] is None
        else:
            expected = instruction_model(raw, flag)
            assert field['native_getter_value'] == expected
            supported = raw <= (100 if flag & 128 else 20)
            assert field['value'] == (expected if supported else None)
            assert field['state'] == ('decoded' if supported else 'raw_outside_supported_domain')
        position = out['positions']['goalkeeper']
        assert position['native_getter_value'] == (raw if raw < 128 else raw - 256)
        assert position['value'] == (raw if raw <= 20 else None)


def test_zero_missing_scale_and_unmapped_byte_have_distinct_meanings():
    raw = bytearray(69)
    raw[1] = 255
    raw[ratings.POSITIONS['goalkeeper']] = 20
    for flag, expected in ((0, 0), (128, 1), (None, None)):
        out = ratings.decode(raw, flag)
        assert out['attributes']['passing']['value'] == expected
        assert out['positions']['goalkeeper']['value'] == 20
        assert out['unmapped_bytes'] == [
            {'block_offset': 1, 'native_offset': '0x149', 'raw_u8': 255}]


def test_existing_public_names_offsets_and_namespaces():
    assert ratings.ATTRIBUTES == players.ATTRIBUTES
    for group, mapping in (('goalkeeping', player_profile.GOALKEEPING),
                           ('hidden_attributes', player_profile.HIDDEN), ('feet', player_profile.FEET)):
        assert ratings.EXTRAS[group] == {name: row[0] - 0x148 for name, row in mapping.items()}
    assert ratings.POSITIONS == {name: row[0] - 0x148 for name, row in player_profile.POSITIONS.items()}
    assert (ratings.ATTRIBUTES['passing'], ratings.ATTRIBUTES['finishing']) == (22, 17)
    raw = bytearray(69)
    raw[ratings.ATTRIBUTES['pace']] = 50
    raw[ratings.POSITIONS['striker']] = 19
    out = ratings.decode(raw, 128)
    assert out['attributes']['pace']['value'] == 10
    assert out['positions']['striker']['value'] == 19
    assert set(out['attributes']) >= {'off_the_ball', 'teamwork', 'free_kick_taking'}


@pytest.mark.parametrize('length', [0, 1, 68, 70, 138])
def test_wrong_block_extent_rejected(length):
    with pytest.raises(ValueError, match='exactly 69'):
        ratings.decode(bytes(length), 128)


@pytest.mark.parametrize('raw', [None, [0] * 69, '0' * 69, memoryview(array.array('I', [0] * 69))])
def test_invalid_raw_buffer_rejected(raw):
    with pytest.raises(ValueError):
        ratings.decode(raw, 128)


@pytest.mark.parametrize('flag', [True, False, -1, 256, 128.0, '128'])
def test_invalid_scale_rejected(flag):
    with pytest.raises(ValueError, match='exact u8'):
        ratings.decode(bytes(69), flag)


@pytest.mark.parametrize('raw', [True, False, -1, 256, 128.0, None])
def test_getter_validates_raw_exact_integer(raw):
    with pytest.raises(ValueError, match='exact u8'):
        ratings.native_attribute_getter(raw, 128)


def test_mutable_and_view_inputs_are_copied_and_results_not_cached():
    block = bytearray(69)
    block[22] = 80
    out = ratings.decode(memoryview(block), 128)
    block[22] = 5
    assert out['attributes']['passing']['value'] == 16
    assert ratings.decode(block, 128)['attributes']['passing']['value'] == 1
    out['attributes']['passing']['value'] = 99
    assert ratings.decode(bytes.fromhex(out['raw_hex']), 128)['attributes']['passing']['value'] == 16
