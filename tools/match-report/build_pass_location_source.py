#!/usr/bin/env python3
"""Reconstruct source-proved event points offline from a captured native CBE."""
import argparse,hashlib,json,struct,sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
from fm_live_mcp.live_retained_pass_events import decode_pass_attempts,ATTEMPT_NATIVE_SPANS
from fm_live_mcp.live_retained_passes import PASS_NATIVE_SPANS
from fm_live_mcp import build_paths, pass_field_position
from pass_location_evidence import STATE,_identity,add_pass_location_evidence


def raw(value):
    b=bytes.fromhex(value['_bytes_hex'])
    if hashlib.sha256(b).hexdigest()!=value['sha256']:raise ValueError('Captured byte receipt hash differs')
    return b


def static_bindings(path):
    checks=[]
    with path.open('rb')as f:
        h=f.read(4096)
        if h[:4]!=bytes.fromhex('cafebabe'):raise ValueError('Expected universal native plugin')
        count=struct.unpack_from('>I',h,4)[0]
        if not 1<=count<=32:raise ValueError('Invalid native plugin slice count')
        arm=next(x for x in(struct.unpack_from('>5I',h,8+20*i)for i in range(count))if x[0]==0x100000c);offset=arm[2]
        f.seek(offset);h=f.read(16384)
        if struct.unpack_from('<II',h)!=(0xfeedfacf,0x100000c):raise ValueError('Expected native ARM64 Mach-O')
        n,size=struct.unpack_from('<II',h,16);pos=32;segments=[]
        if n>256 or size>len(h)-32:raise ValueError('Invalid native load commands')
        for _ in range(n):
            cmd,length=struct.unpack_from('<II',h,pos)
            if cmd==0x19:
                name,vm,vs,fo,fs=struct.unpack_from('<16sQQQQ',h,pos+8);segments.append((vm,fo,fs))
            pos+=length
        for at,expected in ATTEMPT_NATIVE_SPANS+PASS_NATIVE_SPANS+pass_field_position.NATIVE_SPANS:
            vm,fo,fs=next(s for s in segments if s[0]<=at and at+len(expected)<=s[0]+s[2])
            f.seek(offset+fo+at-vm);actual=f.read(len(expected))
            if actual!=expected:raise ValueError('Installed native pass-map binding differs')
            checks.append({'rva':hex(at),'bytes':len(actual),'sha256':hashlib.sha256(actual).hexdigest()})
    return {'state':'verified_expected_installed_native_pass_map_spans','checks':checks,'calls':False,'source':'installed binary bytes only; no process attachment'}


def build(capture_path,source_path):
    c=json.loads(capture_path.read_text());s=json.loads(source_path.read_text());source=s['source'];key=s['native_match_key'];fixture=s['fixture']
    f,=[x for x in c['capture']['fixtures']if x['native_match_key']==key]
    if not c['receipt']['same_native_epoch_verified']or _identity(f['fixture'])!=_identity(fixture):raise ValueError('Captured fixture identity differs')
    events=raw(source['events']);geometry=source['pitch_geometry'];g=struct.unpack('<ff',raw(source['pitch_geometry_raw']))
    if g!=(geometry['half_width_native'],geometry['half_length_native']):raise ValueError('Captured pitch geometry bytes differ')
    frame,=[r for r in c['raw_frames']if r['key']==key]
    if hashlib.sha256(raw(frame['raw'])).hexdigest()!=frame['raw_sha256']:raise ValueError('Captured match raw frame differs')
    decoded=decode_pass_attempts(events,c['retained_players'],pitch_geometry=geometry)
    if decoded['state']!='available':raise ValueError('Complete native pass counter closure is required')
    points=[]
    for row in decoded['attempts']:
        p=row['field_position'];xy=p['native_pass_map_location']
        points.append({k:row[k]for k in('event_id','record_index','side_index','stored_player_slot','person_native_id','person_name','native_category_code','completed','native_flags_word','recipient_person_native_id','recipient_name')}|{
            'native_x':xy['native_x'],'native_y':xy['native_y'],'attacked_goal_positive_native_y':p['attacked_goal_positive_native_y'],
            'attack_relative_longitudinal_coordinate':p['attack_relative_longitudinal_coordinate'],'inside_native_pitch_extents':p['inside_native_pitch_extents'],
            'analytical_pitch_third':p['analytical_pitch_third'],'analytical_lateral_channel':p['analytical_lateral_channel']})
    out={'state':STATE,'native_match_key':key,'fixture':fixture,'raw_frame_sha256':frame['raw_sha256'],
         'raw_events_sha256':hashlib.sha256(events).hexdigest(),'source_events_hex':events.hex(),'pitch_geometry':geometry,'points':points,
         'source_capture_sha256':hashlib.sha256(capture_path.read_bytes()).hexdigest(),'source_cbe_capture_sha256':hashlib.sha256(source_path.read_bytes()).hexdigest(),
         'native_binding_proof':static_bindings(build_paths.pinned_path(build_paths.PLUGIN_IN_APP))}
    minimal={'match_key':key,'fixture':fixture,'geometry':geometry,'team_totals':c['team_totals']['records'][0]['teams'],
       'players':[{'side':p['side_index'],'slot':p['stored_player_slot'],'id':p['canonical_person_id'],'name':p['person_name'],
                   'passes_attempted':p['passes_attempted'],'passes_completed':p['passes_completed'],'source_row_sha256':p['row_sha256']}for p in c['retained_players']],'provenance':[]}
    checked=add_pass_location_evidence(minimal,(c,{}),(out,{}))['pass_event_locations']
    out['side_coverage']=checked['side_coverage'];out['complete_player_counter_checks']=checked['complete_player_counter_checks']
    return out


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture',type=Path,required=True);p.add_argument('--cbe-source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    value=build(a.capture,a.cbe_source);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output':str(a.output),'state':value['state'],'points':len(value['points']),'sides':value['side_coverage']}))
