import asyncio
from datetime import date
import struct

import pytest

from fm_live_mcp import league_age_exemptions as age, players, server, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_competition_stages import stage_memory
from test_database import bind, database_memory
from test_players import memory
from test_shortlist_members import member_memory
from test_teams import team_memory
from test_world import world_memory


@pytest.fixture
def age_memory(member_memory):
    m = stage_memory.__wrapped__(team_memory.__wrapped__(member_memory))
    for rva, raw in age.NATIVE_SPANS:
        m['put'](m['base']+rva, raw)
    comp, runtime, club = m['competitions'][0], m['runtime'], m['club']
    m['put'](comp+12, struct.pack('<II',11,11)); m['q'](comp+0x60,m['geography']['nation'][0])
    m['q'](m['base']+0x566C2B8+0xE8,m['base']+0x3AD4D70)
    m['put'](runtime+0xD0,struct.pack('<HH',1,2030)); m['put'](runtime+0x49,b'\x00')
    owner,bank,rule,req = [m['allocate'](0x400) for _ in range(4)]
    m['q'](runtime+0x388,owner);m['q'](owner+0x1F0,bank);m['vec'](bank+0x60,[rule])
    m['put'](rule+0xE8,struct.pack('<I',0x402));m['put'](rule+0x125,b'\x08');m['put'](rule+0x108,struct.pack('<i',11));m['put'](rule+0xF1,b'\x08')
    m['q'](rule+0x70,req);m['put'](req+0x18,b'\x01\x03')
    selected=[]
    for index, code in enumerate((0,266,268,278)):
        team=m['typed']('team',0xB8)
        m['put'](team+8,struct.pack('<III',index,50+index,50+index))
        m['put'](team+0x28,struct.pack('<H',code));m['q'](team+0x30,club);m['q'](team+0x50,comp)
        m['vec'](team+0x38,[]);selected.append(team)
    outsider=m['team_addresses'][1]
    m['put'](outsider+8,struct.pack('<III',4,90,90))
    m['vec'](m['headers']['teams'],selected+[outsider])
    m['vec'](m['owners'][1]+0x18,[outsider])
    m['vec'](club+0x18,selected)
    m['q'](m['contract']+0x10,selected[0]);m['q'](m['contract']+0x18,selected[0]);m['q'](selected[0]+0x80,m['manager'])
    births=['2005-07-10','2009-03-14','2013-04-07','2008-09-29']
    records=[];persons=[]
    for index,birth in enumerate(births):
        kind='player_staff' if index==1 else 'actual'
        primary,person=m['add_person'](kind,index,1000+index,0 if index==1 else 1000+index,f'Player {index}')
        d=date.fromisoformat(birth);delta=0xF8 if kind=='player_staff' else 0
        m['put'](primary+0x2D0+delta,struct.pack('<HH',d.timetuple().tm_yday,d.year))
        m['q'](primary+0x128,selected[0] if index<3 else outsider)
        records.append(primary);persons.append(person)
    for rva,off in ((players.RVA[2],0x388),(players.STAFF_RVA[2],0x480)):
        for slot,fn in ((0x138,0x148F4C0),(0x1B8,0xCA4640),(0x230,0xD5C578)):
            m['q'](m['base']+rva+slot,m['base']+fn)
        m['put'](m['base']+rva-0x1C8,struct.pack('<q',-0x110))
        m['put'](m['base']+rva-0x240,struct.pack('<q',-off))
    m['vec'](m['headers']['people'],persons)
    m['vec'](selected[0]+0x38,[records[0],records[3]])
    m['vec'](selected[1]+0x38,[records[1]])
    # Same player in another squad remains a separate physical roster occurrence.
    m['vec'](selected[2]+0x38,[records[2],records[1]])
    m['put'](m['base']+world.CURRENT_DATE,struct.pack('<HH',301,2030))
    m.update(age_teams=selected,age_records=records,age_persons=persons,rule=rule,req=req,bank=bank)
    return m


def collect(m,read=None):
    snapshot=world.ReadSet(read or m['read'])
    result,pending=age.collect(snapshot,m['base'],m['tables'],m['age_teams'][0],'2030-10-28')
    snapshot.verify()
    return result,pending


@pytest.mark.parametrize('dob,expected', [('2005-07-10',False),('2009-03-14',True),
 ('2013-04-07',True),('2007-11-19',False),('2008-02-29',False),('2009-12-31',True),
 ('1900-01-01',None),('2031-01-01',None),(None,None)])
