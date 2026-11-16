"""Offline evidence adapter for complete counter-reconciled pass-event points."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct

STATE='verified_complete_counter_reconciled_pass_event_locations'


def _identity(f):
    return(f['date'],f['competition']['native_id'],*((f[k]['database_index'],f[k]['native_id'],f[k].get('native_type_code'))for k in('home_team','away_team')))


def _load(value):
    if isinstance(value,tuple):return value
    path=Path(value);raw=path.read_bytes()
    return json.loads(raw),{'source_path':str(path.resolve()),'file':path.name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def _finite(value):return type(value)in(int,float)and math.isfinite(value)


def _point(event,index,roster,geometry):
    side,slot,category=event[40],event[39],event[42]
    actor=roster.get((side,slot))
    if actor is None:raise ValueError('Pass-event actor is outside checked original-slot roster')
    flags=struct.unpack_from('<H',event,48)[0];x,y=struct.unpack_from('<ff',event,24)
    if not all(_finite(v)for v in(x,y)):raise ValueError('Nonfinite pass-map event position')
    width,length=geometry['half_width_native'],geometry['half_length_native']
    direction=bool(flags&256);forward=y if direction else-y
    inside=abs(x)<=width and abs(y)<=length
    third=('defensive'if forward < -length/3 else'middle'if forward < length/3 else'attacking')if inside else None
    channel=('central'if abs(x)<=width/3 else'outer')if inside else None
    receiver=roster.get((side,event[41]))if category==7 else None
    if category==7 and receiver is None:raise ValueError('Completed-pass recipient is outside checked same-side roster')
    return dict(event_id=struct.unpack_from('<I',event,44)[0],record_index=index,side_index=side,stored_player_slot=slot,
                person_native_id=actor['canonical_person_id'],person_name=actor['person_name'],native_category_code=category,
                completed=category==7,native_flags_word=flags,native_x=x,native_y=y,
                attacked_goal_positive_native_y=direction,attack_relative_longitudinal_coordinate=forward,
                inside_native_pitch_extents=inside,analytical_pitch_third=third,analytical_lateral_channel=channel,
                recipient_person_native_id=receiver['canonical_person_id']if receiver else None,
                recipient_name=receiver['person_name']if receiver else None)


def add_pass_location_evidence(data,capture_path,locations_path):
    """Attach only complete verified points; never upgrade legacy raw XY fields."""
    evidence,provenance=_load(locations_path)
    if evidence.get('state')!=STATE:
        data['pass_event_locations']={'state':'unavailable_missing_verified_pass_event_locations','points':None,
                                      'reason':'Legacy or unverified XY fields do not authorize this layer.'}
        return data
    if(evidence.get('native_binding_proof')or{}).get('state')!='verified_expected_installed_native_pass_map_spans':
        raise ValueError('Pass-map native binding evidence is missing')
    capture,_=_load(capture_path)
    if not(capture.get('receipt')or{}).get('same_native_epoch_verified'):
        raise ValueError('Pass-map capture epoch is unverified')
    if evidence['native_match_key']!=data['match_key']or _identity(evidence['fixture'])!=_identity(data['fixture']):
        raise ValueError('Pass-map fixture identity differs from report')
    frames=[r for r in capture['raw_frames']if r['key']==data['match_key']]
    if len(frames)!=1 or frames[0]['raw_sha256']!=evidence['raw_frame_sha256']:
        raise ValueError('Pass-map raw frame identity differs')
    frame_raw=bytes.fromhex(frames[0]['raw']['_bytes_hex'])
    if hashlib.sha256(frame_raw).hexdigest()!=frames[0]['raw_sha256']or frames[0]['raw'].get('sha256')!=frames[0]['raw_sha256']:
        raise ValueError('Pass-map full native frame bytes differ')
    geometry=evidence['pitch_geometry']
    if geometry!=data['geometry']or any(not _finite(geometry.get(k))or geometry[k]<=0 for k in('half_width_native','half_length_native')):
        raise ValueError('Pass-map native pitch geometry differs')
    raw=bytes.fromhex(evidence['source_events_hex'])
    digest=hashlib.sha256(raw).hexdigest()
    if(digest!=evidence['raw_events_sha256']or digest!=capture['receipt'].get('raw_events_sha256')
       or len(raw)%56 or len(raw)>30000*56):raise ValueError('Pass-map complete event source hash/extent differs')
    roster={};people=set();checks=[]
    source_players=capture['retained_players'];report_players={(p['side'],p['id']):p for p in data['players']}
    for p in source_players:
        side,slot=p['side_index'],p['stored_player_slot'];team=data['fixture']['home_team'if side==0 else'away_team']
        if(type(side)is not int or side not in(0,1)or type(slot)is not int or not 0<=slot<26 or(side,slot)in roster
           or p['fixture_key']!=data['match_key']or p['team_index_word']!=team['database_index']or p['canonical_team_id']!=team['native_id']):
            raise ValueError('Pass-map original roster fixture/TEAM/slot differs')
        identity=p['canonical_person_id'];name=p['person_name']
        if type(identity)is not int or identity<=0 or identity in people or not isinstance(name,str)or not name:
            raise ValueError('Pass-map canonical actor identity is ambiguous')
        people.add(identity);child=bytes.fromhex(p['raw_child_hex']);delta=0 if child[0]>=2 else 4
        if(len(child)<88+delta or hashlib.sha256(child).hexdigest()!=p['row_sha256']
           or int.from_bytes(child[1:5+delta],'little')!=p['person_index_word']
           or not 0<=p['start']<p['end']<=len(frame_raw)or frame_raw[p['start']:p['end']]!=child):raise ValueError('Pass-map native player byte identity differs')
        report=report_players.get((side,identity))
        attempted,completed=child[86+delta],child[87+delta]
        if(report is None or report['slot']!=slot or report['name']!=name or report['source_row_sha256']!=p['row_sha256']
           or report['passes_attempted']!=attempted or report['passes_completed']!=completed
           or p['passes_attempted']!=attempted or p['passes_completed']!=completed or completed>attempted):
            raise ValueError('Pass-map report/player counters differ from native bytes')
        roster[side,slot]=p
        checks.append(dict(side_index=side,stored_player_slot=slot,person_native_id=identity,person_name=name,
                           passes_attempted=attempted,passes_completed=completed,row_sha256=p['row_sha256']))
    if set(report_players)!={(p['side_index'],p['canonical_person_id'])for p in source_players}:
        raise ValueError('Pass-map report roster is incomplete')
    expected=[];event_ids=set()
    for index in range(len(raw)//56):
        event=raw[index*56:index*56+56];eid=struct.unpack_from('<I',event,44)[0]
        if eid in event_ids:raise ValueError('Duplicate complete-source pass-map event ID')
        event_ids.add(eid)
        if event[42]in range(6,12)and not event[48]&8:
            if event[40]not in(0,1):raise ValueError('Invalid pass-map event side')
            expected.append(_point(event,index,roster,geometry))
    if evidence['points']!=expected:raise ValueError('Pass-map point fields or complete event membership differ from native source')
    attempts=Counter((p['side_index'],p['stored_player_slot'])for p in expected)
    completed=Counter((p['side_index'],p['stored_player_slot'])for p in expected if p['completed'])
    for key,p in roster.items():
        if attempts[key]!=p['passes_attempted']or completed[key]!=p['passes_completed']:
            raise ValueError('Pass-map does not reconcile every player attempted/completed counter')
    coverage=[]
    for side in(0,1):
        own=[p for p in expected if p['side_index']==side];totals=next(t for t in data['team_totals']if t['side_index']==side)
        a=len(own);c=sum(p['completed']for p in own)
        if(a,c)!=(totals['passes_attempted'],totals['passes_completed']):raise ValueError('Pass-map team counters differ')
        coverage.append(dict(side_index=side,state='available_complete_native_player_counter_closure',attempt_count=a,
            completed_count=c,not_completed_count=a-c,player_counter_checks=sum(p['side_index']==side for p in checks),
            in_pitch_count=sum(p['inside_native_pitch_extents']for p in own),outside_pitch_count=sum(not p['inside_native_pitch_extents']for p in own),
            unavailable_location_count=0))
    data['pass_event_locations']=dict(state=STATE,native_match_key=data['match_key'],points=expected,side_coverage=coverage,
        raw_frame_sha256=evidence['raw_frame_sha256'],raw_events_sha256=digest,native_event_count=len(raw)//56,
        complete_player_counter_checks=checks,geometry=geometry,
        location_semantics='official_pass_map_event_location; ball_release_location_not_proved',
        orientation='attacked goal at right using source-proved event direction; native lateral axis, human left/right unknown',
        coordinate_units=None,periods='full_match_only',
        limits=['points are native pass-map event locations, not ball-release points, trajectories or intended destinations',
                'all selected native pass-family events require every player counter to close; unlabelled mask8 events excluded',
                'outside-pitch locations remain counted and are not forced onto the pitch','no phase, pressure cause, displayed minutes or human left/right claim'])
    data['provenance'].append({**provenance,'role':'Counter-reconciled pass-map event locations'})
    return data
