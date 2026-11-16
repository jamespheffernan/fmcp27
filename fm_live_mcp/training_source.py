"""Existing managed-team training assignments from the checked loaded source.

No fallback creates or evaluates training. The caller supplies a save-bound
ReadSet and verifies it before publication. Returned wrapper pointers are private
inputs for training_calendar, never public references. Budgets below are reader
limits, not native cardinality rules.
"""
import struct

from . import players, prepared_tactics_source

MANAGER_ROOT = 0x56A5740
MANAGER_VTABLE = 0x55F9778
ASSIGNMENT_MODE = 0x56D4987
OWNER_LIMIT = 256
TREE_NODE_LIMIT = 256
TREE_DEPTH_LIMIT = 64
WEEK_LIMIT = 4096


def _address(value, size=0):
    if (type(value) is not int or value < 4096 or value % 8
            or value + size >= 1 << 64):
        raise ValueError('Invalid training source address')
    return value


def _read(read, address, size):
    raw = read(address, size)
    if len(raw) != size:
        raise ValueError('Incomplete training source read')
    return raw


def verify_native(read, base):
    """Pin ownership, direct lookup, wrapper keys and signed team type semantics."""
    _address(base, max(rva + len(raw) for rva, raw in NATIVE_SPANS))
    for rva, expected in NATIVE_SPANS:
        if _read(read, base+rva, len(expected)) != expected:
            raise ValueError(f'Training native source changed at RVA {rva:#x}')


def _vector(read, address, limit):
    start, end, capacity = struct.unpack('<QQQ', _read(read, address, 24))
    if (start, end, capacity) == (0, 0, 0):
        return ()
    _address(start)
    if (any(value % 8 for value in (end, capacity))
            or not start <= end <= capacity or capacity >= 1 << 64):
        raise ValueError('Invalid training vector bounds')
    count = (end-start)//8
    if count > limit or capacity-start > limit*8:
        raise ValueError('Training vector exceeds implementation budget')
    values = struct.unpack(f'<{count}Q', _read(read, start, count*8)) if count else ()
    for value in values:
        # The selected native owner/week loops dereference every entry.
        _address(value)
    return values


def _team_node(read, record, wanted):
    """Validate the complete pointer-key tree and retain exact TEAM membership."""
    begin, root, count = struct.unpack('<QQQ', _read(read, record+0x48, 24))
    sentinel = record+0x50
    if not root:
        if count or begin != sentinel:
            raise ValueError('Invalid empty training team tree')
        return None
    _address(begin)
    _address(root)
    if not count or count > TREE_NODE_LIMIT or begin == sentinel:
        raise ValueError('Training team tree size exceeds implementation budget')
    stack = [(root, sentinel, 0, 1 << 64, 0)]
    visited = set()
    selected, minimum_key, minimum_node = None, 1 << 64, None
    while stack:
        node, parent, lower, upper, depth = stack.pop()
        _address(node, 0x28)
        if node == sentinel or node in visited or len(visited) >= count:
            raise ValueError('Training team tree cycle or count mismatch')
        if depth >= TREE_DEPTH_LIMIT:
            raise ValueError('Training team tree exceeds implementation depth budget')
        visited.add(node)
        raw = _read(read, node, 0x28)
        left, right, backlink = struct.unpack_from('<QQQ', raw)
        key = struct.unpack_from('<Q', raw, 0x20)[0]
        _address(key)
        if backlink != parent or not lower < key < upper:
            raise ValueError('Training team tree ordering or parent changed')
        if key < minimum_key:
            minimum_key, minimum_node = key, node
        if key == wanted:
            selected = node
        if right:
            stack.append((right, node, key, upper, depth+1))
        if left:
            stack.append((left, node, lower, key, depth+1))
    if len(visited) != count or begin != minimum_node:
        raise ValueError('Training team tree count or begin changed')
    return selected


def inspect(read, base, coach):
    """Return (public canonical team, unavailable reason, private ordered weeks).

    Match the first native owner-vector entry with the checked HUMAN PERSON and
    exact TEAM tree key. Broader club/alternate fallbacks are unsupported. Empty
    resident week vectors remain available; missing dates are calendar states.
    Wrapper date upper bits do not participate in native comparison. Duplicate
    keys and native vector order are retained; year and day low nine bits are keys.
    """
    verify_native(read, base)

    def checked(address, size):
        return _read(read, address, size)

    team, human = prepared_tactics_source._team_and_human(checked, base, coach)
    if _read(read, base+ASSIGNMENT_MODE, 1) != b'\x01':
        return team, 'unsupported_training_assignment_mode', None
    manager = players.u64(_read(read, base+MANAGER_ROOT, 8))
    if not manager:
        return team, 'training_manager_missing', None
    _address(manager, 0x50)
    prepared_tactics_source._typed(checked, base, manager, MANAGER_VTABLE,
                                  b'16TRAINING_MANAGER')
    wanted = coach['team_address']
    club = players.u64(_read(read, wanted+0x30, 8))
    person = human+0x548
    owner_found = False
    for record in _vector(read, manager+0x38, OWNER_LIMIT):
        _address(record, 0xA8)
        if players.u64(_read(read, record+0x90, 8)) != person:
            continue
        owner_found = True
        node = _team_node(read, record, wanted)
        if node is None:
            continue
        if players.u64(_read(read, record+0x98, 8)) != club:
            raise ValueError('Training owner club association changed')
        weeks = []
        for wrapper in _vector(read, node+0x48, WEEK_LIMIT):
            _address(wrapper, 0x48)
            day, year = struct.unpack('<HH', _read(read, wrapper+0xC, 4))
            weeks.append((year, day & 0x1FF, wrapper))
        return team, None, tuple(weeks)
    reason = ('direct_team_entry_missing_native_fallback_unsupported' if owner_found
              else 'owner_entry_missing')
    return team, reason, None


