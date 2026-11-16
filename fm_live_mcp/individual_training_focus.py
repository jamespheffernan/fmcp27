"""Stored focus and club intensity of checked regular ACTUAL_PLAYER records.

Call only inside the caller's verified plugin-build, loaded-save/process lifetime
and selected HUMAN/TEAM scope. The caller must recheck that outer scope before
publishing. This module checks canonical TEAM/PLAYER/PERSON ownership, binding
identity and every byte it consumes, without profile/attribute decoding.

INDIVIDUAL_TRAINING_INFO is a plain ten-byte pool record, not a polymorphic
object. Native allocation uses stride ten, so child addresses need not be
8-aligned. The native getter needs only byte+6; this reader deliberately
requires the complete ten-byte record. PLAYER/TEAM object addresses still
require eight-byte alignment. This supersedes the frozen source brief's
ambiguous proposed child-alignment wording.
No role assignment, applied intensity, workload, recommendation or effective UI state
is inferred. No native getter, allocator, setter or profile generator is called.
"""
from datetime import date, timedelta
import hashlib
import struct

from . import assessment_people, database, individual_training_intensity, players, teams, virtual_identity, world

PLUGIN_SHA256 = players.SHA256
ENGLISH_SHA256 = '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'
INFO_BYTES = 10
SCOPE = ('Stored additional focus and club intensity on the current PLAYER record only; no effective '
         'training, recommendation, training role/position, applied intensity, workload, '
         'attendance or development outcome. Non-atomic reads with byte rechecks.')
# Exact FM27 formatter1327438 switch and pinned English resource; source packet
# evidence/individual-training-20261108, independently reviewed before integration.
FOCUS = {
    0: (684078, 'Quickness Rehab'),
    1: (684079, 'Agility and Balance Rehab'),
    2: (716160, 'Resistance Rehab'),
    3: (684081, 'Endurance Rehab'),
    4: (467459, 'General Rehab'),
    5: (439723, 'Free Kick Taking'),
    6: (596732, 'Corner Taking'),
    7: (439724, 'Penalty Taking'),
    8: (308901, 'Long Throws'),
    9: (308890, 'Quickness'),
    10: (467457, 'Agility and Balance'),
    11: (716161, 'Resistance'),
    12: (467458, 'Endurance'),
    13: (716162, 'Chance Conversion'),
    14: (716163, 'Chance Creation'),
    15: (716164, 'Ball Retention'),
    16: (716165, 'Ball Progression'),
    17: (716166, 'Pressing'),
    18: (716167, 'Containment'),
    19: (467460, 'Defensive Positioning'),
    20: (467461, 'Attacking Movement'),
    21: (467462, 'Final Third'),
    22: (229306, 'Shooting'),
    23: (227881, 'Passing'),
    24: (227798, 'Crossing'),
    25: (492251, 'Ball Control'),
    26: (716168, 'Tackling'),
    27: (716169, 'Marking'),
    28: (492252, 'Aerial'),
    29: (716170, 'GK Shot Stopping'),
    30: (716171, 'GK Handling'),
    31: (492256, 'GK Sweeping'),
    32: (716172, 'GK Distribution'),
}

