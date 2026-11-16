from copy import deepcopy
import struct
import pytest
from fm_live_mcp import bench_cover_source as source, players, world


def assignment(index=0,person=None,mask=4,name='D(R)',pairing='paired_by_native_slot'):
    return {'slot_index':index,'person':person,'pairing_state':pairing,
            'position':{'native_mask':mask,'name':name,'state':'named'},
            'stored_base_role':{'name':'Striker'}}


def test_named_general_join_follows_position_not_role_and_keeps_central_side_unknown():
    row=source.phase_position(assignment())
    assert row['general_position_field']=='defender_right'
    assert row['position']=='D(R)' and row['role_aptitude']=='not_evaluated'
    row=source.phase_position(assignment(mask=0x100010,name='D(CL)'))
    assert row['general_position_field']=='defender_central'
    assert row['side_specific_familiarity']=='not_established'


@pytest.mark.parametrize('row', [None,assignment(mask=123),assignment(name='GK'),
    assignment(pairing='ambiguous_duplicate_person'),assignment(pairing='unsupported_phase_index')])
def test_unknown_or_ambiguous_position_never_borrows_general_field(row):
    assert source.phase_position(row)['general_position_field'] is None


@pytest.fixture
def context(monkeypatch):
    base=0x100000000
    person=lambda i:{'database_index':i,'native_id':100+i,'secondary_id':100+i,
                     'record_kind':'actual','display_name':str(i)}
    slots=[{'slot_index':i,'category':'starting_position'if i<11 else'bench'if i<20 else'unused',
            'bench_ordinal':i-10 if 11<=i<20 else None,
            'person':person(i)if i<20 else None}for i in range(26)]
    sheet={'team':{'native_id':688},'source_state':'available','unavailable_reason':None,
           'role_boundary_state':'native_first_11_and_stored_selected_end','slot_count':26,'slots':slots}
    tactical={'team':sheet['team'],'source_state':'available','phases':{
        phase:{'assignments':[assignment(i,person(i))for i in range(11)]}
        for phase in ('in_possession','out_of_possession')}}
    class Read:
        verified=0
        def __call__(self,at,size):
            assert size==4
            return struct.pack('<HH',1,1900)if at==base+source.player_injury_status.SENTINEL_DATE else struct.pack('<HH',306,2030)
        def verify(self):self.verified+=1
    read=Read();calls=[]
    monkeypatch.setattr(source.live_team_sheet_source,'inspect',lambda *a:deepcopy(sheet))
    monkeypatch.setattr(source.live_tactical_assignments_source,'inspect',lambda *a:deepcopy(tactical))
    monkeypatch.setattr(source.assessment_people,'verify_native',lambda *a:None)
    monkeypatch.setattr(source.player_injury_status,'verify_native',lambda *a:None)
    monkeypatch.setattr(source.database,'table',lambda *a:{})
    def candidate(r,b,t,p,slot,*args):
        i=slot['person']['database_index'];calls.append(i)
        return {'person_index':i,'native_id':100+i,'display_name':str(i),'positions':{'defender_right':20},
                'health':{'condition_percent':0},'injury_status':{'state':'checked','flagged':False}}
    monkeypatch.setattr(source,'_candidate',candidate)
    return {'base':base,'tables':tuple(base+x for x in players.RVA),'read':read,
            'sheet':sheet,'tactical':tactical,'calls':calls}


def capture(c,**kwargs):return source.capture(c['read'],c['base'],{},c['tables'],**kwargs)


def test_actual_order_phase_join_and_zero_condition_preserved(context):
    c=context;r=capture(c,expected_current_date='2030-11-02')
    assert len(r['targets'])==11 and len(r['bench'])==9
    assert r['bench'][0]['slot_index']==11 and r['bench'][0]['bench_ordinal']==1
    assert r['bench'][0]['health']['condition_percent']==0
    assert r['targets'][0]['phases']['out_of_possession']['general_position_field']=='defender_right'
    assert r['coverage']['complete_both_phase_position_joins'] is True
    assert c['read'].verified==1 and len(c['calls'])==20


def test_duplicate_person_slots_preserved_without_double_profile_read(context):
    c=context;c['sheet']['slots'][11]['person']=deepcopy(c['sheet']['slots'][0]['person'])
    r=capture(c)
    assert r['targets'][0]['person_index']==r['bench'][0]['person_index']==0
    assert r['coverage']['duplicate_person_indices']==[0]
    assert c['calls'].count(0)==1 and len(c['calls'])==19


def test_checked_empty_bench_is_not_unavailable(context):
    c=context
    for slot in c['sheet']['slots'][11:20]:slot['person']=None
    r=capture(c)
    assert r['bench']==[] and r['coverage']['empty_bench_slot_indices']==list(range(11,20))
    c['sheet']['source_state']='unavailable';c['sheet']['unavailable_reason']='no_session'
    r=capture(c)
    assert r['bench'] is None and r['targets'] is None and r['source_state']=='unavailable'


def test_empty_starting_slot_and_missing_oop_phase_are_not_complete(context):
    c=context;c['sheet']['slots'][0]['person']=None
    c['tactical']['phases']['out_of_possession']['assignments']=None
    c['tactical']['source_state']='partial'
    r=capture(c)
    assert r['source_state']=='partial'
    assert r['coverage']['empty_starting_slot_indices']==[0]
    assert r['coverage']['complete_both_phase_position_joins'] is False
    assert r['targets'][0]['phases']['out_of_possession']['position'] is None


def test_phase_person_team_and_date_drift_rejected(context):
    c=context
    with pytest.raises(ValueError,match='current date'):capture(c,expected_current_date='2030-11-03')
    c['tactical']['phases']['out_of_possession']['assignments'][0]['person']['native_id']=999
    with pytest.raises(ValueError,match='phase PERSON'):capture(c)
    c['tactical']['team']={'native_id':999}
    with pytest.raises(ValueError,match='TEAM disagree'):capture(c)


def test_readset_rejection_propagates_no_partial_capture(context):
    def reject():raise ValueError('source changed during read')
    context['read'].verify=reject
    with pytest.raises(ValueError,match='changed during read'):capture(context)


def test_bench_from_next_fixture_rule_is_accepted_and_unmapped_end_is_refused(context):
    c=context;c['sheet']['role_boundary_state']=source.live_team_sheet_source.NEXT_FIXTURE_END
    r=capture(c)
    assert r['source_state']=='available' and len(r['targets'])==11 and len(r['bench'])==9
    assert r['coverage']['bench_count']==9
    c['sheet']['role_boundary_state']='stored_boundary_unmapped'
    r=capture(c)
    assert r['source_state']=='unavailable' and r['unavailable_reason']=='selection_boundary_unresolved'
    assert r['targets'] is None and r['bench'] is None
