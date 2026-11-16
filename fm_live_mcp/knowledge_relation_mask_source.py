"""Private passive relation-mask subset for the typed Passing collector.

Only reached existing-data negative paths are reproduced. A cold or unproved
selection remains unavailable, never an inferred native null. No live native
function, materialization, attribute getter or game write is used here.
"""
from .knowledge_native_scope import collection_stream
import hashlib
import struct

from . import database, prepared_tactics_source, bridge as bridge_module, knowledge_context_score as core, knowledge_passing_view as view


class RelationSource(view.ProjectionSource):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for rva,size,digest in NATIVE_GUARDS:
            if hashlib.sha256(self.read(self.base+rva,size)).hexdigest()!=digest:
                raise core.SourceUnavailable('Relation-mask native source changed')

    def _selected_parent(self,club):
        return self.entity(self.reader.parent(club.address),'club')

    def _special_club(self,club):
        nation=self.entity(self.ptr(club.address+0xd8),'nation')
        if nation and self.u32(nation.address+0xc) in (0x186,0x16c):
            raise core.SourceUnavailable('Unproved e02f00 special-country club resolution')
        return None

    def _relation_rows(self,club):
        # Plain relation rows are owned by this checked CLUB vector. Endpoint
        # identities are only consumed where the original branch needs them.
        start,count=self.reader.bounds(club.address+0x118,8,4096)
        for i in range(count):
            row=self.ptr(start+8*i)
            if not row:
                raise core.SourceUnavailable('Null visited club relation row')
            yield row

    def _refuse_selection(self):
        raise core.SourceUnavailable('Reached unproved 17bb4c0 selection; absence is not native null')

    def _auxiliary_equal(self):
        secondary=self.secondary_team()
        if secondary is None:
            return False
        national=self.national()
        if national is None or self.u8(national.address+0xe2)!=1:
            return False
        year=self.u16(national.address+0xba);day=self.u16(national.address+0xb8)&511
        if self.date_passed((year,day)):
            return False  # Native E2 clear is reproduced only as a local decision.
        return self.association_projection(secondary)==self.association_projection(national)

    def _first_team_special(self,club):
        first=self.first_team(club)
        if first is None:
            return
        if self.u8(self.base+0x56d4953)!=1 or self.u8(self.base+0x56d4951) in (1,2):
            return
        selected=None
        if self.ptr(first.address+0x30):
            definition=self.entity(self.ptr(first.address+0x50),'competition')
            if definition and definition.identity[1]==40:
                selected=definition
        if selected is None:
            alternate=self.ptr(first.address+0x58)
            selected=self.entity(alternate or self.ptr(first.address+0x50),'competition')
        if selected is None or selected.identity[1]!=40:
            return
        raise core.SourceUnavailable('Unproved first-team special relation selection')

    def _parent_fanout(self,owner,subject):
        parent=self._selected_parent(owner)
        if parent is not None:
            raise core.SourceUnavailable('Unproved nonnull owner-parent relation composition')
        # With native local W21=1, the no-parent path skips the later both-null
        # parent comparison. It still calls the special-country helper first.
        if self._special_club(subject)==owner:
            self._refuse_selection()

    def _relation_fanout(self,owner,subject):
        if owner==subject:
            return
        for row in self._relation_rows(owner):
            if self.u8(row+0x30) in (17,24) or self.u8(row+0x15)&32:
                continue
            flags=self.u32(row+0x1c)
            if flags&(1<<30):
                continue
            first=self.ptr(row)
            if first!=subject.address and self.ptr(row+8)!=subject.address:
                continue
            selected=bool(flags&8 and first==owner.address)
            if not selected and flags&(1<<24):
                selected=first==owner.address or self.ptr(row+8)==owner.address
            if selected:
                self._refuse_selection()
            return  # First matching native row returns the current null slot.

    def _same_team_fanout(self):
        team=self.team(self.reader.current_team(self.subject.person.address))
        if team is None:
            return
        contract=self.main(self.owner)
        if contract:
            self.route(self.ptr(contract.address),0x58,0xd8c3c8)
            owner_team=self.team(self.ptr(contract.address+0x10))
        else:
            owner_team=None
        if team!=owner_team:
            return
        if self.current_club(self.subject)==self.owner_eligible_club():
            return
        raise core.SourceUnavailable('Unproved equal-team distinct-club relation service')

    def _subject_parent_fanout(self,owner):
        team=self.team(self.reader.current_team(self.subject.person.address))
        club=self.normal_club(team)
        if club is None or self._selected_parent(club)!=owner:
            return
        raise core.SourceUnavailable('Unproved subject-parent relation service')

    def resolve_team_handle(self,address):
        table=database.table(self.read,self.base,'teams')
        if table['count']==0:
            return None
        primary=core._signed(self.u32(address),32)
        if primary<1:
            return None
        root=table['root']
        if self.u8(root+0x64)&1:
            if self.u8(root+0xa8)==1:
                raise core.SourceUnavailable('Unproved lazy TEAM UID sort')
            start,count=self.reader.bounds(root+0x90,8,2000000)
        else:
            start,count=table['start'],table['count']
        low,high=0,count-1
        found=None
        while low<=high:
            middle=(low+high)//2
            row=self.ptr(start+8*middle)
            if not row:
                raise core.SourceUnavailable('Null visited TEAM UID search row')
            self.reader.entity(row,('team','national_team'))
            uid=core._signed(self.u32(row+0xc),32)
            if uid<primary:
                low=middle+1
            elif uid>primary:
                high=middle-1
            else:
                found=row
                break
        secondary=self.u32(address+4)
        fallback=None
        if found is not None:
            uid=self.u32(found+0xc);effective=self.u32(found+0x10) or uid
            if effective==secondary:
                return self.team(found)
            if secondary==0:
                return self.team(found)
        if core._signed(secondary,32)<1:
            return fallback
        # The exact alias helper returns the original primary from an empty
        # owned alias vector. A nonempty vector is not an absent remapping:
        # its secondary-only fallback and lazy sorting still require parity.
        begin,end=struct.unpack('<QQ',self.read(root+8,16))
        if begin==end:
            if begin and (begin<4096 or begin%4):
                raise core.SourceUnavailable('Invalid empty TEAM alias vector')
            return fallback
        raise core.SourceUnavailable('Unproved nonempty TEAM alias resolution')

    def _recent_nodes(self,club,team,expected_team):
        holder=self.ptr(club.address+0xb0)
        if not holder:
            raise core.SourceUnavailable('Missing owned CLUB node container')
        start,count=self.reader.bounds(holder,8,4096)
        for i in range(count-1,-1,-1):
            row=self.ptr(start+8*i)
            if not row:
                continue
            table=self.ptr(row)-self.base
            if table not in NODE_TYPES:
                raise core.SourceUnavailable('Unproved owned CLUB node family')
            name,target,kind=NODE_TYPES[table]
            prepared_tactics_source._typed(self.read,self.base,row,table,name,0)
            self.route(self.base+table,0x28,target)
            if kind!=31 or self.ptr(row+0x38)!=team.address:
                continue
            day,year=struct.unpack('<HH',self.read(row+0x50,4))
            if self.days_since_exceeds(year,day,20):
                return  # Native stops at this stale match, not an older row.
            resolved=self.resolve_team_handle(row+0x48)
            if resolved is None or resolved==expected_team:
                return row
        return None

    def _recent_fanout(self):
        stored=self.stored_team(self.subject)
        if stored is None:
            return
        # Reproduce17800dc's first ordinary owner-contract/first-TEAM candidate.
        club=self.owner_eligible_club()
        if club and self.first_team(club):
            owner=self.entity(self.ptr(stored.address+0x30),
                              'club' if stored.kind=='team' else 'national_team_container')
            if owner is not None:
                if owner.kind!='club':
                    raise core.SourceUnavailable('Unproved national recent-node source')
                if self._recent_nodes(owner,stored,self.first_team(club)) is not None:
                    self._refuse_selection()
        secondary=self.secondary_team()
        if secondary is not None:
            owner=self.entity(self.ptr(stored.address+0x30),
                              'club' if stored.kind=='team' else 'national_team_container')
            if owner is not None:
                if owner.kind!='club':
                    raise core.SourceUnavailable('Unproved national secondary recent-node source')
                if self._recent_nodes(owner,stored,secondary) is not None:
                    self._refuse_selection()

    def relation_mask(self):
        owner=self.current_club(self.owner);subject=self.current_club(self.subject)
        if not self.u8(self.owner.primary+0x422)&1:
            if self.u8(self.base+0x56d34e0)==1 and self.u8(self.base+0x56d498a)==1 and self.u8(self.base+0x56d498b)&1:
                return 0x5fe
        if owner is not None and subject==owner:
            return 0
        if self._auxiliary_equal():
            return 0x5fe
        if owner is None:
            return 0
        self._first_team_special(owner)
        if subject is not None:
            self._parent_fanout(owner,subject)
            self._relation_fanout(owner,subject)
        self._same_team_fanout()
        self._subject_parent_fanout(owner)
        self._recent_fanout()
        return 0


