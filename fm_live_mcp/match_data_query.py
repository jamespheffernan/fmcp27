"""Bounded in-memory projections of explicitly selected live match sources."""
from collections import OrderedDict
from datetime import datetime, timezone
import json
import secrets
import threading
import time

from .live_match_participation import LINEUP_POLICY

TABLES = ('fixtures', 'team_totals', 'events', 'player_matches', 'retained_players', 'goal_crossings', 'sub_entry_context')


class MatchDataQueries:
    """Keep pagination tied to one checked capture, never a disk evidence alias."""

    def __init__(self, capture=None, epoch=None):
        self.capture = capture or capture_live
        self.epoch = epoch or capture_epoch
        self.pages = OrderedDict()
        self.lock = threading.RLock()

    def query(self, bridge, session_id, fixture_refs, table, fields=None, limit=100, cursor=None):
        if (not isinstance(fixture_refs, list) or not 1 <= len(fixture_refs) <= 64
                or any(not isinstance(ref, str) or not ref for ref in fixture_refs)
                or len(set(fixture_refs)) != len(fixture_refs)):
            raise ValueError('Select 1–64 distinct live fixture_refs.')
        if table not in TABLES:
            raise ValueError(f'table must be one of {TABLES}')
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('limit must be 1–500.')
        if fields is not None and (not isinstance(fields, list) or not fields or
                any(not isinstance(field, str) for field in fields) or len(set(fields)) != len(fields)):
            raise ValueError('fields must be a nonempty list of distinct column names.')
        selectors = (session_id, tuple(fixture_refs), table, tuple(fields) if fields else None)
        with self.lock:
            now = time.monotonic()
            for token in list(self.pages):
                if now - self.pages[token]['created'] > 300:
                    del self.pages[token]
            if cursor is not None:
                page = self.pages.get(cursor)
                if page is None or page['selectors'] != selectors:
                    raise ValueError('Expired cursor or changed selectors; start a new capture.')
                if self.epoch(bridge, session_id) != page['epoch']:
                    del self.pages[cursor]
                    raise ValueError('Captured career/load epoch changed; start a new capture.')
                epoch = page['epoch']
                created = page['created']
                offset = page['offset']
                rows, metadata, columns = page['rows'], page['metadata'], page['columns']
            else:
                from .match_dataset import build_connection
                epoch = self.epoch(bridge, session_id)
                captured = (self.capture(bridge, session_id, fixture_refs, include_goal_crossings=True)
                            if table == 'goal_crossings' else self.capture(bridge, session_id, fixture_refs))
                if self.epoch(bridge, session_id) != epoch:
                    raise ValueError('Career/load epoch changed during capture.')
                captured['capture']['observed_at'] = datetime.now(timezone.utc).isoformat()
                db = build_connection(captured['capture'], captured.get('player_rows', ()),
                                      source='live_selected_fixtures', team_totals=captured.get('team_totals'),
                                      retained_players=captured.get('retained_players', ()),
                                      goal_crossings=captured.get('goal_crossings', ()),
                                      entry_state_policy=captured['capture'].get('entry_state_policy'))
                try:
                    columns = [row[1] for row in db.execute(f'PRAGMA table_info({table})')]
                    if fields is not None and any(field not in columns for field in fields):
                        raise ValueError(f'Supported fields for {table}: {columns}')
                    columns = fields or columns
                    # Identifiers are selected only from schema names above.
                    result = db.execute('SELECT '+','.join('"'+c+'"' for c in columns)+' FROM '+table)
                    rows = [dict(zip(columns, row)) for row in result]
                    for row in rows:
                        if 'raw_json' in row:
                            row['raw_json'] = json.loads(row['raw_json'])
                    metadata = {key: json.loads(value) for key, value in db.execute('SELECT key,value_json FROM metadata')}
                    metadata['coverage'] = [dict(source=s, state=st, raw=json.loads(raw)) for s,st,raw in db.execute('SELECT * FROM coverage')]
                finally:
                    db.close()
                offset = 0
                created = now
            end = offset
            response_bytes = 0
            for row in rows[offset:offset + limit]:
                size = len(json.dumps(row, ensure_ascii=False).encode())
                if size > 262144:
                    raise ValueError('One row exceeds response budget; select fewer fields.')
                if response_bytes + size > 262144:
                    break
                response_bytes += size
                end += 1
            next_cursor = None
            if end < len(rows):
                next_cursor = secrets.token_urlsafe(24)
                self.pages[next_cursor] = dict(selectors=selectors, rows=rows, metadata=metadata,
                                              columns=columns, offset=end, created=created, epoch=epoch)
                while len(self.pages) > 32:
                    self.pages.popitem(last=False)
            return dict(session_id=session_id, table=table, fields=columns, rows=rows[offset:end],
                        row_count=len(rows), next_cursor=next_cursor, metadata=metadata,
                        observed_at=metadata.get('observed_at'), captured_save=metadata.get('save'),
                        historical_lineup_policy=dict(LINEUP_POLICY),
                        claim='Captured selected live fixture sources only; missing values remain unknown.')


