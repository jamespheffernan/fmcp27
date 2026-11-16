import copy
import hashlib
import json
import sqlite3

import pytest
from test_observed_run_recorder import packet, tactical_document
from fm_live_mcp import observed_run_registry as registry
from fm_live_mcp import observed_run_tactical_capture as producer
from fm_live_mcp import observed_match_runs as runs
from fm_live_mcp.observed_run_recorder import write_prefix
from fm_live_mcp.observed_tactical_settings import SNAPSHOTS_TABLE,CHANGES_TABLE


@pytest.fixture
def recorded(packet,tmp_path,monkeypatch):
    monkeypatch.setattr(registry,'REGISTRY_PATH',tmp_path/'registry.json')
    packet['tactical_observation']=tactical_document(packet,monkeypatch)
    receipt=write_prefix(packet,tmp_path/'store')
    proof=producer.attestation(packet,receipt)
    registry.register_original(receipt['path'],receipt['source_id'],receipt['sha256'],producer_attestation=proof)
    return packet,receipt,proof


def test_registered_future_capture_immediately_queries_exact_single_sample(recorded):
    packet,receipt,proof=recorded
    q=runs.ObservedRunQueries();sid=receipt['source_id'];sha=receipt['sha256']
    catalog=next(s for s in runs.catalog_runs()['sources']if s['source_id']==sid)
    assert catalog['counts'][SNAPSHOTS_TABLE]==2
    assert CHANGES_TABLE not in catalog['available_tables']
    assert 'one verified observation' in catalog['optional_derivations'][CHANGES_TABLE]['reason']
    page=q.query(sid,sha,SNAPSHOTS_TABLE,limit=1)
    second=q.query(sid,sha,SNAPSHOTS_TABLE,limit=1,cursor=page['next_cursor'])
    assert second['next_cursor']is None
    for row,side in zip(page['rows']+second['rows'],packet['tactical_observation']['samples'][0]['sides']):
        assert row['raw_selection_flags_hex']==side['raw_selection_flags_hex']
        assert json.loads(row['unclassified_selected_bits_json'])==[84]
        assert json.loads(row['selected_instructions_json'])==side['options']
        assert row['mentality_name'] is None and row['mentality_native_code']==9
        assert row['period'] is None and row['native_cursor'] is None and row['score_home'] is None
        assert (row['native_cursor_window_start'],row['native_cursor_window_end'],row['fixed_event_cursor'])==(100,102,100)
        assert row['source_incarnation_id']==packet['incarnation_id']
    assert q.query(sid,sha,SNAPSHOTS_TABLE,side_index=1)['row_count']==1
    assert q.query(sid,sha,SNAPSHOTS_TABLE,period='FirstHalf')['row_count']==0
    with pytest.raises(ValueError,match='not captured'):q.query(sid,sha,CHANGES_TABLE)
    assert hashlib.sha256(open(receipt['path'],'rb').read()).hexdigest()==sha


@pytest.mark.parametrize('change',['no_proof','document_hash','policy','career','fixture','match_uid','window','flags',
    'label','summary','timestamp','scope','incarnation','selection','phase_private'])
def test_rehashed_bad_optional_source_never_supplies_tactics_or_breaks_base(recorded,monkeypatch,change):
    packet,receipt,proof=recorded;proof=copy.deepcopy(proof)
    path=receipt['path'];db=sqlite3.connect(path)
    document=json.loads(db.execute("SELECT document_json FROM source_documents WHERE source_id='tactical_samples'").fetchone()[0])
    sample=document['samples'][0]
    if change=='policy':document['policy']['native_guard_digest']='a'*64;proof['policy']=document['policy']
    elif change=='career':document['career']['name']='Different career'
    elif change=='fixture':document['fixture']['away_team_id']=99
    elif change=='match_uid':sample['official_match_unique_id']=999
    elif change=='window':sample['native_cursor_window']['start']=99
    elif change=='flags':sample['sides'][0]['unclassified_selected_bits']=[]
    elif change=='label':sample['sides'][0]['options'][0]['name']='Invented label'
    elif change=='timestamp':sample['observed_at_unix']=False
    elif change=='scope':sample['same_tick_as_events_verified']=True
    elif change=='incarnation':proof['source_incarnation_id']='b'*64
    elif change=='selection':proof['selection_id']='b'*64
    elif change=='phase_private':sample['sides'][0]['phases']={'in_possession':[{'pointer':1234}]}
    sample['summary_sha256']=producer.hashlib.sha256(producer._json({k:v for k,v in sample.items()if k not in ('observed_at_unix','summary_sha256')}).encode()).hexdigest()
    if change=='summary':sample['summary_sha256']='0'*64
    raw=producer._json(document);digest=hashlib.sha256(raw.encode()).hexdigest()
    db.execute("UPDATE source_documents SET sha256=?,document_json=? WHERE source_id='tactical_samples'",(digest,raw));db.commit();db.close()
    proof['source_document_sha256']=digest if change!='document_hash' else '0'*64
    newsha=hashlib.sha256(open(path,'rb').read()).hexdigest()
    entry={**receipt,'sha256':newsha,'producer_attestation':proof}
    from pathlib import Path
    entry['path']=Path(path)
    if change=='no_proof':entry.pop('producer_attestation')
    monkeypatch.setattr(registry,'load_registrations',lambda:{receipt['source_id']:entry})
    catalog=next(s for s in runs.catalog_runs()['sources']if s['source_id']==receipt['source_id'])
    assert SNAPSHOTS_TABLE not in catalog['available_tables']
    assert runs.ObservedRunQueries().query(receipt['source_id'],newsha,'completed_pass_events')['row_count']==1


