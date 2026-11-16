"""Explicit host-side preservation of one verified native match prefix.

No daemon, game mutation, retained-save fallback, terminal-completeness inference,
metric pitch units or replay exclusion. Native owner epochs are hashed privately.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from . import active_pass_network as passes, active_match_tracking as tracking, players


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def capture_prefix(bridge, session_id, *, include_tactics=True, include_incomplete_passes=False):
    """Capture and reselect used pass/tracking bytes under one career/owner epoch."""
    if type(include_tactics) is not bool:
        raise ValueError('include_tactics must be boolean')
    if type(include_incomplete_passes) is not bool:
        raise ValueError('include_incomplete_passes must be boolean')
    seal = None
    output = None
    def final_verify():
        if seal is not None:
            seal()
            if output is not None:
                output['verification'] = verified
                output['match_statistics_observation'] = statistics
    scope = bridge._read_scope(session_id, final_verify=final_verify) if include_incomplete_passes else bridge._read_scope(session_id)
    with bridge.lock, scope:
        process = bridge._current(session_id)
        layout = bridge._player_layout(process)
        world, save, _ = bridge._world_state(process, layout)
        epoch = (process.pid, process.version, process.executable, layout, bridge.world_identity)
        base = layout[0] - players.RVA[0]
        read = lambda address, size: bridge._read_memory(process, address, size)
        options = {'include_locations': True, 'include_pass_attempts': True} if include_incomplete_passes else {}
        result, packet = passes._capture_components(read, base, save['current_date'], **options)
        if packet is None:
            return {'state': 'unavailable', 'reason': result.get('reason'), 'artifact_written': False}
        binding, bound = packet['binding'], packet['bound']
        native = tracking.capture_source(read, base, binding['client'], binding['engine'],
                                        current_time_slice=bound['current_time_slice'])
        if native.get('state') != 'available_engine_tracking_source':
            raise ValueError('Bound tracking prefix unavailable; no artifact published')
        # Period sampling is optional: this increment preserves unknown period labels
        # rather than guessing halves from clock ranges or borrowing a later cursor.
        from . import active_match_half_boundaries
        period_sampled = True
        try:
            period = active_match_half_boundaries.inspect(read, base, bound)
        except ValueError as error:
            # The optional named-period getter requires a stationary cursor.
            # Never attach its later period to the original fixed prefix.
            if str(error) != 'Checked playback time slice changed':
                raise
            period_sampled = False
            period = {'state': 'unknown', 'reason': 'optional_period_cursor_changed',
                      'period_markers': [], 'period_intervals': []}
        from . import observed_run_match_statistics as match_statistics
        statistics, statistics_proof = match_statistics.capture(read, base, packet, period)
        from . import observed_run_tactical_capture
        tactical = observed_run_tactical_capture.capture(read,base,binding,bound) if include_tactics else {'state':'not_requested'}
        selected = tracking.clip_tracking(native['tracking'], bound['current_time_slice'])
        used = {(r['side_index'], r['stored_player_slot']) for r in selected['players']}
        for event in packet['source']['events']:
            used.add((event['side_index'], event['stored_player_slot']))
            if event['category'] == 7 and not event['flags_word'] & 8:
                used.add((event['side_index'], event['recipient_slot']))
        if statistics.get('state') in ('available', 'partial'):
            for shot in statistics['shots']['shots'] + statistics['shots']['own_goal_markers']:
                used.add((shot['event_side_index'], shot['native_actor_slot']))
        def identities(actors):
            if actors.get('official_match_unique_id') != bound['official_match_unique_id']:
                raise ValueError('Recorded canonical actors belong to another match')
            indexed = passes._actor_map(actors)
            return {key: None if key not in indexed else tuple(indexed[key].get(field) for field in (
                'canonical_person_id', 'person_index_word', 'person_name', 'identity_state')) for key in used}
        world.verify()
        final = bridge._current(session_id)
        final_layout = bridge._player_layout(final)
        final_world, _, _ = bridge._world_state(final, final_layout)
        final_world.verify()
        if epoch != (final.pid, final.version, final.executable, final_layout, bridge.world_identity):
            raise ValueError('Observed recording career/process epoch changed')
        public_save = bridge._public_save(save)
        # Lifetime callbacks can read mutable native state. Check every consumed
        # prefix only after those callbacks, never publish their earlier sample.
        verified = None
        def seal():
            nonlocal verified, statistics
            tracking.verify_prefix(read, base, binding['client'], binding['engine'], bound, native)
            verified = passes._verify_components(read, base, save['current_date'], packet)
            # Re-select only observed markers at the fixed cursor; mutable later
            # markers may append, but used historical marker values cannot change.
            import struct
            if period_sampled:
                provider = bound['frame_provider_address']
                first, last, capacity = struct.unpack('<QQQ', read(provider + 0x1A0, 24))
                if not first <= last <= capacity or (last-first) % 20 or capacity-first > active_match_half_boundaries.MAX_STOP_RECORDS*20:
                    raise ValueError('Period observation vector changed')
                raw = read(first, last-first) if last > first else b''
                again = active_match_half_boundaries.decode(raw, current_time_slice=bound['current_time_slice'],
                    simulation_period=period.get('period_source', {}).get('simulation_period'))
                if again.get('period_markers', []) != period.get('period_markers', []):
                    raise ValueError('Consumed observed period markers changed')
            # Portable artifacts retain raw profile and actual phase bytes, beyond
            # the sign/phase semantics used by tracking averages. Check all of them.
            fresh_tracking = tracking.capture_source(read, base, binding['client'], binding['engine'],
                                                    current_time_slice=bound['current_time_slice'])
            if (fresh_tracking.get('state') != 'available_engine_tracking_source'
                    or tracking.clip_tracking(fresh_tracking['tracking'], bound['current_time_slice']) != selected):
                raise ValueError('Consumed portable tracking bytes changed')
            fresh_actors = passes.active_match_people.inspect_actor_bindings(read, base, binding['engine'],
                                expected_match_unique_id=bound['official_match_unique_id'])
            if identities(fresh_actors) != identities(packet['actors']):
                raise ValueError('Consumed recorded canonical actor changed')
            # The optional proof must be the last source check: base verification or
            # lifetime callbacks can invalidate its previously sampled bytes.
            statistics = match_statistics.finish(statistics, statistics_proof)
        seal()
        actors = [{key: row.get(key) for key in ('side_index', 'stored_player_slot',
                   'canonical_person_id', 'person_index_word', 'person_name', 'identity_state')}
                  for row in packet['actors'].get('players', [])]
        actors = [a for a in actors if (a['side_index'], a['stored_player_slot']) in used]
        portable = {'players': [{**row, 'samples_hex': row['samples'].hex()}
                                for row in selected['players']]}
        for row in portable['players']:
            del row['samples']
        portable.update(orientation_profile_hex=selected['orientation_profile'].hex(),
                        possession_samples_hex=(selected.get('possession_samples') or b'').hex())
        # Private native incarnation binds distinct launches/replays even when an
        # official fixture ID is reused. Addresses themselves never leave memory.
        incarnation = _sha({'epoch': epoch, 'binding': binding,
                            'playback': passes._bound_identity(bound), 'cbe': packet['source']['cbe']})
        fixture = packet['fixture']
        safe_fixture = {'date': fixture['date'], 'competition_id': fixture['competition']['native_id'],
                        'home_team_id': fixture['home_team']['native_id'],
                        'away_team_id': fixture['away_team']['native_id'],
                        'official_match_unique_id': bound['official_match_unique_id']}
        if tactical['state']=='available':
            tactical.update(fixture=safe_fixture,source_incarnation_id=incarnation,
                            career={key:save[key] for key in ('name','created_date','created_version')})
        if statistics.get('state') in ('available', 'partial'):
            statistics.update(fixture=safe_fixture, source_incarnation_id=incarnation)
        markers = period.get('period_markers', [])
        output = {'state': 'verified_partial_prefix', 'fixture': safe_fixture,
                'save': public_save, 'incarnation_id': incarnation,
                'cursor': bound['current_time_slice'], 'actors': actors,
                'events': packet['source']['events'], 'tracking': portable,
                'period_markers': markers, 'period_state': period.get('state'),
                'period_reason': period.get('reason'),
                'observed_at_unix': datetime.now(timezone.utc).timestamp(),
                'tactical_observation':tactical,
                'match_statistics_observation': statistics,
                'assist_annotation_collection':{'state':'unavailable','reason':'complete_independent_counters_and_terminal_all_category_event_scope_not_collected'},
                'verification': verified, 'same_career_epoch_verified': True,
                'replay_exclusion_verified': False, 'terminal_completeness_verified': False}
        if include_incomplete_passes:
            from .observed_pass_attempts import capture_document
            output['pass_attempt_observation'] = capture_document(output, packet['source'])
        return output


def _validate(packet):
    if packet.get('state') != 'verified_partial_prefix' or packet.get('same_career_epoch_verified') is not True:
        raise ValueError('Only a verified same-career prefix can be recorded')
    if not isinstance(packet.get('incarnation_id'), str) or len(packet['incarnation_id']) != 64:
        raise ValueError('Missing source incarnation')
    cursor = packet.get('cursor')
    if type(cursor) is not int or not 0 <= cursor < 65536:
        raise ValueError('Unsupported fixed cursor')
    ids = set()
    for event in packet['events']:
        # The opt-in attempt decoder excludes mask8 before original-slot
        # semantics. Preserve its opaque raw sender byte without assigning an
        # actor or requiring coordinates. Default recording keeps its contract.
        opaque_sender = (packet.get('pass_attempt_observation') is not None
                         and event['flags_word'] & 8
                         and type(event['stored_player_slot']) is int
                         and 0 <= event['stored_player_slot'] < 256)
        if (event['event_id'] in ids or event['side_index'] not in (0,1)
                or not (opaque_sender or 0 <= event['stored_player_slot'] < 26)):
            raise ValueError('Ambiguous pass identity')
        ids.add(event['event_id'])
        if not 0 <= event['start'] <= event['end'] < cursor or event['category'] not in range(6, 12):
            raise ValueError('Event exceeds verified ended selection')
    actor_keys = [(a['side_index'],a['stored_player_slot']) for a in packet['actors']]
    if len(set(actor_keys)) != len(actor_keys):
        raise ValueError('Ambiguous actor binding')
    native = packet['tracking']
    seen = set()
    for row in native['players']:
        key = row['side_index'], row['stored_player_slot']
        if key in seen or key[0] not in (0, 1) or not 0 <= key[1] < 26:
            raise ValueError('Ambiguous tracking slot')
        seen.add(key)
        raw = bytes.fromhex(row['samples_hex'])
        if not raw or len(raw) % 4 or row['start_tick'] + (len(raw)//4 - 1)*24 > cursor:
            raise ValueError('Tracking exceeds selected prefix')
    from .observed_run_tactical_capture import validate as validate_tactics
    validate_tactics(packet.get('tactical_observation',{}),packet)
    from .observed_run_match_statistics import validate as validate_statistics
    validate_statistics(packet.get('match_statistics_observation', {}), packet)
    from .observed_pass_attempts import validate as validate_attempts
    validate_attempts(packet.get('pass_attempt_observation'), packet)
    for key in ('name', 'created_date', 'created_version', 'current_date', 'last_saved_date'):
        if key not in packet['save']:
            raise ValueError('Incomplete career provenance')


def _verify_stored(path, packet):
    db = sqlite3.connect(Path(path).as_uri()+'?mode=ro', uri=True)
    try:
        from .observed_run_match_statistics_store import verify as verify_statistics
        verify_statistics(db, packet.get('match_statistics_observation'), _sha)
        from .observed_pass_attempts import verify_stored
        verify_stored(db, packet.get('pass_attempt_observation'))
        tactical=packet.get('tactical_observation')
        if tactical is not None:
            from .observed_run_tactical_capture import semantic
            row=db.execute("SELECT sha256,document_json FROM source_documents WHERE source_id='tactical_samples'").fetchone()
            if row is None or _sha(json.loads(row[1]))!=row[0] or semantic(json.loads(row[1]))!=semantic(tactical):
                raise ValueError('Existing tactical observation semantics changed')
        expected = sorted((e['event_id'],_json(e)) for e in packet['events'])
        if db.execute('SELECT event_id,record_json FROM native_pass_events ORDER BY event_id').fetchall() != expected:
            raise ValueError('Existing recorded event semantics changed')
        expected = sorted((r['side_index'],r['stored_player_slot'],r['start_tick'],24,bytes.fromhex(r['samples_hex']))
                          for r in packet['tracking']['players'])
        if db.execute('SELECT * FROM tracking_sources ORDER BY side_index,stored_player_slot').fetchall() != expected:
            raise ValueError('Existing recorded tracking semantics changed')
        actors = {(a['side_index'],a['stored_player_slot']):a for a in packet['actors']}
        expected = []
        for e in packet['events']:
            if e['category']==7 and not e['flags_word']&8:
                a=actors.get((e['side_index'],e['stored_player_slot']),{})
                b=actors.get((e['side_index'],e['recipient_slot']),{})
                expected.append((e['event_id'],e['side_index'],e['stored_player_slot'],e['recipient_slot'],
                                 a.get('person_name'),b.get('person_name'),e['start'],e['end'],None,'terminal'))
        if db.execute('SELECT * FROM completed_pass_events ORDER BY event_id').fetchall()!=sorted(expected):
            raise ValueError('Existing recorded analytical events changed')
    finally:
        db.close()


def write_prefix(packet, store):
    """Publish immutable content-addressed SQLite; unchanged selection reuses it."""
    _validate(packet)
    semantic = {key: value for key, value in packet.items()
                if key not in ('observed_at_unix', 'verification', 'save')}
    semantic['career'] = {key: packet['save'][key] for key in ('name', 'created_date', 'created_version')}
    from .observed_run_tactical_capture import semantic as tactical_semantic
    if 'tactical_observation' in semantic:
        semantic['tactical_observation'] = tactical_semantic(semantic['tactical_observation'])
    digest = _sha(semantic)
    source_id = 'observed_' + digest[:32]
    directory = Path(store).expanduser().absolute()
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError('Observed store must be an original directory')
    path = directory / (source_id + '.sqlite')
    if path.exists():
        from .observed_run_registry import inspect_original
        registration = inspect_original(path)
        _verify_stored(path, packet)
        if registration['selection_id'] != digest:
            raise ValueError('Existing observed artifact has different semantics')
        return {'state': 'already_recorded', 'source_id': source_id, **registration}
    handle, temporary = tempfile.mkstemp(prefix='.observed-', suffix='.sqlite', dir=directory)
    os.close(handle)
    try:
        db = sqlite3.connect(temporary)
        try:
            db.executescript('''
CREATE TABLE metadata(key TEXT PRIMARY KEY,value_json TEXT NOT NULL);
CREATE TABLE source_documents(source_id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,document_json TEXT NOT NULL);
CREATE TABLE table_scopes(table_name TEXT PRIMARY KEY,scope TEXT NOT NULL);
CREATE TABLE fixtures(date TEXT,competition_id INTEGER,home_team_id INTEGER,away_team_id INTEGER,official_match_unique_id INTEGER);
CREATE TABLE match_periods(period TEXT PRIMARY KEY,start_tick INTEGER,end_tick INTEGER,source_id TEXT);
CREATE TABLE pass_actors(side_index INTEGER,stored_player_slot INTEGER,canonical_person_id INTEGER,person_name TEXT,identity_state TEXT,PRIMARY KEY(side_index,stored_player_slot));
CREATE TABLE completed_pass_events(event_id INTEGER PRIMARY KEY,side_index INTEGER,sender_slot INTEGER,receiver_slot INTEGER,sender_name TEXT,receiver_name TEXT,start_tick INTEGER,end_tick INTEGER,period TEXT,source_id TEXT);
CREATE TABLE native_pass_events(event_id INTEGER PRIMARY KEY,record_json TEXT NOT NULL);
CREATE TABLE tracking_sources(side_index INTEGER,stored_player_slot INTEGER,start_tick INTEGER,sample_step_native_ticks INTEGER,samples BLOB,PRIMARY KEY(side_index,stored_player_slot));
CREATE TABLE average_positions(team_native_id INTEGER,person_id INTEGER,person_name TEXT,phase TEXT,sample_count INTEGER,axis_0 REAL,axis_1 REAL,cursor INTEGER,coverage_json TEXT,source_id TEXT);
CREATE TABLE tracking_context(orientation_profile BLOB,possession_samples BLOB);
CREATE TABLE period_observations(source_index INTEGER PRIMARY KEY,record_json TEXT NOT NULL);
''')
            metadata = {'product_type': 'observed_native_match_run', 'schema_version': 1,
                'not_retained_match_export': True, 'registered_retained_capture': False,
                'producer': 'explicit_observed_prefix_recorder', 'selection_id': digest,
                'source_incarnation_id': packet['incarnation_id'], 'fixed_time_slice': packet['cursor'],
                'capture_state': 'partial_prefix', 'terminal_completeness_verified': False,
                'replay_exclusion_verified': False, 'native_clocks_are_displayed_minutes': False,
                'missing_scopes': (['full_match_completion', 'on_pitch_membership', 'native_PLAYER_statistics']
                    + ([] if any(row.get('shots') is not None for row in
                        packet.get('match_statistics_observation', {}).get('shots', {}).get('sides', [])) else ['shots'])
                    + ([] if packet.get('match_statistics_observation', {}).get('score', {}).get('current_score', {}).get('state') == 'available' else ['score'])),
                'match_statistics_collection_state': packet.get('match_statistics_observation', {}).get('state', 'not_collected'),
                'native_tracking_units': 'raw_int16_coordinate_pairs; metric distances unproved',
                'period_state': packet.get('period_state'),
                'period_reason': packet.get('period_reason'),
                'tactical_collection_state':packet.get('tactical_observation',{}).get('state','not_collected'),
                'assist_annotation_collection':packet.get('assist_annotation_collection',{'state':'not_collected'})}
            db.executemany('INSERT INTO metadata VALUES (?,?)', [(k, _json(v)) for k,v in metadata.items()])
            fixture = packet['fixture']
            db.execute('INSERT INTO fixtures(date,competition_id,home_team_id,away_team_id,official_match_unique_id) VALUES (?,?,?,?,?)', tuple(fixture[k] for k in
                ('date','competition_id','home_team_id','away_team_id','official_match_unique_id')))
            document = {'save': packet['save'], 'observed_at_unix': packet['observed_at_unix'],
                        'fixture': fixture, 'fixed_time_slice': packet['cursor'],
                        'verification': packet['verification'], 'terminal_completeness_verified': False}
            db.execute('INSERT INTO source_documents VALUES (?,?,?)', ('terminal', _sha(document), _json(document)))
            tactical = packet.get('tactical_observation')
            if tactical is not None:
                db.execute('INSERT INTO source_documents VALUES (?,?,?)', ('tactical_samples',_sha(tactical),_json(tactical)))
            attempts = packet.get('pass_attempt_observation')
            if attempts is not None:
                db.execute('INSERT INTO source_documents VALUES (?,?,?)', ('pass_attempt_samples',_sha(attempts),_json(attempts)))
            actors = {(a['side_index'],a['stored_player_slot']): a for a in packet['actors']}
            db.executemany('INSERT INTO pass_actors VALUES (?,?,?,?,?)',
                [(a['side_index'],a['stored_player_slot'],a.get('canonical_person_id'),a.get('person_name'),a.get('identity_state')) for a in actors.values()])
            for event in packet['events']:
                db.execute('INSERT INTO native_pass_events VALUES (?,?)', (event['event_id'], _json(event)))
                if event['category'] == 7 and not event['flags_word'] & 8:
                    side = event['side_index']
                    sender = actors.get((side,event['stored_player_slot']), {})
                    receiver = actors.get((side,event['recipient_slot']), {})
                    db.execute('INSERT INTO completed_pass_events VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (event['event_id'],side,event['stored_player_slot'],event['recipient_slot'],
                         sender.get('person_name'),receiver.get('person_name'),event['start'],event['end'],None,'terminal'))
            for row in packet['tracking']['players']:
                db.execute('INSERT INTO tracking_sources VALUES (?,?,?,?,?)',
                    (row['side_index'],row['stored_player_slot'],row['start_tick'],24,bytes.fromhex(row['samples_hex'])))
            from . import live_average_positions
            portable_tracking = {'players':[{**r,'samples':bytes.fromhex(r['samples_hex'])} for r in packet['tracking']['players']],
                'orientation_profile':bytes.fromhex(packet['tracking']['orientation_profile_hex']),
                'possession_samples':bytes.fromhex(packet['tracking']['possession_samples_hex'])}
            known = [a for a in actors.values() if a.get('person_name') and a.get('canonical_person_id')]
            keys = {(a['side_index'],a['stored_player_slot']) for a in known}
            portable_tracking['players'] = [r for r in portable_tracking['players'] if (r['side_index'],r['stored_player_slot']) in keys]
            averages = live_average_positions.decode_tracking_average_positions(portable_tracking, known)
            for row in averages['players']:
                team = fixture['home_team_id' if row['side_index']==0 else 'away_team_id']
                db.execute('INSERT INTO average_positions VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (team,row['canonical_person_id'],row['person_name'],'all',row['sample_count'],
                     row['native_axis_0'],row['native_axis_1'],packet['cursor'],_json(row['coverage']),'terminal'))
            db.execute('INSERT INTO tracking_context VALUES (?,?)',
                (bytes.fromhex(packet['tracking']['orientation_profile_hex']),bytes.fromhex(packet['tracking']['possession_samples_hex'])))
            for marker in packet['period_markers']:
                db.execute('INSERT INTO period_observations VALUES (?,?)', (marker['source_index'],_json(marker)))
            scopes = {'fixtures':'same-career current source fixture; score unavailable',
                'match_periods':'no classified periods in this recorder increment; empty is unknown',
                'pass_actors':'same-source original native slots; not active XI or future appearance',
                'completed_pass_events':'category7 without mask8; start<=end<fixed cursor; actor null remains unresolved',
                'average_positions':'official stored-sample means at same fixed prefix; zeros and post-exit tails included; unknown actors omitted; not on-pitch time or metres',
                'tracking_sources':'raw prefix samples at start+24*i<=fixed cursor; zero pairs preserved; no on-pitch inference',
                'period_observations':'native observed markers only; unknown period assignment preserved'}
            db.executemany('INSERT INTO table_scopes VALUES (?,?)', scopes.items())
            from .observed_run_match_statistics_store import write as write_statistics
            write_statistics(db, packet.get('match_statistics_observation'), _sha)
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise ValueError('Recorded artifact integrity failed')
        finally:
            db.close()
        with open(temporary, 'rb+') as stream:       # Windows refuses fsync on a read-only handle
            os.fsync(stream.fileno())
        # Hard-link publication is atomic and cannot overwrite a competing writer.
        try:
            os.link(temporary, path)
        except FileExistsError:
            from .observed_run_registry import inspect_original
            if inspect_original(path)['selection_id'] != digest:
                raise ValueError('Concurrent observed artifact collision')
        from .observed_run_registry import inspect_original
        _verify_stored(path, packet)
        return {'state': 'recorded', 'source_id': source_id, **inspect_original(path)}
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', required=True, help='Original host artifact directory (no copies)')
    parser.add_argument('--pid', type=int, help='Select one supported FM process explicitly')
    parser.add_argument('--register', action='store_true')
    parser.add_argument('--without-tactics', action='store_true', help='Skip optional resident settings observation')
    parser.add_argument('--include-incomplete-passes', action='store_true', help='Preserve attested native pass-attempt event points')
    args = parser.parse_args()
    from .bridge import Bridge
    bridge = Bridge()
    attached = bridge.attach(args.pid)
    try:
        packet = capture_prefix(bridge, attached['session_id'],include_tactics=not args.without_tactics,
                                include_incomplete_passes=args.include_incomplete_passes)
        if packet['state'] == 'unavailable':
            print(_json(packet)); return
        result = write_prefix(packet, args.store)
        if args.register:
            from .observed_run_registry import register_original
            from .observed_run_tactical_capture import attestation
            from .observed_pass_attempts import attestation as attempt_attestation
            proof = attempt_attestation(packet,result)
            options = {'pass_attempt_attestation': proof} if proof is not None else {}
            register_original(result['path'], result['source_id'], result['sha256'],producer_attestation=attestation(packet,result),**options)
        print(_json(result))
    finally:
        bridge.detach()


if __name__ == '__main__':
    main()
