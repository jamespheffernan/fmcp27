from copy import deepcopy
from pathlib import Path
import gzip,json,struct
import pytest
from fm_live_mcp.retained_paired_width import project


def sample(a=((1000,100),(2000,100),(0,0)),b=((2000,100),(1000,100),(0,0)),starts=(24,24),phases=b'\0'*20):
    profile=bytearray(16);struct.pack_into('<iii',profile,0,-1,-1,-1);profile[13]=1
    t=dict(orientation_profile=bytes(profile),possession_samples=phases,players=[dict(side_index=0,stored_player_slot=i,start_tick=starts[i],samples=b''.join(struct.pack('<hh',*p)for p in v))for i,v in enumerate((a,b))])
    p=[dict(side_index=0,stored_player_slot=i,canonical_person_id=i+1,person_name=f'P{i}')for i in(0,1)]
    return t,p


def test_coincident_comparison_uses_absolute_per_point_not_absolute_mean():
    t,p=sample(a=((2000,100),(-2000,100)),b=((1000,100),(1000,100)))
    r=project(t,p,1,2);s=r['comparison']['all_coincident_in_possession']
    assert s['sample_count']==2 and s['players'][0]['wider_sample_count']==2
    assert s['players'][0]['mean_absolute_lateral_native']==20
    assert s['players'][1]['mean_absolute_lateral_native']==10


def test_denominators_ties_zero_tails_and_sensitivity():
    t,p=sample();r=project(t,p,1,2);s=r['comparison']['all_coincident_in_possession']
    assert [x['wider_sample_count']for x in s['players']]==[1,1]
    assert s['equal_width_sample_count']==1 and s['sample_count']==3
    assert r['coverage']['zero_pair_ticks_both']==1 and r['coverage']['trailing_zero_ticks_either']==1
    assert r['comparison']['nonzero_pair_sensitivity']['sample_count']==2
    assert s['both_wide_same_lateral_side']is None


def test_exact_alignment_never_nearest_neighbor():
    t,p=sample(starts=(24,25));r=project(t,p,1,2)
    assert r['state']=='unavailable_no_coincident_tracking_ticks'and r['comparison']is None
    t,p=sample(starts=(24,48));r=project(t,p,1,2)
    assert r['coverage']['coincident_position_ticks']==2
    assert r['coverage']['unmatched_samples']==[1,1]


def test_no_shared_extent_is_unknown():
    t,p=sample(starts=(24,2400))
    assert project(t,p,1,2)['comparison']is None


def test_phase_actual_byte_only_and_no_clamping():
    t,p=sample(a=((100,100),)*6,b=((200,100),)*6,phases=bytes([0,0,1,255,3]))
    r=project(t,p,1,2);c=r['coverage']
    assert c['in_possession_ticks']==1 and c['out_of_possession_ticks']==1
    assert c['phase_unclassified_ticks']==1 and c['phase_other_ticks']==1 and c['phase_uncovered_ticks']==2


def test_missing_phase_never_becomes_out_of_possession_or_zero():
    t,p=sample(phases=b'')
    assert project(t,p,1,2)['state']=='unavailable_possession_stream'


def test_wide_same_side_outer_thirds_and_bounds():
    t,p=sample(a=((2000,100),(-2000,100),(4000,100)),b=((1800,100),(1800,100),(1800,100)))
    r=project(t,p,1,2,pitch_geometry=dict(half_width_native=30,half_length_native=50))
    s=r['comparison']['in_bounds_nonzero_pair_sensitivity'];w=s['both_wide_same_lateral_side']
    assert s['sample_count']==2 and w['sample_count']==1 and w['percentage_computed']==50
    assert w['threshold_absolute_lateral_native']==10
    assert r['coverage']['outside_pitch_bounds_ticks_either']==1


@pytest.mark.parametrize('change',['truncated','duplicate','wrongside','sameperson','bounds'])
def test_hostile_inputs_rejected(change):
    t,p=sample();kw={};a,b=1,2
    if change=='truncated':t['players'][0]['samples']=b'x'
    if change=='duplicate':t['players'].append(deepcopy(t['players'][0]))
    if change=='wrongside':t['players'][1]['side_index']=p[1]['side_index']=1
    if change=='sameperson':b=1
    if change=='bounds':kw['pitch_geometry']=dict(half_width_native=float('nan'),half_length_native=50)
    with pytest.raises(ValueError):project(t,p,a,b,**kw)


