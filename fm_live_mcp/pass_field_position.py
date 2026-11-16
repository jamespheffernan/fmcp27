"""Source-qualified pass-map event positions: where each pass was played from, and where its
stored path ends.

Caller owns canonical fixture/CBE/actor/counter binding and one ReadSet/epoch.
Equal thirds below are explicit analytical bins, not official FM location bins.

The event point is the pass origin (docs/retained-pass-events.md, "Where the point is"): it is
the first sample of the ball's stored path on every pass, both kick-offs of a match sit on the
centre spot, throw-ins on the touchline and corners at the flag. The last path sample is the
location of the event the pass links to (fmdb/match_pass_decode.py): for a completed pass, the
named recipient taking the ball.
"""
import math
import struct

LOCATION_SEMANTICS = 'official_pass_map_event_location; pass_origin_proved'
# What the last stored path sample is, by native pass category (fmdb/match_pass_decode.py).
ENDPOINT_SEMANTICS = {7: 'reception_by_named_recipient', 8: 'opponent_won_ball',
                      9: 'opponent_blocked_or_cleared', 10: 'engine_target_point', 11: 'out_of_play'}


def _bins(x, forward, width, length):
    inside=abs(x)<=width and abs(forward)<=length
    third=('defensive' if forward < -length/3 else 'middle' if forward < length/3 else 'attacking') if inside else None
    channel=('central' if abs(x)<=width/3 else 'outer') if inside else None
    return inside,third,channel


def verify_native(read, base):
    for rva, expected in NATIVE_SPANS:
        if read(base+rva,len(expected)) != expected:
            raise ValueError('Pass event field-position native source changed')


def project_event_location(event, pitch_geometry, *, expected_event_id,
                           expected_side_index, expected_player_slot, path=None):
    """Project one separately selected pass record with exact identity guards.

    path, when supplied, is {event_id, raw_xy_pairs:bytes}. Its last sample is
    reported as sampled_path_endpoint with the same thirds and channels and a
    semantics label from ENDPOINT_SEMANTICS; it is never an intended receiver.
    """
    if not isinstance(event,bytes) or len(event)!=56:
        raise ValueError('Expected one complete native CBE event')
    if (type(expected_event_id) is not int or not 0<=expected_event_id<1<<32
            or type(expected_side_index) is not int or expected_side_index not in (0,1)
            or type(expected_player_slot) is not int or not 0<=expected_player_slot<26):
        raise ValueError('Checked event, side and original roster slot required')
    event_id=struct.unpack_from('<I',event,44)[0]
    if (event_id,event[40],event[39])!=(expected_event_id,expected_side_index,expected_player_slot):
        raise ValueError('Selected pass event identity or actor differs')
    if event[42] not in range(6,12) or event[48]&8:
        raise ValueError('Select a counter-qualified native pass-family event')
    if not isinstance(pitch_geometry,dict):
        raise ValueError('Checked native pitch half-extents required')
    width,length=(pitch_geometry.get(k) for k in ('half_width_native','half_length_native'))
    if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<v<=1000 for v in (width,length)):
        raise ValueError('Invalid native pitch half-extents')
    x,y=struct.unpack_from('<ff',event,24)
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError('Nonfinite native pass-map location')
    direction=bool(struct.unpack_from('<H',event,48)[0]&256)
    forward=y if direction else -y
    inside,third,channel=_bins(x,forward,width,length)
    endpoint=None;path_state='not_supplied'
    if path is not None:
        if not isinstance(path,dict) or path.get('event_id')!=event_id:
            raise ValueError('Native sampled path event identity differs')
        raw=path.get('raw_xy_pairs')
        if not isinstance(raw,bytes) or len(raw)%8 or len(raw)>4096*8:
            raise ValueError('Invalid native sampled path width or budget')
        if any(not math.isfinite(v) for xy in struct.iter_unpack('<ff',raw) for v in xy):
            raise ValueError('Nonfinite native sampled path')
        if raw:
            if raw[:8]!=event[24:32]:
                raise ValueError('Sampled path first position differs from event location')
            ex,ey=struct.unpack_from('<ff',raw,len(raw)-8)
            end_forward=ey if direction else -ey
            end_inside,end_third,end_channel=_bins(ex,end_forward,width,length)
            endpoint={'native_x':ex,'native_y':ey,
                      'attack_relative_longitudinal_coordinate':end_forward,
                      'absolute_lateral_centerline_distance':abs(ex),
                      'inside_native_pitch_extents':end_inside,
                      'analytical_pitch_third':end_third,'analytical_lateral_channel':end_channel,
                      'semantics':ENDPOINT_SEMANTICS.get(event[42]),
                      'sample_count':len(raw)//8}
            path_state='source_bound_sampled_geometry_only'
        else:path_state='empty_native_path'
    return {'event_id':event_id,'side_index':event[40],'stored_player_slot':event[39],
            'native_category_code':event[42],
            'native_pass_map_location':{'native_x':x,'native_y':y},
            'attacked_goal_positive_native_y':direction,
            'attack_relative_longitudinal_coordinate':forward,
            'absolute_lateral_centerline_distance':abs(x),
            'inside_native_pitch_extents':inside,
            'analytical_pitch_third':third,'analytical_lateral_channel':channel,
            'binning_policy':'Three equal longitudinal pitch thirds; central width third versus either outer width third; threshold belongs to middle at -L/3, attacking at +L/3, central at |X|=W/3.',
            'location_semantics':LOCATION_SEMANTICS,
            'ball_release_location':{'native_x':x,'native_y':y},'sampled_path_endpoint':endpoint,
            'sampled_path_state':path_state,'intended_destination':None,
            'coordinate_units':None,'human_left_right':None}


# Shared converter direction flag; official pass-map getter/normalizer;
# event XY accumulator and official pitch goal-area direction predicate.
NATIVE_SPANS = (
    (0x488abc4,bytes.fromhex('88003836696240792901183269620079')),
    (0x4895a54,bytes.fromhex('0860407900210853c0035fd6')),
    (0x1a54e8,bytes.fromhex('e00318aa5ac11b95e80300aa09a340393f010071e9179f1ae04305910201094ae10318aaf8b91b95')),
    (0x4893f2c,bytes.fromhex('9f02007100102e1e01103e1e201c201e610e40fdc21240fd2210800fc21200fd')),
    (0x4895ac8,bytes.fromhex('00c0201ee85700d0021d45bd0020221e4101003445020054000441bde85700d0021945bd0228221e0020211e40c4211e650100540c00001425010054000441bde85700d0022145bd4238201e0040211e0020211e4444211e6c00005400008052c0035fd620008052')),
    (0x1a47bc,bytes.fromhex('a00641bd0028201ee0c30191f07d0995a00241bd0028201ee0830191ec7d0995')),
    (0x488a75c,bytes.fromhex('ea0314aa891240f9693f00b5400140fd600e00fd')),
)
