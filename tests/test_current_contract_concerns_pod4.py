"""Causal old-red/new-green qualification for this native 28-byte POD family."""
from pathlib import Path
import importlib.util
import struct
import pytest
from test_current_contract_concerns_candidate import (concern_memory,agreed_memory,public_assessment_memory,shortlist_public_memory,
    prepared_tactics_memory,bridge,database_memory,memory,team_memory,world_memory,H,PLUGIN,SOURCE as OLD)

SPEC=importlib.util.spec_from_file_location('qualified_concern_pod4',H/'current_contract_concerns_pod4_candidate.py')
NEW=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(NEW)


@pytest.fixture
def pod4_memory(concern_memory):
    m=concern_memory
    with PLUGIN.open('rb')as native:
        for rva,size,digest in NEW.SOURCE:
            native.seek(0x5ed4000+rva);m['put'](m['base']+rva,native.read(size))
    return m


def single(m,address):
    raw=m['read'](m['concern_a'],28);m['put'](address,raw)
    header=bytearray(96);header[0]=1;struct.pack_into('<Q',header,8,address);m['put'](m['concern_ring'],header)
    return raw


def inspect(m,read=None):
    return NEW.inspect(read or m['read'],m['base'],m['concern_primary'],'actual',include_stored_name=True)


def test_old_red_new_green_actual_4mod8_pod_pointer(pod4_memory):
    m=pod4_memory;record=m['allocate'](64)+4;assert record%8==4
    single(m,record)
    with pytest.raises(ValueError,match='source object pointer'):
        OLD.inspect(m['read'],m['base'],m['concern_primary'],'actual')
    result=inspect(m)
    assert result['owner']['display_name']=='Test Müller'and result['native_ring_entry_count']==1
    assert result['records'][0]['record']['native_reason_code']==650
    assert result['UI_or_fulfilment_evaluated']is False


@pytest.mark.parametrize('residue',[1,2,3,5,6,7])
def test_odd_and_2mod4_pod_addresses_refuse_without_partial_result(pod4_memory,residue):
    m=pod4_memory;single(m,m['allocate'](64)+residue)
    with pytest.raises(ValueError,match='qualified 28-byte'):
        inspect(m)


@pytest.mark.parametrize('address',[0,True,4092,(1<<64)-4,1<<64])
def test_invalid_null_low_boolean_and_overflow_pod_guard_refuse(address):
    with pytest.raises(ValueError,match='qualified 28-byte'):
        NEW.pod_record_pointer(address)


def test_null_ring_slot_stays_explicit_and_is_not_an_unavailable_collection(pod4_memory):
    m=pod4_memory;single(m,m['allocate'](64)+4);m['q'](m['concern_ring']+8,0)
    result=inspect(m)
    assert result['native_ring_entry_count']==1 and result['native_unset_end_filter_count']==0
    assert result['records'][0]['state']=='null_native_ring_slot'and result['records'][0]['record']is None


def test_object_pointer8_remains_strict(pod4_memory):
    m=pod4_memory
    with pytest.raises(ValueError,match='source object pointer'):
        NEW.inspect(m['read'],m['base'],m['concern_primary']+4,'actual')
    with pytest.raises(ValueError,match='source object pointer'):
        NEW.pointer(0x1004)


def test_original_stride_and_consuming_rule_bytes_qualify_pod4(pod4_memory):
    m=pod4_memory;m['put'](m['base']+0xfedd88,struct.pack('<I',0x52800403))  # MOV W3,#32 instead of28
    with pytest.raises(ValueError,match='source changed'):
        inspect(m)


@pytest.mark.parametrize('truncate',[False,True])
def test_28byte_record_crosses_page_and_missing_tail_refuses(pod4_memory,truncate):
    m=pod4_memory;allocation=m['allocate'](12288);record=((allocation+4095)&~4095)+4096-12
    assert record%8==4 and record//4096!=(record+27)//4096
    raw=single(m,record);reads=[]
    def read(address,size):
        reads.append((address,size))
        return raw[:-1]if truncate and address==record and size==28 else m['read'](address,size)
    if truncate:
        with pytest.raises(ValueError,match='Incomplete native concern record'):inspect(m,read)
    else:
        assert inspect(m,read)['records'][0]['record']['native_reason_code']==650
    assert(record,28)in reads
