"""Native-layout samples from independently captured history-01 archive/current receipts."""
import struct

import pytest

from fm_live_mcp import player_statistics as stats


CURRENT_GORDON = bytes.fromhex('b8d358f679000000c103ef020b030e0201000000000002002c')
CURRENT_GORDON_ARRAY = bytes.fromhex(
    '13000a00070002009d01610119001800150009001d0014000a00110009001e001400f500c602'
    '00000000ba00000083040e001e000900170000000000190008000b0000008a004200ae00c000'
    '09000000000000000100000000001e0006000000a60000003800540017001300ae001a0042'
    '000c0004000c00930080005900430012000f0004000400')
CURRENT_KOBEL = bytes.fromhex('f08e32f679000000c903ec040e000e0000100000000000053a')
CURRENT_KOBEL_ARRAY = bytes.fromhex(
    '200010000700020057013b0101000000120016000000000000000000000000000000f500bf02cf050000000045005703'
    '00000900d603000000000000020000003e00000021007700000000001600000000000000000000000000000000008fff'
    '00000000020000000000000000000000000000000000000081008100320032001e000a0000000000')


@pytest.mark.parametrize('raw,indirect,expected', [
    (CURRENT_GORDON, CURRENT_GORDON_ARRAY,
     {'starting_appearances': 11, 'sub_appearances': 3, 'total_appearances': 14,
      'goals': 2, 'assists': 1, 'minutes': 751, 'total_rating_tenths': 961,
      'rating_denominator': 14, 'goals_conceded': 0, 'clean_sheets': 0,
      'yellow_cards': 2, 'average_rating': 6.864285469055176}),
    (CURRENT_KOBEL, CURRENT_KOBEL_ARRAY,
     {'starting_appearances': 14, 'sub_appearances': 0, 'total_appearances': 14,
      'goals': 0, 'assists': 0, 'minutes': 1260, 'total_rating_tenths': 969,
      'rating_denominator': 14, 'goals_conceded': 16, 'clean_sheets': 5,
      'yellow_cards': 0, 'average_rating': 6.921428680419922}),
])
def test_independent_current_outfield_and_goalkeeper_samples(raw, indirect, expected):
    result = stats.decode_compact(raw, indirect)
    assert {key: result[key] for key in expected} == expected
    assert result['advanced']['state'] == 'resident'
    assert result['advanced']['units'] == 'unverified_native_units'
    assert result['advanced']['named_raw_values']['passes_attempted'] == (413 if raw == CURRENT_GORDON else 343)
    assert 'b8d358' not in str(result)


@pytest.mark.parametrize('raw,expected', [
    # Archive Gordon offset66956904, record scalar copied by F83FC0/F84190.
    ('001000000000000029027c0107010802010000000000000000',
     {'starting_appearances': 7, 'sub_appearances': 1, 'goals': 2, 'assists': 1,
      'minutes': 380, 'total_rating_tenths': 553, 'average_rating': 6.912499904632568}),
    # Archive Kobel offset49571256, same native copy route.
    ('00100000000000001702d00208000800001100000000000100',
     {'starting_appearances': 8, 'sub_appearances': 0, 'goals': 0, 'assists': 0,
      'minutes': 720, 'goals_conceded': 17, 'clean_sheets': 1,
      'total_rating_tenths': 535, 'average_rating': 6.6875}),
])
def test_independent_archived_samples_use_same_compact_layout(raw, expected):
    result = stats.decode_compact(bytes.fromhex(raw), bytes(136))
    assert {key: result[key] for key in expected} == expected


