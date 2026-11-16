"""Conditional template metadata; original-ARM64 parity is a separate receipt."""
from pathlib import Path
import importlib.util
import pytest

H = Path(__file__).resolve().parents[1] / 'evidence/social-promises-20261109'
SPEC = importlib.util.spec_from_file_location('concern_wrapper_definitions_candidate_test', H / 'concern_wrapper_definitions_candidate.py')
SOURCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE)
import _pinned_build
PLUGIN = _pinned_build.PLUGIN
BASE = 0x100000000


def read(address, size):
    with PLUGIN.open('rb') as native:
        native.seek(0x5ed4000 + address - BASE)
        return native.read(size)


def test_category8_stored_flag_override_has_a_distinct_template():
    table = bytes.fromhex(SOURCE.DATA['reason_category_table_hex'])
    reason = 500 + table.index(8)
    plain = SOURCE.inspect(read, BASE, reason, 0)
    changed = SOURCE.inspect(read, BASE, reason, 0x80)
    assert plain['selection'] == 'default_inner_formatter'
    assert changed['selection'] == 'flags_bit7_and_reason_category8'
    assert changed['translation_id'] == 714687 and changed['english_template']
    assert changed['state'] == 'compiled_wrapper_override_template'
    assert changed['wrapper_first_branch_evaluated'] is True
    assert changed['complete_formatter_executed'] is changed['placeholder_people_resolved'] is changed['localized_UI_rendered'] is changed['lifecycle_evaluated'] is False


def test_other_category_does_not_apply_override():
    table = bytes.fromhex(SOURCE.DATA['reason_category_table_hex'])
    reason = next(500 + index for index, category in enumerate(table) if category != 8 and SOURCE.INNER.DATA['rows'][str(500 + index)]['translation_key'])
    plain, flagged = (SOURCE.inspect(read, BASE, reason, flags) for flags in (0, 255))
    assert plain['translation_id'] == flagged['translation_id']
    assert flagged['state'] == 'compiled_wrapper_default_first_template'


@pytest.mark.parametrize('flags', [None, True, -1, 256, '128'])
def test_unknown_or_invalid_flags_never_default_to_zero(flags):
    with pytest.raises(ValueError):
        SOURCE.inspect(read, BASE, 500, flags)


@pytest.mark.parametrize('source_index', range(3))
def test_changed_wrapper_or_original_category_source_refuses(source_index):
    changed = BASE + int(SOURCE.DATA['source_spans'][source_index]['rva'], 16)
    def altered(address, size):
        raw = read(address, size)
        return bytes([raw[0] ^ 1]) + raw[1:] if address == changed else raw
    with pytest.raises(ValueError, match='source changed'):
        SOURCE.inspect(altered, BASE, 500, 128)


@pytest.mark.parametrize('reason', [0, 499, 1363, 65535])
def test_unknown_default_reason_preserves_no_template(reason):
    result = SOURCE.inspect(read, BASE, reason, 255)
    assert result['state'] == 'outside_default_reason_dispatch'
    assert result['translation_id'] is result['english_template'] is None
