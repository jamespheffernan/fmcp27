"""Private Crossing11 endpoint projection under the explicit H report policy.

Reuses the original Range math with Crossing's field-dependent offset seed.
Crossing owns its metadata, thresholds and getter byte. Unknown skips the
getter entirely; ranges expose endpoints only. PERSON_UI/public mode remain
outside this component, and report freshness remains unestablished.
"""
from . import knowledge_crossing_state as state
from . import knowledge_passing_view as inherited
from .knowledge_native_scope import collection_stream


class CrossingProjectionSource(state.CrossingStateSource,inherited.ProjectionSource):
    def project(self,getter,state,**inputs):
        return inherited.ranges.native_attribute_projection(
            getter,state,native_field_id=self.field,**inputs)

    def getter(self):
        self.ordinary_primary()
        self.route(self.ptr(self.subject.primary),0xf0,0xd19eb0)
        field=state.catalog.field(self.field)
        mode=self.u8(self.subject.primary+0x270)
        stored=self.u8(self.subject.primary+field['primary_offset'])
        return inherited.ranges.passing_getter(stored,mode)


def collect(bridge,session_id,*,subject_person,subject_identity,coach_name=None,field=11):
    if not isinstance(bridge,inherited.bridge_module.Bridge):
        raise ValueError('A genuine reader Bridge instance is required')
    with bridge.lock,collection_stream(bridge,session_id):
        source=CrossingProjectionSource(bridge,session_id,subject_person,subject_identity,coach_name,field)
        try:value=source.permitted()
        except(state.core.SourceUnavailable,ValueError):
            value={'state':'unavailable','reason':'unavailable_source'}
        source.verify()
        return dict(scope='private_crossing11_endpoints_not_person_UI_or_public_mode',
            field='Crossing',native_field_id=11,value=value,
            observer_identity=source.owner.person.identity,subject_identity=source.subject.person.identity,
            current_date=source.save['current_date'],person_ui_caller_evaluated=False,
            manager_knowledge_verified=False,assessment_freshness='not_established_by_native_selectors',non_atomic=True)
