"""Optional canonical-fixture pass attempts and uninterpreted native path samples."""
from collections import Counter
import json
import math

from .match_shot_dataset import _identity
from .match_spatial_dataset import _actor,_side,_integer


def write_pass_attempts(db,capture,selected,packets):
    db.executescript('''
    CREATE TABLE pass_attempt_sources(fixture_id TEXT PRIMARY KEY REFERENCES fixtures,native_match_key INTEGER,
      state TEXT NOT NULL,source_kind TEXT,native_events_sha256 TEXT,native_paths_sha256 TEXT,raw_json TEXT NOT NULL);
    CREATE TABLE pass_attempt_coverage(fixture_id TEXT REFERENCES fixtures,side_index INTEGER,state TEXT,
      attempts INTEGER,completed INTEGER,not_completed INTEGER,raw_json TEXT NOT NULL,
      PRIMARY KEY(fixture_id,side_index));
    CREATE TABLE pass_attempts(fixture_id TEXT REFERENCES fixtures,event_id INTEGER,record_index INTEGER,
      side_index INTEGER,stored_player_slot INTEGER,person_id INTEGER,person_name TEXT,
      native_category_code INTEGER,completed INTEGER,outcome TEXT,specific_failure_reason TEXT,
      recipient_person_id INTEGER,recipient_name TEXT,recipient_state TEXT,native_flags_word INTEGER,
      native_event_x REAL,native_event_y REAL,native_path_start_x REAL,native_path_start_y REAL,
      native_path_end_x REAL,native_path_end_y REAL,geometry_state TEXT,origin_destination_state TEXT,
      coordinate_units TEXT,phase TEXT,displayed_time TEXT,raw_json TEXT NOT NULL,
      PRIMARY KEY(fixture_id,event_id));
    CREATE TABLE pass_path_points(fixture_id TEXT,event_id INTEGER,point_index INTEGER,native_x REAL,native_y REAL,
      PRIMARY KEY(fixture_id,event_id,point_index),FOREIGN KEY(fixture_id,event_id) REFERENCES pass_attempts(fixture_id,event_id));
    CREATE VIEW pass_attempt_analysis AS SELECT f.date,f.home_team,f.away_team,p.*
      FROM pass_attempts p JOIN fixtures f USING(fixture_id);
    ''')
    dump=lambda row:json.dumps(row,ensure_ascii=False,sort_keys=True,allow_nan=False)
    keys=dict(db.execute('SELECT fixture_id,native_match_key FROM fixtures'));seen=set()
    for packet in packets:
        matches=[fid for fid,fixture in selected if keys[fid]==packet.get('native_match_key')
                 and _identity(fixture,require_complete=True)==_identity(packet.get('fixture')or{},require_complete=True)]
        if len(matches)!=1 or matches[0]in seen:raise ValueError('Pass attempts require one exact captured fixture')
        fid=matches[0];seen.add(fid)
        rows=packet.get('attempts',());coverage=packet.get('side_coverage',())
        if packet.get('state')!='available' or len(rows)>30000 or {r.get('side_index')for r in coverage}!={0,1} or len(coverage)!=2:
            raise ValueError('Pass attempts require complete checked side coverage')
        db.execute('INSERT INTO pass_attempt_sources VALUES(?,?,?,?,?,?,?)',(fid,keys[fid],packet['state'],packet.get('source_kind'),packet.get('native_events_sha256'),packet.get('native_paths_sha256'),dump(packet)))
        counts=Counter();completed=Counter();events=set()
        fields=('record_index','side_index','stored_player_slot','person_native_id','person_name','native_category_code','completed','outcome','specific_failure_reason','recipient_person_native_id','recipient_name','recipient_state','native_flags_word','native_event_x','native_event_y','native_path_start_x','native_path_start_y','native_path_end_x','native_path_end_y','geometry_state','origin_destination_state','coordinate_units','phase','displayed_time')
        for row in rows:
            side=_side(row['side_index']);event=_integer(row['event_id'])
            if event in events:raise ValueError('Duplicate pass event identity')
            events.add(event);_actor(db,fid,side,row['person_native_id'],row['person_name'],row['stored_player_slot'])
            if (type(row.get('completed'))is not bool or type(row.get('native_category_code'))is not int or row.get('native_category_code')not in range(6,12)
                    or row['completed']!=(row['native_category_code']==7)or _integer(row['native_flags_word'])&8):
                raise ValueError('Pass completion/family/flag disagrees with native source')
            if row.get('recipient_person_native_id')is not None:
                if not row['completed']:raise ValueError('Uncompleted pass cannot claim a checked recipient')
                _actor(db,fid,side,row['recipient_person_native_id'],row['recipient_name'])
            if row.get('origin_destination_state')!='not_proved' or any(row.get(k)is not None for k in('coordinate_units','phase','displayed_time')):
                raise ValueError('Pass path semantics exceed verified raw source')
            for field in('native_event_x','native_event_y','native_path_start_x','native_path_start_y','native_path_end_x','native_path_end_y'):
                if row.get(field)is not None and (type(row[field])not in(int,float)or not math.isfinite(row[field])):raise ValueError('Invalid native pass coordinates')
            db.execute('INSERT INTO pass_attempts VALUES('+','.join('?'for _ in range(27))+')',(fid,event)+tuple(row.get(k)for k in fields)+(dump(row),))
            points=row.get('native_path_points',())
            if not isinstance(points,list)or len(points)>10000:raise ValueError('Pass path point budget exceeded')
            for index,point in enumerate(points):
                if any(type(point.get(k))not in(int,float)or not math.isfinite(point[k])for k in('x','y')):raise ValueError('Invalid native pass path sample')
                db.execute('INSERT INTO pass_path_points VALUES(?,?,?,?,?)',(fid,event,index,point['x'],point['y']))
            counts[side,row['person_native_id']]+=1;completed[side,row['person_native_id']]+=row['completed']
        for side in(0,1):
            source=next(r for r in coverage if r['side_index']==side)
            actual=list(db.execute('SELECT canonical_person_id,passes_attempted,passes_completed FROM retained_players WHERE fixture_id=? AND side_index=?',(fid,side)))
            if (source.get('state')!='available' or not source.get('all_captured_player_attempt_counters_match')
                    or not source.get('all_captured_player_completion_counters_match')or not actual
                    or any(counts[side,p]!=a or completed[side,p]!=c for p,a,c in actual)):
                raise ValueError('Pass attempts do not reconcile every captured player counter')
            n=sum(a for _,a,_ in actual);c=sum(c for _,_,c in actual)
            if source.get('attempt_count')!=n or source.get('completed_count')!=c or source.get('not_completed_count')!=n-c:
                raise ValueError('Pass attempt side totals disagree with captured players')
            db.execute('INSERT INTO pass_attempt_coverage VALUES(?,?,?,?,?,?,?)',(fid,side,source['state'],n,c,n-c,dump(source)))
