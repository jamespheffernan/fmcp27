import hashlib
import json
import sqlite3

import pytest
from fm_live_mcp.match_crossing_report import report_connection,crossing_report


@pytest.fixture
def db():
    c=sqlite3.connect(':memory:')
    c.executescript('''CREATE TABLE fixtures(fixture_id,native_match_key,date,competition_id,home_team_id,home_team_index,home_team,away_team_id,away_team_index,away_team);
    CREATE TABLE team_totals(fixture_id,side_index,crosses_attempted,crosses_completed,passes_attempted,crossing_counts_state);
    CREATE TABLE retained_players(fixture_id,side_index,person_index_word,canonical_person_id,person_name,minutes,appearance_kind,crosses_attempted,crosses_completed,open_play_crosses_attempted,open_play_crosses_completed);
    INSERT INTO fixtures VALUES('a',1,'2030-10-01',11,1,10,'Alpha',2,20,'Beta'),('b',2,'2030-10-08',11,2,20,'Beta',1,10,'Alpha'),('c',3,'2030-10-15',11,3,30,'Gamma',1,10,'Alpha');
    INSERT INTO team_totals VALUES('a',0,10,1,100,'native_aggregate_available'),('a',1,20,4,200,'native_aggregate_available'),('b',0,0,0,0,'native_aggregate_available'),('b',1,30,9,300,'native_aggregate_available'),('c',0,NULL,NULL,NULL,'unavailable_signed16_overflow'),('c',1,0,0,0,'native_aggregate_available');
    INSERT INTO retained_players VALUES('a',0,100,100,'One',90,'initial_participant_candidate',10,1,3,0),('b',1,100,100,'One',0,'entered_during_match',4,1,0,0),('c',1,100,100,'One',NULL,'unused_substitute',0,0,0,0),('a',0,101,101,'Open leader',90,'initial_participant_candidate',2,1,1,1),('a',0,102,102,'No delivery',90,'initial_participant_candidate',0,0,0,0),('a',0,103,103,'Tied',90,'initial_participant_candidate',9,2,2,0),('a',0,104,104,'Unknown counters',90,'initial_participant_candidate',NULL,NULL,NULL,NULL),('a',0,105,105,'Unknown minutes',NULL,'initial_participant_candidate',2,1,1,0),('a',0,106,NULL,'Unresolved',90,'initial_participant_candidate',3,1,2,0);''')
    yield c;c.close()


def query(db,**kw):return report_connection(db,competition_id=11,team_id=1,**kw)


def test_pooled_denominators_missingness_and_observed_ranks(db):
    out=query(db)
    selected=out['selected_teams'][0]
    own=selected['crosses_for'];against=selected['crosses_against']
    assert own['matches']==3 and own['attempts']==40 and own['completed']==10
    assert own['pooled_accuracy_percent']==25
    assert own['attempts_per_match']==pytest.approx(40/3)
    assert own['crosses_per_100_pass_attempts']==10
    assert own['attempts_per_match_rank']==1
    assert against['matches']==3 and against['known_matches']==2
    assert against['attempts'] is None and against['attempts_per_match_rank'] is None
    assert against['known_attempts']==20 and against['known_completed']==4
    assert against['known_pooled_accuracy_percent']==20
    assert out['coverage']['observed_fixtures']==3
    assert 'subset' in out['coverage']['comparison_scope']


def test_away_comparison_uses_same_venue_and_exact_sample_sizes(db):
    out=query(db,venue='away')
    assert len(out['per_match'])==2 and all(r['side_index']==1 for r in out['per_match'])
    selected=out['selected_teams'][0]['crosses_for']
    assert selected['matches']==2 and selected['attempts']==30 and selected['completed']==9
    assert selected['pooled_accuracy_percent']==30
    league=out['league_reference']['crosses_for']
    assert league['matches']==3 and league['attempts']==50 and league['completed']==13
    assert league['pooled_accuracy_percent']==26
    assert out['coverage']['comparison_team_matches']==3


def test_zero_denominator_is_null_and_complete_zero_stays_zero(db):
    out=query(db,venue='home')
    beta=next(r for r in out['league_teams'] if r['team_id']==2)['crosses_for']
    assert beta['attempts']==beta['completed']==0
    assert beta['pooled_accuracy_percent'] is None
    assert beta['pooled_accuracy_percent_rank'] is None
    assert beta['attempts_per_match']==0


def test_leader_grouping_open_play_cutoff_ties_and_zero_minute_counts(db):
    out=query(db,leaders=1,minimum_minutes=90,leader_sort='completed')
    boards=out['selected_delivery_leaders']
    all_rows=boards['categories']['all']
    assert [r['person_id'] for r in all_rows]==[100,103]
    assert [r['rank'] for r in all_rows]==[1,1]
    one=all_rows[0]
    assert one['known_minutes']==90 and one['attempts']==14 and one['completed']==2
    assert one['attempted_per90']==14
    assert one['unknown_minutes_rows']==0
    assert boards['categories']['open_play'][0]['person_id']==101
    assert boards['unresolved_identity_rows']==1
    assert boards['unknown_minute_eligibility_groups']==1
    assert boards['coverage']['categories']['all']['missing_counter_groups']==1
    assert boards['coverage']['categories']['all']['zero_attempt_groups']==1


