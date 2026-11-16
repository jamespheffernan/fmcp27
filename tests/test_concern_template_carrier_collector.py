"""Offline selection, source, refusal and tight-budget carrier controls."""
import _pinned_build
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_player_concern_history_source import Original

H=Path(__file__).resolve().parents[1]/'evidence/social-promises-20261109'
SPEC=importlib.util.spec_from_file_location('concern_template_carrier_controls',H/'collect_concern_template_carriers.py')
SOURCE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(SOURCE)
CAPTURE_HEAD=SOURCE.EXPECTED_HEAD


@pytest.fixture(autouse=True)
def reach_later_guards_under_current_head(monkeypatch):
    # Frozen capture code must refuse new HEADs. Only this non-collection unit
    # fixture changes its in-memory precondition to exercise the later guards.
    head=SOURCE.subprocess.check_output(['git','-C',str(SOURCE.ROOT),'rev-parse','HEAD'],text=True).strip()
    monkeypatch.setattr(SOURCE,'EXPECTED_HEAD',head)


def test_only_two_named_canonical_id_carriers_are_selected_from_retained_roster():
    old=Original();selected=SOURCE.selected_owners(old.read,old.base,old.packet['context_before']['roster'])
    assert[selected[0][0],selected[1][0]]==[0,7]
    assert[old.inspect(old.packet['players'][slot])['owner']['display_name']for slot,primary in selected]==['Anthony Gordon','Lewis Miley']


def test_unsupported_companion_cannot_hide_or_replace_a_carrier():
    old=Original();unsupported=0x7b00000000;old.put(unsupported,(old.base+0x1234).to_bytes(8,'little'))
    roster=[unsupported]+old.packet['context_before']['roster']
    assert[len(SOURCE.selected_owners(old.read,old.base,roster)),SOURCE.selected_owners(old.read,old.base,roster)[0][0]]==[2,1]


def test_missing_selected_owner_refuses_without_fallback_to_other_history():
    old=Original();roster=old.packet['context_before']['roster'][1:]
    with pytest.raises(ValueError,match='absent; no fallback'):SOURCE.selected_owners(old.read,old.base,roster)


def test_repeated_selected_owner_refuses_duplicate_carriers():
    old=Original();roster=old.packet['context_before']['roster']*2
    with pytest.raises(ValueError,match='Duplicate'):SOURCE.selected_owners(old.read,old.base,roster)


def test_earlier_raw_packet_cannot_supply_missing_template_source_bytes():
    old=Original();history=old.inspect(old.first())
    with pytest.raises(ValueError,match='Missing literal retained'):
        SOURCE.unrendered_templates(old.read,old.base,history)
    with pytest.raises(ValueError,match='Missing literal retained'):
        SOURCE.verify_template_source(old.read,old.base)


def test_unavailable_contract_context_never_becomes_a_template_or_empty_history():
    old=Original();history=old.inspect(old.packet['players'][10])
    with pytest.raises(ValueError,match='unavailable current contract context'):
        SOURCE.unrendered_templates(old.read,old.base,history)


def test_null_native_slot_remains_an_explicit_null_template():
    old=Original();history=old.inspect(old.first());history['records']=[dict(entry_index=0,record=None)]
    assert SOURCE.unrendered_templates(old.read,old.base,history)==[dict(entry_index=0,compiled_unrendered_template=None)]


@pytest.mark.parametrize('fault',['bytes','regions'])
def test_tighter_budget_refuses_before_any_inherited_physical_read(monkeypatch,fault):
    bridge=object.__new__(SOURCE.BoundedBridge)
    bridge.journal=SimpleNamespace(observed={})
    bridge.consumed_bytes=SOURCE.MAX_BYTES if fault=='bytes'else 0
    if fault=='regions':bridge.journal.observed={index:None for index in range(SOURCE.MAX_REGIONS)}
    monkeypatch.setattr(SOURCE.LEGACY.JournalBridge,'_read_memory',lambda *args:(_ for _ in()).throw(AssertionError('Physical read must not happen')))
    with pytest.raises(ValueError,match='budget exceeded; no truncation'):bridge._read_memory(None,0x10000,8)


def test_actual_canonical_runtime_source_and_english_origins_are_pinned():
    _pinned_build.require_steam_language_template()   # its collector hashes the install's English template
    pins=SOURCE.pins()
    assert len(pins['files'])==len(list((SOURCE.ROOT/'fm_live_mcp').rglob('*.py')))
    assert pins['head']==SOURCE.EXPECTED_HEAD and CAPTURE_HEAD=='a4eb95153fb03ccb250fdf7d2afa8e5ba50dfb88'
    assert pins['producer_runtime']==SOURCE.EXPECTED_RUNTIME
    assert pins['english_resource']['sha256']=='3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'
    assert pins['evidence_sources']['collect_promise_exporter_operands.py']['sha256']=='0ba907e25c7df55ca1187bbcc1558ae789bb7344b3ae32dd7ee47edf15d4cff6'
    assert pins['evidence_sources']['concern-template-source-spans.json']['sha256']==SOURCE.EXPECTED_DEPS['concern-template-source-spans.json']
    assert SOURCE.MAX_BYTES==131072 and SOURCE.MAX_REGIONS==2048


def test_wrong_loaded_inner_origin_refuses(monkeypatch):
    monkeypatch.setattr(SOURCE.META.INNER,'__file__',str(H/'native_status_vm.py'))
    with pytest.raises(ValueError,match='inner template source origin'):SOURCE.pins()


def test_profile_generation_stays_refused():
    with pytest.raises(AssertionError,match='cannot decode profiles'):
        SOURCE.BoundedBridge._decode_player(None)


def test_frozen_capture_still_refuses_the_actual_new_head(monkeypatch):
    actual=SOURCE.EXPECTED_HEAD
    monkeypatch.setattr(SOURCE,'EXPECTED_HEAD',CAPTURE_HEAD)
    if actual!=CAPTURE_HEAD:
        with pytest.raises(ValueError,match='source HEAD changed'):SOURCE.pins()
    else:assert SOURCE.pins()['head']==CAPTURE_HEAD
