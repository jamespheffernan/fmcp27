"""Offline heat-map projection of a fully bookended current playback prefix."""
from . import active_match_tracking
from .live_tracking_heatmaps import decode_tracking_heatmaps, decode_native_tracking_heatmaps


def _fixture_identity(fixture):
    return (fixture['date'], fixture['competition']['native_id'],
            *((fixture[k]['database_index'], fixture[k]['native_id']) for k in ('home_team','away_team')))


def project(source,bound,actors,fixture,*,prefix_verification,team_native_id,person_native_id=None,
            method='sample_density',grid='compact'):
    """No reads: caller must finish fixture/actor/prefix/career bookends first."""
    if type(team_native_id)is not int or team_native_id<=0:
        raise ValueError('Select a canonical participating team ID')
    if person_native_id is not None and(type(person_native_id)is not int or person_native_id<=0):
        raise ValueError('Invalid selected canonical player ID')
    if method not in('sample_density','interpolated')or grid not in('compact','native'):
        raise ValueError('Unknown active heat-map method or grid')
    if grid=='native'and person_native_id is None:
        raise ValueError('A native-resolution active heat map requires one player')
    sides=[i for i,k in enumerate(('home_team','away_team'))if fixture[k]['native_id']==team_native_id]
    if len(sides)!=1:
        raise ValueError('Select exactly one team from the active fixture')
    side=sides[0]
    expected=_fixture_identity(fixture)
    # JSON test/proof packets can preserve tuples as lists; canonicalize them.
    actual=source.get('fixture_identity')
    if not isinstance(actual,(tuple,list))or tuple(actual[:2])!=expected[:2]or len(actual)!=4 or tuple(map(tuple,actual[2:]))!=expected[2:]:
        raise ValueError('Active heat-map fixture differs from captured source')
    cursor=bound.get('current_time_slice');identity=bound.get('official_match_unique_id')
    if type(cursor)is not int or not 0<=cursor<65536 or type(identity)is not int or identity<=0:
        raise ValueError('Invalid bound active heat-map identity or cursor')
    checked=prefix_verification
    if(not isinstance(checked,dict)or checked.get('state')!='verified_fixed_prefix_under_monotonic_same_match_playback'
       or checked.get('official_match_unique_id')!=identity or checked.get('current_time_slice')!=cursor
       or type(checked.get('verified_at_time_slice'))is not int or checked['verified_at_time_slice']<cursor
       or checked.get('canonical_actor_ids_rechecked')is not True or checked.get('same_match_ownership_rechecked')is not True):
        raise ValueError('Active heat map requires completed same-match prefix/actor verification')
    selected=active_match_tracking.clip_tracking(source.get('tracking',{}),cursor)
    sample_count=sum(len(r['samples'])//4 for r in selected['players'])
    if type(checked.get('selected_sample_count'))is not int or checked['selected_sample_count']!=sample_count:
        raise ValueError('Verified active heat-map prefix sample count differs')
    players=[r for r in actors.get('players',[])if isinstance(r.get('person_name'),str)and r['person_name']]
    scope=active_match_tracking.project(source,bound,players,actor_binding=actors)
    base=dict(state='unavailable',reason=None,source_kind='active_verified_playback_tracking_heatmap',
              team_native_id=team_native_id,person_native_id=person_native_id,current_time_slice=cursor,
              source_id=scope.get('selected_source_sha256'),heat_map=None,
              temporal_scope='fixed verified playback prefix only; no future points or entrants',
              native_tracking_clock_domain_verified=scope.get('native_tracking_clock_domain_verified',False),
              displayed_pixels_verified=False,displayed_minute=None,saved_file_fallback=False,
              computed_offline_after_source_verification=True)
    if scope['state']not in('available','available_partial'):
        return {**base,'reason':scope.get('reason')or scope['state']}
    known={(r['side_index'],r['stored_player_slot']):r for r in scope['players']}
    rows=[r for r in selected['players']if r['side_index']==side and(r['side_index'],r['stored_player_slot'])in known
          and(person_native_id is None or known[r['side_index'],r['stored_player_slot']]['canonical_person_id']==person_native_id)]
    if not rows:
        return {**base,'reason':'unavailable_no_selected_player_or_team_tracking_prefix'}
    geometry=source.get('pitch_geometry')
    if geometry is None:
        return {**base,'reason':'unavailable_active_pitch_geometry'}
    eligible={**selected,'players':rows}
    names=[r for r in players if(r['side_index'],r['stored_player_slot'])in{(r['side_index'],r['stored_player_slot'])for r in rows}]
    decode=decode_native_tracking_heatmaps if method=='interpolated'else decode_tracking_heatmaps
    density=decode(eligible,names,geometry)
    selected_map=(density['teams'][side]if person_native_id is None else density['players'][0])
    resolution=(65,100)if grid=='native'else(13,20)
    bins=[[0.]*resolution[0]for _ in range(resolution[1])]
    for cell in selected_map['cells']:
        x=cell['axis_0_index']*resolution[0]//65;y=cell['axis_1_index']*resolution[1]//100
        bins[y][x]+=cell['normalized_intensity']if method=='interpolated'else cell['sample_count']
    unresolved=[r for r in scope.get('unresolved_tracking_actors',[])if r['side_index']==side]
    coverage={**selected_map['coverage'],'selected_named_player_count':len(rows),
              'unresolved_selected_side_player_count':len(unresolved),
              'unresolved_selected_side_sample_count':sum(r['sample_count']for r in unresolved),
              'verified_prefix_sample_count_all_sides':sample_count}
    heat=dict(method=method,coverage=coverage,axes=density['axes'],grid_width=resolution[0],grid_length=resolution[1],
              ui_verified=False,tracking_note='Measured position samples, not touch events. Zero/post-exit tails can bias density; native movement reconstruction can retain a centreward transition.',
              scope='selected named current-prefix team pool'if person_native_id is None else'individual current-prefix tracking')
    if method=='interpolated':
        divisor=6500//(resolution[0]*resolution[1])
        heat.update(mean_intensity_by_length_then_width=[[v/divisor for v in r]for r in bins],
                    normalization=selected_map['postprocessing'],
                    source_kind=selected_map.get('source_kind',density['source_kind']),
                    description='Reconstructed native movement interpolation/normalization/smoothing; not an observed UI heat map')
    else:
        heat.update(counts_by_length_then_width=[[int(v)for v in r]for r in bins],description=density['method'])
    return {**base,'state':'available_partial'if unresolved else'available','reason':'unresolved_selected_side_tracking_actors'if unresolved else None,
            'heat_map':heat,'selected_players':[{'canonical_person_id':r['canonical_person_id'],'person_name':r['person_name'],
                'stored_player_slot':r['stored_player_slot']}for r in names]}
