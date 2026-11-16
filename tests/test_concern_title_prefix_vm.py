"""Original literal key-prefix execution with explicit native record fields."""
from pathlib import Path
import importlib.util
import sys
import pytest

pytest.importorskip('capstone')
H = Path(__file__).resolve().parents[1] / 'evidence/social-promises-20261109'
sys.path.insert(0, str(H))
SPEC = importlib.util.spec_from_file_location('concern_title_prefix_vm_test', H / 'native_concern_title_prefix_vm.py')
VM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VM)
import _pinned_build
PLUGIN = _pinned_build.PLUGIN
BASE = 0x100000000


def read(address, size):
    with PLUGIN.open('rb') as native:
        native.seek(0x5ed4000 + address - BASE)
        return native.read(size)


@pytest.mark.parametrize('reason,key', [(648,629791),(649,629793),(650,629797),(651,629795),(652,629798),(653,629796),(654,629795),(1300,629800),(1301,629802)])
def test_known_record_context_closes_nine_previously_tainted_first_keys(reason, key):
    result = VM.execute(read, BASE, reason, 1, 0, 0, 0, 1)
    assert result['state'] == 'original_contextual_first_translation_key'
    assert result['translation_id'] == key
    assert result['whole_formatter_executed'] is result['translation_executed'] is result['UI_or_lifecycle_evaluated'] is False


@pytest.mark.parametrize('reason,key', [(648,629790),(649,629790),(650,629790),(651,629790),(652,629790),(653,629794),(654,629790),(1300,629799),(1301,629801)])
def test_record_scalar14_selects_original_alternate_key(reason, key):
    assert VM.execute(read, BASE, reason, 1, 0, 0, 3, 1)['translation_id'] == key


def test_signed_record_scalar18_and_scalar14_are_not_zero_defaults():
    assert VM.execute(read, BASE, 649, 5, 0, 0, 1, 1)['translation_id'] == 629790
    assert VM.execute(read, BASE, 649, -1, 0, 0, 1, 1)['translation_id'] == 629792
    assert VM.execute(read, BASE, 649, -1, 0, 0, 0xffff, 1)['translation_id'] == 629793


def test_reason594_requires_actual_team_context_for_nonnegative_scalar08():
    assert VM.execute(read, BASE, 594, 1, 0xffffffff, 0, 0, 1)['translation_id'] == 629747
    unknown = VM.execute(read, BASE, 594, 1, 0, 0, 0, 1)
    assert unknown['state'] == 'context_data_before_first_key' and unknown['translation_id'] is None


@pytest.mark.parametrize('reason',[594,648,649,650,651,652,653,654,1300,1301])
def test_conservative_template_carrier_does_not_promote_context_sensitive_keys(reason):
    result=VM.execute(read,BASE,reason,1,0xffffffff,0,1,1,context_fields_known=False)
    assert result['state']=='unknown_context_controls_first_key_branch'
    assert result['translation_id']is None


@pytest.mark.parametrize('reason', [594,649,650])
def test_unknown_record_field_refuses_even_if_current_reason_might_ignore_it(reason):
    with pytest.raises(ValueError):
        VM.execute(read, BASE, reason, None, 0, 0, 0, 1)


@pytest.mark.parametrize('source_index', [0,1])
def test_changed_original_prefix_or_dispatch_table_refuses(source_index):
    changed = BASE + int(VM.DATA['source_spans'][source_index]['rva'], 16)
    def altered(address, size):
        raw = read(address, size)
        return bytes([raw[0] ^ 1]) + raw[1:] if address == changed else raw
    with pytest.raises(ValueError, match='source changed'):
        VM.execute(altered, BASE, 649, 1, 0, 0, 0, 1)
