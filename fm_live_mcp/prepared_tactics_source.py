"""Build-pinned, direct-owned prepared tactics for a checked active HUMAN coach.

Call inside the caller's save-bound ReadSet. The caller verifies it before
publishing; this module never invokes native code or constructs missing state.
"""
import struct

from . import players, teams, world

MANAGER_ROOT = 0x56A8310
MANAGER_VTABLE = 0x55F83A8
PREPARED_VTABLE = 0x569FD80
PERSON_VTABLE = 0x55AD820
OWNER_LIMIT = 256
SLOT_LIMIT = 64
TREE_DEPTH_LIMIT = 64


def verify_native(read, base):
    for rva, expected in NATIVE_SPANS:
        if read(base+rva, len(expected)) != expected:
            raise ValueError(f'Prepared tactics native source changed at RVA {rva:#x}')


def _pointer(value, label):
    if type(value) is not int or value < 4096 or value % 8:
        raise ValueError(f'Invalid prepared tactics {label} pointer')
    return value


def _typed(read, base, address, rva, name, displacement=0):
    _pointer(address, 'typed object')
    if players.u64(read(address, 8)) != base+rva:
        raise ValueError('Prepared tactics native type changed')
    offset, info = struct.unpack('<qQ', read(base+rva-16, 16))
    if offset != displacement:
        raise ValueError('Prepared tactics RTTI displacement changed')
    _pointer(info, 'type information')
    text = players.u64(read(info+8, 8))
    if text < 4096 or read(text, len(name)+1) != name+b'\0':
        raise ValueError('Prepared tactics RTTI name changed')


def _vector(read, address, limit):
    """Retain nulls and duplicates; limits are reader budgets, not native rules."""
    start, end, capacity = struct.unpack('<QQQ', read(address, 24))
    if (start, end, capacity) == (0, 0, 0):
        return ()
    if (start < 4096 or any(value % 8 for value in (start, end, capacity))
            or not start <= end <= capacity):
        raise ValueError('Invalid prepared tactics vector bounds')
    count = (end-start)//8
    if count > limit or capacity-start > limit*8:
        raise ValueError('Prepared tactics vector exceeds implementation budget')
    values = struct.unpack(f'<{count}Q', read(start, count*8)) if count else ()
    for value in values:
        if value:
            _pointer(value, 'vector entry')
    return values


def _unavailable(team, reason):
    return ({'team':team, 'source_state':'unavailable', 'unavailable_reason':reason,
             'complete_stored_slots':False, 'slot_count':None, 'nonnull_slot_count':None,
             'null_slot_count':None, 'primary_trained_tactic':{
                 'state':'source_unavailable', 'native_index':None, 'slot_index':None,
                 'meaning':'primary_trained_tactic'}}, ())


def _team_and_human(read, base, coach):
    if not isinstance(coach, dict):
        raise ValueError('Invalid prepared tactics coach binding')
    team = _pointer(coach.get('team_address'), 'coach team')
    human = _pointer(coach.get('manager_address'), 'coach HUMAN owner')
    index = struct.unpack('<I', read(team+8, 4))[0]
    row, binding = teams.by_index(read, base, index)
    if binding['address'] != team or row['kind'] != 'team':
        raise ValueError('Prepared tactics canonical team membership changed')
    owner = row['owner']
    if owner is None or owner['kind'] != 'club':
        raise ValueError('Prepared tactics managed club ownership changed')
    club, _ = world.club(read, base, binding['owner_address'])
    if club != coach.get('club'):
        raise ValueError('Prepared tactics coach club association changed')
    world.typed(read, base, human, 'manager')
    table = base+world.TYPES['manager'][0]
    if struct.unpack('<q', read(table-0x20, 8))[0] != 0x548:
        raise ValueError('Prepared tactics HUMAN PERSON displacement changed')
    person = human+0x548
    _typed(read, base, person, PERSON_VTABLE, world.TYPES['manager'][1], -0x548)
    person_table = base+PERSON_VTABLE
    if (players.u64(read(person_table+0x1B0, 8)) != base+0x1300058
            or players.u64(read(person_table+0x6F0, 8)) != base+0x1300074
            or struct.unpack('<q', read(person_table-0x700, 8))[0] != -0x548):
        raise ValueError('Prepared tactics HUMAN cast route changed')
    if world.pointer(read, team+0x80) != human:
        raise ValueError('Prepared tactics team HUMAN backlink changed')
    contract = world.pointer(read, human+0x4B0)
    if (world.pointer(read, contract+8) != person
            or world.pointer(read, contract+0x10) != team
            or world.pointer(read, contract+0x18) != team):
        raise ValueError('Prepared tactics HUMAN contract association changed')
    return row, human