def test_missing_selected_track_is_unknown():
    t,p=sample();t['players'].pop()
    assert project(t,p,1,2)['state']=='unavailable_selected_player_tracking'


def decode(v):
    if isinstance(v,dict):return bytes.fromhex(v['_bytes_hex'])if'_bytes_hex'in v else{k:decode(x)for k,x in v.items()}
    if isinstance(v,list):return[decode(x)for x in v]
    return v


def test_genuine_lille_tail_bias_and_width_comparison():
    f=decode(json.loads(gzip.decompress((Path(__file__).parent/'fixtures/lille_paired_width.json.gz').read_bytes())))
    ids={p['person_name']:p['canonical_person_id']for p in f['players']}
    r=project(f['tracking'],f['players'],ids['Alberto Costa'],ids['Luiz Henrique'],pitch_geometry=f['pitch_geometry'])
    assert r['coverage']['coincident_position_ticks']==946 and r['coverage']['in_possession_ticks']==459
    assert r['coverage']['zero_pair_ticks_either']==176
    all_=r['comparison']['all_coincident_in_possession'];clean=r['comparison']['in_bounds_nonzero_pair_sensitivity']
    assert all_['players'][0]['wider_sample_count']==342
    assert clean['sample_count']==269 and clean['players'][0]['wider_sample_count']==152 and clean['players'][1]['wider_sample_count']==113
    assert clean['equal_width_sample_count']==4
    assert clean['both_wide_same_lateral_side']['sample_count']==217
    d=project(f['tracking'],f['players'],ids['El Hadji Malick Diouf'],ids['Jay Robinson'],pitch_geometry=f['pitch_geometry'])
    assert d['comparison']['nonzero_pair_sensitivity']['sample_count']==271
    assert d['coverage']['zero_pair_ticks_both']==176


def test_tool_schema_no_timing_or_role_guess():
    from fm_live_mcp.retained_paired_width_tools import register_retained_paired_width_tools
    class MCP:
        def tool(self,**kwargs):
            assert kwargs['annotations'].readOnlyHint
            def deco(fn):self.fn=fn;return fn
            return deco
    m=MCP();register_retained_paired_width_tools(m,object())
    import inspect
    assert list(inspect.signature(m.fn).parameters)==['session_id','fixture_ref','person_a_native_id','person_b_native_id']


@pytest.mark.parametrize('tracking',[{'state':'unavailable_no_retained_tracking','players':[]},None,{}])
def test_report_unavailable_tracking_early_no_projection_or_recapture(monkeypatch,tracking):
    from types import SimpleNamespace
    from contextlib import nullcontext
    from fm_live_mcp import retained_paired_width as paired,live_retained_shots as retained,live_retained_passes as passes,match_data_query as query,current_spatial_axes,players
    class Read:
        def verify(self):pass
    class Bridge:
        lock=nullcontext()
        def _read_scope(self,sid):return nullcontext()
        def _current(self,sid):return object()
        def _player_layout(self,process):return[players.RVA[0]+4096]
        def _world_state(self,process,tables):return Read(),None,None
    fixture={'fixture_ref':'f'}
    packet={'_live_capture_epoch':'epoch','capture':{'fixtures':[{'fixture':fixture,'native_match_key':7}]},'team_totals':{'records':[{'result_key':7,'teams':[]}]},'retained_players':[{'fixture_key':7}]}
    monkeypatch.setattr(query,'capture_epoch',lambda *a:'epoch')
    def capture(*a,include_players=False):assert include_players;return packet
    monkeypatch.setattr(query,'capture_live',capture)
    monkeypatch.setattr(retained,'_validate_team_oracle',lambda *a:None)
    monkeypatch.setattr(retained,'_validated_actors',lambda *a:{1:1})
    monkeypatch.setattr(passes,'_verify_pass_native',lambda *a:None)
    monkeypatch.setattr(current_spatial_axes,'verify_native',lambda *a:None)
    calls=[]
    def source(*a,**kw):calls.append(1);return {'state':'available','tracking':tracking}
    monkeypatch.setattr(retained,'capture_source',source)
    def forbidden(*a,**kw):pytest.fail('Unavailable tracking must return before counter projection or recapture')
    monkeypatch.setattr(passes,'decode_pass_network',forbidden)
    monkeypatch.setattr(paired,'project',forbidden)
    r=paired.report(Bridge(),'session','f',1,2)
    assert r['state'].startswith('unavailable')and r['comparison']is None
    assert r['reason']=='retained_source_has_no_available_tracking'
    assert r['fixture']==fixture and calls==[1]
