"""Normalize checked retained-shot packets with exact fixture ownership.

Unavailable sources keep NULL counts. Raw native coordinates are never rotated,
scaled or assigned a viewpoint. Own-goal markers remain outside shot attempts.
"""
import json
import math


SIDES = ('home_team', 'away_team')
SHOT_DETAIL_COLUMNS = (
    'event_id', 'native_category_code', 'body_part', 'is_header', 'body_part_state',
    'outcome', 'native_outcome_label', 'outcome_state', 'native_location_bin',
    'official_location', 'location_group', 'location_state',
    'attacked_goal_positive_native_y',
)



def _identity(fixture, *, require_complete=False):
    values = [fixture.get('date'), (fixture.get('competition') or {}).get('native_id')]
    for name in SIDES:
        team = fixture.get(name) or {}
        values.extend((team.get('native_id'), team.get('database_index'), team.get('native_type_code')))
    if (not isinstance(values[0], str) or not values[0]
            or any(value is not None and type(value) is not int for value in values[1:])
            or (require_complete and any(type(values[index]) is not int for index in (1, 2, 3, 5, 6)))):
        raise ValueError('Shot map requires a fully bound fixture date, competition and home/away team identities')
    return tuple(values)


def _number(row, name):
    value = row.get(name)
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
        raise ValueError(f'Shot map {name} must be finite or unknown')
    return value


def _index(row, name):
    value = row.get(name)
    if type(value) is not int or value < 0:
        raise ValueError(f'Shot map {name} must be a nonnegative integer')
    return value


def _penalty_fields(row):
    native = row.get('native_shot_type')
    penalty = row.get('is_penalty')
    situation = row.get('shot_situation')
    state = row.get('shot_situation_state')
    if native is not None and (type(native) is not int or native < 0):
        raise ValueError('Native shot type must be a nonnegative integer or unknown')
    if penalty is not None and type(penalty) is not bool:
        raise ValueError('Penalty selection must be a checked boolean or unknown')
    if situation not in (None,'penalty','non_penalty_unspecified'):
        raise ValueError('Unsupported shot situation label')
    if state is not None and (not isinstance(state,str) or not state):
        raise ValueError('Shot situation state must be explicit or unknown')
    return native,penalty,situation,state



def _detail_fields(row):
    from .retained_shot_location import LOCATION_NAMES
    for name in ('event_id', 'native_category_code', 'native_location_bin'):
        if row.get(name) is not None:
            _index(row, name)
    for name in ('is_header', 'attacked_goal_positive_native_y'):
        if row.get(name) is not None and type(row[name]) is not bool:
            raise ValueError(f'Shot map {name} must be a checked boolean or unknown')
    if row.get('body_part') not in (None, 'head', 'feet'):
        raise ValueError('Unsupported shot body-part label')
    if row.get('body_part') is not None and row.get('is_header') is not None and row['is_header'] != (row['body_part'] == 'head'):
        raise ValueError('Shot header classification disagrees with body part')
    if row.get('outcome') not in (None, 'goal', 'missed_target', 'hit_woodwork', 'saved', 'blocked'):
        raise ValueError('Unsupported exclusive shot outcome')
    outcome_pairs = {1: ('goal','CBE_END_SHOT_GONE_IN'), 2: ('missed_target','CBE_END_SHOT_MISSED_TARGET'),
                     3: ('hit_woodwork','CBE_END_SHOT_HIT_WOODWORK'), 4: ('saved','CBE_END_SHOT_SAVED'),
                     5: ('blocked','CBE_END_SHOT_BLOCKED')}
    expected = outcome_pairs.get(row.get('native_category_code'))
    if expected and (row.get('outcome') not in (None, expected[0]) or row.get('native_outcome_label') not in (None, expected[1])):
        raise ValueError('Shot outcome label disagrees with native category')
    if row.get('native_category_code') is not None and expected is None and row.get('outcome') is not None:
        raise ValueError('Unmapped native category cannot claim a named exclusive outcome')
    index = row.get('native_location_bin')
    if index is not None:
        if index >= len(LOCATION_NAMES):
            raise ValueError('Unsupported native shot-location bin')
        expected_group = 'inside_area' if index < 6 else 'outside_area' if index < 12 else 'outside_area_or_native_fallback'
        if row.get('official_location') not in (None, LOCATION_NAMES[index]) or row.get('location_group') not in (None, expected_group):
            raise ValueError('Shot location label/group disagrees with native bin')
    elif row.get('official_location') is not None or row.get('location_group') is not None:
        raise ValueError('Shot location labels require their native bin')
    for name in ('body_part_state', 'outcome_state', 'native_outcome_label', 'location_state'):
        if row.get(name) is not None and (not isinstance(row[name], str) or not row[name]):
            raise ValueError(f'Shot map {name} must be explicit or unknown')
    return tuple(row.get(name) for name in SHOT_DETAIL_COLUMNS)