def _team_entry(read, container, team_index):
    begin, node, size = struct.unpack('<QQQ', read(container, 24))
    sentinel = container+8
    if not node:
        if size or begin != sentinel:
            raise ValueError('Invalid empty prepared tactics team tree')
        return None
    _pointer(begin, 'team tree begin')
    if not size or begin == sentinel:
        raise ValueError('Invalid prepared tactics tree size')
    candidate, visited = None, set()
    lower, upper = None, None
    for _ in range(TREE_DEPTH_LIMIT):
        if not node:
            break
        _pointer(node, 'team tree node')
        if node == sentinel or node in visited or len(visited) >= size:
            raise ValueError('Prepared tactics team tree cycle or size mismatch')
        visited.add(node)
        data = read(node, 0x24)
        left, right = struct.unpack_from('<QQ', data)
        key = struct.unpack_from('<i', data, 0x20)[0]
        if (lower is not None and key <= lower) or (upper is not None and key >= upper):
            raise ValueError('Prepared tactics team tree key ordering changed')
        for child in (left, right):
            if child:
                _pointer(child, 'team tree child')
                if child == sentinel or child in visited:
                    raise ValueError('Prepared tactics team tree cycle')
        if key < team_index:
            lower, node = key, right
        else:
            candidate = (key, node)
            upper, node = key, left
    else:
        if node:
            raise ValueError('Prepared tactics tree exceeds implementation depth budget')
    return candidate[1]+0x28 if candidate and candidate[0] == team_index else None


def inspect(read, base, coach):
    """Return address-free source metadata and private ordered creator addresses."""
    if type(base) is not int or base < 4096 or base % 8:
        raise ValueError('Invalid prepared tactics image base')
    verify_native(read, base)
    team, human = _team_and_human(read, base, coach)
    manager = players.u64(read(base+MANAGER_ROOT, 8))
    if not manager:
        return _unavailable(team, 'tactics_manager_missing')
    _typed(read, base, manager, MANAGER_VTABLE, b'15TACTICS_MANAGER')
    matches = []
    for container in _vector(read, manager+0x20, OWNER_LIMIT):
        if container and players.u64(read(container+0x98, 8)) == human:
            matches.append(container)
    if len(matches) > 1:
        raise ValueError('Prepared tactics owner container is ambiguous')
    if not matches:
        return _unavailable(team, 'owner_container_missing')
    payload = _team_entry(read, matches[0], team['database_index'])
    if payload is None:
        return _unavailable(team, 'team_entry_missing')
    _typed(read, base, payload+0xFF8, PREPARED_VTABLE,
           b'N7simatch30PREPARED_TACTICS_CREATOR_ARRAYE')
    creators = _vector(read, payload+0x1000, SLOT_LIMIT)
    selector = read(payload+0x1018, 1)[0]
    selected = None
    if selector > 2:
        state = 'selector_out_of_range'
    elif selector >= len(creators):
        state = 'selector_beyond_count'
    elif not creators[selector]:
        state = 'selected_slot_null'
    else:
        state, selected = 'selected', selector
    nonnull = sum(bool(pointer) for pointer in creators)
    return ({'team':team, 'source_state':'available', 'unavailable_reason':None,
             'complete_stored_slots':True, 'slot_count':len(creators),
             'nonnull_slot_count':nonnull, 'null_slot_count':len(creators)-nonnull,
             'primary_trained_tactic':{'state':state, 'native_index':selector,
                 'slot_index':selected, 'meaning':'primary_trained_tactic'}}, creators)


