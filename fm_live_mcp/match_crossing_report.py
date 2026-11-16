"""Read-only crossing comparisons over an explicitly scoped .91 SQLite export."""
import argparse
from collections import defaultdict
from datetime import date
from fractions import Fraction
import json
from pathlib import Path
import sqlite3

VENUES = {'all': None, 'home': 0, 'away': 1}
PLAYER_COLUMNS = ('crosses_attempted', 'crosses_completed', 'open_play_crosses_attempted', 'open_play_crosses_completed')

# Identity comes from the historical fixture side, never the player's current club.
SIDES = '''WITH sides AS (
 SELECT fixture_id,native_match_key,date,competition_id,0 side_index,
 home_team_id team_id,home_team_index team_index,home_team team_name,
 away_team_id opponent_id,away_team_index opponent_index,away_team opponent_name FROM fixtures
 UNION ALL
 SELECT fixture_id,native_match_key,date,competition_id,1,
 away_team_id,away_team_index,away_team,home_team_id,home_team_index,home_team FROM fixtures
), totals AS (
 SELECT fixture_id,side_index,count(*) source_rows,
 max(crosses_attempted) attempts,max(crosses_completed) completed,
 max(passes_attempted) passes,max(crossing_counts_state) state
 FROM team_totals GROUP BY fixture_id,side_index
), scoped AS (
 SELECT s.*,t.source_rows,t.attempts,t.completed,t.passes,t.state,
 o.source_rows opponent_source_rows,o.attempts opponent_attempts,
 o.completed opponent_completed,o.passes opponent_passes,o.state opponent_state
 FROM sides s LEFT JOIN totals t USING(fixture_id,side_index)
 LEFT JOIN totals o ON o.fixture_id=s.fixture_id AND o.side_index=1-s.side_index
 WHERE s.competition_id=:competition_id
 AND (:date_from IS NULL OR s.date>=:date_from)
 AND (:date_to IS NULL OR s.date<=:date_to)
) '''


def _known_pair(row, prefix=''):
    a,c=row[prefix+'attempts'],row[prefix+'completed']
    return (row[prefix+'source_rows']==1 and row[prefix+'state']=='native_aggregate_available'
            and type(a) is int and type(c) is int and 0<=c<=a)


def _summary(rows, prefix=''):
    known=[r for r in rows if _known_pair(r,prefix)]
    attempts=sum(r[prefix+'attempts'] for r in known)
    completed=sum(r[prefix+'completed'] for r in known)
    complete=len(known)==len(rows) and bool(rows)
    pass_rows=[r for r in known if type(r[prefix+'passes']) is int and r[prefix+'passes']>=0]
    passes=sum(r[prefix+'passes'] for r in pass_rows)
    return dict(matches=len(rows),known_matches=len(known),missing_matches=len(rows)-len(known),
                attempts=attempts if complete else None,completed=completed if complete else None,
                attempts_per_match=attempts/len(rows) if complete else None,
                completed_per_match=completed/len(rows) if complete else None,
                pooled_accuracy_percent=100*completed/attempts if complete and attempts else None,
                known_attempts=attempts if known else None,known_completed=completed if known else None,
                known_pooled_accuracy_percent=100*completed/attempts if known and attempts else None,
                known_pass_denominator_matches=len(pass_rows),
                pass_attempts=passes if complete and len(pass_rows)==len(rows) else None,
                crosses_per_100_pass_attempts=100*attempts/passes if complete and len(pass_rows)==len(rows) and passes else None)


def _rank(rows, direction, metric, numerator, denominator):
    eligible=[]
    for row in rows:
        values=row[direction]
        if values[metric] is not None:
            eligible.append((Fraction(values[numerator],values[denominator]),row))
    eligible.sort(key=lambda item:(-item[0],item[1]['team_id'],item[1]['team_index']))
    last=None;rank=None
    for index,(value,row) in enumerate(eligible,1):
        if value!=last: rank=index;last=value
        row[direction][metric+'_rank']=rank
    for row in rows:
        row[direction].setdefault(metric+'_rank',None)
        row[direction][metric+'_rank_population']=len(eligible)


