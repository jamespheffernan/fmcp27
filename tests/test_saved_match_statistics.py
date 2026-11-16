from contextlib import contextmanager
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from fm_live_mcp import saved_match_statistics as query
from fm_live_mcp.saved_component_stream import Reader

PIN = 'a' * 64
FIXTURES = Path(__file__).parent / 'fixtures'
META = json.loads((FIXTURES / 'saved_match_statistics.json').read_text())


def raw(key=135195):
    return gzip.decompress((FIXTURES / f'saved_match_stats_{key}.bin.gz').read_bytes())


@pytest.mark.parametrize('key,goals,assists', [(135195, 1, 0), (132398, 0, 0), (129861, 0, 1)])
def test_three_independent_gordon_controls(key, goals, assists):
    value = query.decode_frame(raw(key), key, 13009)
    row, = value['player_rows']
    assert (row['goals'], row['assists']) == (goals, assists)
    assert value['source_state'] == 'available' and value['stored_player_row_count'] == 40
    assert value['coverage']['complete_side_sections']
    assert not value['coverage']['whole_payload_wire_parsed']
    assert value['appearance_state'] == value['completion_state'] == 'unresolved'


@pytest.mark.parametrize('key,person,goals,assists', [(135195, 11178, 2, 0), (129861, 33495, 1, 1)])
def test_independent_other_player_controls(key, person, goals, assists):
    row, = query.decode_frame(raw(key), key, person)['player_rows']
    assert (row['goals'], row['assists']) == (goals, assists)


def test_absent_person_is_unavailable_not_zero():
    value = query.decode_frame(raw(), 135195, 2147483647)
    assert value['source_state'] == 'unavailable'
    assert value['unavailable_reason'] == 'no_stored_player_row'
    assert value['player_rows'] == []


@pytest.mark.parametrize('key', [135195, 132398, 129861])
def test_full_frame_hash(key):
    data = raw(key)
    meta, = [m for m in META['frames'] if m['key'] == key]
    assert len(data) == meta['size'] and hashlib.sha256(data).hexdigest() == meta['sha256']


def test_wrong_key_and_unsupported_versions_fail():
    with pytest.raises(ValueError, match='inner key'):
        query.decode_frame(raw(), 135196, 13009)
    for offset in (0, 1, 2, 3, 4):
        data = bytearray(raw()); data[offset] = 255
        with pytest.raises(ValueError):
            query.decode_frame(bytes(data), 135195, 13009)


def test_duplicate_person_rows_fail_even_with_equal_values():
    data = bytearray(raw())
    other = META['frames'][0]['other_subject_row']
    assert data[other['start']] == 2
    struct.pack_into('<I', data, other['start'] + 1, 13009)
    with pytest.raises(ValueError, match='multiple retained player-stat rows'):
        query.decode_frame(bytes(data), 135195, 13009)


def test_later_side_corruption_never_publishes_earlier_gordon():
    data = raw()
    result = query.decode_frame(data, 135195, 13009)
    # Both sides are required even though Gordon is in side0; every truncation
    # after his row and before complete side1 must fail.
    selected = META['frames'][0]['Gordon']
    for end in range(selected['end'], result['coverage']['parsed_until']):
        with pytest.raises((ValueError, IndexError)):
            query.decode_frame(data[:end], 135195, 13009)


@pytest.fixture
def source(monkeypatch):
    class Source(io.BytesIO):
        @property
        def finished(self):
            return self.tell() == len(self.getbuffer())
    def setup(entries=None, keys=None):
        selected = raw()
        component = b'packed-frame'
        e = SimpleNamespace(path='root/match_stats_cfg.dat', start=0, compressed_size=12, uncompressed_size=12)
        @contextmanager
        def checked(filename, directory=None):
            yield io.BytesIO(b'\0' * 26 + component), [e] if entries is None else entries, {'pin': PIN}
        @contextmanager
        def opened(handle, entry):
            yield Reader(Source(component), len(component))
        monkeypatch.setattr(query.snapshot_catalog, 'checked_snapshot', checked)
        monkeypatch.setattr(query.snapshot_catalog, 'snapshot_id', lambda i: i['pin'])
        monkeypatch.setattr(query.saved_component_stream, 'open_component', opened)
        monkeypatch.setattr(query, 'expand_frame', lambda p: selected)
        rows = [{'ordinal': i, 'key_i32': k, 'offset': 0, 'length': len(component)} for i, k in enumerate(keys if keys is not None else [135195])]
        monkeypatch.setattr(query, '_index', lambda h, e: {'manager28_present': False, 'containers': [{'container_ordinal': 0, 'payload_start': 0, 'indices': rows}]})
    return setup


