import struct
from types import SimpleNamespace

import pytest

from fm_live_mcp.saved_person_candidates import SearchBudget, search_candidates


def layout(count=100):
    return SimpleNamespace(person_count=count, person_offset=0,
                           name_counts=dict(first=10, second=10, common=10),
                           lookup=lambda ns, index: {'raw_hex': 'ff', 'text': None, 'namespace': ns, 'index': index},
                           provenance={'placement': 'structural_candidate'})


def body(indices=(1, 2, -1), *, tail=b'\0', optional=b'\0', language=b''):
    return b''.join(struct.pack('<iB', n, 0) for n in indices) + struct.pack('<I', len(language)) + language + bytes(38) + optional + tail


def record(index, first=123, second=123, tag=2, common=None):
    return (body() if common is None else common) + bytes(8) + struct.pack('<IIIb', index, first, second, tag)


def component(*records):
    return struct.pack('<IBb', 100, 1, 1) + b''.join(records)


def test_witness_keeps_raw_identity_and_names_without_certification():
    result, = search_candidates(component(record(7, 123, 456, tag=64)), layout(), [7])
    assert result['state'] == 'witnessed'
    row, = result['candidates']
    assert row['identity'] == dict(stored_index=7, native_id_word=123, secondary_word=456)
    assert not row['identity_words_equal']
    assert not row['known_paired_writer_next_tag']
    assert row['names'][0]['text'] is None
    assert row['names'][0]['raw_hex'] == 'ff'
    assert row['names'][2] is None
    assert not row['evidence_scope']['certified_person_record']


def test_zero_id_and_competing_unknown_tags_are_retained():
    result, = search_candidates(component(record(7), record(7, 0, 0, 32)), layout(), [7])
    assert result['state'] == 'ambiguous'
    assert len(result['candidates']) == 2
    assert result['candidates'][1]['zero_identity_word']
    assert result['candidates'][1]['next_tag'] == 32


def test_order_duplicates_missing_and_invalid_requests():
    rows = search_candidates(component(record(7)), layout(), [8, 7, 7])
    assert [r['person_index'] for r in rows] == [8, 7, 7]
    assert rows[0]['state'] == 'missing'
    rows[1]['candidates'].clear()
    assert rows[2]['candidates']
    for bad in [-1, 100, True]:
        with pytest.raises(ValueError):
            search_candidates(component(), layout(), [bad])


def test_native_negative_signed_tail_count_skips_rows():
    result, = search_candidates(component(record(7, common=body(tail=b'\1\xff'))), layout(), [7])
    assert len(result['candidates']) == 1


def test_positive_optional48_and_opaque_text():
    child = b'\1' + bytes(16) + struct.pack('<i', 2) + bytes(14) + bytes(3) + b'\1' + bytes(8) + b'\0'
    common = body(optional=b'\1' + child, language=b'\xff\xfe')
    result, = search_candidates(component(record(7, common=common)), layout(), [7])
    assert len(result['candidates']) == 1


def test_truncated_source_and_invalid_name_indices_do_not_witness():
    assert not search_candidates(component(record(7))[:-3], layout(), [7])[0]['candidates']
    assert not search_candidates(component(record(7, common=body((11, 2, -1)))), layout(), [7])[0]['candidates']


@pytest.mark.parametrize('budget,reason', [
    (SearchBudget(max_scan_bytes=0), 'scan_bytes'),
    (SearchBudget(max_identity_hits=0), 'identity_hits'),
    (SearchBudget(max_suffix_attempts=0), 'suffix_attempts'),
    (SearchBudget(max_witnesses=0), 'witnesses'),
    (SearchBudget(max_text_bytes=0), 'text_bytes'),
])
def test_work_stops_are_not_missing(budget, reason):
    result, = search_candidates(component(record(7, common=body(language=b'x'))), layout(), [7], budget=budget)
    assert result['state'] == 'budget'
    assert not result['search_complete']
    assert reason in result['budget_reasons']


def test_requested_iterator_is_bounded():
    with pytest.raises(ValueError, match='requested index budget'):
        search_candidates(component(), layout(), iter([7] * 1000), budget=SearchBudget(max_requested_indices=2))


