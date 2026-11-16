from copy import deepcopy
from types import SimpleNamespace
import sys
import pytest

from fm_live_mcp import retained_match_discovery as discovery


def fixture(ref='r', when='2030-10-26', home=688, away=713):
    return {'fixture_ref': ref, 'date': when, 'competition': {'native_id': 11, 'name': 'Premier League'},
            'home_team': {'native_id': home, 'database_index': home, 'name': str(home)},
            'away_team': {'native_id': away, 'database_index': away, 'name': str(away)}}


def source(when='2030-10-26', team=688, present=True, collection='0x188'):
    return {'date': when, 'owner_team_native_id': team, 'nonnull_source': present,
            'coach_index': 0, 'native_collection': collection}


def test_binding_merges_same_fixture_sources_without_inventing_extra_matches():
    rows = discovery.bind_candidates([source(), source(team=713)], [fixture()])
    assert len(rows) == 1
    assert rows[0]['fixture_ref'] == 'r'
    assert len(rows[0]['source_candidates']) == 2


def test_two_same_date_team_results_remain_ambiguous_with_candidate_refs():
    rows = discovery.bind_candidates([source()], [fixture(), fixture('other', away=602)])
    assert rows[0]['state'] == 'ambiguous_fixture_binding'
    assert 'fixture_ref' not in rows[0]
    assert len(rows[0]['candidate_fixtures']) == 2


def test_missing_partial_and_invalid_date_bindings_do_not_become_empty_available_data():
    for entries, matches, complete, state in [
        ([source()], [], True, 'unavailable_fixture_binding'),
        ([source()], [fixture()], False, 'incomplete_fixture_search'),
        ([source(None)], [], True, 'unavailable_fixture_binding'),
    ]:
        row, = discovery.bind_candidates(entries, matches, complete)
        assert row['state'] == state and 'fixture_ref' not in row


def test_projection_states_are_independent_and_counts_preserve_true_zero():
    shot = {'state': 'available_partial', 'side_coverage': [
        {'side_index': 0, 'state': 'unavailable_reconciliation', 'shot_count': None},
        {'side_index': 1, 'state': 'available', 'shot_count': 0}]}
    passes = {'state': 'available', 'sides': [{'side_index': 0, 'state': 'available',
                                             'counter_reconciled_completed_passes': 0, 'edges': ['private']}]}
    assert discovery._status(shot, 'shots')['state'] == 'available_partial'
    assert discovery._status(shot, 'shots')['sides'][1]['shot_count'] == 0
    result = discovery._status(passes, 'passes')
    assert result['state'] == 'available' and 'edges' not in result['sides'][0]


@pytest.fixture
def harness(monkeypatch):
    inventory = {'save': {'current_date': '2030-11-02'}, 'source_inventory_id': 'a'*64,
                 'resident_fixture_years': [2030], 'owners': [{'team': {'native_id': 688, 'database_index': 688}}],
                 'entries': [source('2030-10-19'), source(), source(team=713)]}
    monkeypatch.setattr(discovery, 'capture_epoch', lambda *_: ('load',))
    monkeypatch.setattr(discovery, '_inventory', lambda *_: deepcopy(inventory))
    monkeypatch.setattr(discovery, '_targets', lambda *_: ([{'native_id': 688}, {'native_id': 713}], None))
    queries, captures = [], []
    def query(*args):
        queries.append(args[2:])
        return [fixture('new'), fixture('old', '2030-10-19')], {'complete': True}
    monkeypatch.setattr(discovery, '_fixture_query', query)
    monkeypatch.setattr(discovery, 'capture_live', lambda *a, **k: captures.append(a[2]) or {'_live_capture_epoch': ('load',)})
    def batch(*a, **kw):
        assert kw['fixture_captures']['_live_capture_epoch'] == ('load',)
        return {'records': [{'fixture_ref': ref, 'state': 'available', 'side_coverage': []} for ref in a[2]]}
    monkeypatch.setattr(discovery.shots, 'capture_retained_shot_maps', batch)
    monkeypatch.setitem(sys.modules, 'fm_live_mcp.live_retained_passes', SimpleNamespace(capture_retained_pass_networks=batch))
    return inventory, queries, captures


def test_discovery_bulk_resolves_source_dates_and_reuses_one_capture(harness):
    _, queries, captures = harness
    result = discovery.list_retained_match_data(None, 'session')
    assert len(queries) == 2  # per team/year, not per guessed fixture/date
    assert captures == [['new', 'old']]
    assert result['candidate_count'] == result['matched_fixture_count'] == 2
    assert all(row['state'] == 'verified_available' for row in result['fixtures'])
    assert not result['saved_file_fallback']


