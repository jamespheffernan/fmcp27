"""No attach: new source HEAD, literal manifests and runtime-origin refusals."""
from pathlib import Path
import importlib.util
import pytest

H=Path(__file__).resolve().parents[1]/'evidence/social-promises-20261109'
SPEC=importlib.util.spec_from_file_location('qualified_concern_collector',H/'collect_current_contract_concerns_pod4.py')
SOURCE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(SOURCE)


@pytest.fixture(autouse=True)
def historical_capture_head(monkeypatch):
    # This collector is immutable historical evidence: after a new commit its
    # real pins() deliberately refuses the new HEAD. Exercise its other guards
    # under an explicit historical-HEAD fixture, never a live capture.
    original=SOURCE.subprocess.check_output
    def command(argv,*args,**kwargs):
        if argv==['git','-C',str(SOURCE.ROOT),'rev-parse','HEAD']:
            value='aab7e5487ad39db74c33911361c2aa9838ddbdaa\n'
            return value if kwargs.get('text')else value.encode()
        return original(argv,*args,**kwargs)
    monkeypatch.setattr(SOURCE.subprocess,'check_output',command)


def test_exact_frozen_head_and_current_runtime_are_explicitly_pinned():
    import _pinned_build
    _pinned_build.require_steam_language_template()
    pins=SOURCE.pins()
    assert pins['head']==pins['expected_source_head']=='aab7e5487ad39db74c33911361c2aa9838ddbdaa'
    assert pins['producer_runtime']==SOURCE.EXPECTED_RUNTIME
    assert pins['collector_origin']==str((H/'collect_current_contract_concerns_pod4.py').resolve())
    assert pins['evidence_sources']['current_contract_concerns_pod4_candidate.py']['sha256']==SOURCE.EXPECTED_POD4['current_contract_concerns_pod4_candidate.py']
    assert 'all object pointers retain8alignment'in pins['pod_record_pointer_policy']


def test_changed_runtime_origin_refuses_instead_of_using_equivalent_engine_bytes(monkeypatch):
    runtime=SOURCE.runtime();runtime['files']['unicorn_python']['origin']=str(H/'native_concern_context_vm.py')
    monkeypatch.setattr(SOURCE,'runtime',lambda:runtime)
    with pytest.raises(ValueError,match='runtime origin or bytes changed'):SOURCE.pins()


def test_source_head_drift_refuses(monkeypatch):
    monkeypatch.setattr(SOURCE,'EXPECTED_HEAD','0'*40)
    with pytest.raises(ValueError,match='source HEAD changed'):SOURCE.pins()


def test_new_qualified_source_drift_refuses(monkeypatch):
    monkeypatch.setattr(SOURCE,'EXPECTED_POD4',{'current_contract_concerns_pod4_candidate.py':'0'*64})
    with pytest.raises(ValueError,match='POD4 source changed'):SOURCE.pins()


def test_no_collectors_or_game_functions_are_called_by_controls():
    assert SOURCE.LEGACY.MAX_READ==16384 and SOURCE.LEGACY.MAX_BYTES==2097152
    with pytest.raises(AssertionError,match='cannot decode profiles'):
        SOURCE.LEGACY.JournalBridge._decode_player(None)
