"""Native goal-target Y orientation at one checked normal-period frame.

The native player setter and named xG goal-centre feature establish the sign
mapping. Penalty-shootout orientation is deliberately a separate source gate.
No active participation, physical units or sustained box support is inferred.
"""
from . import frame_attack_direction as direction

# Original SI.Match.MatchPeriod metadata: ordinary playing halves, not intervals.
ORDINARY_PLAYING_PERIODS = {6: 'FirstHalf', 7: 'SecondHalf'}

# The complete player direction setter; bounded xG producer through the two
# angular-feature stores; named feature3 parser; original feature-selector loop;
# frame upfield producer and exact constructor copy into FRAME+82.
NATIVE_SPANS = (
    # Named full period getter route, engine period producer and FRAME copy.
    (0x2279C, bytes.fromhex("680240f9086d40f9e00313aae10314aa00013fd6")),
    (0x7359B0, bytes.fromhex("010300b4fd7bbfa9fd030091e80300aa002c40f9800000b4090c40f93f0101ebc0000054003140f9400100b4080c40f91f0101ebe1000054970c0094a00000b408f04039fd7bc1a8001d0013c0035fd6e81f8052fd7bc1a8001d0013c0035fd6e81f8052001d0013c0035fd6")),
    (0x738C44, bytes.fromhex("00044af9400000b44f230114c0035fd6")),
    (0x781988, bytes.fromhex("001041f9c0035fd6")),
    (0x4ABCE24, bytes.fromhex("a8ea4a3968220039")),
    (0x4AB33FC, bytes.fromhex("e84f40f9884203f8885340f8097e8452892ea972200d040e889203f8")),
    (0x4548640, bytes.fromhex("084041f909838a522900a072086969f8094441f91f0109ebe8179f1a08340b39c0035fd6")),
    (0x48DB578, bytes.fromhex("e8e241f97f0200f109019f9a680209aae84b00b4e8f641f9007d42bdfa3700b9e91f00f93a24003408c282528802088b09d14239292901513f210071692200548252c03df43740b9e91f40f90340211e41040c5e0820201e64cc201e654c201e2020241e21cc241e2020251e214c251e441ca24e24040c6e3f0100f16802899a13354b397f060071030c231e00e4006fe32b803d60040c6e83d4a04e63dc236e63d8307ee453803d00d4a44e84f4014f00dc246e0a00381e00040c5e0900381e60c0211e5f0100714c558a5a3f0100712b55895a9f550271680000547f210371e3020054ad369052cd69a3728c7dad9b8cfd64d3eda390526d3daa726b7dad9b6bfd66d39f010b6b8b818b1a6b11c05aeb030b4b0c0080128c21cb1a4d7d1f13ad012c0aaa010a0b4a29cb1a2d7d1f13ac012c0a8901090b2929cb1a8b1680527f060071eb038b1a4a7d4093cc6f00f08ca120918a290a8b49c5298b0a328b524a00a0722969ea780a51c4790c4eb8528301271e0318231e04102e1e6328241e6020241e84cc231e6820201e03e4002f634c241e640d040e031800bd2301271e431d0c4e8374a30e6454300f8404300f092d8052250d040ea384a32e6354300f6304300f636ca40e295900f0243547fd636ca40e05e4006f6364a50e8384a32e64e6012f631c240e63d8212e295900f0243947fd63fc242e030800fd")),
    (0x495C740, bytes.fromhex("1fd800f1e1edff54e00317aae14b00f0213c1791c206805293490694204e003573008052d3feff17")),
    (0x495D9E4, bytes.fromhex("8f154038ff0d0071cc000054ff050071ac01005481020054221c40bd04000014ff190071810100542240201ea34540bc4208231e0028221ece0500f121feff5418000014ff09007161010054220c40bdf7ffff17ff11007181010054221440bdf3ffff1702e4002f2ffeff35221840bdefffff1702e4002fff0d007181fdff54221040bdeaffff1702e4002fff150071e1fcff54222040bde5ffff1700e4002f")),
    (0x52DB5CF, b'transformed_angle_from_shot_location_to_centre_of_goal\0'),
    (0x4ABD804, bytes.fromhex("16544091c80e42f9c9ba41f91f0109ebe8079f1a28080039")),
    (0x4AB35F4, bytes.fromhex("e8f3407988020179e9eb4139890a0239")),
)


def verify_native(read, base):
    direction.verify_native(read, base)
    if direction._q(read, base + 0x54EC0C8 + 0xD8) != base + 0x7359B0:
        raise ValueError('Named native period virtual route changed')
    for at, expected in NATIVE_SPANS:
        if direction._read(read, base + at, len(expected)) != expected:
            raise ValueError('Native attacked-goal Y source changed')


def capture(read, base, bound, *, fixed_tick):
    verify_native(read, base)
    captured = direction.capture(read, base, bound, fixed_tick=fixed_tick)
    return {'_direction': captured}


def verify_capture(read, base, captured, bound):
    verify_native(read, base)
    verified = direction.verify_capture(read, base, captured['_direction'], bound)
    return {'_direction': verified, 'same_session_fixed_frame_goal_basis_reselected': True}


def project(verified):
    if verified.get('same_session_fixed_frame_goal_basis_reselected') is not True:
        raise ValueError('Final native attacked-goal basis verification required')
    source = direction.project(verified['_direction'])
    period = source.get('native_period_code')
    supported = period in ORDINARY_PLAYING_PERIODS
    teams = []
    for row in source.get('teams') or []:
        value = row['native_kicking_upfield']
        known = supported and type(value) is bool
        teams.append({'side_index': row['side_index'],
            'attacked_end_positive_native_y': value if known else None,
            'state': 'available_native_goal_target_sign' if known else 'unavailable_native_goal_target_sign'})
    count = sum(row['attacked_end_positive_native_y'] is not None for row in teams)
    return {'state': 'available_native_attacked_goal_basis' if count == 2 else 'unavailable_native_attacked_goal_basis',
        'frame_tick': source['frame_tick'], 'native_period_code': period,
        'native_period_name': ORDINARY_PLAYING_PERIODS.get(period), 'teams': teams,
        'source': 'native_player_upfield_setter_and_named_xg_goal_centre_feature',
        'same_session_fixed_frame_goal_basis_reselected': True,
        'observed_cursor': source['observed_cursor'], 'verification_cursor': source['verification_cursor'],
        'physical_units': None, 'active_participation_verified': False,
        'penalty_area_occupation': None, 'sustained_box_support': None,
        'interpretation': 'In checked ordinary playing halves (FirstHalf=6, SecondHalf=7), the native kicking-upfield side targets positive '
            'native Y and the other side targets negative native Y. The native xG goal-centre feature '
            'supplies this mapping. Penalty shootouts, screen direction, physical units and active '
            'participation require their own evidence.'}