NATIVE_GUARDS = (
    (0x2cdee14, 28, '942db8975897fbda7843c0d1ea6e63929c4cf7c95a85f55d6e700b75b3d6330d'),  # getter_absent_signed
    (0x1327438, 68, 'a442adbc075c30e533032dad5155385545bb7997abb38542f295eadba912c652'),  # formatter_bound_and_dispatch
    (0x132747c, 3772, '0c9b398659e130572813ac9c18b3fd42c80972c502779cab75f7d6147f9a7321'),  # formatter_cases
    (0x5393b5a, 66, 'b81ba18e3a6f2db148a6cb1ba1d726ed4dedba9246db5ea8b2b4ef870f144933'),  # formatter_table
    (0x2cf5740, 24, '4571859ab791f368f06003732bbf3b1f6552587bed446b61b1c686b924af0e07'),  # audit_stored_focus
    (0x2cf5964, 56, 'dda51eb474edadb787c2e33cf69239ca30db6283cff968a8c4e6b5f3b11cb844'),  # audit_property_name
    (0x17f5d90, 44, '380389d5c31c8c2492e562f00f792569cec3c360af81f99398674f07cf18d812'),  # typed_pool_name_and_size
    (0x17f5d58, 28, 'f6528626cdc693bd1cdd73e40a9949267678dad93c27bc453013757e5b820958'),  # child_default
    (0x13272b4, 344, '0f8474bd2f6e43c6b88f571dae110056027acf3825013722aee4670563263c97'),  # child_writer
    (0x1326ec4, 564, '0dc5c6fedb0f3b82315295674804ccb102648e14138caaea7c5bd1be46c7bc56'),  # child_reader
    (0xcfd99c, 16, 'dff3ba4df1c02c6e74b24429fd65c98b1a8434fd5a6e6508a6c1b90f99f8728f'),  # player_composite_reader
    (0x2cdeb4c, 40, '7b9da2799aede6bee7ecde05a912aec732625ecd0daec5bb147f65f59070e99e'),  # focus_setter
    (0x2cf59d4, 164, '6628296fe418f1f53f3bcd6a5301a01e22ff6384aa1d6b64682a9f4f93eb9d95'),  # stored_intensity_audit
    (0x2cecc84, 956, 'a644b47ebe174dc8e1a151613f0b524e34e80bb3d342f423d7f8317a6ae2b15b'),  # intensity_formatter
)


def _address(value, size=0, *, aligned=True):
    if (type(value) is not int or value < 4096
            or (aligned and value % 8) or value + size >= 1 << 64):
        raise ValueError('Invalid individual-training source address')
    return value


def verify_native(read, base):
    _address(base)
    for rva, size, expected in NATIVE_GUARDS:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != expected:
            raise ValueError(f'Individual-focus native source changed at RVA {rva:#x}')
    assessment_people.verify_native(read, base)
    individual_training_intensity.verify_native(read, base)


def focus(raw_code):
    """Keep all byte codes; zero is named, FF is unset, others stay unknown."""
    if type(raw_code) is not int or not 0 <= raw_code <= 255:
        raise ValueError('Expected an individual-focus byte')
    signed = raw_code if raw_code < 128 else raw_code - 256
    key, name = FOCUS.get(raw_code, (None, None))
    state = 'unset' if signed == -1 else 'stored_named_focus' if name else 'unknown_native_code'
    return {'raw_code': raw_code, 'native_code': signed, 'state': state,
            'english_definition_name': name, 'english_resource_key': key}


def _identity(read, primary, primary_id, secondary_id):
    # These are the existing ordinary player_ref identity fields, not attributes.
    handles = struct.unpack('<QQQ', read(primary + 0x298, 24))
    first, last = (players.name_part(read, h) for h in handles[:2])
    common = players.common_name(read, handles[2])
    name = ' '.join(part for part in (first, last) if part) or common
    display = common or name
    if not display:
        raise ValueError('Individual-focus player has no readable name')
    day, year = struct.unpack('<HH', read(primary + 0x2D0, 4))
    if not 1850 <= year <= 2200 or not 1 <= day <= 366:
        raise ValueError('Invalid individual-focus player birth date')
    birthday = date(year, 1, 1) + timedelta(days=day - 1)
    if birthday.year != year:
        raise ValueError('Invalid individual-focus player birth day')
    return (primary_id, first, last, birthday.isoformat(), secondary_id), name, display


