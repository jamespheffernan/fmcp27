"""Portable, lossless SQLite projection of bounded live match captures.

No inferred event labels, minutes, assists or absent totals. SQLite is local only.
"""
import argparse
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
import sqlite3


PLAYER_ADDITIONAL_FIELDS = ('expected_assists', 'key_passes', 'open_play_key_passes', 'chances_created', 'appearance_kind', 'appearance_kind_state', 'native_substitute_duration_flag', 'native_on_minute', 'native_off_minute', 'native_injury_minute', 'native_sent_off_minute', 'native_end_clock', 'sent_off', 'entry_minute', 'exit_minute', 'exit_reason', 'participation_state', 'interval_precision', 'interval_convention', 'simultaneous_event_order_known', 'aerial_duels_attempted', 'aerial_duels_completed', 'interceptions', 'clearances', 'crosses_attempted', 'crosses_completed', 'open_play_crosses_attempted', 'open_play_crosses_completed', 'saves_held', 'saves_parried', 'saves_tipped', 'total_saves', 'possession_won', 'possession_lost', 'pressures_completed', 'progressive_passes', 'stored_match_position_mask', 'stored_match_position', 'stored_match_position_state', 'direct_free_kick_goals', 'pressures_attempted', 'pressure_completion_percentage_computed', 'pressure_completion_state', 'dribbles_made', 'distance_metres', 'sprints', 'open_play_final_third_passes')


