"""Synthetic lifecycle/schema controls, not a fresh current-report positive.
The actual producer reads only original captured bytes; surrounding Bridge and
report projections are test doubles to isolate final callback ordering.
"""
from historical_match_identity_fixture import historical_team_identity_contract
from contextlib import contextmanager, nullcontext
from unittest.mock import Mock

import pytest
from mcp.server.fastmcp import FastMCP
from fm_live_mcp import current_match_report as report,current_match_tools as tools,world
from test_current_player_passing import Original


def test_default_public_schema_and_strict_opt_in(monkeypatch):
    mcp=FastMCP('candidate');bridge=object();call=Mock(return_value={'test_route_only':True})
    monkeypatch.setattr(tools,'current_match_report',call);tools.register_current_match_tools(mcp,bridge)
    tool=mcp._tool_manager.get_tool('fm_get_current_match');field=tool.parameters['properties']['include_player_passing']
    assert field['type']=='boolean' and field['default'] is False
    tool.fn('sid');assert call.call_args.args==(bridge,'sid','simulation',True,False,False,False)
    tool.fn('sid',include_player_passing=True);assert call.call_args.args[-2:] == (True,False)
    for bad in [1,0,None,'yes',[],{}]:
        with pytest.raises(ValueError,match='include_player_passing must be a boolean'):
            report.current_match_report(object(),'sid',include_player_passing=bad)


def test_unbound_requested_projection_is_unavailable_and_never_zero(monkeypatch):
    source={'source_state':'inactive','reason':None,'physical_client_count':0}
    monkeypatch.setattr(report.active_match_source,'inspect_context',Mock(return_value=(source,None)))
    result=report._inspect(Mock(),0,'2030-11-25','client_snapshot',False,False,True)
    assert result['player_passing']==dict(state='unavailable',reason='unique_current_fixture_source_unavailable',rows=None)
    legacy=report._inspect(Mock(),0,'2030-11-25','client_snapshot',False)
    assert 'player_passing' not in legacy


class ExactJournalSet:
    """Same strict consumed-byte ReadSet, without page-padding source invention."""
    def __init__(self,f):
        self.inner=world.ReadSet(f.read)
        self.historical_identity_read = self.inner
    def __call__(self,*args):return self.inner(*args)
    def verify(self):self.inner.verify()


def setup(monkeypatch,callback=None):
    f=Original();sets=[];b=Mock();b.lock=nullcontext();b._player_layout.return_value=[f.base+report.players.RVA[0]]
    @contextmanager
    def scope(_, *, final_verify=None):
        yield
        if final_verify is not None:final_verify()
    b._read_scope.side_effect=scope
    b.plugin_identity=('isolated-counter-fixture',b'isolated runtime')
    b.world_identity=None;b.session='synthetic-test-only';b.process=b._current.return_value
    # This captured-counter fixture isolates report/counter lifecycle only;
    # actual Bridge/native runtime checks have separate strict publication rigs.
    monkeypatch.setattr(report.players,'verify_runtime',lambda *_:b._player_layout.return_value)
    def state(*args):
        s=ExactJournalSet(f);sets.append(s);return s,{'current_date':'2030-11-23'},None
    b._world_state.side_effect=state
    b._public_save.side_effect=lambda save: callback(f) if callback else save
    def projection(read,base,date,scope,tactics,shots,passing,statistics):
        assert passing is True
        assert statistics is False
        from fm_live_mcp.current_player_passing import inspect
        return dict(state='synthetic_context_only',player_passing=inspect(read,base,f.engine,expected_match_unique_id=f.uid))
    monkeypatch.setattr(report,'_inspect',projection)
    return f,b,sets


def test_wrapper_rechecks_real_counter_projection_after_last_callback(monkeypatch):
    f,b,sets=setup(monkeypatch)
    out=report.current_match_report(b,'synthetic-test-only',include_player_passing=True)
    assert out['state']=='synthetic_context_only' and out['player_passing']['coverage']['available_counter_rows']==40
    assert not out['player_passing']['native_timestamp_association']
    assert len(sets)==2


def test_last_callback_counter_mutation_refuses_both_attempts(monkeypatch):
    def change(f):
        at=int(f.raw()['stats_private'],16)+0xba;current=f.read(at,1)[0];f.write(at,bytes([current+1]));return {'current_date':'2030-11-23'}
    f,b,sets=setup(monkeypatch,change)
    with pytest.raises(ValueError,match='Game state changed during read; retry'):
        report.current_match_report(b,'synthetic-test-only',include_player_passing=True)
    assert len(sets)==4


def test_removed_final_recheck_causally_misses_last_callback_change(monkeypatch):
    # Local ReadSet control omits only verify#2, matching the pre-change order.
    def change(f):
        at=int(f.raw()['stats_private'],16)+0xba;f.write(at,bytes([f.read(at,1)[0]+1]));return {'current_date':'2030-11-23'}
    f,b,sets=setup(monkeypatch,change)
    original=ExactJournalSet.verify;counts={}
    def old_order(s):
        counts[id(s)]=counts.get(id(s),0)+1
        if counts[id(s)]==1:original(s)
    monkeypatch.setattr(ExactJournalSet,'verify',old_order)
    out=report.current_match_report(b,'synthetic-test-only',include_player_passing=True)
    assert len(sets)==2 and out['player_passing']['rows'][0]['passes_attempted']!=f.read(int(f.raw()['stats_private'],16)+0xba,1)[0]
    # This is an intentionally stale control, not a passing public-data example.
