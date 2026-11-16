"""One live union capture comparing explicit historical team windows."""
from collections import OrderedDict, defaultdict
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
import math
import secrets
import threading
import time

from .match_data_query import capture_epoch, capture_live
from .live_match_player_ranking import rank_capture

PLAYER_METRICS = ('shots','shots_on_target','goals','assists','key_passes','open_play_key_passes',
                  'chances_created','progressive_passes','passes_attempted','passes_completed')
CONTEXT_METRICS = ('shots','shots_on_target','expected_goals','expected_assists',
                   'key_passes','open_play_key_passes','chances_created','progressive_passes')
TEAM_METRICS = ('shots','shots_on_target','expected_goals','passes_attempted')
PAGE_SIZE = 100
MAX_FIXTURES = 512


def _number(value):
    return type(value) in (int,float) and math.isfinite(value) and value >= 0


def _summary(values):
    known = [v for v in values if _number(v)]
    complete = len(known) == len(values) and bool(values)
    total = sum(known)
    return {'total':total if complete else None,'per_match':total/len(values) if complete else None,
            'known_total':total if known else None,'known_matches':len(known),
            'missing_matches':len(values)-len(known)}


def _merged_intervals(windows):
    merged = []
    for first,last in sorted(windows):
        if merged and date.fromisoformat(first) <= date.fromisoformat(merged[-1][1])+timedelta(days=1):
            merged[-1] = (merged[-1][0],max(last,merged[-1][1]))
        else:
            merged.append((first,last))
    return merged


def capture_windows(bridge, session_id, team_id, competition_id, windows, player_metric):
    """Reuse guarded capture windows; retain only compact comparison inputs."""
    from .export_live_matches import capture_scope
    counters = set(CONTEXT_METRICS) | {player_metric}
    fields = {'fixture_key','side_index','team_index_word','person_index_word',
              'canonical_person_id','person_name','minutes','appearance_kind'} | counters
    def batch(b,s,refs):
        result = capture_live(b,s,refs,include_players=True)
        return {'capture':{'save':result['capture']['save'], 'fixtures':[
            {'native_match_key':item['native_match_key'],'fixture':{
                'date':item['fixture']['date'],
                **{side:{key:(item['fixture'].get(side) or {}).get(key) for key in ('native_id','database_index','owner')}
                   for side in ('home_team','away_team')}},
             'source_state':(item.get('source') or {}).get('state'),
             'raw_sha256':(item.get('source') or {}).get('raw_sha256')}
            for item in result['capture']['fixtures']], 'source_kind':result['capture'].get('source_kind')},
            'retained_players':[{key:row.get(key) for key in fields} for row in result.get('retained_players',[])],
            'team_totals':{'records':[{'result_key':r['result_key'],'teams':[
                {key:t.get(key) for key in ('side_index','team_index',*TEAM_METRICS)} for t in r['teams']]}
                for r in result.get('team_totals',{}).get('records',[])]},'raw_frames':[]}
    combined = {'capture':{'fixtures':[]},'retained_players':[],'team_totals':{'records':[]},'raw_frames':[]}
    scopes = []
    pages = 0
    for first,last in _merged_intervals(windows):
        def query(sid,**args):
            nonlocal pages
            pages += 1
            if pages > 2048:
                raise ValueError('Comparison fixture page budget exceeded; narrow windows')
            return bridge.find_fixtures(sid,selector_prefilter=True,**args)
        remaining = MAX_FIXTURES-len(combined['capture']['fixtures'])
        result = capture_scope(bridge,session_id,team_id,first,last,competition_id,
                               capture=batch,fixture_query=query,max_matches=remaining,
                               capture_batch_size=16,max_pages=2048)
        scopes.append({key:value for key,value in result['capture'].items() if key!='fixtures'})
        combined['capture'].setdefault('save',result['capture']['save'])
        combined['capture']['fixtures'].extend(result['capture']['fixtures'])
        combined['retained_players'].extend(result['retained_players'])
        combined['team_totals']['records'].extend(result['team_totals']['records'])
    combined['capture']['union_scopes'] = scopes
    return combined


