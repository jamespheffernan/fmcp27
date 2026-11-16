from copy import deepcopy
import gzip
import json
from pathlib import Path
import struct

import pytest
from fm_live_mcp.observed_assist_annotations import project_assist_annotations, _COUNTER_PROOF


def event(identity, *, side=0, slot=0, peer=1, category=7, flags=4, start=10, end=12):
    raw=bytearray(56);raw[39:43]=bytes((slot,side,peer,category));struct.pack_into('<I',raw,44,identity);struct.pack_into('<H',raw,34,start);struct.pack_into('<HH',raw,48,flags,end);return bytes(raw)


def sample():
    actors={'state':'validated_native_stored_slots','official_match_unique_id':42,'players':[
        {'side_index':s,'stored_player_slot':i,'canonical_person_id':100+s*10+i,'person_name':f'person{s}-{i}'}for s in(0,1)for i in(0,1)]}
    counters=[{'side_index':s,'stored_player_slot':i,'canonical_person_id':100+s*10+i,'assists':int((s,i)==(0,0))}for s in(0,1)for i in(0,1)]
    return actors,counters


def project(raw,actors,counters,**kwargs):
    return project_assist_annotations(raw,actors,counters,cutoff=100,intervals=[('FirstHalf',1,50),('SecondHalf',60,100)],rows_per_side=[2,2],match_unique_id=42,**kwargs)


def test_native_annotation_not_nearest_event_or_general_supplier_link():
    actors,counters=sample();raw=event(1)+event(2,flags=0,start=12,end=12,slot=1,category=1)
    rows=project(raw,actors,counters);assert len(rows)==1
    assert rows[0]['person_native_id']==100 and rows[0]['recipient_person_native_id']==101
    assert rows[0]['shot_event_id']is rows[0]['goal_event_id']is None


def test_same_clock_multiple_assists_preserved_without_arbitrary_shot_pairing():
    actors,counters=sample();counters[1]['assists']=1
    rows=project(event(1)+event(2,slot=1,peer=0),actors,counters)
    assert len(rows)==2 and all(x['start_tick']==10 and x['end_tick']==12 for x in rows)
    assert all(x['shot_event_id']is None for x in rows)


def test_missing_actor_and_unknown_name_are_unknown_without_counter_identity_guess():
    actors,counters=sample();actors['players']=actors['players'][1:]
    row=project(event(1),actors,counters)[0];assert row['person_native_id']is None and row['person_name']is None and row['actor_state']=='unresolved_original_slot'
    actors,counters=sample();actors['players'][0]['person_name']=None
    row=project(event(1),actors,counters)[0];assert row['person_native_id']==100 and row['person_name']is None and row['actor_state']=='canonical_original_slot_name_unknown'


def test_cross_family_raw_peer_is_not_silently_a_completed_pass_recipient():
    actors,counters=sample();row=project(event(1,category=12),actors,counters)[0]
    assert row['native_peer_slot']==1 and row['recipient_person_native_id']is None and row['recipient_state']=='unproved_for_this_annotation'


def test_full_zero_counter_ledger_is_known_empty_but_missing_zeros_reject():
    actors,counters=sample()
    for c in counters:c['assists']=0
    assert project(event(1,flags=0),actors,counters)==[]
    with pytest.raises(ValueError,match='Incomplete'):project(event(1,flags=0),actors,counters[:-1])


@pytest.mark.parametrize('fault',['missing_flag','extra_flag','counter_person','duplicate_actor','duplicate_counter','bad_side','cutoff_tie','reversed','duplicate_event','wrong_match','ambiguous_period'])
def test_mismatch_unknown_or_ambiguous_sources_fail_closed(fault):
    actors,counters=sample();raw=event(1)
    if fault=='missing_flag':raw=event(1,flags=0)
    elif fault=='extra_flag':raw+=event(2)
    elif fault=='counter_person':counters[0]['canonical_person_id']=999
    elif fault=='duplicate_actor':actors['players'].append(dict(actors['players'][0]))
    elif fault=='duplicate_counter':counters[1]=dict(counters[0])
    elif fault=='bad_side':raw=event(1,side=2)
    elif fault=='cutoff_tie':raw=event(1,start=90,end=100)
    elif fault=='reversed':raw=event(1,start=20,end=10)
    elif fault=='duplicate_event':raw+=event(1,flags=0)
    elif fault=='wrong_match':actors['official_match_unique_id']=43
    else:
        with pytest.raises(ValueError,match='Ambiguous'):project_assist_annotations(raw,actors,counters,cutoff=100,intervals=[('FirstHalf',1,50),('SecondHalf',1,50)],rows_per_side=[2,2],match_unique_id=42)
        return
    with pytest.raises(ValueError):project(raw,actors,counters)


def test_actual_40_counter_control_3_named_observed_markers_and_retained_flag_omission():
    f=json.loads(gzip.decompress((Path(__file__).parent/'fixtures/active_pass_locations_185.json.gz').read_bytes()));raw=bytes.fromhex(f['raw_event_hex']);kwargs={'cutoff':23929,'intervals':[('FirstHalf',1,11655),('SecondHalf',11715,23929)],'rows_per_side':[20,20],'match_unique_id':f['match_unique_id']}
    rows=project_assist_annotations(raw,f['actors'],_COUNTER_PROOF['rows'],**kwargs)
    assert [(r['event_id'],r['person_name'])for r in rows]==[(1066,'Alberto Costa'),(1218,'Konstantinos Karetsas'),(1717,'Julio Enciso')]
    assert len(_COUNTER_PROOF['rows'])==40 and sum(r['assists']==0 for r in _COUNTER_PROOF['rows'])==37
    enciso=rows[-1];assert enciso['end_tick']==18487 and enciso['native_peer_slot']==14 and enciso['recipient_person_native_id']is None
    assert all(r['shot_event_id']is None and r['goal_event_id']is None for r in rows)
    stripped=bytearray(raw)
    for at in range(0,len(stripped),56):stripped[at+48]&=~4
    with pytest.raises(ValueError,match='do not close'):project_assist_annotations(bytes(stripped),f['actors'],_COUNTER_PROOF['rows'],**kwargs)
