"""Genuine29 source projection plus explicitly synthetic malformed/absent inputs."""
from collections import Counter
import struct

import pytest
from fm_live_mcp import individual_training_role_position as source,world
from training_role_fixture import GenuineTraining


def test_all29_genuine_source_values_match_qualified_original_operators():
    f=GenuineTraining();read=world.ReadSet(f.read);source.verify_native(read,f.base)
    states=Counter();oop_codes=Counter()
    for row,native in zip(f.rows,f.native['rows'],strict=True):
        out=source.inspect(read,f.base,row['primary']);ip=out['ip_training'];oop=out['oop_training']
        assert int(ip['native_role_mask'],16)==int(native['native_IP_mask'],16)
        assert int(ip['native_position_mask'],16)==int(native['original_audit_prefix_IP_position_mask'],16)
        assert oop['native_code']==native['native_OOP_signed_code']
        assert oop['source_state']=='present_child' and oop['native_code_source']=='stored_signed_halfword'
        assert ip['role_name'] is ip['position_name'] is oop['role_name'] is None
        assert out['label_state']=='not_proved_for_training_namespace'
        assert out['planned_training_evaluated'] is out['applied_training_evaluated'] is out['effective_training_evaluated'] is False
        assert not any(key in str(out)for key in ('raw_hex','address','date_started'))
        states[ip['state']]+=1;oop_codes[oop['native_code']]+=1
    read.verify()
    assert states=={'checked_native_nonzero':26,'checked_native_zero':3}
    assert oop_codes[0]==3 and len(oop_codes)==14 and 50 not in oop_codes


def put(f,at,raw):f.cells.update((at+i,value)for i,value in enumerate(raw))


def test_synthetic_missing_IP_child_is_not_a_captured_empty_vector():
    f=GenuineTraining();empty=source.inspect(f.read,f.base,f.rows[10]['primary'])['ip_training']
    primary=f.rows[0]['primary'];put(f,primary+0x1A0,bytes(8))
    missing=source.inspect(f.read,f.base,primary)['ip_training']
    assert empty['source_state']=='checked_empty_vector' and empty['native_role_mask']=='0x0000000000000000'
    assert missing['source_state']=='missing_child' and missing['native_role_mask'] is None
    assert missing['stored_occurrence_count'] is missing['selected_stored_slot'] is None


@pytest.mark.parametrize('code',[-32768,-31,-1,0,50,32767])
def test_synthetic_signed_OOP_codes_keep_presence_and_do_not_gain_names(code):
    f=GenuineTraining();row=f.rows[0];child=row['fields']['oop_child']['address']
    put(f,child+6,struct.pack('<h',code));out=source.inspect(f.read,f.base,row['primary'])['oop_training']
    assert out['source_state']=='present_child' and out['native_code']==code
    assert out['raw_code']==code&65535 and out['role_name'] is None


def test_synthetic_missing_OOP_preserves_native_fallback50_with_no_raw_code():
    f=GenuineTraining();primary=f.rows[0]['primary'];child=f.rows[0]['fields']['oop_child']['address']
    put(f,child+6,struct.pack('<h',50));present=source.inspect(f.read,f.base,primary)['oop_training']
    put(f,primary+0x198,bytes(8));missing=source.inspect(f.read,f.base,primary)['oop_training']
    assert present['native_code']==missing['native_code']==50
    assert present['source_state']=='present_child' and present['raw_code']==50
    assert missing['source_state']=='missing_child' and missing['raw_code'] is None
    assert missing['native_code_source']=='native_missing_child_fallback'


@pytest.mark.parametrize('fault',['unaligned_header','reversed','partial','capacity','missing_OOP_byte','invalid_OOP_pointer'])
def test_synthetic_invalid_geometry_and_missing_bytes_are_fatal(fault):
    f=GenuineTraining();row=f.rows[0];primary=row['primary'];child=row['fields']['ip_child']['address']
    start,end,capacity=struct.unpack('<QQQ',f.read(child,24))
    if fault=='unaligned_header':put(f,primary+0x1A0,struct.pack('<Q',child+1))
    elif fault=='reversed':put(f,child,struct.pack('<QQQ',end,start,capacity))
    elif fault=='partial':put(f,child,struct.pack('<QQQ',start,start+8,capacity))
    elif fault=='capacity':put(f,child,struct.pack('<QQQ',start,end,start+257*24))
    elif fault=='missing_OOP_byte':del f.cells[row['fields']['oop_child']['address']+6]
    else:put(f,primary+0x198,struct.pack('<Q',1))
    with pytest.raises(ValueError):source.inspect(f.read,f.base,primary)


def test_synthetic_unaligned_plain_OOP_pool_record_is_supported():
    f=GenuineTraining();row=f.rows[0];child=row['fields']['oop_child']['address'];at=0x200000001
    put(f,at,f.read(child,12));put(f,row['primary']+0x198,struct.pack('<Q',at))
    assert source.inspect(f.read,f.base,row['primary'])['oop_training']['source_state']=='present_child'


def test_original_twelve_byte_pool_source_is_required():
    f=GenuineTraining();at=f.base+0x17F5E00;f.cells[at]^=1
    with pytest.raises(ValueError,match='OOP pool source changed'):source.verify_native(f.read,f.base)
