import pytest
from fm_live_mcp.pass_field_zones import aggregate_pass_zones


def row(i,done,third='middle',channel='central',side=0):
    return {'event_id':i,'side_index':side,'completed':done,'field_position':{
        'inside_native_pitch_extents':True,'analytical_pitch_third':third,'analytical_lateral_channel':channel}}


def cover(n,m=0):return [{'side_index':0,'state':'available','attempt_count':n},{'side_index':1,'state':'available','attempt_count':m}]


def test_rates_use_attempts_not_failures_and_all_cells_reconcile():
    rows=[row(1,False),row(2,True),row(3,True),row(4,False,'attacking','outer')]
    r=aggregate_pass_zones(rows,cover(4))['sides'][0]
    assert (r['attempted'],r['completed'],r['not_completed'])==(4,2,2)
    middle=r['thirds'][1];assert middle['attempted']==3 and middle['not_completed']==1
    assert middle['not_completed_rate']==1/3
    assert sum(z['attempted'] for z in r['zones'])==4
    assert r['zones'][0]['completion_rate'] is None


def test_unknown_location_preserves_totals_without_fabricated_zones():
    a=row(1,False);a['field_position']=None
    b=row(2,True);b['field_position']['inside_native_pitch_extents']=False
    r=aggregate_pass_zones([a,b],cover(2))['sides'][0]
    assert r['attempted']==2 and r['classified_location_count']==0
    assert r['unclassified_location']['not_completed']==1
    assert r['outside_pitch_extents_count']==1 and r['unavailable_location_count']==1


def test_unavailable_side_has_null_counts_and_zero_available_side_stays_zero():
    c=cover(0);c[1]={'side_index':1,'state':'unavailable_actor_identity'}
    a,b=aggregate_pass_zones([],c)['sides']
    assert a['attempted']==0 and a['not_completed_rate'] is None
    assert b['attempted'] is None and b['zones'] is None


def test_partial_page_duplicate_event_and_unavailable_row_rejected():
    with pytest.raises(ValueError,match='Full pass rows'):aggregate_pass_zones([row(1,True)],cover(2))
    with pytest.raises(ValueError,match='duplicated'):aggregate_pass_zones([row(1,True),row(1,False)],cover(2))
    c=cover(1);c[0]['state']='unavailable_attempt_counter_reconciliation'
    with pytest.raises(ValueError,match='unavailable pass side'):aggregate_pass_zones([row(1,False)],c)
