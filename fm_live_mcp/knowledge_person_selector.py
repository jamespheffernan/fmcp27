"""Private Passing18 with assessor0/report0/mode1 and typed selector6f.

This fixed caller is not a rendered UI/report-selection policy.
"""
from .knowledge_native_scope import collection_stream
from bisect import bisect_left,bisect_right
import hashlib
import struct
from . import knowledge_retained_person as retained, knowledge_relation_mask_source as inherited, knowledge_context_score as core


class SelectorSource(inherited.RelationSource):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for rva,n,digest in NATIVE_GUARDS:
            if hashlib.sha256(self.read(self.base+rva,n)).hexdigest()!=digest:
                raise core.SourceUnavailable('PERSON selector source changed')

    def club150(self,club):
        self.entity(club.address,'club')
        self.route(self.ptr(club.address),0x150,0xe2767c)
        team=self.first_team(club)
        if team is None or not self.ptr(team.address+0x30):
            return True
        definition=self.entity(self.ptr(team.address+0x50),'competition')
        payload=self.ptr(definition.address+0xb0)if definition else 0
        if not payload:
            return True
        # Exact COMP-owned state used by the guarded native predicate. These
        # are numeric internal operands, never English labels or new entities.
        mode=self.u32(self.base+0x56d3518)
        link=self.ptr(payload+0x138)
        uid=self.u32(link+0xc)if link else 0xffffffff
        if mode==uid:
            return False
        flags=self.u32(payload+0x4c)
        if flags&64 or self.u8(payload+0x4c0)==3:
            return True
        if flags&(1<<17)or self.ptr(payload+0x510):
            return True
        nested=self.ptr(payload+0x388)
        if nested:
            state=self.u8(nested+0x23c)
            if state==3 or self.i16(payload+0x3b6)==-3:
                return True
            if state==1:
                raise core.SourceUnavailable('Unproved selector club150 nested3ab45dc predicate')
            return False
        return self.i16(payload+0x3b6)==-3

    def select_person6f(self,club):
        if self.u8(club.address+0xba):
            raise core.SourceUnavailable('Unproved selector6f special CLUB')
        # This bound ordinary CLUB branch can take its direct virtual158
        # result before any retained/cold lookup. Preserve the earlier HUMAN
        # owner check instead of assuming all ordinary clubs share it.
        first=self.first_team(club)
        if first is None or self.ptr(first.address+0x80)!=self.owner.primary:
            raise core.SourceUnavailable('Unproved selector6f parent/foreign-owner prefix')
        if struct.unpack('<q',self.read(self.ptr(self.owner.primary)-0x20,8))[0]!=0x548:
            raise core.SourceUnavailable('Selector owner NON_PLAYER to PERSON displacement changed')
        table=self.ptr(self.owner.person.address)
        self.route(table,0x1b0,0x1300058)
        self.route(table,0x6f0,0x1300074)
        if self.club150(club):
            raise core.SourceUnavailable('Reached selector6f CLUB158 source')
        # 6f with null TEAM has contextFF; the pinned15b7480 jump entry is its
        # zero route. With no native parent this reaches the own retained list.
        if self._selected_parent(club) is not None:
            raise core.SourceUnavailable('Unproved selector6f parent retained source')
        canary=self.ptr(self.base+0x54b05b0)
        if not canary:raise core.SourceUnavailable('Missing selector stack guard source')
        self.read(canary,8)  # Actual original-body guard input, never a stub.
        result=retained.resolve(self.read,self.base,club.address,club.identity,0x6f,255,check_current=self.lifetime)
        if result['state']!='person':
            raise core.SourceUnavailable('Reached selector6f cold source after retained selection')
        if result['record_kind']=='virtual':
            raise core.SourceUnavailable('Unproved compact retained selector PERSON')
        rules=self.ptr(self.base+0x56d57d0)
        inherited.prepared_tactics_source._typed(self.read,self.base,rules,0x55dd068,b'23GAME_RULE_GROUP_MANAGER',0)
        self.route(self.ptr(rules),0x30,0x1bdbc08)
        self._retained_contract_filter(club,result)
        person=result['person_address'];table=self.ptr(person)
        self.route(table,0x1b0,0x1300058 if result['record_kind']=='human_manager'else 0xca4638)
        # Both1b0 results preserve this PERSON for selector6f and flag4=1.
        return result

    def _retained_contract_filter(self,club,result):
        person=result['person_address'];table=self.ptr(person)
        self.route(table,0x3c0,0xcb8c68)
        if struct.unpack('<q',self.read(table-0x3d0,8))[0]!=-0x110:
            raise core.SourceUnavailable('Retained PERSON club-contract projection changed')
        # The fast native filter succeeds on this direct main-contract route.
        # Preserve unsupported affiliation/holder/cache alternatives explicitly.
        main=self.contract(self.ptr(person-0x98))
        if not main or self.ptr(main.address+8)!=person:
            raise core.SourceUnavailable('Unproved retained selector main contract')
        team=self.team(self.ptr(main.address+0x10))
        owner=self.normal_club(team)
        if owner!=club:
            raise core.SourceUnavailable('Unproved retained selector non-direct contract filter')
        if not self.accepted(main):
            raise core.SourceUnavailable('Unproved retained selector contract fallback filter')


    def _recent_fanout(self):
        stored=self.stored_team(self.subject)
        if stored is None:return
        club=self.owner_eligible_club()
        owner=self.entity(self.ptr(stored.address+0x30),'club'if stored.kind=='team'else'national_team_container')
        if owner is not None and owner.kind!='club':
            raise core.SourceUnavailable('Unproved national recent-node source')
        first=self.first_team(club)if club else None
        row=self._recent_nodes(owner,stored,first)if owner and first else None
        secondary=None if row is not None else self.secondary_team()
        if row is None and owner and secondary:row=self._recent_nodes(owner,stored,secondary)
        if row is None:
            return 0
        selected=self.select_person6f(self.current_club(self.owner))
        if selected['projection_state']=='native_null':
            return 0
        if selected['projection_state']!='existing_non_player':
            raise core.SourceUnavailable('Unproved final relation PERSON projection')
        nonplayer=selected['non_player_address']
        if struct.unpack('<q',self.read(self.ptr(nonplayer)-0x20,8))[0]!=selected['person_address']-nonplayer:
            raise core.SourceUnavailable('Final relation NON_PLAYER to PERSON cast changed')
        current=self._retained_current_club(selected)
        if current is None or current!=self.owner_eligible_club():
            raise core.SourceUnavailable('Unproved final relation auxiliary association comparison')
        assessment=self._relation_club_assessment()
        if assessment is None:return 0x0e
        score=core._signed(self.u8(assessment+0x3f),8)
        if score==100:return 0x1fe
        for lower,mask in ((90,0xfe),(80,0x7e),(70,0x3e),(60,0x1e),(40,0x0e)):
            if score>lower:return mask
        return 4

    def _retained_current_club(self,selected):
        person=selected['person_address'];table=self.ptr(person)
        self.route(table,0x240,0x1489900)
        if selected['record_kind']in('actual','player_staff'):
            self.route(table,0x230,0xd5c578)
            if struct.unpack('<q',self.read(table-0x240,8))[0]!=-selected['person_offset']:
                raise core.SourceUnavailable('Retained current-TEAM cast changed')
            stored=self.team(self.ptr(selected['primary_address']+0x128))
            if stored and stored.kind=='team':return self.normal_club(stored)
        else:
            self.route(table,0x230,0xca4744)
        return self.generic_eligible_club(person)

    def _assessment_bounds(self,address):
        # Native consumers read begin/end, not unused allocated capacity. Keep
        # the4096 used-entry budget and the canonical-table capacity bound.
        start,count=self.reader.bounds(address,8,2000000)
        if count>inherited.view.state.inherited.LIMIT:
            raise core.SourceUnavailable('Assessment used-entry reader budget exceeded')
        return start,count

    def state(self):
        # This private collector fixes the native Range caller to assessor0,
        # supplied report0 and mode1. Native H therefore uses K/reciprocal data,
        # not an implicitly selected report. UI caller/report policy is separate.
        candidate=self.own_candidate();self.ordinary_primary();candidate=self.apply_auxiliary(candidate)
        self.assessment_selected=True;self.assessment_record=None
        if candidate:return 2,0,'own_context'
        self.route(self.ptr(self.subject.primary),0x518,0xd5c4bc)
        low,high=self.thresholds(self.u8(self.subject.primary+0x268))
        if not low or not high:return 0,0,'zero_threshold'
        stored=self.reciprocal_score();result=core.evaluate(self)
        if result.score is None:
            raise core.SourceUnavailable('Required contextual K unavailable: '+str(result.reason))
        score=core._signed(max(stored,result.score),8)
        return (2 if score>=high else int(score>=low)),score,'threshold_null_report_mode1'

    def _relation_club_assessment(self):
        # Final fanout calls12d9e40 only. The alternate raw-UID selector used by
        # H after K is deliberately excluded from this earlier dependency.
        start,count=self._assessment_bounds(self.human+0x110)
        rows=[];keys=[]
        for i in range(count):
            row=self.ptr(start+8*i)
            if not row:raise core.SourceUnavailable('Null sorted relation assessment slot')
            person=self.ptr(row)
            key=struct.unpack('<i',self.read(person+8,4))[0]if person else 0
            rows.append(row);keys.append(key)
        if keys!=sorted(keys):raise core.SourceUnavailable('Relation assessment subject-index range is not sorted')
        target=self.subject.person.identity[0]
        for row in rows[bisect_left(keys,target):bisect_right(keys,target)]:
            person=self.reader.resolve_placeholder(self.ptr(row))
            if not person:continue
            if person!=self.subject.person.address:raise core.SourceUnavailable('Relation assessment subject changed')
            assessor=self.ptr(row+8)
            if not assessor:continue
            club=self.generic_eligible_club(assessor)
            if club is None:continue
            owner=self.generic_eligible_club(self.owner.person.address)
            if club==owner or self.reader.parent(club.address)==(owner.address if owner else 0):return row
        return None

    def relation_mask(self):
        owner=self.current_club(self.owner);subject=self.current_club(self.subject)
        if not self.u8(self.owner.primary+0x422)&1:
            if self.u8(self.base+0x56d34e0)==1 and self.u8(self.base+0x56d498a)==1 and self.u8(self.base+0x56d498b)&1:return 0x5fe
        if owner is not None and subject==owner:return 0
        if self._auxiliary_equal():return 0x5fe
        if owner is None:return 0
        self._first_team_special(owner)
        if subject is not None:
            self._parent_fanout(owner,subject);self._relation_fanout(owner,subject)
        self._same_team_fanout();self._subject_parent_fanout(owner)
        return self._recent_fanout()



