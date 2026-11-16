import asyncio
from contextlib import nullcontext
import struct

import pytest
from fm_live_mcp import league_player_ranking as totals, competition_scorers as source, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_competition_scorers import census, Memory


def row(index=0,apps=12,subs=3,minutes=1080,goals=4):
    raw=bytearray(172);struct.pack_into('<II',raw,0,index,545)
    raw[10]=apps;raw[149]=subs;raw[12]=goals;struct.pack_into('<i',raw,52,minutes)
    return bytes(raw)


def candidate(index=0,**kwargs):
    return dict(person_index=index,source_ordinal=index,**totals.decode_row(row(index,**kwargs)))


@pytest.fixture
def ranking_census(census,monkeypatch):
    c=census;m=c['memory']
    for rva,raw in totals.NATIVE_SPANS:m.put(c['base']+rva,raw)
    m.put(0x50000,row(0));m.put(0x500AC,row(1))
    def team(*args,**kwargs):
        assert args[2]==545
        return {'database_index':545,'native_id':688},{}
    monkeypatch.setattr(totals.teams,'by_index',team)
    return c


def collect(c):return totals.collect(c['memory'].read,c['base'],{})


def test_source_preserves_regular_and_combined_and_four_aligned_rows(ranking_census):
    coverage,rows=collect(ranking_census)
    assert coverage['complete_resident_pool'] and coverage['physical_count']==2
    assert [r['starting_appearances']for r in rows]==[9,9]
    assert rows[1]['_identity']['record_kind']=='player_staff'
    assert coverage['starting_appearances_source']['native_English_resource_key']==554500
    assert coverage['primary_League_category_used']is False
    assert coverage['whole_completed_season_verified']is False


def test_raw_negative_wrapping_and_negative_minutes_are_never_clamped():
    r=totals.decode_row(row(apps=255,subs=0,minutes=-2147483648,goals=255))
    assert r['starting_appearances']==-1 and r['minutes']==-2147483648 and r['goals']==255
    result=totals.rank([dict(person_index=1,source_ordinal=0,**r)],minutes_over=1000)
    assert result['selected_count']==0 and result['unknown_filter_or_order_count']==1
    assert result['unknown_rows'][0]['raw']['minutes_signed32']==-2147483648
    goals=totals.rank([dict(person_index=1,source_ordinal=0,**r)],sort_by='goals')
    assert goals['selected_count']==1 and goals['anomalous_metric_row_count']==1


def test_strict_threshold_default_no_filter_and_complete_ties():
    rows=[candidate(0,minutes=1000),candidate(1,minutes=1001),candidate(2,minutes=2000)]
    assert totals.rank(rows)['qualified_known_count']==3
    r=totals.rank(rows,minutes_over=1000,limit=1)
    assert r['qualified_known_count']==2 and r['selected_count']==2
    assert r['cutoff_ties_added']==1 and [r['rank']for r in r['rows']]==[1,1]
    assert [r['person_index']for r in r['rows']]==[1,2]


@pytest.mark.parametrize('metric',totals.METRICS)
@pytest.mark.parametrize('order',['ascending','descending'])
def test_all_three_metrics_have_numeric_order_and_equal_rank(metric,order):
    rows=[candidate(0,apps=12,subs=2,minutes=1100,goals=2),candidate(1,apps=4,subs=1,minutes=30,goals=0)]
    values=[r[metric]for r in totals.rank(rows,sort_by=metric,order=order)['rows']]
    assert values==sorted(values,reverse=order=='descending')


@pytest.mark.parametrize('args',[('x','ascending',None,10),('goals','other',None,10),
    ('goals','ascending',True,10),('goals','ascending',-1,10),('goals','ascending',2**31,10),
    ('goals','ascending',None,True),('goals','ascending',None,0),('goals','ascending',None,101)])
def test_options_are_strict(args):
    with pytest.raises(ValueError):totals.options(*args)


def test_duplicate_population_and_noninteger_values_reject():
    with pytest.raises(ValueError):totals.rank([candidate(),candidate()])
    bad=candidate();bad['minutes']=True
    with pytest.raises(ValueError):totals.rank([bad])


@pytest.mark.parametrize('rva',[rva for rva,raw in totals.NATIVE_SPANS])
def test_each_getter_label_and_namespace_guard_is_required(ranking_census,rva):
    c=ranking_census;m=c['memory'];raw=m.read(c['base']+rva,1)
    m.put(c['base']+rva,bytes([raw[0]^255]))
    with pytest.raises(ValueError,match='native getter/label'):collect(c)


