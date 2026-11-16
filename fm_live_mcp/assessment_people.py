"""Canonical identities for selected assessment subjects and their assessors.

Assessor is a source-qualified relationship, not a scout job title. No native
function, generated profile or report evaluation is invoked.
"""
import struct

from . import database, players, staff, virtual_identity, world


class StalePlayerReference(ValueError):
    """A saved reference disagrees with a stable, verified current player."""


_PERSON_TYPES = {
    players.RVA[2]: ('actual', players.RVA[0], 0x388, b'N2db13ACTUAL_PLAYERE'),
    **{fields[1]: (kind, fields[0], fields[2], fields[4])
       for kind, fields in staff.LAYOUTS.items()},
    virtual_identity.PERSON_RVA: ('virtual', world.TYPES['virtual_player'][0], 0x20,
                                b'N2db14VIRTUAL_PLAYERE'),
}


def _address(value, size=0):
    if (type(value) is not int or value < 4096 or value % 8
            or value + size >= 1 << 64):
        raise ValueError('Invalid assessment PERSON pointer')
    return value


def verify_native(read, base):
    """Pin the proven player/non-player casts without invoking them."""
    _address(base, max(rva + len(raw) for rva, raw in NATIVE_SPANS))
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError(f'Assessment PERSON native layout changed at RVA {rva:#x}')


def _people(read, base, supplied):
    current = database.table(read, base, 'people')
    if (type(supplied) is not dict
            or any(type(supplied.get(key)) is not int
                   or supplied[key] != current[key]
                   for key in ('root', 'header', 'start', 'count'))
            or type(supplied.get('identity')) is not tuple
            or supplied['identity'] != current['identity']):
        raise ValueError('Assessment canonical PERSON table changed')
    return current


def _person(read, base, people, person):
    _address(person, 20)
    vtable, index, primary_id, secondary_id = struct.unpack('<QIII', read(person, 20))
    _address(vtable)
    if not primary_id or index >= people['count']:
        raise ValueError('Invalid assessment PERSON identity')
    if players.u64(read(people['start'] + index * 8, 8)) != person:
        raise ValueError('Assessment PERSON canonical slot changed')
    fields = _PERSON_TYPES.get(vtable - base)
    if fields is None:
        raise ValueError('Unrecognised assessment PERSON type')
    kind, primary_rva, person_offset, name = fields
    primary = _address(person - person_offset, person_offset + 20)
    if players.u64(read(primary, 8)) != base + primary_rva:
        raise ValueError('Assessment PERSON primary relation changed')
    for table, displacement in ((vtable, -person_offset), (base + primary_rva, 0)):
        actual, info = struct.unpack('<qQ', read(table - 16, 16))
        if actual != displacement:
            raise ValueError('Assessment PERSON displacement changed')
        _address(info, 16)
        text = players.u64(read(info + 8, 8))
        # Native RTTI string data need not have pointer alignment.
        if text < 4096 or text + len(name) + 1 >= 1 << 64:
            raise ValueError('Invalid assessment PERSON RTTI pointer')
        if read(text, len(name) + 1) != name + b'\0':
            raise ValueError('Assessment PERSON RTTI changed')
    public = {'display_name': None,
              'native_identity': {'database_index': index, 'native_id': primary_id,
                                  'random_id': None if secondary_id == primary_id else secondary_id},
              'record_kind': kind}
    return primary, person_offset, public, primary_id, secondary_id


