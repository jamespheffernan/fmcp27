"""Additive observed-run tables for cursor-bound attempts and official score."""
import json

SOURCE_ID = 'match_statistics_samples'
COLUMNS = {
    'shots': ('event_id', 'side_index', 'native_actor_slot', 'actor_name',
        'native_clock_start_raw', 'native_clock_end_raw', 'period', 'expected_goals',
        'outcome', 'body_part', 'native_x', 'native_y', 'record_json', 'source_id'),
    'own_goal_markers': ('event_id', 'event_side_index', 'beneficiary_side_index',
        'native_actor_slot', 'actor_name', 'native_clock_start_raw',
        'native_clock_end_raw', 'record_json', 'source_id'),
    'player_shot_statistics': ('side_index', 'native_actor_slot', 'canonical_person_id',
        'person_index_word', 'person_name', 'identity_state', 'shots',
        'shots_on_target', 'shot_goals', 'expected_goals_sum_computed',
        'counter_scope', 'fixed_time_slice', 'source_id'),
    'score_snapshots': ('scope', 'state', 'home_goals', 'away_goals',
        'at_time_slice', 'boundary_policy', 'source_id'),
    'match_prefix_team_totals': ('side_index', 'state', 'shots', 'shots_on_target',
        'shot_goals', 'expected_goals_sum_computed', 'fixed_time_slice', 'source_id'),
    'match_period_team_totals': ('period', 'side_index', 'shots', 'shots_on_target',
        'shot_goals', 'expected_goals_sum_computed'),
}
SCOPES = {
    'shots': 'Independently count-reconciled native attempts; start<=end<fixed cursor; per-side xG stays null when its separate reconciliation fails; period and actor may be unknown.',
    'own_goal_markers': 'Separate native own-goal markers ending strictly before cursor; beneficiary differs from event side; not attempts or independently certified scorer attribution.',
    'player_shot_statistics': 'Event-derived completed-attempt counts by original side/slot; canonical PERSON may be null; NOT native PLAYER totals, minutes, rating, assists or on-pitch membership.',
    'score_snapshots': 'Official ledger score at time<=fixed cursor, independently of strict ended-before-cursor attempts; those boundaries may legitimately disagree; no completion claim.',
    'match_prefix_team_totals': 'Derived reconciled attempt prefix at fixed cursor; null side metrics are unknown, never zero; not engine-frontier cumulative counters.',
    'match_period_team_totals': 'Derived attempts wholly inside verified native stop intervals and before fixed cursor; not an independent official half aggregate; no invented period for unknown boundaries.',
}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def rows(document):
    result = {name: [] for name in COLUMNS}
    chances = document['shots']
    for row in chances['shots']:
        actor = row.get('actor') or {}
        result['shots'].append((row['event_id'], row['side_index'], row['native_actor_slot'],
            actor.get('person_name'), row['native_clock_start_raw'], row['native_clock_end_raw'],
            row.get('period'), row['expected_goals'], row['outcome'], row.get('body_part'),
            row.get('native_x'), row.get('native_y'), _json(row), SOURCE_ID))
    for row in chances['own_goal_markers']:
        result['own_goal_markers'].append((row['event_id'], row['event_side_index'],
            row['side_index'], row['native_actor_slot'], (row.get('actor') or {}).get('person_name'),
            row['native_clock_start_raw'], row['native_clock_end_raw'], _json(row), SOURCE_ID))
    for row in document['player_shot_statistics']:
        result['player_shot_statistics'].append(tuple(row[name] for name in
            COLUMNS['player_shot_statistics'][:-2]) + (document['fixed_time_slice'], SOURCE_ID))
    for label, value in (('current', document['score'].get('current_score')),
                         ('first_half', document['score'].get('first_half_score'))):
        value = value or {'state': 'unavailable'}
        result['score_snapshots'].append((label, value['state'], value.get('home_goals'),
            value.get('away_goals'), value.get('at_time_slice'), 'inclusive_time_slice', SOURCE_ID))
    for row in chances['sides']:
        result['match_prefix_team_totals'].append((row['side_index'], row['state'], row['shots'],
            row['shots_on_target'], row['shot_goals'], row['expected_goals_sum_computed'],
            document['fixed_time_slice'], SOURCE_ID))
    for period in chances['periods']:
        for row in period['sides']:
            result['match_period_team_totals'].append((period['period'], row['side_index'],
                row['shots'], row['shots_on_target'], row['shot_goals'],
                row['expected_goals_sum_computed']))
    return result