def collect(bridge,session_id,*,subject_person,subject_identity,coach_name=None,field=18):
    if not isinstance(bridge,inherited.bridge_module.Bridge):
        raise ValueError('A genuine reader Bridge instance is required')
    with bridge.lock,collection_stream(bridge,session_id):
        source=SelectorSource(bridge,session_id,subject_person,subject_identity,coach_name,field)
        try:value=source.permitted()
        except (core.SourceUnavailable,ValueError):value={'state':'unavailable','reason':'unavailable_source'}
        source.verify()
        return dict(scope='private_permitted_passing_view_not_public_mode',field='Passing',native_field_id=18,
                    observer_identity=source.owner.person.identity,subject_identity=source.subject.person.identity,
                    current_date=source.save['current_date'],value=value,non_atomic=True,
                    assessment_freshness='not_established_by_native_selectors')


NATIVE_GUARDS = ((14841468, 216, '2cbf244ebd582d26650d8cea46ef61433ad412faec7ad7e28609be1543c7607a'), (19923032, 8, '5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac'), (22808268, 72, '9b25e636d2efe7652a426b01313af2b26b4edf32e6f433f9dc156e14d49b2f3b'), (24884416, 2056, 'ceaf44b1f88181479f71d0241766f2bc6f1acc530a73ccce5645a08101eb7878'), (24887240, 840, '82a09dd7b6d5573ac5deb5fd0cd60fbedef6a97bbdf832bf72abc586c4103533'), (22770816, 56, 'c1f51fd59193c7501d1600461f6e02e4c83380b62458fe18d84dfb43b49e5b5f'), (29211656, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'), (87681395, 1, '6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d'))
