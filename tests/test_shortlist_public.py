"""Independent real-memory public shortlist cardinality and reference lifetime checks."""
from copy import deepcopy
import struct

import pytest

from fm_live_mcp import players,shortlist_source as source,shortlist_members as members
from fm_live_mcp.bridge import BridgeError
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_database import bind,database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory


@pytest.fixture
def shortlist_public_memory(bridge,monkeypatch,prepared_tactics_memory):
    m=prepared_tactics_memory;base=m['base'];human=m['manager']
    for module in (source,members):
        for rva,raw in module.NATIVE_SPANS:m['put'](base+rva,raw)
    m['put'](base+source.MODE_FLAG,b'\1');m['put'](human+0x422,b'\1')
    m['put'](human+0x41F,b'\3');m['put'](human+0x42A,b'\0')
    m['typed_at'](0x1000,players.RVA[0],b'N2db13ACTUAL_PLAYERE')
    m['typed_at'](0x1388,players.RVA[2],b'N2db13ACTUAL_PLAYERE',-0x388)
    m['q'](base+players.RVA[2]+0x668,base+0xD5C5FC)
    m['put'](base+players.RVA[2]-0x678,struct.pack('<q',-0x388))
    m['put'](human+0x548+8,struct.pack('<III',1,999,0))
    m['vec'](m['headers']['people'],[0x1388,human+0x548])
    def entry(person):
        address=m['allocate'](0x38);m['q'](address,person);return address
    def new_list(entries=(),kind=0,name=None):
        address=m['allocate'](0x108);m['q'](address+0xD0,human)
        m['put'](address+0x4C,bytes([kind]));m['q'](address+0xE8,0 if name is None else m['text'](name))
        m['vec'](address+0x80,list(entries));return address
    first_entry=entry(0x1388);first_list=new_list([first_entry],name='Recruitment')
    def set_lists(values):m['vec'](human+0x230,list(values))
    set_lists([first_list]);bind(bridge,monkeypatch,m)
    m.update(shortlist_entry=entry,new_shortlist=new_list,set_personal_lists=set_lists,
             first_shortlist=first_list,first_shortlist_entry=first_entry)
    bridge.player_refs['existing']={'untouched':True}
    return m


def query(bridge,**kw):return bridge.get_managed_shortlists(bridge.session,**kw)


def test_real_player_reference_reopens_with_independent_secondary_zero(bridge,shortlist_public_memory):
    m=shortlist_public_memory;m['put'](0x1398,struct.pack('<I',0))
    result=query(bridge)
    assert result['lists']==[{'list_index':0,'stored_name':'Recruitment','entry_count':1}]
    assert result['total_entries']==1 and result['next_offset'] is None
    row=result['entries'][0]
    assert row['state']=='player' and row['native_identity']=={'database_index':0,'native_id':12345,'random_id':0}
    assert row['display_name']=='Test Müller'
    reopened=bridge.get_player(bridge.session,row['player_ref'],profile_policy='available')
    assert reopened['player']['native_identity']==row['native_identity'] and reopened['player']['display_name']==row['display_name']
    assert result['report_availability']=='unavailable_unproved_report_source'


def test_all_slots_include_nulls_unsupported_and_duplicate_players_across_pages(bridge,shortlist_public_memory):
    m=shortlist_public_memory
    a=m['new_shortlist']([m['first_shortlist_entry'],0,m['shortlist_entry'](0),m['shortlist_entry'](m['manager']+0x548),m['first_shortlist_entry']])
    m['set_personal_lists']([a]);all_rows=query(bridge)['entries']
    assert [r['state'] for r in all_rows]==['player','null_entry','null_person','unsupported_person_kind','player']
    assert [r['native_entry_index'] for r in all_rows]==list(range(5))
    assert all_rows[3]['record_kind']=='human_manager' and all_rows[3]['native_identity']=={'database_index':1,'native_id':999,'random_id':0}
    assert all(r['player_ref'] is None for r in all_rows[1:4])
    pages=[];offset=0
    while True:
        result=query(bridge,offset=offset,limit=2);pages.extend(result['entries'])
        assert result['total_entries']==5
        if result['next_offset'] is None:break
        offset=result['next_offset']
    def shape(rows):return [{k:v for k,v in r.items() if k!='player_ref'} for r in rows]
    assert shape(pages)==shape(all_rows)
    assert query(bridge,offset=5)['entries']==[] and query(bridge,offset=99)['next_offset'] is None


