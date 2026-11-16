"""Reconcile the two source-local PERSON references in retained result goal records."""
from collections import Counter

from . import players as player_layout
from .match_data_query import capture_epoch, capture_live


def _actor(row):
    return {'person_native_id': row['canonical_person_id'], 'name': row['person_name']}


def _checked_roster(players, fixture, selected_sides=(0, 1)):
    roster = {}
    identities = set()
    for player in players:
        side = player['side_index']
        if type(side) is not int or side not in (0, 1):
            return None
        if side not in selected_sides:
            continue
        team = fixture[('home_team', 'away_team')[side]]
        index, person = player['person_index_word'], player['canonical_person_id']
        if (player['identity_state'] != 'same_snapshot_canonical_PERSON' or
                type(index) is not int or index < 0 or type(person) is not int or person <= 0 or
                index in roster or person in identities or not player['person_name'] or
                player['team_index_word'] != team['database_index'] or
                player['canonical_team_id'] != team['native_id'] or
                any(type(player[key]) is not int or player[key] < 0 for key in ('goals','assists'))):
            return None
        roster[index] = player
        identities.add(person)
    return roster if {p['side_index'] for p in roster.values()} == set(selected_sides) else None


def project_goal_timeline(item, match_players):
    """Project one exact fixture; publish pairs only after every player and side closes."""
    fixture = item['fixture']
    key = item['native_match_key']
    base = {'fixture': fixture, 'native_match_key': key, 'goal_records': None}
    source = item['event_array']
    if key is None or item['source']['state'] != 'available':
        return dict(base, state='unavailable_retained_match_frame')
    if source['state'] not in ('present_empty','present_records'):
        return dict(base, state='unavailable_event_array')
    rows = source['rows']
    if source['count'] != len(rows) or [r['source_index'] for r in rows] != list(range(len(rows))):
        return dict(base, state='unavailable_event_coverage')
    roster = _checked_roster([p for p in match_players if p['fixture_key'] == key], fixture)
    if roster is None:
        return dict(base, state='unavailable_player_roster')
    goals, assists, side_goals = Counter(), Counter(), Counter()
    records = []
    for row in rows:
        # Extend coverage only when the result-record subtype is source-bound.
        if row['kind13'] != 0:
            return dict(base, state='unavailable_result_event_subtype', native_subtype=row['kind13'])
        side, first, second = row['side12'], row['person_index'], row['second_index_word']
        scorer = roster.get(first)
        if side not in (0, 1) or scorer is None or scorer['side_index'] != side:
            return dict(base, state='unavailable_goal_actor')
        provider = None
        if second != -1:
            provider = roster.get(second)
            if provider is None or provider['side_index'] != side or first == second:
                return dict(base, state='unavailable_assist_actor')
            assists[second] += 1
        goals[first] += 1
        side_goals[side] += 1
        records.append({'source_index':row['source_index'], 'side_index': side,
                        'team_native_id': scorer['canonical_team_id'],
                        'scorer': _actor(scorer), 'timeline_player2': _actor(provider) if provider else None})
    scores = (fixture.get('scores') or {}).get('final_score') or {}
    if any(scores.get(side) != side_goals[i] for i,side in enumerate(('home','away'))):
        return dict(base, state='unavailable_score_reconciliation')
    if any(goals[index] != player['goals'] or assists[index] != player['assists'] for index,player in roster.items()):
        return dict(base, state='unavailable_individual_counter_reconciliation')
    return dict(base, state='available', goal_records=records, checked_players=len(roster),
                second_person_scope='Official GoalscorersString Player2. Roster counts reconcile with assists; its per-goal assist role is unverified.')


# Retained source PERSON indexes, missing sentinel, and the two official GoalscorersString player properties.
TIMELINE_SPANS = (
    (0x3cf9d58, bytes.fromhex('5a0340b9390340b9090b40f91f0109eb420100541a650029170900b9143100391535003916390039133d0039')),
    (0x2e5534c, bytes.fromhex('4a0340f98a0000b44a0940b95f050031410000540a008012ea0f00b94a0740f98a0000b44a0940b95f050031410000540a00801229117dd3cb26c99a651d00132927c99aea0b00b908011b8b040140b90715403921010012e2330091e3230091e00313aa18923a94')),
    (0x2e55440, bytes.fromhex('490340f9890000b4290940b93f0500314100005409008012e90f00b9490740f9890000b4290940b93f05003141000054090080124a117dd3cb26ca9a651d00130a27ca9a411d0013e90b00b908011b8b040140b907154039e2330091e3230091e00313aadb913a94')),
    (0x208aa8, bytes.fromhex('288d8d52c84ca672df02086b80100054')),
    (0x208d34, bytes.fromhex('693e40f93f0100f10801899a1b2140a9e82f00f97f0308eb80c10054')),
    (0x208d98, bytes.fromhex('7b430091e82f40f97f0308ebc0be0054600340b9f0763994f80300aa600740b9ed763994f70300aa')),
    (0x208e2c, bytes.fromhex('f70000b4e80240f9094540f9e8030e91e00317aa20013fd60700001441a602f021602491288440b8e88303b94023009173ee0795e8630e91e0030e9147be3e94e0e30e91e2630e9121498652c10ca6721ab90795')),
)


def _verify_timeline(bridge, session_id):
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        layout = bridge._player_layout(process)
        read, _, _ = bridge._world_state(process, layout)
        base = layout[0] - player_layout.RVA[0]
        supported = all(read(base + rva, len(expected)) == expected for rva, expected in TIMELINE_SPANS)
        read.verify()
        return supported