def _partition(captured, first, last):
    fixtures = [item for item in captured['capture']['fixtures'] if first<=item['fixture']['date']<=last]
    keys = {item['native_match_key'] for item in fixtures}
    return {'capture':{**captured['capture'],'fixtures':fixtures},
            'retained_players':[r for r in captured.get('retained_players',[]) if r.get('fixture_key') in keys],
            'team_totals':{'records':[r for r in captured.get('team_totals',{}).get('records',[]) if r['result_key'] in keys]}}


def _key(row):
    return (row['person_native_id'],row['historical_team_native_id'],row['historical_team_database_index'])


def _team_summary(captured, team_id, minimum_matches):
    totals = {}
    for record in captured.get('team_totals',{}).get('records',[]):
        for row in record['teams']:
            key = (record['result_key'],row['side_index'])
            if key in totals and totals[key] != row:
                raise ValueError('Contradictory duplicate team totals in comparison')
            totals[key] = row
    fixture_by_key={item['native_match_key']:item['fixture'] for item in captured['capture']['fixtures']}
    for (key,side),row in list(totals.items()):
        if key not in fixture_by_key or type(side) is not int or side not in (0,1):
            raise ValueError('Team total is outside the selected fixture sides')
        expected=(fixture_by_key[key].get(('home_team','away_team')[side]) or {}).get('database_index')
        if expected is None:
            totals[(key,side)]={}
        elif row.get('team_index')!=expected:
            raise ValueError('Team total TEAM index differs from canonical fixture side')
    players = defaultdict(list)
    for row in captured.get('retained_players',[]):
        players[(row['fixture_key'],row['side_index'])].append(row)
    groups = defaultdict(list)
    verified = 0
    for item in captured['capture']['fixtures']:
        key = item['native_match_key'];f = item['fixture']
        own = [side for side,field in enumerate(('home_team','away_team')) if (f.get(field) or {}).get('native_id')==team_id]
        if len(own)!=1:
            raise ValueError('Selected team does not uniquely match fixture sides')
        side=own[0];team=f[('home_team','away_team')[side]];index=team.get('database_index')
        row={'date':f['date'],'key':key,'side':side,'for':totals.get((key,side),{}),'against':totals.get((key,1-side),{}),'players':players[(key,side)]}
        for which in (side,1-side):
            ps=players[(key,which)];ts=totals.get((key,which),{})
            for field in ('shots','shots_on_target','expected_goals'):
                if ps and all(_number(p.get(field)) for p in ps) and _number(ts.get(field)):
                    value=sum(p[field] for p in ps)
                    if abs(value-ts[field])>1e-4*max(1,value):
                        raise ValueError('Player/team chance counters do not reconcile')
            if ps and ts and all(_number(ts.get(field)) and all(_number(p.get(field)) for p in ps) for field in ('shots','shots_on_target','expected_goals')):
                verified+=1
        groups[index].append(row)
    result=[]
    for index,rows in sorted(groups.items(),key=lambda item:(item[0] is None,item[0])):
        directions={}
        for direction in ('for','against'):
            metrics={field:_summary([r[direction].get(field) for r in rows]) for field in TEAM_METRICS}
            xg,shots=metrics['expected_goals']['total'],metrics['shots']['total']
            metrics['expected_goals_per_shot']=xg/shots if xg is not None and shots else None
            directions[direction]=metrics
        creators={}
        for field in ('key_passes','open_play_key_passes','chances_created','progressive_passes','expected_assists'):
            values=[sum(p[field] for p in row['players']) if row['players'] and all(_number(p.get(field)) for p in row['players']) else None for row in rows]
            creators[field]=_summary(values)
            numerator=creators[field]['total'];denominator=directions['for']['passes_attempted']['total']
            creators[field]['per_100_pass_attempts']=100*numerator/denominator if numerator is not None and denominator else None
        result.append({'historical_team_native_id':team_id,'historical_team_database_index':index,
                       'observed_matches':len(rows),'home_matches':sum(r['side']==0 for r in rows),'away_matches':sum(r['side']==1 for r in rows),'sample_state':'small_observed_sample' if len(rows)<minimum_matches else 'minimum_observed_sample_met',
                       'chance_creation':directions,'creation_context':creators,
                       'missing_team_stat_matches':sum(not row['for'] or not row['against'] for row in rows),
                       'missing_player_side_matches':sum(not row['players'] for row in rows)})
    count=len(captured['capture']['fixtures'])
    return {'observed_fixtures':count,'sample_state':'no_observed_results' if not count else 'small_observed_sample' if count<minimum_matches else 'minimum_observed_sample_met','teams':result,'verified_player_team_sides':verified}


