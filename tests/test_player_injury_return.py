"""Independent observed input fixture and audited calendar/float32 boundaries."""
from datetime import date
import json
from pathlib import Path
import struct
import pytest
from fm_live_mcp import player_injury_return as source

FIXTURE=json.loads((Path(__file__).parent/'fixtures/injury_return_observed.json').read_text())
RAW=bytes.fromhex(FIXTURE['injury_raw_hex'])
NOW=bytes.fromhex(FIXTURE['current_date_raw_hex'])
SKILL=FIXTURE['staff_inputs']


def packed(value):
    d=date.fromisoformat(value)
    return ((d.year<<16)|d.timetuple().tm_yday).to_bytes(4,'little')


def injury(start='2030-01-01',low=1,high=100):
    raw=bytearray(RAW);raw[0x20:0x24]=packed(start)
    struct.pack_into('<h',raw,0x2a,low);struct.pack_into('<h',raw,0x28,high)
    return bytes(raw)


def test_observed_native_remaining_day_units_and_explicit_conversion():
    r=source.reconstruct(RAW,NOW,SKILL,0)
    assert r['remaining_calendar_days']=={'minimum':39,'maximum':62}
    assert r['calendar_conversion']=={'earliest':'2030-12-06','latest':'2030-12-29','state':'derived_estimated_dates_not_stored_return_dates'}
    assert r['native_inputs']['base_remaining_days']==[34,54]
    assert r['native_inputs']['staff_score']==69
    assert r['native_inputs']['uncertainty_float32']==0.3100000023841858
    assert r['scope']['resident_report_observed'] is False
    assert r['scope']['medical_clearance']==r['scope']['match_eligibility']=='not_assessed'


@pytest.mark.parametrize('mode,days',[(0,[39,62]),(1,[34,54]),(2,[34,54]),(3,[39,62])])
def test_audited_mode_branches(mode,days):
    assert list(source.reconstruct(RAW,NOW,SKILL,mode)['remaining_calendar_days'].values())==days


def test_new_date_and_staff_inputs_recalculate_rather_than_fix_return_dates():
    following=source.reconstruct(RAW,packed('2030-10-29'),SKILL,0)
    assert following['remaining_calendar_days']=={'minimum':37,'maximum':61}
    changed=source.reconstruct(RAW,NOW,{'native_DA_u16':100,'physiotherapy_raw_signed8':50,'people_management_raw_signed8':50},0)
    assert changed['remaining_calendar_days']=={'minimum':46,'maximum':74}


@pytest.mark.parametrize('low,high,days',[(1,100,[57,115]),(1,4,[1,4]),(0,0,[1,1])])
def test_ratio_floor_under_five_and_minimum_one(low,high,days):
    result=source.reconstruct(injury(low=low,high=high),packed('2030-01-01'),SKILL,0)
    assert list(result['remaining_calendar_days'].values())==days


@pytest.mark.parametrize('value',[None,True,-1,4,255])
def test_unproved_modes_fail_explicitly(value):
    with pytest.raises(source.UnsupportedEstimate,match='medical_mode'):source.reconstruct(RAW,NOW,SKILL,value)


@pytest.mark.parametrize('field,value',[('native_DA_u16',-1),('native_DA_u16',32768),('physiotherapy_raw_signed8',-1),('physiotherapy_raw_signed8',101),('people_management_raw_signed8',-1),('people_management_raw_signed8',101),('native_DA_u16',True)])
def test_unsupported_raw_skill_inputs_remain_unknown(field,value):
    with pytest.raises(source.UnsupportedEstimate,match='medical_skill'):source.reconstruct(RAW,NOW,{**SKILL,field:value},0)


@pytest.mark.parametrize('at,value,reason',[(8,bytes(8),'definition'),(0x30,b'\1','treatment'),(0x33,b'\0','byte33'),(0x20,bytes(4),'date'),(0x28,struct.pack('<h',-1),'duration'),(0x2a,struct.pack('<h',65),'duration'),(0x28,struct.pack('<h',367),'duration')])
def test_unproved_injury_branches_do_not_fabricate_windows(at,value,reason):
    raw=bytearray(RAW);raw[at:at+len(value)]=value
    with pytest.raises(source.UnsupportedEstimate,match=reason):source.reconstruct(raw,NOW,SKILL,0)


@pytest.mark.parametrize('current',['2030-10-17','2030-12-02','2031-01-01','1900-01-01'])
def test_before_start_after_minimum_and_unset_current_date(current):
    with pytest.raises(source.UnsupportedEstimate):source.reconstruct(RAW,packed(current),SKILL,0)


def test_cross_year_native_date_branch_is_unknown_not_a_calendar_guess():
    with pytest.raises(source.UnsupportedEstimate,match='cross_year'):
        source.reconstruct(injury('2030-12-01',44,64),packed('2030-12-10'),SKILL,0)


def test_native_guards_do_not_silently_accept_changed_game_code():
    with pytest.raises(ValueError,match='native code changed'):
        source.verify_native(lambda address,length:bytes(length),0x100000)