def _leaderboards(rows, limit, minimum_minutes, sort_by, expected_sides):
    observed_sides={(r['fixture_id'],r['side_index']) for r in rows}
    missing_sides=expected_sides-observed_sides
    source_coverage=dict(expected_side_matches=len(expected_sides),observed_side_matches=len(observed_sides),missing_player_side_matches=len(missing_sides))
    if missing_sides:
        return dict(state='unavailable_missing_player_sides',categories={'all':[],'open_play':[]},coverage=source_coverage,
                    reason='An omitted player side has unknown individual contributions; no zero or complete-player ranking is inferred.')
    groups=defaultdict(list);unresolved=0
    for row in rows:
        if row['canonical_person_id'] is None or not row['person_name'] or row['team_id'] is None or row['team_index'] is None:
            unresolved+=1;continue
        groups[(row['team_id'],row['team_index'],row['canonical_person_id'])].append(row)
    output={};unknown_eligibility=0;category_coverage={}
    def metric(row):
        return Fraction(row['completed'],row['attempts']) if sort_by=='accuracy' else row['attempts' if sort_by=='attempted' else 'completed']
    for category,a_field,c_field in [('all','crosses_attempted','crosses_completed'),('open_play','open_play_crosses_attempted','open_play_crosses_completed')]:
        candidates=[];missing_counters=0;zero_attempts=0
        for (team_id,team_index,person_id),facts in groups.items():
            known_minutes=sum(r['minutes'] for r in facts if type(r['minutes']) is int and r['minutes']>=0)
            unknown_minutes=sum(not(type(r['minutes']) is int and r['minutes']>=0) and r['appearance_kind']!='unused_substitute' for r in facts)
            if known_minutes<minimum_minutes:
                if unknown_minutes and category=='all':unknown_eligibility+=1
                continue
            pairs=[r for r in facts if type(r[a_field]) is int and type(r[c_field]) is int and 0<=r[c_field]<=r[a_field]]
            if len(pairs)!=len(facts):
                missing_counters+=1;continue
            attempts=sum(r[a_field] for r in pairs);completed=sum(r[c_field] for r in pairs)
            if not attempts:
                zero_attempts+=1;continue
            candidates.append(dict(team_id=team_id,team_index=team_index,team_name=facts[0]['team_name'],person_id=person_id,
                                   names=sorted({r['person_name'] for r in facts}),stored_match_rows=len(facts),known_minutes=known_minutes,
                                   unknown_minutes_rows=unknown_minutes,attempts=attempts,completed=completed,
                                   pooled_accuracy_percent=100*completed/attempts,
                                   attempted_per90=90*attempts/known_minutes if known_minutes and not unknown_minutes else None,
                                   completed_per90=90*completed/known_minutes if known_minutes and not unknown_minutes else None))
        candidates.sort(key=lambda r:(-metric(r),-r['attempts'],r['team_id'],r['team_index'],r['person_id']))
        last=None;rank=None
        for index,row in enumerate(candidates,1):
            value=metric(row)
            if value!=last:rank=index;last=value
            row['rank']=rank
        cutoff=metric(candidates[min(limit,len(candidates))-1]) if candidates else None
        output[category]=[row for row in candidates if metric(row)>=cutoff] if candidates else []
        category_coverage[category]=dict(eligible_delivery_groups=len(candidates),missing_counter_groups=missing_counters,zero_attempt_groups=zero_attempts)
    return dict(state='available_observed_player_rows',categories=output,coverage={**source_coverage,'categories':category_coverage},unresolved_identity_rows=unresolved,
                unknown_minute_eligibility_groups=unknown_eligibility,
                ranking=dict(population='Named canonical player and historical-team groups with complete selected counters; excluded identities/counters are counted.',sort=sort_by,units='percent' if sort_by=='accuracy' else 'stored_crossing_count',direction='descending',
                             ties='Exact metric competition ranks1,1,3; all cutoff ties retained; attempts then native IDs only order tied rows.'))


