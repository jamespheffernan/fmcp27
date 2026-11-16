"""Real compressed archive transport, typed PLAYER and canonical INJURY fixtures."""
from dataclasses import dataclass
from io import BytesIO
import json
import os
from pathlib import Path
import struct

import pytest
from fm_live_mcp import (saved_player_injury_history as query_module,
                        saved_injury_history_records as codec,
                        saved_fixed_history_index as fixed,
                        saved_population as population, snapshot_catalog)
from fm_live_mcp.person_wire import parse_record
from fm_live_mcp.saved_component_stream import Reader
import test_saved_competition_state as archive_builder
from test_saved_world_search import world_database, framed

FIXTURES = json.loads(Path(__file__).with_name('person_wire_fixtures.json').read_bytes())

@dataclass(frozen=True)
class Layout:
    _data: object
    person_offset: int
    person_records_offset: int
    person_count: int = 1
    provenance: str = 'fixture original PERSON header following canonical INJURY table'
    @property
    def name_counts(self): return {'first': 0, 'second': 0, 'common': 0}


def player(owner=0):
    f = next(f for f in FIXTURES if f['expected']['signed_tag'] == 2)
    raw = bytearray.fromhex(f['raw_hex'])
    raw[-12:-8] = bytes(4)
    row = parse_record(raw, 0, 0, limit=len(raw))
    at = codec.owner(raw, row)['source_offset']
    raw[at:at + 4] = struct.pack('<i', owner)
    return bytes(raw)


def injury(index, native, secondary=0):
    return b'\0' + bytes(35) + struct.pack('<III', index, native, secondary)


def stored(injury_index=0, day=1, year=2030, *, raw_date=None):
    date = year << 16 | day if raw_date is None else raw_date
    return struct.pack('<hiBBIHBB', injury_index, -1, 1, 2, date, 0xffff, 255, 128)


def index(offsets=(0, 16, 16)):
    previous = 0
    encoded = []
    for value in offsets:
        previous = ((value - previous + 2**31) % 2**32) - 2**31
        encoded.append(previous)
    vector = lambda x: struct.pack('<I', len(x)) + b''.join(struct.pack('<i', v) for v in x)
    return (fixed.LIST_HEADER + vector(()) + struct.pack('<I', 1) + vector(encoded) +
            vector((0,) if not offsets else ()) + struct.pack('<IH', 16, 2))


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(population, '_LAST_LAYOUT', None)
    population._PREFIXES.clear()
    yield
    population._PREFIXES.clear()


def save(tmp_path, monkeypatch, *, owner=0, offsets=(0, 16, 16), ls=None, dt=None,
         injuries=None, missing=(), name='injuries.fm', record=None, person_count=1):
    prefix = world_database() + framed([injury(0, 41), injury(1, 42, 19)] if injuries is None else injuries)
    source = prefix + struct.pack('<IB', person_count, 1) + (player(owner) if record is None else record) + bytes(9)
    monkeypatch.setattr(population.saved_name_vectors, 'locate', lambda data: Layout(data, len(prefix), len(prefix) + 5, person_count))
    monkeypatch.setattr(archive_builder, 'world_database', lambda _: source)
    members = {'injury_histories_ls.dat': index(offsets) if ls is None else ls,
               'injury_histories_dt.cmt': b'\x03\x01tmc.\x02\0' + stored() + stored(1, 20) if dt is None else dt}
    for member in missing: del members[member]
    path = archive_builder.archive(tmp_path / name, [], members)
    pin = snapshot_catalog.inspect_snapshot(path.name, directory=tmp_path, limit=1)['snapshot_id']
    return path, pin


def query(source, **kwargs):
    path, pin = source
    return query_module.get_injury_history(path.name, 0, pin, directory=path.parent, **kwargs)


