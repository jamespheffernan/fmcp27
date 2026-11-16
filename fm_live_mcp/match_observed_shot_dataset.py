"""Optional source observations remain separate from strictly reconciled shots."""
import json

SCOPE = 'source_observed_counts_actors_verified_xg_unreconciled'
AVAILABLE = 'available_source_observed_counts_verified_xg_unreconciled'


def create_tables(db):
    db.executescript('''
    CREATE TABLE source_observed_shots(
      fixture_id TEXT NOT NULL REFERENCES fixtures(fixture_id),native_match_key INTEGER,
      side_index INTEGER NOT NULL CHECK(side_index IN(0,1)),record_index INTEGER NOT NULL,
      source_id TEXT,native_x REAL,native_y REAL,native_expected_goals REAL,
      native_shot_type INTEGER,is_penalty INTEGER,shot_situation TEXT,shot_situation_state TEXT,raw_json TEXT NOT NULL,
      event_id INTEGER,native_category_code INTEGER,body_part TEXT,is_header INTEGER,body_part_state TEXT,
      outcome TEXT,native_outcome_label TEXT,outcome_state TEXT,native_location_bin INTEGER,
      official_location TEXT,location_group TEXT,location_state TEXT,attacked_goal_positive_native_y INTEGER,
      stored_player_slot INTEGER,canonical_person_id INTEGER,person_name TEXT,verification_scope TEXT NOT NULL,
      team_xg_ulp_distance INTEGER,player_xg_ulp_distance INTEGER,player_nonpenalty_xg_ulp_distance INTEGER,
      PRIMARY KEY(fixture_id,side_index,record_index));
    CREATE TABLE source_observed_shot_coverage(
      fixture_id TEXT NOT NULL REFERENCES fixtures(fixture_id),native_match_key INTEGER,
      side_index INTEGER NOT NULL CHECK(side_index IN(0,1)),source_id TEXT,state TEXT NOT NULL,
      strict_side_state TEXT NOT NULL,observed_shot_count INTEGER,
      rostered_players_checked INTEGER,zero_shot_players_checked INTEGER,
      team_xg_ulp_distance INTEGER,verified_shots_promoted INTEGER,xg_tolerance_widened INTEGER,
      raw_json TEXT NOT NULL,PRIMARY KEY(fixture_id,side_index));
    CREATE TABLE source_observed_field_coverage(
      fixture_id TEXT NOT NULL REFERENCES fixtures(fixture_id),side_index INTEGER NOT NULL CHECK(side_index IN(0,1)),
      field_group TEXT NOT NULL,state TEXT NOT NULL,known_attempt_count INTEGER,unknown_attempt_count INTEGER,
      PRIMARY KEY(fixture_id,side_index,field_group));
    CREATE VIEW source_observed_shot_analysis AS
      SELECT f.date,f.competition,f.home_team,f.away_team,s.* FROM source_observed_shots s
      JOIN fixtures f USING(fixture_id);
    ''')


