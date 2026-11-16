"""Independent version-7 archive captures plus codec framing/failure checks."""
import struct

import pytest

from fm_live_mcp import archived_player_statistics as archive, player_statistics


# Frozen native archive bytes: history-01 census, Gordon66956904 and Kobel49571256.
GORDON = bytes.fromhex(
    '00210200000700ffffffffed0729027c010000000002000007010802010000031200020006000100fb00d300060004000f0002'
    '0015000c0005000d0006000000000000000000000001001100000052020500170008001200000000001000070004000000'
    '500023006f009e000000000000000100020001000000170006000000780000001a00350008000a006f0059002e000d000200'
    '0d0000000000000000000000000000000000')
KOBEL = bytes.fromhex(
    '00210200000700ffffffffed071702d0021100000000010008000800000000040e00110002000400a900a50001000000'
    '060012000000000000000000000000000000000000007c04020000002900450100000500ab0200000000000003000000'
    '2d0000000c003b00000000000b0000000000000000000000000000000000d8fd00000000020000000000000000000000'
    '000000000000000000000000000000000000000000000000')
PREFIX = {'consumed_bytes': 7,
          'team_reference': {'tag': 0, 'index': 545, 'state': 'table_index'},
          'competition_reference': {'marker': 7, 'index': 7, 'state': 'table_index', 'extended': False}}


@pytest.mark.parametrize('raw,category,expected', [
    (GORDON, 'Continental',
     {'starting_appearances': 7, 'sub_appearances': 1, 'total_appearances': 8,
      'goals': 2, 'assists': 1, 'minutes': 380, 'total_rating_tenths': 553,
      'rating_denominator': 8, 'average_rating': 6.912499904632568,
      'goals_conceded': 0, 'clean_sheets': 0}),
    (KOBEL, 'International',
     {'starting_appearances': 8, 'sub_appearances': 0, 'total_appearances': 8,
      'goals': 0, 'assists': 0, 'minutes': 720, 'total_rating_tenths': 535,
      'rating_denominator': 8, 'average_rating': 6.6875,
      'goals_conceded': 17, 'clean_sheets': 1}),
])
def test_independent_outfield_and_goalkeeper_archive_samples(raw, category, expected):
    result = archive.decode_record(raw, PREFIX)
    assert result['native_year'] == 2029
    assert result['category_name'] == category
    assert {key: result['statistics'][key] for key in expected} == expected
    assert result['raw_metadata'] == {'native_0x18_signed32': -1, 'native_0x2f_u8': 0}
    assert len(result['statistics']['advanced']['raw_signed16']) == 68
    assert result['statistics']['advanced']['units'] == 'unverified_native_units'
    assert 'team_reference' not in result and 'competition_reference' not in result
    assert not any('fee' in key or 'season' in key for key in result)


def test_native_copy_matches_independent_compact_scalar_sample():
    # Scalar values cross-checked with the independent native archive census.
    compact = bytes.fromhex('001000000000000029027c0107010802010000000000020000')
    expected = player_statistics.decode_compact(compact, GORDON[32:])
    assert archive.decode_record(GORDON, PREFIX)['statistics'] == expected


def test_extended_prefix_consumes_its_actual_bytes_without_fixed_body_offsets():
    raw = GORDON[:5] + struct.pack('<hi', -2, 40000) + GORDON[7:]
    prefix = {**PREFIX, 'consumed_bytes': 11,
              'competition_reference': {'marker': -2, 'index': 40000,
                                        'state': 'table_index', 'extended': True}}
    assert len(raw) == 172
    assert archive.decode_record(raw, prefix) == archive.decode_record(GORDON, PREFIX)
    with pytest.raises(ValueError, match='Unsupported or corrupt.*body length'):
        archive.decode_record(raw[:168], prefix)
    with pytest.raises(ValueError, match='body length'):
        archive.decode_record(raw, PREFIX)


@pytest.mark.parametrize('code,name', [
    (0, 'Non Competitive'), (1, 'League'), (2, 'Cup'),
    (3, 'Continental'), (4, 'International'), (5, 'Overall (Club)'),
])
def test_all_proved_categories_remain_independent(code, name):
    raw = bytearray(GORDON)
    raw[31] = code
    result = archive.decode_record(bytes(raw), PREFIX)
    assert result['native_category_code'] == code and result['category_name'] == name
    assert result['statistics']['goals'] == 2