def capture_epoch(bridge, session_id):
    # get_save verifies the native world identity and clears the session on reload.
    # Its mutable simulation date is deliberately excluded from this epoch.
    bridge.get_save(session_id)
    process = bridge.process
    return (session_id, process.pid, process.executable, process.version, bridge.world_identity)


def capture_live(bridge, session_id, fixture_refs, *, include_players=True, include_goal_crossings=False):
    """Keep each native read stream bounded without dropping selected fixtures."""
    if not isinstance(fixture_refs, list) or not 1 <= len(fixture_refs) <= 64:
        raise ValueError('Select 1–64 live fixture references.')
    epoch = capture_epoch(bridge, session_id)
    include_players = include_players or include_goal_crossings
    size = 16 if include_players else 64
    combined = None
    for at in range(0, len(fixture_refs), size):
        batch = _capture_live_batch(bridge, session_id, fixture_refs[at:at+size], include_players=include_players, include_goal_crossings=include_goal_crossings)
        if combined is None:
            combined = batch
            continue
        if batch['capture']['save'] != combined['capture']['save']:
            raise ValueError('Save changed during selected-frame capture; no partial capture returned.')
        combined['capture']['fixtures'].extend(batch['capture']['fixtures'])
        combined['retained_players'].extend(batch['retained_players'])
        combined['team_totals']['records'].extend(batch['team_totals']['records'])
        combined['raw_frames'].extend(batch['raw_frames'])
        combined.setdefault('goal_crossings', []).extend(batch.get('goal_crossings', ()))
    if capture_epoch(bridge, session_id) != epoch:
        raise ValueError('Career/load epoch changed during selected capture')
    combined['_live_capture_epoch'] = epoch
    return combined


