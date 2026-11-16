import json
from pathlib import Path
import struct
import pytest
from fm_live_mcp import saved_injury_history_records as codec


@pytest.mark.parametrize('word,value,state', [(0, None, 'unmapped_native_date'), (1900 << 16 | 1, None, 'native_unset'),
    (2028 << 16 | 60, '2028-02-29', 'stored'), (2030 << 16 | 366, None, 'unmapped_native_date'),
    (2030 << 16 | 296 | (64 << 9), '2030-10-23', 'stored')])
def test_stored_date_bits_and_calendar(word, value, state):
    out = codec.stored_date(struct.pack('<I', word))
    assert out['value'] == value and out['state'] == state
    assert int.from_bytes(bytes.fromhex(out['raw_hex']), 'little') == word


def test_signed_reference_and_raw_unknowns_remain_explicit():
    raw = struct.pack('<hiBBIHBB', -1, -2, 255, 128, 0, 65535, 254, 253)
    out = codec.decode(raw)
    assert out['injury_reference']['stored_index'] == -1 and out['injury_reference']['state'] == 'native_null_reference'
    assert out['team_reference']['stored_index'] == -2 and out['team_reference']['state'] == 'native_null_reference'
    assert out['unmapped_fields'] == {'native_0xA_unsigned16': 65535, 'native_0xC_byte': 128,
                                    'native_0xD_byte': 254, 'native_0xE_byte': 255, 'native_0xF_byte': 253}
    assert out['raw_record_hex'] == raw.hex()
    for n in range(16):
        with pytest.raises(ValueError): codec.decode(raw[:n])
    with pytest.raises(ValueError): codec.decode(raw + b'x')


def test_source_301_row_fixture_projection():
    fixtures = json.loads(Path(__file__).with_name('saved_injury_history_fixtures.json').read_bytes())
    assert len(fixtures['rows']) == 301
    for expected in fixtures['rows']:
        out = codec.decode(bytes.fromhex(expected['raw_hex']))
        assert out['stored_date']['value'] == expected['date']
        assert out['injury_reference']['stored_index'] == expected['injury_index']
