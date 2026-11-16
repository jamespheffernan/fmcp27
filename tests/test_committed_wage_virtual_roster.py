"""Exact native null COMMON path for canonical virtual roster entries.
Owned synthetic inputs and original disk instructions; no generation or live
zero inferred from a cache sign. Every roster pointer remains in native input.
"""
from pathlib import Path
import importlib.util,struct,sys
import pytest
from fm_live_mcp import committed_wage_spending_core as core,virtual_identity,virtual,world,players
from test_committed_wage_spending_core import Graph,BASE,image


def add_virtual(g,cache_index=-1,aliases=1):
    primary=g.alloc();g.put(primary,'<Q',BASE+world.TYPES['virtual_player'][0]);g.put(primary+8,'<i',0);g.put(primary+0x14,'<h',cache_index);g.put(primary+0x20,'<QIII',BASE+virtual_identity.PERSON_RVA,1,10001,10001)
    g.table('people',[g.person,primary+0x20]);g.vector(g.team+0x38,[g.primary]+[primary]*aliases);return primary


@pytest.mark.parametrize('cache',[-1,0,32767])
def test_original_native_null_getter_visits_virtual_without_cache_or_generation(image,monkeypatch,cache):
    g=Graph(image);v=add_virtual(g,cache);before=g.read(v,64);entry=core._ReducerCPU._instruction;visited=[];read=g.read
    def checked_read(a,n):
        assert not a<=BASE+virtual.MANAGER_ROOT<a+n,'Null COMMON path must not open generated-profile cache'
        return read(a,n)
    def observe(self,vm,pc,size,user):
        if pc==self.base+0xca49dc:visited.append(pc)
        return entry(self,vm,pc,size,user)
    monkeypatch.setattr(core._ReducerCPU,'_instruction',observe)
    result=core.calculate(checked_read,BASE,image,club=g.club,selected_offers=g.selected,lifetime=lambda:('synthetic',1))
    assert visited==[BASE+0xca49dc]
    assert (result.field_818,result.field_81c,result.field_820,result.field_824,result.returned_signed32,result.roster_slots)==(0,0,1200,0,0,2)
    assert g.read(v,64)==before


def test_repeated_virtual_roster_aliases_are_not_dropped(image,monkeypatch):
    g=Graph(image);add_virtual(g,aliases=2);entry=core._ReducerCPU._instruction;visited=[]
    def observe(self,vm,pc,size,user):
        if pc==self.base+0xca49dc:visited.append(pc)
        return entry(self,vm,pc,size,user)
    monkeypatch.setattr(core._ReducerCPU,'_instruction',observe);r=g.run();assert r.roster_slots==3 and len(visited)==2 and r.field_820==1200


def test_old_core_refused_the_same_canonical_virtual_roster(image):
    p=Path(__file__).parent/'fixtures/committed-wage-core-before-virtual.py';s=importlib.util.spec_from_file_location('fm_live_mcp.reducer_before_virtual',p);old=importlib.util.module_from_spec(s);sys.modules[s.name]=old;s.loader.exec_module(old);g=Graph(image);add_virtual(g)
    with pytest.raises(old.SourceUnavailable,match='unproved roster primary specialization'):old.calculate(g.read,BASE,image,club=g.club,selected_offers=(),lifetime=lambda:('synthetic',1))
    assert g.run().roster_slots==2


@pytest.mark.parametrize('what',['primary_vbase','PERSON_slot','getter_code','PERSON_membership','PERSON_type'])
def test_invalid_virtual_binding_never_becomes_zero(image,what):
    g=Graph(image);v=add_virtual(g)
    if what=='primary_vbase':g.put(BASE+world.TYPES['virtual_player'][0]-0x18,'<q',0x28)
    elif what=='PERSON_slot':g.put(BASE+virtual_identity.PERSON_RVA+0x668,'<Q',BASE+0x181e16c)
    elif what=='getter_code':g.put(BASE+0xca49dc,'<II',0xd2800020,0xd65f03c0)
    elif what=='PERSON_membership':g.table('people',[g.person,g.person])
    else:g.put(v+0x20,'<Q',BASE+players.RVA[2])
    with pytest.raises(ValueError):g.run()


def test_late_virtual_identity_change_refuses(image):
    g=Graph(image);v=add_virtual(g);calls=0
    def life():
        nonlocal calls
        calls+=1
        if calls==2:g.put(v+0x2c,'<I',10002)
        return ('synthetic',1)
    with pytest.raises(ValueError):core.calculate(g.read,BASE,image,club=g.club,selected_offers=(),lifetime=life)
