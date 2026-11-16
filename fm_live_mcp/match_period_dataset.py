"""Optional verified host period evidence linked to exact retained shot identities.

This stores retrospective evidence supplied by the checked host linker. It does
not infer periods from clock magnitudes, elapsed minutes, slot order or scores.
"""
from collections import Counter
import json
import math

from .match_shot_dataset import _identity


def _career(save):
    return {key:value for key,value in save.items() if key not in ('current_date','last_saved_date','save_count')}


def write_period_evidence(db, capture, selected, packets):
    db.executescript('''
    CREATE TABLE match_period_evidence(fixture_id TEXT PRIMARY KEY REFERENCES fixtures,native_match_key INTEGER,
      capture_id TEXT NOT NULL,source_kind TEXT NOT NULL,confidence TEXT NOT NULL,
      official_match_unique_id TEXT,clock_domain TEXT NOT NULL,raw_json TEXT NOT NULL);
    CREATE TABLE match_periods(fixture_id TEXT REFERENCES fixtures,period TEXT,start_tick INTEGER,end_tick INTEGER,
      boundary_policy TEXT NOT NULL,PRIMARY KEY(fixture_id,period));
    CREATE TABLE shot_periods(fixture_id TEXT,side_index INTEGER,record_index INTEGER,event_id INTEGER,
      period TEXT,native_clock_start_raw INTEGER,native_clock_end_raw INTEGER,assignment_state TEXT NOT NULL,
      shooter_person_id INTEGER,shooter_name TEXT,raw_json TEXT NOT NULL,
      PRIMARY KEY(fixture_id,side_index,record_index),
      FOREIGN KEY(fixture_id,side_index,record_index) REFERENCES shots(fixture_id,side_index,record_index));
    CREATE TABLE match_period_team_totals(fixture_id TEXT REFERENCES fixtures,period TEXT,side_index INTEGER,
      state TEXT NOT NULL,shots INTEGER,shots_on_target INTEGER,shot_goals INTEGER,
      expected_goals_sum_computed REAL,header_count INTEGER,feet_count INTEGER,unclassified_body_part_count INTEGER,
      source TEXT NOT NULL,PRIMARY KEY(fixture_id,period,side_index));
    CREATE VIEW shot_period_analysis AS SELECT f.date,f.home_team,f.away_team,p.*,s.expected_goals,
      s.native_x,s.native_y,s.body_part,s.outcome,s.official_location
      FROM shot_periods p JOIN shots s USING(fixture_id,side_index,record_index)
      JOIN fixtures f USING(fixture_id);
    ''')
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='shots'").fetchone():
        raise ValueError('Period evidence requires captured shot maps')
    dump=lambda value:json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)
    keys=dict(db.execute('SELECT fixture_id,native_match_key FROM fixtures'))
    seen=set()
    for evidence in packets:
        if (evidence.get('link_state')!='verified_retrospective_continuity'
                or evidence.get('confidence')!='verified_retrospective_continuity'
                or not evidence.get('capture_id') or not evidence.get('provenance')
                or evidence.get('time_slice_domain')!='native_playback_time_slice'):
            raise ValueError('Period evidence requires verified native continuity/provenance')
        if _career(evidence.get('observed_save')or{})!=_career(capture.get('save')or{}):
            raise ValueError('Period evidence belongs to another captured career')
        matches=[fid for fid,fixture in selected if keys[fid]==evidence.get('native_match_key')
                 and _identity(fixture,require_complete=True)==_identity(evidence.get('fixture')or{},require_complete=True)]
        if len(matches)!=1 or matches[0]in seen:
            raise ValueError('Period evidence fixture is absent, duplicated or ambiguous')
        fid=matches[0];seen.add(fid);intervals=[]
        for interval in evidence.get('intervals',()):
            period,start,end=interval.get('period'),interval.get('start_tick'),interval.get('end_tick')
            if (period not in ('FirstHalf','SecondHalf') or type(start)is not int or type(end)is not int
                    or not 0<=start<end<65536 or any(row['period']==period for row in intervals)):
                raise ValueError('Period evidence has unsupported or ambiguous intervals')
            intervals.append(dict(period=period,start_tick=start,end_tick=end))
        if not intervals or any(max(a['start_tick'],b['start_tick'])<min(a['end_tick'],b['end_tick'])for i,a in enumerate(intervals)for b in intervals[i+1:]):
            raise ValueError('Period evidence intervals overlap or are missing')
        db.execute('INSERT INTO match_period_evidence VALUES(?,?,?,?,?,?,?,?)',
                   (fid,keys[fid],evidence['capture_id'],evidence.get('source_kind','host_captured_period_observation'),
                    evidence['confidence'],str(evidence['official_match_unique_id'])if evidence.get('official_match_unique_id')is not None else None,
                    evidence['time_slice_domain'],dump(evidence)))
        for row in intervals:
            db.execute('INSERT INTO match_periods VALUES(?,?,?,?,?)',(fid,row['period'],row['start_tick'],row['end_tick'],'start<=event_start<=event_end<end; ties/crossings unknown'))
        actual={}
        for side,index,event,raw in db.execute('SELECT side_index,record_index,event_id,raw_json FROM shots WHERE fixture_id=?',(fid,)):
            if (side,event)in actual:raise ValueError('Ambiguous retained shot event identity')
            actual[side,event]=(index,json.loads(raw))
        declared={}
        for row in evidence.get('shot_periods',()):
            identity=row.get('side_index'),row.get('event_id')
            if identity in declared:raise ValueError('Duplicate period shot identity')
            declared[identity]=row
        if set(actual)!=set(declared):
            raise ValueError('Period assignment coverage differs from captured retained shots')
        assigned=[]
        for (side,event),(index,row) in actual.items():
            declaration=declared[side,event]
            # At least the exact clock pair is mandatory; other supplied native
            # semantic fields must also agree with the immutable retained row.
            for field in ('native_clock_start_raw','native_clock_end_raw'):
                if type(declaration.get(field))is not int or declaration[field]!=row.get(field):
                    raise ValueError('Period evidence shot native clocks disagree')
            for field in ('native_x','native_y','expected_goals','native_category_code','native_shot_type','stored_player_slot'):
                if field in declaration and declaration[field]!=row.get(field):
                    raise ValueError('Period evidence shot semantic payload disagrees')
            start,end=row['native_clock_start_raw'],row['native_clock_end_raw']
            periods=[p['period']for p in intervals if p['start_tick']<=start<=end<p['end_tick']]
            period=periods[0]if len(periods)==1 else None
            if declaration.get('period')!=period:
                raise ValueError('Declared shot period violates verified interval boundaries')
            actor=row.get('actor')or{}
            db.execute('INSERT INTO shot_periods VALUES('+','.join('?'for _ in range(11))+')',
                       (fid,side,index,event,period,start,end,'verified_native_stop_interval'if period else'unknown_boundary_or_unavailable_interval',
                        actor.get('canonical_person_id'),actor.get('person_name'),dump(declaration)))
            assigned.append(dict(row,period=period))
        coverage=dict(db.execute('SELECT side_index,state FROM shot_map_coverage WHERE fixture_id=?',(fid,)))
        for interval in intervals:
            for side in(0,1):
                rows=[r for r in assigned if r['side_index']==side and r['period']==interval['period']]
                known=coverage.get(side)=='available';parts=Counter(r.get('body_part')or'unclassified'for r in rows)
                db.execute('INSERT INTO match_period_team_totals VALUES('+','.join('?'for _ in range(12))+')',
                           (fid,interval['period'],side,'available_derived_retained_attempts'if known else'unavailable_shot_source',
                            len(rows)if known else None,sum(r.get('native_category_code')in(1,4)for r in rows)if known else None,
                            sum(r.get('outcome')=='goal'for r in rows)if known else None,
                            math.fsum(r['expected_goals']for r in rows)if known else None,
                            parts['head']if known else None,parts['feet']if known else None,parts['unclassified']if known else None,
                            'Retrospective retained CBE attempts after verified native period continuity; own-goal markers excluded'))
