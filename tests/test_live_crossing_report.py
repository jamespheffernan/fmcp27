import pytest
from fm_live_mcp.live_crossing_report import LiveCrossingReports

class Bridge:
    def get_save(self, sid):return {'save': {'current_date': '2030-11-02'}}
    def get_fixture(self, sid, ref):return {'fixture': {'date': '2030-11-02', 'home_team': {'native_id': 688}, 'away_team': {'native_id': 713}, 'competition': {'native_id': 11}}}

def packet():
    f={'date':'2030-10-26','home_team':{'native_id':1,'database_index':1,'owner':{'name':'Other'}},'away_team':{'native_id':713,'database_index':570,'owner':{'name':'Southampton'}},'competition':{'native_id':11,'name':'PL'},'scores':{'final_score':{'home':0,'away':0}}}
    return {'capture': {'save':{'current_date':'2030-11-02'},'fixtures':[{'fixture':f,'native_match_key':1}],'fixture_coverage':{'years':[{'year':2030,'all_groups_materialized':True}]},'completed_windows':1,'pages':1},'team_totals':{'records':[{'result_key':1,'teams':[{'side_index':1,'team_index':570,'crosses_attempted':10,'crosses_completed':2,'crossing_counts_state':'native_aggregate_available'}]}]},'retained_players':[]}

def test_one_full_capture_anchor_venue_and_missingness():
    calls=[]
    def capture(*args,**kwargs):calls.append(args[2:]);return packet()
    r=LiveCrossingReports(capture,lambda *_:1).report(Bridge(),'s',713,'2030-08-01','2030-11-01',fixture_ref='f',venue='matchup')
    assert calls==[(None,'2030-08-01','2030-11-01',11,False,True)]
    assert r['report']['scope']['venue']=='away'
    assert r['report']['selected_teams'][0]['crosses_for']['attempts']==10
    assert not r['disk_capture_fallback']
    assert r['report']['league_delivery_leaders']['state']=='unavailable_missing_player_sides'

def test_reload_rejects_report():
    epoch=[1]
    def capture(*a,**k):epoch[0]=2;return packet()
    with pytest.raises(ValueError,match='epoch'):
        LiveCrossingReports(capture,lambda *_:epoch[0]).report(Bridge(),'s',713,'2030-08-01','2030-11-01',11)

def test_unloaded_groups_remain_explicit():
    def capture(*a,**k):
        p=packet();p['capture']['fixture_coverage']['years'][0]['all_groups_materialized']=False;return p
    r=LiveCrossingReports(capture,lambda *_:1).report(Bridge(),'s',713,'2030-08-01','2030-11-01',11)
    assert r['state']=='available_partial'
    assert r['enumeration']['unavailable_or_unmaterialized_years']==[2030]

def test_future_bounds_fail_before_any_capture():
    calls=[]
    with pytest.raises(ValueError,match='active career date'):
        LiveCrossingReports(lambda *a,**k:calls.append(1),lambda *_:1).report(Bridge(),'s',713,'2030-08-01','2030-11-03',11)
    assert not calls

def test_rotating_reference_tokens_do_not_change_anchor():
    class Rotating(Bridge):
        counter=0
        def get_fixture(self,*args):
            row=super().get_fixture(*args);self.counter+=1;row['fixture']['competition']['competition_ref']=str(self.counter);return row
    assert LiveCrossingReports(lambda *a,**k:packet(),lambda *_:1).report(Rotating(),'s',713,'2030-08-01','2030-11-01',fixture_ref='f',venue='matchup')['state']=='available'

def test_changed_anchor_rejects_even_same_load_epoch():
    class Changed(Bridge):
        counter=0
        def get_fixture(self,*args):
            row=super().get_fixture(*args);self.counter+=1;row['fixture']['date']='2030-11-02'if self.counter==1 else'2030-11-03';return row
    with pytest.raises(ValueError,match='matchup identity'):
        LiveCrossingReports(lambda *a,**k:packet(),lambda *_:1).report(Changed(),'s',713,'2030-08-01','2030-11-01',fixture_ref='f')

def test_reference_expiry_rechecks_unique_live_matchup_without_fallback():
    class Expired(Bridge):
        calls=0
        def get_fixture(self,sid,ref):
            self.calls+=1
            if self.calls==2:raise ValueError('Resident fixture inventory changed')
            return super().get_fixture(sid,ref)
        def find_fixtures(self,sid,**selectors):
            row=super().get_fixture(sid,'fresh')['fixture'];row['fixture_ref']='fresh'
            return {'fixtures':[row],'next_cursor':None}
    r=LiveCrossingReports(lambda *a,**k:packet(),lambda *_:1).report(Expired(),'s',713,'2030-08-01','2030-11-01',fixture_ref='f')
    assert r['matchup']['date']=='2030-11-02'
    assert not r['disk_capture_fallback']

def test_missing_backing_is_partial_and_retains_exact_missing_keys():
    def capture(*a,**k):
        p=packet();p['team_totals']['records']=[];return p
    r=LiveCrossingReports(capture,lambda *_:1).report(Bridge(),'s',713,'2030-08-01','2030-11-01',11)
    assert r['state']=='available_partial'
    assert r['capture_counts']['missing_backing_keys']==[1]
    assert r['report']['selected_teams'][0]['crosses_for']['attempts'] is None


def test_tool_discovery_requires_active_session_and_has_no_file_inputs():
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.live_crossing_tools import register_live_crossing_tools
    async def check():
        m=FastMCP('Live crossing test');register_live_crossing_tools(m,Bridge())
        tool,=await m.list_tools()
        assert tool.name=='fm_report_live_match_crossing'
        assert tool.outputSchema is not None and tool.outputSchema['type']=='object'
        assert 'session_id'in tool.inputSchema['required']
        assert not {'path','source_id','expected_capture_id','sql'}&tool.inputSchema['properties'].keys()
        assert tool.annotations.readOnlyHint
    asyncio.run(check())

def test_bounded_ties_are_disclosed_without_changing_capture_coverage():
    from fm_live_mcp.live_crossing_report import _bound_report
    gaps=[];r=_bound_report({'leaders':[1]*101},gaps)
    assert len(r['leaders'])==100
    assert gaps==[{'path':'report.leaders','total_rows':101,'returned_rows':100,'cutoff_ties_may_be_truncated':True}]
