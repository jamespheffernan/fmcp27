"""Optional recorder scope: cutoff, unknown actors, storage and tamper controls."""
import copy
import json
import sqlite3
import struct

import pytest

from fm_live_mcp import observed_run_match_statistics as stats
from fm_live_mcp import observed_run_match_statistics_store as store
from fm_live_mcp import active_match_score
from fm_live_mcp.observed_run_recorder import write_prefix


def packet_and_document(monkeypatch):
    shot = {'event_id': 7, 'side_index': 0, 'event_side_index': 0,
        'native_actor_slot': 2, 'native_clock_start_raw': 20,
        'native_clock_end_raw': 30, 'native_category_code': 1,
        'outcome': 'goal', 'expected_goals': .25, 'actor': None,
        'period': None, 'native_x': 1., 'native_y': 2., 'body_part': 'feet'}
    chances = {'state': 'available', 'official_match_unique_id': 123,
        'shots': [shot], 'own_goal_markers': [], 'periods': [],
        'sides': [{'side_index': i, 'state': 'available', 'shots': 1-i,
            'shots_on_target': 1-i, 'shot_goals': 1-i,
            'expected_goals_sum_computed': .25 if i == 0 else 0.} for i in (0, 1)]}
    monkeypatch.setattr(stats.active_match_shot_timeline, 'project', lambda *a, **kw: copy.deepcopy(chances))
    score = {'official_match_unique_id': 123, 'current_time_slice': 100,
        'current_score': {'state': 'available', 'home_goals': 1,
            'away_goals': 0, 'at_time_slice': 100}, 'first_half_score': None}
    document = stats.project({'pitch_geometry': {'half_width_native': 3400, 'half_length_native': 5250}},
        {'official_match_unique_id': 123, 'current_time_slice': 100}, {}, None, score)
    packet = {'state': 'verified_partial_prefix', 'same_career_epoch_verified': True,
        'incarnation_id': '1'*64, 'cursor': 100,
        'fixture': {'date': '2030-11-11', 'competition_id': 11, 'home_team_id': 688,
            'away_team_id': 692, 'official_match_unique_id': 123},
        'save': {'name': 'Career', 'created_date': '2030-01-01', 'created_version': '27',
            'current_date': '2030-11-11', 'last_saved_date': '2030-11-10'},
        'actors': [], 'events': [], 'tracking': {'players': [], 'orientation_profile_hex': '00'*16,
            'possession_samples_hex': ''}, 'period_markers': [], 'period_state': 'unknown',
        'observed_at_unix': 1, 'verification': {'fixed_time_slice': 100}}
    document.update(fixture=packet['fixture'], source_incarnation_id=packet['incarnation_id'])
    packet['match_statistics_observation'] = document
    return packet, document


def test_optional_storage_and_unknown_actor(monkeypatch, tmp_path):
    packet, document = packet_and_document(monkeypatch)
    assert document['player_shot_statistics'][0]['canonical_person_id'] is None
    receipt = write_prefix(packet, tmp_path)
    with sqlite3.connect(receipt['path']) as db:
        assert db.execute('SELECT home_score,away_score FROM fixtures').fetchone() == (1, 0)
        assert db.execute('SELECT COUNT(*) FROM shots').fetchone() == (1,)
        assert db.execute('SELECT canonical_person_id,shots,shots_on_target FROM player_shot_statistics').fetchone() == (None, 1, 1)
        raw = json.loads(db.execute("SELECT document_json FROM source_documents WHERE source_id=?", (store.SOURCE_ID,)).fetchone()[0])
        assert raw['native_player_statistics']['state'] == 'unavailable'
        assert 'engine_totals' not in json.dumps(raw)
    assert write_prefix(packet, tmp_path)['state'] == 'already_recorded'
    from fm_live_mcp import observed_run_registry as registry
    from fm_live_mcp.observed_match_runs import open_run, ObservedRunQueries
    monkeypatch.setattr(registry, 'REGISTRY_PATH', tmp_path / 'registry.json')
    registry.register_original(receipt['path'], receipt['source_id'], receipt['sha256'])
    with open_run(receipt['source_id'], receipt['sha256']) as (_, provenance):
        assert set(store.COLUMNS).issubset(provenance['available_tables'])
        assert provenance['counts']['shots'] == 1
    assert ObservedRunQueries().query(receipt['source_id'], receipt['sha256'], 'player_shot_statistics')


@pytest.mark.parametrize('table,cell', [('shots', 'outcome'), ('own_goal_markers', None),
    ('player_shot_statistics', 'shots'), ('score_snapshots', 'home_goals'),
    ('match_prefix_team_totals', 'shots'), ('match_period_team_totals', None)])
