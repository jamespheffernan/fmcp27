"""Scoped-query integration using real retained frames and synthetic identity labels."""
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

from fm_live_mcp import players
from fm_live_mcp.live_match_players import decode_retained_players
from fm_live_mcp.match_data_query import capture_live
from fm_live_mcp.match_scope_query import ScopedMatchQueries, column_catalog

FIXTURES=Path(__file__).parent/'fixtures'
META=json.loads((FIXTURES/'goal_crossings.json').read_text())['frames']


def test_goal_query_zero_one_four_gaps_and_player_identity_requirement(monkeypatch):
    profiles=[]
    monkeypatch.setattr('fm_live_mcp.match_data_query.capture_epoch',lambda *_:('native-epoch',))
    def backing(bridge,session,refs,*,include_players):
        profiles.append(include_players)
        records=[]
        for meta in META:
            raw=gzip.decompress((FIXTURES/f"goal_crossings_{meta['key']}.bin.gz").read_bytes())
            people={r['person_index_word']:dict(native_id=r['person_index_word']+1000000,display_name=f"Person {r['person_index_word']}") for r in decode_retained_players(raw,meta['key'])}
            records.append(dict(fixture_ref=f"ref{meta['key']}",key=meta['key'],state='available',raw=raw,
                                fixture_native={'date':meta['date'],'scores':{'final_score':dict(zip(('home','away'),meta['scoreline']))}},
                                identities={'people':people,'teams':{}}))
        return dict(save={'current_date':'2030-11-02'},source_kind='running_session_active_fd',records=records)
    monkeypatch.setattr('fm_live_mcp.live_match_backing.read_selected_matches',backing)
    def capture(bridge,session,*args,include_goal_crossings=False):
        return capture_live(bridge,session,['selected'],include_players=args[-1],include_goal_crossings=include_goal_crossings)
    bridge=SimpleNamespace(process=SimpleNamespace(version=players.VERSION))
    q=ScopedMatchQueries(capture,epoch=lambda b,s:1)
    args=dict(tables=['goal_crossings'],limit=2)
    first=q.query(bridge,'s',688,'2030-08-01','2030-10-29',**args)
    rows=first['rows'];page=first
    while page['next_cursor']:
        page=q.query(bridge,'s',688,'2030-08-01','2030-10-29',cursor=page['next_cursor'],**args)
        assert page['capture_id']==first['capture_id']
        rows+=page['rows']
    assert profiles==[True]
    assert len(rows)==14
    assert sum(r['row']['native_match_key']==128692 for r in rows)==1
    assert not any(r['row']['native_match_key']==129873 for r in rows)
    assert all(r['row']['canonical_scorer_id'] is not None for r in rows)
    assert all(r['row']['horizontal_viewpoint']=='unresolved_native_signed_axis' for r in rows)
    coverage=[r['raw']['coverage'] for r in first['metadata']['coverage'] if r['source']=='goal_crossings']
    assert len(coverage)==6
    assert sum(sum(c['unrepresented_scoreline_goals_per_side']) for c in coverage)==4
    assert sum(c['complete_scoreline_goals'] for c in coverage)==2


def test_catalog_marks_expensive_table_requirements():
    c=column_catalog()
    assert c['goal_crossings']['requires_player_identities']
    assert c['sub_entry_context']['requires_player_identities']
    assert not c['team_totals']['requires_player_identities']
    assert 'entry_minute' in c['retained_players']['columns']
    assert 'passes_attempted' in c['team_totals']['columns']


def test_scoped_trailing_entry_policy_and_participation_fields():
    from fm_live_mcp.match_entry_state import SOURCE_POLICY
    from fm_live_mcp.live_match_participation import enrich
    def source(policy):
        def capture(b,s,*args,**kwargs):
            src=dict(flags5c=32,on_minute=60,off_minute=0,injury_minute=0,sent_off_minute=0,end_clock=90)
            opponent=dict(src,flags5c=0,on_minute=0)
            retained=enrich([dict(fixture_key=1,side_index=0,person_index_word=5,canonical_person_id=123,person_name='Substitute',goals=1,minutes=30,source=src),dict(fixture_key=1,side_index=1,person_index_word=99,goals=1,minutes=90,source=opponent)])
            return dict(capture={'save':{},'entry_state_policy':policy,'fixtures':[{'fixture':{'date':'2030-10-01','home_team':{'native_id':688},'away_team':{'native_id':10},'scores':{'final_score':{'home':1,'away':1}}},'native_match_key':1,'event_array':{'state':'present_records','rows':[{'source_index':0,'side12':1,'kind13':0,'byte14':20,'byte15':0,'person_index':99},{'source_index':1,'side12':0,'kind13':0,'byte14':90,'byte15':4,'person_index':5}]}}]},retained_players=retained)
        return capture
    q=ScopedMatchQueries(source(SOURCE_POLICY),epoch=lambda b,s:1)
    out=q.query(None,'s',688,'2030-10-01','2030-10-01',tables=['sub_entry_context','retained_players'],fields={'retained_players':['canonical_person_id','entry_minute','exit_minute','participation_state']})
    context=out['rows'][0]['row']
    assert context['entry_state']=='trailing' and context['evidence_state']=='reconciled'
    assert context['personal_goals_after_entry']==1
    assert out['rows'][1]['row']['entry_minute']==60
    assert out['rows'][1]['row']['exit_minute']==90
    unknown=ScopedMatchQueries(source('different_unverified_producer'),epoch=lambda b,s:1).query(None,'s',688,'2030-10-01','2030-10-01',tables=['sub_entry_context'])
    assert unknown['rows'][0]['row']['entry_state']=='unknown'
    assert unknown['rows'][0]['row']['personal_goals_after_entry'] is None