def test_independent_dated_threshold_controls(dob,expected):
    assert age.classify(dob,'2030-10-28','2029-12-31')['age_exempt'] is expected


def test_real_typed_rosters_combined_names_and_outside_context(age_memory):
    m=age_memory;result,pending=collect(m)
    assert result['counts']==dict(age_exempt=3,not_exempt=1,outside_club_context=1,unavailable=0)
    assert [r['native_type'] for r in result['squads']]==[0,266,268]
    assert result['excluded_squads'][0]['native_type']==278
    assert result['source']['cutoff_date']=='2029-12-31'
    assert result['players'][2]['record_kind']=='player_staff'
    assert result['players'][2]['native_identity']['random_id']==0
    assert result['players'][2]['native_identity']==result['players'][4]['native_identity']
    assert all(p['world_bound'] for p in pending)
    assert 'address' not in repr(result)


@pytest.mark.parametrize('fault,reason',[('comp','unsupported_current_competition'),
 ('rule','unsupported_age_requirement'),('missing_rule','default_rule_absent'),
 ('override','unsupported_cutoff_override'),('date_unset','cutoff_date_unset'),
 ('alternate','unsupported_rule_selection_branch'),('missing_bank','rule_bank_absent')])
def test_unsupported_source_is_unavailable_not_false(age_memory,fault,reason):
    m=age_memory
    if fault=='comp':m['put'](m['competitions'][0]+12,struct.pack('<II',12,12))
    if fault=='rule':m['put'](m['req']+0x19,b'\x04')
    if fault=='missing_rule':m['put'](m['runtime']+0x49,b'\xff')
    if fault=='override':m['vec'](m['runtime']+0x2B0,[m['allocate'](8)])
    if fault=='date_unset':m['put'](m['runtime']+0xD0,struct.pack('<HH',1,1900))
    if fault=='alternate':m['put'](m['runtime']+0x4C,b'\x08')
    if fault=='missing_bank':m['q'](m['runtime']+0x388,0)
    result,_=collect(m)
    assert result['source']['source_state']=='unavailable'
    assert result['source']['reason']==reason
    assert result['counts']['unavailable']==4
    assert all(r['age_exempt'] is None for r in result['players'])


@pytest.mark.parametrize('fault',['native','canonical_person','canonical_team','birth_base','age_dispatch','team_dispatch','team_base','cutoff_dispatch','bad_cutoff','backlink'])
def test_corrupt_sources_reject(age_memory,fault):
    m=age_memory;vt=m['base']+players.RVA[2]
    if fault=='native':m['put'](m['base']+age.NATIVE_SPANS[0][0],b'\0')
    if fault=='canonical_person':m['q'](int.from_bytes(m['read'](m['headers']['people'],8),'little'),m['age_persons'][1])
    if fault=='canonical_team':m['put'](m['age_teams'][0]+8,struct.pack('<I',1))
    if fault=='birth_base':m['put'](vt-0x1C8,struct.pack('<q',-0x108))
    if fault=='age_dispatch':m['q'](vt+0x138,0)
    if fault=='team_dispatch':m['q'](vt+0x230,0)
    if fault=='team_base':m['put'](vt-0x240,struct.pack('<q',-0x380))
    if fault=='cutoff_dispatch':m['q'](m['base']+0x566C2B8+0xE8,0)
    if fault=='bad_cutoff':m['put'](m['runtime']+0xD0,struct.pack('<HH',366,2030))
    if fault=='backlink':m['q'](m['age_teams'][1]+0x30,m['owners'][1])
    with pytest.raises(ValueError):collect(m)


def test_unknown_age_namespace_and_virtual_are_explicit_without_generation(age_memory):
    m=age_memory;m['put'](m['age_persons'][0]+0x18,struct.pack('<Q',1<<12))
    p,person=m['add_person']('virtual',4,999,999)
    m['vec'](m['headers']['people'],m['age_persons']+[person])
    m['vec'](m['age_teams'][2]+0x38,[p])
    result,pending=collect(m)
    assert result['players'][0]['reason']=='unsupported_player_age_calendar'
    assert result['players'][-1]['reason']=='unsupported_virtual_age_source'
    assert pending[-1] is None and result['players'][-1]['birth_date'] is None


