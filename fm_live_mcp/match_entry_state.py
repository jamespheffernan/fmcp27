"""Conservative score-at-substitute-entry projection from proved source fields.

Caller must explicitly opt into the B129 scoring/time policy. Numeric similarity
alone never enables it. Same-minute boundaries remain unresolved.
"""
import json
from collections import Counter

SOURCE_POLICY = 'b129_scoring_credit_and_display_clock'


def query_entry_context(connection, *, team_id=None, competition_id=None,
                        date_from=None, date_to=None, source_policy=None):
    """Read captured SQLite rows; each used substitute gets a filterable result.

    team_id is the canonical native team ID. Connections are caller-owned; this
    function performs SELECTs only and never attaches to FM or refreshes captures.
    """
    where, values = [], []
    if team_id is not None:
        where.append('(home_team_id=? OR away_team_id=?)'); values.extend((team_id, team_id))
    for column, operator, value in [('competition_id', '=', competition_id),
                                    ('date', '>=', date_from), ('date', '<=', date_to)]:
        if value is not None:
            where.append(f'{column}{operator}?'); values.append(value)
    sql = 'SELECT * FROM fixtures' + (' WHERE ' + ' AND '.join(where) if where else '') + ' ORDER BY date,fixture_id'
    def dictionaries(cursor):
        keys = [column[0] for column in cursor.description]
        return [dict(zip(keys, row)) for row in cursor]
    results = []
    for fixture in dictionaries(connection.execute(sql, values)):
        fixture_id = fixture['fixture_id']
        events = dictionaries(connection.execute('SELECT * FROM events WHERE fixture_id=? ORDER BY source_index', (fixture_id,)))
        if not events and fixture.get('event_state') in ('absent_array', 'not_captured'):
            events = None
        players = dictionaries(connection.execute('SELECT * FROM retained_players WHERE fixture_id=?', (fixture_id,)))
        tallies_match = fixture_player_tallies_match(events, players)
        for player in players:
            native_team = fixture['home_team_id'] if player['side_index'] == 0 else fixture['away_team_id']
            if team_id is not None and native_team != team_id:
                continue
            raw = json.loads(player['raw_json'])
            source = raw.get('source') or {}
            if type(source.get('flags5c')) is not int or not source['flags5c'] & 32 or not source.get('on_minute'):
                continue
            result = entry_context(fixture, events, {**player, 'source': source}, source_policy=source_policy)
            if source_policy == SOURCE_POLICY and not tallies_match:
                result.update(entry_state='unknown', evidence_state='fixture_player_goals_reconciliation_failed',
                              score_for_before_entry=None, score_against_before_entry=None, personal_goals_after_entry=None)
            results.append({**{k:fixture.get(k) for k in ('fixture_id','native_match_key','date','competition_id','competition')},
                            'team_id': native_team, 'person_id': player.get('canonical_person_id'),
                            'player': player.get('person_name'), **result})
    return results


def fixture_player_tallies_match(events, players):
    """Every credited scoring event must reconcile with the complete stored sides."""
    pairs = [(row.get('side_index'), row.get('person_index_word')) for row in players]
    if len(set(pairs)) != len(pairs) or any(side not in (0, 1) or type(person) is not int or person < 0 for side, person in pairs):
        return False
    credits = Counter((event.get('side_code'), event.get('person_index')) for event in events or () if event.get('kind_code') in (0, 2))
    if any(pair not in pairs for pair in credits):
        return False
    return all(type(row.get('goals')) is int and row['goals'] == credits[pair] for pair, row in zip(pairs, players))


