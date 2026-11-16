"""Private concern projection controls on typed synthetic memory only."""
import importlib.util
from pathlib import Path
import struct
import pytest
from fm_live_mcp import players,world
from test_playing_time import (agreed_memory,public_assessment_memory,shortlist_public_memory,
    prepared_tactics_memory,bridge,database_memory,memory,team_memory,world_memory)

H=Path(__file__).resolve().parents[1]/'evidence/social-promises-20261109'
SPEC=importlib.util.spec_from_file_location('current_contract_concerns_candidate',H/'current_contract_concerns_candidate.py')
SOURCE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(SOURCE)
import _pinned_build
PLUGIN=_pinned_build.PLUGIN

@pytest.fixture
def concern_memory(agreed_memory):
    m=agreed_memory;base=m['base'];primary=m['agreed_person']-0x388;table=base+players.RVA[2]
    with PLUGIN.open('rb')as native:
        for rva,size,digest in SOURCE.SOURCE:
            native.seek(0x5ed4000+rva);m['put'](base+rva,native.read(size))
    m['put'](base+0x55edf40,struct.pack('<q',0));m['q'](base+0x55edf48,base+0x55edae0)
    m['q'](base+0x55edf60,base+0x24a9e1c);m['q'](base+0x55edae8,base+0x53bce67);m['put'](base+0x53bce67,SOURCE.RULE)
    m['q'](table+0x3c0,base+0xcb8c68);m['put'](table-0x3d0,struct.pack('<q',-0x110))
    m['q'](primary+0x278,base+0x5589a90);m['put'](base+0x5589a90-16,struct.pack('<q',-0x278))
    m['q'](primary+0x128,m['team']);m['q'](m['agreed_contract']+0x10,m['team'])
    m['q'](base+world.TYPES['full_contract'][0]+0x90,base+0x129fffc)
    ring=m['allocate'](96);a=m['allocate'](32);b=m['allocate'](32)
    raw_a=bytearray(28);struct.pack_into('<IIiiIH',raw_a,0,(2030<<16)|300,(1900<<16)|1|0xfe00,-1,42,7,99)
    struct.pack_into('<H',raw_a,0x16,650);raw_a[0x18:]=bytes([255,7,12,4])
    raw_b=bytearray(raw_a);struct.pack_into('<I',raw_b,4,(2030<<16)|320);struct.pack_into('<H',raw_b,0x16,1000)
    m['put'](a,raw_a);m['put'](b,raw_b)
    header=bytearray(96);header[0]=3;header[0x58]=0
    struct.pack_into('<QQQ',header,8,a,b,a);m['put'](ring,header);m['q'](m['agreed_contract']+0x30,ring)
    m.update(concern_primary=primary,concern_ring=ring,concern_a=a,concern_b=b)
    return m

def inspect(m,**kwargs):return SOURCE.inspect(m['read'],m['base'],m['concern_primary'],'actual',**kwargs)


def test_named_current_owned_full_context_keeps_repeats_dates_and_unmapped_fields(concern_memory,monkeypatch):
    m=concern_memory
    monkeypatch.setattr(players,'decode',lambda *args,**kwargs:(_ for _ in()).throw(AssertionError('No profile decode')))
    result=inspect(m,include_stored_name=True)
    assert result['owner']['display_name']=='Test Müller'
    assert result['owner']['native_identity']['native_id']==12345
    assert result['state']=='observed_native_ring'and result['native_ring_entry_count']==3
    assert result['native_unset_end_filter_count']==2
    assert[row['native_physical_slot']for row in result['records']]==[2,1,0]
    first,middle,last=[row['record']for row in result['records']]
    assert first==last and first['native_reason_code']==650 and middle['native_reason_code']==1000
    assert first['matches_native_unset_end_date']is True and middle['matches_native_unset_end_date']is False
    assert first['stored_end_date']['value']=='1900-01-01'and first['stored_end_date']['unmapped_low_word_flags']==0xfe00
    assert first['native_scalar08']==-1 and first['native_scalar0c']==42 and first['native_scalar14']==99
    assert first['native_scalar18']==-1 and first['native_byte1a']==12 and first['native_flags1b']==4
    assert first['reason_title']is first['satisfaction']is first['promise_fulfilled']is None
    assert result['whole_manager_population_verified']is result['UI_or_fulfilment_evaluated']is False


def test_unnamed_policy_does_not_guess_owner_name(concern_memory):
    assert inspect(concern_memory)['owner']['display_name']is None


