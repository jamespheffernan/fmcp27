import struct

import pytest

from fm_live_mcp import awards, world
from fm_live_mcp.award_tools import find_awards, get_award
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind, database_memory
from test_players import memory
from test_world import world_memory
from test_competitions import competition_fixture
from test_geography import add_geography


@pytest.fixture
def award_memory(database_memory):
    m=add_geography(competition_fixture(database_memory))
    ti=m['allocate'](16);name=m['allocate'](len(awards.RTTI)+1)
    m['put'](name,awards.RTTI+b'\0');m['q'](ti+8,name)
    m['put'](m['base']+awards.VTABLE-16,struct.pack('<qQ',0,ti))
    m['q'](m['base']+awards.VTABLE+24,m['base']+awards.GETTER)
    addresses=[]
    for i,title in enumerate(('Golden Ball','Golden Ball',None,'')):
        a=m['allocate'](0xa0);m['q'](a,m['base']+awards.VTABLE)
        m['put'](a+8,struct.pack('<III',i,1000+i,2000+i))
        m['q'](a+0x30,m['text'](title) if title is not None else 0)
        m['q'](a+0x38,m['text']('Short')if i==0 else 0)
        if i==0:
            m['q'](a+0x50,m['geography']['continent'][0]);m['q'](a+0x58,m['competitions'][0]);m['q'](a+0x60,m['geography']['nation'][0])
        for offset,value in ((0x85,4),(0x86,2 if i==0 else 99),(0x8d,1)):
            m['put'](a+offset,struct.pack('<b',value))
        addresses.append(a)
    m['vec'](m['headers']['awards'],addresses);m['awards']=addresses
    return m


def test_definitions_and_links_are_not_winners(bridge,monkeypatch,award_memory):
    m=award_memory;bind(bridge,monkeypatch,m)
    out=find_awards(bridge,bridge.session,name='GOLDEN',max_matches=10)
    assert out['count']==2 and out['complete_table_scan']
    a,b=out['awards'];assert a['native_id']!=b['native_id']
    assert a['name']==b['name']=='Golden Ball'
    assert a['random_id']==2000
    assert a['competition']['native_id']==100 and a['nation']['native_id']==200
    assert a['continent']['name']=='Europe'
    assert a['award_period']['label']=='Of The Month'
    assert b['award_period']==dict(native_code=99,label=None,native_property='AWdr',state='unmapped')
    assert all(r['record_scope']=='award_definition'and r['winner_history']==dict(state='not_decoded',winners=None)for r in(a,b))
    assert get_award(bridge,bridge.session,a['award_ref'])['award']==a


def test_combined_selectors_and_empty_pages(bridge,monkeypatch,award_memory):
    m=award_memory;bind(bridge,monkeypatch,m)
    out=find_awards(bridge,bridge.session,competition_native_id=100,nation_native_id=200,period_code=2,recipient_type_code=1,category_code=4)
    assert out['count']==1
    assert find_awards(bridge,bridge.session,name='short')['count']==1
    page=find_awards(bridge,bridge.session,native_id=1003,record_budget=1)
    assert page['count']==0 and page['next_cursor'] and not page['complete_table_scan']
    with pytest.raises(BridgeError,match='cursor'):
        find_awards(bridge,bridge.session,native_id=1002,record_budget=1,cursor=page['next_cursor'])
    while page['next_cursor']:
        page=find_awards(bridge,bridge.session,native_id=1003,record_budget=1,cursor=page['next_cursor'])
    assert page['count']==1 and page['awards'][0]['name']==''
    allrows=find_awards(bridge,bridge.session)['awards']
    assert allrows[2]['name']is None and allrows[3]['name']==''
    assert allrows[1]['competition']is None


@pytest.mark.parametrize('fault',['award_type','rtti','getter','index','identity','table_bounds','competition_type','foreign_competition','nation_membership','field_drift'])
def test_bad_sources_fail_without_publishing(bridge,monkeypatch,award_memory,fault):
    m=award_memory;bind(bridge,monkeypatch,m);a=m['awards'][0]
    if fault=='award_type':m['q'](a,m['base']+awards.VTABLE+8)
    if fault=='rtti':m['put'](m['base']+awards.VTABLE-16,struct.pack('<q',8))
    if fault=='getter':m['q'](m['base']+awards.VTABLE+24,0)
    if fault=='index':m['put'](a+8,struct.pack('<I',9))
    if fault=='identity':m['put'](a+12,bytes(4))
    if fault=='table_bounds':m['put'](m['headers']['awards'],struct.pack('<QQQ',8192,4096,8192))
    if fault=='competition_type':m['q'](m['competitions'][0],0)
    if fault=='foreign_competition':m['q'](a+0x58,m['competitions'][0]+8)
    if fault=='nation_membership':m['vec'](m['headers']['nations'],[m['geography']['nation'][1]])
    if fault=='field_drift':
        original=m['read'];n=0
        def drift(address,length):
            nonlocal n
            raw=original(address,length)
            if address==a+0x86:
                n+=1
                if n>1:return bytes([3])
            return raw
        monkeypatch.setattr(bridge,'_read_memory',lambda p,a,n:drift(a,n))
    with pytest.raises(BridgeError):find_awards(bridge,bridge.session)
    assert not bridge.geographic_refs


def test_stale_references_and_detach(bridge,monkeypatch,award_memory):
    m=award_memory;bind(bridge,monkeypatch,m)
    ref=find_awards(bridge,bridge.session,max_matches=1)['awards'][0]['award_ref']
    m['put'](m['awards'][0]+16,struct.pack('<I',999))
    with pytest.raises(BridgeError,match='identity'):get_award(bridge,bridge.session,ref)
    assert ref not in bridge.geographic_refs
    with pytest.raises(BridgeError,match='expired'):get_award(bridge,bridge.session,'fake')


@pytest.mark.parametrize('args',[dict(max_matches=True),dict(record_budget=1001),dict(native_id=0),dict(period_code=128),dict(name=''),dict(name='A\n')])
def test_validate_before_read(bridge,args):
    with pytest.raises(BridgeError):find_awards(bridge,bridge.session,**args)


def test_real_premier_league_raw_controls():
    import json
    from pathlib import Path
    control=json.loads((Path(__file__).parent/'fixtures/awards_b162.json').read_text())
    assert control['total_count']==3883 and len(control['selected_controls'])==15
    byid={c['row']['native_id']:c for c in control['selected_controls']}
    assert byid[102418]['row']['name']=='Premier League Player of the Month'
    assert byid[102426]['row']['award_period']['label']=='Of The Week'
    assert byid[150767]['row']['award_category']['label']=='Top Goalscorer'
    assert byid[2000463068]['row']['award_category']['label']=='Most Assists'
    for c in control['selected_controls']:
        row=c['row'];raw=bytes.fromhex(c['raw8_97_hex'])
        assert struct.unpack_from('<III',raw)==(row['database_index'],row['native_id'],row['random_id'])
        for offset,field,prop in [(0x85,'award_category','AWty'),(0x86,'award_period','AWdr'),(0x8d,'recipient_type','AWrt')]:
            assert awards.classification(struct.unpack_from('<b',raw,offset-8)[0],prop)==row[field]
        assert row['competition']['native_id']==11
        assert row['winner_history']==dict(state='not_decoded',winners=None)