def _fixture_bounds(item, rows, team_id, scorer_id, *, timeline_verified=True):
    from .goal_assist_bounds import goal_assist_bounds
    fixture = item['fixture']
    key = item['native_match_key']
    ref = fixture['fixture_ref']
    out = {'fixture_ref': ref, 'native_match_key': key, 'date': fixture['date'],
           'home_team': fixture['home_team'], 'away_team': fixture['away_team'],
           'scores': fixture.get('scores'), 'bounds': None, 'timeline': None}
    sides = [i for i, name in enumerate(('home_team','away_team')) if fixture[name]['native_id'] == team_id]
    if len(sides) != 1:
        raise ValueError('Selected team must appear on one side of every selected fixture.')
    if key is None or item['source']['state'] != 'available':
        return dict(out, state='unavailable_retained_frame')
    side = sides[0]
    roster = _checked_roster([p for p in rows if p['fixture_key'] == key], fixture, (side,))
    if not roster:
        return dict(out, state='unavailable_roster_identity_or_counters')
    own = list(roster.values())
    total = ((fixture.get('scores') or {}).get('final_score') or {}).get(('home','away')[side])
    if type(total) is not int or total < 0:
        return dict(out, state='unavailable_team_score')
    by_id = {p['canonical_person_id']: p for p in own}
    if scorer_id not in by_id:
        return dict(out, state='scorer_absent_from_checked_team_roster')
    timeline = (project_goal_timeline(item, rows) if timeline_verified else
                {'state': 'unavailable_goal_timeline_binding', 'goal_records': None})
    out['timeline'] = {'state': timeline['state'], 'records': None}
    if timeline['goal_records'] is not None:
        out['timeline']['records'] = [r for r in timeline['goal_records'] if r['scorer']['person_native_id'] == scorer_id]
    counter_rows = [{'fixture_id':ref,'team_native_id':team_id,'canonical_person_id':p['canonical_person_id'],
                     'goals':p['goals'],'assists':p['assists']} for p in own]
    result = goal_assist_bounds(counter_rows, fixture_id=ref, team_native_id=team_id, credited_goal_total=total,
                                coverage_state='complete_canonical_player_counters')
    out.update(state=result['state'], scorer_name=by_id[scorer_id]['person_name'],
               goals=by_id[scorer_id]['goals'], checked_team_players=len(own))
    if result['bounds'] is not None:
        out['bounds'] = []
        for row in result['bounds']:
            if row['scorer_person_id'] != scorer_id or row['maximum'] == 0:
                continue
            provider = row['supplier_person_id']
            out['bounds'].append(dict(row, name=by_id[provider]['person_name'] if provider is not None else None))
    return out


def _summarize(fixtures):
    measured = [fixture for fixture in fixtures if fixture['bounds'] is not None]
    suppliers = {}
    for fixture in measured:
        for row in fixture['bounds']:
            person = row['supplier_person_id']
            entry = suppliers.setdefault(person, {'supplier_person_id': person, 'name': row['name'],
                'supplier_kind': row['supplier_kind'], 'minimum': 0, 'maximum': 0})
            entry['minimum'] += row['minimum']
            entry['maximum'] += row['maximum']
    return {'selected_fixture_count': len(fixtures), 'covered_fixture_count': len(measured),
            'coverage': 'complete_selection' if len(measured) == len(fixtures) else 'covered_fixtures_only',
            'scorer_goals_in_covered_fixtures': sum(f['goals'] for f in measured) if measured else None,
            'suppliers': sorted(suppliers.values(), key=lambda row: (-row['minimum'], -row['maximum'],
                                row['supplier_person_id'] or 0)) if measured else None}


def report_goal_combinations(bridge, session_id, refs, team_id, scorer_id):
    if (not isinstance(refs, list) or not 1 <= len(refs) <= 16
            or not all(isinstance(ref, str) and ref for ref in refs) or len(set(refs)) != len(refs)):
        raise ValueError('Select 1–16 distinct retained fixture references.')
    epoch = capture_epoch(bridge, session_id)
    timeline_verified = _verify_timeline(bridge, session_id)
    packet = capture_live(bridge, session_id, refs)
    if packet.get('_live_capture_epoch') != epoch or capture_epoch(bridge, session_id) != epoch:
        raise ValueError('Retained goal sources changed career during collection.')
    items = packet['capture']['fixtures']
    keys = [item['native_match_key'] for item in items if item['native_match_key'] is not None]
    if (len(keys) != len(set(keys)) or len(items) != len(refs) or
            {item['fixture']['fixture_ref'] for item in items} != set(refs)):
        raise ValueError('Retained goal sources differ from selected fixtures.')
    fixtures = [_fixture_bounds(item, packet['retained_players'], team_id, scorer_id,
                                timeline_verified=timeline_verified) for item in items]
    return {'team_native_id':team_id, 'scorer_person_id':scorer_id, 'captured_save':packet['capture']['save'],
            'source':'running_career_selected_retained_results','saved_file_fallback':False,
            'fixtures': fixtures, 'selection_summary': _summarize(fixtures),
            'interpretation': 'Bounds use independently named goal and assist totals under the single-assist, no-self-assist model. '
            'A minimum above zero guarantees that many assists to the scorer under the model. A maximum is a possibility. '
            'These counts do not assign a particular goal. The separate named goalscorers timeline exposes its second person '
            'as Player2. Agreement with assist totals does not certify that individual timeline role as an assist.'}
