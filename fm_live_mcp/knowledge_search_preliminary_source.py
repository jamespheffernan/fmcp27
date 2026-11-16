"""Private typed port of Player Search's preliminary predicate14FB918.

This is the exact mode0 caller used by1F9AA0C. It does not implement that
caller's remaining FOW logic, club admission, retained union or field masking.
Only a native predicate Boolean leaves; internal codes are not English facts.
"""
from copy import deepcopy
import hashlib
import struct

from . import knowledge_search_association_source as association
from . import knowledge_transfer_predicate as transfer, world

ALIASES = {
    129504:390,129508:390,383:390,129523:390,
    129514:145174,363:145174,129517:145174,365:145174,765:145174,
    214394:145174,129520:145174,785:145174,793:145174,129526:145174,801:145174,
    111:110,124:110,767:764,1441:769,360:784,380:784,
}
NATIVE_GUARDS = (
    (0x14fb918,636,'4474bf1529cfc05a83cb6b9f57926c635f369dde691c184975c7e76d11ba41df'),
    (0x13b7cbc,332,'25c75af34c4a3905b6283bc6b02aa36165ee3baa19787dbf72ed2dfcfaa8f1eb'),
    (0x5396de0,160,'f29d6ae37ec9e925cff86c00e1ee0f701ccc9f39436021a8fda069aae9788db7'),
    (0xd30ff8,92,'1eba0add6bc0b2b93ffc950691c8ff179c0a78aca0b57054f51b00933a3c76bc'),
    (0xd2cde8,24,'7177e76fb7bbcb2a4621b90cae12612414c83fb50fa91003a16a9abf34e89dfc'),
    (0xca4674,24,'64164ca1568787b841601d69f3ceda841316cad0e4423bb8dd9b7768d7206047'),
)


def verify_native(read,base):
    association.verify_native(read,base)
    for rva,n,digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base+rva,n)).hexdigest()!=digest:
            raise ValueError('Preliminary search native source changed')


class Reader(transfer._Reader):
    def subject_nation(self,person):
        _,common,_,_=self.person(person)
        table=self.ptr(person)
        self.route(table,0x1d0,0xca4674)
        self.adjustment(table,0x1e0,-0x110)
        nation=self.ptr(common+0x38)
        if nation:self.entity(nation,('nation',))
        return nation

    def projection(self,person,nation):
        # PERSON bit12, not a guessed association/gender enum.
        mode=self.u8(self.base+0x56d4992)
        alternate=mode==1 and bool(int.from_bytes(self.read(person+0x18,8),'little')&0x1000)
        value=self.ptr(nation+(0x118 if alternate else 0x110))
        if not value:value=self.ptr(nation+0x110)
        if value:self.entity(value,('national_team_container',))
        return value

    def normalized(self,nation):
        if not nation:
            # Native13B7CBC dereferences its argument; a null lower input is
            # unavailable source, never a fabricated zero association key.
            raise transfer.SourceUnavailable('Null native association normalization input')
        identity=self.entity(nation,('nation',))[1]
        return ALIASES.get(identity[1],identity[1])

    def status(self,person):
        primary,_,_,_=self.person(person);table=self.ptr(person)
        self.route(table,0x558,0xd5c590)
        self.adjustment(table,0x568,primary-person)
        return struct.unpack('<b',self.read(primary+0x266,1))[0]

    def kind10(self,person):
        primary,common,_,_=self.person(person)
        self.route(self.ptr(primary),0x2c8,0xd30ff8)
        self.adjustment(self.ptr(primary),0x20,common-primary)
        holder=self.ptr(common+0x48)
        if not holder:return False
        start,count=self.bounds(holder,16,association.ROW_LIMIT)
        return any(self.u8(start+index*16+0xb)==10 for index in range(count))

    def preliminary(self,person,context):
        if not context:return False
        self.entity(context,('national_team_container',))
        primary,_,_,_=self.person(person)
        self.adjustment(self.ptr(primary),0x18,person-primary)
        nation=self.subject_nation(person)
        if not nation or not self.projection(person,nation):return False
        discriminator=self.u8(context+0xb9)
        subject_bit=(self.u8(person+0x19)&16)>>4
        if (discriminator^subject_bit)&1:return False
        if self.kind10(person):return False
        if self.projection(person,self.subject_nation(person))==context:
            return self.status(person) not in (0x52,0x56,0x58,0x5a,0x5b)
        context_nation=self.ptr(context+0x170)
        context_uid=self.entity(context_nation,('nation',))[1][1] if context_nation else None
        special=context_uid==0x23716
        left=self.normalized(context_nation)
        right=self.normalized(self.subject_nation(person))
        if special and left==right:return True
        primary,_,_,_=self.person(person)
        self.route(self.ptr(primary),0x338,0xd2cde8)
        if self.u8(primary+0x266) in (0x53,0x59):return False
        if left==right:
            subject=self.subject_nation(person)
            if self.entity(subject,('nation',))[1][1]==0x2fe and association._predicate(self,person,0x247):
                return False
        return association._predicate(self,person,self.entity(context,('national_team_container',))[1][1])


def evaluate(read,base,person,identity,context,context_identity,*,check_current):
    """Read one canonical subject/context; caller owns the search lifetime."""
    transfer._identity(identity)
    if context:transfer._identity(context_identity)
    elif context_identity is not None:raise ValueError('Null context must have null identity')
    if not callable(check_current):raise ValueError('A checked lifetime callback is required')
    before=deepcopy(check_current())
    if type(before) is not tuple or not before:raise ValueError('A checked lifetime identity is required')
    read=world.ReadSet(read);transfer.verify_native(read,base);verify_native(read,base)
    reader=Reader(read,base)
    if reader.person(person)[3]!=identity:raise ValueError('Preliminary subject identity changed')
    if context and reader.entity(context,('national_team_container',))[1]!=context_identity:
        raise ValueError('Preliminary context identity changed')
    value=reader.preliminary(person,context)
    read.verify()
    if check_current()!=before:raise ValueError('Preliminary search lifetime changed')
    read.verify()
    return {'scope':'private_native_preliminary_search_predicate_only','native_result':value,
            'complete_search_admission_evaluated':False,'field_visibility_evaluated':False,'non_atomic':True}