@pytest.mark.parametrize('name,offset', [
    ('starting_appearances', 12), ('sub_appearances', 13), ('rating_denominator', 14),
    ('goals', 15), ('assists', 16), ('goals_conceded', 17), ('penalties', 18),
    ('penalties_scored', 19), ('player_of_the_match', 20), ('red_cards', 21),
    ('yellow_cards', 22), ('clean_sheets', 23), ('unmapped_enum_81', 24),
])
def test_byte_255_preserves_native_bits_and_integer_getter_sentinel(name, offset):
    raw = bytearray(CURRENT_GORDON)
    raw[offset] = 255
    result = stats.decode_compact(bytes(raw), CURRENT_GORDON_ARRAY)
    assert result[name] is None
    assert result['native_raw'][name] == 255
    assert result['native_getter_values'][name] == -1
    if offset in (12, 13):
        assert result['total_appearances'] is None


def test_zero_and_255_rating_denominators_follow_native_float_route():
    raw = bytearray(CURRENT_GORDON)
    raw[14] = 0
    result = stats.decode_compact(bytes(raw), CURRENT_GORDON_ARRAY)
    assert result['average_rating'] == 0.0
    assert result['rating_denominator'] == 0
    assert 'unrated' not in result
    raw[14] = 255
    result = stats.decode_compact(bytes(raw), CURRENT_GORDON_ARRAY)
    assert result['rating_denominator'] is None
    assert result['native_getter_values']['rating_denominator'] == -1
    assert result['average_rating'] == 0.3768627345561981


def test_signed_array_and_shorts_preserve_negatives_without_sentinel_guessing():
    raw = bytearray(CURRENT_GORDON)
    raw[8:12] = struct.pack('<hh', -1, -32768)
    array = [0] * 68
    array[0], array[47], array[55], array[67] = -1, -32768, -113, 32767
    result = stats.decode_compact(bytes(raw), struct.pack('<68h', *array))
    assert result['total_rating_tenths'] == -1
    assert result['minutes'] == -32768
    assert result['advanced']['raw_signed16'] == array
    assert result['advanced']['named_raw_values']['expected_goals_prevented'] == -32768
    assert result['advanced']['named_raw_values']['expected_goals_overperformance'] == -113
    assert stats.decode_compact(CURRENT_KOBEL, CURRENT_KOBEL_ARRAY)['advanced']['raw_signed16'][47] == -113


def test_null_indirect_uses_explicit_native_integer_getter_zero_default():
    raw = bytes(8) + CURRENT_GORDON[8:]
    result = stats.decode_compact(raw, None)
    assert result['advanced']['state'] == 'native_zero_default_null_indirect'
    assert result['advanced']['raw_signed16'] == [0] * 68
    assert set(result['advanced']['named_raw_values'].values()) == {0}
    assert result['goals'] == 2
    assert result['average_rating'] == 6.864285469055176


@pytest.mark.parametrize('raw,indirect', [
    (b'', None), (bytes(24), None), (bytes(26), None), (bytearray(25), None),
    (CURRENT_GORDON, b''), (CURRENT_GORDON, bytes(135)),
    (CURRENT_GORDON, bytes(137)), (CURRENT_GORDON, bytearray(136)),
    (CURRENT_GORDON, None), (bytes(25), bytes(136)),
])
def test_incomplete_or_inconsistent_input_fails(raw, indirect):
    with pytest.raises(ValueError):
        stats.decode_compact(raw, indirect)


def native_memory():
    base = 0x100000000
    spans = {base + rva: expected for rva, expected in stats.NATIVE_SPANS}
    return base, spans, lambda address, size: spans[address][:size]


def test_native_verifier_accepts_complete_selected_instruction_spans():
    base, _, read = native_memory()
    assert stats.verify_native(read, base) is None


@pytest.mark.parametrize('index', range(len(stats.NATIVE_SPANS)))
def test_each_native_instruction_or_dispatch_span_mismatch_fails(index):
    base, spans, read = native_memory()
    address = base + stats.NATIVE_SPANS[index][0]
    spans[address] = bytes([spans[address][0] ^ 1]) + spans[address][1:]
    with pytest.raises(ValueError, match='native layout changed'):
        stats.verify_native(read, base)


def test_short_native_instruction_read_fails():
    with pytest.raises(ValueError, match='native layout changed'):
        stats.verify_native(lambda address, size: bytes(size - 1), 0)
