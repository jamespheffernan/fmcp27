"""Private byte-bound PERSON_UI Passing18 state, never a public permission.

The native score/attribute getter and debug payload never leave this module's
private collector. It computes only H23871f0's state/score under the selected
HUMAN and ordinary subject scope. Endpoint/rendering/population policy and
Manager mode remain separate. No native call or cache write is performed.
"""
from .knowledge_native_scope import collection_stream
from bisect import bisect_left, bisect_right
import hashlib
import struct

from . import (assessment_people, bridge as bridge_module,
               knowledge_context_score as core,
               knowledge_context_score_source as inherited,
               knowledge_passing_range as ranges)


class StateSource(inherited._Source):
    def thresholds(self, category):
        return ranges.passing_thresholds(category)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for rva, size, digest in NATIVE_GUARDS:
            if hashlib.sha256(self.read(self.base+rva, size)).hexdigest() != digest:
                raise core.SourceUnavailable('Passing state native source changed')
        table=self.ptr(self.owner.person.address)
        self.route(table, 0x6f0, 0x1300074)
        if struct.unpack('<q',self.read(table-0x700,8))[0] != -0x548:
            raise core.SourceUnavailable('State owner HUMAN6f0 displacement changed')
        self.assessment_record = None
        self.assessment_selected = False

    def ordinary_primary(self):
        table=self.ptr(self.subject.person.address)
        self.route(table,0x668,0xd5c5fc)
        if struct.unpack('<q',self.read(table-0x678,8))[0] != self.subject.primary-self.subject.person.address:
            raise core.SourceUnavailable('State subject668 displacement changed')
        return self.subject.primary

    def normal_club(self, team):
        return self.entity(self.ptr(team.address+0x30),'club') if team and team.kind=='team' else None

    def owner_eligible_club(self):
        return self.normal_club(self.eligible_team(self.owner))

    def own_candidate(self):
        owner=self.owner_eligible_club()
        if owner is None:
            return None
        current=self.team(self.reader.current_team(self.subject.person.address))
        if self.normal_club(current)!=owner:
            if self.normal_club(self.stored_team(self.subject))!=self.owner_eligible_club():
                return None
        chosen=self.selected_contract(self.subject,self.owner_eligible_club())
        if chosen and chosen.category!=5 and chosen.kind=='trial':
            return None
        return self.owner_eligible_club()

    def association_projection(self, team):
        if team is None:
            return None
        team=self.team(team.address)
        owner_kind,offset=('club',0xd8) if team.kind=='team' else ('national_team_container',0x170)
        owner=self.entity(self.ptr(team.address+0x30),owner_kind)
        nation=self.entity(self.ptr(owner.address+offset),'nation') if owner else None
        if nation is None:
            return None
        return self.entity(self.ptr(nation.address+(0x118 if self.u8(owner.address+0xb9) else 0x110)),
                           'national_team_container')

    def apply_auxiliary(self, candidate):
        national=self.national()
        if national:
            flag=self.u8(national.address+0xe2)
            if flag!=1:
                national=None
            else:
                day,year=struct.unpack('<HH',self.read(national.address+0xb8,4))
                if self.date_passed((year,day&511)):
                    national=None  # Native clears E2; owned replay changes no source byte.
        # HUMAN COMMON438 is called even when X is locally null. The inherited
        # method binds the exact mode993/secondary-contract path without calls.
        secondary=self.secondary_team()
        if secondary and national:
            a,b=self.association_projection(secondary),self.association_projection(national)
            return b if a==b else candidate
        return candidate

    def generic_eligible_club(self, person):
        if not person:
            return None
        primary,delta,public,uid,secondary=assessment_people._person(self.read,self.base,self.people,person)
        if public['record_kind']=='virtual':
            raise core.SourceUnavailable('Unproved compact assessment assessor')
        table=self.ptr(person)
        self.route(table,0x3c8,0xcb3724)
        if struct.unpack('<q',self.read(table-0x3d8,8))[0]!=-0x110:
            raise core.SourceUnavailable('Assessor main-contract displacement changed')
        contract=self.contract(self.ptr(person-0x98))
        if contract is None:
            return None
        if self.ptr(contract.address+8)!=person:
            raise core.SourceUnavailable('Assessor contract owner changed')
        if not self.accepted(contract):
            return None
        return self.normal_club(self.team(self.ptr(contract.address+0x10)))

    def selected_assessment(self):
        # Owned sorted range. Null record slots are outside the checked subset:
        # native equal_range dereferences visited slots before later null skips.
        start,count=self.reader.bounds(self.human+0x110,8,inherited.LIMIT)
        rows=[];keys=[]
        for i in range(count):
            row=self.ptr(start+8*i)
            if not row:
                raise core.SourceUnavailable('Null sorted assessment slot')
            person=self.ptr(row)
            key=struct.unpack('<i',self.read(person+8,4))[0] if person else 0
            rows.append(row);keys.append(key)
        if keys!=sorted(keys):
            raise core.SourceUnavailable('Assessment subject-index range is not sorted')
        target=self.subject.person.identity[0]
        for row in rows[bisect_left(keys,target):bisect_right(keys,target)]:
            person=self.reader.resolve_placeholder(self.ptr(row))
            if not person:
                continue
            if person!=self.subject.person.address:
                raise core.SourceUnavailable('Selected assessment PERSON differs from subject')
            assessor=self.ptr(row+8)
            if not assessor:
                continue
            club=self.generic_eligible_club(assessor)
            if club is None:
                continue
            owner=self.generic_eligible_club(self.owner.person.address)
            if club==owner or self.reader.parent(club.address)==(owner.address if owner else 0):
                self.assessment_record=row;self.assessment_selected=True
                return row
        # The alternate selector uses raw UID and reverse physical order. It
        # does not resolve placeholders or require a nonnull assessor.
        start,count=self.reader.bounds(self.human+0x128,8,inherited.LIMIT)
        for i in range(count-1,-1,-1):
            row=self.ptr(start+8*i)
            if not row:
                continue
            person=self.ptr(row)
            if not person or self.u32(person+0xc)!=self.subject.person.identity[1]:
                continue
            if person!=self.subject.person.address:
                raise core.SourceUnavailable('Alternate assessment UID is ambiguous')
            self.assessment_record=row;self.assessment_selected=True
            return row
        self.assessment_selected=True
        return None

    def knowledge_node(self,cell,*,required=False):
        # Native2385b30 initializes a pool with stride12. Its plain nodes can
        # be four-byte aligned; their vector cells remain eight-byte aligned.
        row=int.from_bytes(self.read(cell,8),'little')
        if not row:
            if required:raise core.SourceUnavailable('Null visited reciprocal node')
            return 0
        if row<4096 or row%4 or row+12>=1<<64:
            raise core.SourceUnavailable('Invalid reciprocal knowledge node')
        return row

    def reciprocal_score(self):
        self.ordinary_primary()
        start,count=self.reader.bounds(self.subject.primary+0xc8,8,inherited.LIMIT)
        owner_uid=self.owner.person.identity[1]
        for i in range(count-1,-1,-1):
            row=self.knowledge_node(start+8*i,required=True)
            if self.u32(row+4)!=owner_uid:
                continue
            if self.u32(row)!=self.subject.person.identity[0]:
                raise core.SourceUnavailable('Reciprocal node subject ordinal changed')
            own_start,own_count=self.reader.bounds(self.fow_record,8,inherited.LIMIT)
            if not any(self.knowledge_node(own_start+8*j)==row for j in range(own_count)):
                raise core.SourceUnavailable('Reciprocal node not in selected FOW owner vector')
            return core._signed(self.u8(row+8),8)
        return 0

    def state(self):
        candidate=self.own_candidate()
        self.ordinary_primary()
        candidate=self.apply_auxiliary(candidate)
        if candidate:
            # H's exact own-context branch ignores K and supplied assessment.
            return 2,0,'own_context'
        self.route(self.ptr(self.subject.primary),0x518,0xd5c4bc)
        category=self.u8(self.subject.primary+0x268)
        low,high=self.thresholds(category)
        if not low or not high:
            return 0,0,'zero_threshold'
        stored=self.reciprocal_score()
        result=core.evaluate(self)
        if result.score is None:
            raise core.SourceUnavailable('Required contextual K unavailable: '+str(result.reason))
        score=core._signed(max(stored,result.score),8)
        assessment=self.selected_assessment()
        if assessment:
            score=max(score,core._signed(self.u8(assessment+0x3f),8))
        return (2 if score>=high else int(score>=low)),score,'threshold'