def call(**kw):
    args = dict(filename='sample.fm', fixture_key=135195, person_index=13009, expected_snapshot_id=PIN)
    args.update(kw)
    return query.get_player_statistics(**args)


def test_source_query_available_missing_and_duplicate_key(source):
    source()
    assert call()['player_rows'][0]['goals'] == 1
    source(keys=[])
    missing = call()
    assert missing['unavailable_reason'] == 'no_retained_match_key' and missing['stored_player_row_count'] is None
    source(keys=[135195, 135195])
    with pytest.raises(ValueError, match='multiple physical'):
        call()


def test_stale_pin_and_component_mutation(source, monkeypatch):
    source()
    with pytest.raises(ValueError, match='snapshot identity'):
        call(expected_snapshot_id='b' * 64)
    hashes = iter(['a', 'b'])
    monkeypatch.setattr(query, '_packed_hash', lambda h, e: next(hashes))
    with pytest.raises(ValueError, match='changed during'):
        call()


@pytest.mark.parametrize('kwargs', [{'fixture_key': True}, {'fixture_key': -1}, {'person_index': True}, {'person_index': 2**31}, {'expected_snapshot_id': ''}, {'expected_snapshot_id': 'A' * 64}, {'filename': '../sample.fm'}])
def test_invalid_selectors_before_source(kwargs, monkeypatch):
    monkeypatch.setattr(query.snapshot_catalog, 'checked_snapshot', lambda *a, **k: pytest.fail('source touched'))
    with pytest.raises(ValueError):
        call(**kwargs)


def index_bytes(payload=b'frame', *, offset=0, length=None):
    key = 135195
    length = len(payload) if length is None else length
    header = bytes.fromhex('03017461642e0600') + struct.pack('<I', 0)
    vector = b'\1' + struct.pack('<I', 1)
    row = (struct.pack('<II', 0, 0) + struct.pack('<I', 0) + b'\1\1'
           + struct.pack('<I', 1) + struct.pack('<III', key, offset, length)
           + struct.pack('<IIBi', 0, 0, 3, len(payload)) + payload + b'\1')
    return header + b'\1' + vector + row


def test_storage_index_exact_extents_and_every_truncation():
    data = index_bytes()
    parsed = query.index_wire.parse(Reader(io.BytesIO(data), len(data)), manager28_present=False)
    row, = parsed['containers'][0]['indices']
    assert row == {'ordinal': 0, 'key_u32': 135195, 'key_i32': 135195, 'offset': 0, 'length': 5}
    assert parsed['end'] == len(data)
    for end in range(len(data)):
        with pytest.raises(ValueError):
            query.index_wire.parse(Reader(io.BytesIO(data[:end]), end), manager28_present=False)
    for bad in (index_bytes(offset=1), index_bytes(length=6), data+b'x'):
        with pytest.raises(ValueError):
            query.index_wire.parse(Reader(io.BytesIO(bad), len(bad)), manager28_present=False)


def test_storage_profile_budget_is_unresolved_not_an_exclusion(monkeypatch):
    def parse(reader, *, manager28_present):
        if manager28_present:
            raise query.index_wire.BudgetError('unresolved budget')
        return {'containers': []}
    @contextmanager
    def opened(*a):
        class S(io.BytesIO):
            finished = True
        yield Reader(S(b''), 0)
    monkeypatch.setattr(query.saved_component_stream, 'open_component', opened)
    monkeypatch.setattr(query.index_wire, 'parse', parse)
    with pytest.raises(ValueError, match='unresolved budget'):
        query._index(None, None)


def test_all48_independent_person_form_source_controls():
    frames = {key: raw(key) for key in (135195, 132398, 129861)}
    controls = META['independent_form_controls']
    assert len(controls) == 48
    for expected in controls:
        value = query.decode_frame(frames[expected['key']], expected['key'], expected['person_index'])
        row, = value['player_rows']
        assert (row['goals'], row['assists']) == (expected['goals'], expected['assists'])
        assert value['appearance_state'] == 'unresolved'


@pytest.mark.parametrize('offset', [13, 30, 31, 56, 66])
def test_indexed_storage_unknown_versions_or_modes_fail(offset, monkeypatch):
    data = bytearray(index_bytes()); data[offset] = 255
    class Source(io.BytesIO):
        @property
        def finished(self):
            return self.tell() == len(self.getbuffer())
    @contextmanager
    def opened(*a):
        yield Reader(Source(bytes(data)), len(data))
    monkeypatch.setattr(query.saved_component_stream, 'open_component', opened)
    with pytest.raises(ValueError):
        query._index(None, None)