def export_dataset(output, capture, player_rows=(), source='capture', *, team_id=None,
                   date_from=None, date_to=None, competition_id=None, team_totals=None, retained_players=(), raw_frames=(), player_metrics=(), field_provenance=None, goal_crossings=(), entry_state_policy=None, shot_maps=None, spatial_reports=None, period_evidence=None, pass_attempts=None, _connection=False):
    """Export normalized fixtures and ambiguous candidate joins; preserve raw sources."""
    path = Path(output)
    if not _connection and (path.exists() or path.is_symlink()):
        raise FileExistsError(f'Refusing to replace existing dataset: {path}')
    staging = None
    if not _connection:
        descriptor, temporary = tempfile.mkstemp(prefix='.fm-match-export-', suffix='.sqlite.tmp', dir=path.parent)
        os.close(descriptor)
        staging = Path(temporary)
    try:
        db = sqlite3.connect(':memory:' if _connection else staging)
    except BaseException:
        if staging is not None: staging.unlink(missing_ok=True)
        raise
    try:
        db.executescript('''
        CREATE TABLE metadata(key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
        CREATE TABLE fixtures(fixture_id TEXT PRIMARY KEY, native_match_key INTEGER,
          date TEXT, competition_id INTEGER, competition TEXT, home_team_index INTEGER,
          home_team_id INTEGER, home_team TEXT, away_team_index INTEGER,
          away_team_id INTEGER, away_team TEXT, home_score INTEGER, away_score INTEGER,
          event_state TEXT, raw_json TEXT NOT NULL, fixture_ref TEXT);
        CREATE TABLE events(fixture_id TEXT REFERENCES fixtures, source_index INTEGER,
          person_index INTEGER, person_native_id INTEGER, person TEXT, side_code INTEGER,
          kind_code INTEGER, clock_word INTEGER, byte14 INTEGER, byte15 INTEGER,
          raw_json TEXT NOT NULL, PRIMARY KEY(fixture_id, source_index));
        CREATE TABLE player_matches(row_id INTEGER PRIMARY KEY, person_index INTEGER,
          player TEXT, team_index INTEGER, ring_slot INTEGER, date TEXT,
          opponent_id INTEGER, opponent TEXT, competition_id INTEGER, competition TEXT,
          minutes INTEGER, goals INTEGER, sub_on_minute INTEGER, appearance_state TEXT,
          join_state TEXT, raw_json TEXT NOT NULL);
        CREATE TABLE player_fixture_candidates(row_id INTEGER REFERENCES player_matches,
          fixture_id TEXT REFERENCES fixtures, PRIMARY KEY(row_id,fixture_id));
        CREATE TABLE team_totals(fixture_id TEXT REFERENCES fixtures, native_match_key INTEGER,
          side_index INTEGER, team_index INTEGER, shots INTEGER, shots_on_target INTEGER,
          expected_goals REAL, raw_json TEXT NOT NULL, passes_attempted INTEGER, passes_completed INTEGER,
          corners INTEGER,possession_time_raw INTEGER,possession_share_percentage_computed INTEGER,
          possession_share_state TEXT,pass_completion_percentage_derived REAL,
          crosses_attempted INTEGER,crosses_completed INTEGER,
          cross_completion_percentage_derived REAL,crossing_counts_state TEXT);
        CREATE TABLE retained_players(fixture_id TEXT REFERENCES fixtures, native_match_key INTEGER,
          side_index INTEGER, team_index_word INTEGER, person_index_word INTEGER,
          canonical_person_id INTEGER, person_name TEXT, stored_player_slot INTEGER,
          minutes INTEGER, goals INTEGER, assists INTEGER, match_rating REAL,
          identity_state TEXT, raw_json TEXT NOT NULL,
          shots INTEGER, shots_on_target INTEGER, passes_attempted INTEGER, passes_completed INTEGER,
          tackles_attempted INTEGER,tackles_completed INTEGER,fouls_committed INTEGER,
          yellow_cards_received INTEGER,red_cards_received INTEGER, expected_goals REAL,
          expected_assists REAL,
          key_passes INTEGER,
          open_play_key_passes INTEGER,
          chances_created INTEGER,
          appearance_kind TEXT,
          appearance_kind_state TEXT,
          native_substitute_duration_flag INTEGER,
          native_on_minute INTEGER,
          native_off_minute INTEGER,
          native_injury_minute INTEGER,
          native_sent_off_minute INTEGER,
          native_end_clock INTEGER,
          sent_off INTEGER,
          entry_minute INTEGER,
          exit_minute INTEGER,
          exit_reason TEXT,
          participation_state TEXT,
          interval_precision TEXT,
          interval_convention TEXT,
          simultaneous_event_order_known INTEGER,
          aerial_duels_attempted INTEGER,aerial_duels_completed INTEGER,interceptions INTEGER,clearances INTEGER,
          crosses_attempted INTEGER,crosses_completed INTEGER,open_play_crosses_attempted INTEGER,open_play_crosses_completed INTEGER,
          saves_held INTEGER,saves_parried INTEGER,saves_tipped INTEGER,total_saves INTEGER,
          possession_won INTEGER,possession_lost INTEGER,pressures_completed INTEGER,progressive_passes INTEGER,
          stored_match_position_mask INTEGER,stored_match_position TEXT,stored_match_position_state TEXT,direct_free_kick_goals INTEGER,
          pressures_attempted INTEGER,pressure_completion_percentage_computed REAL,pressure_completion_state TEXT,dribbles_made INTEGER,distance_metres REAL,sprints INTEGER,open_play_final_third_passes INTEGER);
        CREATE TABLE raw_frames(fixture_id TEXT REFERENCES fixtures, native_match_key INTEGER,
          sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL, raw BLOB NOT NULL, source_json TEXT NOT NULL);
        CREATE TABLE player_metrics(fixture_id TEXT REFERENCES fixtures, native_match_key INTEGER,
          side_index INTEGER, person_index_word INTEGER, stored_player_slot INTEGER, raw_json TEXT NOT NULL);
        CREATE TABLE goal_crossings(fixture_id TEXT REFERENCES fixtures,native_match_key INTEGER,
          record_index INTEGER,side_index INTEGER,team_index INTEGER,scorer_person_index INTEGER,
          stored_player_slot INTEGER,canonical_scorer_id INTEGER,scorer_name TEXT,identity_state TEXT,
          native_horizontal REAL,native_height REAL,height_band TEXT,coordinate_units TEXT,
          horizontal_viewpoint TEXT,wire24 TEXT,raw_json TEXT NOT NULL);
        CREATE TABLE sub_entry_context(fixture_id TEXT REFERENCES fixtures,native_match_key INTEGER,
          date TEXT,competition_id INTEGER,team_id INTEGER,person_id INTEGER,player TEXT,
          entry_state TEXT,evidence_state TEXT,score_for_before_entry INTEGER,
          score_against_before_entry INTEGER,personal_goals_after_entry INTEGER,
          boundary_event_count INTEGER,entry_minute INTEGER,native_minutes INTEGER,raw_json TEXT NOT NULL);
        CREATE TABLE coverage(source TEXT, state TEXT, raw_json TEXT);
        CREATE INDEX fixture_selectors ON fixtures(date, competition_id, home_team_id, away_team_id);
        CREATE INDEX player_identity ON player_matches(person_index,date);
        CREATE VIEW joined_player_matches AS SELECT p.*, c.fixture_id FROM player_matches p
          LEFT JOIN player_fixture_candidates c USING(row_id) WHERE p.join_state='unique_candidate';
        CREATE VIEW player_match_analysis AS
          SELECT p.fixture_id,p.native_match_key,f.date,f.competition,f.home_team,f.away_team,
            f.home_score,f.away_score,p.side_index,p.team_index_word,p.person_index_word,
            p.canonical_person_id,p.person_name,p.stored_player_slot,p.minutes,p.goals,p.assists,p.match_rating,
            p.expected_assists,p.key_passes,p.open_play_key_passes,p.chances_created,p.appearance_kind,p.appearance_kind_state,p.native_substitute_duration_flag,p.native_on_minute,p.native_off_minute,p.native_injury_minute,p.native_sent_off_minute,p.native_end_clock,p.sent_off,p.entry_minute,p.exit_minute,p.exit_reason,p.participation_state,p.interval_precision,p.interval_convention,p.simultaneous_event_order_known,p.aerial_duels_attempted,p.aerial_duels_completed,p.interceptions,p.clearances,p.crosses_attempted,p.crosses_completed,p.open_play_crosses_attempted,p.open_play_crosses_completed,p.saves_held,p.saves_parried,p.saves_tipped,p.total_saves,p.possession_won,p.possession_lost,p.pressures_completed,p.pressures_attempted,p.pressure_completion_percentage_computed,p.pressure_completion_state,p.progressive_passes,
            CASE WHEN p.minutes IS NULL THEN 'unknown' WHEN p.minutes=0 THEN 'zero_stored_minutes'
                 ELSE 'positive_stored_minutes' END AS minutes_state,
            CASE WHEN p.open_play_final_third_passes IS NOT NULL OR p.sprints IS NOT NULL OR p.distance_metres IS NOT NULL OR p.dribbles_made IS NOT NULL OR p.pressures_attempted IS NOT NULL OR p.direct_free_kick_goals IS NOT NULL OR p.progressive_passes IS NOT NULL OR p.possession_won IS NOT NULL OR p.possession_lost IS NOT NULL OR p.pressures_completed IS NOT NULL OR p.saves_held IS NOT NULL OR p.saves_parried IS NOT NULL OR p.saves_tipped IS NOT NULL OR p.total_saves IS NOT NULL OR p.crosses_attempted IS NOT NULL OR p.crosses_completed IS NOT NULL OR p.open_play_crosses_attempted IS NOT NULL OR p.open_play_crosses_completed IS NOT NULL OR p.aerial_duels_attempted IS NOT NULL OR p.aerial_duels_completed IS NOT NULL OR p.interceptions IS NOT NULL OR p.clearances IS NOT NULL OR m.raw_json IS NOT NULL OR p.expected_assists IS NOT NULL OR p.key_passes IS NOT NULL OR p.open_play_key_passes IS NOT NULL OR p.chances_created IS NOT NULL OR p.expected_goals IS NOT NULL OR p.shots IS NOT NULL OR p.shots_on_target IS NOT NULL OR p.passes_attempted IS NOT NULL OR p.passes_completed IS NOT NULL OR p.tackles_attempted IS NOT NULL OR p.tackles_completed IS NOT NULL OR p.fouls_committed IS NOT NULL OR p.yellow_cards_received IS NOT NULL OR p.red_cards_received IS NOT NULL THEN 'captured' ELSE 'not_captured' END AS action_source_state,
            coalesce(json_extract(m.raw_json,'$.expected_goals'),p.expected_goals) AS expected_goals,
            coalesce(json_extract(m.raw_json,'$.shots'),p.shots) AS shots,
            coalesce(json_extract(m.raw_json,'$.shots_on_target'),p.shots_on_target) AS shots_on_target,
            coalesce(json_extract(m.raw_json,'$.passes_attempted'),p.passes_attempted) AS passes_attempted,
            coalesce(json_extract(m.raw_json,'$.passes_completed'),p.passes_completed) AS passes_completed,
            coalesce(json_extract(m.raw_json,'$.tackles_attempted'),p.tackles_attempted) AS tackles_attempted,
            coalesce(json_extract(m.raw_json,'$.tackles_completed'),p.tackles_completed) AS tackles_completed,
            coalesce(json_extract(m.raw_json,'$.fouls_committed'),p.fouls_committed) AS fouls_committed,
            coalesce(json_extract(m.raw_json,'$.yellow_cards_received'),p.yellow_cards_received) AS yellow_cards_received,
            coalesce(json_extract(m.raw_json,'$.red_cards_received'),p.red_cards_received) AS red_cards_received,
            p.stored_match_position_mask,p.stored_match_position,p.stored_match_position_state,p.direct_free_kick_goals,p.dribbles_made,p.distance_metres,p.sprints,p.open_play_final_third_passes
          FROM retained_players p JOIN fixtures f USING(fixture_id)
          LEFT JOIN player_metrics m ON m.fixture_id=p.fixture_id
            AND m.native_match_key=p.native_match_key AND m.side_index=p.side_index
            AND m.person_index_word=p.person_index_word AND m.stored_player_slot=p.stored_player_slot;
        ''')
        dump = lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True)
        metadata = {k:v for k,v in capture.items() if k != 'fixtures'}
        metadata.update(source=source, schema_version=3 if spatial_reports is not None or period_evidence is not None or pass_attempts is not None else 2 if shot_maps is not None else 1, field_provenance=field_provenance,
          scope='Retained resident fixtures and player ring records only; missing data is unknown.',
          identity_scope='Database indices are same-save snapshot identities; refs are not persistent IDs.',
          event_semantics='Raw verified record fields only. Codes/time/second actor are not inferred.',
          joins='Date, competition native ID, own team database index and opponent native ID; all candidates retained.',
          filters=dict(team_id=team_id,date_from=date_from,date_to=date_to,competition_id=competition_id))
        db.executemany('INSERT INTO metadata VALUES (?,?)', [(k,dump(v)) for k,v in metadata.items()])
        selected=[]
        for ordinal,item in enumerate(capture.get('fixtures', [])):
            f=item.get('fixture',item); h=f.get('home_team') or {}; a=f.get('away_team') or {}; comp=f.get('competition') or {}
            if team_id is not None and team_id not in (h.get('native_id'),a.get('native_id')): continue
            if date_from and (f.get('date') or '') < date_from: continue
            if date_to and (f.get('date') or '') > date_to: continue
            if competition_id is not None and comp.get('native_id') != competition_id: continue
            key=item.get('native_match_key')
            # Identity includes the full fixture, so duplicate native keys remain separate.
            stable={k:v for k,v in f.items() if k != 'fixture_ref'}
            for side in ('home_team','away_team'):
                if stable.get(side): stable[side]={k:v for k,v in stable[side].items() if k!='team_ref'}
            fid=hashlib.sha256(dump([ordinal,key,stable]).encode()).hexdigest()[:24]
            score=(f.get('scores') or {}).get('final_score') or {}; event=item.get('event_array') or {}
            db.execute('INSERT INTO fixtures VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (fid,key,f.get('date'),comp.get('native_id'),comp.get('name'),h.get('database_index'),h.get('native_id'),(h.get('owner') or {}).get('name'),a.get('database_index'),a.get('native_id'),(a.get('owner') or {}).get('name'),score.get('home'),score.get('away'),event.get('state','not_captured'),dump(item),f.get('fixture_ref')))
            selected.append((fid,f))
            for e in event.get('rows') or []:
                person=e.get('person') or {}
                db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)',(fid,e.get('source_index'),e.get('person_index'),person.get('native_id'),person.get('display_name'),e.get('side12'),e.get('kind13'),e.get('word8'),e.get('byte14'),e.get('byte15'),dump(e)))
        selected_team_indices={team.get('database_index') for _,f in selected for team in (f.get('home_team') or {},f.get('away_team') or {}) if team.get('native_id')==team_id}
        for row in player_rows:
            r=dict(row)
            for k in ('person_index','team_index','ring_slot','opponent_id','competition_id','minutes','goals','sub_on_minute'):
                r[k]=int(r[k]) if r.get(k) not in (None,'') else None
            if team_id is not None and r['team_index'] not in selected_team_indices: continue
            if date_from and (r.get('date') or '') < date_from: continue
            if date_to and (r.get('date') or '') > date_to: continue
            if competition_id is not None and r['competition_id'] != competition_id: continue
            candidates=[]
            for fid,f in selected:
                if f.get('date')!=r.get('date') or (f.get('competition') or {}).get('native_id')!=r['competition_id']: continue
                h=f.get('home_team') or {}; a=f.get('away_team') or {}
                if ((h.get('database_index'),a.get('native_id'))==(r['team_index'],r['opponent_id']) or
                    (a.get('database_index'),h.get('native_id'))==(r['team_index'],r['opponent_id'])): candidates.append(fid)
            # Keep unmatched rows: they expose incomplete fixture coverage.
            state='unique_candidate' if len(candidates)==1 else 'ambiguous' if candidates else 'unmatched'
            cols=('person_index','player','team_index','ring_slot','date','opponent_id','opponent','competition_id','competition','minutes','goals','sub_on_minute','appearance_state')
            cur=db.execute('INSERT INTO player_matches('+','.join(cols)+',join_state,raw_json) VALUES ('+','.join('?' for _ in range(15))+')',tuple(r.get(k) for k in cols)+(state,dump(row)))
            db.executemany('INSERT INTO player_fixture_candidates VALUES (?,?)',[(cur.lastrowid,fid) for fid in candidates])
        db.execute('INSERT INTO coverage VALUES (?,?,?)',(source,'captured_subset',dump({'fixture_count':len(selected),'unknowns':['unloaded fixtures','players outside captured roster','uncaptured totals','unverified event semantics']})))
        for record in (team_totals or {}).get('records', []):
            key=record.get('result_key')
            matches=db.execute('SELECT fixture_id FROM fixtures WHERE native_match_key=?',(key,)).fetchall()
            # Duplicate match keys cannot authorize a unique totals join.
            if len(matches)!=1:
                db.execute('INSERT INTO coverage VALUES (?,?,?)',('team_totals','unmatched_or_ambiguous',dump(record)))
                continue
            for team in record.get('teams', []):
                db.execute('INSERT INTO team_totals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(matches[0][0],key,team.get('side_index'),team.get('team_index'),team.get('shots'),team.get('shots_on_target'),team.get('expected_goals'),dump(team))+tuple(team.get(k) for k in ('passes_attempted','passes_completed','corners','possession_time_raw','possession_share_percentage_computed','possession_share_state','pass_completion_percentage_derived','crosses_attempted','crosses_completed','cross_completion_percentage_derived','crossing_counts_state')))
        for row in retained_players:
            from .saved_match_player_recoveries import pressure_completion_fields
            row = {**row, **pressure_completion_fields(row)}
            matches=db.execute('SELECT fixture_id FROM fixtures WHERE native_match_key=?',(row.get('fixture_key'),)).fetchall()
            if len(matches)!=1:
                db.execute('INSERT INTO coverage VALUES (?,?,?)',('retained_players','unmatched_or_ambiguous',dump(row)))
                continue
            cols=('fixture_key','side_index','team_index_word','person_index_word','canonical_person_id','person_name','stored_player_slot','minutes','goals','assists','match_rating')
            state='canonical_source_identity' if row.get('canonical_person_id') is not None else 'unresolved_source_local_words'
            db.execute('INSERT INTO retained_players VALUES ('+','.join('?' for _ in range(24+len(PLAYER_ADDITIONAL_FIELDS)))+')',(matches[0][0],)+tuple(row.get(k) for k in cols)+(state,dump(row))+tuple(row.get(k) for k in ('shots','shots_on_target','passes_attempted','passes_completed','tackles_attempted','tackles_completed','fouls_committed','yellow_cards_received','red_cards_received','expected_goals'))+tuple(row.get(k) for k in PLAYER_ADDITIONAL_FIELDS))
        for metric in player_metrics:
            matches=db.execute('SELECT fixture_id FROM fixtures WHERE native_match_key=?',(metric.get('fixture_key'),)).fetchall()
            if len(matches)!=1:
                db.execute('INSERT INTO coverage VALUES (?,?,?)',('player_metrics','unmatched_or_ambiguous',dump(metric)))
                continue
            db.execute('INSERT INTO player_metrics VALUES (?,?,?,?,?,?)',(matches[0][0],metric.get('fixture_key'),metric.get('side_index'),metric.get('person_index_word'),metric.get('stored_player_slot'),dump(metric)))
        for record in goal_crossings:
            key=record.get('fixture_key')
            matches=db.execute('SELECT fixture_id FROM fixtures WHERE native_match_key=?',(key,)).fetchall()
            db.execute('INSERT INTO coverage VALUES (?,?,?)',('goal_crossings',record.get('source_state','captured'),dump({k:v for k,v in record.items() if k!='goal_crossings'})))
            if len(matches)!=1:
                db.execute('INSERT INTO coverage VALUES (?,?,?)',('goal_crossings','unmatched_or_ambiguous',dump(record)))
                continue
            for row in record.get('goal_crossings',()):
                cols=('record_index','side_index','team_index','scorer_person_index','stored_player_slot','canonical_scorer_id','scorer_name','identity_state','native_horizontal','native_height','height_band','coordinate_units','horizontal_viewpoint','wire24')
                db.execute('INSERT INTO goal_crossings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(matches[0][0],key)+tuple(row.get(k) for k in cols)+(dump(row),))
        if entry_state_policy is not None:
            from .match_entry_state import query_entry_context
            for row in query_entry_context(db,source_policy=entry_state_policy):
                cols=('fixture_id','native_match_key','date','competition_id','team_id','person_id','player','entry_state','evidence_state','score_for_before_entry','score_against_before_entry','personal_goals_after_entry','boundary_event_count','entry_minute','native_minutes')
                db.execute('INSERT INTO sub_entry_context VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',tuple(row.get(k) for k in cols)+(dump(row),))
        for frame in raw_frames:
            from . import saved_match_statistics_wire as wire
            key=frame['key']
            raw=frame.get('raw')
            if raw is None: raw=Path(frame['raw_path']).read_bytes()
            if not isinstance(raw,bytes) or not 1<=len(raw)<=10000000:
                raise ValueError('Raw frame size/type budget exceeded')
            sha=hashlib.sha256(raw).hexdigest()
            if frame.get('raw_sha256',sha)!=sha or frame.get('raw_length',len(raw))!=len(raw):
                raise ValueError('Raw frame receipt hash/size mismatch')
            prefix=wire.fixture_prefix(raw)
            parsed=wire.continue_fixture(raw,prefix['end'],wire.parse_person,wire.fixture_extra)
            if parsed['fields']['scalar_u32'][0]!=key:
                raise ValueError('Raw frame internal match key mismatch')
            matches=db.execute('SELECT fixture_id FROM fixtures WHERE native_match_key=?',(key,)).fetchall()
            if len(matches)!=1:
                raise ValueError('Raw frame requires unique fixture match key')
            receipt={k:v for k,v in frame.items() if k!='raw'}
            db.execute('INSERT INTO raw_frames VALUES (?,?,?,?,?,?)',(matches[0][0],key,sha,len(raw),raw,dump(receipt)))
        if spatial_reports is not None:
            from .match_spatial_dataset import write_spatial_reports
            write_spatial_reports(db, capture, selected, spatial_reports)
        if shot_maps is not None:
            from .match_shot_dataset import write_shot_maps
            write_shot_maps(db, capture, selected, shot_maps)
        if pass_attempts is not None:
            from .match_pass_attempt_dataset import write_pass_attempts
            write_pass_attempts(db, capture, selected, pass_attempts)
        if period_evidence is not None:
            from .match_period_dataset import write_period_evidence
            write_period_evidence(db, capture, selected, period_evidence)
        db.commit()
    except BaseException:
        db.close()
        if staging is not None: staging.unlink(missing_ok=True)
        raise
    if _connection: return db
    db.close()
    try:
        # Publish only a complete committed database; link refuses a concurrent
        # destination creation and never overwrites another writer's file.
        os.link(staging, path)
    finally:
        staging.unlink(missing_ok=True)
    return path


def build_connection(capture, player_rows=(), source='capture', **filters):
    """Return an in-memory SQLite connection; caller owns closing it."""
    return export_dataset(':memory:', capture, player_rows, source, _connection=True, **filters)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',required=True,type=Path,help='JSON fixture capture; fixtures contain fixture, native_match_key and optional event_array')
    parser.add_argument('--player-rows',type=Path,help='Retained player-match CSV')
    parser.add_argument('--output',required=True,type=Path,help='New SQLite path (never overwritten)')
    parser.add_argument('--field-provenance',type=Path,help='JSON field registry and evidence limits embedded in metadata')
    parser.add_argument('--raw-frames',type=Path,help='Receipt JSON records[] with key/raw_path/raw_sha256/raw_length; embeds full frames')
    parser.add_argument('--player-metrics',type=Path,help='Field-provenance player metric JSONL')
    parser.add_argument('--retained-players',type=Path,help='Decoded frame player JSONL; source-local identity words remain explicit')
    parser.add_argument('--team-totals',type=Path,help='Verified records[].result_key/teams[] totals JSON')
    parser.add_argument('--shot-maps',type=Path,help='Explicit checked retained-shot packet JSON, list or records[]; adds per-side source coverage and separate own-goal markers')
    parser.add_argument('--team-id',type=int)
    parser.add_argument('--date-from'); parser.add_argument('--date-to'); parser.add_argument('--competition-id',type=int)
    args=parser.parse_args()
    rows=[]
    if args.player_rows:
        with args.player_rows.open(newline='') as handle: rows=list(csv.DictReader(handle))
    shot_maps=None
    if args.shot_maps:
        shot_maps=json.loads(args.shot_maps.read_text())
        if isinstance(shot_maps,dict):shot_maps=shot_maps['records']
        if not isinstance(shot_maps,list):raise ValueError('Shot-map input must be a list or records[] packet')
    path=export_dataset(args.output,json.loads(args.capture.read_text()),rows,str(args.capture),team_id=args.team_id,date_from=args.date_from,date_to=args.date_to,competition_id=args.competition_id,team_totals=json.loads(args.team_totals.read_text()) if args.team_totals else None,field_provenance=json.loads(args.field_provenance.read_text()) if args.field_provenance else None,raw_frames=json.loads(args.raw_frames.read_text()).get('records',[]) if args.raw_frames else (),player_metrics=[json.loads(line) for line in args.player_metrics.read_text().splitlines() if line] if args.player_metrics else (),retained_players=[json.loads(line) for line in args.retained_players.read_text().splitlines() if line] if args.retained_players else (),shot_maps=shot_maps)
    print(path.resolve())


if __name__=='__main__': main()
