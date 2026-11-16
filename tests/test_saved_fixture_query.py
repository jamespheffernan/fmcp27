from contextlib import contextmanager
import io
from types import SimpleNamespace

import pytest

from fm_live_mcp import saved_fixture_query as query
from fm_live_mcp.saved_component_stream import Reader
from test_saved_fixture_records import manager,fixture,result

PIN = 'a' * 64


class Source(io.BytesIO):
    @property
    def finished(self):
        return self.tell() == len(self.getbuffer())


@pytest.fixture
def fake_source(monkeypatch):
    query._CACHE.clear()
    selected = []
    def setup(data):
        @contextmanager
        def archive(filename, pin, directory):
            assert filename == 'sample.fm' and pin == PIN
            yield None, {'filename': filename, 'snapshot_id': PIN}, None, [SimpleNamespace(path='root/rgman/fix_man.dat')]
        @contextmanager
        def component(handle, entry):
            yield Reader(Source(data), len(data))
        def canonical(db, rows, index, maximum, *, cache_rows=None):
            assert index == 7 and maximum in (-1, 8)
            selected.extend(rows)
            for row in rows + (cache_rows or []):
                row['teams'] = [{'database_index': ref['database_index']} for ref in row['team_references']]
            return {'database_index': index}, 10
        @contextmanager
        def checked(filename, directory=None):
            yield None, (), {'fixture_test_pin': PIN}
        monkeypatch.setattr(query.snapshot_catalog, 'checked_snapshot', checked)
        monkeypatch.setattr(query.snapshot_catalog, 'snapshot_id', lambda identity: identity['fixture_test_pin'])
        monkeypatch.setattr(query.saved_database, 'open_archive_at_clubs', archive)
        monkeypatch.setattr(query.saved_component_stream, 'open_component', component)
        monkeypatch.setattr(query, '_canonical', canonical)
        return selected
    return setup


def call(**kw):
    return query.find_fixture_results('sample.fm', 7, '2030-01-01', '2030-01-01', expected_snapshot_id=PIN, **kw)


def test_inclusive_native_date_and_duplicate_stable_pagination(fake_source):
    records = [(0, 1, result()), (0, 1, result()), (1, 0, fixture(date=0x07ee0002, other=0x07ee0001)), (2, 0, fixture())]
    fake_source(manager(records))
    r = call(offset=1, limit=1)
    assert r['matched_count'] == 3 and r['next_offset'] == 2
    assert r['rows'][0]['original_group_row'] == 1 and r['rows'][0]['match_ordinal'] == 1
    assert r['coverage']['component']['full_frame_validated']
    assert not r['coverage']['full_save_absence_proved']
    assert r['coverage']['historical']['state'] == 'not_searched'
    assert r['rows'][0]['completion_state'] == 'unresolved'
    assert call(offset=3)['rows'] == []
    bare = call(offset=2)['rows'][0]
    assert bare['score_channels'] is None and bare['source_class'] == 'FIXTURE'


def test_present_empty_retained_scope_does_not_claim_history_absence(fake_source):
    fake_source(manager())
    r = call()
    assert r['matched_count'] == 0 and r['rows'] == []
    assert r['coverage']['historical']['absence_proved'] is False


@pytest.mark.parametrize('args', [
    {'team_index': True}, {'team_index': -1}, {'date_from': '20300101'},
    {'date_to': '2029-12-31'}, {'date_to': '2030-02-30'}, {'expected_snapshot_id': ''},
    {'expected_snapshot_id': 'A' * 64}, {'include_competition': 1}, {'include_historical': 'yes'},
    {'offset': True}, {'limit': 0}, {'limit': 501}, {'filename': '../sample.fm'},
])
def test_bad_selectors_fail_before_source_open(args, monkeypatch):
    query._CACHE.clear()
    def fail(*a, **kw):
        pytest.fail('Invalid query attempted source access')
    monkeypatch.setattr(query.saved_database, 'open_archive_at_clubs', fail)
    values = dict(filename='sample.fm', team_index=7, date_from='2030-01-01', date_to='2030-01-01', expected_snapshot_id=PIN)
    values.update(args)
    with pytest.raises(ValueError):
        query.find_fixture_results(**values)


def test_broken_fixture_never_publishes_a_partial_result(fake_source):
    fake_source(manager([(0, 1, result())])[:-3])
    with pytest.raises(ValueError):
        call()


def test_serialized_response_budget_is_checked(fake_source, monkeypatch):
    fake_source(manager([(0, 1, result())]))
    monkeypatch.setattr(query, 'MAX_RESPONSE_BYTES', 1)
    with pytest.raises(ValueError, match='response budget'):
        call()


