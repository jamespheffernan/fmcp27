"""Same-tick in-possession lateral width; no movement/marking inference."""
import hashlib
import math
import struct
from .live_average_positions import decode_tracking_average_positions,tracking_positive_orientation,_f32


def _summary(rows, identities, half_width=None):
    n=len(rows);aw=sum(abs(a[0])for _,a,b in rows);bw=sum(abs(b[0])for _,a,b in rows)
    counts=[sum(abs(a[0])>abs(b[0])for _,a,b in rows),sum(abs(b[0])>abs(a[0])for _,a,b in rows),sum(abs(a[0])==abs(b[0])for _,a,b in rows)]
    result=dict(sample_count=n,first_tick=rows[0][0]if rows else None,last_tick=rows[-1][0]if rows else None,
        players=[dict(**identity,mean_absolute_lateral_native=_f32(total*_f32(.01)/n)if n else None,
                      wider_sample_count=count,wider_percentage_computed=100*count/n if n else None)
                 for identity,total,count in zip(identities,(aw,bw),counts[:2])],
        equal_width_sample_count=counts[2],equal_width_percentage_computed=100*counts[2]/n if n else None,
        signed_width_difference_mean_native=_f32((aw-bw)*_f32(.01)/n)if n else None)
    if half_width is not None:
        threshold=half_width/3
        both=sum(abs(a[0])*_f32(.01)>=threshold and abs(b[0])*_f32(.01)>=threshold and a[0]*b[0]>0 for _,a,b in rows)
        result['both_wide_same_lateral_side']=dict(sample_count=both,denominator=n,percentage_computed=100*both/n if n else None,
            threshold_absolute_lateral_native=threshold,definition='Both in the same analytical outer pitch-width third; abs(axis0)>=half_width/3 and same nonzero sign. Not a tactical wide-role classification.')
    else:result['both_wide_same_lateral_side']=None
    return result


def project(tracking, players, person_a, person_b, *, pitch_geometry=None):
    if any(type(p)is not int or p<=0 for p in(person_a,person_b))or person_a==person_b:
        raise ValueError('Select two distinct canonical player IDs')
    decoded=decode_tracking_average_positions(tracking,players)
    selected=[]
    for person in(person_a,person_b):
        found=[p for p in decoded['players']if p['canonical_person_id']==person]
        if len(found)!=1:return dict(state='unavailable_selected_player_tracking',comparison=None)
        selected.append(found[0])
    if selected[0]['side_index']!=selected[1]['side_index']:raise ValueError('Selected players must belong to the same fixture side')
    side=selected[0]['side_index'];identities=[{k:p[k]for k in('canonical_person_id','person_name','stored_player_slot')}for p in selected]
    streams=[];metadata=[]
    for player in selected:
        row=next(r for r in tracking['players']if(r['side_index'],r['stored_player_slot'])==(side,player['stored_player_slot']))
        pairs=list(struct.iter_unpack('<hh',row['samples']));stream={row['start_tick']+i*24:pair for i,pair in enumerate(pairs)};streams.append(stream)
        tail=player['coverage']['trailing_zero_pair_sample_count']
        metadata.append(dict(**{k:player[k]for k in('canonical_person_id','person_name','sample_count','sample_start_tick','coverage')},
                             last_tick=max(stream)if stream else None,tail_start_tick=(row['start_tick']+(len(pairs)-tail)*24)if tail else None))
    common=sorted(streams[0].keys()&streams[1].keys());phases=tracking.get('possession_samples')
    coverage=dict(coincident_position_ticks=len(common),first_coincident_tick=common[0]if common else None,last_coincident_tick=common[-1]if common else None,
        unmatched_samples=[len(s)-len(common)for s in streams],phase_uncovered_ticks=0,phase_unclassified_ticks=0,phase_other_ticks=0,out_of_possession_ticks=0,
        in_possession_ticks=0,zero_pair_ticks_either=0,zero_pair_ticks_both=0,trailing_zero_ticks_either=0,outside_pitch_bounds_ticks_either=None)
    base=dict(side_index=side,players=metadata,coverage=coverage,sample_step_native_ticks=24,
        coincidence_policy='Exact equal native tracking tick; no nearest-point alignment, interpolation or interval inference.',
        phase_policy='Actual possession byte at tick//24 must equal the same side. Missing/beyond-stream,255 and other non-side bytes excluded and counted; no end-byte clamping.',
        lateral_axis='native_axis_0_verified_pitch_width',physical_units=None,human_left_right=None,
        limits='Co-recorded position samples are not validated shared on-pitch minutes, overlapping/underlapping runs, marking, space created or tactical effect. Known zero pairs/tails remain in all-sample results; filtered views are sensitivity controls, not corrected official positions.')
    if not common:return dict(base,state='unavailable_no_coincident_tracking_ticks',comparison=None)
    if not phases:return dict(base,state='unavailable_possession_stream',comparison=None)
    extents=None
    if pitch_geometry is not None:
        extents=[pitch_geometry.get(k)for k in('half_width_native','half_length_native')]
        if any(type(v)not in(int,float)or not math.isfinite(v)or not 0<v<1000 for v in extents):raise ValueError('Invalid pitch bounds')
        coverage['outside_pitch_bounds_ticks_either']=0
    all_rows=[];nonzero=[];inbounds=[]
    for tick in common:
        index=tick//24
        if index>=len(phases):coverage['phase_uncovered_ticks']+=1;continue
        phase=phases[index]
        if phase==255:coverage['phase_unclassified_ticks']+=1;continue
        if phase not in(0,1):coverage['phase_other_ticks']+=1;continue
        if phase!=side:coverage['out_of_possession_ticks']+=1;continue
        coverage['in_possession_ticks']+=1
        a,b=(s[tick]for s in streams);az,bz=a==(0,0),b==(0,0)
        coverage['zero_pair_ticks_either']+=az or bz;coverage['zero_pair_ticks_both']+=az and bz
        coverage['trailing_zero_ticks_either']+=any(m['tail_start_tick']is not None and tick>=m['tail_start_tick']for m in metadata)
        sign=1 if tracking_positive_orientation(tracking['orientation_profile'],side,tick)else -1
        a,b=tuple(v*sign for v in a),tuple(v*sign for v in b)
        row=(tick,a,b);all_rows.append(row)
        bounded=extents is not None and all(abs(v)*_f32(.01)<=half for pair in(a,b)for v,half in zip(pair,extents))
        if extents is not None:coverage['outside_pitch_bounds_ticks_either']+=not bounded
        if not az and not bz:
            nonzero.append(row)
            if bounded:inbounds.append(row)
    return dict(base,state='available'if all_rows else'unavailable_no_coincident_in_possession_ticks',
        comparison=dict(all_coincident_in_possession=_summary(all_rows,identities),
                        nonzero_pair_sensitivity=_summary(nonzero,identities),
                        in_bounds_nonzero_pair_sensitivity=_summary(inbounds,identities,extents[0])if extents else None))


