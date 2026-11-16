import json
import struct
from pathlib import Path
from contextlib import nullcontext

import pytest
from fm_live_mcp import live_player_match_form as form, players, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_players import memory
from test_world import world_memory
from test_database import database_memory
from test_teams import team_memory


@pytest.fixture
def form_memory(team_memory):
    m=team_memory
    for rva,raw in json.loads(Path(__file__).with_name('live_player_match_form_native.json').read_text()).items():
        m['put'](m['base']+int(rva,0),bytes.fromhex(raw))
    f0=m['allocate'](0x80);vector=m['allocate'](24);m['q'](0x10F0,f0);m['q'](f0+0x58,vector)
    def group(team=0,cap=20,head=0,rows=()):
        rva=0x55BA1E0 if cap==20 else 0x55BA270
        _,off,getters=form.GROUPS[rva];a=m['allocate'](off+8);vt=m['base']+rva
        ti=m['allocate'](16);name=m['allocate'](64);m['q'](ti+8,name)
        m['put'](name,f'N2db25PLAYER_TEAM_FORM_CONCRETEILm{cap}EEE'.encode()+b'\0')
        m['put'](vt-16,struct.pack('<qQ',0,ti));m['q'](a,vt)
        for slot,getter in zip((0x30,0x38,0x40,0x48),getters):m['q'](vt+slot,m['base']+getter)
        m['q'](a+8,m['team_addresses'][team]);m['put'](a+0x10,bytes([len(rows)]));m['put'](a+off,bytes([head]))
        for i,r in enumerate(rows):m['q'](a+0x18+8*((head+i)%cap),r)
        return a
    def row(day,minutes=90,goals=0,on=0,stats=True,comp=0):
        a=m['allocate'](0x20);m['q'](a,m['team_addresses'][1]);m['put'](a+0x10,struct.pack('<IiB',(2030<<16)|day,comp,0 if stats else 12))
        if stats:
            s=m['allocate'](40);m['q'](a+8,s);m['put'](s+7,bytes([goals]));m['put'](s+0x15,bytes([minutes]));m['put'](s+0x11,bytes([on]))
        return a
    rows=[row(290,90,2),row(291,stats=False),row(292,0,0,on=90),row(293,0),row(294,25,1)]
    g=group(rows=rows,head=18);m['vec'](vector,[g]);m.update(f0=f0,form_vector=vector,form_group=g,form_rows=rows,form_row=row,form_make_group=group)
    return m


def decode(m,mode='confirmed_appearances',limit=5,read=None):
    return form.decode(read or m['read'],m['base'],0x1000,m['tables'],m['team_addresses'][0],mode,limit)


def test_ring_rotates_and_keeps_missing_and_zero_states(form_memory):
    r=decode(form_memory);s=r['selection']
    assert r['source_state']=='available' and r['whole_career_complete'] is False
    assert [x['native_row_index']for x in s['rows']]==[4,2,0]
    assert [x['minutes']for x in s['rows']]==[25,0,90]
    assert [x['goals']for x in s['rows']]==[1,0,2]
    assert [x['native_row_index']for x in s['ambiguous_entries_at_or_after_cutoff']]==[3,1]
    assert s['last_confirmed_rows_unambiguous_within_resident_ring'] is False
    allrows=decode(form_memory,'team_entries')['selection']['rows']
    assert [x['native_row_index']for x in allrows]==[4,3,2,1,0]
    assert allrows[3]['minutes'] is None and allrows[3]['goals'] is None
    assert allrows[1]['appearance_state']=='unknown_zero_minutes'
    assert allrows[0]['opponent']['kind']=='national_team'
    assert '0x' not in str(r)


@pytest.mark.parametrize('cap,head',[(20,0),(20,19),(60,0),(60,59)])
def test_both_native_ring_classes(form_memory,cap,head):
    m=form_memory;g=m['form_make_group'](cap=cap,head=head,rows=m['form_rows']);m['vec'](m['form_vector'],[g])
    r=decode(m,'team_entries');assert r['capacity']==cap
    assert [x['physical_ring_slot']for x in reversed(r['selection']['rows'])]==[(head+i)%cap for i in range(5)]


@pytest.mark.parametrize('where,reason',[('secondary','player_secondary_not_resident'),('form','match_form_not_resident'),('group','no_retained_group_for_selected_team')])
def test_source_unavailable_is_not_empty(form_memory,where,reason):
    m=form_memory
    if where=='secondary':m['q'](0x10F0,0)
    elif where=='form':m['q'](m['f0']+0x58,0)
    else:m['vec'](m['form_vector'],[])
    r=decode(m);assert r['source_state']=='unavailable' and r['unavailable_reason']==reason
    assert r['selection'] is None and r['capacity'] is None


