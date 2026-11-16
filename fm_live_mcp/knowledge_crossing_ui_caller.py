"""Private PERSON_UI-selected Crossing11 endpoints; no public mode or rendering.

The original report/assessor prefix is field-independent. Crossing's own
metadata/threshold/getter hooks feed the original H/Range path after that
selection. Report freshness and complete searchable population remain separate.
"""
from . import knowledge_crossing_view as crossing
from . import knowledge_person_ui_caller as inherited
from .knowledge_native_scope import collection_stream


class CrossingUiCallerSource(crossing.CrossingProjectionSource,inherited.UiCallerSource):
    pass


def collect(bridge,session_id,*,subject_person,subject_identity,coach_name=None,field=11):
    if not isinstance(bridge,crossing.inherited.bridge_module.Bridge):
        raise ValueError('A genuine reader Bridge instance is required')
    with bridge.lock,collection_stream(bridge,session_id):
        source=CrossingUiCallerSource(bridge,session_id,subject_person,subject_identity,coach_name,field)
        try:value=source.permitted()
        except(crossing.state.core.SourceUnavailable,ValueError):
            value={'state':'unavailable','reason':'unavailable_source'}
        source.verify()
        return dict(scope='private_person_ui_crossing11_view_not_public_mode',field='Crossing',native_field_id=11,
            observer_identity=source.owner.person.identity,subject_identity=source.subject.person.identity,
            current_date=source.save['current_date'],value=value,non_atomic=True,
            assessment_freshness='not_established_by_native_selectors',manager_knowledge_verified=False,
            rendered_ui_verified=False,complete_search_population=False)