def test_source_empty_vs_unavailable(ranking_census):
    c=ranking_census;m=c['memory'];m.pack(c['stats']+0x1278,'<QQQ',0,0,0)
    coverage,rows=collect(c);assert coverage['source_state']=='available'and rows==[]
    m.pack(c['runtime']+0x390,'<Q',0)
    coverage,rows=collect(c);assert coverage['source_state']=='unavailable'and coverage['physical_count']is None


def test_both_collectors_respect_transport_limit_above_2048_pointer_slots(ranking_census):
    c=ranking_census;m=c['memory'];n=2050
    for i in range(n):
        ptr=0x100000+172*i;m.pack(0x40000+i*8,'<Q',ptr);m.put(ptr,row(i,goals=1))
    m.pack(c['stats']+0x1278,'<QQQ',0x40000,0x40000+n*8,0x40000+n*8)
    sizes=[]
    def limited(a,size):
        assert size<=16384;sizes.append(size);return m.read(a,size)
    coverage,rows=totals.collect(limited,c['base'],{})
    assert coverage['physical_count']==len(rows)==2050 and max(sizes)==16384
    result=totals.rank(rows,limit=1)
    assert result['selected_count']==2050 and result['cutoff_ties_added']==2049


def bind(bridge,c,monkeypatch):
    from fm_live_mcp import players
    tables=tuple(c['base']+r for r in players.RVA)
    monkeypatch.setattr(bridge,'_read_scope',lambda sid:nullcontext())
    monkeypatch.setattr(bridge,'_player_layout',lambda p:tables)
    save={'name':'Synthetic','current_date':'2030-11-13','coaches':[]}
    monkeypatch.setattr(bridge,'_world_state',lambda p,t:(world.ReadSet(c['memory'].read),save,None))
    bridge.competition_refs['comp']={'tables':tables}
    def player(read,address,tables,*args,**kwargs):
        i=0 if address==0x70000-0x388 else 1;kind='actual'if i==0 else'player_staff'
        return {'name':f'Player{i}','display_name':f'Player{i}','record_kind':kind,
                'native_identity':{'database_index':i,'native_id':100+i,'random_id':None}},('identity',i)
    monkeypatch.setattr(bridge,'_roster_player',player)
    return bridge


def test_public_paging_keeps_complete_tie_and_requires_same_pin(bridge,ranking_census,monkeypatch):
    b=bind(bridge,ranking_census,monkeypatch)
    first=b.rank_league_players(b.session,'comp',limit=1,page_size=1)
    assert first['ranking']['selected_count']==2 and first['returned_count']==1
    assert not first['returned_complete']and first['next_cursor']and first['source_pin']
    second=b.rank_league_players(b.session,'comp',limit=1,page_size=2,cursor=first['next_cursor'],source_pin=first['source_pin'])
    assert second['returned_complete']and second['next_cursor']is None
    assert [r['person_index']for r in first['rows']+second['rows']]==[0,1]
    assert all(r['rank']==1 for r in first['rows']+second['rows'])
    for options in ({'source_pin':'wrong'},{'order':'descending'}):
        with pytest.raises(BridgeError,match='expired'):
            b.rank_league_players(b.session,'comp',limit=1,cursor=first['next_cursor'],source_pin=options.get('source_pin',first['source_pin']),order=options.get('order','ascending'))


def test_unknown_ledger_is_paged_and_values_preserved(bridge,ranking_census,monkeypatch):
    c=ranking_census;c['memory'].put(0x50000,row(0,apps=255,subs=0,minutes=-1))
    b=bind(bridge,c,monkeypatch)
    first=b.rank_league_players(b.session,'comp',page_size=1)
    assert len(first['rows'])==1 and first['unknown_rows']==[]and not first['returned_complete']
    assert not first['complete_resident_counter_ranking']
    last=b.rank_league_players(b.session,'comp',page_size=1,cursor=first['next_cursor'],source_pin=first['source_pin'])
    assert last['rows']==[]and last['unknown_rows'][0]['raw']['starting_appearances_formula_signed8']==-1
    assert last['returned_complete']


