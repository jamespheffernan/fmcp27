"""Stored player ability, positions and extra ratings from build-verified getters."""
import struct

from . import personality

# Offsets are relative to the primary ACTUAL_PLAYER / combined player object.
# Property IDs and labels come from the installed editor definitions.
GOALKEEPING = {
    'aerial_reach': (0x163, 'PDae', 'Aerial Ability'),
    'command_of_area': (0x164, 'PDca', 'Command Of Area'),
    'communication': (0x165, 'PDcm', 'Communication'),
    'eccentricity': (0x176, 'PDec', 'Eccentricity'),
    'handling': (0x162, 'PDhn', 'Handling'),
    'kicking': (0x166, 'PDkc', 'Kicking'),
    'one_on_ones': (0x16A, 'PDoo', 'One On Ones'),
    'reflexes': (0x16C, 'PDrf', 'Reflexes'),
    'rushing_out': (0x177, 'PDro', 'Rushing Out (Tendency)'),
    'tendency_to_punch': (0x178, 'PDtp', 'Tendency To Punch'),
    'throwing': (0x167, 'PDth', 'Throwing'),
}
HIDDEN = {
    'consistency': (0x183, 'PDcy', 'Consistency'),
    'dirtiness': (0x180, 'PDdt', 'Dirtiness'),
    'important_matches': (0x186, 'PDim', 'Important Matches'),
    'injury_proneness': (0x187, 'PDij', 'Injury Proneness'),
    'versatility': (0x188, 'PDvt', 'Versatility'),
}
FEET = {'left': (0x16F, 'PDlf', 'Left Foot'), 'right': (0x170, 'PDri', 'Right Foot')}
# offset, primary vtable slot, getter RVA, property, editor label, property case RVA
POSITIONS = {
    'goalkeeper': (0x148, 114, 0xD5B2A0, 'Pgoa', 'Goalkeeper', 0x1505B4C),
    'defender_left': (0x14A, 122, 0xD5B2A8, 'Pdls', 'Defender Left', 0x1509070),
    'defender_central': (0x14B, 123, 0xD14318, 'Pdce', 'Defender Central', 0x150A714),
    'defender_right': (0x14C, 124, 0xD5B2B0, 'Pdrs', 'Defender Right', 0x1506D48),
    'defensive_midfielder': (0x14D, 125, 0xD14320, 'Pdmc', 'Defensive Midfielder', 0x1504EE0),
    'midfielder_left': (0x14E, 126, 0xD5B2D0, 'Pmls', 'Midfielder Left', 0x1503C74),
    'midfielder_central': (0x14F, 127, 0xD5B2C8, 'Pmce', 'Midfielder Central', 0x15048C8),
    'midfielder_right': (0x150, 128, 0xD5B2D8, 'Pmrs', 'Midfielder Right', 0x150448C),
    'attacking_midfielder_left': (0x151, 129, 0xD14348, 'Paml', 'Attacking Midfielder Left', 0x15076B0),
    'attacking_midfielder_central': (0x152, 130, 0xD5B2E0, 'Pamc', 'Attacking Midfielder Central', 0x150A6A8),
    'attacking_midfielder_right': (0x153, 131, 0xD14350, 'Pamr', 'Attacking Midfielder Right', 0x1509328),
    'striker': (0x154, 132, 0xD142F0, 'Pace', 'Striker', 0x15073D8),
    'wing_back_left': (0x155, 133, 0xD5B2B8, 'Pwbl', 'Wing-Back Left', 0x150AADC),
    'wing_back_right': (0x156, 134, 0xD5B2C0, 'Pwbr', 'Wing-Back Right', 0x1507860),
}
GETTERS = {6: 0xD09D58, 7: 0xD28D64, 16: 0xD1414C, 113: 0xD09E68,
           **{v[1]: v[2] for v in POSITIONS.values()}}
VIRTUAL_GETTERS = {6: 0x18A66D8, 7: 0x18A6708, 16: 0x18A68F8, 113: 0x18A70B0,
                   114: 0x18A70E0, **{s: 0x18A732C + (s-122)*0x30 for s in range(122, 135)}}
POTENTIAL_RANGES = {-10: (170, 200), -95: (160, 190), -9: (150, 180), -85: (140, 170),
                    -8: (130, 160), -75: (120, 150), -7: (110, 140), -65: (100, 130),
                    -6: (90, 120), -55: (80, 110), -5: (70, 100), -45: (60, 90),
                    -4: (50, 80), -35: (40, 70), -3: (30, 60), -25: (20, 50),
                    -2: (10, 40), -15: (0, 30), -1: (0, 20)}
QUERY_FIELDS = {'ability.current': 200, 'ability.potential': 200,
                **{f'{group}.{name}': 20 for group, fields in (
                    ('goalkeeping', GOALKEEPING), ('hidden_attributes', HIDDEN),
                    ('feet', FEET), ('positions', POSITIONS), ('personality', personality.FIELDS)) for name in fields}}


def rating(raw, fifths):
    if not 0 <= raw <= (100 if fifths else 20):
        raise ValueError('Player attribute outside verified range')
    return max(1, (raw + 2) // 5) if fifths else raw


def verify_getters(read, base, table, getters=GETTERS):
    for slot, getter in getters.items():
        if int.from_bytes(read(table + slot*8, 8), 'little') != base + getter:
            raise ValueError('Player profile getter changed')


def decode(read, base, data, person_offset=0x388, virtual=False):
    verify_getters(read, base, int.from_bytes(data[:8], 'little'))
    current, potential = struct.unpack_from('<hh', data, 0x25C)
    if not 0 <= current <= 200 or not -100 <= potential <= 200:
        raise ValueError('Player ability outside verified range')
    fifths = bool(data[0x270] & 0x80)
    def ratings(mapping):
        return {name: rating(data[offset], fifths) for name, (offset, _, _) in mapping.items()}
    positions = {name: data[fields[0]] for name, fields in POSITIONS.items()}
    if any(value > 20 for value in positions.values()):
        raise ValueError('Player position rating outside verified range')
    return {
        'ability': {'current': current, 'potential': potential if potential >= 0 else None,
                    'potential_native_code': potential,
                    'potential_range': list(POTENTIAL_RANGES[potential]) if potential in POTENTIAL_RANGES else None,
                    'potential_state': 'fixed' if potential >= 0 else 'range' if potential in POTENTIAL_RANGES else 'unmapped_range'},
        'positions': positions, 'goalkeeping': ratings(GOALKEEPING),
        'hidden_attributes': ratings(HIDDEN), 'feet': ratings(FEET),
        'personality': personality.decode(read, base, data, person_offset, virtual),
        'personality_scale': '0–20',
        'personality_native_defaults': ['controversy'] if virtual else [],
        'attribute_scale': '1–20' if fifths else '0–20', 'position_scale': '0–20',
        'evidence': 'native_player_getters_and_installed_editor_fields',
    }