def collect(bridge,session_id,*,subject_person,subject_identity,coach_name=None,field=18):
    """Private permitted endpoint collector with passive relation composition."""
    if not isinstance(bridge,bridge_module.Bridge):
        raise ValueError('A genuine reader Bridge instance is required')
    with bridge.lock,collection_stream(bridge,session_id):
        source=RelationSource(bridge,session_id,subject_person,subject_identity,coach_name,field)
        try:
            value=source.permitted()
        except (core.SourceUnavailable,ValueError):
            value={'state':'unavailable','reason':'unavailable_source'}
        source.verify()
        return dict(scope='private_permitted_passing_view_not_public_mode',field='Passing',native_field_id=18,
                    observer_identity=source.owner.person.identity,subject_identity=source.subject.person.identity,
                    current_date=source.save['current_date'],value=value,non_atomic=True,
                    assessment_freshness='not_established_by_native_selectors')


NODE_TYPES = {89903960: (b'N2db17SCOUTED_TEAM_INFOE', 23507980, 31), 89929040: (b'N2db47TEAM_DIVISION_SQUAD_SELECTION_TOTAL_VALUES_INFOE', 25254908, 22), 89930000: (b'N2db22COMPETITION_BONUS_INFOE', 25180612, 4), 89930384: (b'N2db25NEXT_SALE_PERCENTAGE_INFOE', 25184932, 5), 89930576: (b'N2db21APPEARANCE_MONEY_INFOE', 25242948, 6), 89932944: (b'N2db41NUMBER_ESC_PLAYERS_SIGNED_PER_SEASON_INFOE', 25237740, 62), 89939520: (b'N2db16TESTIMONIAL_INFOE', 25251884, 38), 89939952: (b'N2db27EXTRA_TRANSFER_PAYMENT_INFOE', 25253292, 39), 89943384: (b'N2db29START_OF_SEASON_SETTINGS_INFOE', 25235380, 26)}