def test_typed_owner_canonical_ids_and_duplicate_order(tmp_path, monkeypatch):
    r = query(save(tmp_path, monkeypatch))
    assert r['state'] == 'available' and r['total_indexed_entries'] == 3
    assert [row['entry_index'] for row in r['rows']] == [0, 1, 2]
    assert [row['native_offset'] for row in r['rows']] == [0, 16, 16]
    assert [row['injury_reference']['identity']['native_id'] for row in r['rows']] == [41, 42, 42]
    assert r['rows'][0]['injury_reference']['identity']['secondary_id'] == 0
    assert r['owner']['source_field'] == 'PLAYER+0x200'
    assert r['person']['identity']['stored_index'] == 0
    assert r['rows'][0]['unmapped_fields']['native_0xA_unsigned16'] == 65535
    assert r['current_availability'] == {'state': 'not_assessed_by_history_source', 'value': None}
    assert set(r['components']) == {'game_db.dat', 'injury_histories_ls.dat', 'injury_histories_dt.cmt'}
    assert all(c['state'] == 'complete_frame_and_packed_bytes_rechecked' for c in r['components'].values())


def test_filters_before_page_same_pin_and_empty_filter(tmp_path, monkeypatch):
    source = save(tmp_path, monkeypatch)
    a = query(source, date_from='2030-01-20', date_to='2030-01-20', injury_native_ids=[42], limit=1)
    b = query(source, date_from='2030-01-20', injury_native_ids=[42], offset=a['next_offset'], limit=1)
    assert a['selected_row_count'] == b['selected_row_count'] == 2
    assert [a['rows'][0]['entry_index'], b['rows'][0]['entry_index']] == [1, 2]
    assert b['next_offset'] is None
    r = query(source, injury_native_ids=[999])
    assert r['state'] == 'available' and r['selected_row_count'] == 0 and r['known_excluded_count'] == 3


@pytest.mark.parametrize('owner,offsets,state', [(-1, (0,), 'no_history_index'), (-10, (0,), 'no_history_index'), (0, (), 'available_empty'), (1, (0,), 'unavailable')])
def test_absent_empty_outside_distinctions(tmp_path, monkeypatch, owner, offsets, state):
    r = query(save(tmp_path, monkeypatch, owner=owner, offsets=offsets))
    assert r['state'] == state and r['rows'] == []
    assert r['selected_row_count'] is None if owner == 1 else r['selected_row_count'] == 0


def test_missing_source_is_unavailable_not_empty(tmp_path, monkeypatch):
    r = query(save(tmp_path, monkeypatch, missing=('injury_histories_dt.cmt',)))
    assert r['state'] == 'unavailable' and r['total_indexed_entries'] is None
    assert r['missing_components'] == ['injury_histories_dt.cmt']


def test_unknowns_and_known_failure_before_unknown(tmp_path, monkeypatch):
    dt = b'\x03\x01tmc.\x02\0' + stored(0, raw_date=0) + stored(-1) + stored(9)
    source = save(tmp_path, monkeypatch, offsets=(0, 16, 32), dt=dt)
    r = query(source)
    assert r['selected_row_count'] == 3 and r['rows'][0]['stored_date']['value'] is None
    assert r['rows'][1]['injury_reference']['state'] == 'native_null_reference'
    assert r['rows'][2]['injury_reference']['state'] == 'outside_same_snapshot_table'
    r = query(source, date_from='2030-01-01', injury_native_ids=[42])
    assert r['known_excluded_count'] == 1 and r['filter_unknown_count'] == 2
    assert r['selected_row_count'] == 0


def test_negative_offsets_are_skipped_after_reconstruction(tmp_path, monkeypatch):
    r = query(save(tmp_path, monkeypatch, offsets=(-1, 0, -1)))
    assert r['total_indexed_entries'] == 3 and r['decoded_row_count'] == 1
    assert len(r['skipped_entries']) == 2 and r['rows'][0]['entry_index'] == 1


@pytest.mark.parametrize('kw', [{'date_from': '20300101'}, {'date_to': '2030-02-29'}, {'date_to': '2201-01-01'}, {'date_from': '2030-01-02', 'date_to': '2030-01-01'}, {'injury_native_ids': []}, {'injury_native_ids': [True]}, {'injury_native_ids': [1 << 32]}, {'offset': True}, {'limit': 201}])
def test_validation_before_file_access(kw):
    with pytest.raises(ValueError): query_module.get_injury_history('missing.fm', 0, 'pin', **kw)


