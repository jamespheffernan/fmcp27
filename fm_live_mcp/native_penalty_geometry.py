"""Float32 native goal-end area geometry; no actor participation inference.

The selected native predicate has no far goal-line cap. Its intersection with
checked native pitch bounds is therefore returned separately. This is neither
retained shot-bin membership nor a physical-unit or displayed-frame claim.
"""
import math
import struct

NATIVE_PREDICATE = (0x447ED24, bytes.fromhex("200440bd0820201e220200358504005401dc40bd088195526830b8720201271e2128221e2140211e0020211e85030054200040bda84781522834a8720101271e0020211e04020054150000148d02005401dc40bd088195526830b8720201271e2128221e0020211ead010054200040bda84781522834a8720101271e0020211ee5000054a84781522834b8720101271e0020211ee0d79f1ac0035fd600008052c0035fd6"))


def _f32(value):
    if type(value) not in (float,int) or not math.isfinite(value):
        raise ValueError('Finite native float32 geometry is required')
    try:
        rounded=struct.unpack('<f',struct.pack('<f',value))[0]
    except (OverflowError,struct.error) as exc:
        raise ValueError('Native float32 geometry range exceeded') from exc
    if not math.isfinite(rounded):
        raise ValueError('Native float32 geometry range exceeded')
    return rounded


def classify(x,y,*,selected_goal_positive_y,half_width,half_length):
    """Native447ED24 plus a separately stated pitch-bounds intersection."""
    if type(selected_goal_positive_y) is not bool:
        raise ValueError('A proved native goal-end boolean is required')
    x,y,half_width,half_length=map(_f32,(x,y,half_width,half_length))
    if half_width<=0 or half_length<=0:
        raise ValueError('Positive native pitch half-extents are required')
    limit=_f32(20.13)
    threshold=_f32(half_length+_f32(-16.459))
    forward=y if selected_goal_positive_y else -y
    strip=forward>0 and forward>threshold and -limit<x<limit
    in_pitch=abs(x)<=half_width and abs(y)<=half_length
    return {'native_selected_goal_end_strip':strip,
        'inside_native_pitch_bounds':in_pitch,
        'inside_native_pitch_and_selected_goal_end_area':in_pitch and strip,
        'selected_goal_positive_y':selected_goal_positive_y,
        'native_lateral_strict_limits':[-limit,limit],
        'native_forward_strict_threshold':threshold,
        'native_longitudinal_cap_in_predicate':False,
        'pitch_boundary_policy':'inclusive_native_half_extents; selected-area edges are strict',
        'physical_units':None,'actor_on_pitch':None,
        'scope':'Pure geometry for supplied source-qualified native coordinates and half-extents. '
            'No side orientation, active player population, box support, run or frame provenance '
            'is inferred by this function.'}


def verify_native(read,base):
    at,expected=NATIVE_PREDICATE
    if read(base+at,len(expected))!=expected:
        raise ValueError('Native goal-end area predicate changed')
