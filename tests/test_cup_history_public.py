from copy import deepcopy
import pytest
from fm_live_mcp import bridge as module
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_managed_team_sheet_bridge import sheet


@pytest.fixture
def bound(bridge,sheet,monkeypatch):
    tables=tuple(0x100000+r for r in module.players.RVA)
    saved=dict(tables=tables,catalog_identity=('catalog',),year=2030,day=300,group=0,
               route=('route',),slot=0,address=0x7000,identity=('fixture',))
    bridge.fixture_refs['fixture']=saved
    decoded={'identity':('fixture',),'teams':(0x8000,0x9000),'competition':{'database_index':7,'native_id':11},'competition_address':0xa000}
    monkeypatch.setattr(module.fixtures,'catalog',lambda *a:(None,{2030:{}},('catalog',)))
    monkeypatch.setattr(module.fixtures,'bucket',lambda *a:([0x7000],('route',)))
    monkeypatch.setattr(module.fixtures,'record',lambda *a:decoded)
    monkeypatch.setattr(module.fixtures,'detail',lambda *a:({'date':'2030-10-29'},[],{}))
    sheet['source'].update(role_boundary_state='native_first_11_and_stored_selected_end',duplicate_person_indices=[])
    sheet['source']['slots']=[{'slot_index':i,'category':'starting_position'if i<11 else'bench',
                             'person':{'database_index':i,'native_id':100+i}}for i in range(20)]
    coverage={'phase':{'rule_flags':[1]},'source_state':'available'}
    rows={i:{'state':'absent','reason':None,'stored_appearance_counter_raw_u8':None,
             'native_other_team_cup_history_condition':None,'historical_other_team_appearance':None}for i in range(20)}
    def collect(*a):
        assert a[-1]==set(range(20));return deepcopy(coverage),deepcopy(rows)
    monkeypatch.setattr(module.cup_history,'collect',collect)
    monkeypatch.setattr(bridge,'_compose_fixture_player_checks',lambda *a:None)
    return {'decoded':decoded,'coverage':coverage,'rows':rows,'saved':saved}


def test_source_bound_slots_preserved_and_no_refs_or_addresses(bridge,sheet,bound):
    answer=bridge.get_fixture_player_checks(bridge.session,'fixture')
    assert len(answer['selected_players'])==20
    assert all(r['cup_history']['native_other_team_cup_history_condition']is False for r in answer['selected_players'])
    assert all(r['cup_history']['stored_appearance_counter_raw_u8']is None for r in answer['selected_players'])
    assert answer['overall_clearance']=='unknown'
    assert bridge.player_refs=={} and bridge.team_refs=={}
    assert sheet['calls']['opened']==sheet['calls']['closed']==1
    assert 'address'not in str(answer)


def test_duplicate_selected_slots_not_dropped(bridge,sheet,bound,monkeypatch):
    sheet['source']['slots'][1]['person']=sheet['source']['slots'][0]['person']
    monkeypatch.setattr(module.cup_history,'collect',lambda *a:(bound['coverage'],bound['rows']))
    answer=bridge.get_fixture_player_checks(bridge.session,'fixture')
    assert len(answer['selected_players'])==20
    assert answer['selected_players'][0]['person']==answer['selected_players'][1]['person']


@pytest.mark.parametrize('kind',['unknown','inventory','route','identity','nonparticipant','torn'])
def test_binding_failures_reject_whole_answer(bridge,sheet,bound,kind,monkeypatch):
    ref='fixture'
    if kind=='unknown':ref='expired'
    if kind=='inventory':bound['saved']['catalog_identity']=('old',)
    if kind=='route':bound['saved']['route']=('old',)
    if kind=='identity':bound['decoded']['identity']=('changed',)
    if kind=='nonparticipant':bound['decoded']['teams']=(0x11000,0x12000)
    if kind=='torn':
        def collect(*a):
            sheet['memory'][0x100]=b'changed!!';return bound['coverage'],bound['rows']
        monkeypatch.setattr(module.cup_history,'collect',collect)
    with pytest.raises(BridgeError):bridge.get_fixture_player_checks(bridge.session,ref)
    assert bridge.player_refs=={}


def test_missing_selection_or_unknown_boundary_is_unavailable_not_empty(bridge,sheet,bound):
    sheet['source']['source_state']='unavailable'
    assert bridge.get_fixture_player_checks(bridge.session,'fixture')['selected_players']is None
    sheet['source'].update(source_state='available',role_boundary_state='unresolved')
    answer=bridge.get_fixture_player_checks(bridge.session,'fixture')
    assert answer['coverage']['unavailable_reason']=='selected_bench_boundary_unresolved'
    assert answer['selected_players']is None


@pytest.mark.parametrize('refs',[[],[''],[True],['x']*33,'x'])
def test_invalid_proposed_ref_input_rejected(bridge,sheet,bound,refs):
    with pytest.raises(BridgeError):
        bridge.get_fixture_player_checks(bridge.session,'fixture',player_refs=refs)


def test_proposal_optin_and_duplicates_preserve_default(bridge,sheet,bound,monkeypatch):
    ref='candidate';bridge.player_refs[ref]={'address':0x12300}
    public={'display_name':'Cal Cresdee','record_kind':'actual',
            'native_identity':{'database_index':100,'native_id':123}}
    monkeypatch.setattr(bridge,'_bound_subjects',lambda *a:{ref:(0x12688,public)})
    monkeypatch.setattr(module.database,'table',lambda *a:{})
    monkeypatch.setattr(module.cup_history,'candidate_context',lambda *a:{'state':'compatible'})
    rows=deepcopy(bound['rows']);rows[100]=deepcopy(rows[0]);seen=[]
    def collect(*a):seen.append(a[-1]);return bound['coverage'],rows
    monkeypatch.setattr(module.cup_history,'collect',collect)
    default=bridge.get_fixture_player_checks(bridge.session,'fixture')
    answer=bridge.get_fixture_player_checks(bridge.session,'fixture',player_refs=[ref,ref])
    assert 'proposed_players'not in default
    assert default['selected_players']==answer['selected_players']
    assert answer['proposed_players'][0]==answer['proposed_players'][1]
    assert seen==[set(range(20)),set(range(20))|{100}]
    assert answer['proposed_players'][0]['cup_history']['native_other_team_cup_history_condition']is False
    sheet['source'].update(source_state='unavailable',role_boundary_state='source_unavailable',slots=None)
    proposed_only=bridge.get_fixture_player_checks(bridge.session,'fixture',player_refs=[ref])
    assert proposed_only['selected_players']is None
    assert proposed_only['proposed_players'][0]['history_state']=='compatible_proposal_checked'


def test_unknown_proposed_ref_rejected_without_publishing(bridge,sheet,bound,monkeypatch):
    monkeypatch.setattr(module.database,'table',lambda *a:{})
    with pytest.raises(BridgeError,match='Unknown or expired player reference'):
        bridge.get_fixture_player_checks(bridge.session,'fixture',player_refs=['unknown'])
    assert bridge.player_refs=={}


def test_unavailable_cup_keeps_picks_for_other_checks_without_zero_summary(bridge,sheet,bound,monkeypatch):
    monkeypatch.setattr(module.cup_history,'collect',lambda *a:({'source_state':'unavailable'},None))
    answer=bridge.get_fixture_player_checks(bridge.session,'fixture')
    assert len(answer['selected_players'])==20
    assert all(row['cup_history']is None for row in answer['selected_players'])
    assert answer['native_condition_true_count']is None
