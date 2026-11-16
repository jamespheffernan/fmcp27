import copy
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from fm_live_mcp.saved_match_player_recoveries import decode_player_recoveries, pressure_completion_fields, recovery_field_registry
from fm_live_mcp.match_dataset import build_connection, export_dataset
from fm_live_mcp.match_scope_query import column_catalog, ScopedMatchQueries
from fm_live_mcp.match_data_query import MatchDataQueries
from fm_live_mcp.live_match_player_ranking import rank_capture, metric_catalog, LiveMatchPlayerRanks

FIELDS = ['pressures_attempted', 'pressures_completed', 'pressure_completion_percentage_computed', 'pressure_completion_state']


def actual():
    with gzip.open(Path(__file__).parent / 'fixtures/lille_pressure_players.json.gz', 'rt') as f:
        return json.load(f)


def captured(rows=None):
    control = actual()
    return {'capture': {'save': {}, 'fixtures': [{'native_match_key': 136941, 'fixture': control['source']['fixture']}]},
            'retained_players': control['rows'] if rows is None else rows}


def test_actual_lille_all43_canonical_rows_match_raw_child_hashes_and_named_counters():
    c = actual(); assert c['native_match_key'] == 136941 and len(c['rows']) == 43
    for row in c['rows']:
        child = bytes.fromhex(row['raw_child_hex'])
        assert hashlib.sha256(child).hexdigest() == row['row_sha256']
        decoded = decode_player_recoveries(child)
        assert decoded['pressures_attempted'] == row['pressures_attempted']
        assert decoded['pressures_completed'] == row['pressures_completed']
        assert pressure_completion_fields(decoded)['pressure_completion_percentage_computed'] == row['pressure_completion_percentage_computed']
    assert [(r['pressures_attempted'], r['pressures_completed']) for r in c['sides']] == [(52, 13), (49, 11)]
    registry = recovery_field_registry()['pressures_attempted']
    assert registry['native_stat_id'] == 12 and registry['native_offset'] == '0xec'
    assert registry['supported_individual_property_getter'] is False


@pytest.mark.parametrize('attempted,completed,state,rate', [
    (None, 1, 'unavailable_missing_pressure_counters', None),
    (3, None, 'unavailable_missing_pressure_counters', None),
    (False, 0, 'unavailable_missing_pressure_counters', None),
    (0, 0, 'undefined_zero_pressure_attempts', None),
    (0, 1, 'unavailable_completed_exceeds_attempted', None),
    (2, 3, 'unavailable_completed_exceeds_attempted', None),
    (5, 0, 'available', 0.0), (4, 1, 'available', 25.0), (255, 255, 'available', 100.0),
])
def test_pressure_rate_denominator_unknown_zero_and_inconsistent_are_distinct(attempted, completed, state, rate):
    out = pressure_completion_fields({'pressures_attempted': attempted, 'pressures_completed': completed})
    assert out == {'pressure_completion_percentage_computed': rate, 'pressure_completion_state': state}


def test_query_catalog_explicit_scoped_and_analysis_view_preserve_actual_pressure_fields():
    packet = captured()
    columns = column_catalog()['retained_players']
    assert all(field in columns['columns'] for field in FIELDS)
    assert columns['field_provenance']['pressures_attempted']['official_property_label'] == 'PressuresAttempted'
    explicit = MatchDataQueries(lambda *a, **k: packet, epoch=lambda *_: 1)
    rows = explicit.query(None, 's', ['r'], 'retained_players', ['person_name'] + FIELDS)['rows']
    poku, = [row for row in rows if row['person_name'] == 'Ernest Poku']
    assert poku['pressures_attempted'] == 4 and poku['pressures_completed'] == 3
    assert poku['pressure_completion_percentage_computed'] == 75
    scoped = ScopedMatchQueries(lambda *a, **k: packet, epoch=lambda *_: 1)
    result = scoped.query(None, 's', 688, '2030-11-06', '2030-11-06', tables=['retained_players'], fields={'retained_players': FIELDS})
    assert len(result['rows']) == 43
    db = build_connection(packet['capture'], retained_players=packet['retained_players'])
    try:
        assert db.execute('SELECT sum(pressures_attempted),sum(pressures_completed) FROM player_match_analysis GROUP BY side_index ORDER BY side_index').fetchall() == [(52, 13), (49, 11)]
        assert db.execute('SELECT pressure_completion_percentage_computed FROM player_match_analysis WHERE person_name=?', ('Ernest Poku',)).fetchone() == (75.0,)
    finally: db.close()


