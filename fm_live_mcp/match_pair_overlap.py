"""Source-normalized pair interval intersections over one scoped live capture."""
from collections import defaultdict
import struct

from .live_match_participation import project
from .match_entry_state import SOURCE_POLICY, fixture_player_tallies_match
from .match_scope_query import ScopedMatchQueries

_NATIVE = ('on_minute', 'off_minute', 'injury_minute', 'sent_off_minute', 'end_clock')
PLAYER_FIELDS = ['fixture_id','side_index','canonical_person_id','person_index_word','person_name',
                 'minutes','goals','appearance_kind','native_substitute_duration_flag',
                 *['native_'+k for k in _NATIVE]]
FIXTURE_FIELDS = ['fixture_id','native_match_key','date','competition_id','competition',
                  'home_team_id','away_team_id','home_team_index','away_team_index',
                  'home_team','away_team','home_score','away_score','event_state','fixture_ref','raw_json']
EVENT_FIELDS = ['fixture_id','source_index','side_code','kind_code','byte14','byte15','person_index']


def _fixture_identity(fixture, team_references):
    """Keep captured labels on every result; bind refs only to matching side identities."""
    result={key:fixture.get(key) for key in ('fixture_id','native_match_key','date','competition_id',
            'competition','fixture_ref','home_team_id','away_team_id','home_team','away_team',
            'home_score','away_score')}
    raw=fixture.get('raw_json')
    raw=raw.get('fixture',raw) if isinstance(raw,dict) else {}
    raw=raw if isinstance(raw,dict) else {}
    for side in ('home','away'):
        team=raw.get(side+'_team') or {}
        matching=(isinstance(team,dict) and type(team.get('native_id')) is int
                  and team['native_id']==fixture.get(side+'_team_id')
                  and type(team.get('database_index')) is int
                  and team['database_index']==fixture.get(side+'_team_index'))
        identity={key:team.get(key) for key in ('database_index','native_id','random_id')} if matching else None
        result[side+'_team_identity']=identity
        reference=None
        if matching:
            random_id=identity['random_id'] if identity['random_id'] is not None else identity['native_id']
            reference=team_references.get((identity['database_index'],identity['native_id'],random_id))
        result[side+'_team_ref']=reference if isinstance(reference,str) and reference else None
        result[side+'_team_ref_state']=('same_capture_fixture_identity' if result[side+'_team_ref']
                                       else 'unavailable_or_unmatched_fixture_identity')
    return result


def interval(row):
    if row is None:
        return {'state':'missing_retained_person','start':None,'stop':None,'terminal_clock':None}
    source = {key:row.get('native_'+key) for key in _NATIVE}
    flag = row.get('native_substitute_duration_flag')
    if type(flag) not in (bool,int) or flag not in (0,1):
        return {'state':'unknown_usage_source','start':None,'stop':None,'terminal_clock':None}
    if any(type(value) is not int or not 0<=value<=120 for value in source.values()):
        return {'state':'unknown_usage_source','start':None,'stop':None,'terminal_clock':None}
    source['flags5c'] = 32 if flag else 0
    normalized = project({'source':source,'minutes':row.get('minutes'),
                          'appearance_state':'unused_substitute' if flag and source['on_minute']==0 else None})
    state = normalized['participation_state']
    return {'state':state,'start':normalized['entry_minute'],'stop':normalized['exit_minute'],
            'terminal_clock':source['end_clock'],'exit_reason':normalized['exit_reason'],
            'person_id':row.get('canonical_person_id'),'name':row.get('person_name'),
            'source':source,'native_minutes':row.get('minutes')}


