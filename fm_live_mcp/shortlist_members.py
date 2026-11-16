"""Page existing personal shortlist slots and bind supported canonical players.

Known staff, HUMAN and compact virtual PERSON types remain explicit unsupported
rows. Unrecognised vtables are rejected, rather than treated as valid profiles.
"""
import struct

from . import database, players, world


MAX_SLOTS = 100000
_PERSON_TYPES = {
    players.RVA[2]: ('actual', players.RVA[0], 0x388, b'N2db13ACTUAL_PLAYERE'),
    players.STAFF_RVA[2]: ('player_staff', players.STAFF_RVA[0], 0x480,
                          b'N2db28ACTUAL_PLAYER_AND_NON_PLAYERE'),
    0x55849D8: ('staff', 0x5583660, 0x208, b'N2db17ACTUAL_NON_PLAYERE'),
    0x55AD820: ('human_manager', 0x55AC480, 0x548, b'N2db16HUMAN_NON_PLAYERE'),
    0x55CB9F8: ('virtual', 0x55CAC48, 0x20, b'N2db14VIRTUAL_PLAYERE'),
}


def _address(value, size=0):
    if (type(value) is not int or value < 4096 or value % 8
            or value + size >= 1 << 64):
        raise ValueError('Invalid shortlist member pointer')
    return value


def verify_native(read, base):
    """Pin physical membership order/null branches and the PERSON player cast."""
    _address(base, max(rva + len(raw) for rva, raw in NATIVE_SPANS))
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError(f'Shortlist membership native layout changed at RVA {rva:#x}')


def _geometry(read, address, total):
    start, end, capacity = struct.unpack('<QQQ', read(address + 0x80, 24))
    if (not start <= end <= capacity or any(v % 8 for v in (start, end, capacity))
            or capacity - start > MAX_SLOTS * 8):
        raise ValueError('Invalid shortlist member vector geometry')
    if (start, end, capacity) != (0, 0, 0):
        _address(start)
        _address(end)
        _address(capacity)
    if (end - start) // 8 != total:
        raise ValueError('Shortlist member count changed')
    return start


def _person_type(read, base, person, vtable):
    fields = _PERSON_TYPES.get(vtable - base)
    if fields is None:
        raise ValueError('Unrecognised shortlist PERSON vtable')
    kind, primary_rva, offset, name = fields
    primary = _address(person - offset, offset + 20)
    if players.u64(read(primary, 8)) != base + primary_rva:
        raise ValueError('Shortlist PERSON primary type changed')
    for table, displacement in ((vtable, -offset), (base + primary_rva, 0)):
        actual, info = struct.unpack('<qQ', read(table - 16, 16))
        if actual != displacement:
            raise ValueError('Shortlist PERSON displacement changed')
        _address(info, 16)
        name_pointer = players.u64(read(info + 8, 8))
        # Native RTTI string pointers can be unaligned.
        if name_pointer < 4096 or name_pointer + len(name) + 1 >= 1 << 64:
            raise ValueError('Invalid shortlist PERSON RTTI name pointer')
        if read(name_pointer, len(name) + 1) != name + b'\0':
            raise ValueError('Shortlist PERSON RTTI changed')
    return kind, primary, offset