# Accepted batches 15/16, ARM64. No game function is invoked by these guards.
NATIVE_SPANS = (
    (0x1300058, bytes.fromhex(
        '20008052c0035fd6'
    )),
    (0x1300074, bytes.fromhex(
        '080040f908011cd1080140f90000088bc0035fd6'
    )),
    (0x179d558, bytes.fromhex(
        '94a2c039de99b19400a00091b4031db8a0831cf8a8e300d1'
    )),
    (0x25659e4, bytes.fromhex(
        '088a01901ca143f9a1a302d1e0031caaba4a1d94'
    )),
    (0x2cabfb8, bytes.fromhex(
        '080080d2c11000b4a21000b4f44fbea9fd7b01a9fd43009109a843a9e80309aa3f010aeb200300542b201591e80309aa'
        '0c0140f98d4940f9bf010beba0000054082100911f010aeb41ffff54150000148d0d45f86dffffb4ee030caaaf1140f9'
        'ff0102ebce318d9aef279f1aad596ff86dffffb5df010ceb40feff54cc1140f99f0102ebe8fdff541f010aeba0000054'
        '080109eb64000054286968f8c80b00b5'
    )),
    (0x3a1d718, bytes.fromhex(
        '7f8608a9c8ffdf9288ede0f262a209a9'
    )),
    (0x3a1e668, bytes.fromhex(
        '804a40f9e10313aa31975b9760090034804e40f9e10313aa9f885b97e0080034'
    )),
    (0x2c95694, bytes.fromhex(
        '284b019008e11d9109a10091682600a9e80313aa1f8d01f8e80700f97f7e02a9755001f0'
    )),
    (0x2cb3390, bytes.fromhex(
        'ff8301d1fa6701a9f85f02a9f65703a9f44f04a9fd7b05a9fd430191a10100b4f40302aaf50301aaf30300aa085101b0'
        '081d66391f050071e1110054f60303aaa8be4039a8000034170080d204000014140080d20f020014b71a40f9b84240f9'
        '580800b4080340f908015ef8096b68f829d940f90003088b20013fd660070034080340f908015ef8096b68f8297943f9'
        '0003088b20013fd6800600b4e10300aae00313aae20315aae0e2ff97e01900b416190034080c45f8881900b4f60300aa'
        '091140f93f0115ebd632889ae9279f1a085969f868ffffb5df0200eb60180054c81240f91f0115eb0818005488064079'
        '89024079292100128b0240b91fb11d712009417ac0000054eb0b00b9e02300914100805261de5894eb0b40b9c8a644a9'
        '1f0109eb201600546a3d00126b7d1053000140f90c1c40790d184079ad010a4aad210012bf01007180014b7aa0140054'
        '190080d216008052082100911f0109eb81feff54a3000014770800b4e8a641a9'
    )),
    (0x2cb3760, bytes.fromhex(
        'e10315aae20314aa66b23594600000b4144000912b010014190080d216008052e00313aa'
    )),
    (0x3a1f1f0, bytes.fromhex(
        'ff0303d1f44f0aa9fd7b0ba9fdc30291a1031ef8e80300aa0a0d45f8aa0100b4e90308aa4b1140f97f0101eb29318a9a'
        'eb279f1a4a596bf86affffb53f0108eb800000542a1140f95f0101eb09070054132100d1'
    )),
    (0x3a1f31c, bytes.fromhex(
        '33a10091e00313aafd7b4ba9f44f4aa9ff030391c0035fd6'
    )),
    (0x3a20228, bytes.fromhex(
        '163d0012177d1053082442a91f0109eb60010054000140f90a1c40790b1840796b01164a6b2100127f0100714001577a'
        'a003005408210091f5ffff17e00314aa'
    )),
    (0x2cb93c4, bytes.fromhex(
        '69a243a9080109cb08fd43d3e82b00b9e00f40f9080040f9081940f9e1a300918200805200013fd6e80f40f9091140b9'
        '6902003400008052092100910a0080122901eab83f050071e1000054090140f9290540f9f30300aae00308aa20013fd6'
        'e00313aafd7b46a9f44f45a9f65744a9f85f43a9ffc30191c0035fd675d243a9bf0214eb40010054a00240f9e1630091'
        '6f943594a0fa0736b5220091e80f40f9091140b9e9feff34e3ffff17'
    )),
)