def test_allocated_empty_ring_is_available(form_memory):
    m=form_memory;m['put'](m['form_group']+0x10,b'\0');r=decode(m)
    assert r['source_state']=='available' and r['selection']['rows']==[]
    assert r['selection']['retained_entry_count']==0


@pytest.mark.parametrize('fault',['head','count','type','rtti','getter','native','dispatch','duplicate_group','duplicate_team','row_null','row_duplicate','team_membership','person_membership','person_index','playing_type','person_type','f0_pointer','form_bounds','competition','opponent'])
def test_corrupt_sources_reject_all_partial_results(form_memory,fault):
    m=form_memory;g=m['form_group'];base=m['base'];rows=m['form_rows']
    if fault=='head':m['put'](g+0xB8,b'\x14')
    elif fault=='count':m['put'](g+0x10,b'\x15')
    elif fault=='type':m['q'](g,base+0x1234)
    elif fault=='rtti':m['q'](base+0x55BA1E0-16,8)
    elif fault=='getter':m['q'](base+0x55BA1E0+0x40,base+0x153A5D4)
    elif fault=='native':m['put'](base+form.NATIVE_GUARDS[0][0],b'\xff')
    elif fault=='dispatch':m['put'](base+form.DISPATCH[0],b'\xff')
    elif fault=='duplicate_group':m['vec'](m['form_vector'],[g,g])
    elif fault=='duplicate_team':m['vec'](m['form_vector'],[g,m['form_make_group']()])
    elif fault=='row_null':m['q'](g+0x18+18*8,0)
    elif fault=='row_duplicate':m['q'](g+0x18+19*8,rows[0])
    elif fault=='team_membership':m['put'](m['team_addresses'][0]+8,struct.pack('<I',1))
    elif fault=='person_membership':m['vec'](m['headers']['people'],[m['club']])
    elif fault=='person_index':m['put'](0x1390,struct.pack('<I',1))
    elif fault=='playing_type':m['q'](0x1140,0)
    elif fault=='person_type':m['q'](0x1388,0)
    elif fault=='f0_pointer':m['q'](0x10F0,1)
    elif fault=='form_bounds':m['put'](m['form_vector'],struct.pack('<QQQ',4096,4104,0))
    elif fault=='competition':m['put'](rows[0]+0x14,struct.pack('<i',-2))
    elif fault=='opponent':m['q'](rows[0],4104)
    with pytest.raises((ValueError,KeyError,BridgeError)):decode(m)


@pytest.mark.parametrize('minutes,on,expected',[(0,0,'unknown_zero_minutes'),(0,90,'confirmed_recorded_substitution_on'),(1,0,'confirmed_positive_stored_duration'),(127,0,'confirmed_positive_stored_duration'),(128,0,'unknown_unmapped_duration'),(255,0,'unknown_unmapped_duration'),(0,255,'unknown_zero_minutes')])
def test_statistics_never_cast_unsigned_to_negative(minutes,on,expected):
    b=bytearray(37);b[21]=minutes;b[17]=on;r=form.statistics(bytes(b))
    assert r['appearance_state']==expected and r['minutes']==(minutes if minutes<=127 else None)


def test_undated_and_same_day_do_not_disappear(form_memory):
    m=form_memory;m['put'](m['form_rows'][0]+0x10,bytes(4));m['put'](m['form_rows'][1]+0x10,struct.pack('<I',(2030<<16)|294))
    s=decode(m,'team_entries',1)['selection'];assert len(s['undated_entries'])==1
    assert s['same_day_ties']==['2030-10-21']
    assert s['rows'][0]['native_row_index']==4 and len(s['ambiguous_entries_at_or_after_cutoff'])==2


@pytest.mark.parametrize('mode,limit',[('all',5),('confirmed_appearances',True),('team_entries',0),('team_entries',61),('team_entries',1.0)])
def test_options_strict(mode,limit):
    with pytest.raises(ValueError):form.select([],mode,limit)


def test_snapshot_recheck_detects_late_source_change(form_memory):
    m=form_memory;s=world.ReadSet(m['read']);decode(m,read=s)
    m['put'](m['form_rows'][0]+0x18,b'\x02')
    with pytest.raises(ValueError,match='changed'):s.verify()