@pytest.mark.parametrize('mode',['global_off','human_off'])
def test_unsupported_source_has_unknown_counts_not_empty_membership(bridge,shortlist_public_memory,mode):
    m=shortlist_public_memory
    if mode=='global_off':m['put'](m['base']+source.MODE_FLAG,b'\0')
    else:m['put'](m['manager']+0x422,b'\0')
    before=deepcopy(bridge.player_refs);result=query(bridge)
    assert result['source_state']=='unavailable' and result['selection_state']=='source_unavailable'
    assert result['personal_list_count'] is result['total_entries'] is result['selected_list_index'] is None
    assert result['lists']==result['entries']==[] and result['next_offset'] is None
    assert result['report_availability']=='unavailable_unproved_report_source' and bridge.player_refs==before


def test_empty_selected_list_is_zero_distinct_from_no_personal_lists(bridge,shortlist_public_memory):
    m=shortlist_public_memory;m['set_personal_lists']([m['new_shortlist']()])
    result=query(bridge)
    assert result['source_state']=='available' and result['selection_state']=='selected' and result['selected_list_index']==0
    assert result['total_entries']==0 and result['entries']==[] and result['next_offset'] is None
    m['set_personal_lists']([]);result=query(bridge)
    assert result['source_state']=='available' and result['selection_state']=='personal_list_vector_empty'
    assert result['personal_list_count']==0 and result['total_entries'] is None and result['entries']==[]


def test_null_default_list_retains_ordinal_and_is_unavailable(bridge,shortlist_public_memory):
    m=shortlist_public_memory;m['set_personal_lists']([0,m['first_shortlist']])
    result=query(bridge)
    assert result['personal_list_count']==2 and result['null_list_indices']==[0]
    assert result['lists'][0]['list_index']==1
    assert result['selection_state']=='selected_list_null' and result['total_entries'] is None
    assert result['entries']==[]


@pytest.mark.parametrize('selector',[-1,-128])
def test_negative_stored_selector_has_explicit_native_clamp(bridge,shortlist_public_memory,selector):
    m=shortlist_public_memory;m['put'](m['manager']+0x42A,struct.pack('<b',selector))
    result=query(bridge)
    assert result['stored_selected_index']==selector and result['selector_negative_clamped'] is True
    assert result['effective_personal_selected_index']==result['selected_list_index']==0 and result['total_entries']==1


def test_explicit_native_index_is_not_filtered_list_ordinal(bridge,shortlist_public_memory):
    m=shortlist_public_memory;m['set_personal_lists']([0,m['new_shortlist'](kind=8),m['first_shortlist']])
    m['put'](m['manager']+0x41F,b'\1')
    default=query(bridge);assert default['selection_state']=='current_selection_not_personal' and default['total_entries'] is None
    result=query(bridge,list_index=2)
    assert result['selected_list_index']==2 and result['entries'][0]['state']=='player'
    assert result['lists']==[{'list_index':2,'stored_name':'Recruitment','entry_count':1}]
    for invalid in (0,1,3):
        with pytest.raises(BridgeError):query(bridge,list_index=invalid)


@pytest.mark.parametrize('target',['entry_pointer','identity','canonical_membership','owner','mode','selector','stored_name'])
def test_late_failure_publishes_no_new_refs(bridge,monkeypatch,shortlist_public_memory,target):
    m=shortlist_public_memory;original=members.page;before=deepcopy(bridge.player_refs)
    def changed(*a,**kw):
        rows=original(*a,**kw)
        if target=='canonical_membership':
            start=struct.unpack('<Q',m['read'](m['headers']['people'],8))[0];m['q'](start,m['manager']+0x548)
        else:
            address={'entry_pointer':m['first_shortlist_entry'],'identity':0x1394,'owner':m['first_shortlist']+0xD0,
                'mode':m['base']+source.MODE_FLAG,'selector':m['manager']+0x42A,'stored_name':m['first_shortlist']+0xE8}[target]
            value=m['read'](address,1)[0];m['put'](address,bytes([value^1]))
        return rows
    monkeypatch.setattr(members,'page',changed)
    with pytest.raises(BridgeError):query(bridge)
    assert bridge.player_refs==before


def test_retained_person_same_index_cannot_mint_reference(bridge,shortlist_public_memory):
    m=shortlist_public_memory;start=struct.unpack('<Q',m['read'](m['headers']['people'],8))[0]
    m['q'](start,m['manager']+0x548);before=deepcopy(bridge.player_refs)
    with pytest.raises(BridgeError,match='canonical membership'):query(bridge)
    assert bridge.player_refs==before