def report(bridge,session_id,fixture_ref,person_a,person_b):
    from . import live_retained_shots as retained,players,current_spatial_axes
    from .live_retained_passes import decode_pass_network,_verify_pass_native
    from .match_data_query import capture_live,capture_epoch
    epoch=capture_epoch(bridge,session_id);packet=capture_live(bridge,session_id,[fixture_ref],include_players=True)
    if packet.get('_live_capture_epoch')!=epoch:raise ValueError('Retained capture epoch differs')
    items=packet['capture']['fixtures']
    if len(items)!=1 or items[0]['fixture']['fixture_ref']!=fixture_ref:raise ValueError('Exact selected retained fixture required')
    fixture,key=items[0]['fixture'],items[0]['native_match_key']
    totals=[r for r in packet['team_totals']['records']if r['result_key']==key]
    if len(totals)!=1:return dict(state='unavailable_team_oracle',comparison=None)
    retained._validate_team_oracle(fixture,totals[0]['teams'])
    roster=[p for p in packet['retained_players']if p.get('fixture_key',p.get('native_match_key'))==key]
    if not roster or len(retained._validated_actors(roster,totals[0]['teams']))!=len(roster):return dict(state='unavailable_fixture_roster',comparison=None)
    _verify_pass_native(bridge,session_id)
    with bridge.lock,bridge._read_scope(session_id):
        process=bridge._current(session_id);tables=bridge._player_layout(process);read,_,_=bridge._world_state(process,tables)
        current_spatial_axes.verify_native(read,tables[0]-players.RVA[0]);read.verify();bridge._current(session_id)
    source=retained.capture_source(bridge,session_id,fixture_ref,key,fixture,include_tracking=True)
    if source['state']!='available':return dict(state=source['state'],comparison=None)
    tracking=source.get('tracking')
    if not isinstance(tracking,dict) or tracking.get('state')!='available':
        return dict(state=tracking.get('state','unavailable_tracking_source')if isinstance(tracking,dict)else'unavailable_tracking_source',
                    reason='retained_source_has_no_available_tracking',fixture=fixture,native_match_key=key,comparison=None,
                    source_kind='same_fixture_retained_tracking_exact_tick_comparison',saved_file_fallback=False,atomic=False)
    if any(s['state']!='available'for s in decode_pass_network(source['events'],roster)['sides']):return dict(state='unavailable_tracking_roster_reconciliation',comparison=None)
    result=project(source['tracking'],roster,person_a,person_b,pitch_geometry=source.get('pitch_geometry'))
    fresh=retained.capture_source(bridge,session_id,fixture_ref,key,fixture,include_tracking=True)
    if (fresh.get('state')!='available'or any(fresh.get(k)!=source.get(k)for k in('events','tracking','pitch_geometry'))or capture_epoch(bridge,session_id)!=epoch):raise ValueError('Paired tracking source changed')
    return dict(result,fixture=fixture,native_match_key=key,captured_save=packet['capture']['save'],
                source_kind='same_fixture_retained_tracking_exact_tick_comparison',source_id=hashlib.sha256(source['events']+repr(source['tracking']).encode()).hexdigest(),
                saved_file_fallback=False,atomic=False,source_rechecked=True)
