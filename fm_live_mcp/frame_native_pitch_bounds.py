"""Exact-frame native XY pitch bounds from provider-owned geometry.

The named dimensions, native constructor's axes/corners and motion/player/frame
XYZ copy chain are checked separately. Bounds do not identify the attacked end,
physical units or active participants; inside bounds is not on-pitch membership.
"""
import math
import struct
from . import frame_pitch_setup as setup, native_motion_world_basis as basis

NATIVE_SPANS = (
    (0x4A55180,bytes.fromhex("01001a2d01040c6e2004084e284d00d00105c13d00dc216e00808d3c1f6000f91fc800b901040c5e2240211e1f0000b9020400bd1f0800b90008082d1f4800b90340211e0308062d1f3800b9284d00d0042144bd2128241e2440211e1f5000b9045400bd1f5800b928ae8752480da872081000b9021400bd1f1800b929ae8752490db872092000b9022400bd1f2800b91f6000b90a9001914091000d1f6800b903a000bd0a9002914091000d1fa800b9004800fd1f9800b91fb000b901b400bd1fb800b9097000b909d001912091000d1f7800b9088000b9081002910091000d1f8800b9c0035fd6")),
    (0x53FB410,bytes.fromhex("0000003f0000003f0000803e0000803e68912fc1")),
)


def verify_native(read,base):
    basis.verify_native(read,base)
    for at,expected in NATIVE_SPANS:
        if setup.direction._read(read,base+at,len(expected))!=expected:
            raise ValueError('Native pitch XY geometry constructor changed')


def capture(read,base,bound,*,fixed_tick):
    verify_native(read,base)
    pitch=setup.capture(read,base,bound,fixed_tick=fixed_tick)
    common={'state':'unavailable_named_pitch_setup','named_pitch_setup_state':pitch['state'],'frame_tick':fixed_tick,
        'native_xy_bounds':None,'native_pitch_corners_xyz':None,
        'native_xy_to_pitch_bounds_verified':False,'_setup':pitch,'_geometry':None}
    if pitch['state']!='available_native_pitch_setup':return common
    address=pitch['_dimensions'][1]
    raw=setup.direction._read(read,address+0x1A0,0xE8)
    width,length,half_width,half_length=struct.unpack_from('<4f',raw,0xD0)
    if not all(math.isfinite(v) and v>0 for v in (width,length,half_width,half_length)):
        return common | {'state':'unavailable_native_pitch_extents','_geometry':(address,raw)}
    expected=struct.pack('<4f',pitch['pitch_width_native'],pitch['pitch_length_native'],
        pitch['pitch_width_native']*0.5,pitch['pitch_length_native']*0.5)
    if raw[0xD0:0xE0]!=expected:
        return common | {'state':'unavailable_native_pitch_dimension_constructor_disagreement','_geometry':(address,raw)}
    corners=[(-half_width,-half_length,0.0),(half_width,-half_length,0.0),
        (half_width,half_length,0.0),(-half_width,half_length,0.0)]
    for offset,point in zip((0x30,0x40,0x90,0xA0),corners):
        if raw[offset:offset+12]!=struct.pack('<3f',*point):
            return common | {'state':'unavailable_native_pitch_corner_constructor_disagreement','_geometry':(address,raw)}
    for offset,point in ((0,(0.0,-half_length,0.0)),(0x60,(0.0,half_length,0.0))):
        if raw[offset:offset+12]!=struct.pack('<3f',*point):
            return common | {'state':'unavailable_native_goal_centre_constructor_disagreement','_geometry':(address,raw)}
    return common | {'state':'available_native_xy_pitch_geometry',
        'native_xy_bounds':{'x_min':-half_width,'x_max':half_width,
                           'y_min':-half_length,'y_max':half_length},
        'native_pitch_corners_xyz':[list(v) for v in corners],
        'native_xy_to_pitch_bounds_verified':True,'_geometry':(address,raw)}


def verify_capture(read,base,captured,bound):
    setup.verify_capture(read,base,captured['_setup'],bound)
    again=capture(read,base,bound,fixed_tick=captured['frame_tick'])
    if again['state']!=captured['state'] or again['_geometry']!=captured['_geometry']:
        raise ValueError('Consumed exact-frame native pitch geometry changed')
    return captured | {'same_session_exact_frame_pitch_geometry_verified':True,
        'observed_cursor':captured['_setup']['_frame']['_observed_cursor'],
        'verification_cursor':bound['current_time_slice']}


def project(verified):
    if verified.get('same_session_exact_frame_pitch_geometry_verified') is not True:
        raise ValueError('Final exact-frame native pitch geometry verification required')
    return {k:v for k,v in verified.items() if not k.startswith('_')} | {
        'physical_units':None,'attacked_end_positive_y':None,
        'active_participation_verified':False,'penalty_area_occupation':None,
        'interpretation':'Provider-owned native pitch bounds, in the same XYZ representation '
            'copied to native player and exact playback frame points. Width runs along X; '
            'length runs along Y. Inside these bounds does not establish active playing '
            'membership, attacked end, physical units or sustained box support.'}
