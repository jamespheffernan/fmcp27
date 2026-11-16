"""Explicit tracking-sample density, distinct from the smoothed native heat map."""
import math
import struct
from collections import Counter
from .live_average_positions import decode_tracking_average_positions, tracking_positive_orientation, _f32


def decode_tracking_heatmaps(tracking, players, pitch_geometry, *, start_tick=None, end_tick=None, side_index=None, stored_player_slot=None):
    """Bin real retained position samples; each included sample has weight one.

    This transparent derived grid is NOT the native rendered HeatMap, whose
    movement interpolation, filters, normalization and smoothing differ.
    """
    if side_index is not None and(type(side_index)is not int or side_index not in(0,1)):
        raise ValueError('Invalid selected tracking side')
    if stored_player_slot is not None and(side_index is None or type(stored_player_slot)is not int or not 0<=stored_player_slot<26):
        raise ValueError('A selected player slot requires its side')
    for value in(start_tick,end_tick):
        if value is not None and(type(value)is not int or not 0<=value<=0x7fffffff):
            raise ValueError('Invalid native tracking cutoff')
    if start_tick is not None and end_tick is not None and start_tick>end_tick:
        raise ValueError('Reversed native tracking interval')
    averages=decode_tracking_average_positions(tracking,players)
    if not isinstance(pitch_geometry,dict):
        raise ValueError('Absent native pitch geometry')
    extents=[pitch_geometry.get(k)for k in('half_width_native','half_length_native')]
    if any(type(v)not in(int,float)or not math.isfinite(v)or not 0<v<1000 for v in extents):
        raise ValueError('Invalid native pitch geometry')
    names={(r['side_index'],r['stored_player_slot']):r for r in averages['players']}
    grids={0:Counter(),1:Counter()};team_counts={0:Counter(),1:Counter()};output=[]
    total=sum(len(row['samples'])//4 for row in tracking['players'])
    if total>1_000_000:
        raise ValueError('Tracking heatmap total sample budget exceeded')
    profile=tracking['orientation_profile'];scale=_f32(.01)
    for row in tracking['players']:
        side,slot=row['side_index'],row['stored_player_slot']
        if(side_index is not None and side!=side_index)or(stored_player_slot is not None and slot!=stored_player_slot):
            continue
        counts=Counter();grid=Counter();ticks=[]
        for index,pair in enumerate(struct.iter_unpack('<hh',row['samples'])):
            tick=row['start_tick']+index*24
            counts['retained_samples']+=1
            if(start_tick is not None and tick<start_tick)or(end_tick is not None and tick>end_tick):
                counts['outside_selected_ticks']+=1;continue
            counts['selected_samples']+=1;ticks.append(tick)
            multiplier=scale if tracking_positive_orientation(profile,side,tick)else -scale
            coords=[_f32(value*multiplier)for value in pair]
            if any(value < -half or value > half for value,half in zip(coords,extents)):
                counts['outside_native_pitch_bounds']+=1;continue
            bins=[min(size-1,int((value+half)/(2*half)*size))
                  for value,half,size in zip(coords,extents,(65,100))]
            grid[tuple(bins)]+=1;counts['binned_samples']+=1
        identity=names[side,slot]
        coverage={key:counts[key]for key in('retained_samples','selected_samples','outside_selected_ticks','outside_native_pitch_bounds','binned_samples')}
        coverage.update(first_selected_tick=min(ticks)if ticks else None,last_selected_tick=max(ticks)if ticks else None)
        output.append(dict(side_index=side,stored_player_slot=slot,
                           canonical_person_id=identity['canonical_person_id'],person_name=identity['person_name'],
                           state='available'if counts['binned_samples']else'unavailable_no_in_bounds_selected_samples',
                           coverage=coverage,cells=_cells(grid)))
        grids[side].update(grid);team_counts[side].update(counts)
    return dict(state='available'if any(grids.values())else'unavailable_no_in_bounds_selected_samples',
                source_kind='derived_retained_tracking_sample_density',
                method='one count per observed position sample; no movement interpolation or smoothing',
                official_rendered_heatmap_equivalence=False,
                axes={'axis_0':{'bins':65,'minimum':-extents[0],'maximum':extents[0]},
                      'axis_1':{'bins':100,'minimum':-extents[1],'maximum':extents[1]},
                      'orientation':'native4895a60 per-side/per-tick sign applied to both axes',
                      'physical_units':None,'human_left_right_viewpoint':None},
                sample_step_native_ticks=24,selected_side_index=side_index,selected_stored_player_slot=stored_player_slot,requested_start_tick=start_tick,requested_end_tick=end_tick,
                players=output,teams=[dict(side_index=side,players_with_samples=sum(r['side_index']==side and r['state']=='available'for r in output),
                                          coverage={key:team_counts[side][key]for key in('retained_samples','selected_samples','outside_selected_ticks','outside_native_pitch_bounds','binned_samples')},
                                          cells=_cells(grids[side]))for side in(0,1)],
                limitations=['position samples, not touch/event counts','sample availability does not prove continuous full-match tracking',
                             'tick cutoffs require independently proved period boundaries','not the official interpolated/smoothed HeatMap'])


def _cells(grid):
    return [{'axis_0_index':a,'axis_1_index':b,'sample_count':n}for(a,b),n in sorted(grid.items())]


# Native4a39e20 initializes these five float32 taps from52e0cc0.
_KERNEL=struct.unpack('<5f',bytes.fromhex('a7ebf53d6f7e6f3ebc8b953e6f7e6f3ea7ebf53d'))


def _native_normalize_smooth(grid):
    """Native1a7974..83e0: nonzero quantiles, two clamped five-tap passes."""
    from .live_average_positions import _fmaf
    nonzero=sorted(grid.values())
    if not nonzero:
        return [],{'state':'unavailable_no_interpolated_cells'}
    low=nonzero[int(_f32(_f32(len(nonzero))*_f32(.15)))]
    high=nonzero[int(_f32(_f32(len(nonzero)-1)*_f32(.95)))]
    denominator=high if high==low else high-low
    values=[[0.]*100 for _ in range(65)]
    for(a,b),count in grid.items():
        values[a][b]=min(1.,_f32(_f32(count-low)/_f32(denominator)))if count>low else 0.
    intermediate=[[0.]*100 for _ in range(65)]
    for a in range(65):
        for b in range(100):
            value=0.
            for delta,weight in zip(range(-2,3),_KERNEL):
                value=float(_fmaf(weight,values[min(64,max(0,a+delta))][b],value))
            intermediate[a][b]=value
    cells=[]
    for a in range(65):
        for b in range(100):
            value=0.
            for delta,weight in zip(range(-2,3),_KERNEL):
                value=float(_fmaf(intermediate[a][min(99,max(0,b+delta))],weight,value))
            if value>=_f32(.01):
                cells.append({'axis_0_index':a,'axis_1_index':b,'normalized_intensity':value})
    return cells,dict(state='native_algorithm_reconstructed',nonzero_raw_cell_count=len(nonzero),
                      lower_count_quantile=low,upper_count_quantile=high,
                      normalization_denominator=denominator,smoothing_kernel=list(_KERNEL),
                      threshold=_f32(.01),normalization_scope='independent for this map; not a shared player/team intensity scale')


def decode_native_tracking_heatmaps(tracking,players,pitch_geometry,*,start_tick=None,end_tick=None,
                                    side_index=None,stored_player_slot=None):
    """Reconstruct the all-phase native HeatMap geometry and postprocessing.

    Team maps pool raw interpolation counts before normalization; no official
    pooled-team renderer equivalence is claimed. No displayed UI oracle used.
    """
    from .live_average_positions import _fmaf
    checked=decode_tracking_heatmaps(tracking,players,pitch_geometry,start_tick=start_tick,end_tick=end_tick,
                                    side_index=side_index,stored_player_slot=stored_player_slot)
    names={(r['side_index'],r['stored_player_slot']):r for r in checked['players']}
    profile=tracking['orientation_profile'];half=[pitch_geometry[k]for k in('half_width_native','half_length_native')]
    cell_width=[_f32(_f32(v+v)/n)for v,n in zip(half,(65,100))]
    team_grids={0:Counter(),1:Counter()};team_coverage={0:Counter(),1:Counter()};output=[]
    scale=_f32(.01)
    for row in tracking['players']:
        side,slot=row['side_index'],row['stored_player_slot']
        if(side,slot)not in names:continue
        pairs=list(struct.iter_unpack('<hh',row['samples']));grid=Counter();coverage=Counter()
        coverage['zero_pair_samples']=sum(p==(0,0)for p in pairs)
        for pair in reversed(pairs):
            if pair!=(0,0):break
            coverage['trailing_zero_pairs']+=1
        for index in range(1,len(pairs)):
            tick=row['start_tick']+index*24;coverage['retained_segments']+=1
            if(start_tick is not None and tick<start_tick)or(end_tick is not None and tick>end_tick):
                coverage['outside_selected_ticks']+=1;continue
            coverage['selected_segments']+=1
            previous,current=pairs[index-1],pairs[index]
            if previous!=(0,0)and current==(0,0):coverage['nonzero_to_zero_segments']+=1
            if previous==(0,0)and current!=(0,0):coverage['zero_to_nonzero_segments']+=1
            if previous==current:
                coverage['duplicate_position_segments_skipped']+=1;continue
            multiplier=scale if tracking_positive_orientation(profile,side,tick)else -scale
            origin=[_f32(v*multiplier)for v in previous];destination=[_f32(v*multiplier)for v in current]
            delta=[_f32(b-a)for a,b in zip(origin,destination)]
            distance=float(_fmaf(delta[0],delta[0],_f32(delta[1]*delta[1])))
            if distance>3600.:
                coverage['over_60_native_unit_segments_skipped']+=1;continue
            coverage['interpolated_segments']+=1
            for step in range(60):
                fraction=_f32(_f32(_f32(step)*_f32(.1))/_f32(6.))
                bins=[]
                for a in(0,1):
                    position=float(_fmaf(fraction,delta[a],origin[a]))
                    bins.append(int(_f32(_f32(position+half[a])/cell_width[a])))
                if 0<=bins[0]<65 and 0<=bins[1]<100:
                    grid[tuple(bins)]+=1;coverage['interpolated_points_binned']+=1
                else:coverage['interpolated_points_outside_grid']+=1
        cells,processing=_native_normalize_smooth(grid)
        identity=names[side,slot]
        output.append(dict(side_index=side,stored_player_slot=slot,canonical_person_id=identity['canonical_person_id'],
                           person_name=identity['person_name'],state='available'if grid else'unavailable_no_interpolated_cells',
                           coverage=dict(coverage),raw_cells=[{'axis_0_index':a,'axis_1_index':b,'interpolation_count':v}for(a,b),v in sorted(grid.items())],
                           cells=cells,postprocessing=processing))
        team_grids[side].update(grid);team_coverage[side].update(coverage)
    teams=[]
    for side in(0,1):
        cells,processing=_native_normalize_smooth(team_grids[side])
        teams.append(dict(side_index=side,source_kind='derived_pooled_player_native_interpolation_counts',
                          coverage=dict(team_coverage[side]),cells=cells,postprocessing=processing,
                          raw_cells=[{'axis_0_index':a,'axis_1_index':b,'interpolation_count':v}for(a,b),v in sorted(team_grids[side].items())]))
    return dict(state='available'if any(team_grids.values())else'unavailable_no_interpolated_cells',
                source_kind='reconstructed_native_all_phase_heatmap_algorithm',axes=checked['axes'],
                requested_start_tick=start_tick,requested_end_tick=end_tick,selected_side_index=side_index,
                selected_stored_player_slot=stored_player_slot,players=output,teams=teams,
                cutoff_applies_to='current segment sample tick; previous endpoint may precede start cutoff',
                ui_oracle_verified=False,possession_filtering='all phases only; phase-filter semantics not exposed',
                native_processing='60 float32/FMA interpolants per movement segment;15/95 nonzero quantile scaling;separable5tap clamp-edge smoothing;zero below.01',
                limitations=['physical units and human viewing perspective unproved','independently normalized maps cannot compare absolute intensity',
                             'team pooled grids are derived, not an independently bound native team map',
                             'trailing zero pairs may be post-exit padding; native repeated-position exclusion removes stationary hotspots but one valid-to-zero transition can draw a centerward segment',
                             'tick cutoffs are supplied from independent period proof, never hardcoded'])


HEATMAP_NATIVE_SPANS = ((1733952, b"\xe0'@\xf9\xe47\x00\xb9\xe1\x03\x04\xaa\xe2\x03\x18\xaa\xd0\xbc\x1b\x95\x00\x95\x00\xb4\xfc\x03\x00\xaa\x08\xa4@\xa9\x1f\x01\t\xeb\x80\x94\x00T\xfbc\x08)\xf6k\x03)"), (1734052, b"\x88\xa7@\xa9\xe9+\x00\xf9\x1f\x01\t\xeb\xc0\x13\x00T\x19\x00\x80\xd2\xe9'@\xf9(\x01A\xbd)\x05A\xbd\x00)(\x1eIP\xa8R!\x01'\x1e\n\x18!\x1e ))\x1e\tY\xa8R!\x01'\x1e\x9c\x03@\xb9X\x00\x80R\xbb\x99\x99R\x9b\xb9\xa7r\x0b\x18!\x1e"), (1734292, b'(\x03@yI\x03@y\x1f\x01\tk\xa1\x00\x00T(\x07@yI\x07@y\x1f\x01\tk`\xfa\xffT\xe0\'@\xf9\xe1G@\xb9\xe2\x03\x1c\xaa\xe8\xb8\x1b\x95 \x03@}\x00\xa4\x10\x0f\x00\xd8!^\x1f\x00\x00qH\xe1\x9aRh\x84\xb7r\x01\x01\'\x1eH\xe1\x9aRh\x84\xa7r\x02\x01\'\x1eA\x1c!\x1e"\x08 \x1e \x07@}\x00\xa4\x10\x0f\x00\xd8!^#\x08 \x1e@\x03@}\x00\xa4\x10\x0f\x00\xd8!^ \x08 \x1eD\x07@}\x84\xa4\x10\x0f\x84\xd8!^!\x08$\x1eB8 \x1ec8!\x1ed\x08#\x1eD\x10\x02\x1f(\xac\xa8R\x05\x01\'\x1e\x80 %\x1e\xec\xf5\xffT'), (1734548, b"\t\x00\x80R\x04\x00\x00\x14)\x05\x00\x11_\xed\x00q\xc2\xf2\xffT*=\x00\x12_u\x00q\x0b\x95\x9f\x1a_y\x00q\x8c&\x9f\x1a\x7f\x05\x00q\x84\t@z\xc0\xfe\xffTD\x01#\x1ee\x03'\x1e\x84\x08%\x1e\x84\x18,\x1e\x85\x00\x02\x1f\x05)%\x1e\xa5\x18*\x1e\xab\x008\x1e\x7f\x01\x01q\x88\xfd\xffT\x84\x04\x03\x1f$)$\x1e\x84\x18+\x1e\x8c\x008\x1e\x9f\x8d\x01q\xc8\xfc\xffT\xed3@\x91\xad\x813\x91\x0e2\x80Rk5.\x9bm\xd9l\xb8\xad\x05\x00\x11m\xd9,\xb8\xde\xff\xff\x17"), (1735028, b'\xbf\x02\x1c\xeb\x80n\x00T\x88\x03\x15\xcb\x16\xfdB\x93\xc0\x02#\x9eH3\x93R(\xc3\xa7r\x01\x01\'\x1e\x00\x08!\x1e\x13\x009\x9e\xb4\n\x13\x8b\x9f\x02\x1c\xeb\xe0\x00\x00T\xe3\x1b@\x91c\xe0\x1c\x91\xe0\x03\x15\xaa\xe1\x03\x14\xaa\xe2\x03\x1c\xaa\x1d\'\x00\x94\xc8\x06\x00\xd1\x00\x01#\x9ehf\x86Rh\xee\xa7r\x01\x01\'\x1e\x00\x08!\x1e\x16\x009\x9e\xb3zs\xb8\xa1\n\x16\x8b?\x00\x1c\xeb\xc0\x00\x00T\xe3\x1b@\x91c\xe0\x1c\x91\xe0\x03\x14\xaa\xe2\x03\x1c\xaa\r\'\x00\x94\xa8zv\xb8\x1f\x01\x13k\xe9\x03\x93\x1a\x08\x01\tK\x00\x01"\x1e\xe0\x17\x80=\xf4\x1b@\x91'), (1736080, b'\x08\x00\x80\xd2\xd4\xab\x02\xf0\x94\x020\x91\x80\x02\xc0=\x81B\xc0<\x82\x06@\xfd\x83\xc2@\xfc\x00\x04\x04N!\x04\x04N\x90B\x00\x91B\x04\x04Nc\x04\x04N\xe9\x1b@\x91)\xe1\x1c\x91*\x01\x06\x91+\x01\x01\x91,\x01\x02\x91-\x01\x03\x91.\x01\x04\x91/\x01\x05\x91\x04\xca@M\xd0\x02\x03\x91\x11\x08\x80\x92\x00\x08\x80R\x012\x80R"\xfe\x00\x11C|\xa2\ns$\xa1\x9bf\x16@\xad'), (1737320, b"\xe0\xe3\x05\x91yY\t\x95\xe0\xe3\x05\x91\x81\x0c\x80R\xf56\xfa\x97\x082\x80R\xd8^\x08\x9b\x80\x06@-\t+@- !\x00\x1f \x01\x01\x1f\x81\nA- \x01\x01\x1f@\x01\x02\x1f\x0b\x0b@\xbd\x81\x12@\xbd`\x01\x01\x1fa\x03'\x1e\x00 !\x1e\x00M \x1e\xe0C\x05\x913o\t\x95"), (1737504, b"3\x0c\x80\x92\xf9\x03\x1a\xaa \x07\x7f-\x82\x0e@-\x00 \x02\x1f \x00\x03\x1f!\x03@\xbd\x82\x0eA- \x00\x02\x1fh\x96\x01\x11\x1f\x8d\x01q\x08\xb1\x9c\x1a\x08}\xa8\n\x01[h\xbch\x9a\x01\x11\x1f\x8d\x01q\x08\xb1\x9c\x1a\x08}\xa8\n\x02[h\xbc \x00\x03\x1f\x81\x12@\xbd@\x00\x01\x1fa\x03'\x1e\x00 !\x1e\x00M \x1e\xe0C\x05\x91\x00o\t\x95"), (77831712, b'\xf4O\xbe\xa9\xfd{\x01\xa9\xfdC\x00\x91Sg\x00\xb0s\xc2/\x91\xe0\x03\x13\xaa^\xd2\x02\x94`\x01\x004(E\x00\xf0\x001\xc3=`\x06\x80=\xe8t\x9dR\xa8\xbe\xa7rh"\x00\xb9'), (86904000, b'\xa7\xeb\xf5=o~o>\xbc\x8b\x95>o~o>'), (1738336, b'\xf3\x03\x00\xf9\xe0\xe3\x04\x91\xe1\xc3\x04\x91\xe4c\x04\x91\xe5C\x03\x91\xe6c\x02\x91\xe7\x03\x02\x91"\x08\x80R\x83\x0c\x80Rf%\x00\x94'), (1776784, b"\xe1\x03\x19\xaa\x8bH\t\x95\xe2\x03\x00\x91\xe0\x03\x13\xaa\xe1\x8e\x8cR!j\xa9r\x8f\x15\t\x95\xe0\x03\x00\x91\xc0G\t\x95\xe0\x03\x00\x91\xe1\x03\x18\xaa\x81H\t\x95\xe2\x03\x00\x91\xe0\x03\x13\xaa\xc1J\x86R\x01'\xabr\x85\x15\t\x95"))


def verify_native_heatmap(read,base):
    for rva,expected in HEATMAP_NATIVE_SPANS:
        if read(base+rva,len(expected))!=expected:
            raise ValueError("Native tracking heatmap binding changed")
