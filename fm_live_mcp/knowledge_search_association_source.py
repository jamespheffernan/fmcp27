"""Private passive port of ordinary PERSON association-ID predicate CF3C90.

This is one dependency of Player Search's preliminary admission. A true result
alone is neither search visibility, nationality eligibility nor field knowledge.
No names, ratings, native status byte or row payload leave the result boundary.
"""
from copy import deepcopy
import hashlib
import struct

from . import knowledge_transfer_predicate as transfer, world

ROW_LIMIT = 100_000
NATIVE_GUARDS = (
    (0xcf3c90, 296, 'bb3592f09a6e10b02bca1266f5b2d1025c8c9d0e20209da8249908d00712c30f'),
    (0xd5c590, 24, '64f0e51c5322911f9bb568e5681d0ac789c6472bb83c205e3a0bea5c86c9502a'),
)


def verify_native(read, base):
    for rva, size, digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base+rva,size)).hexdigest() != digest:
            raise ValueError('Search association native source changed')


def _predicate(reader, person, target):
    primary, common, _, _ = reader.person(person)
    table = reader.ptr(person)
    reader.route(table,0x2f0,0xcf3c90)
    reader.adjustment(table,0x300,-0x110)
    nation = reader.ptr(common+0x38)
    if nation:
        identity = reader.entity(nation,('nation',))[1]
        if identity[1] == target:
            reader.route(table,0x558,0xd5c590)
            reader.adjustment(table,0x568,primary-person)
            code = struct.unpack('<b',reader.read(primary+0x266,1))[0]
            return code in (0,0x50,0x54,0x55)
    holder = reader.ptr(common+0x48)
    if not holder:
        return False
    start, count = reader.bounds(holder,16,ROW_LIMIT)
    for index in range(count):
        row = start+index*16
        if reader.u8(row+0xb) != 9:
            continue
        if reader.u8(row+0xd) not in (0x50,0x54,0x55):
            continue
        kind = reader.u8(row+0xa)
        if kind not in (2,8):
            continue
        owner = reader.ptr(row)
        if not owner:
            continue
        if kind == 2:
            # This checked family is a native owner with nation at+170.
            # Other kind2 owner families remain explicitly unsupported here.
            reader.entity(owner,('national_team_container',))
            nation = reader.ptr(owner+0x170)
            if not nation:
                continue
        else:
            nation = owner
        if reader.entity(nation,('nation',))[1][1] == target:
            return True
    return False


def evaluate(read, base, person, identity, association_native_id, *, check_current):
    """Rebind bytes and return only a private native predicate Boolean.

    The caller must fingerprint the plugin and establish the selected search
    process/save context. Its mandatory callback returns that checked identity;
    the callback and consumed bytes are checked again before a result leaves.
    """
    transfer._identity(identity)
    if (type(association_native_id) is not int
            or not 0 <= association_native_id < 1 << 32):
        raise ValueError('Expected an exact unsigned native association ID')
    if not callable(check_current):
        raise ValueError('A process/save/build lifetime callback is required')
    before = deepcopy(check_current())
    if type(before) is not tuple or not before:
        raise ValueError('A checked nonempty lifetime identity is required')
    read = world.ReadSet(read)
    transfer.verify_native(read,base)
    verify_native(read,base)
    reader = transfer._Reader(read,base)
    if reader.person(person)[3] != identity:
        raise ValueError('Search association canonical subject identity changed')
    result = _predicate(reader,person,association_native_id)
    read.verify()
    if check_current() != before:
        raise ValueError('Search association process/save/build lifetime changed')
    read.verify()
    return {'scope':'private_native_association_id_predicate_only',
            'native_result':result,'search_admission_evaluated':False,
            'field_visibility_evaluated':False,'non_atomic':True}
