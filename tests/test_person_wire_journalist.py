"""Typed JOURNALIST fixtures from four independently checked source snapshots."""
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp.person_wire import parse_record
from fm_live_mcp.person_wire import _person_tag6

FIXTURES = json.loads(Path(__file__).with_name('person_wire_journalist_fixtures.json').read_bytes())


@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda f: f"{f['filename']}:{f['original_ordinal']}")
def test_actual_journalists_keep_identity_name_and_absolute_extent(fixture):
    raw = bytes.fromhex(fixture['raw_hex'])
    prefix = b'checked-prefix'
    data = memoryview(prefix + raw + b'next-record-not-consumed')
    end = len(prefix) + len(raw)
    row = parse_record(data, len(prefix), fixture['original_ordinal'], limit=end)
    assert row['state'] == 'decoded' and row['source_record_kind'] == 'JOURNALIST'
    assert row['tag_offset'] == len(prefix) and row['end'] == end
    assert row['identity']['offset'] == end - 12
    assert {key: row['identity'][key] for key in fixture['identity']} == fixture['identity']
    assert row['names'] == fixture['name_references']
    assert row['native_fields']['native70_72_73_raw_hex'] == raw[1:4].hex()
    assert row['native_fields']['local_reference_word_u32'] == struct.unpack_from('<I', raw, 4)[0]
    assert row['reference_conditions']['class_local'] == 'conditional_direct32_local1'
    assert row['reference_conditions']['ambient_loader_globals_observed'] is False
    assert 'ambient native globals unobserved' in row['source_profile']


@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda f: f"{f['filename']}:{f['original_ordinal']}")
def test_every_actual_truncation_refuses_complete_record(fixture):
    raw = bytes.fromhex(fixture['raw_hex'])
    for limit in range(len(raw)):
        with pytest.raises(ValueError):
            parse_record(raw, 0, fixture['original_ordinal'], limit=limit)


def test_mismatched_identity_and_common_writer_markers_reject():
    fixture = FIXTURES[0]
    raw = bytearray.fromhex(fixture['raw_hex'])
    struct.pack_into('<I', raw, len(raw) - 12, fixture['original_ordinal'] + 1)
    with pytest.raises(ValueError, match='ordinal'):
        parse_record(raw, 0, fixture['original_ordinal'], limit=len(raw))
    raw = bytes.fromhex(fixture['raw_hex'])
    body = _person_tag6.parse(raw, 1, ordinal=fixture['original_ordinal'])
    marker_at = body['parts']['common']['prefix']['end'] - 1
    mutated = bytearray(raw)
    mutated[marker_at] = 2
    with pytest.raises(ValueError, match='presence'):
        parse_record(mutated, 0, fixture['original_ordinal'], limit=len(raw))


@pytest.mark.parametrize('kwargs', [
    {'source_major': 3753}, {'minor': 8}, {'reference_mode': 'raw32'},
    {'local_reference_profile': 'index16_local1'}, {'source_major': True},
    {'start': True}, {'limit': True}, {'ordinal': True},
])
def test_unproved_or_malformed_class_context_is_not_reinterpreted(kwargs):
    fixture = FIXTURES[0]
    raw = bytes.fromhex(fixture['raw_hex'])
    params = dict(start=1, ordinal=fixture['original_ordinal'])
    params.update(kwargs)
    with pytest.raises(ValueError):
        _person_tag6.parse(raw, **params)