@pytest.mark.parametrize('code', [6, 127, 128, 255])
def test_unproved_category_codes_fail(code):
    raw = bytearray(GORDON)
    raw[31] = code
    with pytest.raises(ValueError, match='category'):
        archive.decode_record(bytes(raw), PREFIX)


@pytest.mark.parametrize('year', [0, 1, 65535])
def test_year_and_unmapped_metadata_keep_native_values_without_guessed_meaning(year):
    raw = bytearray(GORDON)
    struct.pack_into('<iH', raw, 7, -2147483648, year)
    raw[30] = 255
    result = archive.decode_record(bytes(raw), PREFIX)
    assert result['native_year'] == year
    assert result['raw_metadata'] == {'native_0x18_signed32': -2147483648, 'native_0x2f_u8': 255}
    assert set(result) == {'native_year', 'native_category_code', 'category_name', 'statistics', 'raw_metadata'}


def test_signed_array_rating_short_and_byte_sentinel_bits_survive_native_copy():
    raw = bytearray(KOBEL)
    struct.pack_into('<hh', raw, 13, -1, -32768)
    raw[24], raw[27], raw[28], raw[26] = 255, 255, 255, 255
    struct.pack_into('<hh', raw, 32 + 47*2, -32768, -1)
    result = archive.decode_record(bytes(raw), PREFIX)['statistics']
    assert result['total_rating_tenths'] == -1 and result['minutes'] == -32768
    assert result['starting_appearances'] is None and result['total_appearances'] is None
    assert result['goals'] is None and result['assists'] is None
    assert result['native_raw']['goals'] == 255
    assert result['native_getter_values']['assists'] == -1
    assert result['rating_denominator'] is None
    assert result['average_rating'] == -0.0003921568568330258
    assert result['advanced']['raw_signed16'][47:49] == [-32768, -1]
    assert archive.decode_record(KOBEL, PREFIX)['statistics']['advanced']['raw_signed16'][47] == -552


def test_zero_rating_denominator_retains_native_result_without_unrated_claim():
    raw = bytearray(GORDON)
    raw[26] = 0
    result = archive.decode_record(bytes(raw), PREFIX)['statistics']
    assert result['average_rating'] == 0.0 and result['rating_denominator'] == 0
    assert 'unrated' not in result


@pytest.mark.parametrize('raw', [b'', GORDON[:-1], GORDON + b'\0', bytearray(GORDON), None])
def test_raw_type_truncation_and_trailing_bytes_fail(raw):
    with pytest.raises(ValueError):
        archive.decode_record(raw, PREFIX)


@pytest.mark.parametrize('prefix', [
    None, [], {}, {'consumed_bytes': 7}, {**PREFIX, 'consumed_bytes': True},
    {**PREFIX, 'consumed_bytes': '7'}, {**PREFIX, 'consumed_bytes': -1},
    {**PREFIX, 'consumed_bytes': 0}, {**PREFIX, 'consumed_bytes': 6},
    {**PREFIX, 'consumed_bytes': 8}, {**PREFIX, 'consumed_bytes': 12},
])
def test_invalid_or_unsupported_prefix_fails(prefix):
    with pytest.raises(ValueError):
        archive.decode_record(GORDON, prefix)


def native_memory():
    base = 0x100000000
    spans = {base + rva: data for rva, data in (*player_statistics.NATIVE_SPANS, *archive.NATIVE_SPANS)}
    return base, spans, lambda address, size: spans[address][:size]


def test_native_verifier_accepts_selected_archive_copy_and_category_spans():
    base, _, read = native_memory()
    assert archive.verify_native(read, base) is None


@pytest.mark.parametrize('index', range(len(archive.NATIVE_SPANS)))
def test_each_archive_native_span_mismatch_fails(index):
    base, spans, read = native_memory()
    address = base + archive.NATIVE_SPANS[index][0]
    spans[address] = bytes([spans[address][0] ^ 1]) + spans[address][1:]
    with pytest.raises(ValueError, match='native layout changed'):
        archive.verify_native(read, base)


def test_shared_compact_native_verifier_mismatch_also_fails():
    base, spans, read = native_memory()
    address = base + player_statistics.NATIVE_SPANS[0][0]
    spans[address] = bytes(len(spans[address]))
    with pytest.raises(ValueError, match='native layout changed'):
        archive.verify_native(read, base)