def _goal_context(fixture, events, players, side, start, stop, a, b, policy):
    if policy != SOURCE_POLICY:
        return {'state':'unverified_source_policy'}
    scores = [fixture.get('home_score'),fixture.get('away_score')]
    if any(type(v) is not int or v<0 for v in scores):
        return {'state':'unknown_final_score'}
    if not events and scores != [0,0] and fixture.get('event_state') in ('absent_array','not_captured'):
        return {'state':'missing_scoring_events'}
    for e in events:
        values=[e.get(k) for k in ('side_code','kind_code','byte14','byte15')]
        if (any(type(v) is not int for v in values) or values[0] not in (0,1)
                or values[1] not in (0,1,2) or not 0<=values[2]<=120 or not 0<=values[3]<=255):
            return {'state':'unknown_scoring_code_or_clock'}
    if [sum(e['side_code']==s for e in events) for s in (0,1)] != scores:
        return {'state':'score_reconciliation_failed'}
    if not fixture_player_tallies_match(events, players):
        return {'state':'fixture_player_goals_reconciliation_failed'}
    terminal = stop==a['terminal_clock']==b['terminal_clock'] and a['exit_reason']==b['exit_reason']=='end_clock'
    boundary=[];certain=[]
    for e in events:
        minute=e['byte14']
        compact={k:e[k] for k in ('source_index','side_code','kind_code','byte14','byte15')}
        if minute==start or (minute==stop and not terminal):
            boundary.append(compact)
        elif start<minute<stop or (minute==stop and terminal):
            certain.append(compact)
    lower=[sum(e['side_code']==s for e in certain) for s in (side,1-side)]
    upper=[sum(e['side_code']==s for e in certain+boundary) for s in (side,1-side)]
    return {'state':'reconciled_with_boundary_bounds' if boundary else 'reconciled',
            'goals_for_lower':lower[0],'goals_for_upper':upper[0],
            'goals_against_lower':lower[1],'goals_against_upper':upper[1],
            'ambiguous_boundary_events':boundary,'certain_scoring_events':certain,
            'terminal_stoppage_events_included':terminal,
            'exact_elapsed_stoppage_minutes':None}


def pair_overlap(rows, team_id, first_id, second_id, *, include_goals=False, source_policy=None, team_references=None):
    tables=defaultdict(list)
    for item in rows:tables[item['table']].append(item['row'])
    results=[]
    for fixture in sorted(tables['fixtures'],key=lambda r:(r.get('date') or '',r['fixture_id'])):
        side=0 if fixture.get('home_team_id')==team_id else 1 if fixture.get('away_team_id')==team_id else None
        base=_fixture_identity(fixture, team_references or {})
        base.update(selection_reason='stored_result_in_explicit_team_date_competition_scope',
                    side_index=side,overlap_minutes=None,overlap_lower=0,overlap_upper=None,
                    both_initial_participant_candidates=None)
        players=[p for p in tables['retained_players'] if p['fixture_id']==fixture['fixture_id']]
        chosen=[[p for p in players if p.get('side_index')==side and p.get('canonical_person_id')==identity]
                for identity in (first_id,second_id)]
        if side is None or any(len(group)>1 for group in chosen):
            results.append({**base,'state':'ambiguous_fixture_or_person_identity'});continue
        a,b=[interval(group[0] if group else None) for group in chosen]
        base.update(first=a,second=b)
        known='reconciled_native_minute_interval'
        if any(i['state']=='unused_substitute' for i in (a,b)):
            results.append({**base,'state':'verified_no_overlap_unused_player','overlap_minutes':0,'overlap_lower':0,'overlap_upper':0,'both_initial_participant_candidates':False});continue
        if a['state']!=known or b['state']!=known:
            possible=[i['stop']-i['start'] for i in (a,b) if i['state']==known]
            clocks={p.get('native_end_clock') for p in players if p.get('side_index')==side}
            clock=next(iter(clocks)) if len(clocks)==1 else None
            upper=min(possible) if possible else clock if type(clock) is int and 0<=clock<=120 else None
            results.append({**base,'state':'unknown_individual_interval','overlap_upper':upper});continue
        if a['terminal_clock']!=b['terminal_clock']:
            results.append({**base,'state':'inconsistent_terminal_clocks'});continue
        start=max(a['start'],b['start']);stop=min(a['stop'],b['stop']);duration=max(stop-start,0)
        base.update(state='overlap' if duration else 'verified_no_overlap_adjacent_or_disjoint',
                    overlap_start=start if duration else None,overlap_stop=stop if duration else None,
                    overlap_minutes=duration,overlap_lower=duration,overlap_upper=duration,
                    both_initial_participant_candidates=a['start']==b['start']==0)
        if include_goals and duration:
            events=[e for e in tables['events'] if e['fixture_id']==fixture['fixture_id']]
            base['scoring']=_goal_context(fixture,events,players,side,start,stop,a,b,source_policy)
        results.append(base)
    upper=None if any(r['overlap_upper'] is None for r in results) else sum(r['overlap_upper'] for r in results)
    summary_state='no_selected_retained_results' if not results else 'bounded_with_unknown_intervals' if any(r['overlap_minutes'] is None for r in results) else 'source_intersections'
    return {'state':summary_state,'selected_fixture_count':len(results),'observed_overlap_fixture_count':sum(r['state']=='overlap' for r in results),
            'known_shared_initial_fixture_count':sum(r['both_initial_participant_candidates'] is True for r in results),
            'unknown_shared_initial_fixture_count':sum(r['both_initial_participant_candidates'] is None for r in results),
            'native_overlap_minutes_lower':sum(r['overlap_lower'] for r in results),
            'native_overlap_minutes_upper':upper,'fixtures':results}