@pytest.mark.parametrize('fault',['no_current_team','no_main_contract','no_main_team','basic_contract','foreign_club'])
def test_unavailable_context_is_distinct_from_empty_history(concern_memory,fault):
    m=concern_memory
    expected={'no_current_team':'current_team_unavailable','no_main_contract':'main_contract_unavailable','no_main_team':'main_contract_team_unavailable','basic_contract':'non_FULL_CONTRACT_context_unavailable','foreign_club':'main_contract_outside_current_CLUB_context'}[fault]
    if fault=='no_current_team':m['q'](m['concern_primary']+0x128,0)
    elif fault=='no_main_contract':m['q'](m['agreed_person']-0x98,0)
    elif fault=='no_main_team':m['q'](m['agreed_contract']+0x10,0)
    elif fault=='basic_contract':m['q'](m['agreed_contract'],m['base']+world.TYPES['basic_contract'][0])
    else:
        club=m['typed']('club',0x170);team=m['typed']('team',0xb8);m['q'](team+0x30,club);m['vec'](club+0x18,[team]);m['q'](m['agreed_contract']+0x10,team)
    result=inspect(m)
    assert result['state']==expected and result['records']is result['native_ring_entry_count']is result['native_unset_end_filter_count']is None


@pytest.mark.parametrize('mode',['null','empty'])
def test_observed_null_and_empty_ring_are_explicit_source_states(concern_memory,mode):
    m=concern_memory
    if mode=='null':m['q'](m['agreed_contract']+0x30,0)
    else:m['put'](m['concern_ring'],b'\0')
    result=inspect(m)
    assert result['state']==('absent_native_ring'if mode=='null'else'observed_empty_native_ring')
    assert result['records']==[]and result['native_ring_entry_count']==result['native_unset_end_filter_count']==0


@pytest.mark.parametrize('fault',['source','rule_name','rule_handler','owner','canonical_slot','context_getter','context_displacement','normalized','type_getter','count','head','record_pointer','club_membership','club_identity'])
def test_wrong_source_owner_or_geometry_refuses(concern_memory,fault):
    m=concern_memory;base=m['base'];table=base+players.RVA[2]
    if fault=='source':m['put'](base+0xcb85fc,b'\0')
    elif fault=='rule_name':m['put'](base+0x53bce67,b'X')
    elif fault=='rule_handler':m['q'](base+0x55edf60,base+0x24bfc18)
    elif fault=='owner':m['q'](m['agreed_contract']+8,m['manager']+0x548)
    elif fault=='canonical_slot':
        header=m['headers']['people'];start=struct.unpack('<Q',m['read'](header,8))[0];m['q'](start,m['manager']+0x548)
    elif fault=='context_getter':m['q'](table+0x3c0,base+0xcb3724)
    elif fault=='context_displacement':m['put'](table-0x3d0,struct.pack('<q',0))
    elif fault=='normalized':m['q'](m['concern_primary']+0x278,base+0x5589a98)
    elif fault=='type_getter':m['q'](base+world.TYPES['full_contract'][0]+0x90,base+0x129fffe)
    elif fault=='count':m['put'](m['concern_ring'],b'\x0b')
    elif fault=='head':m['put'](m['concern_ring']+0x58,b'\x0a')
    elif fault=='record_pointer':m['q'](m['concern_ring']+8,0x123)
    elif fault=='club_membership':m['vec'](m['club']+0x18,[])
    else:m['put'](m['club']+0xc,b'\0'*4)
    with pytest.raises(ValueError):inspect(m)


def test_null_slot_and_invalid_date_remain_visible_without_closed_claim(concern_memory):
    m=concern_memory;m['q'](m['concern_ring']+16,0);m['put'](m['concern_a']+4,struct.pack('<I',0))
    result=inspect(m);first,middle,last=result['records']
    assert middle['state']=='null_native_ring_slot'and middle['record']is None
    assert first['record']['stored_end_date']['state']=='unavailable_native_date'
    assert first['record']['matches_native_unset_end_date']is False
    assert first['record']['promise_fulfilled']is None and result['native_unset_end_filter_count']==0


def test_unsupported_record_kind_preserves_unavailable_collection(concern_memory):
    m=concern_memory;result=SOURCE.inspect(m['read'],m['base'],m['concern_primary'],'player_staff')
    assert result['state']=='unsupported_record_kind'and result['records']is None
