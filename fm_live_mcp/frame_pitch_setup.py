"""Named native pitch setup attached to one verified exact cached frame.

Pitch dimensions are setup metadata. They do not by themselves normalize frame
coordinates, identify penalty boundaries, establish physical units or active XI.
The caller performs final lifetime/ReadSet checks before refreshed verification.
"""
import math
import struct

from . import frame_attack_direction as direction

NATIVE_SPANS = (
    (0x213C4, bytes.fromhex("880240f9092540f9e8330091e00314aae10315aa20013fd6")),
    (0x734C2C, bytes.fromhex("a10100b4092c40f9890000b42a0d40f95f0101ebc0000054093040f9c90000b42a0d40f95f0101eb6100005420a10091ca08001400e4006f00c18a3c008104ad008103ad008102ad008101ad008100ad0001803dc0035fd6")),
    (0x736F84, bytes.fromhex("ff4301d1f65702a9f44f03a9fd7b04a9fd030191f40300aaf30308aa00e4006f00c18a3c008104ad15101f91008103ad008102ad008101ad008100ad0001803de8130091e22a0094e0c340fc600200fd")),
    (0x741B50, bytes.fromhex("090e82520900098b001cc43d0001803d20c1c03c00c1803cc0035fd6")),
    (0x74198C, bytes.fromhex("a07642bd607a10bda07242bd607e10bd")),
    (0x116E0, bytes.fromhex("c181029021400a9160420091e2018052e64f0094010080d253732b95a18102d021600e9122008052e04f0094810080524d732b95a18102d021400e91")),
    (0x11724, bytes.fromhex("c181029021800a9160420091c2018052d54f00948100805242732b95a18102d021600e9122008052cf4f0094810080523c732b95")),
    (0x5049290, bytes.fromhex("6f2870697463684c656e677468293d00")),
    (0x50492A0, bytes.fromhex("6f2870697463685769647468293d00")),
)


def verify_native(read, base):
    for at, expected in NATIVE_SPANS:
        if direction._read(read, base+at, len(expected)) != expected:
            raise ValueError('Native named pitch setup source changed')
    if direction._q(read, base+0x54EC0C8+0x48) != base+0x734C2C:
        raise ValueError('Named pitch setup virtual route changed')


def capture(read, base, bound, *, fixed_tick):
    verify_native(read, base)
    frame = direction.capture(read, base, bound, fixed_tick=fixed_tick)
    result = {'state':'unavailable_exact_frame', 'frame_tick':fixed_tick,
              'pitch_length_native':None, 'pitch_width_native':None,
              '_frame':frame, '_dimensions':None}
    if '_native_fields' not in frame:
        return result
    # Named get_stadium_setup returns MATCH_INFO+1078/107C via741B50 and
    #736F84. MATCH_INFO is embedded in the already bound playback at+28.
    raw = direction._read(read, bound['playback_address']+0x10A0, 8)
    length, width = struct.unpack('<ff', raw)
    if any(not math.isfinite(v) or v<=0 for v in (length,width)):
        return result | {'state':'unavailable_native_pitch_dimensions', '_dimensions':raw}
    pitch = direction._q(read, bound['source_match_address']+0x153E8)
    direction._pointer(pitch)
    source = direction._read(read, pitch+0x270, 8)
    # Preserve exact float32 bits. No CBE extents, standard-pitch default,
    # stadium-name lookup or assumed physical unit is substituted.
    if source[4:8]+source[0:4] != raw:
        return result | {'state':'unavailable_pitch_setup_source_disagreement',
                         '_dimensions':(raw,pitch,source)}
    return result | {'state':'available_native_pitch_setup', 'pitch_length_native':length,
                     'pitch_width_native':width, '_dimensions':(raw,pitch,source)}


def verify_capture(read, base, captured, bound):
    direction.verify_capture(read,base,captured['_frame'],bound)
    again = capture(read,base,bound,fixed_tick=captured['frame_tick'])
    if again['state']!=captured['state'] or again['_dimensions']!=captured['_dimensions']:
        raise ValueError('Named pitch setup changed during frame capture')
    return captured | {'same_session_exact_frame_pitch_setup_verified':True,
                       'observed_cursor':captured['_frame']['_observed_cursor'],
                       'verification_cursor':bound['current_time_slice']}


def project(verified):
    if verified.get('same_session_exact_frame_pitch_setup_verified') is not True:
        raise ValueError('Final named pitch setup verification is required')
    return {k:v for k,v in verified.items() if not k.startswith('_')} | {
        'source':'official_native_get_stadium_setup_pitch_setup_info',
        'physical_units':None, 'world_xy_to_pitch_bounds_verified':False,
        'penalty_area_geometry':None, 'on_pitch_population_verified':False,
        'interpretation':'Named pitch length and width setup metadata for the same bound '
            'playback/frame, reconciled to its provider-owned pitch source. Frame coordinate '
            'normalization, penalty geometry, physical units and active participation require '
            'separate proof. Retained tracking extents are not substituted.'}