def _deduplicate(captured):
    fixtures={}
    for item in captured['capture']['fixtures']:
        key=item['native_match_key']
        if key in fixtures and fixtures[key]!=item:
            raise ValueError('Contradictory duplicate fixture in window capture')
        fixtures[key]=item
    players={}
    for row in captured.get('retained_players',[]):
        key=(row.get('fixture_key'),row.get('side_index'),row.get('person_index_word'))
        if key[0] not in fixtures or type(key[1]) is not int or key[1] not in (0,1):
            raise ValueError('Player is outside the selected fixture sides')
        expected=(fixtures[key[0]]['fixture'].get(('home_team','away_team')[key[1]]) or {}).get('database_index')
        if expected is not None and row.get('team_index_word')!=expected:
            raise ValueError('Player TEAM word differs from canonical fixture side')
        if key in players and players[key]!=row:
            raise ValueError('Contradictory duplicate player in window capture')
        players[key]=row
    return {**captured,'capture':{**captured['capture'],'fixtures':list(fixtures.values())},'retained_players':list(players.values())}


def compare_capture(captured, team_id, baseline, comparison, metric, baseline_minimum, comparison_minimum, minimum_team_matches, direction):
    captured=_deduplicate(captured)
    partitions={'baseline':_partition(captured,*baseline),'comparison':_partition(captured,*comparison)}
    rankings={name:rank_capture(partitions[name],metric,'per90',cutoff,team_id)
              for name,cutoff in (('baseline',baseline_minimum),('comparison',comparison_minimum))}
    eligible={name:{_key(row):(value,row) for value,row in r['ranked']} for name,r in rankings.items()}
    excluded={name:{_key(row):row for row in r['excluded']} for name,r in rankings.items()}
    observed={name:set(eligible[name])|set(excluded[name]) for name in rankings}
    returning=observed['baseline']&observed['comparison'];qualified=[];unclassified=[]
    for identity in sorted(returning):
        if any(identity not in eligible[name] for name in rankings):
            reasons={name:excluded[name][identity]['reasons'] for name in rankings if identity in excluded[name]}
            uncertain=any(excluded[name][identity]['classification']=='uncertain' for name in reasons)
            unclassified.append({'person_native_id':identity[0],'historical_team_native_id':identity[1],
                                 'historical_team_database_index':identity[2],'classification':'uncertain' if uncertain else 'defined_exclusion','reasons':reasons})
            continue
        base_value,base=eligible['baseline'][identity];new_value,new=eligible['comparison'][identity]
        delta=new_value-base_value
        def period(row):
            return {'observed_total':row['observed_total'],'minutes':row['minutes'],'stored_match_rows':row['stored_match_rows'],
                    'per90':row['value'],'exact_per90':row['exact_value'],'rank_among_window_qualifiers':row['rank']}
        qualified.append((delta,{'person_native_id':identity[0],'person_name':new['person_name'] or base['person_name'],
                                'historical_team_native_id':identity[1],'historical_team_database_index':identity[2],
                                'baseline':period(base),'comparison':period(new),'change_per90':float(delta),
                                'exact_change':{'numerator':delta.numerator,'denominator':delta.denominator}}))
    qualified.sort(key=lambda item:((item[0] if direction=='decrease' else -item[0]),item[1]['person_native_id'],item[1]['historical_team_database_index']))
    last=None;rank=None
    for index,(value,row) in enumerate(qualified,1):
        if value!=last:rank,last=index,value
        row['change_rank']=rank
    overlap={f['native_match_key'] for f in partitions['baseline']['capture']['fixtures']} & {f['native_match_key'] for f in partitions['comparison']['capture']['fixtures']}
    summaries={name:_team_summary(value,team_id,minimum_team_matches) for name,value in partitions.items()}
    team_changes=[]
    by_team={name:{r['historical_team_database_index']:r for r in summary['teams']} for name,summary in summaries.items()}
    for index in sorted(by_team['baseline'].keys() & by_team['comparison'].keys(),key=lambda value:(value is None,value)):
        before,after=by_team['baseline'][index],by_team['comparison'][index]
        changes={}
        for side in ('for','against'):
            changes[side]={}
            for field in TEAM_METRICS:
                a,b=before['chance_creation'][side][field]['per_match'],after['chance_creation'][side][field]['per_match']
                changes[side][field+'_per_match']=b-a if a is not None and b is not None else None
            a,b=before['chance_creation'][side]['expected_goals_per_shot'],after['chance_creation'][side]['expected_goals_per_shot']
            changes[side]['expected_goals_per_shot']=b-a if a is not None and b is not None else None
        team_changes.append({'historical_team_native_id':team_id,'historical_team_database_index':index,'comparison_minus_baseline':changes})
    missing_team_metrics=any(metric['missing_matches'] for window in summaries.values() for team in window['teams'] for side in ('for','against') for key,metric in team['chance_creation'][side].items() if key!='expected_goals_per_shot')
    missing_context_metrics=any(metric['missing_matches'] for window in summaries.values() for team in window['teams'] for metric in team['creation_context'].values())
    partial=missing_team_metrics or missing_context_metrics or any(r['counts']['unclassified_groups'] or r['counts']['unresolved_identity_rows'] or r['counts']['unresolved_fixture_sides'] or any(t['missing_player_sides'] for t in r['team_coverage']) for r in rankings.values())
    return {'state':'available_partial' if partial else 'available_observed_comparison','ranked':qualified,'team_windows':summaries,'team_changes':team_changes,
            'counts':{'observed_returning_groups':len(returning),'qualifying_returning_groups':len(qualified),
                      'defined_excluded_returners':sum(r['classification']=='defined_exclusion' for r in unclassified),
                      'uncertain_returners':sum(r['classification']=='uncertain' for r in unclassified),
                      'baseline_only_groups':len(observed['baseline']-observed['comparison']),
                      'comparison_only_groups':len(observed['comparison']-observed['baseline']),
                      'overlapping_fixtures':len(overlap),
                      'windows_disjoint':max(baseline[0],comparison[0])>min(baseline[1],comparison[1]),
                      'observed_fixture_sets_disjoint':not overlap},
            'returner_exclusions':unclassified[:100],
            'window_player_coverage':{name:{key:value for key,value in r.items() if key not in ('ranked','excluded','unclassified_groups','unresolved_identity_examples','unresolved_fixture_side_examples')} for name,r in rankings.items()}}