def _capture_live_batch(bridge, session_id, fixture_refs, *, include_players=True, include_goal_crossings=False):
    from .live_match_backing import read_selected_matches
    from .live_match_team_totals import decode_team_totals, crossing_field_registry as team_crossing_registry
    from .live_match_players import decode_retained_players
    from .saved_match_player_actions import decode_player_actions, field_registry
    from .saved_match_player_defensive import decode_player_defensive, field_registry as defensive_registry
    from .saved_match_player_crosses import decode_player_crosses, cross_field_registry
    from .saved_match_player_keeper import decode_player_keeper, field_registry as keeper_registry
    from .match_player_position import field_registry as position_registry
    from .saved_match_player_recoveries import decode_player_recoveries, recovery_field_registry, pressure_completion_fields
    from .saved_match_player_progression import decode_player_progression, progression_field_registry
    from .saved_match_player_dribbling import decode_player_dribbling, dribbling_field_registry
    from .saved_match_player_running import decode_player_running, running_field_registry
    from .saved_match_player_sprinting import decode_player_sprinting, sprinting_field_registry
    from .saved_match_player_final_third import decode_player_final_third, final_third_field_registry
    from .saved_match_player_free_kicks import decode_player_free_kicks, free_kick_field_registry
    from .live_match_identities import join
    backing = read_selected_matches(bridge, session_id, fixture_refs, include_players=include_players)
    fixtures = []
    totals = []
    retained = []
    crossings = []
    for record in backing['records']:
        fixture = dict(record['fixture_native'], fixture_ref=record['fixture_ref'])
        fixtures.append(dict(fixture=fixture, native_match_key=record.get('key'),
                             event_array=record.get('event_array', {'state': 'not_captured'}),
                             source={k:v for k,v in record.items() if k not in ('raw', 'fixture_native', 'identities', 'event_array')}))
        if record.get('state') == 'available':
            totals.append(decode_team_totals(record['raw']))
            rows = decode_retained_players(record['raw'], record['key']) if include_players else []
            if record.get('identities') is not None:
                rows = join(rows, record['identities'])
            for row in rows:
                row.update(decode_player_actions(bytes.fromhex(row['raw_child_hex'])))
                row.update(decode_player_defensive(bytes.fromhex(row['raw_child_hex'])))
                row.update(decode_player_crosses(bytes.fromhex(row['raw_child_hex'])))
                row.update(decode_player_keeper(bytes.fromhex(row['raw_child_hex'])))
                row.update(decode_player_recoveries(bytes.fromhex(row['raw_child_hex'])))
                row.update(pressure_completion_fields(row))
                row.update(decode_player_progression(bytes.fromhex(row['raw_child_hex'])))
                row.update(decode_player_dribbling(bytes.fromhex(row['raw_child_hex'])))
                row.update(decode_player_running(bytes.fromhex(row['raw_child_hex'])))
                row.update(decode_player_sprinting(bytes.fromhex(row['raw_child_hex'])))
                row.update(decode_player_final_third(bytes.fromhex(row['raw_child_hex'])))
                row.update(decode_player_free_kicks(bytes.fromhex(row['raw_child_hex'])))
                row['unknown_semantics'] = [name for name in row.get('unknown_semantics', ())
                                            if name not in ('shots', 'passes', 'tackles', 'interceptions', 'clearances', 'crosses', 'saves', 'distance', 'sprints', 'open_play_final_third_passes')]
                row['native_match_key'] = record['key']
                row.setdefault('identity_state', 'unresolved_source_local_identity')
                retained.append(row)
            if include_goal_crossings:
                from .saved_goal_crossings import decode_frame
                scores = (fixture.get('scores') or {}).get('final_score') or {}
                scoreline = [scores.get('home'), scores.get('away')]
                if not all(type(value) is int for value in scoreline):
                    scoreline = None
                decoded = decode_frame(record['raw'], record['key'], scoreline=scoreline)
                people = (record.get('identities') or {}).get('people', {})
                for crossing in decoded['goal_crossings']:
                    person = people.get(crossing['scorer_person_index'], {})
                    crossing.update(canonical_scorer_id=person.get('native_id'),
                                    scorer_name=person.get('display_name') or person.get('name'),
                                    identity_state='same_snapshot_canonical_PERSON' if person.get('native_id') is not None else 'unresolved_source_local_word')
                crossings.append(decoded)
        elif include_goal_crossings:
            crossings.append(dict(fixture_key=record['key'], goal_crossings=[],
                                  source_state=record['state'], coverage={'scope':'credited-player goal-line crossings only','source_state':record['state'],'complete_scoreline_goals':None}))
    from .match_entry_state import SOURCE_POLICY
    from . import players
    entry_policy = SOURCE_POLICY if include_players and backing.get('source_kind') == 'running_session_active_fd' and bridge.process.version == players.VERSION else None
    return dict(capture=dict(save=backing['save'], fixtures=fixtures,
                             source_kind=backing.get('source_kind'),
                             entry_state_policy=entry_policy,
                             sub_entry_context_coverage='source_policy_and_fixture_tallies_checked' if entry_policy else 'unverified_source_policy',
                             entry_state_policy_provenance={'runtime_version': players.VERSION, 'native_producer_rva': '0x2E552AC', 'scoring_kinds': [0,1,2], 'player_credit_kinds': [0,2]} if entry_policy else None,
                             goal_crossing_coverage='per_fixture_credited_goal_coverage' if include_goal_crossings else 'not_requested',
                             action_field_provenance={**field_registry(), **defensive_registry(), **cross_field_registry(), **keeper_registry(), **recovery_field_registry(), **progression_field_registry(), **dribbling_field_registry(), **running_field_registry(), **sprinting_field_registry(), **final_third_field_registry(), **free_kick_field_registry(), **position_registry()},
                             team_field_provenance=team_crossing_registry(),
                             player_coverage='retained_rows_identity_state_per_row' if include_players else 'not_requested',
                             player_ring_coverage='not_captured',
                             event_coverage='per_fixture_event_array_state',
                             spatial_coverage='unsupported_semantics'),
                team_totals={'records': totals}, retained_players=retained, goal_crossings=crossings,
                raw_frames=[{k:v for k,v in record.items() if k not in ('fixture_native', 'identities', 'event_array')}
                            for record in backing['records'] if record.get('state') == 'available'])
