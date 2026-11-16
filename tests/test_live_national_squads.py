from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
import struct
import pytest
from fm_live_mcp import live_national_squads as query


class Read:
    def __call__(self,address,length):
        if address>=1000 and address<1024:return struct.pack('<Q',2000+(address-1000)*10)
        if address in (2000+0x170,2080+0x170):return struct.pack('<Q',9000)
        if address==2160+0x170:return bytes(8)
        raise AssertionError((address,length))
    def verify(self):pass


class Bridge:
    lock=nullcontext()
    world_identity='career-a'
    team_refs={}
    def __init__(self):self.team_refs={};self.database_cursors={}
    def _read_scope(self,*args):return nullcontext()
    def _current(self,*args):return SimpleNamespace(pid=10)
    def _player_layout(self,*args):return (query.players.RVA[0],)
    def _world_state(self,*args):return Read(),{'current_date':'2030-10-30'},None
    def _public_save(self,value):return value


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setattr(query.database,'table',lambda *a:{'start':1000,'count':3,'identity':('table',)})
    monkeypatch.setattr(query.teams,'_typed',lambda *a:None)
    monkeypatch.setattr(query.teams,'_identity',lambda r,a:({'database_index':(a-2000)//80,'native_id':a},b'id'))
    monkeypatch.setattr(query.geography,'record',lambda *a:{'short_name':'England','abbreviation':'ENG','native_id':765})
    def container(read,base,info,index):
        return {'database_index':index,'teams':[{'roster_count':0,'roster_state':'known_empty','team_type_label':'U23 Team'}]},[{'address':100+index,'identity':b'x','database_index':index}]
    monkeypatch.setattr(query,'read_container',container)
    return Bridge()


def test_cursor_pages_empty_results_and_binds_filters_and_epoch(source):
    first=query.find_national_teams(source,'s','No match',record_budget=1)
    assert first['containers']==[] and first['next_cursor']
    second=query.find_national_teams(source,'s','No match',record_budget=1,next_cursor=first['next_cursor'])
    assert second['start_index']==1 and second['next_index']==2
    with pytest.raises(ValueError,match='cursor'):
        query.find_national_teams(source,'s','England',record_budget=1,next_cursor=first['next_cursor'])
    source.world_identity='career-b'
    with pytest.raises(ValueError,match='cursor'):
        query.find_national_teams(source,'s','No match',record_budget=1,next_cursor=first['next_cursor'])


def test_known_empty_roster_and_unknown_nation_are_distinct(source):
    result=query.find_national_teams(source,'s','England',record_budget=3)
    assert len(result['containers'])==2
    assert result['containers'][0]['teams'][0]['roster_state']=='known_empty'
    assert result['unclassified_containers'][0]['reason']=='nation_reference_unavailable'
    assert len(source.team_refs)==2 and all(r['source']=='national'for r in source.team_refs.values())

@pytest.mark.parametrize('args',[{'record_budget':17},{'record_budget':True},{'name':''},{'nation_native_id':0}])
def test_invalid_bounds_fail_before_read(source,args):
    with pytest.raises(ValueError):query.find_national_teams(source,'s',**args)


def test_native_container_keeps_cross_owner_membership_and_empty_vectors(monkeypatch):
    class Memory:
        def __call__(self,a,n):
            return {1000:struct.pack('<Q',2000),2000+0x170:struct.pack('<Q',9000),3008:struct.pack('<I',7)}[(a)]
    monkeypatch.setattr(query.teams,'_typed',lambda *a:None)
    monkeypatch.setattr(query.teams,'_identity',lambda *a:({'database_index':0,'native_id':1},b'id'))
    monkeypatch.setattr(query.geography,'record',lambda *a:{'short_name':'Great Britain'})
    monkeypatch.setattr(query.world,'vector',lambda read,a,limit:(3000,)if a==2000+0x18 else ())
    monkeypatch.setattr(query.teams,'by_index',lambda *a:({'kind':'national_team','native_type_code':9,'owner':{'nation':{'short_name':'England'}}},{'address':3000,'owner_address':4000}))
    row,bindings=query.read_container(Memory(),0,{'start':1000},0)
    team,=row['teams']
    assert team['owner_matches_listed_container'] is False
    assert team['owner']['nation']['short_name']=='England'
    assert team['roster_count']==0 and team['gender'] is None
