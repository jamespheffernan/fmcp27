"""Private byte-bound Crossing11 H state; no attribute, UI caller or public mode.

The contextual K and H ordinary caller are shared original functions. Only
Crossing's exact compiled metadata and threshold branches are substituted;
Passing's public/private entry points retain their Passing-only validation.
The inherited private assessment selector supplies H's report argument with
mode1. This does not establish the distinct PERSON_UI caller selection policy.
"""
from . import knowledge_context_score as core
from . import knowledge_field_catalog as catalog
from . import knowledge_passing_state as inherited
from . import knowledge_crossing_thresholds as thresholds
from .knowledge_native_scope import collection_stream


class CrossingStateSource(inherited.StateSource):
    FIELD_SCOPE='Crossing11'

    def _supports_field(self,field):
        return type(field)is int and field==11

    def _verify_field_metadata(self):
        catalog.verify_native(self.read,self.base)
        field=catalog.field(self.field)
        if field['compiled_name']!='Crossing'or field['stored_offset']!=0x0f:
            raise core.SourceUnavailable('Selected Crossing11 metadata binding changed')
        thresholds.verify_native(self.read,self.base)

    def thresholds(self,category):
        return thresholds.crossing_thresholds(category)


def collect(bridge,session_id,*,subject_person,subject_identity,coach_name=None,field=11):
    """Return private H state only; no getter value or internal K score escapes."""
    if not isinstance(bridge,inherited.bridge_module.Bridge):
        raise ValueError('A genuine reader Bridge instance is required')
    with bridge.lock,collection_stream(bridge,session_id):
        source=CrossingStateSource(bridge,session_id,subject_person,subject_identity,coach_name,field)
        try:
            state,_,_=source.state()
            value={'state':('unknown','range','exact')[state]}
        except(core.SourceUnavailable,ValueError):
            value={'state':'unavailable','reason':'unavailable_source'}
        source.verify()
        return dict(scope='private_crossing11_H_state_not_field_value_or_public_mode',
            field='Crossing',native_field_id=11,value=value,
            observer_identity=source.owner.person.identity,subject_identity=source.subject.person.identity,
            current_date=source.save['current_date'],field_value_evaluated=False,
            person_ui_caller_evaluated=False,manager_knowledge_verified=False,non_atomic=True)
