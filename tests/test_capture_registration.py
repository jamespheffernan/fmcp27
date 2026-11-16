import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from fm_live_mcp import captured_match_registry as registry
from fm_live_mcp import captured_match_sources as sources
from fm_live_mcp.captured_match_query import CapturedMatchQueries
from fm_live_mcp.match_dataset import export_dataset


@pytest.fixture
def local_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, 'REGISTRY_PATH', tmp_path / 'catalog' / 'sources.json')
    return registry.REGISTRY_PATH


def export(path, *, day='2030-10-26', key=135904, career='Cesar Jules - Newcastle'):
    capture = {'save': dict(sources.EXPECTED_CAREER, name=career, current_date='2030-11-02'),
               'selectors': {'team_native_id': 713, 'date_from': day, 'date_to': day},
               'fixtures': [{'native_match_key': key, 'fixture': {'date': day,
                            'competition': {'native_id': 11}, 'home_team': {'native_id': 713},
                            'away_team': {'native_id': 692}}}]}
    export_dataset(path, capture, source='bounded_live_export')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_two_scopes_reload_without_restart_or_live_fallback(tmp_path, local_registry, monkeypatch):
    query = CapturedMatchQueries()
    a = tmp_path / 'one.sqlite'; sha_a = export(a)
    b = tmp_path / 'two.sqlite'; sha_b = export(b, day='2031-02-03', key=5, career='Different career')
    with pytest.raises(ValueError, match='Unknown named'):
        query.query('chosen_scope_one', sha_a)
    first = registry.register_capture(a, 'chosen_scope_one', sha_a, label='First historical scope')
    assert first['original_unchanged']
    assert query.query('chosen_scope_one', sha_a)['rows'][0]['date'] == '2030-10-26'
    registry.register_capture(b, 'chosen_scope_two', sha_b)
    second = query.query('chosen_scope_two', sha_b)
    assert second['rows'][0]['date'] == '2031-02-03'
    assert second['source']['captured_save']['name'] == 'Different career'
    assert second['source']['career_id'] != first['career_id']
    assert 'not the current' in second['claim']
    assert 'shots' not in second['source']['available_tables']
    with pytest.raises(ValueError, match='Table unavailable'):
        query.query('chosen_scope_two', sha_b, table='shots')
    def forbidden(*args, **kwargs):
        raise AssertionError('No directory scan is permitted')
    monkeypatch.setattr(Path, 'iterdir', forbidden)
    listed = {row['source_id']: row for row in sources.catalog_sources()['sources']}
    assert listed['chosen_scope_one']['state'] == listed['chosen_scope_two']['state'] == 'available'
    assert set(sources.SOURCES) <= set(listed)  # all four historical IDs preserved
    assert 'path' not in listed['chosen_scope_one']
    assert hashlib.sha256(a.read_bytes()).hexdigest() == sha_a
    assert hashlib.sha256(b.read_bytes()).hexdigest() == sha_b


def test_changed_file_rejects_old_and_new_hash_and_survives_reload(tmp_path, local_registry):
    path = tmp_path / 'original.sqlite'; digest = export(path)
    registry.register_capture(path, 'immutable_capture', digest)
    before = local_registry.read_bytes()
    with sqlite3.connect(path) as db:
        db.execute("UPDATE fixtures SET date='2030-10-27'")
    changed = hashlib.sha256(path.read_bytes()).hexdigest()
    for query in (CapturedMatchQueries(), CapturedMatchQueries()):
        for pin in (digest, changed):
            with pytest.raises(ValueError, match='fingerprint differs'):
                query.query('immutable_capture', pin)
    row = next(row for row in sources.catalog_sources()['sources'] if row['source_id'] == 'immutable_capture')
    assert row['state'] == 'unavailable'
    assert local_registry.read_bytes() == before


def test_wrong_hash_duplicate_id_builtin_and_duplicate_original_never_overwrite(tmp_path, local_registry):
    a = tmp_path / 'a.sqlite'; sha_a = export(a)
    b = tmp_path / 'b.sqlite'; sha_b = export(b, key=8)
    with pytest.raises(ValueError, match='fingerprint'):
        registry.register_capture(a, 'wrong_hash', '0' * 64)
    assert not local_registry.exists()
    registry.register_capture(a, 'one', sha_a)
    original_registry = local_registry.read_bytes()
    for path, source_id, digest in ((b, 'one', sha_b), (a, 'two', sha_a)):
        with pytest.raises(FileExistsError):
            registry.register_capture(path, source_id, digest)
    for source_id in sources.SOURCES:
        with pytest.raises(ValueError, match='Built-in'):
            registry.register_capture(b, source_id, sha_b)
    assert local_registry.read_bytes() == original_registry
    assert hashlib.sha256(a.read_bytes()).hexdigest() == sha_a
    assert hashlib.sha256(b.read_bytes()).hexdigest() == sha_b


