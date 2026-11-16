"""Portable byte fixtures, independent scalar controls and package boundaries."""
import ast
from array import array
import builtins
import json
from pathlib import Path
import struct

import pytest
from fm_live_mcp.person_wire import parse_record
from fm_live_mcp.person_wire import _bindings, _regular_player

FIXTURES = json.loads(Path(__file__).with_name('person_wire_fixtures.json').read_bytes())


def rebase(value, delta):
    if isinstance(value, list):
        return [rebase(v, delta) for v in value]
    if isinstance(value, dict):
        return {k: v + delta if k in ('start', 'end', 'offset', 'source_offset', 'count_offset', 'rows_start', 'rows_end') and type(v) is int
                else rebase(v, delta) for k, v in value.items()}
    return value


@pytest.mark.parametrize('fixture', FIXTURES,
                         ids=lambda f: f"{f['filename']}:{f['original_ordinal']}")
def test_actual_records_preserve_absolute_spans_names_and_independent_ids(fixture):
    raw = bytes.fromhex(fixture['raw_hex'])
    prefix = b'prefix-source'
    data = prefix + raw + b'unread-next-record'
    row = parse_record(data, len(prefix), fixture['original_ordinal'], limit=len(prefix) + len(raw))
    expected = rebase(fixture['expected'], len(prefix) - fixture['source_tag_offset'])
    for key, value in expected.items():
        assert row[key] == value, key
    assert row['tag_offset'] == len(prefix)
    assert row['body_offset'] == len(prefix) + 1
    assert row['end'] == len(prefix) + len(raw)
    assert row['identity']['offset'] == row['end'] - 12
    assert {k: row['identity'][k] for k in fixture['identity']} == fixture['identity']
    assert 'parts' not in row


@pytest.mark.parametrize('tag', (1, 2, 3, 4, 5, 7, 8, 16, 18))
def test_every_truncation_of_a_complete_actual_type_fails_without_partial_success(tag):
    fixture = next(f for f in FIXTURES if f['expected']['signed_tag'] == tag)
    raw = bytes.fromhex(fixture['raw_hex'])
    for limit in range(len(raw)):
        with pytest.raises(ValueError):
            parse_record(raw, 0, fixture['original_ordinal'], limit=limit)


@pytest.mark.parametrize('tag', (-128, -1, 0, 17, 19, 127))
def test_unknown_tag_is_an_explicit_frontier_with_no_identity_or_extent(tag):
    row = parse_record(struct.pack('<b', tag), 0, 99, limit=1)
    assert row['state'] == 'unsupported' and row['signed_tag'] == tag
    assert row['ordinal'] == 99 and row['reason'] == 'unsupported_source_tag'
    assert 'end' not in row and 'identity' not in row


@pytest.mark.parametrize('kwargs', ({'tag_offset': True}, {'tag_offset': -1}, {'tag_offset': 1},
                                    {'ordinal': True}, {'ordinal': -1}, {'ordinal': 2_000_000},
                                    {'limit': True}, {'limit': -1}, {'limit': 2}))
def test_invalid_call_shapes_raise(kwargs):
    params = dict(tag_offset=0, ordinal=0, limit=1)
    params.update(kwargs)
    with pytest.raises(ValueError):
        parse_record(b'\x63', **params)


def test_nonbyte_noncontiguous_and_multidimensional_buffers_reject():
    for data in (None, 'text', memoryview(array('I', [1])), memoryview(b'abcdef')[::2],
                 memoryview(b'abcd').cast('B', shape=[2, 2])):
        with pytest.raises(ValueError):
            parse_record(data, 0, 0, limit=1)


def retired(selector=0, flags=0, raw20=2, raw28=3, native=0, secondary=0xffffffff):
    return bytes([16, selector]) + (struct.pack('<I', raw20) if selector == 0 else b'') + struct.pack(
        '<IQIII', raw28, flags, 7, native, secondary)


@pytest.mark.parametrize('selector,flags,routes', [
    (0, 0, [('first', 2, '0x20'), ('second', 3, '0x28')]),
    (0, 1 << 16, [('second', 2, '0x20'), ('first', 3, '0x28')]),
    (1, 1 << 29, [('common', 3, '0x28')]),
    (2, 1 << 30, [('common', 3, '0x28')]),
    (3, 1 << 31, [('second', 3, '0x28')]),
    (1, (1 << 29) | (1 << 30) | (1 << 31), [('common', 3, '0x28')]),
])
def test_retired_typed_namespaces_follow_final_flags_and_swap(selector, flags, routes):
    data = retired(selector, flags)
    row = parse_record(data, 0, 7, limit=len(data))
    assert [(r['namespace'], r['raw_index'], r['native_offset'])
            for r in row['retired_name_references']] == routes
    assert row['identity']['native_id_word'] == 0
    assert row['identity']['secondary_word'] == 0xffffffff
    assert row['retired_pointer_raw']['final_flags_u64'] == flags


@pytest.mark.parametrize('raw', (0x80000000, 0xffffffff))
def test_retired_signed_guard_preserves_raw_reference_and_native_null_state(raw):
    data = retired(raw20=raw)
    row = parse_record(data, 0, 7, limit=len(data))
    ref = row['retired_name_references'][0]
    assert ref['raw_index'] == raw and ref['state'] == 'native_null_reference'


