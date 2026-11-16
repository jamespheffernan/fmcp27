"""Private PERSON_UI-selected Passing caller, never a public Manager mode.

The guarded3f9878 caller selects club report first, then reverse raw-UID
fallback, before the field loop. It supplies that report and its assessor to
Range with mode1. No completion/freshness or rendered UI claim follows.
"""
from .knowledge_native_scope import collection_stream
import hashlib
from . import knowledge_person_selector as inherited, knowledge_context_score as core


class UiCallerSource(inherited.SelectorSource):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for rva,n,digest in NATIVE_GUARDS:
            if hashlib.sha256(self.read(self.base+rva,n)).hexdigest()!=digest:
                raise core.SourceUnavailable('PERSON_UI report caller changed')

    def ui_report(self):
        row=self._relation_club_assessment()
        if row is not None:
            self.ptr(row+8)  # Upstream UI always loads the assessor argument.
            return row
        # Native12da3d0 visits the alternate range in reverse physical order,
        # using raw UID without resolving placeholders or filtering assessor.
        start,count=self._assessment_bounds(self.human+0x128)
        for i in range(count-1,-1,-1):
            row=self.ptr(start+8*i)
            if not row:continue
            person=self.ptr(row)
            if not person or self.u32(person+0xc)!=self.subject.person.identity[1]:continue
            if person!=self.subject.person.address:
                raise core.SourceUnavailable('UI alternate assessment UID is ambiguous')
            self.ptr(row+8)
            return row
        return None

    def state(self):
        # Upstream caller selects even if H later takes own-context or zero
        # thresholds. Preserve that dependency/order separately from H itself.
        selected=self.ui_report()
        native_state,score,route=super().state()
        self.assessment_record=selected
        self.assessment_selected=True
        if route!='threshold_null_report_mode1':
            return native_state,score,'person_ui_'+route
        if selected is not None:
            score=max(score,core._signed(self.u8(selected+0x3f),8))
        low,high=self.thresholds(self.u8(self.subject.primary+0x268))
        return (2 if score>=high else int(score>=low)),score,'person_ui_threshold_report_mode1'


def collect(bridge,session_id,*,subject_person,subject_identity,coach_name=None,field=18):
    if not isinstance(bridge,inherited.inherited.bridge_module.Bridge):
        raise ValueError('A genuine reader Bridge instance is required')
    with bridge.lock,collection_stream(bridge,session_id):
        source=UiCallerSource(bridge,session_id,subject_person,subject_identity,coach_name,field)
        try:value=source.permitted()
        except (core.SourceUnavailable,ValueError):value={'state':'unavailable','reason':'unavailable_source'}
        source.verify()
        return dict(scope='private_person_ui_passing_view_not_public_mode',field='Passing',native_field_id=18,
                    observer_identity=source.owner.person.identity,subject_identity=source.subject.person.identity,
                    current_date=source.save['current_date'],value=value,non_atomic=True,
                    assessment_freshness='not_established_by_native_selectors')


NATIVE_GUARDS = ((4167800, 60, '99007b85e8dbea1529e1146dfd0d7f056ff8866160f5bc476ddb616337780276'), (4181132, 8, '7596464823fb848019e409ee0b0e5d041915a2c3ff7c3c18d1c9ad140067e654'), (4167876, 16, '543e5cbf5d91eec97faf9d34c1dc791a5a75e3dfe35910b18db52661cf083ae8'), (4167916, 36, 'a649bc6d1668028ac97f9d37d2972aae19bf2ddb60e229cf7bed887e00a31fae'), (4162868, 72, '457c1ae76952cd2f575b607ba60af9468581d94c873b61bef666c183b95e4bae'))