def test_opt_in_historical_unavailable_is_not_empty_present_scope(fake_source, monkeypatch):
    from fm_live_mcp import saved_fixture_archive
    fake_source(manager())
    monkeypatch.setattr(saved_fixture_archive, 'read_historical', lambda reader, callback: {
        'state': 'unavailable', 'unavailable_reason': 'no_serialized_archive_tail',
        'scanned_records': 0, 'complete_source': False, 'next_cursor': None})
    r = call(include_historical=True)
    assert r['matched_count'] == 0
    assert r['matched_count_is_complete_for_requested_scope'] is False
    assert r['coverage']['historical']['state'] == 'unavailable'


def test_opt_in_historical_budget_never_publishes_full_match_count(fake_source, monkeypatch):
    from fm_live_mcp import saved_fixture_archive
    fake_source(manager())
    monkeypatch.setattr(saved_fixture_archive, 'read_historical', lambda reader, callback: {
        'next_cursor': {'frame_offset': 1, 'row_offset': 0}})
    with pytest.raises(ValueError, match='scan budget exhausted'):
        call(include_historical=True)


def test_competition_provider_batches_indices_once_and_checks_pin(fake_source, monkeypatch):
    from fm_live_mcp import saved_fixture_name_lookup
    fake_source(manager([(0, 1, result()), (1, 0, fixture())]))
    calls = []
    def lookup(filename, indices, **kw):
        calls.append((filename, indices, kw))
        return {'snapshot_id': PIN, 'table': {'scope': 'structural conjunction'},
                'rows': [{'database_index': 3, 'native_id': 90, 'primary_competition': {'native_id': 11}}]}
    monkeypatch.setattr(saved_fixture_name_lookup, 'load_fixture_name_lookup', lookup)
    r = call(include_competition=True)
    assert len(calls) == 1 and calls[0][1] == [3]
    assert all(row['fixture_name']['primary_competition']['native_id'] == 11 for row in r['rows'])
    query._CACHE.clear()
    monkeypatch.setattr(saved_fixture_name_lookup, 'load_fixture_name_lookup', lambda *a, **kw: {'snapshot_id': 'b'*64})
    with pytest.raises(ValueError, match='snapshot mismatch'):
        call(include_competition=True)


def test_historical_rows_append_in_scope_order_without_deduplication(fake_source, monkeypatch):
    from fm_live_mcp import saved_fixture_archive,saved_fixture_records
    from test_saved_fixture_records import reader
    fake_source(manager([(0, 1, result())]))
    def historical(stream, callback):
        row = saved_fixture_records.read_record(reader(result()), True)
        callback({**row, 'container': 'historical_0', 'original_group_row': 0,
                  'source_offset_space': 'historical_frame_decompressed'})
        return {'state': 'available', 'complete_source': True, 'scanned_records': 1, 'next_cursor': None}
    monkeypatch.setattr(saved_fixture_archive, 'read_historical', historical)
    r = call(include_historical=True)
    assert r['matched_count'] == 2
    assert [row['container'] for row in r['rows']] == ['initial', 'historical_0']
    assert r['rows'][0]['record_sha256'] == r['rows'][1]['record_sha256']
    assert r['matched_count_is_complete_for_requested_scope'] is True
    assert r['coverage']['total_scanned_records'] == 2


def test_cached_pages_recheck_pin_and_return_independent_objects(fake_source, monkeypatch):
    fake_source(manager([(0, 1, result()), (1, 0, fixture())]))
    first = call(limit=1)
    assert len(query._CACHE) == 1
    first['rows'][0]['teams'][0]['database_index'] = 999
    checks = []
    @contextmanager
    def checked(filename, directory=None):
        checks.append('enter')
        yield None, (), {'fixture_test_pin': PIN}
        checks.append('exit')
    monkeypatch.setattr(query.snapshot_catalog, 'checked_snapshot', checked)
    def heavy(*a, **kw):
        pytest.fail('Cache hit repeated a source scan')
    monkeypatch.setattr(query.saved_database, 'open_archive_at_clubs', heavy)
    second = call(offset=1, limit=1)
    assert second['rows'][0]['original_group_row'] == 1
    assert second['matched_count'] == 2 and second['next_offset'] is None
    again = call(limit=1)
    assert again['rows'][0]['teams'][0]['database_index'] == 7
    assert checks == ['enter', 'exit', 'enter', 'exit']
    assert first['coverage'] == second['coverage']


def test_cache_stale_pin_or_changed_source_exit_invalidates(fake_source, monkeypatch):
    fake_source(manager([(0, 1, result())]))
    call()
    @contextmanager
    def changed(filename, directory=None):
        yield None, (), {'fixture_test_pin': 'b'*64}
    monkeypatch.setattr(query.snapshot_catalog, 'checked_snapshot', changed)
    with pytest.raises(ValueError, match='identity changed'):
        call()
    assert not query._CACHE
    # A change detected after reading must also prevent cached publication.
    fake_source(manager([(0, 1, result())]));call()
    @contextmanager
    def changed_at_exit(filename, directory=None):
        yield None, (), {'fixture_test_pin': PIN}
        raise ValueError('Snapshot changed during request')
    monkeypatch.setattr(query.snapshot_catalog, 'checked_snapshot', changed_at_exit)
    with pytest.raises(ValueError, match='changed during'):
        call()
    assert not query._CACHE


