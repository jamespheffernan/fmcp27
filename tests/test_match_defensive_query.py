from fm_live_mcp.match_scope_query import ScopedMatchQueries, column_catalog
from fm_live_mcp.match_dataset import build_connection

FIELDS=['aerial_duels_attempted','aerial_duels_completed','interceptions','clearances']

def test_defensive_schema_view_zero_and_unknown_preserved():
    capture={'fixtures':[{'native_match_key':1,'fixture':{'date':'2030-10-01'}}]}
    rows=[dict(fixture_key=1,person_index_word=4,side_index=0,stored_player_slot=0,aerial_duels_attempted=9,aerial_duels_completed=6,interceptions=0,clearances=3),dict(fixture_key=1,person_index_word=5,side_index=0,stored_player_slot=1)]
    db=build_connection(capture,retained_players=rows)
    assert db.execute('SELECT '+','.join(FIELDS)+' FROM retained_players ORDER BY person_index_word').fetchall()==[(9,6,0,3),(None,None,None,None)]
    assert db.execute('SELECT '+','.join(FIELDS)+',action_source_state FROM player_match_analysis ORDER BY person_index_word').fetchall()==[(9,6,0,3,'captured'),(None,None,None,None,'not_captured')]
    assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
    db.close()

def test_scoped_defensive_fields_selected_without_raw_rows():
    def capture(*args,**kwargs):
        return {'capture':{'fixtures':[{'native_match_key':1,'fixture':{'date':'2030-10-01'}}]},'retained_players':[dict(fixture_key=1,side_index=0,person_index_word=4,aerial_duels_attempted=9,aerial_duels_completed=6,interceptions=0,clearances=3)]}
    result=ScopedMatchQueries(capture,epoch=lambda b,s:1).query(None,'s',688,'2030-10-01','2030-10-01',tables=['retained_players'],fields={'retained_players':FIELDS})
    assert result['rows'][0]['row']==dict(zip(FIELDS,[9,6,0,3]))
    catalog=column_catalog()['retained_players']
    assert all(name in catalog['columns'] for name in FIELDS)
    assert catalog['field_provenance']['aerial_duels_completed']['frontend_literal']=='AerialDuelsCompleted'


def test_cross_counts_are_typed_and_selectable_with_unknowns():
    names=['crosses_attempted','crosses_completed','open_play_crosses_attempted','open_play_crosses_completed']
    capture={'fixtures':[{'native_match_key':1,'fixture':{'date':'2030-10-01'}}]}
    rows=[dict(fixture_key=1,person_index_word=4,**dict(zip(names,[9,4,8,3]))),dict(fixture_key=1,person_index_word=5)]
    db=build_connection(capture,retained_players=rows)
    assert db.execute('SELECT '+','.join(names)+' FROM retained_players ORDER BY person_index_word').fetchall()==[(9,4,8,3),(None,None,None,None)]
    assert db.execute('SELECT '+','.join(names)+' FROM player_match_analysis ORDER BY person_index_word').fetchall()==[(9,4,8,3),(None,None,None,None)]
    db.close()
    assert all(name in column_catalog()['retained_players']['columns'] for name in names)


def test_team_crossing_provenance_exposes_native_reconstruction_limit():
    provenance=column_catalog()['team_totals']['field_provenance']
    assert provenance['crosses_attempted']['official_property']=='CrossAttempts'
    assert provenance['independent_serialized_team_oracle'] is False
