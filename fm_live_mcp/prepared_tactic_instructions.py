"""English meanings of shared stored prepared-tactic selections.

Ownership comes from prepared_tactics_source.inspect. The owning query calls
verify_native once and verifies its ReadSet after all requested decodes. Guards
pin native KEY routes; English labels are frozen from the accepted installed
resource. Phase applicability, defaults and effective instructions are unproved.
"""
import struct



MENTALITY_NAMES = {
    1: 'Very Defensive',
    2: 'Defensive',
    3: 'Cautious',
    4: 'Balanced',
    5: 'Positive',
    6: 'Attacking',
    7: 'Very Attacking',
}

OPTION_NAMES = {
    1: 'Much More Direct Passing',
    2: 'More Direct Passing',
    3: 'Shorter Passing',
    4: 'Much Shorter Passing',
    5: 'Pass Into Space',
    6: 'Pass Into Feet',
    7: 'Play Through Press',
    8: 'Bypass Press',
    9: 'Hit Early Crosses',
    10: 'Floated Crosses',
    11: 'Whipped Crosses',
    12: 'Low Crosses',
    13: 'Run At Defence',
    14: 'Dribble Less',
    15: 'Shoot On Sight',
    16: 'Discourage Long Shots',
    17: 'Work Ball Into Box',
    18: 'Play For Set Pieces',
    19: 'Be More Expressive',
    20: 'Be More Disciplined',
    21: 'Focus Play Down The Left',
    22: 'Focus Play Down The Right',
    23: 'Focus Play Through The Middle',
    24: 'Focus Play Down Both Flanks',
    25: 'Look For Overlap',
    26: 'Overlap Left',
    27: 'Overlap Right',
    28: 'Look For Underlap',
    29: 'Underlap Left',
    30: 'Underlap Right',
    31: 'Roll It Out',
    32: 'Throw It Long',
    33: 'Take Short Kicks',
    34: 'Take Long Kicks',
    35: 'Distribute To Centre-Backs',
    36: 'Distribute To Full-Backs',
    37: 'Distribute To Flanks',
    38: 'Distribute Over Opposition Defence',
    39: 'Distribute To Playmaker',
    40: 'Distribute to Target Forward',
    41: 'Distribute To Specific Team-Mate',
    42: 'Distribute Quickly',
    43: 'Slow Pace Down',
    44: 'Short Goal Kicks',
    45: 'Long Goal Kicks',
    46: 'Much Higher Tempo',
    47: 'Higher Tempo',
    48: 'Lower Tempo',
    49: 'Much Lower Tempo',
    50: 'Much Wider',
    51: 'Wider',
    52: 'Narrower',
    53: 'Much Narrower',
    54: 'Counter',
    55: 'Hold Shape',
    56: 'Much Higher Defensive Line',
    57: 'Higher Defensive Line',
    58: 'Lower Defensive Line',
    59: 'Much Lower Defensive Line',
    60: 'Goalkeeper Up For Set Pieces',
    61: 'High Press',
    62: 'Mid Block',
    63: 'Low Block',
    65: 'Trigger Press Much More Often',
    66: 'Trigger Press More Often',
    67: 'Trigger Press Less Often',
    68: 'Trigger Press Much Less Often',
    69: 'Prevent Short GK Distribution',
    70: 'Counter-Press',
    71: 'Regroup',
    72: 'Get Stuck In',
    73: 'Stay On Feet',
    76: 'Step Up More',
    77: 'Drop Off More',
    78: 'Waste Much More Time',
    79: 'Waste Time',
    80: 'Trap Inside',
    81: 'Trap Outside',
    82: 'Stop Crosses',
    83: 'Invite Crosses',
}


def _address(value, size=0):
    if (type(value) is not int or value < 4096 or value % 8
            or value + size >= 1 << 64):
        raise ValueError('Invalid prepared tactic instruction address')


def _read(read, address, size):
    raw = read(address, size)
    if len(raw) != size:
        raise ValueError('Incomplete prepared tactic instruction read')
    return raw


