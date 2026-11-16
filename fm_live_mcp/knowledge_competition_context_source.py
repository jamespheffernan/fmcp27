"""Private F0F038 competition-context predicate used by club scoring.

Only the native Boolean leaves. Opaque COMP+B0 projections are traversed at
the exact guarded offsets; no English meaning or field permission is inferred.
"""
from copy import deepcopy
import hashlib
import struct

from . import knowledge_transfer_predicate as transfer,world

NATIVE_GUARDS = (
    (0xf0f038,228,'708c7de12ef3e33ce8ba3820a659cfe1fe1b9e84cc57f7b174ad513224af1482'),
    (0x3ab45dc,32,'957b1ff4944a3b7cecee8e780c3b7ca7ef094a73eb8b8e1adb31c7ce988dd2b0'),
)


def verify_native(read,base):
    for rva,n,digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base+rva,n)).hexdigest()!=digest:
            raise ValueError('Competition-context native source changed')


def _classified(value):
    return value in (8,23) or 105<=value<123


def _direct(reader,projection):
    if reader.u8(projection+0x4c0)==1 or reader.u8(projection+0x4d)&32:return True
    settings=reader.ptr(projection+0x388)
    return bool(settings and reader.u8(settings+0x23c)==1)


def predicate(reader,definition):
    reader.entity(definition,('competition',))
    projection=reader.ptr(definition+0xb0)
    if not projection:return False
    active=int.from_bytes(reader.read(reader.base+0x56d3518,4),'little')
    group=reader.ptr(projection+0x138)
    key=int.from_bytes(reader.read(group+0xc,4),'little') if group else 0xffffffff
    if active==key:return _direct(reader,projection)
    flags=int.from_bytes(reader.read(projection+0x4c,4),'little')
    if flags&64 or reader.u8(projection+0x4c0)==3:return False
    if flags&0x20000 or reader.ptr(projection+0x510):return False
    settings=reader.ptr(projection+0x388)
    code=reader.u8(settings+0x23c) if settings else None
    if code==3 or struct.unpack('<h',reader.read(projection+0x3b6,2))[0]==-3:return False
    if code==1 and _classified(reader.u8(projection+0x3be)):return False
    return _direct(reader,projection)


def evaluate(read,base,definition,identity,*,check_current):
    transfer._identity(identity)
    if not callable(check_current):raise ValueError('A checked competition-context lifetime callback is required')
    before=deepcopy(check_current())
    if type(before) is not tuple or not before:raise ValueError('A checked competition-context identity is required')
    read=world.ReadSet(read);verify_native(read,base);reader=transfer._Reader(read,base)
    if reader.entity(definition,('competition',))[1]!=identity:raise ValueError('Competition-context identity changed')
    result=predicate(reader,definition)
    read.verify()
    if check_current()!=before:raise ValueError('Competition-context lifetime changed')
    read.verify()
    return {'scope':'private_native_competition_context_predicate_only','native_result':result,
            'club_score_evaluated':False,'field_visibility_evaluated':False,'non_atomic':True}