def test_retired_selector_final_flags_mismatch_and_wrong_ordinal_reject():
    for data in (retired(selector=1, flags=0), retired(selector=0, flags=1 << 29)):
        with pytest.raises(ValueError):
            parse_record(data, 0, 7, limit=len(data))
    data = retired()
    with pytest.raises(ValueError):
        parse_record(data, 0, 8, limit=len(data))


def test_typed_unknown_child_is_unavailable_but_truncation_and_geometry_propagate(monkeypatch):
    def unknown(*args, **kwargs):
        raise _regular_player.UnsupportedPlayer('0x1234', 1, {}, 'Unimplemented native child')
    monkeypatch.setattr(_bindings, 'player', unknown)
    row = parse_record(b'\x02', 0, 0, limit=1)
    assert row['state'] == 'unsupported' and row['native_reader'] == '0x1234'
    assert 'identity' not in row and 'end' not in row
    def truncated(*args, **kwargs):
        raise _regular_player.UnsupportedPlayer('0x1234', 1, {}, 'Truncated child')
    monkeypatch.setattr(_bindings, 'player', truncated)
    with pytest.raises(ValueError):
        parse_record(b'\x02', 0, 0, limit=1)
    def invalid(*args, **kwargs):
        raise ValueError('unsupported A native slot capacity')
    monkeypatch.setattr(_bindings, 'player', invalid)
    with pytest.raises(ValueError):
        parse_record(b'\x02', 0, 0, limit=1)


def test_no_runtime_io_or_dynamic_imports_and_source_is_unchanged(monkeypatch):
    root = Path(__file__).parents[1] / 'fm_live_mcp/person_wire'
    for path in root.glob('*.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(a.name in ('struct', 'math', 'functools') for a in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.level == 1 or node.module in ('functools',)
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, 'attr', '')
                assert name not in ('open', 'read_bytes', 'read_text', 'write_bytes', 'write_text',
                                    'spec_from_file_location', 'exec_module', '__import__', 'eval', 'exec')
    fixture = next(f for f in FIXTURES if f['expected']['signed_tag'] == 1)
    data = bytearray.fromhex(fixture['raw_hex'])
    before = bytes(data)
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected runtime filesystem access')
    monkeypatch.setattr(builtins, 'open', forbidden)
    row = parse_record(data, 0, fixture['original_ordinal'], limit=len(data))
    assert row['state'] == 'decoded' and bytes(data) == before


def common_empty():
    return b''.join(struct.pack('<iB', -1, 0) for _ in range(3)) + struct.pack('<I', 0) + b'\0' * 38 + b'\0\0'


def canonical(index=7):
    return b'\0' * 8 + struct.pack('<III', index, 0, 1)


def test_virtual_optional_null_missing_and_present_zero_are_distinct():
    for flags, optional, present in ((0, b'', False), (512, struct.pack('<I', 0), True)):
        data = b'\x07' + struct.pack('<H4sHBI', flags, b'DATE', 0, 0, 0) + optional + canonical()
        row = parse_record(data, 0, 7, limit=len(data))
        assert row['native_fields']['0x08_u32_raw'] == 0
        assert row['optional_0c']['present'] is present
        assert row['optional_0c']['raw_word_u32'] == (0 if present else None)
        assert row['optional_0c']['end'] - row['optional_0c']['start'] == (4 if present else 0)
    data = b'\x08' + struct.pack('<IBB', 0, 0, 0) + common_empty() + canonical()
    row = parse_record(data, 0, 7, limit=len(data))
    assert 'optional_0c' not in row
    assert row['native_fields'] == {'0x68_raw_reference_word_u32': 0, '0x71_u8': 0, '0x70_u8': 0}


def test_agent_empty_vectors_keep_counts_and_bounded_payload_spans():
    data = b'\x12' + b'\0' * 11 + struct.pack('<III', 0, 0, 0) + b'\0' + common_empty() + canonical()
    row = parse_record(data, 0, 7, limit=len(data))
    for key in ('person_vector_summary', 'date_word_vector_summary'):
        assert row[key]['count'] == 0
        assert row[key]['rows_start'] == row[key]['rows_end']
        assert row[key]['payload_state'] == 'not_projected'
    assert row['nation_reference']['raw_word_u32'] == 0
    assert 'optional_0c' not in row
    assert 'raw_reference_words' not in row and 'date_word_vector' not in row


def test_form_envelope_checks_every_version_marker_and_exclusive_boundary():
    from fm_live_mcp.person_wire import _player_153e56c as form
    group = struct.pack('<BBII', 20, 1, 17, 2)
    basic = bytes([1]) + bytes(14)
    extended = bytes([1]) + bytes(13) + bytes([1, 3]) + bytes(38)
    wire = bytes([1]) + group + basic + extended + bytes(2)
    assert form.parse(wire, 0, child_readers={}) == {'start': 0, 'end': len(wire)}
    for cursor in range(len(wire)):
        with pytest.raises(ValueError):
            form.parse(wire[:cursor], 0, child_readers={})
    for at in (1, 2, 11, 25, 26, 40, 41, len(wire) - 2, len(wire) - 1):
        altered = bytearray(wire)
        altered[at] = 255
        with pytest.raises(ValueError):
            form.parse(altered, 0, child_readers={})