def test_every_new_table_is_verified(monkeypatch, tmp_path, table, cell):
    packet, document = packet_and_document(monkeypatch)
    receipt = write_prefix(packet, tmp_path)
    with sqlite3.connect(receipt['path']) as db:
        if cell:
            db.execute(f'UPDATE {table} SET {cell}=?', ('tampered',))
        elif table == 'own_goal_markers':
            db.execute(f'INSERT INTO {table} VALUES (9,0,1,2,NULL,1,2,\'{{}}\',\'x\')')
        else:
            db.execute(f'INSERT INTO {table} VALUES (\'invented\',0,1,1,1,1.0)')
    with pytest.raises(ValueError, match='analytical'):
        write_prefix(packet, tmp_path)


@pytest.mark.parametrize('change', ['cursor', 'actor', 'count', 'identity'])
def test_wrong_binding_or_future_attempt_rejects(monkeypatch, change):
    packet, document = packet_and_document(monkeypatch)
    if change == 'cursor': document['shots']['shots'][0]['native_clock_end_raw'] = 100
    elif change == 'actor': document['shots']['shots'][0]['actor'] = {'canonical_person_id': 3}
    elif change == 'count': document['shots']['sides'][0]['shots'] = 2
    else: document['official_match_unique_id'] = 456
    with pytest.raises(ValueError): stats.validate(document, packet)


def test_unavailable_scope_does_not_invent_zero_tables(monkeypatch, tmp_path):
    packet, document = packet_and_document(monkeypatch)
    packet['match_statistics_observation'] = stats.unavailable('moving_source')
    receipt = write_prefix(packet, tmp_path)
    with sqlite3.connect(receipt['path']) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='shots'").fetchone()
        assert 'home_score' not in [r[1] for r in db.execute('PRAGMA table_info(fixtures)')]


def test_source_drift_withholds_optional_scope():
    class Changed:
        def verify(self): raise ValueError('changed')
    assert stats.finish({'state': 'available'}, Changed())['state'] == 'unavailable'


def test_unavailable_clock_projection_is_not_partial(monkeypatch):
    monkeypatch.setattr(stats.active_match_shot_timeline, 'project',
        lambda *a, **kw: {'state': 'unavailable', 'reason': 'clock_wrap'})
    assert stats.project({}, {}, {}, None, {}) == stats.unavailable('clock_wrap')


def test_official_score_cursor_tie_is_inclusive():
    row = bytearray(32)
    struct.pack_into('<i', row, 0x18, 100)
    row[0x1d], row[0x1f] = 0, 1
    assert active_match_score.project_incidents([bytes(row)], 100)['home_goals'] == 1
    assert not (20 <= 100 < 100)  # The independently retained shot must be excluded.


def test_capture_rechecks_shot_only_actor_binding(monkeypatch):
    # These optional reads use their own rechecked read set, including actors
    # who were absent from the completed-pass prefix.
    packet, document = packet_and_document(monkeypatch)
    bound = {'official_match_unique_id': 123, 'current_time_slice': 100}
    actors = {'players': [], 'state': 'validated_native_stored_slots'}
    private = {'binding': {'client': 4096, 'engine': 8192}, 'bound': bound,
        'source': {'cbe': 0}, 'actors': actors,
        'fixture': {'date': '2030-11-11', 'competition': {'native_id': 11},
            'home_team': {'database_index': 545, 'native_id': 688},
            'away_team': {'database_index': 549, 'native_id': 692}}}
    source = {'state': 'available_engine_source',
        'fixture_identity': ('2030-11-11', 11, (545, 688), (549, 692))}
    monkeypatch.setattr(stats.active_match_shot_timeline, '_verify_bound', lambda *a: None)
    monkeypatch.setattr(stats.active_match_shots, 'capture_source', lambda *a: source)
    monkeypatch.setattr(stats.active_match_score, 'capture', lambda *a, **kw: document['score'])
    monkeypatch.setattr(stats.active_match_people, 'inspect_actor_bindings', lambda *a, **kw: actors)
    result, proof = stats.capture(lambda a, n: bytes(n), 0, private, {})
    assert result['state'] == 'available' and proof is not None
    monkeypatch.setattr(stats.active_match_people, 'inspect_actor_bindings', lambda *a, **kw: {'players': [{'person_name': 'changed'}]})
    result, proof = stats.capture(lambda a, n: bytes(n), 0, private, {})
    assert result['state'] == 'unavailable' and proof is None
