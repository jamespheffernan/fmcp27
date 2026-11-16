"""Stored occurrence semantics; complete original parity is a separate fixture gate."""
import struct
import json
from pathlib import Path

import pytest

from fm_live_mcp import individual_training_ip_role as source


def occurrence(family=0, position=0, level=1, flag=0):
    raw = bytearray(24)
    struct.pack_into('<Hh', raw, 8, ((family & 127) << 6) | (position & 63), level)
    raw[23] = flag
    return bytes(raw)


def test_first_native_match_keeps_occurrence_order_and_does_not_label_later_rows_negative():
    rows = (occurrence(flag=1), occurrence(level=0), occurrence(family=63),
            occurrence(family=-31), occurrence(family=1))
    result = source.decode(rows)
    assert result['selected_stored_slot'] == 3
    assert result['native_ip_role_mask'] == '0x0000000000000001'
    assert result['occurrences'][4]['state'] == 'not_reached_after_native_return'
    assert 'native_signed_role_family' not in result['occurrences'][4]
    assert result['stored_occurrence_count'] == 5
    assert result['native_ip_position_mask'] is None
    assert all(result[name] is False for name in
        ('planned_training_evaluated', 'applied_training_evaluated', 'effective_training_evaluated'))


@pytest.mark.parametrize('rows', [(), (occurrence(level=0),), (occurrence(family=-19),),
                                (occurrence(flag=255),), (occurrence(family=-64),)])
def test_native_zero_preserves_empty_and_checked_nonmatching_sources(rows):
    result = source.decode(rows)
    assert result['native_ip_role_mask'] == '0x0000000000000000'
    assert result['state'] == 'checked_native_zero' and result['selected_stored_slot'] is None
    assert result['source_state'] == ('stored_occurrences' if rows else 'checked_empty_vector')


@pytest.mark.parametrize('entries', [None, [], b'', (b'',), (bytes(23),), (bytes(25),),
                                   (bytearray(24),), (bytes(24),) * 257])
def test_unavailable_truncated_mutable_and_oversized_sources_are_not_empty(entries):
    with pytest.raises(ValueError):source.decode(entries)


@pytest.mark.parametrize('position', [-32, -1, 0, 31])
def test_native_packed_position_operand_remains_signed_and_separate_from_position_mask(position):
    result = source.decode((occurrence(position=position),))
    assert result['occurrences'][0]['native_signed_position_code'] == position
    assert result['native_ip_position_mask'] is None


def test_maximum_population_keeps_every_stored_duplicate_after_native_return():
    result = source.decode((occurrence(),) * 256)
    assert result['selected_stored_slot'] == 0 and result['stored_occurrence_count'] == 256
    assert sum(row['state'] == 'not_reached_after_native_return' for row in result['occurrences']) == 255


@pytest.mark.parametrize('base', [True, 0, 4097, -4096])
def test_invalid_image_binding_rejects_before_source_read(base):
    with pytest.raises(ValueError):source.verify_native(lambda *args:pytest.fail('Read before base validation'),base)


@pytest.mark.parametrize('fault', [None, 'changed0', 'changed1', 'changed2', 'short0', 'short1', 'short2'])
def test_complete_native_code_and_both_data_tables_are_required(fault):
    spans = json.loads((Path(__file__).parent/'fixtures/individual_training_ip_role_native.json').read_text())
    base = 0x100000000
    values = {base + row['rva']: bytes.fromhex(row['raw_hex']) for row in spans}
    if fault:
        at = base + spans[int(fault[-1])]['rva']
        raw = values[at]
        values[at] = raw[:-1] if fault.startswith('short') else bytes((raw[0] ^ 1,)) + raw[1:]
    if fault:
        with pytest.raises(ValueError):source.verify_native(lambda at,n:values[at],base)
    else:
        source.verify_native(lambda at,n:values[at],base)
