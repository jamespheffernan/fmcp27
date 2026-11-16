"""Passive selection of already resident native player motion bytes.

This is a source operand collector, not an active-player or historical-identity
projector. A native ring selection has no independent historical tick tag; its
bytes must be reconciled to the exact frame before any historical position claim.
"""
import math
import struct

from . import frame_attack_direction as direction

NATIVE_GETTER = (0x47D46C4, bytes.fromhex("ffc303d1f44f0da9fd7b0ea9fd830391088041b91f01046bcd010054887ca40a080500120814088b090104910041c03d2191c03c6190803c6000803d250200b5fd7b4ea9f44f4da9ffc30391c0035fd6098841b9e901f8373f01046b6b050054137840f9930700b48800084b087d40936816088b0001c03d0191c03ceeffff17088841b9080af837a80000b9edffff17095440b93f01046b4afeff54000443ade08704ad000444ade08705ad000441ade08702ad000442ade08703ad000440ade08701ade80302aae2c30091e10302a9e90303aae30304aae80b00f9e40308aaf40305aae50309aab7efff97b4faffb4f30314aae08b40b9a006f836e10342a9e20b40f931000014e10302a9e50f00f9f30302aaf40303aa99ffff97e58741a9e20313aae80300aae01740f9098881b90a8081b929010acb0815098b0001c03d0191c03c8192803c8002803d9f1200b9bbffff17e40f00b9e30300f9e10302a9e21701a9f7f8759713c0925201c092527108ee97e80300aa094000913f011ff83f811fb83f0100f93f21003929810091738200f141ffff54f30308aae00308aa01c0925244680c94e10342a9137800f9088041b9e21741a9e30340f9e40f40b9aaffff17f30305aa7c850a94600200b99cffff17"))
MAX_BUFFER_ROWS = 1200  # Native fixed allocation0x9600, stride32; conservative bound.


def verify_native(read, base):
    at, expected = NATIVE_GETTER
    if direction._read(read, base+at, len(expected)) != expected:
        raise ValueError('Native cached player motion getter changed')


def capture(read, base, player_address, *, fixed_tick):
    """Mirror only the getter's two read-only paths, never a constructor."""
    verify_native(read, base)
    direction._pointer(player_address)
    if type(fixed_tick) is not int or not 0 <= fixed_tick <= 0x7FFFFFFF:
        raise ValueError('Unsupported native motion tick')
    motion = player_address+0x80
    start_raw = direction._read(read, motion+0x180, 4)
    start = struct.unpack('<i', start_raw)[0]
    common = {'requested_tick':fixed_tick, 'start_tick':start,
              'native_xyz':None, 'pose_rawhex':None, '_selection':(start_raw,),
              'historical_tick_attested':False, 'actor_on_pitch':None}
    if start > fixed_tick:
        address = motion+0x100+32*(fixed_tick&3)
        state = 'resident_native_ring_bytes_require_exact_frame_reconciliation'
        selection = (start_raw,address)
    else:
        end_raw = direction._read(read, motion+0x188, 4)
        end = struct.unpack('<i', end_raw)[0]
        common.update(end_tick=end, _selection=(start_raw,end_raw))
        # Negative end has a secondary cached/generated path. Deliberately
        # refuse it here until its separate+54 validity source is proved.
        if end < 0 or end < fixed_tick:
            return common | {'state':'unavailable_requires_generation_or_secondary_clock'}
        offset = fixed_tick-start
        if not 0 <= offset < MAX_BUFFER_ROWS:
            return common | {'state':'unavailable_bounded_motion_buffer_range'}
        pointer_raw = direction._read(read, motion+0xF0, 8)
        pointer = struct.unpack('<Q', pointer_raw)[0]
        common['_selection'] = (start_raw,end_raw,pointer_raw)
        if not pointer:
            return common | {'state':'unavailable_requires_buffer_allocation'}
        direction._pointer(pointer)
        address = pointer+32*offset
        selection = (start_raw,end_raw,pointer_raw,address)
        state = 'resident_native_buffer_bytes_require_exact_frame_reconciliation'
    raw = direction._read(read,address,25)
    xyz = struct.unpack_from('<3f',raw)
    if not all(math.isfinite(v) for v in xyz):
        return common | {'state':'unavailable_nonfinite_native_motion_pose',
                         '_selection':(*selection,raw)}
    return common | {'state':state, 'native_xyz':list(xyz), 'pose_rawhex':raw.hex(),
                     '_selection':(*selection,raw)}


def verify_capture(read, base, player_address, captured):
    again = capture(read,base,player_address,fixed_tick=captured['requested_tick'])
    if again != captured:
        raise ValueError('Consumed native motion selection changed')
    return captured | {'native_motion_bytes_physically_reselected':True}