POSITION={'slot':0,'position':'D(R)','position_mask':4,'base_role':'Full-Back'}


def _store_phases(recorded,monkeypatch,phases):
    """Give the stored tactical document these phases and attest it again, as its recorder would have."""
    from pathlib import Path
    packet,receipt,proof=recorded;proof=copy.deepcopy(proof)
    path=receipt['path'];db=sqlite3.connect(path)
    document=json.loads(db.execute("SELECT document_json FROM source_documents WHERE source_id='tactical_samples'").fetchone()[0])
    sample=document['samples'][0]
    for side in sample['sides']:side['phases']=copy.deepcopy(phases)
    sample['summary_sha256']=hashlib.sha256(producer._json({k:v for k,v in sample.items()if k not in ('observed_at_unix','summary_sha256')}).encode()).hexdigest()
    raw=producer._json(document);digest=hashlib.sha256(raw.encode()).hexdigest()
    db.execute("UPDATE source_documents SET sha256=?,document_json=? WHERE source_id='tactical_samples'",(digest,raw));db.commit();db.close()
    proof['source_document_sha256']=digest
    newsha=hashlib.sha256(open(path,'rb').read()).hexdigest()
    entry={**receipt,'sha256':newsha,'producer_attestation':proof,'path':Path(path)}
    monkeypatch.setattr(registry,'load_registrations',lambda:{receipt['source_id']:entry})
    return receipt['source_id'],newsha,raw


@pytest.mark.parametrize('shape',['written_before_15_november_2026','written_now'])
def test_both_recorded_position_shapes_read_and_neither_returns_the_legacy_key(recorded,monkeypatch,shape):
    """Earlier recorders named the role word's internal flag in each position, as `duty`. A role
    in Football Manager 27 has no duty: the stored document stays as written and reads, and the
    returned phases carry the position and the role only."""
    from test_no_role_duty import duty_mentions
    old=shape=='written_before_15_november_2026'
    stored={**POSITION,'duty':'Defend'} if old else dict(POSITION)
    sid,sha,raw=_store_phases(recorded,monkeypatch,{'in_possession':[stored],'out_of_possession':[stored]})
    assert ('"duty":"Defend"' in raw) is old
    catalog=next(s for s in runs.catalog_runs()['sources']if s['source_id']==sid)
    assert catalog['counts'][SNAPSHOTS_TABLE]==2
    page=runs.ObservedRunQueries().query(sid,sha,SNAPSHOTS_TABLE)
    assert page['row_count']==2
    for row in page['rows']:
        assert json.loads(row['phases_json'])=={'in_possession':[POSITION],'out_of_possession':[POSITION]}
    assert duty_mentions(page)==[] and duty_mentions(catalog)==[]


@pytest.mark.parametrize('position',[{**POSITION,'duty':'Defend','pointer':1},{'slot':0,'duty':'Defend'},['duty']])
def test_the_legacy_key_admits_no_other_position_shape(recorded,monkeypatch,position):
    sid,sha,_raw=_store_phases(recorded,monkeypatch,{'in_possession':[position]})
    catalog=next(s for s in runs.catalog_runs()['sources']if s['source_id']==sid)
    assert SNAPSHOTS_TABLE not in catalog['available_tables']
