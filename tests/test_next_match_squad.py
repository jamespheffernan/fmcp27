import copy
from datetime import date
import pytest
from fm_live_mcp import next_match_squad as planning
from fm_live_mcp.bridge import Bridge, BridgeError


def fixture(day='2030-10-29', clock='19:45', kind='fixture_record', scores=None):
    return {'date': day, 'kickoff_time': {'state': 'decoded' if clock else 'no_time_code', 'time': clock},
            'record_kind': kind, 'scores': scores}


def test_same_day_scored_row_remains_candidate():
    today = fixture('2030-10-28', kind='result_record', scores={'normal_time': {'home': 0, 'away': 0}})
    value = planning.select_fixture([fixture(), today], '2030-10-28', True)
    assert value['candidate'] == today
    assert value['state'] == 'same_day_time_or_completion_unknown'
    assert value['match_completion_known'] is False and value['current_time_known'] is False


def test_same_day_ties_and_unknown_clock_are_explicit():
    unknown, known = fixture(clock=None), fixture(clock='12:00')
    value = planning.select_fixture([unknown, known], '2030-10-28', True)
    assert value['state'] == 'same_day_kickoff_order_unknown'
    assert value['same_day_candidates'] == [unknown, known]
    assert planning.select_fixture([fixture(clock='20:00'), known], '2030-10-28', True)['candidate'] == known


def test_partial_empty_is_not_no_future_fixture():
    assert planning.select_fixture([], '2030-10-28', False)['state'] == 'no_candidate_in_partial_search'
    assert planning.select_fixture([fixture()], '2030-10-28', False)['state'] == 'earliest_observed_candidate_unconfirmed'


def test_projection_keeps_zero_unknown_and_ban_applicability_separate():
    player = {'name': 'Example', 'native_identity': {'database_index': 7}, 'roster_index': 0,
              'profile': {'positions': {'goalkeeper': 1, 'defender_right': 20, 'wing_back_right': 1}},
              'health': {'state': 'stored_without_refresh', 'condition': 0, 'match_sharpness': 5000,
                         'fatigue': -9, 'injury_record_count': 0, 'injuries': []}}
    location = {'location_state': 'away_from_managed_club', 'at_managed_club': False,
                'current_club_identity': {'native_id': 2}, 'contract_club_identity': {'native_id': 1},
                'loan_club_identity': {'native_id': 2}, 'clubs': {'on_loan': True}}
    bans = {'source_state': 'present_empty', 'physical_record_count': 0, 'records': []}
    result = planning.project_player(player, location, bans, 15, 'opaque')
    assert result['positions'] == [{'code': 'defender_right', 'label': 'Right back', 'rating': 20}]
    assert result['health']['condition_percent'] == 0 and result['health']['sharpness_percent'] == 50
    assert result['bans']['fixture_applicability'] == result['fixture_eligibility'] == 'unknown'
    player['health'].update(state='partial_virtual', native_defaults=['fatigue', 'injury_record_count'])
    result = planning.project_player(player, location, bans, 15, 'opaque')
    assert result['health']['fatigue'] is None and result['health']['injury_record_count'] is None
    assert result['health']['injuries'] is None


def test_complete_day_search_skips_native_id_alias_and_stops_at_first_day(monkeypatch):
    calls = []
    team = {'database_index': 545, 'native_id': 688}
    def scan(read, base, binding, year, bounds, *args):
        calls.append(bounds)
        # Native ID filtering can include a different canonical TEAM alias.
        index = 999 if bounds[0] == 301 else 545
        row = {**fixture('2030-10-29' if index == 545 else '2030-10-28'),
               'home_team': {'database_index': index, 'native_id': 688}, 'away_team': None}
        item = (row, [], None, None, None, {})
        return [item], {'position': (bounds[0] + 1, 0, 0), 'bucket_identity': None,
                        'finished': True, 'scanned_records': 1, 'examined_buckets': 66,
                        'stop_reason': 'resident_range_end'}
    monkeypatch.setattr(planning.fixtures, 'scan', scan)
    pending, years, cursors, full = planning._scan(None, 0, {}, {2030: {'coverage': {'all_groups_materialized': True}}},
        'catalog', team, date(2030, 10, 28), date(2030, 12, 2), 20)
    assert calls == [(301, 301), (302, 302)] and len(pending) == 1
    assert years[0]['searched_through'] == '2030-10-29' and years[0]['complete'] is True
    assert years[0]['filtered_team_alias_records'] == 1 and full is False
    assert cursors[0]['position'] == (303, 0, 0)
    assert cursors[0]['criteria']['date_to'] == '2030-12-02'


