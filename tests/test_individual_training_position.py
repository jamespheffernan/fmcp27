"""Native-zero/source distinctions and exact genuine29 position operands."""
import json
from pathlib import Path

import pytest
from fm_live_mcp import individual_training_position as source,world
from test_individual_training_ip_role import occurrence
from training_role_fixture import GenuineTraining


def test_genuine29_selected_codes_masks_and_three_native_zero_sources():
    f=GenuineTraining();counts={};read=world.ReadSet(f.read)
    source.verify_native(read,f.base)
    for row,original in zip(f.rows,f.native['rows'],strict=True):
        result=source.decode(f.entries(row))
        assert int(result['native_mask'],16)==int(original['original_audit_prefix_IP_position_mask'],16)
        selected=row['fields']['ip_role']['selected_stored_slot']
        assert result['selected_stored_slot']==selected
        code=None if selected is None else row['fields']['ip_role']['occurrences'][selected]['native_signed_position_code']
        assert result['native_code']==code
        counts[result['state']]=counts.get(result['state'],0)+1
    read.verify()
    assert counts=={'checked_native_nonzero':26,'no_native_selected_occurrence':3}
    assert len(f.entries(f.rows[10]))==0
    assert f.rows[12]['fields']['ip_role']['occurrences'][0]['native_signed_level_operand']==-63
    assert f.rows[15]['fields']['ip_role']['occurrences'][0]['native_signed_level_operand']==-5


def test_selected_native_zero_code_is_distinct_from_no_selected_occurrence():
    result=source.decode((occurrence(family=-31,position=-14),))
    assert result==dict(state='checked_native_zero',native_code=-14,native_mask='0x00000000',selected_stored_slot=0)
    assert source.decode(())==dict(state='no_native_selected_occurrence',native_code=None,native_mask='0x00000000',selected_stored_slot=None)


def test_native_order_skips_flags_nonpositive_and_unsupported_before_position():
    rows=(occurrence(position=6,flag=1),occurrence(position=9,level=-5),
          occurrence(family=-19,position=11),occurrence(family=-31,position=0),occurrence(position=7))
    assert source.decode(rows)==dict(state='checked_native_nonzero',native_code=0,native_mask='0x00100400',selected_stored_slot=3)


@pytest.mark.parametrize('entries',[None,[],b'',(bytes(23),),(bytearray(24),),(bytes(24),)*257])
def test_unavailable_or_incomplete_input_is_never_an_empty_source(entries):
    with pytest.raises(ValueError):source.decode(entries)


@pytest.mark.parametrize('fault',[None,'changed_code','changed_table','missing_code','missing_table'])
def test_complete_original_code_and_position_table_required(fault):
    spans=json.loads((Path(__file__).parent/'fixtures/individual_training_position_native.json').read_text())
    base=0x100000000;values={base+span['rva']:bytes.fromhex(span['raw_hex'])for span in spans}
    if fault:
        index=0 if fault.endswith('code')else 1;at=base+spans[index]['rva'];raw=values[at]
        values[at]=raw[:-1]if fault.startswith('missing')else bytes([raw[0]^1])+raw[1:]
        with pytest.raises(ValueError):source.verify_native(lambda at,n:values[at],base)
    else:source.verify_native(lambda at,n:values[at],base)