def test_export_absent_attempts_preserve_unknown_instead_of_backfilling_raw_child(tmp_path):
    packet = captured()
    rows = copy.deepcopy(packet['retained_players'])
    for row in rows:
        row.pop('pressures_attempted'); row.pop('pressure_completion_percentage_computed'); row.pop('pressure_completion_state')
    db = build_connection(packet['capture'], retained_players=rows)
    try:
        assert db.execute('SELECT count(pressures_attempted),count(pressure_completion_percentage_computed) FROM retained_players').fetchone() == (0, 0)
        assert db.execute('SELECT DISTINCT pressure_completion_state FROM retained_players').fetchall() == [('unavailable_missing_pressure_counters',)]
    finally: db.close()


def test_weighted_pressure_ranking_uses_ratio_of_sums_and_allows_both_historical_sides():
    from test_live_match_player_ranking import fixture, player, data
    rows = [player(1, person=1, pressures_attempted=1, pressures_completed=1),
            player(2, person=1, pressures_attempted=99, pressures_completed=1),
            player(1, person=2, pressures_attempted=10, pressures_completed=5),
            player(2, person=2, pressures_attempted=10, pressures_completed=5)]
    result = rank_capture(data([fixture(1), fixture(2)], rows), 'pressures_completed', 'per_100_pressure_attempts', 0)
    assert [row['person_native_id'] for _, row in result['ranked']] == [2, 1]
    assert [row['value'] for _, row in result['ranked']] == [50.0, 2.0]
    assert result['ranked'][1][1]['denominator'] == 100
    actual_rank = rank_capture(captured(), 'pressures_attempted', 'total', 0)
    assert {row['historical_team_native_id'] for _, row in actual_rank['ranked']} == {858, 688}
    assert metric_catalog()['metrics']['pressures_completed']['normalizations'] == ['total', 'per90', 'per_100_pressure_attempts']


@pytest.mark.parametrize('attempted,completed,reason', [(None, 1, 'missing_pressure_attempts_denominator'), (0, 0, 'zero_pressure_attempts_denominator'), (1, 2, 'pressure_completions_exceed_attempts')])
def test_pressure_ranking_withholds_missing_zero_or_inconsistent_denominator(attempted, completed, reason):
    from test_live_match_player_ranking import fixture, player, data
    result = rank_capture(data([fixture(1)], [player(1, pressures_attempted=attempted, pressures_completed=completed)]),
                          'pressures_completed', 'per_100_pressure_attempts', 0)
    assert result['ranked'] == []
    assert reason in result['excluded'][0]['reasons']


def test_registered_older_source_explicit_pressure_requests_are_unknown_and_do_not_mutate_it(tmp_path, monkeypatch):
    from test_captured_match_query import original, SOURCE
    from fm_live_mcp import captured_match_sources as sources
    from fm_live_mcp.captured_match_query import CapturedMatchQueries
    path, _ = original(tmp_path, monkeypatch)
    db = sqlite3.connect(path)
    db.execute('DROP VIEW player_match_analysis')
    for field in ('pressures_attempted', 'pressure_completion_percentage_computed', 'pressure_completion_state'):
        db.execute('ALTER TABLE retained_players DROP COLUMN ' + field)
    db.execute('CREATE VIEW player_match_analysis AS SELECT * FROM retained_players')
    db.commit(); db.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with sources.open_source(SOURCE) as (_, provenance):
        assert provenance['pressure_statistics_coverage']['state'] == 'not_captured'
    for table in ('retained_players', 'player_match_analysis'):
        out = CapturedMatchQueries().query(SOURCE, provenance['capture_id'], table=table, fields=FIELDS, limit=1)
        assert out['rows'] == [{'pressures_attempted': None, 'pressures_completed': None,
                                'pressure_completion_percentage_computed': None,
                                'pressure_completion_state': 'unavailable_not_in_registered_capture'}]
        assert out['pressure_field_availability']['pressures_attempted'] == 'unknown_not_in_registered_capture'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_actual_lille_new_export_has_all43_pressure_counters_and_rate_columns(tmp_path):
    packet = captured(); path = tmp_path / 'lille-pressure.sqlite'
    export_dataset(path, packet['capture'], retained_players=packet['retained_players'])
    db = sqlite3.connect(path)
    try:
        assert db.execute('SELECT count(pressures_attempted) FROM retained_players').fetchone() == (43,)
        assert db.execute('SELECT sum(pressures_attempted),sum(pressures_completed) FROM retained_players GROUP BY side_index ORDER BY side_index').fetchall() == [(52, 13), (49, 11)]
        assert db.execute('SELECT pressure_completion_percentage_computed FROM player_match_analysis WHERE person_name=?', ('Luiz Henrique',)).fetchone() == (100.0,)
        assert db.execute('SELECT pressure_completion_percentage_computed,pressure_completion_state FROM retained_players WHERE pressures_attempted=0 LIMIT 1').fetchone() == (None, 'undefined_zero_pressure_attempts')
    finally: db.close()


def test_pressure_ratio_normalization_is_not_available_for_attempt_counts():
    with pytest.raises(ValueError, match='normalization'):
        rank_capture(captured(), 'pressures_attempted', 'per_100_pressure_attempts', 0)