def test_registry_corruption_symlink_and_unrelated_sqlite_fail_closed(tmp_path, local_registry):
    unrelated = tmp_path / 'unrelated.sqlite'
    with sqlite3.connect(unrelated) as db: db.execute('CREATE TABLE unrelated(value TEXT)')
    with pytest.raises(sqlite3.Error):
        registry.register_capture(unrelated, 'unrelated', hashlib.sha256(unrelated.read_bytes()).hexdigest())
    path = tmp_path / 'source.sqlite'; digest = export(path)
    alias = tmp_path / 'alias.sqlite'; alias.symlink_to(path)
    with pytest.raises(ValueError, match='symlink'):
        registry.register_capture(alias, 'alias', digest)
    local_registry.parent.mkdir()
    local_registry.symlink_to(path)
    with pytest.raises(ValueError, match='regular file'):
        registry.load_registrations()
    with pytest.raises(ValueError, match='regular file'):
        registry.register_capture(path, 'one', digest)
    local_registry.unlink()
    local_registry.write_text('{"version":99}')
    result = sources.catalog_sources()
    assert result['registration_catalog']['state'] == 'unavailable'
    assert set(sources.SOURCES) == {row['source_id'] for row in result['sources']}


def test_explicit_cli_and_new_process_reload_without_mcp_paths(tmp_path):
    home = tmp_path / 'home'; home.mkdir()
    path = tmp_path / 'one.sqlite'; digest = export(path)
    env = dict(os.environ, HOME=str(home))
    command = [sys.executable, '-m', 'fm_live_mcp.captured_match_registry']
    result = subprocess.run(command + ['register', str(path), '--source-id', 'from_cli', '--sha256', digest],
                            env=env, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['capture_id'] == digest
    result = subprocess.run(command + ['list'], env=env, capture_output=True, text=True, check=True)
    row = next(row for row in json.loads(result.stdout)['sources'] if row['source_id'] == 'from_cli')
    assert row['state'] == 'available' and row['capture_id'] == digest
    assert 'path' not in row and row['registration_kind'] == 'explicit_local_cli'
    from fm_live_mcp.captured_match_tools import register_captured_match_tools
    from mcp.server.fastmcp import FastMCP
    import asyncio
    mcp = FastMCP('capture registration check'); register_captured_match_tools(mcp)
    tools = asyncio.run(mcp.list_tools())
    assert all(not ({'path', 'sql', 'register'} & set(tool.inputSchema['properties'])) for tool in tools)


def test_export_cli_registration_is_explicit_and_existing_output_never_changes(tmp_path, local_registry, monkeypatch, capsys):
    from fm_live_mcp import export_live_matches as exporter
    from fm_live_mcp import bridge
    class OfflineBridge:
        def attach(self): return {'session_id': 'test'}
        def detach(self): pass
    monkeypatch.setattr(bridge, 'Bridge', OfflineBridge)
    capture = {'save': dict(sources.EXPECTED_CAREER, current_date='2030-11-02'),
               'fixtures': [{'native_match_key': 1, 'fixture': {'date': '2030-10-29',
                            'competition': {'native_id': 11}, 'home_team': {'native_id': 713},
                            'away_team': {'native_id': 692}}}]}
    monkeypatch.setattr(exporter, 'capture_scope', lambda *args, **kwargs: {
        'capture': capture, 'retained_players': [], 'team_totals': {'records': []}, 'raw_frames': []})
    output = tmp_path / 'exported.sqlite'
    args = ['export', '--team-id', '713', '--date-from', '2030-10-29', '--date-to', '2030-10-29', '--output', str(output)]
    monkeypatch.setattr(sys, 'argv', args)
    exporter.main()
    capsys.readouterr()
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    assert not local_registry.exists()  # ordinary exports stay unregistered
    output2 = tmp_path / 'registered.sqlite'
    args2 = args[:-1] + [str(output2), '--register-capture', 'explicit_export']
    monkeypatch.setattr(sys, 'argv', args2)
    exporter.main()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['registration']['source_id'] == 'explicit_export'
    pin = receipt['registration']['capture_id']
    assert CapturedMatchQueries().query('explicit_export', pin)['row_count'] == 1
    assert output2.is_file() and not list(local_registry.parent.glob('*.sqlite'))
    monkeypatch.setattr(sys, 'argv', args)
    with pytest.raises(FileExistsError): exporter.main()
    assert hashlib.sha256(output.read_bytes()).hexdigest() == digest
    # An already-used ID is rejected before any game attachment or new export.
    output3 = tmp_path / 'uncreated.sqlite'
    monkeypatch.setattr(sys, 'argv', args[:-1] + [str(output3), '--register-capture', 'explicit_export'])
    with pytest.raises(FileExistsError): exporter.main()
    assert not output3.exists()


def observed_export(path):
    export(path)
    with sqlite3.connect(path) as db:
        fid = db.execute('SELECT fixture_id FROM fixtures').fetchone()[0]
        db.executescript('''
        CREATE TABLE shots(fixture_id TEXT,native_match_key INTEGER,side_index INTEGER,record_index INTEGER,expected_goals REAL,raw_json TEXT);
        CREATE TABLE shot_map_coverage(fixture_id TEXT,native_match_key INTEGER,side_index INTEGER,team_native_id INTEGER,team_index INTEGER,source_id TEXT,state TEXT,shot_count INTEGER,shots_on_target INTEGER,expected_goals REAL,own_goal_marker_count INTEGER,raw_json TEXT);
        CREATE TABLE source_observed_shots(fixture_id TEXT,native_match_key INTEGER,side_index INTEGER,record_index INTEGER,native_expected_goals REAL,verification_scope TEXT,canonical_person_id INTEGER,person_name TEXT,raw_json TEXT);
        CREATE TABLE source_observed_shot_coverage(fixture_id TEXT,native_match_key INTEGER,side_index INTEGER,source_id TEXT,state TEXT,strict_side_state TEXT,observed_shot_count INTEGER,rostered_players_checked INTEGER,zero_shot_players_checked INTEGER,team_xg_ulp_distance INTEGER,verified_shots_promoted INTEGER,xg_tolerance_widened INTEGER,raw_json TEXT);
        CREATE TABLE source_observed_field_coverage(fixture_id TEXT,side_index INTEGER,field_group TEXT,state TEXT,known_attempt_count INTEGER,unknown_attempt_count INTEGER);
        CREATE VIEW source_observed_shot_analysis AS SELECT f.date,f.competition,f.home_team,f.away_team,s.* FROM source_observed_shots s JOIN fixtures f USING(fixture_id);
        ''')
        for side in (0,1):
            strict = 'unavailable_xg_reconciliation' if side == 0 else 'available'
            counts = (None,None,None,None) if side == 0 else (0,0,0.0,0)
            db.execute('INSERT INTO shot_map_coverage VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (fid,135904,side,713 if side==0 else 692,side,'cache',strict,*counts,'{}'))
            state = 'available_source_observed_counts_verified_xg_unreconciled' if side == 0 else 'not_needed_strict_side_available'
            db.execute('INSERT INTO source_observed_shot_coverage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', (fid,135904,side,'cache',state,strict,1 if side==0 else 0,11 if side==0 else None,10 if side==0 else None,2 if side==0 else None,0,0,'{}'))
            db.execute('INSERT INTO source_observed_field_coverage VALUES (?,?,?,?,?,?)', (fid,side,'outcome','complete' if side==0 else 'unavailable_source',1 if side==0 else None,0 if side==0 else None))
        db.execute('INSERT INTO source_observed_shots VALUES (?,?,?,?,?,?,?,?,?)',(fid,135904,0,0,0.2,'source_observed_counts_actors_verified_xg_unreconciled',7,'Observed Player','{}'))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_separate_observed_tables_never_fill_strict_missing_rows(tmp_path, local_registry):
    path = tmp_path / 'observed.sqlite'; digest = observed_export(path)
    registry.register_capture(path, 'observed_scope', digest)
    query = CapturedMatchQueries()
    strict = query.query('observed_scope', digest, table='shots')
    assert strict['rows'] == []
    assert strict['selected_shot_coverage']['sides'][0]['shot_count'] is None
    assert strict['selected_shot_coverage']['sides'][1]['shot_count'] == 0
    observed = query.query('observed_scope', digest, table='source_observed_shots')
    assert observed['rows'][0]['native_expected_goals'] == 0.2
    assert 'expected_goals' not in observed['fields']
    context = observed['selected_source_observed_coverage']['sides'][0]
    assert context['observed_shot_count'] == 1 and context['verified_shots_promoted'] == 0
    assert context['strict_side_state'] == 'unavailable_xg_reconciliation'
    assert query.query('observed_scope', digest, table='source_observed_shot_analysis')['row_count'] == 1
    assert query.query('observed_scope', digest, table='source_observed_field_coverage')['rows'][1]['known_attempt_count'] is None


def test_misleading_observed_schema_or_promotion_rejected(tmp_path, local_registry):
    for name, statement in (
        ('promoted', 'UPDATE source_observed_shot_coverage SET verified_shots_promoted=1 WHERE side_index=0'),
        ('renamed_xg', 'ALTER TABLE source_observed_shots ADD COLUMN expected_goals REAL'),
        ('wrong_count', 'UPDATE source_observed_shot_coverage SET observed_shot_count=9 WHERE side_index=0'),
    ):
        path = tmp_path / (name + '.sqlite'); observed_export(path)
        with sqlite3.connect(path) as db: db.execute(statement)
        with pytest.raises(ValueError, match='Source-observed'):
            registry.register_capture(path, name, hashlib.sha256(path.read_bytes()).hexdigest())
    assert not local_registry.exists()


def test_registered_delivery_provenance_remains_explicit(tmp_path, local_registry):
    path=tmp_path/'historical.sqlite';export(path)
    delivery={'fresh_live_refresh_at_delivery':False,'code_installation_claim':False,'captured_game_date':'2030-11-02'}
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO metadata VALUES (?,?)',('delivery_provenance',json.dumps(delivery)))
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    registry.register_capture(path,'historical_delivery',digest)
    result=CapturedMatchQueries().query('historical_delivery',digest)
    assert result['source']['delivery_provenance']==delivery