class MatchPairOverlapReports:
    def __init__(self, queries=None):
        self.queries=queries or ScopedMatchQueries()

    def report(self, bridge, session_id, team_native_id, first_person_native_id,
               second_person_native_id, date_from, date_to, competition_native_id=None, include_goals=False):
        for value in (team_native_id,first_person_native_id,second_person_native_id):
            if type(value) is not int or not 1<=value<=4294967295:raise ValueError('Canonical native IDs must be positive uint32 integers.')
        if first_person_native_id==second_person_native_id:raise ValueError('Select two different canonical PERSON IDs.')
        fields={'fixtures':FIXTURE_FIELDS,'retained_players':PLAYER_FIELDS}
        if include_goals:fields['events']=EVENT_FIELDS
        options=dict(tables=list(fields),fields=fields,limit=500)
        page=self.queries.query(bridge,session_id,team_native_id,date_from,date_to,competition_native_id,**options)
        rows=list(page['rows']);initial=page;cursor=page['next_cursor']
        while cursor:
            page=self.queries.query(bridge,session_id,team_native_id,date_from,date_to,competition_native_id,cursor=cursor,**options)
            if page['capture_id']!=initial['capture_id'] or page['captured_save']!=initial['captured_save']:
                raise ValueError('Scoped capture changed during pagination.')
            rows.extend(page['rows']);cursor=page['next_cursor']
        # Reuse refs published during this scope's fixture enumeration; no extra
        # fixture/team reads. Match all three native identity words, not names.
        team_references={}
        if getattr(bridge,'session',session_id)==session_id:
            for reference,binding in dict(getattr(bridge,'team_refs',{})).items():
                identity=binding.get('identity')
                if isinstance(identity,bytes) and len(identity)==12:
                    team_references[struct.unpack('<III',identity)]=reference
        # A concurrent attach may replace the cache after the final scoped page.
        if getattr(bridge,'session',session_id)!=session_id:
            team_references.clear()
        result=pair_overlap(rows,team_native_id,first_person_native_id,second_person_native_id,
                            include_goals=include_goals,source_policy=initial['metadata'].get('entry_state_policy'),
                            team_references=team_references)
        return {**result,'team_native_id':team_native_id,'first_person_native_id':first_person_native_id,
                'second_person_native_id':second_person_native_id,'date_from':date_from,'date_to':date_to,
                'competition_native_id':competition_native_id,'capture_id':initial['capture_id'],
                'captured_save':initial['captured_save'],'observed_at':initial['observed_at'],
                'collection_metadata':initial['metadata'],
                'limits':['Native minute-label intersection; exact elapsed/stoppage overlap is unavailable.',
                          'Missing individual rows remain unknown, not non-appearances.',
                          'Initial participant candidates do not prove tactical roles or positions.',
                          'Scoring boundaries at equal nominal minutes remain unresolved, including stoppage.',
                          'Stored result records do not establish match completion.',
                          'No full-match xG, shots or player actions allocated to overlap; no causal pairing rating.']}