def bind_bridge(b,m,monkeypatch):
    monkeypatch.setattr(b,'_read_scope',lambda sid:nullcontext())
    monkeypatch.setattr(b,'_read_memory',lambda p,a,n:m['read'](a,n))
    monkeypatch.setattr(b,'_player_layout',lambda p:m['tables'])
    # Keep the real player decode, canonical database and TEAM checks.
    def world_state(process,tables):
        return world.ReadSet(m['read']),{'name':'Test','coaches':[{'name':'Test','team_address':m['team_addresses'][0]}]},None
    monkeypatch.setattr(b,'_world_state',world_state)
    monkeypatch.setattr(b,'_public_save',lambda s:s)
    player,identity=b._roster_player(m['read'],0x1000,m['tables'],False,{})
    b.player_refs['p']={'address':0x1000,'identity':identity,'tables':m['tables'],'database_index':0}
    return b


def test_bridge_real_codec_no_new_refs(bridge,form_memory,monkeypatch):
    b=bind_bridge(bridge,form_memory,monkeypatch);before=(dict(b.player_refs),dict(b.team_refs),dict(b.competition_refs))
    result=b.get_player_match_form(b.session,'p')
    assert result['player']['name']=='Test Müller' and result['selection']['count']==3
    assert (b.player_refs,b.team_refs,b.competition_refs)==before
    m=form_memory;t=m['team_addresses'][0]
    b.team_refs['t']={'address':t,'identity':m['read'](t+8,12),'tables':m['tables'],'club_address':m['club']}
    assert b.get_player_match_form(b.session,'p','t')['selection']==result['selection']


@pytest.mark.parametrize('fault',['stale_player','stale_team','native','virtual','combined'])
def test_bridge_rejects_and_drops_failed_player_ref(bridge,form_memory,monkeypatch,fault):
    m=form_memory;b=bind_bridge(bridge,m,monkeypatch);team=None
    if fault=='stale_player':b.player_refs['p']['identity']=('stale',)
    elif fault=='stale_team':team='missing'
    elif fault=='native':m['put'](m['base']+form.NATIVE_GUARDS[0][0],b'\xff')
    elif fault=='virtual':m['q'](0x1000,m['base']+world.TYPES['virtual_player'][0])
    elif fault=='combined':m['q'](0x1000,m['base']+players.STAFF_RVA[0])
    with pytest.raises(BridgeError):b.get_player_match_form(b.session,'p',team)
    assert 'p'not in b.player_refs


@pytest.mark.parametrize('rva',[x[0]for x in (*form.NATIVE_GUARDS,form.DISPATCH)])
def test_each_native_guard_is_enforced(form_memory,rva):
    m=form_memory;at=m['base']+rva;raw=m['read'](at,1);m['put'](at,bytes([raw[0]^255]))
    with pytest.raises(ValueError,match='native code changed'):decode(m)


def test_explicit_team_owner_identity_is_not_normalized(bridge,form_memory,monkeypatch):
    m=form_memory;b=bind_bridge(bridge,m,monkeypatch);t=m['team_addresses'][0]
    b.team_refs['t']={'address':t,'identity':m['read'](t+8,12),'tables':m['tables'],
                      'club_address':m['club'],'club_identity':world.club(m['read'],m['base'],m['club'])[1]}
    m['put'](m['club']+0x10,struct.pack('<I',999))
    with pytest.raises(BridgeError,match='owner identity changed'):b.get_player_match_form(b.session,'p','t')


def test_bridge_torn_row_returns_no_result_or_new_references(bridge,form_memory,monkeypatch):
    m=form_memory;b=bind_bridge(bridge,m,monkeypatch);old=m['read'];target=m['form_rows'][4]
    def changing(a,n):
        raw=old(a,n)
        if a==target and n==32:m['put'](target+0x18,b'\x55')
        return raw
    m['read']=changing
    before=(dict(b.team_refs),dict(b.competition_refs))
    with pytest.raises(BridgeError,match='changed'):b.get_player_match_form(b.session,'p')
    assert (b.team_refs,b.competition_refs)==before and not b.player_refs


@pytest.mark.parametrize('rva',[0x153B6C8,0x153BF78,0x153B6D0,0x153BF80])
def test_selected_sixty_ring_getter_code_change_is_rejected(form_memory,rva):
    m=form_memory;g=m['form_make_group'](cap=60,head=59,rows=m['form_rows'])
    m['vec'](m['form_vector'],[g]);assert decode(m)['capacity']==60
    at=m['base']+rva;raw=m['read'](at,1);m['put'](at,bytes([raw[0]^255]))
    with pytest.raises(ValueError,match='native code changed'):decode(m)