def page(read, base, tables, list_address, total, offset, limit):
    """Return one row per requested stored slot; the caller publishes references.

    Read only the requested member-pointer slice. A local consumed-byte recheck
    rejects detected drift before returning; callers also recheck their complete
    owner/save/source scope before publication. No expiry or report state is
    inferred, and no native function or profile generator is executed.
    """
    if (type(total) is not int or not 0 <= total <= MAX_SLOTS
            or type(offset) is not int or offset < 0
            or type(limit) is not int or not 1 <= limit <= 100):
        raise ValueError('Invalid shortlist member page bounds')
    _address(base)
    if (type(tables) is not tuple or tables != tuple(base + rva for rva in players.RVA)
            or any(type(value) is not int for value in tables)):
        raise ValueError('Shortlist player layout changed')
    _address(list_address, 0x98)
    read = world.ReadSet(read)
    verify_native(read, base)
    start = _geometry(read, list_address, total)
    count = min(limit, max(0, total - offset))
    if not count:
        read.verify()
        return []
    pointers = struct.unpack(f'<{count}Q', read(start + offset * 8, count * 8))
    people = None
    result = []
    for index, entry in enumerate(pointers, offset):
        row = {'native_entry_index': index, 'state': 'null_entry',
               'display_name': None, 'native_identity': None, 'record_kind': None}
        if not entry:
            result.append((row, None))
            continue
        _address(entry, 8)
        person = players.u64(read(entry, 8))
        if not person:
            row['state'] = 'null_person'
            result.append((row, None))
            continue
        _address(person, 20)
        vtable, person_index, primary_id, secondary_id = struct.unpack('<QIII', read(person, 20))
        _address(vtable)
        if not primary_id:
            raise ValueError('Shortlist PERSON identity is missing')
        if people is None:
            people = database.table(read, base, 'people')
        if (person_index >= people['count']
                or players.u64(read(people['start'] + person_index * 8, 8)) != person):
            raise ValueError('Shortlist PERSON canonical membership changed')
        kind, primary, person_offset = _person_type(read, base, person, vtable)
        row.update(state='unsupported_person_kind', record_kind=kind,
                   native_identity={'database_index': person_index, 'native_id': primary_id,
                                    'random_id': None if secondary_id == primary_id else secondary_id})
        binding = None
        if kind in ('actual', 'player_staff'):
            adjustment = struct.unpack('<q', read(vtable - 0x678, 8))[0]
            if (players.u64(read(vtable + 0x668, 8)) != base + 0xD5C5FC
                    or adjustment != -person_offset or person + adjustment != primary):
                raise ValueError('Shortlist PERSON player cast changed')
            database.player_membership(read, base, people, person_index, primary)
            decoded, identity = players.decode(read, primary, tables)
            decoded_primary = identity[1] if kind == 'player_staff' else identity[0]
            if decoded_primary != primary_id or identity[-1] != secondary_id:
                raise ValueError('Shortlist player identity changed')
            row.update(state='player', display_name=decoded['display_name'])
            binding = {'address': primary, 'identity': identity, 'tables': tables,
                       'world_bound': True, 'database_index': person_index,
                       'record_kind': kind}
        result.append((row, binding))
    read.verify()
    return result


# Accepted recruitment-shortlists-18 membership and existing PERSON cast proof.
NATIVE_SPANS = (
    # remove_membership
    (0x1926564, bytes.fromhex(
        'e82740f9091d41f9081941f93f0108eba0160054fb0700f91a0080d2ff1300f90c0080d2010080d21b797af868334139'
        '48020035682748a9290108ebe001005429fd43933f0500f129859f9a0a0140f9ea0000b44a0140f9aa0000b44a0940b9'
        '8b0b40b95f010b6b8001005408210091290500f1c1feff545a070091e82740f9091d41f9081941f9290108cb5f0f89eb'
        'c3fcff5435000014e81340f99f0108eb'
    )),
    # add_duplicate_membership
    (0x18cc294, bytes.fromhex(
        'a81e41f9a91a41f91f0109eb60040054180080d22a7978f8aa831af84b314139eb020035482548a9290108ebe0010054'
        '29fd43933f0500f129859f9a0a0140f9ea0000b44a0140f9aa0000b44a0940b96b0b40b95f010b6bc001005408210091'
        '290500f1c1feff54e0a30091a16301d16a6c4894a81e41f9a91a41f9180700910a0109cb1f0f8aeb63fcff5403000014'
    )),
    # person_primary_cast
    (0xd5c5fc, bytes.fromhex(
        '080040f908e119d1080140f90000088bc0035fd6'
    )),
    # entry_count_and_order
    (0x14d6e44, bytes.fromhex(
        '892248a9080109cb08fd43d3e80b00b9750240f9a80240f9081940f9e1230091e00315aa8200805200013fd6a81240b9'
        'e8e5ff35e80b40b908f7ff34150080d2884240f9007975f8e10313aa71750594e0e40736b5060091e80b40b9bf0208eb'
        '03ffff54adffff17'
    )),
)