# Accepted08 owner/tree and09 owned-array/primary-trained semantics, ARM64.
NATIVE_SPANS = (
    (0x175DCE4, bytes.fromhex(
        'f44fbea9fd7b01a9fd430091134040f9130200b4680240f908015ef8696a68f829d940f96002088b20013fd620010034'
        '680240f908015ef8696a68f8217943f96002088bfd7b41a9f44fc2a820001fd6000080d2fd7b41a9f44fc2a8c0035fd6'
    )),
    (0x1300058, bytes.fromhex(
        '20008052c0035fd6'
    )),
    (0x1300074, bytes.fromhex(
        '080040f908011cd1080140f90000088bc0035fd6'
    )),
    (0x2B5709C, bytes.fromhex(
        '000a00b4f657bda9f44f01a9fd7b02a9fd830091f30300aa08a04039a8000034e00313aa121db097800000b50f000014'
        '604240f9a00100b4080040f908015ef8096868f8293d43f90000088b20013fd6c00000b4e00313aa051db097f40300aa'
        'e00100b534000014681a40f9080d40f9000140f9fe1cb097800500b4f40300aa080040f908015ef8096868f829d940f9'
        '0000088b20013fd680040036880240f908015ef8896a68f8297943f98002088b20013fd6000400b4f40300aa885a01b0'
        '158941f9e00315aae10314aa020080d2e30313aaceecff97e00200b5e00315aae10314aa1c140094a82642a9290108eb'
        '0002005429fd43933f0500f129859f9a000140f9800000b40a4c40f95f0114eb20010054000080d208210091290500f1'
        '01ffff540400001468be4039c8000034000080d2fd7b42a9f44f41a9f657c3a8c0035fd6681a40f948ffffb4098d4539'
        '09ff273709a951a93f010aeba0feff542b0080520c3e80520c02a072ed0309aaae0140f9cf0540f9ff0108ebe1000054'
        'cfc14039ff5100716f21cf1aef010c0ae499407ac1000054000080d2ad210091bf010aeb61feff54e3ffff17ca0140f9'
        '0afcffb4292100912a0080520b3e80520b02a0722c815ff88d0540f9bf0108ebe10000548dc14039bf5100714d21cd1a'
        'ad010b0aa499407a6100005429210091f5ffff17880140f9080d40f9000140f99b1cb09780f9ffb4f40300aa080040f9'
        '08015ef8096868f829d940f90000088b20013fd6c0f30737c2ffff17'
    )),
    (0x2B524A8, bytes.fromhex(
        'a10500b40a2042a908010aeb8005005408fd43931f0500f10b859f9a080080d2430300b4497968f8890200b42c4d40f9'
        '9f0101eb80040054ed0309aaae8d40f8ce0100b46c0840b9ef030daad02140b91f020c6bf0a79f1aefb18e9ace5970f8'
        '6effffb5ff010deb80000054ed2140b99f010d6b8a020054080500911f010beb21fdff5409000014497968f8890000b4'
        '2c4d40f99f0101eb60010054080500917f0108eb21ffff54090080d20800805237000014000080d2c0035fd6090080d2'
        '33000014430600b4eb0309aa6d8d46f8ed0500b46a0840b9ec030baaae1d40b9df010a6beea79f1a8cb18d9aad596ef8'
        '6dffffb59f010beba00400548b1d40b95f010b6b4b0400548b8140397f050071e10300540cac43a96b010ceba0030054'
        '0d0080d26bfd43937f0500f16e859f9a8b796df86b0200b46f4d40f9ff0101eb40030054ef030baaf08d40f8b00100b4'
        'f1030faa002240b91f000a6be0a79f1a31b2909a105a60f870ffffb53f020feb800000542f2240b95f010f6b6a010054'
        'ad050091bf010eeb41fdff540b0080d27f0100f120018b9a02f9ffb4e0f8ffb448000079c0035fd6e8030daaf9ffff17'
    )),
    (0x22C000C, bytes.fromhex(
        '61ca5af9f70300aae98e40f8c90100b4280840b9f90317aa2a2140b95f01086beaa79f1a39b3899a29596af869ffffb5'
        '3f0317eb80000054292340b91f01096baa030054'
    )),
    (0x22C0104, bytes.fromhex(
        '163c82526002168b21a300910a237f97'
    )),
    (0x4849E04, bytes.fromhex(
        'ff4301d1f85f01a9f65702a9f44f03a9fd7b04a9fd030191f30300aaf40300aa9ffe80a99f0a00f9d57200f0a84a45f9'
        '080100b5c873009008a1199108c1bf3828020036c873009008c11891a84a05f9a87200d008013691680200f9e00313aa'
        '2100805239000094e00313aafd7b44a9f44f43a9f65742a9f85f41a9ff430191c0035fd6'
    )),
    (0x288DBC, bytes.fromhex(
        '60e23f9181e23f913402179588326079'
    )),
    (0x484A198, bytes.fromhex(
        '088040391f0900f1e800005409a840a94a0109cb1f0d8aeb62000054207968f8c0035fd6000080d2c0035fd6'
    )),
    (0x48388E0, bytes.fromhex(
        'f30300aae86300b008011d91088400f8210080520e930094'
    )),
    (0x52EF84, bytes.fromhex(
        'c81250b9c90a50b90801094b19290353381f00131534003708048252da6a6838ff0a00712808005468008052a8831038'
        'a02303d1a1e303d13259fb94e8d08352e800a07209fd26115f03376b0101891aa8e303d1e00314aa'
    )),
)
