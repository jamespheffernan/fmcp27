"""Private passive Player Search context selector at208B3A8..208B400.

This is the context passed to the preliminary/FOW search branch. It follows
the selected HUMAN's secondary DATA contract, not their primary club nation.
Null is a native result; it is never replaced with a convenient association.
No search refresh, native calls, profile generation or field permission.
"""
from copy import deepcopy
import hashlib

from . import assessment_people,prepared_tactics_source,world
from . import knowledge_transfer_predicate as transfer

NATIVE_GUARDS = (
    (0x208b3a8,88,'aa285ac48e55756defcb77b45223cabdc25d7bd2370594a46e1a2e48d1d1c4fa'),
    (0xc8cf20,64,'207979a4160eb708962c03bc99109154b678bbdc473a42eda955a3f5b70861b3'),
    (0x12ffe58,68,'886c19702f1de55ea43b2858e54d30ca614142ec863c5fc31319727f3486c69c'),
)


def verify_native(read,base):
    for rva,n,digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base+rva,n)).hexdigest()!=digest:
            raise ValueError('Player Search context native source changed')


class Reader(transfer._Reader):
    def owner(self,human,identity):
        primary,offset,public,uid,secondary=assessment_people._person(
            self.read,self.base,self.table('people'),human+0x548)
        if (primary!=human or offset!=0x548 or public['record_kind']!='human_manager'
                or (public['native_identity']['database_index'],uid,secondary)!=identity):
            raise ValueError('Selected search context HUMAN identity changed')
        person_table=self.ptr(human+0x548)
        self.route(person_table,0x408,0xc8cf20)
        self.adjustment(person_table,0x418,-0x548)
        self.adjustment(self.ptr(human),0x18,0x438)
        data=human+0x438
        prepared_tactics_source._typed(self.read,self.base,data,0x55acb30,
                                      world.TYPES['manager'][1],-0x438)
        self.route(self.ptr(data),0x438,0x12ffe58)
        self.adjustment(self.ptr(data),0x450,-0x438)
        return data

    def selection(self,human,identity):
        data=self.owner(human,identity)
        if self.u8(self.base+0x56d4993)!=1:return 0
        # This opaque holder is reached only by the guarded DATA getter.
        # Its stored contract must independently belong to this HUMAN PERSON.
        holder=self.ptr(data+0x80)
        if not holder:return 0
        contract=self.ptr(holder+0x10)
        if not contract:return 0
        self.contract(contract,human+0x548)
        team=self.ptr(contract+0x10)
        if not team:return 0
        self.team(team)
        owner=self.ptr(team+0x30)
        if not owner:return 0
        nation=self.ptr(owner+(0xd8 if self.u8(team+0x2f)==0 else 0x170))
        if not nation:return 0
        self.entity(nation,('nation',))
        projection=self.ptr(nation+(0x118 if self.u8(owner+0xb9)!=0 else 0x110))
        if projection:self.entity(projection,('national_team_container',))
        return projection


def evaluate(read,base,human,owner_identity,*,check_current):
    """Return an internal context binding; caller owns the selected HUMAN."""
    transfer._identity(owner_identity)
    if not callable(check_current):raise ValueError('A checked search lifetime callback is required')
    before=deepcopy(check_current())
    if type(before) is not tuple or not before:raise ValueError('A checked search lifetime identity is required')
    read=world.ReadSet(read);verify_native(read,base)
    reader=Reader(read,base)
    context=reader.selection(human,owner_identity)
    identity=reader.entity(context,('national_team_container',))[1] if context else None
    read.verify()
    if check_current()!=before:raise ValueError('Player Search context lifetime changed')
    read.verify()
    return {'scope':'private_native_player_search_context_only','context':context,
            'context_identity':identity,'complete_search_population_evaluated':False,
            'field_visibility_evaluated':False,'non_atomic':True}