def collect(bridge,session_id,*,subject_person,subject_identity,coach_name=None,field=18):
    """Root/private use only. No getter, endpoint or public Manager mode."""
    if not isinstance(bridge,bridge_module.Bridge):
        raise ValueError('A genuine reader Bridge instance is required')
    with bridge.lock,collection_stream(bridge,session_id):
        source=StateSource(bridge,session_id,subject_person,subject_identity,coach_name,field)
        try:
            state,score,route=source.state();reason=None
        except (core.SourceUnavailable,ValueError) as error:
            state=score=route=None;reason=str(error)
        source.verify()
        return dict(scope='private_passing18_native_state_not_public_permission',native_state=state,
                    private_score=score,route=route,unavailable_reason=reason,
                    subject_identity=source.subject.person.identity,owner_identity=source.owner.person.identity,
                    current_date=source.save['current_date'],assessment_selected=source.assessment_selected,
                    native_assessment_selection=source.assessment_record,
                    assessment_freshness='not_evaluated_by_native_selectors',
                    attribute_getter_read=False,model_projection_delivered=False,non_atomic=True)


NATIVE_GUARDS = (
    (0x23871f0, 2744, '96ccf286063553b055db4d95e2cecb046e85cfb027c4676faba6489c8de77cec'),
    (0x12d9e40, 1424, 'f680bd4980af615585d22a4d661c2f6fce36eb437c3b17916be6efa8330c0b2c'),
    (0x12da3d0, 348, 'c120a9e26837f9ddea109c84f93a4caaebbbb28de0d50239ec86e4584cbf2aba'),
    (0x12d8b88, 1052, '922d3b04ad24078b32cfd3cb448e6a1ed7209c020ddf0d969d7f9089a060874a'),
    (0x14e98e4, 3940, 'd8ba68fb2e502cc925bf25786a7eb19bc9f84c1f7d43d0467beeb53bb6c032eb'),
    (0x5399419, 1, '6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d'),
    (0x539944a, 1, '62b67e1f685b7fef51102005dddd27774be3fee38c42965c53aab035d0b6b221'),
    (0x539947b, 1, '62b67e1f685b7fef51102005dddd27774be3fee38c42965c53aab035d0b6b221'),
    (0x53994ac, 1, '62b67e1f685b7fef51102005dddd27774be3fee38c42965c53aab035d0b6b221'),
    (0x53994dd, 1, '62b67e1f685b7fef51102005dddd27774be3fee38c42965c53aab035d0b6b221'),
    (0x539950e, 1, '62b67e1f685b7fef51102005dddd27774be3fee38c42965c53aab035d0b6b221'),
    (0x539953f, 1, '62b67e1f685b7fef51102005dddd27774be3fee38c42965c53aab035d0b6b221'),
    (0xd5c4bc, 8, '87c95004f83bcde8ac89e5691e743bac0d3e0aa4923aa7f39425750b11cd24b8'),
    (0x1300074, 20, '3f6f9d5a8b337d573adebd2a1339b59a12468aba23fb837448a097c1ff86c9fa'),
    (0x1635eb4, 192, '6dd37d677e80b3ebe934c14c75a685414376d4cf21278a8f12be1ab2017c870c'),
    (0x53934b0, 16, 'ede0dbaef839d05d5d93423da724ad9a31caa8e4ab6dd3dc6021e223596cfe18'),
    (0x2385b30, 40, 'e10b8762924ec4283e3a89cbf404e5ee75c2527fe01c67cdd438c9d7cd3d1025'),
)