def verify_native(read, base):
    """Pin selected-bit membership, mentality and exact English-label KEY routes."""
    _address(base, max(rva + len(raw) for rva, raw in NATIVE_SPANS))
    for rva, expected in NATIVE_SPANS:
        if _read(read, base + rva, len(expected)) != expected:
            raise ValueError(f'Prepared tactic instruction native layout changed at RVA {rva:#x}')


def decode(read, creator_address):
    """Decode only stored selections; caller validates ownership, code and lifetime."""
    _address(creator_address, 0x106)
    flags = int.from_bytes(_read(read, creator_address + 0xE0, 11), 'little')
    mentality_code = struct.unpack('<b', _read(read, creator_address + 0x105, 1))[0]
    options = [{'native_option_id': option, 'name': OPTION_NAMES.get(option),
                'state': 'named' if option in OPTION_NAMES else 'no_native_label'}
               for option in range(1, 84) if flags & (1 << option)]
    return {'mentality': {'native_code': mentality_code, 'name': MENTALITY_NAMES.get(mentality_code),
                          'state': 'named' if mentality_code in MENTALITY_NAMES else 'unmapped_native_code'},
            'team_instructions': {'scope': 'shared_stored_options', 'selected_count': len(options),
                                  'selected_options': options,
                                  'unmapped_serialized_bits': [0] if flags & 1 else []}}