@pytest.mark.parametrize('field', ['ls_tail', 'dt_header', 'dt_extent', 'offset', 'definition_ordinal'])
def test_late_malformed_source_does_not_publish_cache(tmp_path, monkeypatch, field):
    kw = {'ls': index() + b'x'} if field == 'ls_tail' else {'dt': b'wronghdr' + stored()} if field == 'dt_header' else {'dt': b'\x03\x01tmc.\x02\0' + b'x'} if field == 'dt_extent' else {'offsets': (1,)} if field == 'offset' else {'injuries': [injury(1, 41)]}
    with pytest.raises(ValueError): query(save(tmp_path, monkeypatch, **kw))
    assert not population._PREFIXES and population._LAST_LAYOUT is None


def test_stale_archive_and_final_change_do_not_publish(tmp_path, monkeypatch):
    source = save(tmp_path, monkeypatch)
    read = query_module.fixed.read_rows
    def changed(reader, offsets, **kw):
        out = read(reader, offsets, **kw)
        st = source[0].stat()
        os.utime(source[0], ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        return out
    monkeypatch.setattr(query_module.fixed, 'read_rows', changed)
    with pytest.raises(ValueError, match='changed'): query(source)
    assert not population._PREFIXES and population._LAST_LAYOUT is None


def test_trailing_compressed_bytes_reject_even_no_filter_matches(tmp_path, monkeypatch):
    compress = archive_builder.compress
    monkeypatch.setattr(archive_builder, 'compress', lambda raw: compress(raw) + (b'x' if raw.startswith(b'\x03\x01tmc.') else b''))
    source = save(tmp_path, monkeypatch)
    with pytest.raises(ValueError): query(source, injury_native_ids=[999])
    assert not population._PREFIXES


def test_unsupported_class_is_not_absent(tmp_path, monkeypatch):
    f = next(f for f in FIXTURES if f['expected']['signed_tag'] == 16)
    raw = bytearray.fromhex(f['raw_hex']); raw[-12:-8] = bytes(4)
    r = query(save(tmp_path, monkeypatch, record=bytes(raw)))
    assert r['state'] == 'unavailable' and r['owner'] is None and r['selected_row_count'] is None
    assert set(r['components']) == {'game_db.dat'}


def test_generic_index_profile_is_not_specific_to_injuries():
    for width, version in [(16, 2), (40, 4), (168, 7)]:
        raw = fixed.LIST_HEADER + struct.pack('<IIII', 0, 1, 1, 0) + struct.pack('<IIH', 0, width, version)
        r = Reader(BytesIO(raw), len(raw))
        offsets, summary = fixed.read_index(r, 0, width=width, data_version=version)
        assert offsets == [0] and summary['record_width'] == width
        raw = b'\x03\x01tmc.' + struct.pack('<H', version) + bytes(width)
        r = Reader(BytesIO(raw), len(raw))
        assert fixed.read_rows(r, offsets, width=width, data_version=version) == {0: bytes(width)}


def test_identical_query_advances_only_original_prefix_then_rechecks_selected_owner(tmp_path, monkeypatch):
    first = player(0)
    second = bytearray(first)
    second[-12:-8] = struct.pack('<I', 1)
    source = save(tmp_path, monkeypatch, record=first + second, person_count=2)
    monkeypatch.setattr(query_module, 'MAX_ADVANCE', 1)
    path, pin = source
    early = query_module.get_injury_history(path.name, 1, pin, directory=tmp_path)
    assert early['state'] == 'stopped' and early['selected_row_count'] is None
    assert early['PERSON_coverage']['retry_same_query_to_advance'] is True
    assert set(early['components']) == {'game_db.dat'}
    final = query_module.get_injury_history(path.name, 1, pin, directory=tmp_path)
    assert final['state'] == 'available' and final['person']['ordinal'] == 1
    assert final['owner']['source_field'] == 'PLAYER+0x200'
    assert final['PERSON_coverage']['footer']['state'] == 'source_footer_read'