def _field_coverage(packet, rows, source_state):
    groups = {
        'location': ('location_provenance', lambda r: r.get('native_location_bin') is not None and r.get('location_state') == 'native_renderer_predicate'),
        'body_part': ('body_part_policy', lambda r: r.get('body_part') is not None and r.get('is_header') is not None),
        'outcome': ('outcome_policy', lambda r: r.get('outcome') is not None and r.get('outcome_state') == 'official_native_end_shot_category'),
    }
    for group, (policy, known) in groups.items():
        if source_state != 'available':
            yield group, 'unavailable_source', None, None
            continue
        count = sum(known(row) for row in rows)
        declared = bool(packet and packet.get(policy) and (group != 'location' or packet.get('pitch_geometry')))
        if not rows and not declared:
            yield group, 'not_captured', None, None
        else:
            state = 'complete' if count == len(rows) else 'partial' if count else 'not_captured'
            # A captured but unmapped source differs from an old missing field.
            if count == 0 and any(row.get({'location':'location_state','body_part':'body_part_state','outcome':'outcome_state'}[group]) for row in rows):
                state = 'unclassified'
            yield group, state, count, len(rows)-count


def write_shot_maps(db, capture, selected, packets):
    """Insert already checked packets; mismatched identities reject the export."""
    packets = list(packets)
    observed_requested = capture.get('source_observed_shots_requested') is True or any(p.get('source_observed_policy') for p in packets)
    db.executescript('''
    CREATE TABLE shot_map_coverage(
      fixture_id TEXT NOT NULL REFERENCES fixtures(fixture_id),
      native_match_key INTEGER,side_index INTEGER NOT NULL CHECK(side_index IN (0,1)),
      team_native_id INTEGER,team_index INTEGER,source_id TEXT,state TEXT NOT NULL,
      shot_count INTEGER,shots_on_target INTEGER,expected_goals REAL,
      own_goal_marker_count INTEGER,raw_json TEXT NOT NULL,
      pitch_half_width_native REAL,pitch_half_length_native REAL,
      PRIMARY KEY(fixture_id,side_index));
    CREATE TABLE shots(
      fixture_id TEXT NOT NULL REFERENCES fixtures(fixture_id),native_match_key INTEGER,
      side_index INTEGER NOT NULL CHECK(side_index IN (0,1)),record_index INTEGER NOT NULL,
      source_id TEXT,native_x REAL,native_y REAL,expected_goals REAL,
      native_shot_type INTEGER,is_penalty INTEGER,shot_situation TEXT,shot_situation_state TEXT,raw_json TEXT NOT NULL,
      event_id INTEGER,native_category_code INTEGER,body_part TEXT,is_header INTEGER,body_part_state TEXT,
      outcome TEXT,native_outcome_label TEXT,outcome_state TEXT,native_location_bin INTEGER,
      official_location TEXT,location_group TEXT,location_state TEXT,attacked_goal_positive_native_y INTEGER,
      PRIMARY KEY(fixture_id,side_index,record_index));
    CREATE TABLE own_goal_markers(
      fixture_id TEXT NOT NULL REFERENCES fixtures(fixture_id),native_match_key INTEGER,
      beneficiary_side_index INTEGER NOT NULL CHECK(beneficiary_side_index IN (0,1)),
      event_side_index INTEGER,record_index INTEGER NOT NULL,source_id TEXT,
      native_x REAL,native_y REAL,native_expected_goals REAL,raw_json TEXT NOT NULL,
      PRIMARY KEY(fixture_id,beneficiary_side_index,record_index));
    CREATE TABLE shot_field_coverage(
      fixture_id TEXT NOT NULL REFERENCES fixtures(fixture_id),side_index INTEGER NOT NULL CHECK(side_index IN (0,1)),
      field_group TEXT NOT NULL,state TEXT NOT NULL,known_attempt_count INTEGER,unknown_attempt_count INTEGER,
      PRIMARY KEY(fixture_id,side_index,field_group));
    CREATE VIEW shot_attempt_analysis AS
      SELECT f.date,f.competition,f.home_team,f.away_team,s.*,c.state AS shot_source_state
      FROM shots s JOIN fixtures f USING(fixture_id)
      JOIN shot_map_coverage c USING(fixture_id,side_index);
    CREATE VIEW shot_map_analysis AS
      SELECT f.date,f.competition,f.home_team,f.away_team,c.*
      FROM shot_map_coverage c JOIN fixtures f USING(fixture_id);
    ''')
    if observed_requested:
        from .match_observed_shot_dataset import create_tables
        create_tables(db)
    db.execute('PRAGMA foreign_keys=ON')
    dump = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True)
    db.execute('INSERT INTO metadata VALUES (?,?)', ('shot_map_semantics', dump({
        'source': 'checked retained HUMAN shot-cache vectors joined to exact fixture identity',
        'coordinates': 'raw native_x/native_y; units and orientation unverified',
        'actors_and_clocks': 'not normalized by this export',
        'own_goals': 'separate credited-side marker rows; excluded from shot attempts',
        'missing_counts': 'NULL is unavailable; zero requires available reconciled source coverage'})))
    db.execute('INSERT INTO metadata VALUES (?,?)', ('shot_map_schema_revision', dump(3 if observed_requested else 2)))
    selected_refs = {}
    fixture_keys = dict(db.execute('SELECT fixture_id,native_match_key FROM fixtures'))
    all_refs = {}
    for item in capture.get('fixtures', ()):
        fixture = item.get('fixture', item)
        ref = fixture.get('fixture_ref')
        if ref: all_refs.setdefault(ref, []).append((fixture, item.get('native_match_key')))
    for fid, fixture in selected:
        ref = fixture.get('fixture_ref')
        if ref: selected_refs.setdefault(ref, []).append((fid, fixture))
    bound = {}
    for packet in packets:
        fixture = packet.get('fixture') or {}
        ref = packet.get('fixture_ref') or fixture.get('fixture_ref')
        candidates = all_refs.get(ref, ())
        if len(candidates) != 1:
            raise ValueError('Shot map requires one exact captured fixture reference')
        original, key = candidates[0]
        complete=any(side.get('state')=='available' for side in packet.get('side_coverage',()))
        if (fixture.get('fixture_ref', ref) != ref or _identity(fixture,require_complete=complete) != _identity(original,require_complete=complete)
                or packet.get('native_match_key') != key):
            raise ValueError('Shot map fixture identity or native match key disagrees with capture')
        if ref in bound: raise ValueError('Duplicate shot map packets for one fixture')
        bound[ref] = packet
    for fid, fixture in selected:
        key = fixture_keys[fid]
        ref = fixture.get('fixture_ref')
        packet = bound.get(ref)
        if packet is not None and len(selected_refs[ref]) != 1:
            raise ValueError('Shot map fixture reference is ambiguous in selected rows')
        source_id = packet.get('source_id') if packet else None
        sides = {}
        if packet:
            for coverage in packet.get('side_coverage', ()):
                side = coverage.get('side_index')
                if type(side) is not int or side not in (0, 1) or side in sides:
                    raise ValueError('Shot map must provide distinct home and away coverage')
                sides[side] = coverage
            if set(sides) != {0, 1}:
                raise ValueError('Shot map must provide both fixture sides even when unavailable')
        attempts = {0: [], 1: []}
        markers = {0: [], 1: []}
        for row in packet.get('shots', ()) if packet else ():
            side = row.get('side_index')
            if type(side) is not int or side not in attempts:
                raise ValueError('Shot attempt has an unsupported fixture side')
            if row.get('native_category_code')==49 or row.get('statistical_shot') is False or row.get('kind')=='own_goal_marker':
                raise ValueError('Own-goal markers must remain separate from statistical attempts')
            if row.get('event_side_index',side)!=side:
                raise ValueError('Shot event side differs from the fixture team side')
            attempts[side].append(row)
        for row in packet.get('own_goal_markers', ()) if packet else ():
            side = row.get('beneficiary_side_index')
            event_side = row.get('event_side_index')
            if type(side) is not int or side not in markers or (event_side is not None and (type(event_side) is not int or event_side not in (0, 1))):
                raise ValueError('Own-goal marker has an unsupported side identity')
            if event_side is not None and event_side==side:
                raise ValueError('Own-goal marker event side cannot equal its beneficiary side')
            markers[side].append(row)
        for side in (0, 1):
            coverage = sides.get(side, {'side_index': side, 'state': 'not_captured'})
            state = coverage.get('state')
            if not isinstance(state, str) or not state:
                raise ValueError('Shot source coverage requires an explicit state')
            counts = tuple(coverage.get(name) for name in ('shot_count','shots_on_target','expected_goals','own_goal_marker_count'))
            if state == 'available':
                if any(type(counts[index]) is not int or counts[index] < 0 for index in (0, 1, 3)) or counts[2] is None:
                    raise ValueError('Available shot coverage requires reconciled non-null counts')
                if counts[1] > counts[0]:
                    raise ValueError('Shot targets exceed the reconciled attempt count')
                if not isinstance(source_id, str) or not source_id:
                    raise ValueError('Available shot coverage requires its checked source identity')
                if counts[0] != len(attempts[side]) or counts[3] != len(markers[side]):
                    raise ValueError('Normalized shot and own-goal counts disagree with coverage')
                _number(coverage, 'expected_goals')
            elif any(value is not None for value in counts) or attempts[side] or markers[side]:
                raise ValueError('Unavailable shot sources must keep null counts and no normalized rows')
            team = fixture.get(SIDES[side]) or {}
            for supplied,expected in (('team_native_id',team.get('native_id')),('team_index',team.get('database_index'))):
                if coverage.get(supplied) is not None and coverage[supplied]!=expected:
                    raise ValueError('Shot side coverage differs from canonical fixture TEAM identity')
            geometry = (packet or {}).get('pitch_geometry') or {}
            dimensions = tuple(_number(geometry, name) if state == 'available' else None
                               for name in ('half_width_native', 'half_length_native'))
            db.execute('INSERT INTO shot_map_coverage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (fid,key,side,team.get('native_id'),team.get('database_index'),source_id,state,*counts,dump(coverage),*dimensions))
            for group, field_state, known, unknown in _field_coverage(packet, attempts[side], state):
                db.execute('INSERT INTO shot_field_coverage VALUES (?,?,?,?,?,?)',
                           (fid,side,group,field_state,known,unknown))
            for row in attempts[side]:
                index = _index(row, 'record_index')
                db.execute('INSERT INTO shots VALUES ('+','.join('?' for _ in range(13+len(SHOT_DETAIL_COLUMNS)))+')',
                    (fid,key,side,index,source_id,_number(row,'native_x'),_number(row,'native_y'),_number(row,'expected_goals'),*_penalty_fields(row),dump(row),*_detail_fields(row)))
            for row in markers[side]:
                index = _index(row, 'record_index')
                db.execute('INSERT INTO own_goal_markers VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (fid,key,side,row.get('event_side_index'),index,source_id,_number(row,'native_x'),_number(row,'native_y'),_number(row,'native_expected_goals'),dump(row)))
        if observed_requested:
            from .match_observed_shot_dataset import write_observed
            write_observed(db, fid, key, fixture, packet, sides, source_id)
        db.execute('INSERT INTO coverage VALUES (?,?,?)', ('shot_map',packet.get('state','captured') if packet else 'not_captured',dump(packet or {'fixture_ref':ref,'state':'not_captured'})))