def test_independently_frozen_b42_suffixes_all_28():
    import json
    from pathlib import Path

    fixture_path = Path(__file__).parent / 'fixtures/saved_person_candidates.json'
    fixture = json.loads(fixture_path.read_text())
    assert fixture['provenance']['blind_freeze_sha256'] == '64cf8f0201162b832b3768a036a22911b037d0a2b28b809cb56882e109ec6a8b'
    rows = fixture['rows']
    names = {}
    for row in rows:
        for ns, name in zip(('first', 'second', 'common'), row['names']):
            if name is not None:
                names[ns, name['index']] = bytes.fromhex(name['raw_hex'])
    checked_layout = SimpleNamespace(
        person_count=fixture['person_count'], person_offset=0,
        name_counts=fixture['name_counts'],
        lookup=lambda ns, index: names.get((ns, index), b''),
        provenance=fixture['provenance'],
    )
    wire = struct.pack('<IBb', fixture['person_count'], 1, 1) + b''.join(bytes.fromhex(r['wire_hex']) for r in rows)
    actual = search_candidates(wire, checked_layout, [r['person_index'] for r in rows])
    assert len(actual) == 28
    for expected, result in zip(rows, actual):
        matches = [c for c in result['candidates'] if c['identity'] == expected['identity']
                   and c['name_indices'] == [n['index'] if n else -1 for n in expected['names']]]
        assert len(matches) == 1
        for source, decoded in zip(expected['names'], matches[0]['names']):
            assert decoded == (None if source is None else {'raw_hex': source['raw_hex'], 'text': source['text']})
        assert not result['evidence_scope']['certified_person_record']


def test_optional48_negative_second_count_is_native_failure_not_budget():
    child = b'\0' + struct.pack('<i', -1) + bytes(5)
    result, = search_candidates(component(record(7, common=body(optional=b'\1' + child))), layout(), [7])
    assert all(c['common_start'] != 6 for c in result['candidates'])
    assert result['search_complete']


def test_optional48_first_count_over_native_limit_is_rejected():
    child = bytes([126]) + bytes(126 * 16) + bytes(9)
    result, = search_candidates(component(record(7, common=body(optional=b'\1' + child))), layout(), [7])
    assert all(c['common_start'] != 6 for c in result['candidates'])


def test_large_checked_name_vector_does_not_drop_high_byte_indices():
    value = 0x01000001
    checked = layout()
    checked.name_counts['first'] = value + 1
    result, = search_candidates(component(record(7, common=body((value, 2, -1)))), checked, [7])
    assert result['candidates'][0]['name_indices'][0] == value


def test_layout_header_count_mismatch_is_integrity_error():
    with pytest.raises(ValueError, match='header count'):
        search_candidates(component(record(7)), layout(count=99), [7])


def test_raw_name_lookup_preserves_unsupported_utf8():
    checked = layout()
    checked.lookup_raw = lambda namespace, index: b'\xff'
    result, = search_candidates(component(record(7)), checked, [7])
    assert result['candidates'][0]['names'][0] == {'raw_hex': 'ff', 'text': None}


def test_name_output_budget_keeps_witness_identity_and_indices():
    result, = search_candidates(component(record(7)), layout(), [7], budget=SearchBudget(max_name_bytes=0))
    row, = result['candidates']
    assert row['identity']['stored_index'] == 7
    assert row['name_indices'] == [1, 2, -1]
    assert row['names'][0] == {'state': 'budget', 'raw_hex': None, 'text': None}
    assert result['state'] == 'budget'
    assert result['budget_reasons'] == ['name_output_bytes']


@pytest.mark.parametrize('marker', [2, 127, 128, 255])
@pytest.mark.parametrize('field', ['optional48', 'optional08'])
def test_unrepresentable_current_writer_presence_is_not_a_witness(marker, field):
    common = body(optional=bytes([marker])) if field == 'optional48' else body(tail=bytes([marker]))
    result, = search_candidates(component(record(7, common=common)), layout(), [7])
    assert all(c['common_start'] != 6 for c in result['candidates'])
    assert result['evidence_scope']['presence_profile'] == 'CEA86C_pointer_presence_normalized_0_or_1'
    assert result['evidence_scope']['future_or_legacy_writers'] == 'outside_supported_subset'
