"""Canonical HUMAN-owned ordinary player shortlist headers and selection.

The caller supplies and verifies a save-bound ReadSet. This module reads stored
personal lists only. It does not construct lists, resolve members, or substitute
club/system/transfer-target pools. Native addresses in the return tuple remain
private inputs to the member reader. Bounds are reader budgets, not game limits.
"""
import struct

from . import prepared_tactics_source

MODE_FLAG = 0x56D497D
LIST_LIMIT = 256
MEMBER_LIMIT = 100000
NAME_LIMIT = 2048


def _address(value, size=0, alignment=8):
    if (type(value) is not int or value < 4096 or value % alignment
            or value+size >= 1 << 64):
        raise ValueError('Invalid personal shortlist address')
    return value


def _read(read, address, size):
    raw = read(address, size)
    if len(raw) != size:
        raise ValueError('Incomplete personal shortlist read')
    return raw


def verify_native(read, base):
    """Pin personal ownership, kind, geometry, names, modes and selector rules."""
    _address(base, max(rva+len(raw) for rva, raw in NATIVE_SPANS))
    for rva, expected in NATIVE_SPANS:
        if _read(read, base+rva, len(expected)) != expected:
            raise ValueError(f'Personal shortlist native source changed at RVA {rva:#x}')


def _bounds(read, address, limit):
    start, end, capacity = struct.unpack('<QQQ', _read(read, address, 24))
    if (start, end, capacity) == (0, 0, 0):
        return 0, 0
    _address(start)
    if (any(value % 8 for value in (end, capacity))
            or not start <= end <= capacity):
        raise ValueError('Invalid personal shortlist vector bounds')
    count = (end-start)//8
    if count > limit or capacity-start > limit*8:
        raise ValueError('Personal shortlist vector exceeds implementation budget')
    return start, count


def _name(read, address):
    pointer = struct.unpack('<Q', _read(read, address+0xE8, 8))[0]
    if not pointer:
        return None
    # Native strings may be unaligned. No default/localized name is invented.
    _address(pointer, 5, alignment=1)
    length = struct.unpack('<I', _read(read, pointer, 4))[0]
    if length > NAME_LIMIT:
        raise ValueError('Personal shortlist name exceeds implementation budget')
    _address(pointer, length+5, alignment=1)
    raw = _read(read, pointer+4, length+1)
    if raw[-1]:
        raise ValueError('Personal shortlist name lacks native terminator')
    value = raw[:-1].decode('utf-8', errors='strict')
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('Invalid personal shortlist name control character')
    return value


def inspect(read, base, coach, list_index=None):
    """Return (public summary, selected private list pointer, slot count or None).

    Explicit list_index is a physical personal-vector ordinal, not an ordinal in
    the kind0 filtered headers. Default selection honors only the current
    personal container, including the proved negative signed-index clamp to zero.
    Null slots retain their native ordinals and cannot become empty member lists.
    """
    if list_index is not None and (type(list_index) is not int or list_index < 0):
        raise ValueError('Invalid personal shortlist index')
    verify_native(read, base)

    def checked(address, size):
        return _read(read, address, size)

    _, human = prepared_tactics_source._team_and_human(checked, base, coach)
    summary = {
        'lists': [], 'personal_list_count': None, 'selected_list_index': None,
        'selection_state': 'source_unavailable', 'source_state': 'unavailable',
        'unavailable_reason': None,
        'selection_source': ('current_personal_selection' if list_index is None
                             else 'explicit_native_index'),
        'current_container_code': None, 'stored_selected_index': None,
        'effective_personal_selected_index': None, 'selector_negative_clamped': None,
        'null_list_indices': None,
    }
    if not _read(read, base+MODE_FLAG, 1)[0] & 1:
        summary['unavailable_reason'] = 'unsupported_shortlist_mode'
        return summary, None, None
    if _read(read, human+0x422, 1) != b'\x01':
        summary['unavailable_reason'] = 'human_shortlists_unavailable'
        return summary, None, None
    start, count = _bounds(read, human+0x230, LIST_LIMIT)
    pointers = (struct.unpack(f'<{count}Q', _read(read, start, count*8))
                if count else ())
    ordinary = {}
    null_indices = []
    for index, address in enumerate(pointers):
        if not address:
            null_indices.append(index)
            continue
        _address(address, 0xF0)
        owner = struct.unpack('<Q', _read(read, address+0xD0, 8))[0]
        if owner != human:
            raise ValueError('Personal shortlist HUMAN ownership changed')
        kind = _read(read, address+0x4C, 1)[0]
        if kind == 0:
            _, entry_count = _bounds(read, address+0x80, MEMBER_LIMIT)
            header = {'list_index': index, 'stored_name': _name(read, address),
                      'entry_count': entry_count}
            summary['lists'].append(header)
            ordinary[index] = header
    current = _read(read, human+0x41F, 1)[0]
    stored = struct.unpack('<b', _read(read, human+0x42A, 1))[0]
    effective = max(stored, 0)
    summary.update(source_state='available', personal_list_count=count,
                   current_container_code=current, stored_selected_index=stored,
                   effective_personal_selected_index=effective,
                   selector_negative_clamped=stored < 0, null_list_indices=null_indices)
    if list_index is not None:
        if list_index >= count:
            raise IndexError('Personal shortlist index is outside the stored vector')
        if list_index not in ordinary:
            raise ValueError('Requested personal shortlist is not an ordinary player list')
        selected = list_index
    else:
        if current != 3:
            summary['selection_state'] = 'current_selection_not_personal'
            return summary, None, None
        if not count:
            summary['selection_state'] = 'personal_list_vector_empty'
            return summary, None, None
        if effective >= count:
            summary['selection_state'] = 'selected_index_beyond_count'
            return summary, None, None
        if not pointers[effective]:
            summary['selection_state'] = 'selected_list_null'
            return summary, None, None
        if effective not in ordinary:
            summary['selection_state'] = 'selected_list_not_ordinary'
            return summary, None, None
        selected = effective
    summary.update(selected_list_index=selected, selection_state='selected')
    return summary, pointers[selected], ordinary[selected]['entry_count']