class LiveMatchWindowComparisons:
    def __init__(self,capture=None,epoch=None):
        self.capture=capture or capture_windows;self.epoch=epoch or capture_epoch
        self.pages=OrderedDict();self.lock=threading.RLock()

    def compare(self,bridge,session_id,team_native_id,competition_native_id,baseline_from,baseline_to,comparison_from,comparison_to,
                player_metric='open_play_key_passes',baseline_minimum_minutes=450,comparison_minimum_minutes=450,
                minimum_team_matches=5,sort_direction='decrease',limit=10,cursor=None):
        for value in (baseline_from,baseline_to,comparison_from,comparison_to):
            if not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value:raise ValueError('Dates must use canonical YYYY-MM-DD')
        if baseline_from>baseline_to or comparison_from>comparison_to:raise ValueError('Date bounds are reversed')
        if player_metric not in PLAYER_METRICS:raise ValueError('Unsupported chance-creation player metric')
        if sort_direction not in ('increase','decrease'):raise ValueError('Unsupported change sort direction')
        for value in (team_native_id,competition_native_id):
            if type(value) is not int or not 1<=value<=2**32-1:raise ValueError('Select positive native team/competition IDs')
        for value in (baseline_minimum_minutes,comparison_minimum_minutes):
            if type(value) is not int or not 0<=value<=1000000:raise ValueError('Minute thresholds must be 0–1000000')
        if type(minimum_team_matches) is not int or not 1<=minimum_team_matches<=512:raise ValueError('minimum_team_matches must be 1–512')
        if type(limit) is not int or not 1<=limit<=100:raise ValueError('limit must be 1–100')
        selectors=(session_id,team_native_id,competition_native_id,baseline_from,baseline_to,comparison_from,comparison_to,player_metric,baseline_minimum_minutes,comparison_minimum_minutes,minimum_team_matches,sort_direction,limit)
        with self.lock:
            now=time.monotonic()
            for token in list(self.pages):
                if now-self.pages[token]['created']>300:del self.pages[token]
            if cursor is not None:
                snapshot=self.pages.get(cursor)
                if snapshot is None or snapshot['selectors']!=selectors:raise ValueError('Expired comparison cursor or changed selectors')
                if self.epoch(bridge,session_id)!=snapshot['epoch']:raise ValueError('Career/load epoch changed; start a fresh comparison')
                offset=snapshot['offset']
            else:
                epoch=self.epoch(bridge,session_id);first=bridge.get_save(session_id)['save']
                if max(baseline_to,comparison_to)>first['current_date']:raise ValueError('Comparison windows exceed active career date')
                captured=self.capture(bridge,session_id,team_native_id,competition_native_id,[(baseline_from,baseline_to),(comparison_from,comparison_to)],player_metric)
                if self.epoch(bridge,session_id)!=epoch:raise ValueError('Career/load epoch changed during comparison')
                report=compare_capture(captured,team_native_id,(baseline_from,baseline_to),(comparison_from,comparison_to),player_metric,baseline_minimum_minutes,comparison_minimum_minutes,minimum_team_matches,sort_direction)
                from .live_crossing_report import _enumeration
                scope_enumeration=[]
                for source in captured['capture'].get('union_scopes',[]):
                    scope_selectors=source.get('selectors',{})
                    enumeration=_enumeration({'capture':source},scope_selectors['date_from'],scope_selectors['date_to'])
                    scope_enumeration.append(enumeration)
                if any(row['state']!='complete_resident_groups' for row in scope_enumeration):
                    report['state']='available_partial'
                report['enumeration']=scope_enumeration
                ranked=report.pop('ranked');cutoff=ranked[min(limit,len(ranked))-1][0] if ranked else None
                rows=[row for value,row in ranked if (value<=cutoff if sort_direction=='decrease' else value>=cutoff)] if ranked else []
                last=bridge.get_save(session_id)['save']
                if self.epoch(bridge,session_id)!=epoch:raise ValueError('Career/load epoch changed before returning comparison')
                snapshot={'selectors':selectors,'epoch':epoch,'created':time.monotonic(),'rows':rows,
                          'capture_id':secrets.token_urlsafe(16),'observed_at':datetime.now(timezone.utc).isoformat(),
                          'active_save_first':first,'active_save_last':last,'source_scopes':captured['capture'].get('union_scopes',[]),
                          'maximum_selected_fixtures':MAX_FIXTURES,
                          'applied_thresholds':{'baseline_minutes':baseline_minimum_minutes,'comparison_minutes':comparison_minimum_minutes,'minimum_team_matches_flag':minimum_team_matches},
                          'window_dates':{'baseline':[baseline_from,baseline_to],'comparison':[comparison_from,comparison_to]},
                          'player_metric':player_metric,'change_direction':sort_direction,**report}
                offset=0
            end=offset+PAGE_SIZE;next_cursor=None
            if end<len(snapshot['rows']):
                next_cursor=secrets.token_urlsafe(24);self.pages[next_cursor]={**snapshot,'offset':end}
                while len(self.pages)>32:self.pages.popitem(last=False)
            return {key:value for key,value in snapshot.items() if key not in ('selectors','epoch','created','rows','offset')} | {
                'rows':snapshot['rows'][offset:end],'next_cursor':next_cursor,'selected_with_cutoff_ties':len(snapshot['rows']),
                'interpretation_limits':['Different window lengths, venue/opponent mixtures and game states are not statistically adjusted.','Minimum sample flags are count thresholds, not confidence intervals.'],
                'source_kind':'active_running_session_only','disk_capture_fallback':False,'atomic':False,
                'ranking_policy':'Exact comparison-minus-baseline per90 differences; competition ranks1,1,3, complete cutoff ties across100-row cached pages.',
                'claim':'Descriptive available-result comparison, not causal tactics, current roster/role, match completion or season completeness. One-window-only players are not assigned zero rates.'}
