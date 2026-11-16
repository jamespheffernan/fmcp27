"""Private typed Passing endpoint projection; never register as a public mode.

Only freshly constructed permitted exact/range/unknown data leaves collect.
Native H score, getter/debug transport, assessment addresses and private range
objects remain internal. All source bytes and context are rechecked after the
last callback. This does not establish search population or UI rendering.
"""
from .knowledge_native_scope import collection_stream
import hashlib
import struct

from . import (assessment_people, bridge as bridge_module, staff,
               prepared_tactics_source, knowledge_context_score as core,
               knowledge_passing_state as state, knowledge_passing_range as ranges)


class ProjectionSource(state.StateSource):
    def project(self,getter,state,**inputs):
        return ranges.native_passing_projection(getter,state,**inputs)

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for rva,size,digest in NATIVE_GUARDS:
            if hashlib.sha256(self.read(self.base+rva,size)).hexdigest()!=digest:
                raise core.SourceUnavailable('Passing projection native source changed')

    def getter(self):
        self.ordinary_primary()
        self.route(self.ptr(self.subject.primary),0xf0,0xd19eb0)
        # Passing18 metadata was bound by the inherited source before any field
        # read. Its getter selects this exact byte and signed scale mode.
        mode=self.u8(self.subject.primary+0x270)
        stored=self.u8(self.subject.primary+0x148+0x16)
        return ranges.passing_getter(stored,mode)

    def assessor_bytes(self):
        if not self.assessment_selected:
            raise core.SourceUnavailable('Range assessor selection has not been established')
        row=self.assessment_record
        person=self.ptr(row+8) if row else 0
        if not person:
            return None
        primary,offset,public,uid,secondary=assessment_people._person(self.read,self.base,self.people,person)
        table=self.ptr(person);kind=public['record_kind']
        if kind=='actual':
            self.route(table,0x658,0xca49c0)
            return None
        if kind not in staff.LAYOUTS:
            raise core.SourceUnavailable('Unproved range assessor family')
        nonplayer_offset=staff.LAYOUTS[kind][3]-8
        self.route(table,0x658,0xca4e78)
        adjustment=struct.unpack('<q',self.read(table-0x668,8))[0]
        if adjustment!=nonplayer_offset-offset:
            raise core.SourceUnavailable('Range assessor NON_PLAYER cast changed')
        nonplayer=primary+nonplayer_offset
        expected_table=0x558f568 if kind=='player_staff' else staff.LAYOUTS[kind][0]
        prepared_tactics_source._typed(self.read,self.base,nonplayer,expected_table,
                                      staff.LAYOUTS[kind][4],-nonplayer_offset)
        return tuple(self.read(nonplayer+0x2c,2))

    def permitted(self):
        native_state,score,route=self.state()
        if native_state==0:
            # Native's hidden third getter byte cannot affect unknown endpoints.
            # Eliminate that unused input entirely rather than copying transport.
            return {'state':'unknown'}
        getter=self.getter()
        if native_state==2:
            projection=self.project(getter,2)
        else:
            projection=self.project(
                getter,1,age=self.native_age(self.subject),
                person_index=self.subject.person.identity[0],
                private_knowledge_score=score,assessor_bytes=self.assessor_bytes())
        # The private projection has an exact getter even for state1. Construct
        # its permitted endpoint-only result before returning any object.
        permitted=ranges.permitted_passing_value(projection)
        if permitted['state']=='unavailable':
            return {'state':'unavailable','reason':'unsupported_native_projection'}
        return permitted


def collect(bridge,session_id,*,subject_person,subject_identity,coach_name=None,field=18):
    """Private root/probe route; returns only the permitted Passing view."""
    if not isinstance(bridge,bridge_module.Bridge):
        raise ValueError('A genuine reader Bridge instance is required')
    with bridge.lock,collection_stream(bridge,session_id):
        source=ProjectionSource(bridge,session_id,subject_person,subject_identity,coach_name,field)
        try:
            value=source.permitted()
        except (core.SourceUnavailable,ValueError):
            # Keep detailed exceptions/internal numbers outside this boundary.
            value={'state':'unavailable','reason':'unavailable_source'}
        source.verify()
        return dict(scope='private_permitted_passing_view_not_public_mode',field='Passing',native_field_id=18,
                    observer_identity=source.owner.person.identity,subject_identity=source.subject.person.identity,
                    current_date=source.save['current_date'],value=value,non_atomic=True,
                    assessment_freshness='not_established_by_native_selectors')


NATIVE_GUARDS = ((37252780, 836, 'd9c4bb089fbf3d8ff9d7109bdca8f468f03717a4f6d9f2a6566bbec048d60d47'), (13737648, 120, '8cf664225461c38119f9007fb7735bb3585839e49183fe6d43e957bbb9ac609b'), (87047824, 8, '4f9fe0685bdf4ceba1148f85eec2f482d24fe4d3ef625e4b8f21512a790f35c5'), (87047768, 8, '7c039a3f7e41f389a828a440c8011656b0b6c0f3da1cca834adb1be3428ca80d'), (87013088, 8, '7b2ed67587fcbc411fcb4b71b1cef1ef6cd9edf948148414cf5f0ab21362b9aa'), (78444596, 36, 'f0b21cec26691de907c307936e46a342cdd2ca1a812ad2995a8b6c9de0f37325'), (13258360, 20, 'd00a7e05bbc8b02cfe3ef011a288eeb1d787d8e9d9bea42002c050b8b2a56139'), (13257152, 8, 'd3c844a0173107453aa9896cdb7276470625501e7ff067cd764c7a160ece5ca3'))