def test_late_drift_rejects_without_reference_publication(bridge,monkeypatch,age_memory):
    m=age_memory;bind(bridge,monkeypatch,m)
    baseline=bridge.get_managed_league_age_exemptions(bridge.session)
    assert baseline['counts']['age_exempt']==3
    assert bridge.get_player(bridge.session,baseline['players'][0]['player_ref'])['player']['name']=='Player 0'
    before=dict(bridge.player_refs)
    original=m['read'];reads=0
    def drift(address,size):
        nonlocal reads
        if address==m['runtime']+0xD0:
            reads+=1
            if reads>=2:return struct.pack('<HH',2,2030)
        return original(address,size)
    monkeypatch.setattr(bridge,'_read_memory',lambda p,a,n:drift(a,n))
    with pytest.raises(BridgeError,match='changed'):
        bridge.get_managed_league_age_exemptions(bridge.session)
    assert bridge.player_refs==before


def test_public_readonly_contract(monkeypatch):
    tool=next(t for t in asyncio.run(server.mcp.list_tools()) if t.name=='fm_get_managed_league_age_exemptions')
    assert set(tool.inputSchema['properties'])=={'session_id','coach_name','include_registration'}
    assert tool.inputSchema['required']==['session_id']
    assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
    calls=[]
    monkeypatch.setattr(server.bridge,'get_managed_league_age_exemptions',lambda *a:calls.append(a) or {})
    assert server.fm_get_managed_league_age_exemptions('session','Coach')=={}
    assert calls==[('session','Coach')]


@pytest.mark.parametrize('born,at,expected', [
 ('2009-12-31','2029-12-30',19),('2009-12-31','2029-12-31',20),
 ('2009-12-31','2030-01-01',20),('2008-02-29','2028-02-28',19),
 ('2008-02-29','2028-02-29',20),('2008-02-29','2028-03-01',20),
 ('1933-03-01','2032-02-29',None),('2008-02-29','2029-02-28',None),
 ('1980-01-01','1900-01-01',None),('1850-06-01','1900-12-31',None)])
def test_exact_same_leap_anniversaries_and_explicit_mixed_leap_gap(born,at,expected):
    assert age.native_age(born,at)==expected


def test_allocated_empty_selected_rosters_remain_explicit(age_memory):
    m=age_memory
    for team in m['age_teams'][:3]:m['vec'](team+0x38,[])
    result,pending=collect(m)
    assert result['count']==0 and pending==[]
    assert len(result['squads'])==3 and result['missing_squad_types']==[]
    assert all(s['native_slot_count']==0 for s in result['squads'])


@pytest.mark.parametrize('name',[True,2,'', ' '*2,'x'*129])
def test_invalid_coach_selector_fails_before_reads(bridge,name):
    with pytest.raises(BridgeError,match='coach_name'):
        bridge.get_managed_league_age_exemptions(bridge.session,name)


@pytest.mark.parametrize('change',['club_order','managed_type','absent_comp','absent_runtime'])
def test_managed_context_and_absence_do_not_become_age_rejection(age_memory,change):
    m=age_memory
    if change=='club_order':m['vec'](m['club']+0x18,list(reversed(m['age_teams'])))
    if change=='managed_type':m['put'](m['age_teams'][0]+0x28,struct.pack('<H',256))
    if change=='absent_comp':m['q'](m['age_teams'][0]+0x50,0)
    if change=='absent_runtime':m['q'](m['competitions'][0]+0xB0,0)
    result,_=collect(m)
    assert result['source']['source_state']=='unavailable'
    assert all(r['age_exempt'] is None for r in result['players'])


def test_late_canonical_slot_drift_rejects_before_refs(bridge,monkeypatch,age_memory):
    m=age_memory;bind(bridge,monkeypatch,m)
    pointer=int.from_bytes(m['read'](m['headers']['people'],8),'little')
    original=m['read'];reads=0
    def drift(address,size):
        nonlocal reads
        if address==pointer and size==8:
            reads+=1
            if reads>=3:return struct.pack('<Q',m['age_persons'][1])
        return original(address,size)
    monkeypatch.setattr(bridge,'_read_memory',lambda p,a,n:drift(a,n))
    with pytest.raises(BridgeError):bridge.get_managed_league_age_exemptions(bridge.session)
    assert bridge.player_refs=={}