def write(db, document, sha):
    if document is None:
        return
    db.execute('INSERT INTO source_documents VALUES (?,?,?)',
               (SOURCE_ID, sha(document), _json(document)))
    if document.get('state') not in ('available', 'partial'):
        return
    db.executescript('''
CREATE TABLE shots(event_id INTEGER PRIMARY KEY,side_index INTEGER,native_actor_slot INTEGER,actor_name TEXT,native_clock_start_raw INTEGER,native_clock_end_raw INTEGER,period TEXT,expected_goals REAL,outcome TEXT,body_part TEXT,native_x REAL,native_y REAL,record_json TEXT,source_id TEXT);
CREATE TABLE own_goal_markers(event_id INTEGER PRIMARY KEY,event_side_index INTEGER,beneficiary_side_index INTEGER,native_actor_slot INTEGER,actor_name TEXT,native_clock_start_raw INTEGER,native_clock_end_raw INTEGER,record_json TEXT,source_id TEXT);
CREATE TABLE player_shot_statistics(side_index INTEGER,native_actor_slot INTEGER,canonical_person_id INTEGER,person_index_word INTEGER,person_name TEXT,identity_state TEXT,shots INTEGER,shots_on_target INTEGER,shot_goals INTEGER,expected_goals_sum_computed REAL,counter_scope TEXT,fixed_time_slice INTEGER,source_id TEXT,PRIMARY KEY(side_index,native_actor_slot));
CREATE TABLE score_snapshots(scope TEXT PRIMARY KEY,state TEXT,home_goals INTEGER,away_goals INTEGER,at_time_slice INTEGER,boundary_policy TEXT,source_id TEXT);
CREATE TABLE match_prefix_team_totals(side_index INTEGER PRIMARY KEY,state TEXT,shots INTEGER,shots_on_target INTEGER,shot_goals INTEGER,expected_goals_sum_computed REAL,fixed_time_slice INTEGER,source_id TEXT);
CREATE TABLE match_period_team_totals(period TEXT,side_index INTEGER,shots INTEGER,shots_on_target INTEGER,shot_goals INTEGER,expected_goals_sum_computed REAL,PRIMARY KEY(period,side_index));
ALTER TABLE fixtures ADD COLUMN home_score INTEGER;
ALTER TABLE fixtures ADD COLUMN away_score INTEGER;
''')
    for name, values in rows(document).items():
        fields = ','.join(COLUMNS[name])
        placeholders = ','.join('?' for _ in COLUMNS[name])
        db.executemany(f'INSERT INTO {name}({fields}) VALUES ({placeholders})', values)
    current = document['score'].get('current_score') or {}
    if current.get('state') == 'available':
        db.execute('UPDATE fixtures SET home_score=?,away_score=?',
                   (current['home_goals'], current['away_goals']))
    db.executemany('INSERT INTO table_scopes VALUES (?,?)', SCOPES.items())


def verify(db, document, sha):
    if document is None:
        return
    stored = db.execute('SELECT sha256,document_json FROM source_documents WHERE source_id=?',
                        (SOURCE_ID,)).fetchone()
    if stored is None or stored != (sha(document), _json(document)):
        raise ValueError('Stored observed match statistics source changed')
    if document.get('state') not in ('available', 'partial'):
        return
    for name, expected in rows(document).items():
        fields = ','.join(COLUMNS[name])
        actual = db.execute(f'SELECT {fields} FROM {name}').fetchall()
        if sorted(actual, key=repr) != sorted(expected, key=repr):
            raise ValueError('Stored observed match statistics analytical cells changed: ' + name)
    current = document['score'].get('current_score') or {}
    expected = (current.get('home_goals'), current.get('away_goals')) if current.get('state') == 'available' else (None, None)
    if db.execute('SELECT home_score,away_score FROM fixtures').fetchone() != expected:
        raise ValueError('Stored observed official score changed')
