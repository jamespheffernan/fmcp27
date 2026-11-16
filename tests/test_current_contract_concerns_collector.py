"""New concern collector source and owner-selection controls; never attach."""
import importlib.util
import hashlib
from pathlib import Path
import pytest

H=Path(__file__).resolve().parents[1]/'evidence/social-promises-20261109'
SPEC=importlib.util.spec_from_file_location('concern_source_collector_test',H/'collect_current_contract_concerns.py')
SOURCE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(SOURCE)


def row(state,count,context=False):
    result={'concern_history':{'state':state,'native_ring_entry_count':count,'records':None if count is None else[]}}
    if context:result['concern_history']['contract_context']='owned_main_FULL_CONTRACT_matches_current_TEAM_CLUB'
    return result


@pytest.mark.parametrize('unsupported_first',[False,True])
def test_unsupported_companion_preserves_supported_context(unsupported_first):
    supported=row('observed_native_ring',2,True);unsupported=row('unsupported_record_kind',None)
    rows=[unsupported,supported]if unsupported_first else[supported,unsupported]
    assert SOURCE.select_context_owner(rows)is supported


def test_nonempty_history_precedes_empty_but_empty_context_remains_testable():
    empty=row('observed_empty_native_ring',0,True);full=row('observed_native_ring',3,True)
    assert SOURCE.select_context_owner([empty,full])is full
    assert SOURCE.select_context_owner([empty])is empty


def test_all_unavailable_owners_do_not_become_an_empty_context():
    assert SOURCE.select_context_owner([row('unsupported_record_kind',None),row('main_contract_unavailable',None)])is None


def test_producer_runtime_and_all_new_evidence_sources_are_attested():
    import _pinned_build
    _pinned_build.require_steam_language_template()
    pin=SOURCE.pins()
    assert pin['producer_runtime']['unicorn_version']=='2.1.4'
    assert set(pin['producer_runtime']['files'])=={'python_executable','unicorn_python','unicorn_native'}
    for proof in pin['producer_runtime']['files'].values():
        assert Path(proof['origin']).is_absolute()
        assert hashlib.sha256(Path(proof['origin']).read_bytes()).hexdigest()==proof['sha256']
    for name,proof in pin['evidence_sources'].items():
        assert proof['origin']==str((H/name).resolve())
        assert(H/name).read_bytes()==proof['utf8'].encode()
        assert hashlib.sha256(proof['utf8'].encode()).hexdigest()==proof['sha256']
    assert pin['evidence_sources']['collect_promise_exporter_operands.py']['sha256']=='0ba907e25c7df55ca1187bbcc1558ae789bb7344b3ae32dd7ee47edf15d4cff6'
    assert pin['helper_origin']==str((Path('/Volumes/4TB Private/Offloaded/FMCP 27/build/fm_live_helper')).resolve())


def test_inherited_transport_retains_exact_bounds_and_profile_refusal():
    assert SOURCE.LEGACY.MAX_BYTES==2*1024*1024
    assert SOURCE.LEGACY.MAX_REGIONS==16384 and SOURCE.LEGACY.MAX_READ==16384
    with pytest.raises(AssertionError,match='cannot decode profiles'):
        SOURCE.LEGACY.JournalBridge._decode_player(None)