def test_pagination_pin_binds_scope_and_native_inventory(harness):
    with pytest.raises(ValueError, match='continuation requires'):
        discovery.list_retained_match_data(None, 's', offset=1)
    first = discovery.list_retained_match_data(None, 's', limit=1)
    second = discovery.list_retained_match_data(None, 's', offset=1,
                                               expected_source_inventory_id=first['source_inventory_id'])
    assert first['fixtures'][0]['fixture_ref'] != second['fixtures'][0]['fixture_ref']
    with pytest.raises(ValueError, match='inventory changed'):
        discovery.list_retained_match_data(None, 's', scope='team', team_native_id=688, offset=1,
                                           expected_source_inventory_id=first['source_inventory_id'])


def test_missing_resident_year_remains_explicit_candidate(harness):
    inventory, queries, captures = harness
    inventory['entries'] = [source('2029-10-26')]
    result = discovery.list_retained_match_data(None, 's')
    assert queries == captures == []
    assert result['fixtures'][0]['state'] == 'incomplete_fixture_search'
    assert result['fixtures'][0]['shot_map']['state'] == 'not_checked'
    assert result['fixture_search'][0]['state'] == 'resident_fixture_year_unavailable'


def test_inventory_change_during_capture_rejects_whole_observation(harness, monkeypatch):
    inventory, _, _ = harness
    calls = iter([deepcopy(inventory), {**inventory, 'source_inventory_id': 'b'*64}])
    monkeypatch.setattr(discovery, '_inventory', lambda *_: next(calls))
    with pytest.raises(ValueError, match='changed during discovery'):
        discovery.list_retained_match_data(None, 's')


@pytest.mark.parametrize('kwargs', [dict(scope='team'), dict(scope='managed', team_native_id=688),
                                     dict(coach_index=True), dict(limit=17), dict(offset=-1)])
def test_invalid_scope_and_bounds_reject_before_live_access(kwargs):
    with pytest.raises(ValueError):
        discovery.list_retained_match_data(None, 's', **kwargs)


def test_tool_schema_is_read_only_and_has_typed_selectors():
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.retained_match_discovery_tools import register_retained_match_discovery_tools
    async def check():
        mcp = FastMCP('discovery')
        register_retained_match_discovery_tools(mcp, None)
        tool, = await mcp.list_tools()
        assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
        assert tool.name == 'fm_list_retained_match_data'
        assert tool.inputSchema['properties']['scope']['default'] == 'managed_and_next_opponent'
        assert tool.outputSchema['type'] == 'object'
    asyncio.run(check())


def test_fixture_summary_uses_canonical_club_names_and_retains_team_type():
    row = fixture()
    row['home_team'] = {'native_id': 688, 'native_type_code': 0, 'owner': {'name': 'Newcastle United'}}
    result = discovery._summary(row)
    assert result['home_team'] == {'name': 'Newcastle United', 'native_id': 688, 'native_type_code': 0}
    assert result['competition']['name'] == 'Premier League'


def test_earliest_day_with_two_opponents_does_not_choose_one(monkeypatch):
    inventory = {'save': {'current_date': '2030-11-02'},
                 'owners': [{'team': {'native_id': 688, 'database_index': 688}}]}
    monkeypatch.setattr(discovery, '_fixture_query', lambda *a:
                        ([fixture('a', '2030-11-02', away=713),
                          fixture('b', '2030-11-02', away=602)], {'complete': True}))
    targets, selection = discovery._targets(None, 's', inventory, 'managed_and_next_opponent', None)
    assert [t['native_id'] for t in targets] == [688]
    assert selection['opponent_state'] == 'ambiguous_earliest_day_opponents'
    assert selection['match_completion_known'] is False


def test_next_opponent_keeps_same_day_completion_uncertainty(monkeypatch):
    inventory = {'save': {'current_date': '2030-11-02'},
                 'owners': [{'team': {'native_id': 688, 'database_index': 688}}]}
    monkeypatch.setattr(discovery, '_fixture_query', lambda *a:
                        ([fixture('a', '2030-11-02', away=713)], {'complete': True}))
    targets, selection = discovery._targets(None, 's', inventory, 'next_opponent', None)
    assert targets[0]['native_id'] == 713
    assert targets[0]['selection_state'] == 'same_day_time_or_completion_unknown'
    assert not selection['current_time_known']


def test_bulk_queries_deduplicate_canonical_fixture_with_different_opaque_refs():
    a = dict(fixture('first'), _discovery_binding='canonical-address-identity')
    b = dict(fixture('fresh-reference'), _discovery_binding='canonical-address-identity')
    result = discovery.bind_candidates([source(), source(team=713)], [a, b])
    assert len(result) == 1 and result[0]['state'] == 'resolved_candidate'
    assert len(result[0]['source_candidates']) == 2