NATIVE_GUARDS = ((34530824, 1008, '838d53e5227bff6ff0a83e3d73ea3580c709406e0540078b126fd5f258785bd3'), (34533784, 592, '46189739c65562bd843ae831cf91f57d019682adf9a99953dc938cd631d17ac2'), (34534376, 236, 'af6f3d5d3017f723e377eb4d94cd6d878ed15667cfdffa9b2ce5281164e79c3f'), (34534612, 772, 'a42db1cf6ee47a40183d033f2aa7674a7192aeb877c9794b2a9e6b9068ad8c5b'), (34535384, 668, '54030019f59715c2f036d55f17efa8de7421bce60f69b0c27686e298b60c0558'), (34536052, 664, 'be9d79516c61edc28254e8bf5eceb952b34973f469ef646e46e476effd3e7a95'), (24641756, 232, '8c1d3b0a9211c22d0f0f34c7f85a50fff30c0b33abaf5691e00ce669c7c371e8'), (25014744, 460, '45cc93d9aee990e2d3bb6edb8e9d32a12d1a5dcd2be5cec957fa104f491013ee'), (14692096, 892, 'c1f776b1d5e02e58ee2609ce177e96a3389bd77306838251656d05f1c3e26ef9'), (23507980, 8, '53f821f22f9a22f7bab26eec7a1325e84eeefef3f5e417829fdd21ebaad490b8'), (25254908, 8, '504492943c53e7bc7f89b7f348e5073f373f0fb2c2951ebc218de73a6252114b'), (25180612, 8, '866b82fb6649dcf0f7873c61006d47004b1074ea9b382227c4ab724c93f547f7'), (25184932, 8, '94152e462f3e98d8d99662739e87c91ff06eb16d5afefc0047346c214bd99ac8'), (25242948, 8, '5df1989c16767cd1d335f12745774eb72525d351309884cd8e2ac543e19f2ed0'), (25237740, 8, '8be1c7e19e29b067777f37c2826eb1fa64a6353bc3a723e60b840e5b109059d0'), (25251884, 8, '9c3fc1d193fcefd506db31ba5751f2351dd5bfdb614defdbb5a2a8746dbc9c81'), (25253292, 8, '5bce6661aae95481eeacc589150c74fa186814d1cba6925ab2d3d5616a8b62af'), (25235380, 8, '7b5b9bb8689a4d3703729066f9c625d899a47e35c432b603c966cd0fa0a80905'), (17507112, 448, 'b0113a81e7e4e285a1a8bd49a0836ad1236bde0651c95e68fd860e167c024e64'), (18702564, 660, 'bed67cb0ef83d9ba321007b7c558e8503df826f2f6698b76a4b24e945f9f693c'))