def entry_context(fixture, events, player, *, source_policy=None):
    """Return one compact queryable row; invalid/incomplete evidence stays unknown.

    fixture: home_score/away_score. events: side_code,kind_code,byte14,byte15,
    person_index. player: side_index,person_index_word,goals,source (B89 fields).
    A missing array can establish an empty scoreboard only for a verified 0–0.
    """
    out = {'entry_state': 'unknown', 'evidence_state': 'unverified_source_policy',
           'score_for_before_entry': None, 'score_against_before_entry': None,
           'personal_goals_after_entry': None, 'boundary_event_count': None,
           'entry_minute': None, 'native_minutes': None}
    if source_policy != SOURCE_POLICY:
        return out
    scores = [fixture.get('home_score'), fixture.get('away_score')]
    if any(type(v) is not int or v < 0 for v in scores):
        return {**out, 'evidence_state': 'unknown_final_score'}
    if events is None:
        if scores != [0, 0]:
            return {**out, 'evidence_state': 'missing_nonzero_score_events'}
        events = []
    for event in events:
        values = [event.get(k) for k in ('side_code', 'kind_code', 'byte14', 'byte15')]
        if (any(type(v) is not int for v in values) or values[0] not in (0, 1)
                or values[1] not in (0, 1, 2) or not 0 <= values[2] <= 120
                or not 0 <= values[3] <= 255):
            return {**out, 'evidence_state': 'untrusted_event_codes_or_clock'}
    if [sum(e['side_code'] == side for e in events) for side in (0, 1)] != scores:
        return {**out, 'evidence_state': 'score_reconciliation_failed'}
    source = player.get('source') or {}
    names = ('flags5c', 'on_minute', 'off_minute', 'injury_minute', 'sent_off_minute', 'end_clock')
    if any(type(source.get(k)) is not int or source[k] < 0 for k in names):
        return {**out, 'evidence_state': 'missing_participation_source'}
    if not source['flags5c'] & 32 or not source['on_minute']:
        return {**out, 'evidence_state': 'not_used_substitute'}
    side = player.get('side_index')
    if side not in (0, 1) or type(side) is not int:
        return {**out, 'evidence_state': 'unknown_player_side'}
    start = source['on_minute']
    stop = source['off_minute'] or source['injury_minute'] or source['sent_off_minute'] or source['end_clock']
    if not 0 < start <= stop <= 120:
        return {**out, 'evidence_state': 'invalid_participation_interval'}
    duration = max(((stop - start + 128) % 256) - 128, 0)
    out.update(entry_minute=start, native_minutes=duration)
    clock = lambda event: (event['byte14'], event['byte15'])
    boundary = [e for e in events if clock(e) == (start, 0)]
    before = [sum(e['side_code'] == s and clock(e) < (start, 0) for e in events)
              for s in (side, 1 - side)]
    out.update(score_for_before_entry=before[0], score_against_before_entry=before[1],
               boundary_event_count=len(boundary))
    if boundary:
        return {**out, 'evidence_state': 'ambiguous_entry_minute', 'entry_state': 'ambiguous'}
    state = 'leading' if before[0] > before[1] else 'trailing' if before[0] < before[1] else 'level'
    out.update(entry_state=state, evidence_state='reconciled')
    person = player.get('person_index_word')
    if type(person) is not int or person < 0:
        return {**out, 'entry_state': 'unknown', 'evidence_state': 'unknown_player_identity'}
    personal = [e for e in events if e.get('person_index') == person and e['kind_code'] in (0, 2)
                and e['side_code'] == side]
    if type(player.get('goals')) is not int or len(personal) != player['goals']:
        return {**out, 'entry_state': 'unknown', 'evidence_state': 'personal_goals_reconciliation_failed'}
    # An exit-minute event has no established order relative to substitution.
    # End-clock stoppage belongs to a player without an explicit exit field.
    explicit_exit = any(source[k] for k in ('off_minute', 'injury_minute', 'sent_off_minute'))
    if any(e['byte14'] == stop for e in personal) and explicit_exit:
        return {**out, 'entry_state': 'unknown', 'evidence_state': 'ambiguous_exit_minute'}
    after = [e for e in personal if clock(e) > (start, 0)
             and (e['byte14'] < stop if explicit_exit else e['byte14'] <= stop)]
    if len(after) != len(personal):
        return {**out, 'entry_state': 'unknown', 'evidence_state': 'personal_goal_outside_interval'}
    out['personal_goals_after_entry'] = len(after)
    return out
