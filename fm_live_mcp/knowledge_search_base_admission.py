"""Private ordinary kind1 base-admission branch of native208B238.

This reuses exact club/FOW/context predicates. It returns one private Boolean,
never a field permission or completed manager-known population. The selected
list's stored show-all bit is an input, not a product default.
"""
import hashlib

from . import assessment_people, world
from . import knowledge_club_admission_source as club_source
from . import knowledge_search_context_source as context_source
from . import knowledge_search_fow_source as fow_source


NATIVE_GUARDS = (
    (0x208b238, 6244, '7b5e788d25b6fa257059289a9dd32e8edc6898f6703bff6ab749e2b860b94977'),
    (0x14d8bfc,384,'5c956e7330e31def1c20d94fabb4b8c273e00c8ca0912c3f875cf6b4bfe0f1c5'),
    (0x14d68d8,528,'d098735ffd83cfa4794a0d9637682c8052ec1233b56ba1ea1d6a8241a869d29b'),
    (0x14d9f00,700,'f06b4a130cb169e73f060ccb774ee3589de90ece79ccc309aaf755a32ffdc5d7'),
    (0x163429c,212,'18e7d7ce7bfb0534ecc2d2963aeb542d3cd446ed245c52b47d07c3701ea84f3e'),
    (0xca4a50,8,'d3c844a0173107453aa9896cdb7276470625501e7ff067cd764c7a160ece5ca3'),
    (0xca4e8c,20,'c3719ee73c7556f633194a0644fe570347a4a5f1c09cedde41b5f62e753e4fbf'),
)


def verify_native(read, base):
    for rva, size, digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base+rva, size)).hexdigest() != digest:
            raise ValueError('Player Search complete refresh source changed')


class Frame:
    """A checked selected HUMAN/kind1 frame shared by an ordinal source page."""

    def __init__(self, read, base, human, *, show_all):
        if type(show_all) is not bool:
            raise ValueError('Expected native kind1 show-all Boolean')
        verify_native(read, base)
        self.read, self.base, self.human, self.show_all = read, base, human, show_all
        self.club_reader = club_source.Reader(read, base)
        primary, offset, public, uid, secondary = assessment_people._person(
            read, base, self.club_reader.table('people'), human+0x548)
        if primary != human or offset != 0x548 or public['record_kind'] != 'human_manager':
            raise ValueError('Base admission selected HUMAN binding changed')
        self.owner_identity = (public['native_identity']['database_index'], uid, secondary)
        self.club, self.context = 0, 0
        if show_all:
            return
        club_source.verify_native(read, base)
        context_source.verify_native(read, base)
        self.context_reader = context_source.Reader(read, base)
        self.context = self.context_reader.selection(human, self.owner_identity)
        if self.context:
            fow_source.verify_native(read, base)
            self.fow_reader = fow_source.Reader(read, base)
            self.fow_reader.owner(human, self.owner_identity)
        # Native208B314..208B368 chooses the primary accepted contract's
        # ordinary TEAM owner. It does not substitute the selected UI TEAM.
        reader = self.club_reader
        table = reader.ptr(human+0x548)
        reader.route(table, 0x3c8, 0xcb3724)
        reader.adjustment(table, 0x3d8, -0x110)
        main = reader.ptr(human+0x438+0x78)
        if main:
            reader.contract(main, human+0x548)
            accepted = reader.u8(main+0x26) > 1
            if not accepted:
                kind = reader.ptr(main)
                full = kind == base+world.TYPES['full_contract'][0]
                reader.route(kind, 0x70, 0x129a4b8 if full else 0xd88c6c)
                accepted = full and reader.u8(main+0xc2) >= 2
            if accepted:
                team = reader.team(reader.ptr(main+0x10))
                if team and reader.u8(team+0x2f) == 0:
                    self.club = reader.ptr(team+0x30)
                    if self.club:
                        reader.club(self.club)

    def _same_club(self, person):
        reader = self.club_reader
        primary, common, _, _ = reader.person(person)
        main = reader.ptr(common+0x78)
        category = reader.contract(main, person)
        if category and category[0] == 0:
            team = reader.ptr(main+0x18)
        else:
            stored = reader.team(reader.ptr(primary+0x128))
            holder = reader.ptr(common+0x80) if stored and not main else 0
            if stored and not main and (not holder or not any(
                    reader.ptr(holder+off) for off in (0, 8, 0x10, 0x18))):
                team = stored
            elif person-primary == 0x388 or not main:
                team = 0  # Actual's literal-null PERSON3f8.
            else:
                reader.route(reader.ptr(main), 0x58, 0xd8c3c8)
                team = reader.ptr(main+0x10) if reader.u8(main+0x26) >= 2 else 0
        if not team:
            return False
        reader.team(team)
        return reader.u8(team+0x2f) == 0 and reader.ptr(team+0x30) == self.club

    def admitted(self, person):
        primary,_,_,_=self.club_reader.person(person)
        value=self._predicate(person)
        if value:
            # Base materialization stores PERSON unchanged, then obtains6d0
            # solely for a descriptor. These ordinary getters cannot generate
            # a compact profile: actual is null, combined is an existing base.
            table=self.club_reader.ptr(person)
            combined=person-primary==0x480
            self.club_reader.route(table,0x6d0,0xca4e8c if combined else 0xca4a50)
            if combined:
                self.club_reader.adjustment(table,0x6e0,-0x208)
        return value

    def _predicate(self, person):
        if self.show_all:
            return True
        if self.club:
            if self._same_club(person):
                return True
            if self.club_reader.admission(self.club, person, 0):
                return True
            return bool(self.context and self.fow_reader.admission(person, self.context, self.human))
        # Native208BD14 allows an unaffiliated subject when context is null;
        # after a failed nonnull CLUB predicate, null context instead rejects.
        return not self.context or self.fow_reader.admission(person, self.context, self.human)
