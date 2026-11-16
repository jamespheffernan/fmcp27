"""Private ordinary-player FOW admission leaf1F9AA0C, without native calls.

The native result is one Player Search admission branch, not a complete search
population or permission to expose a field. Preserve native bypass results as
predicate results only. Owner/context identity is always established by caller.
"""
from copy import deepcopy
import hashlib
import struct

from . import assessment_people,prepared_tactics_source,world
from . import knowledge_search_preliminary_source as preliminary
from . import knowledge_transfer_predicate as transfer

NATIVE_GUARDS = (
    (0x1f9aa0c,288,'67217fdc97e2716a8d44c3dba1555fe0d129f616ab3e18322d1d21e6f1b946f6'),
    (0x238816c,280,'3c02431b3935795acec9b729ff0baee70d4e11eebb7b9b6389a964fb6aeddbcf'),
    (0x1300060,20,'c62b747862d1cf16fb01c5408524041f7d9c9e27edb97fc458d3338ac9ee7b8d'),
    (0xd5c5fc,20,'62e50aff752959cc367e0ab72a4ea1286e80d2e70d5a58cc8796f16a3c89568d'),
    (0x2385b30,40,'e10b8762924ec4283e3a89cbf404e5ee75c2527fe01c67cdd438c9d7cd3d1025'),
)


def verify_native(read,base):
    preliminary.verify_native(read,base)
    for rva,n,digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base+rva,n)).hexdigest()!=digest:
            raise ValueError('Player Search FOW source changed')
    service=world.pointer(read,base+0x56d2d08)
    prepared_tactics_source._typed(read,base,service,0x55def88,b'18GAME_ACTUAL_PLAYER')
    if int.from_bytes(read(base+0x55def88+0x348,8),'little')!=base+0x1f9aa0c:
        raise ValueError('Player Search FOW virtual dispatch changed')


class Reader(preliminary.Reader):
    def owner(self,human,identity):
        primary,offset,public,uid,secondary=assessment_people._person(
            self.read,self.base,self.table('people'),human+0x548)
        if (primary!=human or offset!=0x548 or public['record_kind']!='human_manager'
                or (public['native_identity']['database_index'],uid,secondary)!=identity):
            raise ValueError('Selected search HUMAN canonical identity changed')
        table=self.ptr(human+0x548)
        self.route(table,0x678,0x1300060);self.adjustment(table,0x688,-0x548)

    def reciprocal(self,person,record):
        primary,_,_,_=self.person(person);table=self.ptr(person)
        self.route(table,0x668,0xd5c5fc);self.adjustment(table,0x678,primary-person)
        owner=self.ptr(record+0x18)
        owner_uid=int.from_bytes(self.read(owner+0xc,4),'little') if owner else 0xffffffff
        start,count=self.bounds(primary+0xc8,8,transfer.VECTOR_LIMIT)
        for index in range(count-1,-1,-1):
            # FOW node pool stride is12. Nodes are four-byte aligned; their
            # owning vector cells and PLAYER objects remain eight-byte aligned.
            node=int.from_bytes(self.read(start+index*8,8),'little')
            if node<4096 or node%4 or node+12>=1<<64:
                raise ValueError('Invalid native reciprocal knowledge node')
            if int.from_bytes(self.read(node+4,4),'little')==owner_uid:
                return struct.unpack('<b',self.read(node+8,1))[0]
        return 0

    def admission(self,person,context,human):
        if not self.preliminary(person,context):return False
        target=self.ptr(context+0x170)
        if not target:return False
        subject=self.subject_nation(person)
        if not subject:return False
        key=self.normalized(subject)
        if key==self.normalized(target) and (subject==target or key!=0x23716):
            return True
        primary,_,_,_=self.person(person)
        if struct.unpack('<h',self.read(primary+0x25a,2))[0]>0x1481:return True
        if self.u8(self.base+0x56d4980)!=1:return True
        manager=self.ptr(self.base+0x56a8430)
        if self.u8(human+0x3fc)&16:return True
        ordinal=self.i32(human+0x3e4)
        if ordinal<0:return True
        if not manager:raise transfer.SourceUnavailable('Missing native FOW manager')
        prepared_tactics_source._typed(self.read,self.base,manager,0x55f5d80,b'18FOG_OF_WAR_MANAGER')
        start,count=self.bounds(manager+0x18,8,4096)
        if ordinal>=count:return True
        record=self.ptr(start+ordinal*8)
        if not record:return True
        if self.ptr(record+0x18)!=human+0x548:
            raise ValueError('Selected FOW record belongs to another HUMAN')
        return self.reciprocal(person,record)>0


def evaluate(read,base,person,identity,context,context_identity,human,owner_identity,*,check_current):
    """Read a current caller-bound subject/context/HUMAN, returning no score."""
    transfer._identity(identity);transfer._identity(owner_identity)
    if context:transfer._identity(context_identity)
    elif context_identity is not None:raise ValueError('Null search context must have null identity')
    if not callable(check_current):raise ValueError('A checked search lifetime callback is required')
    before=deepcopy(check_current())
    if type(before) is not tuple or not before:raise ValueError('A checked search lifetime identity is required')
    read=world.ReadSet(read);transfer.verify_native(read,base);verify_native(read,base)
    reader=Reader(read,base)
    if reader.person(person)[3]!=identity:raise ValueError('Search FOW subject identity changed')
    if context and reader.entity(context,('national_team_container',))[1]!=context_identity:
        raise ValueError('Search FOW context identity changed')
    reader.owner(human,owner_identity)
    value=reader.admission(person,context,human)
    read.verify()
    if check_current()!=before:raise ValueError('Player Search FOW lifetime changed')
    read.verify()
    return {'scope':'private_native_fow_search_admission_branch_only','native_result':value,
            'complete_search_population_evaluated':False,'field_visibility_evaluated':False,'non_atomic':True}
