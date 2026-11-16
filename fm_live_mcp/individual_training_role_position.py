"""Stored training role/position sources inside a caller-owned canonical scope.

The caller binds regular ACTUAL_PLAYER/PERSON, selected HUMAN/TEAM membership,
runtime Mach-O/build/save lifetime and references, verifies native source once,
then physically fences every consumed byte after all publication callbacks.
Plain OOP children use stride12 and need not have8-byte-aligned addresses.
"""
import hashlib
import struct

from . import individual_training_ip_role as role,individual_training_position as position,players

SCOPE=('Stored native individual-training role/position selections only. '
       'Native masks/codes retain their training namespace; human-readable labels '
       'are unproved. No applied/effective training, attendance, workload, medical '
       'clearance, admission, assignment dates or whole training-screen population.')
COMBINED_SCOPE=('Stored additional focus and club intensity plus requested native '
                'role/position selections. Role/position labels remain unproved for '
                'this training namespace. No actual applied/effective training, '
                'attendance, workload, recommendation, development outcome, medical '
                'clearance, assignment dates or complete training-screen population.')
NATIVE_GUARDS=(
    (0x17F5E00,332,'47cb87fb6bb558abef80d8f84f776737b59a76715a570ab19147735b665559df'),
)


def verify_native(read,base):
    role.verify_native(read,base)
    position.verify_native(read,base)
    for rva,n,digest in NATIVE_GUARDS:
        if hashlib.sha256(_read(read,base+rva,n)).hexdigest()!=digest:
            raise ValueError('Individual-training OOP pool source changed')


def _read(read,at,n):
    if type(at)is not int or at<4096 or type(n)is not int or not 1<=n<=16384 or at+n>=1<<64:
        raise ValueError('Invalid bounded training role/position source')
    raw=read(at,n)
    if type(raw)is not bytes or len(raw)!=n:
        raise ValueError('Incomplete individual-training role/position source')
    return raw


def _pointer(read,at):return int.from_bytes(_read(read,at,8),'little')


def unavailable(reason):
    return dict(state='unavailable',reason=reason,ip_training=None,oop_training=None,
        label_state='not_proved_for_training_namespace',planned_training_evaluated=False,
        applied_training_evaluated=False,effective_training_evaluated=False,scope=SCOPE)


def inspect(read,base,primary):
    """Read only after native verification and caller's canonical focus binding."""
    if (type(base)is not int or base<4096 or base%4096 or type(primary)is not int
            or primary<4096 or primary%8 or _pointer(read,primary)!=base+players.RVA[0]):
        raise ValueError('Individual-training regular PLAYER source changed')
    child=_pointer(read,primary+0x1A0)
    if not child:
        ip=dict(source_state='missing_child',state='unavailable_missing_child',
            stored_occurrence_count=None,selected_stored_slot=None,native_role_mask=None,
            native_role_code=None,native_position_code=None,native_position_mask=None,
            native_position_state='source_unavailable',role_name=None,position_name=None)
    else:
        if child%8:raise ValueError('Unaligned individual-training IP vector header')
        start,end,capacity=struct.unpack('<QQQ',_read(read,child,24))
        if (start,end,capacity)==(0,0,0):entries=()
        else:
            if (start<4096 or any(value%8 for value in (start,end,capacity))
                    or not start<=end<=capacity or (end-start)%24 or (capacity-start)%24
                    or capacity-start>role.OCCURRENCE_LIMIT*role.OCCURRENCE_BYTES):
                raise ValueError('Malformed or oversized individual-training IP vector')
            entries=tuple(_read(read,at,24)for at in range(start,end,24))
        selected=role.decode(entries);pos=position.decode(entries)
        slot=selected['selected_stored_slot']
        family=None if slot is None else selected['occurrences'][slot]['native_signed_role_family']
        ip=dict(source_state=selected['source_state'],state=selected['state'],
            stored_occurrence_count=selected['stored_occurrence_count'],selected_stored_slot=slot,
            native_role_mask=selected['native_ip_role_mask'],native_role_code=family,
            native_position_code=pos['native_code'],native_position_mask=pos['native_mask'],
            native_position_state=pos['state'],role_name=None,position_name=None)
    child=_pointer(read,primary+0x198)
    if child:
        raw=_read(read,child,12)
        raw_code=struct.unpack_from('<H',raw,6)[0];native=struct.unpack_from('<h',raw,6)[0]
        oop=dict(source_state='present_child',raw_code=raw_code,native_code=native,
            native_code_source='stored_signed_halfword',role_name=None)
    else:
        oop=dict(source_state='missing_child',raw_code=None,native_code=50,
            native_code_source='native_missing_child_fallback',role_name=None)
    return dict(state='available',reason=None,ip_training=ip,oop_training=oop,
        label_state='not_proved_for_training_namespace',planned_training_evaluated=False,
        applied_training_evaluated=False,effective_training_evaluated=False,scope=SCOPE)
