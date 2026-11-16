"""Private ordinary47-field PERSON_UI endpoint source; never a public mode.

Compiled metadata binds the requested field to its own stored byte. The full
native dispatcher binds its category thresholds; original shared H/K, UI
report selection and Range semantics remain separate checked dependencies.
Unknown reads no attribute; range exposes endpoints only. This establishes no
freshness, rendered UI, final population, perceived stars, CA/PA or activation.
"""
from . import bridge as bridge_module
from . import knowledge_context_score as core
from . import knowledge_passing_range as ranges
from . import knowledge_attribute_thresholds as native_thresholds
from . import knowledge_field_catalog as catalog
from . import knowledge_person_ui_caller as inherited
from .knowledge_native_scope import collection_stream


class AttributeUiCallerSource(inherited.UiCallerSource):
    FIELD_SCOPE='ordinary attribute field0..46'

    def _supports_field(self,field):
        return type(field)is int and 0<=field<47

    def _verify_field_metadata(self):
        catalog.verify_native(self.read,self.base)
        native_thresholds.verify_native(self.read,self.base)
        self.field_metadata=catalog.field(self.field)

    def thresholds(self,category):
        return native_thresholds.thresholds(self.field,category)

    def project(self,getter,state,**inputs):
        return ranges.native_attribute_projection(getter,state,native_field_id=self.field,**inputs)

    def getter(self):
        self.ordinary_primary()
        self.route(self.ptr(self.subject.primary),0xf0,0xd19eb0)
        mode=self.u8(self.subject.primary+0x270)
        stored=self.u8(self.subject.primary+self.field_metadata['primary_offset'])
        return ranges.passing_getter(stored,mode)


def collect(bridge,session_id,*,subject_person,subject_identity,field,coach_name=None):
    if not isinstance(bridge,bridge_module.Bridge):
        raise ValueError('A genuine reader Bridge instance is required')
    with bridge.lock,collection_stream(bridge,session_id):
        source=AttributeUiCallerSource(bridge,session_id,subject_person,subject_identity,coach_name,field)
        try:value=source.permitted()
        except(core.SourceUnavailable,ValueError):
            value={'state':'unavailable','reason':'unavailable_source'}
        source.verify()
        return dict(scope='private_person_ui_attribute_endpoints_not_public_mode',
            field=source.field_metadata['compiled_name'],native_field_id=source.field,value=value,
            observer_identity=source.owner.person.identity,subject_identity=source.subject.person.identity,
            current_date=source.save['current_date'],non_atomic=True,
            assessment_freshness='not_established_by_native_selectors',manager_knowledge_verified=False,
            rendered_ui_verified=False,complete_search_population=False)
