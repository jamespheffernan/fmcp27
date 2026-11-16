"""Selected-roster adapter for the current native national-duty/travel gate.

No native execution, generated profiles, attribute reads or saved-file fallback.
The gate is an input to final availability, not full eligibility or whereabouts.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import struct

from . import assessment_people, database, international_duty_source as duty
from . import players, prepared_tactics_source, virtual_identity, world
from .bridge import BridgeError

SCOPE = ('Requested distinct existing references on the selected HUMAN/TEAM native roster; '
         'this roster can include loaned-out players and does not establish whole-club '
         'coverage. PLAYER current club TEAM outside that selection remains outside_scope. '
         'The current native national assignment/travel gate and NATIONAL_TEAM+B8 native '
         'estimated return are not complete match eligibility, physical absence or a '
         'guaranteed actual return. No game calls, writes or profile generation.')


def _canonical_ref(read, base, address, kind, table_kind):
    world.typed(read, base, address, kind)
    _, index, uid, secondary = struct.unpack('<QIII', read(address, 20))
    table = database.table(read, base, table_kind)
    if (index >= table['count']
            or world.pointer(read, table['start'] + index * 8) != address):
        raise ValueError('International-duty canonical membership changed')
    return duty.CanonicalRef(address, index, uid, secondary)


def _public(ref):
    return {'database_index': ref.database_index, 'native_id': ref.native_id,
            'random_id': None if ref.secondary_id == ref.native_id else ref.secondary_id}


def _named_identity(read, primary, offset, kind, uid, secondary):
    # Stock player_ref identity fields only; shared PERSON_DATA names/birthday.
    delta = offset - 0x388
    first, last = (players.name_part(read, players.u64(read(primary + field + delta, 8)))
                   for field in (0x298, 0x2A0))
    common = players.common_name(read, players.u64(read(primary + 0x2A8 + delta, 8)))
    name = ' '.join(part for part in (first, last) if part) or common
    if not name:
        raise ValueError('International-duty player has no readable name')
    day, year = struct.unpack('<HH', read(primary + 0x2D0 + delta, 4))
    if not 1850 <= year <= 2200 or not 1 <= day <= 366:
        raise ValueError('Invalid international-duty player birth date')
    birthday = date(year, 1, 1) + timedelta(days=day - 1)
    if birthday.year != year:
        raise ValueError('Invalid international-duty player birth day')
    identity = (uid, first, last, birthday.isoformat(), secondary)
    if kind == 'player_staff':
        identity = ('player_staff', *identity)
    return identity, name, common or name


def _bound_person(read, base, tables, people, binding):
    if (type(tables) is not tuple or tables != tuple(base + rva for rva in players.RVA)
            or any(type(value) is not int for value in tables)):
        raise ValueError('International-duty player layout changed')
    if (type(binding) is not dict or type(binding.get('tables')) is not tuple
            or binding['tables'] != tables or type(binding.get('identity')) is not tuple
            or ('world_bound' in binding and type(binding['world_bound']) is not bool)):
        raise ValueError('Invalid international-duty player reference binding')
    primary = assessment_people._address(binding.get('address'))
    table = world.pointer(read, primary)
    offsets = {base + players.RVA[0]: 0x388, base + players.STAFF_RVA[0]: 0x480,
               base + world.TYPES['virtual_player'][0]: 0x20}
    offset = offsets.get(table)
    if offset is None:
        raise ValueError('Unsupported international-duty player primary type')
    found, actual_offset, public, uid, secondary = assessment_people._person(
        read, base, people, primary + offset)
    kind = public['record_kind']
    index = public['native_identity']['database_index']
    if (found != primary or actual_offset != offset
            or ('record_kind' in binding and binding['record_kind'] != kind)
            or ('database_index' in binding and (type(binding['database_index']) is not int
                                               or binding['database_index'] != index))):
        raise ValueError('International-duty player reference type/index changed')
    ref = duty.CanonicalRef(primary + offset, index, uid, secondary)
    if kind == 'virtual':
        saved = binding['identity']
        if (binding.get('binding_kind') != virtual_identity.BINDING_KIND
                or saved != (virtual_identity.BINDING_KIND, index, uid, secondary)
                or any(type(value) is not int for value in saved[1:])):
            raise ValueError('Invalid international-duty compact reference identity')
        return ref, kind, None, None
    if binding.get('binding_kind') is not None or kind not in ('actual', 'player_staff'):
        raise ValueError('Unsupported international-duty reference kind')
    # Existing canonical PLAYER membership and literal cast, without decode().
    person_table = base + (players.STAFF_RVA[2] if kind == 'player_staff' else players.RVA[2])
    if (players.u64(read(person_table + 0x668, 8)) != base + 0xD5C5FC
            or struct.unpack('<q', read(person_table - 0x678, 8))[0] != -offset):
        raise ValueError('International-duty PERSON player cast changed')
    database.player_membership(read, base, people, index, primary)
    identity, name, display = _named_identity(read, primary, offset, kind, uid, secondary)
    saved = binding['identity']
    if (len(saved) != len(identity) or saved != identity
            or any(type(value) is not type(expected) for value, expected in zip(saved, identity))):
        raise ValueError('International-duty player reference identity changed')
    return ref, kind, name, display


def _checked_result(read, base, primary, result, current_date):
    if result['current_date'] != current_date:
        raise ValueError('International-duty date differs from loaded save')
    gate = result['national_assignment_gate']
    if ((result['state'] == 'available') != (type(gate) is bool)
            or result['state'] not in ('available', 'unavailable')
            or (gate is not None and type(gate) is not bool)
            or result['eligibility_state'] != 'not_evaluated'):
        raise ValueError('International-duty state/gate domain changed')
    if gate is not True:
        expected = 'not_applicable' if gate is False else 'not_proved'
        if (result['return_date'] is not None or result['return_date_state'] != expected
                or result['native_gate_reason'] is not None):
            raise ValueError('Unavailable/false duty gate supplies a date or reason')
        return result
    reason = result['native_gate_reason']
    if (type(reason) is not dict or reason.get('code') not in (4, 15, 16)
            or reason.get('scope') != 'input_to_final_availability'):
        raise ValueError('International-duty native reason domain changed')
    national = world.pointer(read, primary + 0x120)
    national_ref = _canonical_ref(read, base, national, 'national_team', 'teams')
    if result['national_team_identity'] != _public(national_ref):
        raise ValueError('International-duty national TEAM identity differs')
    container = world.pointer(read, national + 0x30)
    _canonical_ref(read, base, container, 'national_team_container', 'national_team_containers')
    if national not in world.vector(read, container + 0x18, 256):
        raise ValueError('International-duty national TEAM owner backlink differs')
    raw = read(national + 0xB8, 4)
    low, year = struct.unpack('<HH', raw)
    sentinel = (year, low & 511) == (1900, 1)
    if sentinel:
        if result['return_date'] is not None or result['return_date_state'] != 'not_applicable':
            raise ValueError('International-duty sentinel date supplies a return estimate')
    elif (result['return_date'] != world.packed_date(raw)
          or result['return_date_state'] != 'native_estimated_return'):
        raise ValueError('International-duty return estimate differs from NATIONAL_TEAM+B8')
    return {**result, 'native_estimated_return_source': 'NATIONAL_TEAM_plus_0xb8'}


def get_player_international_duty(bridge, session_id, player_refs, coach_name=None):
    """Read 1–100 distinct existing refs, rejecting a drifting batch as a whole."""
    if (type(player_refs) is not list or not 1 <= len(player_refs) <= 100
            or any(type(ref) is not str or not ref for ref in player_refs)
            or len(set(player_refs)) != len(player_refs)):
        raise BridgeError('Supply 1 through 100 distinct nonempty player references.')
    if coach_name is not None and (type(coach_name) is not str or not 1 <= len(coach_name) <= 256):
        raise BridgeError('coach_name must be a name returned by fm_get_save.')
    try:
        with bridge.lock, bridge._read_scope(session_id):
            process = bridge._current(session_id)
            tables = bridge._player_layout(process)
            plugin = deepcopy(bridge.plugin_identity)
            read, loaded, identity = bridge._world_state(process, tables)
            save, identity = deepcopy(loaded), deepcopy(identity)
            if bridge.world_identity != identity:
                raise ValueError('International-duty world binding differs')
            base = tables[0] - players.RVA[0]
            coach = deepcopy(bridge._select_coach(save, coach_name))
            team, human = prepared_tactics_source._team_and_human(read, base, coach)
            selected_team = _canonical_ref(read, base, coach['team_address'], 'team', 'teams')
            roster = world.vector(read, coach['team_address'] + 0x38, 256)
            people = database.table(read, base, 'people')
            assessment_people.verify_native(read, base)
            duty.verify_native(read, base)
            bindings, rows = {}, []
            for reference in player_refs:
                binding = bridge.player_refs.get(reference)
                if type(binding) is not dict:
                    raise ValueError('Unknown or expired player reference')
                binding = deepcopy(binding)
                if binding.get('address') not in roster:
                    raise ValueError('Player reference is outside the selected native TEAM roster')
                bindings[reference] = binding
                person, kind, name, display = _bound_person(read, base, tables, people, binding)
                row = {'player_ref': reference, 'native_identity': _public(person),
                       'record_kind': kind, 'name': name, 'display_name': display,
                       'name_state': 'unavailable_without_generated_profile' if kind == 'virtual'
                                     else 'stored_native_name_fields',
                       'current_date': save['current_date'], 'state': 'unsupported_type',
                       'reason': 'compact_virtual_not_supported_no_generation',
                       'national_assignment_gate': None, 'native_gate_reason': None,
                       'national_team_identity': None, 'return_date': None,
                       'return_date_state': 'not_proved', 'eligibility_state': 'not_evaluated'}
                if kind != 'virtual':
                    current_team = players.u64(read(binding['address'] + 0x128, 8))
                    if current_team != selected_team.address:
                        outside = (_canonical_ref(read, base, current_team, 'team', 'teams')
                                   if current_team else None)
                        row.update(state='outside_scope',
                                   reason='PLAYER_current_club_TEAM_differs_from_selected_TEAM',
                                   current_club_team=_public(outside) if outside else None)
                    else:
                        row.update(_checked_result(read, base, binding['address'],
                            duty.read_current(read, base, person=person, club_team=selected_team),
                            save['current_date']))
                rows.append(row)
            read.verify()
            current = bridge._current(session_id)
            if current != process:
                raise ValueError('International-duty process lifetime changed')
            after_tables = bridge._player_layout(current)
            if after_tables != tables or bridge.plugin_identity != plugin:
                raise ValueError('International-duty loaded plugin/build changed')
            after_read, after_save, after_identity = bridge._world_state(current, after_tables)
            if (after_identity != identity or bridge.world_identity != identity or after_save != save):
                raise ValueError('International-duty loaded save/date context changed')
            after_coach = bridge._select_coach(after_save, coach_name)
            after_team, after_human = prepared_tactics_source._team_and_human(after_read, base, after_coach)
            after_roster = world.vector(after_read, after_coach['team_address'] + 0x38, 256)
            if (after_coach != coach or after_team != team or after_human != human or after_roster != roster):
                raise ValueError('International-duty selected coach/TEAM/roster changed')
            if any(bridge.player_refs.get(ref) != value for ref, value in bindings.items()):
                raise ValueError('International-duty player reference binding changed')
            read.verify()
            after_read.verify()
            if bridge._current(session_id) != process:
                raise ValueError('International-duty process lifetime changed')
            # Recheck both source journals after the final lifetime callback.
            read.verify()
            after_read.verify()
            if (bridge.plugin_identity != plugin or bridge.world_identity != identity
                    or any(bridge.player_refs.get(ref) != value for ref, value in bindings.items())):
                raise ValueError('International-duty final context/reference binding changed')
            return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                    'save': bridge._public_save(save), 'coach': coach['name'], 'club': coach['club'],
                    'team': team, 'players': rows, 'count': len(rows),
                    'source': 'current_native_national_assignment_travel_gate',
                    'scope': SCOPE, 'atomic': False, 'saved_file_fallback': False}
    except (ValueError, IndexError, KeyError, TypeError, BridgeError) as exc:
        raise BridgeError(f'International-duty query rejected; no partial result returned: {exc}') from exc
