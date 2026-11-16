"""Stored staff ratings mapped through this build's editor IDs and native getters.

Offsets below are relative to NON_PLAYER (eight bytes before NON_PLAYING_DATA).
These are underlying values, without role/visibility suppression in the UI.
"""
import struct

from . import players

# name: (offset, fifths-of-a-point encoding, property code)
ATTRIBUTES = {
    'goalkeeping': (0x2B, True, 'Npgs'),
    'working_with_youngsters': (0x1C, False, 'Npwy'),
    'people_management': (0x2E, True, 'Npmm'),
    'attacking': (0x32, True, 'Ncha'),
    'defending': (0x33, True, 'Nchd'),
    'fitness': (0x34, True, 'Nchf'),
    'possession': (0x35, True, 'Nchm'),
    'technical': (0x36, True, 'Ncte'),
    'tactical': (0x37, True, 'Ncta'),
    'set_pieces': (0x43, True, 'Ncsp'),
    'tactical_knowledge': (0x31, True, 'Nptk'),
    'determination': (0x1D, True, 'Npde'),
    'judging_player_ability': (0x2C, True, 'Npja'),
    'judging_player_potential': (0x2D, True, 'Npjp'),
    'authority': (0x14, False, 'Npld'),
    'motivating': (0x2F, True, 'Npmo'),
    'physiotherapy': (0x30, True, 'Npph'),
    'analysing_data': (0x3C, True, 'Npjd'),
    'judging_staff_ability': (0x42, True, 'Npjs'),
    'sports_science': (0x3F, True, 'NpIM'),
    'negotiating': (0x41, True, 'Nneg'),
    'versatility': (0x3B, True, 'Npvr'),
}
TENDENCIES = {
    'attacking': (0x10, False, 'Natt'),
    'defensive_line': (0x23, False, 'Ndep'),
    'directness': (0x13, False, 'Ndir'),
    'dirtiness_allowance': (0x38, True, 'Ndal'),
    'flexibility': (0x25, False, 'Nflx'),
    'trigger_press': (0x1A, False, 'Npre'),
    'tempo': (0x28, False, 'Ntem'),
    'width': (0x29, False, 'Nwid'),
    'buying_players': (0x1E, False, 'Nbpl'),
    'hardness_of_training': (0x26, False, 'Nhat'),
    'mind_games': (0x1F, False, 'Nmig'),
    'squad_rotation': (0x27, False, 'Nrot'),
}
BOARD = {
    'business': (0x11, False, 'Nbus'),
    'interference': (0x16, False, 'Nint'),
    'resources': (0x1B, False, 'Nres'),
    'patience': (0x19, False, 'Npat'),
}
QUERY_ATTRIBUTES = frozenset(ATTRIBUTES) | {'adaptability'}
DISPATCH = {
    'staff': (0x5583660, 0xC9A0A8),
    'human_manager': (0x55AC480, 0x12E353C),
    'player_staff': (0x558F568, 0xD65178),
}


def decode(read, base, raw, kind, person_offset, data_offset):
    nonplayer_offset = data_offset - 8
    table_rva, getter_rva = DISPATCH[kind]
    table = base + table_rva
    if players.u64(raw, nonplayer_offset) != table:
        raise ValueError('Staff attribute base type changed')
    if players.u64(read(table + 26 * 8, 8)) != base + getter_rva:
        raise ValueError('Staff property getter changed')
    adjustment = struct.unpack('<q', read(table - 24, 8))[0]
    if adjustment != person_offset - 0x110 - nonplayer_offset:
        raise ValueError('Staff attribute person-data adjustment changed')
    if struct.unpack('<q', read(table - 16, 8))[0] != -nonplayer_offset:
        raise ValueError('Staff attribute base displacement changed')

    def group(fields):
        result = {}
        for name, (offset, fifths, _) in fields.items():
            value = raw[nonplayer_offset + offset]
            if value > (100 if fifths else 20):
                raise ValueError(f'Invalid stored staff rating: {name}')
            result[name] = max(1, min(20, (value + 2) // 5)) if fifths else value
        return result

    attributes = group(ATTRIBUTES)
    adaptability = raw[person_offset - 0xD0]
    if adaptability > 20:
        raise ValueError('Invalid stored staff adaptability')
    attributes['adaptability'] = adaptability
    return {'attributes': attributes, 'tendencies': group(TENDENCIES), 'board_attributes': group(BOARD),
            'attribute_evidence': 'installed_editor_property_names_and_native_getter_mapping',
            'attribute_scope': 'Underlying stored ratings converted with native scaling; role and UI visibility suppression are not applied. Direct native zero values remain zero. No new foreground UI comparison.'}
