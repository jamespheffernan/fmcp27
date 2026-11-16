import json
import sqlite3

from fm_live_mcp.match_entry_state import SOURCE_POLICY, entry_context, query_entry_context


def event(side=1, minute=20, person=99, kind=0, additional=0):
    return dict(side_code=side, kind_code=kind, byte14=minute, byte15=additional, person_index=person)


def player(**source):
    return dict(side_index=0, person_index_word=5, goals=1, source=dict(
        flags5c=32, on_minute=60, off_minute=0, injury_minute=0,
        sent_off_minute=0, end_clock=90, **source))


def run(events, person=None, scores=(1, 1), **kwargs):
    return entry_context(dict(home_score=scores[0], away_score=scores[1]), events,
                         player() if person is None else person, source_policy=SOURCE_POLICY, **kwargs)


def test_trailing_substitute_scores_in_stoppage():
    result = run([event(), event(0, 90, 5, additional=4)])
    assert result['entry_state'] == 'trailing'
    assert result['personal_goals_after_entry'] == 1
    assert result['native_minutes'] == 30


def test_level_and_leading():
    assert run([event(0, 70, 5)], scores=(1, 0))['entry_state'] == 'level'
    result = run([event(0, 20), event(0, 70, 5)], scores=(2, 0))
    assert result['entry_state'] == 'leading'


def test_missing_goalless_array_is_known_but_nonzero_is_unknown():
    p = player(); p['goals'] = 0
    assert run(None, p, (0, 0))['personal_goals_after_entry'] == 0
    assert run(None)['evidence_state'] == 'missing_nonzero_score_events'


def test_unverified_policy_and_unknown_codes_fail_closed():
    assert entry_context({}, [], {})['evidence_state'] == 'unverified_source_policy'
    assert run([event(kind=3)])['evidence_state'] == 'untrusted_event_codes_or_clock'
    assert run([event()], scores=(0, 0))['evidence_state'] == 'score_reconciliation_failed'


def test_same_entry_minute_is_ambiguous():
    result = run([event(minute=60), event(0, 70, 5)])
    assert result['entry_state'] == 'ambiguous'
    assert result['personal_goals_after_entry'] is None


def test_type1_counts_for_score_but_not_personal_goals():
    result = run([event(0, 10, 5, kind=1), event(0, 70, 5)], scores=(2, 0))
    assert result['entry_state'] == 'leading'
    assert result['personal_goals_after_entry'] == 1


def test_exit_boundary_and_personal_reconciliation_fail_closed():
    p = player(); p['source']['off_minute'] = 70
    assert run([event(), event(0, 70, 5)], p)['evidence_state'] == 'ambiguous_exit_minute'
    assert run([event(), event(0, 71, 5)], p)['evidence_state'] == 'personal_goal_outside_interval'
    p['goals'] = 2
    assert run([event(), event(0, 70, 5)], p)['evidence_state'] == 'personal_goals_reconciliation_failed'


def test_unused_or_missing_participation_remains_unknown():
    p = player(); p['source']['on_minute'] = 0
    assert run([], p, (0, 0))['evidence_state'] == 'not_used_substitute'
    assert run([], {}, (0, 0))['evidence_state'] == 'missing_participation_source'


def test_query_filters_team_competition_date_and_reads_source_without_writes():
    c = sqlite3.connect(':memory:')
    c.executescript('''CREATE TABLE fixtures(fixture_id, native_match_key,date,competition_id,
        competition,home_team_id,away_team_id,home_score,away_score,event_state);
        CREATE TABLE events(fixture_id,source_index,side_code,kind_code,byte14,byte15,person_index);
        CREATE TABLE retained_players(fixture_id,side_index,person_index_word,canonical_person_id,person_name,goals,raw_json);
        INSERT INTO fixtures VALUES('a',1,'2030-10-01',11,'League',688,10,1,1,'present_records');
        INSERT INTO events VALUES('a',0,1,0,20,0,99),('a',1,0,0,70,0,5);''')
    c.execute('INSERT INTO retained_players VALUES(?,?,?,?,?,?,?)',
              ('a',0,5,123,'Example',1,json.dumps({'source':player()['source']})))
    c.execute('INSERT INTO retained_players VALUES(?,?,?,?,?,?,?)',
              ('a',1,99,456,'Opponent',1,json.dumps({'source':{'flags5c':0}})))
    before = c.total_changes
    rows = query_entry_context(c, team_id=688, competition_id=11, date_from='2030-09-01',
                               date_to='2030-10-01', source_policy=SOURCE_POLICY)
    assert len(rows) == 1 and rows[0]['entry_state'] == 'trailing'
    assert rows[0]['personal_goals_after_entry'] == 1 and rows[0]['person_id'] == 123
    assert query_entry_context(c, team_id=10, source_policy=SOURCE_POLICY) == []
    assert query_entry_context(c, competition_id=12, source_policy=SOURCE_POLICY) == []
    assert query_entry_context(c, date_to='2030-09-30', source_policy=SOURCE_POLICY) == []
    assert c.total_changes == before


def test_unknown_personal_credit_never_keeps_a_named_entry_state():
    p=player();p['goals']=2
    result=run([event(),event(0,70,5)],p)
    assert result['entry_state']=='unknown'
    assert result['personal_goals_after_entry'] is None


def test_fixture_tallies_require_every_source_credit():
    from fm_live_mcp.match_entry_state import fixture_player_tallies_match
    rows=[dict(side_index=0,person_index_word=5,goals=1)]
    assert fixture_player_tallies_match([event(0,70,5)],rows)
    assert not fixture_player_tallies_match([event(0,70,5),event()],rows)
    assert not fixture_player_tallies_match([event(0,70,5)],rows+rows)
