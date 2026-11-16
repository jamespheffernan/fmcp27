from fm_live_mcp.match_dataset import build_connection
from fm_live_mcp.match_scope_query import ScopedMatchQueries, column_catalog

FIELDS=['saves_held','saves_parried','saves_tipped','total_saves']

def test_named_keeper_fields_preserve_unused_zero_and_missing():
    fixtures=[{'native_match_key':1,'fixture':{'date':'2030-10-01'}}]
    rows=[dict(fixture_key=1,person_index_word=1,minutes=90,saves_held=2,saves_parried=4,saves_tipped=0,total_saves=6),dict(fixture_key=1,person_index_word=2,minutes=None,appearance_kind='unused_substitute',**dict.fromkeys(FIELDS,0)),dict(fixture_key=1,person_index_word=3)]
    db=build_connection({'fixtures':fixtures},retained_players=rows)
    assert db.execute('SELECT minutes,'+','.join(FIELDS)+',action_source_state FROM player_match_analysis ORDER BY person_index_word').fetchall()==[(90,2,4,0,6,'captured'),(None,0,0,0,0,'captured'),(None,None,None,None,None,'not_captured')]
    db.close()

def test_keeper_fields_scoped_projection_catalog_and_no_raw_dependency():
    def capture(*args,**kwargs):
        return {'capture':{'fixtures':[{'native_match_key':1,'fixture':{'date':'2030-10-01'}}]},'retained_players':[dict(fixture_key=1,person_index_word=1,**dict(zip(FIELDS,[1,0,2,3])))]}
    result=ScopedMatchQueries(capture,epoch=lambda b,s:1).query(None,'s',688,'2030-10-01','2030-10-01',tables=['retained_players'],fields={'retained_players':FIELDS})
    assert result['rows'][0]['row']==dict(zip(FIELDS,[1,0,2,3]))
    catalog=column_catalog()['retained_players']
    assert all(name in catalog['columns'] for name in FIELDS)
    assert 'No post-shot expected goals' in catalog['field_provenance']['total_saves']['limits']
