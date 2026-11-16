"""Typed removal requests, distinct from executed player participation.

The source vector also stores pending changes. INJURE_PLAYER has an empty
native apply body; only the separate removal classes request status changes.
Neither a request clock nor current kind eligibility proves past execution.
"""
import struct
from . import native_player_changes as changes

direction, people = changes.direction, changes.people
NATIVE_SPANS = (
    (0x4A796D0, bytes.fromhex("08008012080800b9286100d008e11591080000f980c6072f000c00bdc0035fd6")),
    (0x4A7A414, bytes.fromhex("08008012080800b91f30003901340039e8ff9f52081c0079286100b008611b91080000f9c0035fd6")),
    (0x4A7A45C, bytes.fromhex("08388039a80c088b096e8a522900a072186969f8083c8039080f088b15a140f9c8c48352")),
    (0x4A7A494, bytes.fromhex("19344039")),
    (0x4A7A4B4, bytes.fromhex("68008052a90080523f1b00712501881a684a409102c13c91e6030091e00315aae10316aae30317aae40314aa0700805215a4eb97")),
    (0x4A7A814, bytes.fromhex("08008012080800b9286100b008211e91080000f960c6072f000c00bdc0035fd6")),
    (0x4A7A85C, bytes.fromhex("08388039a80c088b096e8a522900a072086969f8093c8039080d098b17a140f918e68552")),
    (0x4A7A89C, bytes.fromhex("6202188be6030091e00317aae10316aae30315aae40314aa45008052070080521fa3eb97")),
    (0x4A7979C, bytes.fromhex("c0035fd6")),
    (0x4A64F9C, bytes.fromhex("3f38007161000054080080520c00001428008052091a8652096869782a0082524b6484520b01a0726b25c11a3f4c0071eb838b1a3f010a6a08118b1a00010012c0035fd6")),
)
TYPES = {
    # type codes 6 (the change factory 0x4A8B248) and 18 (the request creator 0x2F28D20, mov w19,#0x12);
    # the factory's code 1 builds another class
    0x569F6D8: ('PLAYER_TAKEN_OFF', b'N7simatch16PLAYER_TAKEN_OFFE', 0x4A7A43C, (6, 18)),
    0x569F788: ('SEND_OFF_PLAYER', b'N7simatch15SEND_OFF_PLAYERE', 0x4A7A834, (12,)),
    0x569F578: ('INJURE_PLAYER', b'N7simatch13INJURE_PLAYERE', 0x4A7979C, (11,)),
}


def current_kind_allowed(side_flags, kind):
    """Mirror complete native 4A64F9C; this is eligibility, not execution."""
    kind &= 0xFFFFFFFF
    if kind == 14:
        return False
    if side_flags & 0x1001:
        return True
    return kind <= 19 and bool((0x82322 >> kind) & 1)


def verify_native(read, base):
    changes.verify_native(read, base)
    for at, expected in NATIVE_SPANS:
        if direction._read(read, base + at, len(expected)) != expected:
            raise ValueError('Native removal request source changed')
    for table, (_, _, method, _) in TYPES.items():
        if direction._q(read, base + table + 0x20) != base + method:
            raise ValueError('Native removal apply route changed')


def capture(read, base, bound):
    verify_native(read, base)
    source = changes.capture(read, base, bound)
    result = {'state': 'available_native_removal_requests',
        'official_match_unique_id': bound['official_match_unique_id'], 'rows': [],
        'history_complete': None, 'pending_vs_executed_verified': False,
        'fixed_frame_participation_verified': False, '_changes': source, '_objects': []}
    if source['rows'] is None:
        return result | {'state': 'unavailable_native_removal_request_budget', 'rows': None}
    objects = source['_source'][2] if len(source['_source']) > 1 else ()
    rows, consumed = [], []
    for index, obj in enumerate(objects):
        row = {'native_change_index': index, 'kind': None, 'side_index': None,
            'native_change_tick': None, 'player_original_slot': None,
            'native_apply_requested_status': None, 'native_apply_body_noop': None}
        if obj is None:
            rows.append(row | {'state': 'unavailable_null_change_object'})
            continue
        address, header = obj
        kind = TYPES.get(struct.unpack_from('<Q', header)[0] - base)
        if kind is None:
            rows.append(row | {'state': 'outside_typed_removal_request_scope'})
            continue
        name, typename, _, codes = kind
        people._type(read, base, address, struct.unpack_from('<Q', header)[0] - base, typename)
        raw = direction._read(read, address, 16)
        if raw[13] not in codes:
            raise ValueError('Typed removal request kind disagrees with native constructor')
        consumed.append((address, raw))
        tick = struct.unpack_from('<i', raw, 8)[0]
        side, slot = struct.unpack_from('<2b', raw, 14)
        if side not in (0, 1) or not 0 <= slot < 26:
            rows.append(row | {'state': 'unavailable_typed_removal_side_or_original_slot', 'kind': name})
            continue
        requested = (5 if raw[13] == 6 else 3) if name == 'PLAYER_TAKEN_OFF' else 2 if name == 'SEND_OFF_PLAYER' else None
        rows.append(row | {'state': 'typed_removal_request_with_native_clock' if tick >= 0 else 'typed_removal_request_clock_unavailable',
            'kind': name, 'side_index': side, 'player_original_slot': slot,
            'native_change_tick': tick if tick >= 0 else None,
            'native_apply_requested_status': requested, 'native_apply_body_noop': name == 'INJURE_PLAYER'})
    return result | {'rows': rows, '_objects': consumed}


def verify_capture(read, base, bound, captured):
    if capture(read, base, bound) != captured:
        raise ValueError('Native removal request storage changed')
    return captured | {'native_removal_source_physically_reselected': True}


def project(verified):
    if verified.get('native_removal_source_physically_reselected') is not True:
        raise ValueError('Final native removal request verification required')
    return {k: v for k, v in verified.items() if not k.startswith('_')}
