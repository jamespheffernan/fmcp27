import pytest
from fm_live_mcp.match_scope_query import ScopedMatchQueries, column_catalog


def test_catalog_needs_no_game():
    catalog=column_catalog()
    assert 'shots_on_target' in catalog['team_totals']['columns']
    assert 'person_name' in catalog['retained_players']['columns']
    assert 'raw_json' not in catalog['fixtures']['default_fields']


def capture(b,s,team,start,end,comp,youth,players,**kwargs):
    b.append(players)
    return dict(capture={'save':{'current_date':'2030-10-29'},'fixtures':[{'fixture':{'fixture_ref':'f1','date':'2030-10-20'},'native_match_key':7}]},team_totals={'records':[{'result_key':7,'teams':[{'side_index':0,'shots':12,'shots_on_target':4}]}]})


def test_multi_projection_captures_once_and_pages_same_observation():
    calls=[]
    q=ScopedMatchQueries(capture,epoch=lambda b,s:1)
    a=q.query(calls,'s',688,'2030-07-01','2030-10-29',limit=1)
    assert calls==[False]
    b=q.query(calls,'s',688,'2030-07-01','2030-10-29',limit=1,cursor=a['next_cursor'])
    assert calls==[False]
    assert a['capture_id']==b['capture_id']
    assert a['observed_at']==b['observed_at']
    assert a['rows'][0]['table']=='fixtures'
    assert b['rows'][0]['row']['shots']==12
    assert a['counts']=={'fixtures':1,'team_totals':1}


def test_player_request_selects_full_source_and_bad_fields_fail_before_capture():
    calls=[];q=ScopedMatchQueries(capture,epoch=lambda b,s:1)
    q.query(calls,'s',688,'2030-07-01','2030-10-29',tables=['retained_players'])
    assert calls==[True]
    with pytest.raises(ValueError,match='Unsupported fields'):
        q.query(calls,'s',688,'2030-07-01','2030-10-29',fields={'team_totals':['DROP TABLE']})
    assert calls==[True]


def test_epoch_change_expires_scoped_pages():
    state=[1];q=ScopedMatchQueries(capture,epoch=lambda b,s:state[0]);calls=[]
    a=q.query(calls,'s',688,'2030-07-01','2030-10-29',limit=1)
    state[0]=2
    with pytest.raises(ValueError,match='epoch changed'):
        q.query(calls,'s',688,'2030-07-01','2030-10-29',limit=1,cursor=a['next_cursor'])


def test_starter_limitation_reaches_column_discovery_and_scoped_response():
    catalog=column_catalog()['retained_players']
    assert catalog['historical_lineup_policy']['may_report_as_formal_starts'] is False
    assert catalog['field_provenance']['appearance_kind']['formal_started'] is None
    result=ScopedMatchQueries(capture,epoch=lambda b,s:1).query([], 's',688,'2030-09-01','2030-10-31')
    assert result['historical_lineup_policy']['formal_starting_lineup_state']=='not_decoded'
    assert result['historical_lineup_policy']['match_completion_state']=='not_decoded'


def test_running_column_units_and_scope_are_discoverable_without_memory_capture(monkeypatch):
    from fm_live_mcp import match_scope_query as module
    from fm_live_mcp.saved_match_player_running import running_field_registry
    def unexpected_capture(*args, **kwargs):
        pytest.fail('Column discovery must not capture career memory')
    monkeypatch.setattr(module, 'capture_live', unexpected_capture)
    monkeypatch.setattr(module, 'scoped_capture', unexpected_capture)
    catalog = module.column_catalog()['retained_players']
    assert 'distance_metres' in catalog['columns']
    provenance = catalog['field_provenance']['distance_metres']
    assert provenance == running_field_registry()['distance_metres']
    assert provenance['unit'] == 'metres'
    assert provenance['official_property_label'] == 'DistanceRan'
    assert 'one retained fixture/player row' in provenance['scope']
    assert 'Zero is stored zero' in provenance['scope']
    assert 'Missing source or player row is unavailable, never zero' in provenance['missing_policy']


def test_scoped_running_fields_retain_unit_metadata_and_null_minutes():
    from fm_live_mcp.saved_match_player_running import running_field_registry
    registry = running_field_registry()
    def source(*args, **kwargs):
        return {
            'capture': {'save': {}, 'action_field_provenance': registry,
                        'fixtures': [{'native_match_key': 7, 'fixture': {'date': '2030-11-06'}}]},
            'retained_players': [
                {'fixture_key': 7, 'stored_player_slot': 0, 'side_index': 1,
                 'distance_metres': 13174.189453125, 'minutes': 90},
                {'fixture_key': 7, 'stored_player_slot': 1, 'side_index': 1,
                 'distance_metres': 0.0, 'minutes': None, 'appearance_kind': 'unused_substitute'},
                {'fixture_key': 7, 'stored_player_slot': 2, 'side_index': 1,
                 'minutes': 30},
            ],
        }
    page = ScopedMatchQueries(source, epoch=lambda *args: 1).query(
        None, 's', 688, '2030-11-06', '2030-11-06', tables=['retained_players'],
        fields={'retained_players': ['distance_metres', 'minutes', 'appearance_kind']},
    )
    assert [r['row'] for r in page['rows']] == [
        {'distance_metres': 13174.189453125, 'minutes': 90, 'appearance_kind': None},
        {'distance_metres': 0.0, 'minutes': None, 'appearance_kind': 'unused_substitute'},
        {'distance_metres': None, 'minutes': 30, 'appearance_kind': None},
    ]
    assert page['metadata']['action_field_provenance']['distance_metres'] == registry['distance_metres']
    assert page['metadata']['action_field_provenance']['distance_metres']['unit'] == 'metres'
