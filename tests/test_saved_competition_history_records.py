"""Portable original rows plus independent native wire/edge controls."""
import json
from pathlib import Path
import struct
import pytest
from fm_live_mcp import saved_competition_history_records as codec

FIXTURE = Path(__file__).parent/'fixtures'/'saved_competition_history_rows.json'


def test_all_distinct_original_source_fields_and_every_truncation():
    fixture=json.loads(FIXTURE.read_text())
    assert fixture['observation_count']==1024 and fixture['distinct_row_count']==256
    for expected in fixture['rows']:
        raw=bytes.fromhex(expected['raw_hex']);result=codec.decode(raw)
        assert result['raw_record_hex']==expected['raw_hex']
        for key,value in expected.items():
            if key!='raw_hex':assert result[key]==value
        for length in range(55):
            with pytest.raises(ValueError):codec.decode(raw[:length])
        with pytest.raises(ValueError):codec.decode(raw+b'x')


def raw(**kwargs):
    data=bytearray(55)
    for offset,fmt,value in ((0,'i',-2147483648),(4,'h',kwargs.get('year',2029)),
                             (6,'H',65535),(8,'i',-1),(12,'i',-17),(44,'B',255),
                             (45,'H',65535),(47,'h',kwargs.get('start',-10)),
                             (49,'h',kwargs.get('end',-5)),(51,'I',kwargs.get('date',0))):
        struct.pack_into('<'+fmt,data,offset,value)
    return data


def test_signed_and_unmapped_values_retained_without_contextual_identity_claim():
    result=codec.decode(raw())
    assert result['competition_index_word']==-2147483648 and result['second_placed_team_index']==-17
    assert result['unmapped_fields']['native_0x56_unsigned16']==65535
    assert result['unmapped_fields']['native_0x5E_byte']==255
    assert result['unmapped_fields']['history_flags_unsigned16']==65535
    assert (result['start_year'],result['end_year'])==(-10,-5)
    assert (result['native_effective_start_year'],result['native_effective_end_year'])==(2029,2029)
    assert result['native_year_correction_applied'] is True


@pytest.mark.parametrize('end,corrected',[(1900,False),(2029,False),(2030,False),(1899,True),(-32768,True)])
def test_exact_native_end_year_sentinel_and_signed_comparison(end,corrected):
    assert codec.decode(raw(end=end))['native_year_correction_applied'] is corrected


@pytest.mark.parametrize('value,state,projected',[(1900<<16|1,'native_unset',None),
 (2030<<16|366,'unmapped_native_date',None),(2028<<16|366,'stored_Date_Decided','2028-12-31'),
 (0,'unmapped_native_date',None),(2029<<16|143,'stored_Date_Decided','2029-05-23')])
def test_native_date_bits_unset_and_calendar_domain(value,state,projected):
    out=codec.decode(raw(date=value|0xFE00))['date_decided']
    assert out['state']==state and out['value']==projected
    assert out['unmapped_high7']==127 and out['raw_hex']==struct.pack('<I',value|0xFE00).hex()
