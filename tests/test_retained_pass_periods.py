from copy import deepcopy
import hashlib
import struct
import pytest
from fm_live_mcp.retained_pass_periods import project,pass_event_fingerprint
from fm_live_mcp.match_period_observations import digest


def sample():
    rows=[]
    for eid,side,a,b,start,end,category,flags in [(1,0,0,1,2,3,7,0),(2,0,1,0,12,13,7,0),(3,1,0,1,4,5,7,0),(4,0,0,1,8,10,7,0),(5,0,0,1,14,15,6,0),(6,0,0,1,16,17,7,8)]:
        e=bytearray(56);e[39:43]=bytes([a,side,b,category]);struct.pack_into('<H',e,34,start);struct.pack_into('<I',e,44,eid);struct.pack_into('<HH',e,48,flags,end);rows.append(e)
    raw=b''.join(rows)
    players=[dict(side_index=s,stored_player_slot=i,canonical_person_id=100+s*10+i,person_name=f'P{s}{i}',passes_completed=c,passes_attempted=a)for s,i,c,a in [(0,0,2,3),(0,1,1,1),(1,0,1,1),(1,1,0,0)]]
    observation=dict(pass_event_fingerprint=pass_event_fingerprint(raw))
    link=dict(state='verified_retrospective_continuity',capture_id=digest(observation),intervals=[dict(period='FirstHalf',start_tick=1,end_tick=10),dict(period='SecondHalf',start_tick=12,end_tick=20)],provenance={'test':True})
    return raw,players,link,observation


def test_exact_period_pairs_denominators_boundary_and_mask():
    out=project(*sample());assert out['state']=='available'
    first,second=out['sides'][0]['periods']
    assert (first['attempts'],first['completed_passes'])==(1,1)
    assert (second['attempts'],second['completed_passes'])==(2,1)
    assert out['sides'][0]['unknown_interval_attempts']==1
    assert first['two_way_pairs'][0]['share_of_period_completed_passes_computed']==100
    assert second['directed_pairs'][0]['from_name']=='P01'
    assert out['sides'][1]['periods'][1]['completed_passes']==0
    assert out['sides'][1]['periods'][1]['two_way_pairs']==[]


def test_relocated_paths_do_not_change_semantic_binding():
    raw,p,l,o=sample();r=bytearray(raw);struct.pack_into('<QQQ',r,0,0x1000,0x1100,0x1200)
    assert project(bytes(r),p,l,o)['state']=='available'


@pytest.mark.parametrize('offset',[34,39,40,41,42,44,48,50])
def test_any_consumed_event_semantic_change_rejects(offset):
    raw,p,l,o=sample();r=bytearray(raw);r[offset]^=1
    assert project(bytes(r),p,l,o)['state']=='unavailable_no_exact_pass_period_source'


def test_missing_host_evidence_does_not_become_zero():
    raw,p,l,o=sample();l['state']='unavailable_no_verified_host_period_link'
    out=project(raw,p,l,o);assert out['sides']is None


def test_bad_player_counter_withholds_only_affected_side():
    raw,p,l,o=sample();p[0]['passes_attempted']+=1
    out=project(raw,p,l,o);assert out['state']=='partial'
    assert out['sides'][0]['periods']is None
    assert out['sides'][1]['state']=='available'


def test_missing_recipient_withholds_side():
    raw,p,l,o=sample();p.pop(1)
    assert project(raw,p,l,o)['sides'][0]['periods']is None


def test_forged_observation_id_raises():
    raw,p,l,o=sample();o['extra']='changed'
    with pytest.raises(ValueError,match='identity'):project(raw,p,l,o)


def test_duplicate_pass_event_id_rejected():
    raw,*_=sample()
    with pytest.raises(ValueError,match='Duplicate'):pass_event_fingerprint(raw+raw[:56])


def test_raw_hash_compatibility_and_rejection():
    raw,p,l,o=sample();o={'source_hashes':{'events':hashlib.sha256(raw).hexdigest()}};l['capture_id']=digest(o)
    assert project(raw,p,l,o)['pass_period_binding']=='exact_complete_observed_event_vector'
    o['source_hashes']['events']='0'*64;l['capture_id']=digest(o)
    assert project(raw,p,l,o)['periods']is None


def test_prefix_digest_excludes_future_but_not_past_changes():
    raw,p,l,o=sample();o['pass_event_fingerprint']=pass_event_fingerprint(raw,10);l['capture_id']=digest(o)
    l['intervals']=l['intervals'][:1]
    changed=bytearray(raw);changed[56+39]=0
    assert project(bytes(changed),p,l,o)['pass_period_binding']=='all_pass_event_semantics_match_host_observation'
    l['intervals'].append(dict(period='SecondHalf',start_tick=12,end_tick=20))
    assert project(raw,p,l,o)['reason']=='period_exceeds_observed_pass_prefix'


def test_registered_tool_declares_host_write_and_has_no_boundaries():
    from fm_live_mcp.retained_pass_period_tools import register_retained_pass_period_tools
    class MCP:
        def tool(self,**kw):
            assert kw['annotations'].readOnlyHint is False
            def deco(fn):self.fn=fn;return fn
            return deco
    m=MCP();register_retained_pass_period_tools(m,object())
    import inspect
    assert list(inspect.signature(m.fn).parameters)==['session_id','fixture_ref']


def test_report_specific_witness_preserves_strict_mutation_and_same_published_network():
    from fm_live_mcp.retained_pass_periods import pass_period_report_fingerprint
    raw,players,link,observation=sample()
    observation['pass_period_report_fingerprint']=pass_period_report_fingerprint(raw)
    link['capture_id']=digest(observation)
    original=deepcopy(observation)
    before=project(raw,players,link,observation)
    changed=bytearray(raw);changed[48]^=4;changed[56+48]^=2
    assert pass_event_fingerprint(bytes(changed))!=observation['pass_event_fingerprint']
    after=project(bytes(changed),players,link,observation)
    assert after['state']=='available'
    assert after['strict_pass_event_continuity']=='mismatch'
    assert after['pass_period_report_continuity']=='matched'
    assert before['sides']==after['sides']
    assert observation==original  # No upgrade or overwrite from retained bytes.
    assert before['event_vector_sha256']!=after['event_vector_sha256']


@pytest.mark.parametrize('offset,mask',[(34,1),(39,1),(40,1),(41,1),(42,1),(44,1),(48,8),(50,1)])
def test_report_specific_witness_rejects_every_consumed_field(offset,mask):
    from fm_live_mcp.retained_pass_periods import pass_period_report_fingerprint
    raw,players,link,observation=sample()
    observation['pass_period_report_fingerprint']=pass_period_report_fingerprint(raw)
    link['capture_id']=digest(observation)
    changed=bytearray(raw);changed[offset]^=mask
    out=project(bytes(changed),players,link,observation)
    assert out['state']=='unavailable_no_exact_pass_period_source'
    assert out['reason']=='published_pass_period_fields_or_selection_mask_differ'


def test_legacy_strict_witness_does_not_get_report_fingerprint_from_retained_source():
    raw,players,link,observation=sample()
    changed=bytearray(raw);changed[48]^=4
    out=project(bytes(changed),players,link,observation)
    assert out['reason']=='complete_observed_pass_semantics_differ'
    assert 'pass_period_report_fingerprint'not in observation
