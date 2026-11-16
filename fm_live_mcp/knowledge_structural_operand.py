"""Collector-local exact transfer-offer+8 LSE operand closure; no game calls.

Package copy of `evidence/knowledge-player-field-lse-v2-20261109/structural_operand.py` (lane codex/continuous-knowledge-20261109, commit 268c3a2, SHA256 c80a8ba48aad25bddaa21a858271a65964edd3deeb27afb2f43161ded66143e8); the code is unchanged.


Hooks only an already reached, successful pinned transfer predicate dependency.
The approved value result is returned unchanged. Only typed, manager-owned
offers visited by a second execution of that same passive predicate can add an
exact four-byte structural read. No property permission or CPU write is granted.
"""
import hashlib

MAX_CELLS=256


def source_type(observed_type,transfer,offers,journal,receipts):
    class StructuralSource(observed_type):
        def _operand(self,name,*args):
            result=super()._operand(name,*args)
            if name!='transfer_predicate':return result
            person,club=args
            try:
                if person!=self.subject or club!=self.owner_club:
                    raise ValueError('Structural operand caller differs from bound subject/owner')
                before=self.lifetime()
                # The closure re-runs the predicate and adds receipts; it never changes the
                # returned value, so a journal that records inputs leaves its reads out of
                # the subject's inputs (they stay journalled and fenced).
                recording=getattr(journal,'inputs',None)
                if recording is not None:recording.suspend()
                try:
                    collect(self,person,club,result,transfer,offers,journal,receipts)
                finally:
                    if recording is not None:recording.resume()
                self.read.verify()
                if self.lifetime()!=before:
                    raise ValueError('Structural operand caller lifetime changed')
                self.read.verify();journal.healthy()
            except Exception as exc:
                # Extra structural verification cannot silently change an H
                # outcome into unavailable through the collector's ValueError
                # policy. Any extension fault rejects the complete packet.
                journal.poison(exc);raise
            return result
    return StructuralSource


def collect(source,person,club,expected,transfer,offers,journal,receipts):
    transfer.verify_native(source.read,source.base)
    prefix=transfer._Reader(source.read,source.base)
    if prefix.person(person.person.address)[3]!=person.person.identity or prefix.club(club.address)!=club.identity:
        raise ValueError('Structural operand canonical caller identity changed')
    common=prefix.person(person.person.address)[1]
    indices=prefix.ptr(common+0x68)
    visited={}
    manager=None;owned={};statuses={}
    def owned_offers():
        manager=offers._manager(source.read,source.base)
        if not manager or prefix.ptr(source.base+0x56a67f0)!=manager+0x18:
            raise ValueError('Structural operand BASE manager ownership changed')
        owned={}
        for slot,offer in enumerate(prefix.pointers(manager+0x20,transfer.VECTOR_LIMIT)):
            if offer:owned.setdefault(offer,[]).append(slot)
        return manager,owned,{offer+0x8d:offer for offer in owned}
    if indices:
        _,count=prefix.bounds(indices,4,transfer.VECTOR_LIMIT)
        if count:
            # The manager's offer vector does not depend on the subject: a bulk journal with a
            # call memo reads and indexes it once (the result is only read, never changed).
            memo=getattr(journal,'memo',None)
            manager,owned,statuses=memo(('structural','owned_offers'),owned_offers) if memo else owned_offers()

    class Reader(transfer._Reader):
        def u8(self,address):
            offer=statuses.get(address)
            if offer is not None and offer not in visited:
                table=self.ptr(offer)
                if table-source.base not in offers.CLASSES:
                    # Keep the unclassified family unproved; no raw refill.
                    visited[offer]=dict(offer=hex(offer),state='unsupported_offer_family_no_operand_read')
                else:
                    kind=offers._type(source.read,source.base,table)
                    key=(person.person.address,club.address,offer)
                    if key not in receipts and len(receipts)>=MAX_CELLS:
                        error=ValueError('Structural LSE operand cell budget exceeded')
                        journal.poison(error);raise error
                    raw=source.read(offer+8,4)
                    receipt=dict(state='typed_manager_owned_visited_offer_LSE_operand',
                        subject_identity=person.person.identity,owner_identity=club.identity,
                        subject_person=person.person.address,owner_club=club.address,
                        manager=manager,manager_first_vector_slots=owned[offer],offer=offer,
                        runtime_kind=kind,offer_vtable=table,address=hex(offer+8),size=4,
                        raw_sha256=hashlib.sha256(raw).hexdigest(),
                        original_increment_rva='0xcbba84',original_decrement_rva='0xcbbe6c',
                        scope='exact_owned_structural_LSE_cell_not_attribute_permission',
                        native_or_game_write_performed=False)
                    previous=receipts.get(key)
                    if previous is not None and previous!=receipt:
                        error=ValueError('Structural operand ownership or bytes changed')
                        journal.poison(error);raise error
                    receipts[key]=receipt;visited[offer]=receipt
            return super().u8(address)

    reader=Reader(source.read,source.base)
    actual,route,ordinal=reader.predicate(person.person.address,club.address)
    if type(expected)is not bool or actual!=expected:
        raise ValueError('Structural closure changed the pinned predicate result')
    return dict(route=route,offer_index_ordinal=ordinal,visited=visited)