def test_source_change_expires_page_without_new_refs(bridge,ranking_census,monkeypatch):
    c=ranking_census;b=bind(bridge,c,monkeypatch)
    first=b.rank_league_players(b.session,'comp',limit=1,page_size=1)
    old=dict(b.player_refs);c['memory'].put(0x5000C,b'\x09')
    with pytest.raises(BridgeError,match='source/filter changed'):
        b.rank_league_players(b.session,'comp',limit=1,cursor=first['next_cursor'],source_pin=first['source_pin'])
    assert b.player_refs==old


def test_new_readonly_tool_and_old_scorer_schema_unchanged(monkeypatch):
    from fm_live_mcp import server
    tools=asyncio.run(server.mcp.list_tools());new=next(t for t in tools if t.name=='fm_rank_league_players')
    old=next(t for t in tools if t.name=='fm_get_league_scorers')
    assert set(old.inputSchema['properties'])=={'session_id','competition_ref','limit'}
    assert new.annotations.readOnlyHint and not new.annotations.destructiveHint
    assert set(new.inputSchema['required'])=={'session_id','competition_ref'}
    assert new.inputSchema['properties']['minutes_over']['default']is None
    called=[];monkeypatch.setattr(server.bridge,'rank_league_players',lambda *a:called.append(a)or{})
    server.fm_rank_league_players('s','c');assert called[0][2:]==('starting_appearances','ascending',None,10,100,None,None)



def test_substitutes_exceeding_apps_remain_raw_and_anomalous():
    c=candidate(apps=0,subs=255)
    assert c['starting_appearances']==1 and c['raw']['starting_appearances_formula_signed8']==1
    assert c['metric_states']['starting_appearances']=='anomalous_substitutes_exceed_appearances'
    assert totals.rank([c])['unknown_filter_or_order_count']==1


def test_missing_TEAM_getter_default_does_not_become_zero_starts(ranking_census):
    c=ranking_census;c['memory'].pack(0x50004,'<I',0xffffffff)
    coverage,rows=collect(c)
    assert rows[0]['starting_appearances']is None
    assert rows[0]['raw']['starting_appearances_formula_signed8']==9
    assert rows[0]['raw']['native_getter_zero_default_for_missing_TEAM']==0
    assert totals.rank(rows)['unknown_filter_or_order_count']==1


def test_source_duplicate_rows_fail_without_partial_rank(ranking_census):
    c=ranking_census;c['memory'].pack(0x500AC,'<I',0)
    coverage,rows=collect(c)
    assert coverage['source_state']=='unavailable'and rows==[]


def test_every_unsigned_pair_matches_signed_native_formula():
    for apps in range(256):
        for subs in range(256):
            raw=row(apps=apps,subs=subs)
            value=(apps-subs)&255;value=value-256 if value&128 else value
            assert totals.decode_row(raw)['raw']['starting_appearances_formula_signed8']==value


@pytest.mark.parametrize('options',[{'limit':True},{'page_size':True},{'page_size':0},{'minutes_over':True},
    {'minutes_over':-1},{'sort_by':'initial_participants'},{'order':'random'}])
def test_public_tool_strict_invalid_options(options):
    from fm_live_mcp import server
    from mcp.server.fastmcp.exceptions import ToolError
    with pytest.raises(ToolError):
        asyncio.run(server.mcp.call_tool('fm_rank_league_players',{'session_id':'bad','competition_ref':'bad',**options}))


def test_large_complete_tie_can_be_delivered_across_bounded_pages(bridge,ranking_census,monkeypatch):
    c=ranking_census;m=c['memory'];n=1005
    for i in range(n):
        ptr=0x100000+172*i;m.pack(0x40000+i*8,'<Q',ptr);m.put(ptr,row(i))
    m.pack(c['stats']+0x1278,'<QQQ',0x40000,0x40000+n*8,0x40000+n*8)
    b=bind(bridge,c,monkeypatch);args={'limit':1,'page_size':100};indices=[];pins=set()
    for page_index in range(11):
        result=b.rank_league_players(b.session,'comp',**args)
        assert result['ranking']['selected_count']==1005 and result['ranking']['cutoff_ties_added']==1004
        assert result['returned_count']<=100 and result['ranking']['cutoff_ties_complete']
        indices.extend(row['person_index']for row in result['rows']);pins.add(result['source_pin'])
        if result['next_cursor']is None:
            assert result['returned_complete']and page_index==10;break
        assert not result['returned_complete']
        args.update(cursor=result['next_cursor'],source_pin=result['source_pin'])
    assert indices==list(range(n))and len(pins)==1
