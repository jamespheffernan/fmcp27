"""Synthetic empty original query path and strict refusal controls only."""
import importlib.util
from pathlib import Path
import struct
from datetime import date,timedelta
import pytest

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'evidence/social-promises-20261109/native_event_query_vm.py'
spec=importlib.util.spec_from_file_location('original_event_query',P);vm=importlib.util.module_from_spec(spec);spec.loader.exec_module(vm)
import _pinned_build
PLUGIN=_pinned_build.PLUGIN
BASE,HUMAN,HISTORY=0x100000000,0x200000000,0x200010000
CUTOFF=struct.pack('<I',(2030<<16)|317)


class Source:
    def __init__(self):
        self.cells={}
        with PLUGIN.open('rb')as stream:
            stream.seek(0x5ed4000+0x12dc000);self.write(BASE+0x12dc000,stream.read(4096))
        self.write(HUMAN+0x388,struct.pack('<Q',HISTORY));self.write(HISTORY+0x110,b'\0')
    def write(self,address,raw):
        for i,value in enumerate(raw):self.cells[address+i]=value
    def read(self,address,size):
        try:return bytes(self.cells[address+i]for i in range(size))
        except KeyError as error:raise ValueError('Missing synthetic query operand')from error


def date_source(raw):
    source=Source()
    with PLUGIN.open('rb')as stream:
        stream.seek(0x5ed4000+0x2469ef8);source.write(BASE+0x2469ef8,stream.read(120))
    source.write(BASE+0x56b1db8,raw)
    return source


@pytest.mark.parametrize('year',[1899,1900,1901,1999,2000,2001,2030,2032,2099,2100])
@pytest.mark.parametrize('day',[1,7,14,15,16,330,365])
@pytest.mark.parametrize('flags',[0,0xfe00])
def test_original_cutoff_prefix_matches_calendar_minus_fourteen_days(year,day,flags):
    raw=struct.pack('<I',(year<<16)|day|flags);source=date_source(raw)
    result=vm.original_cutoff(source.read,BASE,HUMAN)
    expected=date(year,1,1)+timedelta(days=day-15)
    packed=(expected.year<<16)|(expected.timetuple().tm_yday)|flags
    assert result['cutoff_raw_hex']==struct.pack('<I',packed).hex()
    assert result['query_called']is result['game_calls']is result['whole_override_executed']is False


def test_invalid_non_leap_current_day_has_no_default_cutoff():
    source=date_source(struct.pack('<I',(2030<<16)|366))
    with pytest.raises(ValueError,match='current day'):vm.original_cutoff(source.read,BASE,HUMAN)


def test_full_original_empty_ring_query_returns_without_allocator_or_callee_stubs():
    source=Source();result=vm.execute(source.read,BASE,HUMAN,CUTOFF)
    assert result['state']=='complete_original_event_query_return'
    assert result['event_count']==0 and result['event_pointers_private']==[]
    assert result['trace'][0]==0x12dc0b4 and result['trace'][-1]==0x12dc2c8
    assert result['caller_output_capacity']==120
    assert result['game_calls']is result['callee_stubs']is result['non_stack_writes']is result['full_override_executed']is False


@pytest.mark.parametrize('address',[HUMAN+0x388,HISTORY+0x110,BASE+0x12dc0b4])
def test_missing_original_query_operand_rejects_without_refill(address):
    source=Source();source.cells.pop(address)
    with pytest.raises(ValueError,match='Missing synthetic'):vm.execute(source.read,BASE,HUMAN,CUTOFF)


@pytest.mark.parametrize('count,head',[(121,0),(255,0),(1,120),(120,255)])
def test_corrupt_ring_geometry_is_not_truncated(count,head):
    source=Source();source.write(HISTORY+0x110,bytes([count]));source.write(HISTORY+0x4d8,bytes([head]))
    with pytest.raises(ValueError,match='120-slot geometry'):vm.execute(source.read,BASE,HUMAN,CUTOFF)


@pytest.mark.parametrize('cutoff',[None,0,b'',b'123',b'12345'])
def test_invalid_cutoff_does_not_get_a_default_date(cutoff):
    source=Source()
    with pytest.raises(ValueError,match='cutoff'):vm.execute(source.read,BASE,HUMAN,cutoff)


def test_original_unknown_system_state_is_refused_for_query_too():
    source=Source();source.write(BASE+0x12dc0b4,struct.pack('<I',0xd53bd042))
    result=vm.execute(source.read,BASE,HUMAN,CUTOFF)
    assert result['state']=='unsupported_original_event_query_path'
    assert 'system instruction'in result['reason']and result['event_count']is None