def bound_player(read, base, tables, people, binding):
    """Rebind an existing actual/combined player_ref to its canonical PERSON.

    Legacy player refs may lack database_index; recover it from the checked
    PERSON header, then require its current canonical table slot. No virtual
    player or cached generated-profile binding is accepted.
    """
    _address(base)
    expected_tables = tuple(base + rva for rva in players.RVA)
    if (type(tables) is not tuple or tables != expected_tables
            or any(type(value) is not int for value in tables)):
        raise ValueError('Assessment player layout changed')
    if (type(binding) is not dict or binding.get('tables') != tables
            or type(binding.get('tables')) is not tuple
            or type(binding.get('identity')) is not tuple
            or binding.get('binding_kind') is not None
            or ('world_bound' in binding and type(binding['world_bound']) is not bool)):
        raise ValueError('Unsupported assessment player reference binding')
    primary = _address(binding.get('address'))
    if 'record_kind' in binding and binding['record_kind'] not in ('actual', 'player_staff'):
        raise ValueError('Unsupported assessment subject type')
    read = world.ReadSet(read)
    verify_native(read, base)
    current = _people(read, base, people)
    offset = players.person_offset(read, primary, tables)
    person = primary + offset
    found, checked_offset, public, primary_id, secondary_id = _person(read, base, current, person)
    kind = public['record_kind']
    if (found != primary or checked_offset != offset or kind not in ('actual', 'player_staff')
            or ('record_kind' in binding and binding['record_kind'] != kind)):
        raise ValueError('Assessment player reference type changed')
    index = public['native_identity']['database_index']
    saved_index = binding.get('database_index')
    if 'database_index' in binding and (type(saved_index) is not int
                                      or not 0 <= saved_index < 1 << 32):
        raise ValueError('Invalid assessment player reference database index')
    index_changed = 'database_index' in binding and saved_index != index
    table = base + (players.STAFF_RVA[2] if kind == 'player_staff' else players.RVA[2])
    adjustment = struct.unpack('<q', read(table - 0x678, 8))[0]
    if (players.u64(read(table + 0x668, 8)) != base + 0xD5C5FC
            or adjustment != -offset or person + adjustment != primary):
        raise ValueError('Assessment player PERSON cast changed')
    database.player_membership(read, base, current, index, primary)
    decoded, identity = players.decode(read, primary, tables)
    saved = binding['identity']
    if (len(saved) != len(identity)
            or any(type(value) is not type(expected) for value, expected in zip(saved, identity))):
        raise ValueError('Unsupported assessment player reference identity')
    saved_primary = saved[1] if kind == 'player_staff' else saved[0]
    if (not 1 <= saved_primary < 1 << 32 or not 0 <= saved[-1] < 1 << 32
            or (kind == 'player_staff' and saved[0] != 'player_staff')):
        raise ValueError('Unsupported assessment player reference identity')
    if ((identity[1] if kind == 'player_staff' else identity[0]) != primary_id
            or identity[-1] != secondary_id):
        raise ValueError('Assessment current player identity changed during read')
    if index_changed or saved != identity:
        read.verify()
        reason = 'database index' if index_changed else 'identity'
        raise StalePlayerReference(f'Assessment player reference {reason} changed')
    public['display_name'] = decoded['display_name']
    read.verify()
    return person, public


def assessor(read, base, people, person):
    """Return canonical assessor identity or an explicit known unavailable state.

    Staff, HUMAN and combined PLAYER/STAFF identities can be named. Other proved
    canonical PERSON kinds retain their IDs, with no invented name or scout job.
    Unrecognised native types and corrupt/stale identity links reject the read.
    """
    _address(base)
    if type(person) is int and person == 0:
        return {'state': 'null_person', 'display_name': None,
                'native_identity': None, 'record_kind': None}
    read = world.ReadSet(read)
    verify_native(read, base)
    current = _people(read, base, people)
    primary, offset, public, primary_id, secondary_id = _person(read, base, current, person)
    kind = public['record_kind']
    public['state'] = 'unsupported_person_kind'
    if kind in staff.LAYOUTS:
        data_offset = staff.LAYOUTS[kind][3]
        target_offset = data_offset - 8  # NON_PLAYER base precedes NON_PLAYING_DATA.
        table = base + staff.LAYOUTS[kind][1]
        adjustment = struct.unpack('<q', read(table - 0x668, 8))[0]
        if (players.u64(read(table + 0x658, 8)) != base + 0xCA4E78
                or adjustment != target_offset - offset
                or person + adjustment != primary + target_offset):
            raise ValueError('Assessment assessor PERSON cast changed')
        database.staff_membership(read, base, current, public['native_identity']['database_index'], primary)
        decoded, identity = staff.decode(read, base, primary)
        if identity[1] != primary_id or identity[-1] != secondary_id:
            raise ValueError('Assessment assessor identity changed')
        public.update(state='available', display_name=decoded['display_name'])
    read.verify()
    return public


# Batch20 labelled subject/assessor and prior canonical PERSON cast proof.
NATIVE_SPANS = (
    # player_person_cast
    (0xd5c5fc, bytes.fromhex('080040f908e119d1080140f90000088bc0035fd6')),
    # nonplayer_person_cast
    (0xca4e78, bytes.fromhex('080040f908a119d1080140f90000088bc0035fd6')),
    # actual_player_nonplayer_null
    (0xca49c0, bytes.fromhex('000080d2c0035fd6')),
    # staff_player_null
    (0xca49dc, bytes.fromhex('000080d2c0035fd6')),
)