# Accepted batches18/19. These are static instruction bytes, never game calls.
NATIVE_SPANS = (
    (0x1300058, bytes.fromhex(
        '20008052c0035fd6'
    )),
    (0x1300074, bytes.fromhex(
        '080040f908011cd1080140f90000088bc0035fd6'
    )),
    (0x12c14e0, bytes.fromhex(
        '3f040071600100543f080071c00000543f0c0071c1010054091c41f9081841f906000014093441f9083041f903000014'
        '092841f9082441f9290108cb5f0c89eb62000054007962f8c0035fd6000080d2c0035fd6280400511f090071a8010054'
        '081d4092890602d029e12191297968f88a0602d04a412291487968f8086868f8096869f8080109cb00fd4393c0035fd6'
        '000080d2c0035fd6'
    )),
    (0x12c1578, bytes.fromhex(
        '8102f837291c0012280589131f0900718d0300540a0d00515f090071630800541f190071c105005408b05039081d0013'
        '087da80a0b3441f90a3041f96b010acb1f0d8beb820c00544b00805240000014097c5039280500511f090071c8020054'
        '081d40928a0602d04a212191487968f808686838081d0013087da80a0f000014480500341f090071a102005408ac5039'
        '081d0013087da80a0b2841f90a2441f96b010acb1f0d8beb620900542b00805227000014080080d23f05007120020054'
        '3f090071800100543f0d0071410800540a1c41f9091841f90c000014020200b448bc403948fdff341f050071e0f9ff54'
        '390000140a3441f9093041f9030000140a2841f9092441f94a0109cb1f0d8aeb22060054287968f83000001428050051'
        '1f0500718805005408a85039081d0013087da80a0b1c41f90a1841f96b010acb1f0d8beb820400546b008052487968f8'
        '480400b40a3141395f01096be0030054687d7dd3082100d18a0602d04ae121914a6968f88c0602d08c412291886968f8'
        '086868f80a686af808010aeb600200540afd4393690200347f050071e00500547f090071010700540b0080d20c3041f9'
        '88796bf80d314139bf01096be0000054080080d26b0500915f010beb21ffff5402000014080080d2e00308aa'
    )),
    (0x12c1890, bytes.fromhex(
        '3f040071200100543f080071a00000543f0c0071e100005408a850390600001408b050390400001408ac503902000014'
        '08008052001d0013c0035fd6'
    )),
    (0x12c1960, bytes.fromhex(
        '7f060071600100547f0a0071c00000547f0e0071c1010054891e41f9881a41f906000014893641f9883241f903000014'
        '892a41f9882641f9290108cb7f0f89eb6200005418797bf802000014180080d2083341391f01196b21040054087740f9'
        '091100911f0100f18103899a080100b4090140b9a80240f93f05003140010054c80000b40a0140b90500001409008052'
        'a80240f988ffffb50a0080525f01096be1010054091100911f0100f18003899a2fb6e09440010035086f40f9080100b4'
        '090140f929015ef80801098b080940b9e90a40b91f01096be01500547b0700915f031bebe1f8ff54a10000141b0080d2'
    )),
    (0x12c1cfc, bytes.fromhex(
        '3f040071200100543f080071a00000543f0c0071c100005402a810390400001402b010390200001402ac1039017c1039'
    )),
    (0x12bbd70, bytes.fromhex(
        '741a41f9540200b4751e41f9e10314aabf0214eb00010054a08e5ff8600000b40865089460cae094bf0214eb61ffff54'
        '611a41f9741e01f9682241f9020101cb481f02b0004945f94768c294'
    )),
    (0x14d9bbc, bytes.fromhex(
        '686a40f9a80200b409a542f929e541f90021159120013fd6'
    )),
    (0x1926400, bytes.fromhex(
        '68ed01d008f5653988250036'
    )),
    (0x192650c, bytes.fromhex(
        'e02740f9088850391f05007181190054e1031caa0bbee697'
    )),
    (0x1926564, bytes.fromhex(
        'e82740f9091d41f9081941f93f0108eba0160054fb0700f91a0080d2ff1300f90c0080d2010080d21b797af868334139'
        '48020035682748a9290108ebe001005429fd43933f0500f129859f9a0a0140f9ea0000b44a0140f9aa0000b44a0940b9'
        '8b0b40b95f010b6b8001005408210091290500f1c1feff545a070091e82740f9091d41f9081941f9290108cb5f0f89eb'
        'c3fcff5435000014e81340f99f0108eb'
    )),
    (0x5393848, bytes.fromhex(
        '2b040000000000002c040000000000002a04000000000000'
    )),
    (0x5393878, bytes.fromhex(
        '480200000000000060020000000000003002000000000000500200000000000068020000000000003802000000000000'
    )),
)
