import copy
import hashlib
import json
import sqlite3
import pytest
from fm_live_mcp import observed_tactical_settings as module
from fm_live_mcp import observed_match_runs as runs
from test_observed_match_runs import source


def sample():
    def sides(option):
        return [{'team_id':team,'mentality':{'native_code':5,'name':'Positive','state':'named'},
                 'options':[{'native_option_id':option,'name':'Option '+str(option),'state':'named'}],
                 'phases':{'in_possession':[],'out_of_possession':[]}}for team in(11,13)]
    document={'state':'observed_settings_difference_between_two_samples',
        'before':{'path':'/private/not/exposed/before.json','sha256':'a'*64,'cursor':11655,'period':'HalfTime','score':{'home':2,'away':0},'sides':sides(1)},
        'after':{'path':'/private/not/exposed/after.json','sha256':'b'*64,'cursor':16319,'period':'SecondHalf','score':{'home':3,'away':0},'sides':sides(2)},
        'differences':[{'untrusted_summary':'never consumed'}]}
    proof={'official_match_unique_id':123,'career':{'name':'Career','created_date':'2025-01-01','created_version':1}}
    for name in('before','after'):
        value=document[name]
        proof[name]={'summary_sha256':module._digest({k:value[k]for k in('sha256','cursor','period','score','sides')}),
                     'observed_at_unix':1700000000+(0 if name=='before' else 300)}
    return document,proof,{'home_team_native_id':11,'away_team_native_id':13}


def test_sparse_native_observations_project_without_exact_change_or_causation_claim():
    d,p,f=sample();snapshots,changes=module.project_settings(d,f,p)
    assert len(snapshots)==4 and len(changes)==2
    assert changes[0]['before_cursor']==11655 and changes[0]['after_cursor']==16319
    assert changes[0]['before_period']=='HalfTime' and changes[0]['after_period']=='SecondHalf'
    assert json.loads(changes[0]['removed_instructions_json'])[0]['native_option_id']==1
    assert json.loads(changes[0]['added_instructions_json'])[0]['native_option_id']==2
    assert changes[0]['phase_positions_or_roles_changed'] is False
    assert '/private/'not in json.dumps([snapshots,changes])
    assert 'exact change time' in module.SCOPE.lower()


def test_changed_snapshot_rejected_and_stored_diff_not_trusted():
    d,p,f=sample();d['after']['sides'][0]['options'][0]['name']='Changed'
    with pytest.raises(ValueError,match='attested native sample'):module.project_settings(d,f,p)
    d,p,f=sample();d['after']['cursor']=100
    with pytest.raises(ValueError,match='not ordered'):module.project_settings(d,f,p)
    d,p,f=sample();f['home_team_native_id']=99
    with pytest.raises(ValueError,match='team ordering'):module.project_settings(d,f,p)


def test_catalog_query_filters_pins_pages_and_bad_optional_source_leaves_base_usable(source,monkeypatch):
    path,_=source;d,p,_=sample()
    for side,team in enumerate((688,692)):
        for label in('before','after'):d[label]['sides'][side]['team_id']=team
    for name in('before','after'):
        value=d[name];p[name]['summary_sha256']=module._digest({k:value[k]for k in('sha256','cursor','period','score','sides')})
    raw=json.dumps(d);p['document_sha256']='c'*64;p['stored_document_sha256']=hashlib.sha256(raw.encode()).hexdigest()
    db=sqlite3.connect(path);terminal=json.loads(db.execute("SELECT document_json FROM source_documents WHERE source_id='terminal'").fetchone()[0]);terminal['raw_source']={'match_unique_id':123};db.execute("UPDATE source_documents SET document_json=? WHERE source_id='terminal'",(json.dumps(terminal),));db.execute('INSERT INTO source_documents VALUES(?,?,?)',('tactical_observations','c'*64,raw));db.commit();db.close()
    capture=hashlib.sha256(path.read_bytes()).hexdigest();runs.SOURCES['test_run']['sha256']=capture;monkeypatch.setattr(module,'ATTESTED_CAPTURES',{capture:p})
    catalog=next(r for r in runs.catalog_runs()['sources']if r['source_id']=='test_run')
    assert catalog['counts'][module.SNAPSHOTS_TABLE]==4 and catalog['counts'][module.CHANGES_TABLE]==2
    q=runs.ObservedRunQueries();page=q.query('test_run',capture,module.SNAPSHOTS_TABLE,side_index=0,limit=1)
    assert page['rows'][0]['snapshot_label']=='before' and page['next_cursor']
    second=q.query('test_run',capture,module.SNAPSHOTS_TABLE,side_index=0,limit=1,cursor=page['next_cursor'])
    assert second['rows'][0]['snapshot_label']=='after'
    assert q.query('test_run',capture,module.SNAPSHOTS_TABLE,period='SecondHalf')['row_count']==2
    assert '/private/not/exposed/' not in json.dumps(page)
    p['stored_document_sha256']='f'*64
    catalog=next(r for r in runs.catalog_runs()['sources']if r['source_id']=='test_run')
    assert module.SNAPSHOTS_TABLE not in catalog['available_tables']
    assert q.query('test_run',capture,'shots')['row_count']==5
    with pytest.raises(ValueError,match='not captured'):q.query('test_run',capture,module.SNAPSHOTS_TABLE)


def test_unknown_capture_does_not_invent_recorded_before_state():
    assert module.derive_tactical_settings(None,{'capture_id':'d'*64},table=module.SNAPSHOTS_TABLE)is None


def test_old_shape_positions_are_read_and_the_legacy_key_is_neither_returned_nor_compared():
    """Recordings written before 15 November 2026 name the role word's internal flag in each
    position. A role in Football Manager 27 has no duty, so the key is dropped on read."""
    from test_no_role_duty import duty_mentions
    position={'slot':0,'position':'D(R)','position_mask':4,'base_role':'Full-Back'}
    def attest(d,p):
        for name in('before','after'):
            p[name]['summary_sha256']=module._digest({k:d[name][k]for k in('sha256','cursor','period','score','sides')})
    d,p,f=sample()
    for name,flag in(('before','Defend'),('after','Support')):
        for side in d[name]['sides']:
            side['phases']={'in_possession':[{**position,'duty':flag}],'out_of_possession':[]}
    attest(d,p)
    snapshots,changes=module.project_settings(d,f,p)
    assert len(snapshots)==4
    assert all(json.loads(row['phases_json'])=={'in_possession':[position],'out_of_possession':[]} for row in snapshots)
    assert [row['phase_positions_or_roles_changed'] for row in changes]==[False,False]
    assert duty_mentions([snapshots,changes])==[]
    assert d['before']['sides'][0]['phases']['in_possession'][0]['duty']=='Defend'   # the stored document is untouched
    d['after']['sides'][0]['phases']['in_possession'][0]['base_role']='Wing-Back'
    attest(d,p)
    assert [row['phase_positions_or_roles_changed'] for row in module.project_settings(d,f,p)[1]]==[True,False]
