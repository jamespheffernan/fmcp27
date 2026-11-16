import struct
import pytest
from fm_live_mcp import bridge as module, fixture_player_checks as projection, world
from test_bridge import bridge


@pytest.fixture
def combined(bridge,monkeypatch):
    base=0x100000000;cells={};calls=[]
    def put(at,raw):cells.update((at+i,b)for i,b in enumerate(raw))
    def read(at,n):return bytes(cells.get(at+i,0)for i in range(n))
    put(0x60000,struct.pack('<QQ',0x70000,0x80000))
    put(base+0x56d2d08,struct.pack('<Q',0x90000))
    monkeypatch.setattr(module.database,'table',lambda *a:{'start':0x60000,'count':2})
    monkeypatch.setattr(module.assessment_people,'verify_native',lambda *a:None)
    def person(r,b,people,address):
        index=0 if address==0x70000 else 1
        return address+0x1000,0,{'record_kind':'actual','native_identity':{'database_index':index}},100+index,100+index
    monkeypatch.setattr(module.assessment_people,'_person',person)
    activation={'state':'decoded_named_round_option','enabled':False,'native_round_flags_u8':0}
    monkeypatch.setattr(module.fixture_signed_after_round,'read_activation',lambda *a:dict(activation))
    monkeypatch.setattr(module.fixture_suspension,'verify_native',lambda *a:None)
    suspension={'state':'ruled_out','reason':'no_stored_personal_bans','applies':False}
    def check(r,b,primary,kind,**kwargs):
        calls.append((primary,kind,kwargs));return dict(suspension)
    monkeypatch.setattr(module.fixture_suspension,'check',check)
    history={'state':'absent','native_other_team_cup_history_condition':False,
             'native_condition_reason':'native_flag1_person_row_team_comparison'}
    picked=[{'person':{'database_index':0,'native_id':100,'secondary_id':100,'record_kind':'actual'},'cup_history':history}]
    proposed=[{'native_identity':{'database_index':1,'native_id':101},'record_kind':'actual',
               'candidate_context':{'state':'compatible'},'cup_history':history}]
    return locals()


def compose(c):
    module.Bridge._compose_fixture_player_checks(c['bridge'],c['read'],c['base'],0xa000,
        {'competition_address':0xb000},None,c['picked'],c['proposed'],{}, {})


def test_three_scopes_combined_without_clearance_or_selection_change(combined):
    c=combined;compose(c)
    for row in c['picked']+c['proposed']:
        assert row['overall_clearance']=='unknown'
        assert all(check['state']=='ruled_out'for check in row['checks'].values())
    assert c['picked'][0]['selection_kind']=='currently_picked'
    assert c['proposed'][0]['selection_kind']=='proposed_check'
    assert c['proposed'][0]['is_currently_picked']is False
    assert c['calls'][0][2]=={'fixture_address':0xa000,'manager_address':0x90000}


def test_independent_missing_cup_or_nonempty_suspension_does_not_erase_other_checks(combined):
    c=combined;c['picked'][0]['cup_history']=None
    c['suspension'].update(state='unavailable',reason='nonempty_personal_bans_not_evaluated',applies=None)
    compose(c);checks=c['picked'][0]['checks']
    assert checks['other_team_cup_history']['state']=='unavailable'
    assert checks['ordinary_suspension']['state']=='unavailable'
    assert checks['signed_after_round']['state']=='ruled_out'


def test_enabled_signing_rule_never_becomes_restriction_or_clearance(combined):
    c=combined;c['activation']['enabled']=True;compose(c)
    check=c['picked'][0]['checks']['signed_after_round']
    assert check['state']=='unavailable'and check['applies']is None
    assert check['reason']=='enabled_player_and_date_checks_not_evaluated'
    assert c['picked'][0]['checks']['ordinary_suspension']['state']=='ruled_out'


def test_proposal_incompatible_has_no_player_restriction_evaluation(combined):
    c=combined;c['proposed'][0]['candidate_context']['state']='incompatible'
    c['proposed'][0]['cup_history']=None;compose(c)
    assert len(c['calls'])==1
    assert all(x['state']=='unavailable'for x in c['proposed'][0]['checks'].values())


def test_current_subject_identity_mismatch_rejects_composed_checks(combined):
    c=combined;c['picked'][0]['person']['native_id']=999
    with pytest.raises(ValueError,match='identity changed'):compose(c)


def test_false_inner_condition_is_not_historical_absence():
    result=projection.other_team_history({'native_other_team_cup_history_condition':False,
        'native_condition_reason':'native_flag1_person_row_team_comparison'})
    assert result['state']=='ruled_out'and result['historical_other_team_appearance']is None
    assert result['historical_absence_proved']is False