@pytest.mark.parametrize('kwargs', [{'window_days': True}, {'position_minimum': 0}, {'max_fixture_pages': 51}])
def test_bad_bounds_reject_before_native_scope(kwargs):
    with pytest.raises(BridgeError):
        Bridge().get_next_match_squad('not-a-session', **kwargs)


def test_reference_transaction_restores_cleared_old_maps():
    bridge = Bridge()
    bridge.player_refs['old'] = {'binding': 'preserved'}
    before = copy.deepcopy(bridge.player_refs)
    with pytest.raises(ValueError):
        with planning._reference_transaction(bridge):
            bridge.player_refs.clear()
            bridge.player_refs['new'] = {}
            bridge.database_cursors['new'] = {}
            raise ValueError('late projection failure')
    assert bridge.player_refs == before and bridge.database_cursors == {}


def test_missing_resident_year_does_not_claim_window_scanned():
    rows, years, cursors, complete = planning._scan(None, 0, {}, {}, 'catalog',
        {'database_index': 1, 'native_id': 2}, date(2030, 12, 31), date(2031, 1, 2), 2)
    assert rows == [] and complete is False and cursors == []
    assert [r['state'] for r in years] == ['resident_year_unavailable', 'resident_year_unavailable']


def test_planning_cache_reuses_only_exact_regions_and_final_read_rejects_mutation():
    memory=bytearray(b'abcd');calls=[]
    def native(address,length):
        calls.append((address,length))
        return bytes(memory[address:address+length])
    snapshot=planning._PlanningReadSet(native)
    for _ in range(100001):
        assert snapshot(0,2)==b'ab'
    assert calls==[(0,2)]
    assert snapshot(0,3)==b'abc'  # Overlapping lengths remain distinct consumed regions.
    memory[1]=ord('z')
    with pytest.raises(ValueError,match='Game state changed during read'):
        snapshot.verify()
    assert calls==[(0,2),(0,3),(0,2)]


def test_planning_final_check_is_native_not_cached_and_new_queries_are_fresh():
    calls=[];memory=bytearray(b'a')
    def native(address,length):
        calls.append((address,length))
        return bytes(memory)
    first=planning._PlanningReadSet(native)
    assert first(0,1)==b'a'
    first.verify()
    assert len(calls)==2
    memory[0]=ord('b')
    second=planning._PlanningReadSet(native)
    assert second(0,1)==b'b'
    second.verify()
    assert len(calls)==4


def test_planning_original_world_bookend_observations_remain_verified():
    snapshot=planning._PlanningReadSet(lambda address,length:b'changed')
    snapshot.observed.update({(123,7):b'initial'})
    assert snapshot(123,7)==b'initial'
    with pytest.raises(ValueError,match='Game state changed during read'):
        snapshot.verify()


def test_save_bookend_bypasses_planning_cache_and_rejects_changed_native_roots(monkeypatch):
    memory=bytearray(b'a');calls=[]
    def native(address,length):
        calls.append((address,length));return bytes(memory)
    snapshot=planning._PlanningReadSet(native)
    assert snapshot(123,1)==b'a'
    monkeypatch.setattr(planning.world,'loaded',lambda read,base:(read(123,1),'identity'))
    assert planning._fresh_world_bookend(snapshot,0)==(b'a','identity')
    assert len(calls)==2
    memory[0]=ord('b')
    with pytest.raises(ValueError,match='Game state changed during read'):
        planning._fresh_world_bookend(snapshot,0)
    assert len(calls)==3
