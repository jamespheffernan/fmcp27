"""Caller-owned passive MATCH read: participating teams and stored manager plans.

Caller supplies a freshly derived resident GAME_MATCH, owns the ReadSet/epoch,
and independently binds any fixture. This module never labels kickoff, display
clock, active-player state or effective instructions.
"""
import hashlib
import json
import struct

from . import players, prepared_tactics_source, prepared_tactics_fields
from . import prepared_tactic_instructions, prepared_tactic_roles, teams, world

MATCH_VTABLE = 0x55FA258
MANAGER_VTABLE = 0x55FA760
MAX_MATCH_PLAYER_SLOTS = 26


def verify_native(read, base):
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError('Resident match-plan native source changed')
    prepared_tactics_fields.verify_native(read, base)
    prepared_tactic_instructions.verify_native(read, base)
    prepared_tactic_roles.verify_native(read, base)


def inspect(read, base, engine, expected_team_indices=None, *, include_raw_instructions=False):
    """Return checked current stored settings; caller verifies ReadSet before use.

    expected_team_indices, when supplied, are the ordered canonical TEAM ordinals
    from an independently checked fixture. Equality verifies teams, not fixture
    identity: another match between the same teams remains possible.
    """
    if type(include_raw_instructions) is not bool:
        raise ValueError('include_raw_instructions must be boolean')
    if expected_team_indices is not None and (not isinstance(expected_team_indices, (list, tuple))
            or len(expected_team_indices) != 2
            or any(type(i) is not int or i < 0 for i in expected_team_indices)):
        raise ValueError('Expected teams must be two ordered canonical TEAM indices')
    verify_native(read, base)
    prepared_tactics_source._typed(read, base, engine, MATCH_VTABLE, b'10GAME_MATCH')
    sides = []
    manager_pointers = []
    for side_index in range(2):
        side = world.pointer(read, engine + 0x15370 + side_index * 8)
        team_address = world.pointer(read, side + 0xB8)
        index = struct.unpack('<I', read(team_address + 8, 4))[0]
        team, binding = teams.by_index(read, base, index)
        if binding['address'] != team_address:
            raise ValueError('Resident match canonical TEAM pointer changed')
        if expected_team_indices is not None and index != expected_team_indices[side_index]:
            raise ValueError('Resident match ordered TEAM differs from expected fixture')
        # Independent reverse links: each nonnull player's MATCH/side must agree,
        # and each nonnull manager must be the same typed per-side manager.
        players_raw = read(side + 0x140, MAX_MATCH_PLAYER_SLOTS * 8)
        if len(players_raw) != MAX_MATCH_PLAYER_SLOTS * 8:
            raise ValueError('Incomplete resident match player slots')
        managers = set()
        checked_players = 0
        slots_without_manager = 0
        for (player,) in struct.iter_unpack('<Q', players_raw):
            if not player:
                continue
            manager = players.u64(read(player + 0x298, 8))
            if not manager:
                slots_without_manager += 1
                continue
            if (world.pointer(read, player + 0x280) != engine
                    or world.pointer(read, player + 0x288) != side):
                raise ValueError('Resident match player reverse links disagree')
            managers.add(manager)
            checked_players += 1
        if len(managers) != 1:
            raise ValueError('Resident side manager is missing or ambiguous')
        manager, = managers
        prepared_tactics_source._typed(read, base, manager, MANAGER_VTABLE, b'18GAME_MATCH_MANAGER')
        if (world.pointer(read, manager + 0x280) != engine
                or world.pointer(read, manager + 0x288) != side):
            raise ValueError('Resident typed manager reverse links disagree')
        creator = manager + 0x1800
        plan = prepared_tactics_fields.decode(read, base, creator)
        plan.update(prepared_tactic_instructions.decode(read, creator))
        if include_raw_instructions:
            flags = read(creator + 0xE0, 11)
            if len(flags) != 11:
                raise ValueError('Incomplete resident instruction flags')
            plan['team_instructions']['raw_selection_flags_hex'] = flags.hex()
            bits = int.from_bytes(flags, 'little')
            plan['team_instructions']['unclassified_selected_bits'] = [i for i in (0,84,85,86,87) if bits & (1 << i)]
        for phase_name, phase in plan['phases'].items():
            for position in phase['positions']:
                position['stored_base_role'] = prepared_tactic_roles.decode(
                    read, creator, phase_name, position['position_index'])
        sides.append({'side_index': side_index, 'team': team, 'plan': plan,
                      'manager_type': 'GAME_MATCH_MANAGER',
                      'source': 'participating_MATCH_side_and_reverse_linked_resident_manager',
                      'checked_match_player_reverse_links': checked_players,
                      'player_slots_without_manager': slots_without_manager,
                      'temporal_state': 'currently_resident_stored_manager_settings',
                      'effective_instructions_verified': False,
                      'effective_individual_overrides_verified': False,
                      'actual_kickoff_plan_verified': False})
        manager_pointers.append(manager)
    if manager_pointers[0] == manager_pointers[1] or sides[0]['team']['database_index'] == sides[1]['team']['database_index']:
        raise ValueError('Resident match sides are not distinct')
    result = {'source': 'resident_GAME_MATCH_stored_manager_plans', 'source_state': 'available',
              'sides': sides, 'expected_ordered_teams_matched': expected_team_indices is not None,
              'fixture_binding_state': 'requires_independent_exact_fixture_binding',
              'actual_kickoff_plan_verified': False, 'display_clock_alignment_verified': False,
              'saved_file_fallback': False,
              'limits': ['Stored game-manager settings can advance independently of the presented match clock.',
                         'This is not proof of kickoff settings or a complete tactical-change history.',
                         'Named pressing/trap settings do not establish effective individual overrides or tactical success.',
                         'Expected team equality alone does not identify the particular fixture.']}
    raw = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    return {**result, 'content_sha256': hashlib.sha256(raw).hexdigest()}


# MATCH_MANAGER::load_tactics passes manager+1800 to the engine tactic supplier;
# MATCH_PLAYER setup consumes manager+1920/1C40 position rows and phase role masks.
NATIVE_SPANS = (
    (0x451f248, bytes.fromhex('0a4041f908b08a522800a072496968f816008352282540a91f0109eba002005418008052753ecb390a214039aa001037084100911f0109eb80010054fbffff17000140f90a0040f94a2540f96202168be10315aae92300a940013fd6')),
    (0x46ff604, bytes.fromhex('f85fbca9f65701a9f44f02a9fd7b03a9fdc30091f30300aa1404409108904df9080e00b596467939df2e007122100054684e41f98946b9391511098b160083526a4241f94a5540914b7955390b0d00364c9555390b2483520b010b8b0d0980522d7d2d9b60696db860220db960da0cb99f050071610c00540c0980522b2d2c9b6b2140f96bb206f96b8e06f90b01098b8df683526b696d387ffd03712b018b1a6b1d40936b212c9b6c415cb96cfa0db96cb20db96b414ef96b1e07f96bfa06f96b424cf98b0000b4607100b94add44b96a050034')),
    (0x46ff790, bytes.fromhex('68424cf9006100b969da4cb9097500b9698e46f9eadf9bd2ea21b5f22a69cff26a7fe0f229010a8a6ab24db90a7900b96afa46f9ebff9fd2eb03bff26bffc7f24a010b8a09a900a9')),
)