# Compact decisive native instructions/data only; no native calls are made.
NATIVE_SPANS = (
    (0x4a8d824, bytes.fromhex('80820391e10313aa1304009440faff34')),
    (0x2b51780, bytes.fromhex('758203913600805297058452c8fe43d308e57d92a86a68f80825d69a48020036e84740b9a8010034e0e30091410080520bd36094e81f40f9080100b4e94780b90801098b171100791f290039e84740b908090011e84700b9c11e0013e0e3009143cc6094d6060091df5201f101fdff54')),
    (0x2b51afc, bytes.fromhex('413001f021200591e043009102008012fbdc6094e81f40f9e80000b4e24740b9ff0700f9e023009101210091f4dc609402000014ff0700f968c8629408200291e90740f9ff0700f9e82706a9e0230191e1430091e2830191')),
    (0x4a8ebec, bytes.fromhex('ff0b00b9ca7e03534a057d928a6a6af84a25d69a8a000036aa22c81a29010a2ae90b00b9d6060011ca1e00125f510171a00000540a0500111f7d0071e8030aaa21feff54')),
    (0x4a8ec4c, bytes.fromhex('e83f4039ff02086b83fcff54')),
    (0x50fb44, bytes.fromhex('680a4279e8ab0b79680241b9e8d305b9e057d739e8831591494a0d95')),
    (0x4862494, bytes.fromhex('e90300aaf30308aa1f0100f9147200d0801246f93f0d00714d0400543f1500712c0800543f110071200f00543f150071411a0054e823009101538352e100a072')),
    (0x4862534, bytes.fromhex('3f050071e00700543f090071c01100543f0d007121160054e8230091c1528352e100a072d8e4ed97')),
    (0x48625b8, bytes.fromhex('3f190071800a00543f1d007141120054e823009121538352e100a072b9e4ed97')),
    (0x4862634, bytes.fromhex('e8230091a1528352e100a0729ee4ed97')),
    (0x48626a0, bytes.fromhex('e8230091e1528352e100a07283e4ed97')),
    (0x486270c, bytes.fromhex('e8230091018491528100a07268e4ed97')),
    (0x4862778, bytes.fromhex('e8230091818391528100a0724de4ed97')),
    (0x486280c, bytes.fromhex('fd7b45a9f44f44a9f65743a9ff830191c0035fd6')),
    (0x4865cf8, bytes.fromhex('280400511f490171881a0154f30300aaf47100f0801246f9c95c00f029e13d918a0000102b7968784a090b8b40011fd6')),
    (0x5400f78, bytes.fromhex('00002304450304053b0599033f045b04c60572056702b4030f03f8019404b0041a06e205c0012a036e06dc01f3024b02eb0313022f071407bb026103e8047d039f078302fe0583076c01560550013401d70207045206a800880177042005bb07cc041801c4002a086707fc008e053606e000f80689067e08f4074608a506ca08c1062f024b075400d8070f08cf036208dc06ca08ca087000a401aa058c00990838009f021c00')),
    (0x4868050, bytes.fromhex('fd7b45a9f44f44a9f65743a9ff830191c0035fd6')),
    (0x4865d28, bytes.fromhex('09698352e900a072e823009121292d11e0d6ed97')),
    (0x4866db4, bytes.fromhex('a9a28752a900a072e823009121850f11bdd2ed97')),
    (0x4866a3c, bytes.fromhex('a9a28752a900a072e8230091215517119bd3ed97')),
    (0x4867138, bytes.fromhex('09698352e900a072e823009121252d11dcd1ed97')),
    (0x4867214, bytes.fromhex('e8230091214191528100a072a6d1ed97')),
    (0x4866b8c, bytes.fromhex('e823009121b998524101a07248d3ed97')),
    (0x4866e24, bytes.fromhex('29b998524901a072e823009121011f32a1d2ed97')),
    (0x4866e94, bytes.fromhex('29b998524901a072e8230091210d001185d2ed97')),
    (0x4867440, bytes.fromhex('89369d528900a072e8230091210500321ad1ed97')),
    (0x48672f0, bytes.fromhex('a9a28752a900a072e8230091210906116ed1ed97')),
    (0x48666c4, bytes.fromhex('69079252a900a072e8230091215d041179d4ed97')),
    (0x4866bf8, bytes.fromhex('e823009161079252a100a0722dd3ed97')),
    (0x4866964, bytes.fromhex('e823009181369d528100a072d2d3ed97')),
    (0x4866508, bytes.fromhex('e8230091412a9b52a100a072e9d4ed97')),
    (0x4866f78, bytes.fromhex('294191528900a072e823009121011e324cd2ed97')),
    (0x4866fe8, bytes.fromhex('29b998524901a072e82300912105001130d2ed97')),
    (0x4867590, bytes.fromhex('294191528900a072e823009121150011c6d0ed97')),
    (0x48674b0, bytes.fromhex('09698352e900a072e823009121992e11fed0ed97')),
    (0x4866428, bytes.fromhex('a9a28752a900a072e82300912105001120d5ed97')),
    (0x48669d0, bytes.fromhex('e8230091a1a28752a100a072b7d3ed97')),
    (0x48676e0, bytes.fromhex('e823009181408152e100a07273d0ed97')),
    (0x4866498, bytes.fromhex('09698352e900a072e823009121292e1104d5ed97')),
    (0x48668f4, bytes.fromhex('09698352e900a072e823009121312e11edd3ed97')),
    (0x4866654, bytes.fromhex('09698352e900a072e8230091212d2e1195d4ed97')),
    (0x4866cd4, bytes.fromhex('294191528900a072e823009121210011f5d2ed97')),
    (0x4866574, bytes.fromhex('09698352e900a072e823009121352e11cdd4ed97')),
    (0x48679e4, bytes.fromhex('09698352e900a072e823009121392e11b1cfed97')),
    (0x4867978, bytes.fromhex('e8230091e13a9852c100a072cdcfed97')),
    (0x4866814, bytes.fromhex('09698352e900a072e8230091213d2e1125d4ed97')),
    (0x4866aac, bytes.fromhex('09698352e900a072e823009121412e117fd3ed97')),
    (0x48670c8, bytes.fromhex('09698352e900a072e823009121c12e11f8d1ed97')),
    (0x4866b1c, bytes.fromhex('09698352e900a072e8230091219d2e1163d3ed97')),
    (0x4867ba4, bytes.fromhex('09698352e900a072e823009121c52e1141cfed97')),
    (0x4866734, bytes.fromhex('09698352e900a072e823009121a12e115dd4ed97')),
    (0x4867520, bytes.fromhex('09698352e900a072e823009121ad2e11e2d0ed97')),
    (0x4867b34, bytes.fromhex('09698352e900a072e823009121a92e115dcfed97')),
    (0x48662d8, bytes.fromhex('09698352e900a072e823009121b52e1174d5ed97')),
    (0x4867280, bytes.fromhex('09698352e900a072e823009121bd2e118ad1ed97')),
    (0x4866268, bytes.fromhex('09698352e900a072e823009121b12e1190d5ed97')),
    (0x48661f8, bytes.fromhex('e93b81520901a072e823009121110011acd5ed97')),
    (0x4866884, bytes.fromhex('09698352e900a072e823009121a52e1109d4ed97')),
    (0x4866d44, bytes.fromhex('09698352e900a072e823009121cd2e11d9d2ed97')),
    (0x4867670, bytes.fromhex('09698352e900a072e823009121c92e118ed0ed97')),
    (0x4865fc8, bytes.fromhex('29b998524901a072e823009121011e3238d6ed97')),
    (0x4866348, bytes.fromhex('29b998524901a072e82300912115001158d5ed97')),
    (0x4866f04, bytes.fromhex('291080524ae08b52aa00a072e82300914101092a68d2ed97')),
    (0x48671a8, bytes.fromhex('e823009141e08b52a100a072c1d1ed97')),
    (0x4867c14, bytes.fromhex('890c80524ae08b52aa00a072e82300914101092a24cfed97')),
    (0x4867058, bytes.fromhex('49e08b52a900a072e8230091210d021114d2ed97')),
    (0x4866188, bytes.fromhex('09698352e900a072e823009121452e11c8d5ed97')),
    (0x4866038, bytes.fromhex('09698352e900a072e823009121492e111cd6ed97')),
    (0x4867dd0, bytes.fromhex('09698352e900a072e8230091214d2e11b6ceed97')),
    (0x4867ac4, bytes.fromhex('09698352e900a072e823009121512e1179cfed97')),
    (0x4866118, bytes.fromhex('09698352e900a072e823009121712e11e4d5ed97')),
    (0x4867360, bytes.fromhex('09698352e900a072e823009121752e1152d1ed97')),
    (0x4867600, bytes.fromhex('49e08b52a900a072e823009121f90111aad0ed97')),
    (0x48660a8, bytes.fromhex('09698352e900a072e823009121552e1100d6ed97')),
    (0x4867908, bytes.fromhex('09698352e900a072e823009121592e11e8cfed97')),
    (0x486774c, bytes.fromhex('09698352e900a072e8230091218d2e1157d0ed97')),
    (0x4867f20, bytes.fromhex('e8230091c1ab9d524101a07263ceed97')),
    (0x4867cf8, bytes.fromhex('e8230091614491520101a072edceed97')),
    (0x4867e40, bytes.fromhex('694491520901a072e8230091210900119aceed97')),
    (0x48677bc, bytes.fromhex('694491520901a072e8230091210500113bd0ed97')),
    (0x486782c, bytes.fromhex('e8230091e13b81520101a07220d0ed97')),
    (0x48665e4, bytes.fromhex('e93b81520901a072e823009121050011b1d4ed97')),
    (0x4867a54, bytes.fromhex('e93b81520901a072e82300912109001195cfed97')),
    (0x4865e78, bytes.fromhex('e93b81520901a072e8230091210d00118cd6ed97')),
    (0x4867c88, bytes.fromhex('69079252a900a072e82300912179011108cfed97')),
    (0x4867d64, bytes.fromhex('e823009101698352e100a072d2ceed97')),
    (0x4866c64, bytes.fromhex('09698352e900a072e823009121792e1111d3ed97')),
    (0x4867eb0, bytes.fromhex('294191528900a072e823009121011c327eceed97')),
    (0x4867898, bytes.fromhex('294191528900a072e82300912145001104d0ed97')),
    (0x4865ee8, bytes.fromhex('694491520901a072e8230091211d191170d6ed97')),
    (0x48663b8, bytes.fromhex('694491520901a072e8230091212119113cd5ed97')),
    (0x48673d0, bytes.fromhex('09698352e900a072e8230091216d2e1136d1ed97')),
    (0x4865f58, bytes.fromhex('49e08b52a900a072e82300912131061154d6ed97')),
    (0x4867f8c, bytes.fromhex('694491520901a072e8230091211d001147ceed97')),
    (0x4865e08, bytes.fromhex('694491520901a072e823009121011d32a8d6ed97')),
    (0x48667a4, bytes.fromhex('694491520901a072e82300912125001141d4ed97')),
    (0x4865d98, bytes.fromhex('694491520901a072e823009121290011c4d6ed97')),
)