def test_unknown_minutes_preserve_totals_but_not_per90(db):
    out=query(db,leaders=100)
    row=next(r for r in out['selected_delivery_leaders']['categories']['all'] if r['person_id']==105)
    assert row['attempts']==2 and row['completed']==1
    assert row['attempted_per90'] is None


def test_native_id_does_not_merge_distinct_team_indices(db):
    db.executescript("""INSERT INTO fixtures VALUES('d',4,'2030-10-20',11,1,11,'Alpha reserves',4,40,'Delta');
    INSERT INTO team_totals VALUES('d',0,5,1,100,'native_aggregate_available'),('d',1,3,0,90,'native_aggregate_available');""")
    out=query(db)
    assert [(r['team_id'],r['team_index']) for r in out['selected_teams']]==[(1,10),(1,11)]
    assert len(query(db,team_index=10)['per_match'])==3


def test_dates_and_opponent_leaders_are_from_historical_sides(db):
    db.execute("INSERT INTO retained_players VALUES('a',1,200,200,'Opponent',90,'initial_participant_candidate',20,4,12,2)")
    out=query(db,date_from='2030-10-01',date_to='2030-10-01')
    assert out['coverage']['observed_fixtures']==1
    row=out['opponent_delivery_leaders']['categories']['all'][0]
    assert row['team_id']==2 and row['person_id']==200 and row['completed']==4


def test_duplicate_team_totals_become_missing_not_double_counted(db):
    db.execute("INSERT INTO team_totals SELECT * FROM team_totals WHERE fixture_id='a' AND side_index=0")
    own=query(db)['selected_teams'][0]['crosses_for']
    assert own['known_matches']==2 and own['attempts'] is None


def test_duplicate_player_records_refuse_double_counting(db):
    db.execute("INSERT INTO retained_players SELECT * FROM retained_players WHERE canonical_person_id=100 LIMIT 1")
    with pytest.raises(ValueError,match='duplicate retained'):
        query(db)


def test_path_wrapper_is_read_only_and_does_not_change_file(db,tmp_path):
    path=tmp_path/'source.sqlite';disk=sqlite3.connect(path);db.backup(disk);disk.close()
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    out=crossing_report(path,competition_id=11,team_id=1,venue='away')
    assert out['source']['read_only']
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    json.dumps(out)


def test_old_schema_is_explicitly_unavailable():
    c=sqlite3.connect(':memory:')
    with pytest.raises(ValueError,match='.91 report fields'):
        query(c)


def test_opposing_attempt_completion_and_accuracy_order(db):
    # A high-attempt delivery threat must remain visible even with fewer completions.
    db.execute("INSERT INTO retained_players VALUES('a',0,110,110,'Volume threat',90,'initial_participant_candidate',100,1,90,1)")
    volume=query(db,leaders=1,minimum_minutes=90,leader_sort='attempted')['selected_delivery_leaders']
    completed=query(db,leaders=1,minimum_minutes=90,leader_sort='completed')['selected_delivery_leaders']
    accuracy=query(db,leaders=1,minimum_minutes=90,leader_sort='accuracy')['selected_delivery_leaders']
    assert volume['categories']['all'][0]['person_id']==110
    assert {r['person_id'] for r in completed['categories']['all']}=={100,103}
    assert accuracy['categories']['all'][0]['person_id']==101
    assert volume['categories']['open_play'][0]['person_id']==110
    assert accuracy['ranking']['units']=='percent'


def test_missing_opponent_player_side_is_unknown_not_zero(db):
    boards=query(db)['opponent_delivery_leaders']
    assert boards['state']=='unavailable_missing_player_sides'
    assert boards['coverage']['missing_player_side_matches']==3
    assert boards['categories']=={'all':[],'open_play':[]}


@pytest.mark.parametrize('value',['20301001','2030-W40-2'])
def test_noncanonical_iso_dates_are_rejected(db,value):
    with pytest.raises(ValueError,match='canonical YYYY-MM-DD'):
        query(db,date_from=value)


def test_requirements_and_missing_fields_are_machine_readable(db):
    from fm_live_mcp.match_crossing_report import report_requirements,missing_report_fields,ReportUnavailable
    assert 'open_play_crosses_completed' in report_requirements()['retained_players']
    assert missing_report_fields(db)=={}
    old=sqlite3.connect(':memory:')
    with pytest.raises(ReportUnavailable) as error:
        query(old)
    assert 'fixtures' in error.value.missing_fields