def test_cache_preserves_unavailable_history_and_empty_result(fake_source, monkeypatch):
    from fm_live_mcp import saved_fixture_archive
    fake_source(manager())
    monkeypatch.setattr(saved_fixture_archive, 'read_historical', lambda *a: {
        'state': 'unavailable', 'entry_count': None, 'scanned_records': 0,
        'complete_source': False, 'next_cursor': None})
    first = call(include_historical=True)
    second = call(include_historical=True, offset=10)
    assert first['coverage'] == second['coverage']
    assert second['coverage']['historical']['entry_count'] is None
    assert second['rows'] == [] and second['matched_count'] == 0
    assert second['matched_count_is_complete_for_requested_scope'] is False


def test_cache_does_not_cross_historical_or_competition_selection(fake_source, monkeypatch):
    from fm_live_mcp import saved_fixture_archive,saved_fixture_name_lookup
    fake_source(manager([(0, 1, result())]));call()
    history_calls = []
    monkeypatch.setattr(saved_fixture_archive, 'read_historical', lambda *a: history_calls.append(1) or {
        'state': 'available', 'complete_source': True, 'scanned_records': 0, 'next_cursor': None})
    call(include_historical=True)
    assert history_calls == [1]
    names = []
    monkeypatch.setattr(saved_fixture_name_lookup, 'load_fixture_name_lookup', lambda *a, **kw: names.append(1) or {
        'snapshot_id': PIN, 'table': {}, 'rows': [{'database_index': 3, 'state': 'resolved_structural_source'}]})
    r = call(include_competition=True)
    assert names == [1] and r['rows'][0]['fixture_name']['state'] == 'resolved_structural_source'
    assert len(query._CACHE) == query.MAX_CACHE_ENTRIES


def test_cache_row_and_byte_limits_keep_cold_page_path(fake_source, monkeypatch):
    fake_source(manager([(0, 1, result())] * 3))
    monkeypatch.setattr(query, 'MAX_CACHED_ROWS', 2)
    r = call(limit=1)
    assert r['matched_count'] == 3 and len(r['rows']) == 1 and not query._CACHE
    monkeypatch.setattr(query, 'MAX_CACHED_ROWS', 500)
    monkeypatch.setattr(query, 'MAX_CACHE_ENTRY_BYTES', 1)
    assert len(call(limit=1)['rows']) == 1 and not query._CACHE


def test_cache_lru_and_serialized_total_bound(fake_source):
    fake_source(manager([(0, 1, result())]))
    for year in (2028, 2029, 2030):
        query.find_fixture_results('sample.fm', 7, f'{year}-01-01', '2030-01-01', expected_snapshot_id=PIN)
    assert len(query._CACHE) == 2
    assert all(len(blob) <= query.MAX_CACHE_ENTRY_BYTES for blob in query._CACHE.values())
    assert sum(map(len, query._CACHE.values())) <= query.MAX_CACHE_ENTRY_BYTES * query.MAX_CACHE_ENTRIES
    assert all(key[4] != '2028-01-01' for key in query._CACHE)


def test_optional_prefetch_identity_failure_does_not_break_original_page(monkeypatch):
    team = dict(database_index=7, native_id=99, secondary_id=99, team_type_code=0,
                owner_kind='club', owner_index=None, name='', short_name='')
    monkeypatch.setattr(query.saved_database, 'table', lambda reader, label, decode: iter([] if label == 'CLUB' else [dict(team, database_index=i) for i in range(8)]))
    monkeypatch.setattr(query.saved_squad_tables, 'reach_teams_after_clubs', lambda reader: None)
    page = {'team_references': [{'database_index': 7, 'identity_word': 99}]}
    prefetch = [page, {'team_references': [{'database_index': 7, 'identity_word': 123}]}]
    result, count = query._canonical(None, [page], 7, 7, cache_rows=prefetch)
    assert result['native_id'] == 99 and count == 8 and prefetch == []


def test_prefetch_never_adds_competition_requirement_to_empty_or_null_page(fake_source, monkeypatch):
    from fm_live_mcp import saved_fixture_name_lookup
    null = bytearray(fixture());null[1:5] = b'\xff'*4
    fake_source(manager([(0, 0, bytes(null)), (1, 0, fixture())]))
    def unexpected(*a, **kw):
        pytest.fail('Original page had no competition lookup requirement')
    monkeypatch.setattr(saved_fixture_name_lookup, 'load_fixture_name_lookup', unexpected)
    first = call(limit=1, include_competition=True)
    assert first['rows'][0]['fixture_name_index'] is None and not query._CACHE
    empty = call(offset=2, include_competition=True)
    assert empty['rows'] == [] and empty['matched_count'] == 2 and not query._CACHE