def write_observed(db, fid, key, fixture, packet, strict_sides, source_id):
    from .match_shot_dataset import _detail_fields, _field_coverage, _index, _number, _penalty_fields
    dump = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True)
    packet = packet or {}
    rows = {0: [], 1: []}
    coverage = {}
    for item in packet.get('source_observed_coverage', ()):
        side = item.get('side_index')
        if type(side) is not int or side not in rows or side in coverage:
            raise ValueError('Source-observed coverage requires distinct fixture sides')
        coverage[side] = item
    for row in packet.get('source_observed_shots', ()):
        side = row.get('side_index')
        if type(side) is not int or side not in rows or row.get('event_side_index') != side:
            raise ValueError('Source-observed attempt side is not bound to its fixture')
        if row.get('native_category_code') == 49 or 'expected_goals' in row or row.get('verification_scope') != SCOPE:
            raise ValueError('Source-observed rows must retain their distinct unreconciled xG scope')
        rows[side].append(row)
    for side in (0, 1):
        strict = strict_sides.get(side, {'state': 'not_captured'})['state']
        item = coverage.get(side)
        if strict == 'available':
            if rows[side] or item:
                raise ValueError('Source observations cannot duplicate a strictly available side')
            item = {'state': 'not_needed_strict_side_available', 'observed_shot_count': 0}
        elif item is None:
            if rows[side]:
                raise ValueError('Source-observed rows require explicit verification coverage')
            item = {'state': 'unavailable_source_observed_verification', 'observed_shot_count': None,
                    'unavailable_reason': strict}
        state = item.get('state')
        if not isinstance(state, str) or not state:
            raise ValueError('Source observations need an explicit verification state')
        available = state == AVAILABLE
        count = item.get('observed_shot_count')
        if available:
            if type(count) is not int or count < 0 or count != len(rows[side]) or not source_id:
                raise ValueError('Source-observed counts differ from their separate collection')
            if item.get('verified_shots_promoted') is not False or item.get('xg_tolerance_widened') is not False:
                raise ValueError('Observed rows cannot widen strict reconciliation or promote shots')
            rostered = _index(item, 'rostered_players_checked')
            zero = _index(item, 'zero_shot_players_checked')
            if zero > rostered:
                raise ValueError('Source-observed independent player coverage is inconsistent')
        else:
            if rows[side] or (state != 'not_needed_strict_side_available' and count is not None):
                raise ValueError('Unverified source observations require null counts and no rows')
            rostered = zero = None
        diagnostic = item.get('team_xg_diagnostic') or {}
        team_ulps = diagnostic.get('xg_float32_ulp_distance')
        if team_ulps is not None:
            _index(diagnostic, 'xg_float32_ulp_distance')
        db.execute('INSERT INTO source_observed_shot_coverage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (fid,key,side,source_id,state,strict,count,rostered,zero,team_ulps,
                    item.get('verified_shots_promoted'),item.get('xg_tolerance_widened'),dump(item)))
        for group, field_state, known, unknown in _field_coverage(packet, rows[side], 'available' if available else 'unavailable'):
            if state == 'not_needed_strict_side_available':
                field_state, known, unknown = 'not_applicable_strict_side_available', 0, 0
            db.execute('INSERT INTO source_observed_field_coverage VALUES (?,?,?,?,?,?)',
                       (fid,side,group,field_state,known,unknown))
        expected_team = (fixture.get('home_team' if side == 0 else 'away_team') or {}).get('native_id')
        seen_events = set()
        for row in rows[side]:
            event_id = _index(row, 'event_id')
            if event_id in seen_events:
                raise ValueError('Source-observed event identity is ambiguous')
            seen_events.add(event_id)
            actor = row.get('actor') or {}
            pid = actor.get('canonical_person_id')
            if (type(pid) is not int or pid <= 0 or actor.get('canonical_team_id') != expected_team
                    or not isinstance(actor.get('person_name'), str) or not actor['person_name']):
                raise ValueError('Source-observed actor requires the exact canonical fixture PERSON/TEAM binding')
            native_xg = _number(row, 'native_expected_goals')
            if native_xg is None or not 0 <= native_xg <= 1:
                raise ValueError('Source-observed native xG must remain a bounded source value')
            reconciliation = row.get('xg_reconciliation') or {}
            ulps = []
            for name in ('team_float32_ulp_distance','player_float32_ulp_distance','player_nonpenalty_float32_ulp_distance'):
                value = reconciliation.get(name)
                if value is not None:
                    _index(reconciliation, name)
                ulps.append(value)
            if ulps[0] != team_ulps:
                raise ValueError('Source-observed row and side xG diagnostics disagree')
            values = (fid,key,side,_index(row,'record_index'),source_id,_number(row,'native_x'),_number(row,'native_y'),native_xg,
                      *_penalty_fields(row),dump(row),*_detail_fields(row),_index(row,'stored_player_slot'),pid,actor['person_name'],SCOPE,*ulps)
            db.execute('INSERT INTO source_observed_shots VALUES ('+','.join('?'for _ in values)+')',values)