def inspect(read, base, tables, people, binding, *, team_address):
    """Read one existing ref belonging to the caller's selected managed TEAM.

    Caller MUST establish players.disk_uuid/verify_runtime, current loaded-save
    and process lifetime, and canonical selected HUMAN/TEAM ownership. Recheck
    that outer scope after this returns; internal checks do not replace it.
    The complete source read is kept in a local ReadSet and rechecked here.
    Combined/compact virtual identities return unsupported without inspecting
    their training child. Unknown types/identities/owners reject the read.
    """
    _address(base)
    _address(team_address, 0x50)
    if (type(tables) is not tuple or tables != tuple(base + rva for rva in players.RVA)
            or any(type(v) is not int for v in tables)):
        raise ValueError('Individual-focus player layout changed')
    if (type(binding) is not dict or type(binding.get('tables')) is not tuple
            or binding['tables'] != tables or type(binding.get('identity')) is not tuple
            or ('world_bound' in binding and type(binding['world_bound']) is not bool)):
        raise ValueError('Invalid individual-focus player reference binding')
    primary = _address(binding.get('address'))
    read = world.ReadSet(read)
    verify_native(read, base)
    current = assessment_people._people(read, base, people)
    team_index = struct.unpack('<I', read(team_address + 8, 4))[0]
    team, team_binding = teams.by_index(read, base, team_index)
    if team['kind'] != 'team' or team_binding['address'] != team_address:
        raise ValueError('Individual-focus canonical TEAM ownership changed')
    if primary not in world.vector(read, team_address + 0x38, 256):
        raise ValueError('Individual-focus player is not on the selected TEAM roster')
    primary_table = players.u64(read(primary, 8))
    offsets = {base + players.RVA[0]: 0x388,
               base + players.STAFF_RVA[0]: 0x480,
               base + world.TYPES['virtual_player'][0]: 0x20}
    offset = offsets.get(primary_table)
    if offset is None:
        raise ValueError('Unrecognised individual-focus player primary type')
    found, checked_offset, public, primary_id, secondary_id = assessment_people._person(
        read, base, current, primary + offset)
    kind = public['record_kind']
    if (found != primary or checked_offset != offset
            or ('record_kind' in binding and binding['record_kind'] != kind)):
        raise ValueError('Individual-focus player reference type changed')
    index = public['native_identity']['database_index']
    if ('database_index' in binding and (type(binding['database_index']) is not int
                                       or binding['database_index'] != index)):
        raise ValueError('Individual-focus player reference database index changed')
    saved = binding['identity']
    if kind != 'actual':
        if kind == 'player_staff':
            valid = (binding.get('binding_kind') is None and len(saved) == 6
                     and saved[0] == 'player_staff' and type(saved[1]) is int
                     and saved[1] == primary_id and type(saved[-1]) is int
                     and saved[-1] == secondary_id)
        elif kind == 'virtual':
            valid = (binding.get('binding_kind') == virtual_identity.BINDING_KIND
                     and saved == (virtual_identity.BINDING_KIND, index, primary_id, secondary_id)
                     and all(type(v) is int for v in saved[1:]))
        else:
            valid = False
        if not valid:
            raise ValueError('Unsupported individual-focus player reference identity')
        read.verify()
        return {'source_state': 'unsupported_record_kind', 'record_kind': kind,
                'native_identity': public['native_identity'], 'name': None,
                'display_name': None, 'name_state': 'unsupported_record_kind',
                'additional_focus': None, 'club_training_intensity': None, 'scope': SCOPE}
    if binding.get('binding_kind') is not None:
        raise ValueError('Unsupported individual-focus regular-player binding kind')
    if players.u64(read(primary + 0x140, 8)) != tables[1]:
        raise ValueError('Individual-focus PLAYING_DATA type changed')
    cast = struct.unpack('<q', read(tables[2] - 0x678, 8))[0]
    if (players.u64(read(tables[2] + 0x668, 8)) != base + 0xD5C5FC
            or cast != -0x388 or primary + offset + cast != primary):
        raise ValueError('Individual-focus PERSON player cast changed')
    database.player_membership(read, base, current, index, primary)
    identity, name, display = _identity(read, primary, primary_id, secondary_id)
    if (len(saved) != 5 or any(type(v) is not type(e) for v, e in zip(saved, identity))
            or saved != identity):
        raise ValueError('Individual-focus player reference identity changed')
    child = players.u64(read(primary + 0x190, 8))
    if child:
        # Native ten-byte pool records may have a non-eight-aligned stride.
        _address(child, INFO_BYTES, aligned=False)
        raw = read(child, INFO_BYTES)
        value, state = focus(raw[6]), 'present_child'
    else:
        value, state = focus(255), 'missing_child'
    intensity = individual_training_intensity.decode(read(primary + individual_training_intensity.OFFSET, 1)[0])
    read.verify()
    return {'source_state': state, 'record_kind': 'actual',
            'native_identity': public['native_identity'], 'name': name,
            'display_name': display, 'name_state': 'available',
            'additional_focus': value, 'club_training_intensity': intensity, 'scope': SCOPE}
