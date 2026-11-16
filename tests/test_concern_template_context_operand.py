"""Qualified operational read controls; no current-packet byte borrowing."""
import _pinned_build
import importlib.util
import json
from pathlib import Path
import pytest
from test_player_concern_history_source import Original

H=Path(__file__).resolve().parents[1]/'evidence/social-promises-20261109'
SPEC=importlib.util.spec_from_file_location('qualified_template_context_operand_controls',H/'collect_concern_template_carriers_context.py')
SOURCE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(SOURCE)
CAPTURE_HEAD=SOURCE.EXPECTED_HEAD


@pytest.fixture(autouse=True)
def reach_later_guards_under_current_head(monkeypatch):
    # This is a guard unit fixture, never a collection or a new provenance claim.
    head=SOURCE.subprocess.check_output(['git','-C',str(SOURCE.ROOT),'rev-parse','HEAD'],text=True).strip()
    monkeypatch.setattr(SOURCE,'EXPECTED_HEAD',head)


def test_explicit_operational_read_uses_typed_current_club_and_preserves_raw_value():
    old=Original();row=old.first();history=old.inspect(row);reads=[]
    def read(address,size):reads.append((address,size));return old.read(address,size)
    team=int.from_bytes(old.read(row['primary_private']+0x128,8),'little');club=int.from_bytes(old.read(team+0x30,8),'little')
    assert SOURCE.capture_context_operational_operand(read,old.base,row['primary_private'],history)==old.read(club+0xba,1)
    assert(club+0xba,1)in reads


def test_current_carrier_missing_byte_is_refused_without_borrowing_the_old_byte():
    packet=json.loads((H/'live-concern-template-carriers-1.json').read_text());cells={}
    for row in packet['journal']['regions']:
        address=int(row['address'],16);cells.update({address+offset:value for offset,value in enumerate(bytes.fromhex(row['raw_hex']))})
    def read(address,size):
        try:return bytes(cells[address+offset]for offset in range(size))
        except KeyError as error:raise ValueError('Missing current literal operand')from error
    carrier=packet['players'][0]
    with pytest.raises(ValueError,match='Missing current literal'):
        SOURCE.capture_context_operational_operand(read,int(packet['plugin_base_private'],16),carrier['primary_private'],carrier['concern_history'])


def test_foreign_or_unqualified_context_refuses_before_operational_read():
    old=Original();row=old.packet['players'][10];history=old.inspect(row)
    with pytest.raises(ValueError,match='Unqualified concern context'):
        SOURCE.capture_context_operational_operand(lambda *args:(_ for _ in()).throw(AssertionError('No read')),old.base,row['primary_private'],history)


def test_incomplete_operational_byte_never_becomes_a_default_zero():
    old=Original();row=old.first();history=old.inspect(row)
    team=int.from_bytes(old.read(row['primary_private']+0x128,8),'little');club=int.from_bytes(old.read(team+0x30,8),'little')
    def incomplete(address,size):return b''if address==club+0xba else old.read(address,size)
    with pytest.raises(ValueError,match='Incomplete original concern context'):
        SOURCE.capture_context_operational_operand(incomplete,old.base,row['primary_private'],history)


def test_wrong_club_type_is_not_silently_followed():
    old=Original();row=old.first();history=old.inspect(row)
    team=int.from_bytes(old.read(row['primary_private']+0x128,8),'little');club=int.from_bytes(old.read(team+0x30,8),'little')
    old.put(club,(old.base+0x5588ee8).to_bytes(8,'little'))
    with pytest.raises(ValueError):SOURCE.capture_context_operational_operand(old.read,old.base,row['primary_private'],history)


def test_new_collector_keeps_head_runtime_and_distinct_journal_budgets():
    _pinned_build.require_steam_language_template()   # its collector hashes the install's English template
    pins=SOURCE.pins()
    assert CAPTURE_HEAD=='a4eb95153fb03ccb250fdf7d2afa8e5ba50dfb88'and pins['head']==SOURCE.EXPECTED_HEAD
    assert len(pins['files'])==len(list((SOURCE.ROOT/'fm_live_mcp').rglob('*.py')))
    assert pins['producer_runtime']==SOURCE.EXPECTED_RUNTIME
    assert SOURCE.MAX_BYTES==131072 and SOURCE.MAX_REGIONS==2048


def test_frozen_context_capture_still_refuses_actual_new_head(monkeypatch):
    actual=SOURCE.EXPECTED_HEAD
    monkeypatch.setattr(SOURCE,'EXPECTED_HEAD',CAPTURE_HEAD)
    if actual!=CAPTURE_HEAD:
        with pytest.raises(ValueError,match='source HEAD changed'):SOURCE.pins()
    else:assert SOURCE.pins()['head']==CAPTURE_HEAD
