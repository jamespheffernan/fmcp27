"""Owning live Bridge binding, per-record states and torn-input rejection."""
import json,struct
from pathlib import Path
import pytest
from fm_live_mcp import player_injury_return as source,world
from fm_live_mcp.bridge import BridgeError
from test_assessment_public import (public_assessment_memory,bridge,shortlist_public_memory,
                                    prepared_tactics_memory,database_memory,memory,team_memory,world_memory)

FIXTURE=json.loads((Path(__file__).parent/'fixtures/injury_return_observed.json').read_text())


@pytest.fixture
def return_world(public_assessment_memory,bridge,monkeypatch):
    m=public_assessment_memory;ref=m['assessment_player_ref'];primary=bridge.player_refs[ref]['address']
    definition=m['typed']('injury',0x28);m['put'](definition+8,struct.pack('<III',0,38,38));m['q'](definition+0x18,m['text']('hip injury'))
    m['vec'](m['headers']['injuries'],[definition])
    raw=bytearray.fromhex(FIXTURE['injury_raw_hex']);struct.pack_into('<Q',raw,8,definition)
    row=m['allocate'](56);m['put'](row,bytes(raw));header=m['allocate'](24);m['vec'](header,[row]);m['q'](primary+0xf0,header)
    m['put'](m['base']+world.CURRENT_DATE,bytes.fromhex(FIXTURE['current_date_raw_hex']))
    m['put'](m['base']+0x56d4951,b'\0')
    marker=m['allocate'](8);m['put'](marker,struct.pack('<Hbb',150,96,84)+bytes(4))
    calls=[]
    def context(read,base,address,cache):
        calls.append(address);da,physio,people=struct.unpack('<Hbb',read(marker,4))
        return {'selected_staff':{'raw_medical_inputs':{'native_DA_u16':da,'physiotherapy_raw_signed8':physio,'people_management_raw_signed8':people}},'selection':'test context'}
    monkeypatch.setattr(source,'verify_native',lambda *_:None)
    monkeypatch.setattr(source,'_medical_service',lambda *_:None)
    monkeypatch.setattr(source,'_club_physio',context)
    m.update(return_ref=ref,return_primary=primary,return_row=row,return_header=header,skill_marker=marker,context_calls=calls)
    return m


def call(bridge,m,refs=None):return bridge.get_player_injury_return_estimates(bridge.session,refs or [m['return_ref']])


def test_supported_range_order_and_duplicates_without_new_references(bridge,return_world):
    m=return_world;before=dict(bridge.player_refs);ref=m['return_ref']
    result=call(bridge,m,[ref,ref]);a,b=result['players'];assert a==b and bridge.player_refs==before
    assert a['native_identity']['native_id']==12345 and a['display_name']=='Test Müller'
    estimate=a['injury_return'];assert estimate['state']=='reconstructed' and estimate['injury_record_count']==1
    row,=estimate['records'];assert row['definition']['name']=='hip injury'
    assert row['estimate']['remaining_calendar_days']=={'minimum':39,'maximum':62}
    assert len(m['context_calls'])==1
    assert result['scope']['medical_clearance']==result['scope']['match_eligibility']=='not_assessed'


def test_absent_and_empty_are_checked_sources_not_zero_day_forecasts(bridge,return_world):
    m=return_world;m['put'](m['return_header'],bytes(24))
    empty=call(bridge,m)['players'][0]['injury_return']
    assert empty['state']=='no_stored_injury_records' and empty['injury_source']=='present_vector'
    m['q'](m['return_primary']+0xf0,0)
    absent=call(bridge,m)['players'][0]['injury_return']
    assert absent['state']=='no_stored_injury_records' and absent['injury_source']=='absent_optional_container'
    assert empty['injury_record_count']==absent['injury_record_count']==0
    assert empty['records']==absent['records']==[] and m['context_calls']==[]


def test_multiple_injuries_keep_individual_supported_and_unknown_results(bridge,return_world):
    m=return_world;row=m['allocate'](56);raw=bytearray(m['read'](m['return_row'],56));raw[0x30]=1;m['put'](row,bytes(raw))
    m['vec'](m['return_header'],[m['return_row'],row])
    result=call(bridge,m)['players'][0]['injury_return']
    assert result['state']=='partial' and result['injury_record_count']==2
    assert result['records'][0]['state']=='reconstructed'
    assert result['records'][1]['estimate'] is None and result['records'][1]['reason']=='unsupported_treatment_branch'
    assert result['aggregate_return_date'] is None


def test_new_current_date_and_staff_are_rebound_each_request(bridge,return_world):
    m=return_world
    assert call(bridge,m)['players'][0]['injury_return']['records'][0]['estimate']['remaining_calendar_days']=={'minimum':39,'maximum':62}
    m['put'](m['base']+world.CURRENT_DATE,struct.pack('<HH',302,2030))
    following=call(bridge,m)['players'][0]['injury_return']['records'][0]['estimate']
    assert following['as_of']=='2030-10-29' and following['remaining_calendar_days']=={'minimum':37,'maximum':61}
    m['put'](m['skill_marker'],struct.pack('<Hbb',100,50,50))
    changed=call(bridge,m)['players'][0]['injury_return']['records'][0]['estimate']
    assert changed['remaining_calendar_days']!=following['remaining_calendar_days']
    assert len(m['context_calls'])==3


@pytest.mark.parametrize('where',['injury','staff','current_date','mode'])
def test_torn_evidence_returns_no_partial_estimate(bridge,return_world,monkeypatch,where):
    m=return_world;original=source.project
    def drift(*args,**kwargs):
        result=original(*args,**kwargs)
        address={'injury':m['return_row']+0x28,'staff':m['skill_marker'],'current_date':m['base']+world.CURRENT_DATE,'mode':m['base']+0x56d4951}[where]
        m['put'](address,bytes([m['read'](address,1)[0]^1]));return result
    monkeypatch.setattr(source,'project',drift)
    with pytest.raises(BridgeError,match='changed during read'):call(bridge,m)


def test_unknown_reference_and_stale_identity_do_not_publish_estimates(bridge,return_world):
    m=return_world
    with pytest.raises(BridgeError,match='Unknown or expired'):call(bridge,m,[m['return_ref'],'wrong'])
    m['put'](0x1394,struct.pack('<I',54321))
    with pytest.raises(BridgeError,match='identity changed'):call(bridge,m)
    assert m['return_ref'] not in bridge.player_refs


@pytest.mark.parametrize('refs',[[],['x']*33,[None],['']])
def test_invalid_batch_rejected(bridge,refs):
    with pytest.raises(BridgeError):bridge.get_player_injury_return_estimates(bridge.session,refs)
