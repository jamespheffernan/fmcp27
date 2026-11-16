"""Conditional metadata/source checks; not genuine UI or lifecycle evidence."""
import importlib.util
from pathlib import Path
import pytest

H=Path(__file__).resolve().parents[1]/'evidence/social-promises-20261109'
SPEC=importlib.util.spec_from_file_location('concern_default_inner_definitions_candidate_test',H/'concern_default_inner_definitions_candidate.py')
SOURCE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(SOURCE)
import _pinned_build
PLUGIN=_pinned_build.PLUGIN
BASE=0x100000000


def read(address,size):
    with PLUGIN.open('rb')as native:native.seek(0x5ed4000+address-BASE);return native.read(size)


def test_pinned_metadata_retains_context_and_no_key_unknowns():
    counts={}
    for reason,row in SOURCE.DATA['rows'].items():counts[row['state']]=counts.get(row['state'],0)+1
    assert counts=={'constant_first_default_inner_translation_key':461,'no_first_translation_key':391,'unknown_context_controls_first_key_branch':10,'other_callee_before_first_key':1}
    for reason,row in SOURCE.DATA['rows'].items():
        if row['state']=='constant_first_default_inner_translation_key':assert row['english_template']and row['translation_key']
        else:assert row['english_template']is row['translation_key']is None


def test_named_template_is_explicitly_conditional_before_wrapper_or_rendering():
    reason=next(int(reason)for reason,row in SOURCE.DATA['rows'].items()if row['translation_key']==377863)
    result=SOURCE.inspect(read,BASE,reason)
    assert result['english_template']=='Dislikes [%person#1] due to team meeting fall-out'
    assert result['state']=='compiled_default_inner_template'
    assert result['compiled_prefix_only']is True
    assert result['wrapper_overrides_evaluated']is result['placeholder_people_resolved']is result['localized_UI_rendered']is result['lifecycle_evaluated']is False


@pytest.mark.parametrize('reason',[594,648,649,650,651,652,653,654,1300,1301])
def test_unknown_context_never_uses_zero_as_a_default_label(reason):
    result=SOURCE.inspect(read,BASE,reason)
    assert result['state']=='unknown_context_controls_first_key_branch'
    assert result['translation_id']is result['english_template']is None


@pytest.mark.parametrize('reason',[0,499,1363,65535])
def test_outside_dispatch_has_no_invented_template(reason):
    result=SOURCE.inspect(read,BASE,reason)
    assert result['state']=='outside_default_reason_dispatch'and result['translation_id']is result['english_template']is None


@pytest.mark.parametrize('reason',[True,-1,65536,'650',None])
def test_invalid_reason_or_source_refuses(reason):
    with pytest.raises(ValueError):SOURCE.inspect(read,BASE,reason)


@pytest.mark.parametrize('source_index',[0,1])
def test_changed_native_prefix_or_dispatch_table_refuses(source_index):
    span=SOURCE.DATA['source_spans'][source_index];bad=BASE+int(span['rva'],16)
    def altered(address,size):
        raw=read(address,size)
        return bytes([raw[0]^1])+raw[1:]if address==bad else raw
    with pytest.raises(ValueError,match='source changed'):SOURCE.inspect(altered,BASE,500)