REQUIRED_COLUMNS = {
    'fixtures':{'fixture_id','native_match_key','date','competition_id','home_team_id','home_team_index','home_team','away_team_id','away_team_index','away_team'},
    'team_totals':{'fixture_id','side_index','crosses_attempted','crosses_completed','passes_attempted','crossing_counts_state'},
    'retained_players':{'fixture_id','side_index','person_index_word','canonical_person_id','person_name','minutes','appearance_kind',*PLAYER_COLUMNS},
}


class ReportUnavailable(ValueError):
    def __init__(self, missing_fields):
        self.missing_fields=missing_fields
        super().__init__(f'Source lacks .91 report fields: {missing_fields}')


def report_requirements():
    return {table:sorted(columns) for table,columns in REQUIRED_COLUMNS.items()}


def missing_report_fields(db):
    missing={}
    for table,columns in REQUIRED_COLUMNS.items():
        actual={row[1] for row in db.execute(f'PRAGMA table_info({table})')}
        if not columns<=actual:missing[table]=sorted(columns-actual)
    return missing


def _validate(db):
    missing=missing_report_fields(db)
    if missing:raise ReportUnavailable(missing)


def report_connection(db, *, competition_id, team_id=None, team_index=None, date_from=None,date_to=None,venue='all',leaders=10,minimum_minutes=0,leader_sort='attempted'):
    """Read caller-owned SQLite; a caller transaction pins a consistent snapshot."""
    if type(competition_id) is not int or competition_id<=0:raise ValueError('competition_id must be a positive native ID')
    if venue not in VENUES:raise ValueError('venue must be all, home or away')
    if leader_sort not in ('attempted','completed','accuracy'):raise ValueError('leader_sort must be attempted, completed or accuracy')
    if type(leaders) is not int or not 1<=leaders<=100:raise ValueError('leaders must be1–100')
    if type(minimum_minutes) is not int or minimum_minutes<0:raise ValueError('minimum_minutes must be nonnegative')
    if team_id is not None and (type(team_id) is not int or team_id<=0):raise ValueError('team_id must be positive')
    if team_index is not None and (team_id is None or type(team_index) is not int or team_index<0):raise ValueError('team_index requires team_id and a nonnegative index')
    for value in (date_from,date_to):
        if value is not None and (not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value):
            raise ValueError('Dates must use canonical YYYY-MM-DD')
    if date_from and date_to and date_from>date_to:raise ValueError('date_from must precede date_to')
    _validate(db)
    params=dict(competition_id=competition_id,date_from=date_from,date_to=date_to)
    def records(sql):
        cursor=db.execute(sql,params);cols=[c[0] for c in cursor.description]
        return [dict(zip(cols,row)) for row in cursor]
    facts=records(SIDES+'SELECT * FROM scoped ORDER BY date,fixture_id,side_index')
    venue_side=VENUES[venue]
    comparison=[r for r in facts if venue_side is None or r['side_index']==venue_side]
    groups=defaultdict(list);unresolved=0
    for r in comparison:
        if r['team_id'] is None or r['team_index'] is None:unresolved+=1;continue
        groups[(r['team_id'],r['team_index'])].append(r)
    league=[dict(team_id=key[0],team_index=key[1],names=sorted({r['team_name'] for r in rows if r['team_name']}),
                 crosses_for=_summary(rows),crosses_against=_summary(rows,'opponent_')) for key,rows in sorted(groups.items())]
    for direction in ('crosses_for','crosses_against'):
        for metric,num,den in [('attempts_per_match','attempts','matches'),('completed_per_match','completed','matches'),('pooled_accuracy_percent','completed','attempts'),('crosses_per_100_pass_attempts','attempts','pass_attempts')]:
            _rank(league,direction,metric,num,den)
    selected=[r for r in comparison if team_id is not None and r['team_id']==team_id and (team_index is None or r['team_index']==team_index)]
    player_facts=records(SIDES+'''SELECT s.*,p.person_index_word,p.canonical_person_id,p.person_name,p.minutes,p.appearance_kind,
      p.crosses_attempted,p.crosses_completed,p.open_play_crosses_attempted,p.open_play_crosses_completed
      FROM scoped s JOIN retained_players p USING(fixture_id,side_index)''')
    identities=[(r['fixture_id'],r['side_index'],r['person_index_word']) for r in player_facts]
    if len(identities)!=len(set(identities)):raise ValueError('Ambiguous duplicate retained player records; report refused to double-count')
    selected_keys={(r['fixture_id'],r['side_index']) for r in selected}
    scoped_players=[r for r in player_facts if venue_side is None or r['side_index']==venue_side]
    own_players=[r for r in player_facts if (r['fixture_id'],r['side_index']) in selected_keys]
    opponent_players=[r for r in player_facts if (r['fixture_id'],1-r['side_index']) in selected_keys]
    metadata={}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone():
        allowed={'schema_version','source','source_kind','scope','selectors','save','unavailable_years','observed_save_first','observed_save_last','fixture_coverage','cross_day_atomic','identity_scope'}
        metadata={key:json.loads(value) for key,value in db.execute('SELECT key,value_json FROM metadata') if key in allowed}
    return dict(export_metadata=metadata,scope=dict(competition_id=competition_id,team_id=team_id,team_index=team_index,date_from=date_from,date_to=date_to,venue=venue,minimum_minutes=minimum_minutes,leader_sort=leader_sort),
      coverage=dict(observed_fixtures=len({r['fixture_id'] for r in facts}),comparison_team_matches=len(comparison),observed_team_groups=len(league),unresolved_side_identities=unresolved,
                    comparison_scope='Observed exported fixture subset; complete league coverage and match completion are not established.',
                    denominator_policy='Main metrics/ranks require complete known pairs. Known subtotals stay separate. Zero denominators are null.',
                    team_crossing_source='Native player-counter aggregate; not an independent serialized team counter.',
                    grouping='Historical fixture native team ID + database index; players additionally use canonical person ID. No current-club grouping.',
                    rank_policy='Rank1 is highest observed value; exact rational competition ranks1,1,3; partial metrics are unranked.'),
      league_teams=league,league_reference=dict(crosses_for=_summary(comparison),crosses_against=_summary(comparison,'opponent_')),
      selected_teams=[r for r in league if r['team_id']==team_id and (team_index is None or r['team_index']==team_index)],
      per_match=[dict(fixture_id=r['fixture_id'],native_match_key=r['native_match_key'],date=r['date'],side_index=r['side_index'],team_id=r['team_id'],team_index=r['team_index'],opponent_id=r['opponent_id'],opponent_index=r['opponent_index'],opponent_name=r['opponent_name'],crosses_for=_summary([r]),crosses_against=_summary([r],'opponent_')) for r in selected],
      league_delivery_leaders=_leaderboards(scoped_players,leaders,minimum_minutes,leader_sort,{(r['fixture_id'],r['side_index']) for r in comparison}),selected_delivery_leaders=_leaderboards(own_players,leaders,minimum_minutes,leader_sort,selected_keys),opponent_delivery_leaders=_leaderboards(opponent_players,leaders,minimum_minutes,leader_sort,{(fid,1-side) for fid,side in selected_keys}))


def crossing_report(path, **selectors):
    """Open one exported source read-only; never attach, refresh, or mutate it."""
    path=Path(path).expanduser().resolve(strict=True)
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        out=report_connection(db,**selectors)
        out['source']=dict(path=str(path),read_only=True,sqlite_snapshot='single_read_transaction')
        return out
    finally:db.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True,type=Path);parser.add_argument('--competition-id',required=True,type=int)
    parser.add_argument('--team-id',type=int);parser.add_argument('--team-index',type=int)
    parser.add_argument('--date-from');parser.add_argument('--date-to');parser.add_argument('--venue',choices=tuple(VENUES),default='all')
    parser.add_argument('--leader-sort',choices=('attempted','completed','accuracy'),default='attempted')
    parser.add_argument('--leaders',type=int,default=10);parser.add_argument('--minimum-minutes',type=int,default=0)
    args=vars(parser.parse_args());path=args.pop('database')
    try:
        output=crossing_report(path,**args)
    except ReportUnavailable as error:
        print(json.dumps(dict(state='unavailable',source=str(path.resolve()),missing_fields=error.missing_fields),indent=2))
        raise SystemExit(2) from error
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(output,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
