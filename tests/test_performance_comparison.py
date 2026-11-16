from collections import Counter
from copy import deepcopy
import json

import pytest

from fm_live_mcp import performance_comparison as comparison


def statistics(minutes, goals, assists):
    return {'state':'stored_without_refresh', 'current_team':{'native_id':80},
            'current_team_state':'decoded', 'categories':[{'native_code':1, 'name':'League',
             'availability':'resident', 'statistics':{'minutes':minutes, 'goals':goals, 'assists':assists}}]}


class FakeBridge:
    """Public-query fake with real cache lifecycle, generated links and call hooks."""

    def __init__(self):
        self.player_refs = {'old-player':{'old':True}}
        self.team_refs = {'team-root':{'old':True}}
        self.competition_refs = {'old-competition':{'old':True}}
        self.save = {'name':'Synthetic career', 'current_date':'2030-10-28', 'save_count':4}
        self.players = [
            {'name':'Same', 'birth_date':'2000-01-01'},
            {'name':'Same', 'birth_date':'2000-01-01'},
            {'name':'Cutoff', 'birth_date':'2001-01-01'},
            {'name':'Unknown', 'birth_date':'2002-01-01'},
            {'name':'Virtual', 'birth_date':'2003-01-01', 'record_kind':'virtual'},
        ]
        for row in self.players:
            row['clubs'] = {'on_loan':False, 'contract_club':{'name':'Example'}}
        self.statistics = [statistics(900,5,5), statistics(450,8,2), statistics(449,20,None),
                           statistics(600,1,None), None]
        self.calls = []
        self.counts = Counter()
        self.hooks = {}
        self.serial = 0
        self.order = list(range(5))
        self.clear_players_on_final = False

    def _reference(self, prefix):
        self.serial += 1
        return f'{prefix}-{self.serial}'

    def _finish(self, method, response, index=None):
        self.counts[method] += 1
        self.calls.append((method,index))
        response = deepcopy(response)
        response.update(observed_at=f'time-{len(self.calls)}', save=deepcopy(self.save))
        if method in self.hooks:
            self.hooks[method](self, self.counts[method], response)
        return response

    def _index(self, reference):
        return self.player_refs[reference]['roster_index']

    def get_team_squad(self, session_id, team_ref, include_clubs=False, profile_policy='required'):
        assert profile_policy == 'available'
        assert include_clubs is True
        if team_ref not in self.team_refs:
            raise ValueError('expired fake team reference')
        if self.clear_players_on_final and self.counts['squad']:
            self.player_refs.clear()
        rows = []
        for index in self.order:
            ref = self._reference('player')
            self.player_refs[ref] = {'address':0x10000+index*1000, 'identity':(index, 'identity'),
                                     'tables':(10,20,30), 'roster_index':index}
            rows.append({**deepcopy(self.players[index]), 'player_ref':ref})
        return self._finish('squad', {'players':rows, 'count':len(rows), 'complete_native_roster':True,
                                     'label':'Senior', 'club':{'name':'Example'}})

    def _player(self, index):
        row = self.players[index]
        return {'name':row['name'], 'birth_date':row['birth_date'], 'record_kind':'actual'}

    def get_current_player_statistics(self, session_id, player_ref):
        index = self._index(player_ref)
        assert self.players[index].get('record_kind','actual') == 'actual'
        return self._finish('current', {'player_ref':player_ref, 'player':self._player(index),
                                      'statistics':self.statistics[index]}, index)

    def get_player_statistics_history(self, session_id, player_ref):
        index = self._index(player_ref)
        team = {'database_index':1, 'native_id':1001, 'random_id':0, 'name':'History team'}
        competition = {'database_index':2, 'native_id':2002, 'random_id':3003, 'name':'History competition'}
        for kind,row,cache in (('team',team,self.team_refs), ('competition',competition,self.competition_refs)):
            reference = self._reference(kind)
            raw = b''.join(value.to_bytes(4,'little') for value in
                           (row['database_index'],row['native_id'],row['random_id']))
            cache[reference] = {'address':0x20000+row['database_index'], 'identity':raw,
                                'database_index':row['database_index'], 'native_id':row['native_id'],
                                'random_id':row['random_id']}
            row[kind+'_ref'] = reference
        league = {'native_offset':10, 'native_year':2029, 'native_category_code':1,
                  'team':team, 'competition':competition, 'statistics':{'goals':index+1}}
        history = {'state':'decoded', 'reason':None, 'native_entry_count':4, 'returned_row_count':3,
                   'skipped_entries':[{'native_offset':-1,'reason':'native_negative_offset_skipped'}],
                   'rows':[league, {**league,'native_offset':11,'native_category_code':3}, deepcopy(league)],
                   'record_width':168, 'version':7, 'encoding':{'stream_flags':2},
                   'source_coverage':'indexed_archive_only', 'limitations':'Separate archive context'}
        return self._finish('history', {'player_ref':player_ref, 'player':self._player(index), 'history':history}, index)

    def get_save(self, session_id):
        return self._finish('save', {})


@pytest.fixture
def performance_bridge():
    return FakeBridge()


def test_exact_join_duplicate_names_complete_classification_and_final_refs(performance_bridge):
    bridge = performance_bridge
    bridge.clear_players_on_final = True
    result = comparison.collect(bridge, 'session', 'team-root')
    ranked = result['comparison']
    assert [row['roster_index'] for row in ranked['rows']] == [1,0]
    assert [row['per90']['value'] for row in ranked['rows']] == [2,1]
    assert [row['player']['name'] for row in ranked['rows']] == ['Same','Same']
    assert [row['player']['player_ref'] for row in ranked['rows']] != ['player-2','player-1']
    assert all(row['player']['player_ref'] in bridge.player_refs for row in ranked['classifications'])
    assert ranked['counts']['roster_count'] == 5 and ranked['counts']['unknown_count'] == 1
    assert ranked['counts']['unsupported_count'] == 1 and ranked['counts']['below_minimum_count'] == 1
    assert ranked['ranking_complete_for_roster'] is False
    assert ranked['selected_team'] == {'label':'Senior', 'club':{'name':'Example'}}
    assert [row['state'] for row in ranked['classifications']] == ['qualified','qualified','below_minimum','unknown','unsupported']
    assert bridge.counts == {'squad':2, 'current':8, 'history':4, 'save':1}
    assert 'address' not in json.dumps(result) and 'identity' not in json.dumps(ranked)
    assert 'Non-atomic' in result['snapshot']


def test_history_filter_preserves_source_counts_order_duplicates_and_final_links(performance_bridge):
    bridge = performance_bridge
    result = comparison.collect(bridge, 'session', 'team-root', limit=1)
    history = result['comparison']['rows'][0]['archived_league_history']
    assert history['source_native_entry_count'] == 4 and history['source_returned_row_count'] == 3
    assert len(history['source_skipped_entries']) == 1 and history['filtered_row_count'] == 2
    assert [row['native_offset'] for row in history['rows']] == [10,10]
    for row in history['rows']:
        assert row['team']['team_ref'] in bridge.team_refs
        assert row['competition']['competition_ref'] in bridge.competition_refs


def test_history_not_requested_never_queries_archive(performance_bridge):
    result = comparison.collect(performance_bridge, 'session', 'team-root', include_history=False)
    assert performance_bridge.counts['history'] == 0
    assert all(row['archived_league_history'] == {'state':'not_requested'} for row in result['comparison']['rows'])


@pytest.mark.parametrize('missing', [None, {}])
def test_actual_missing_stats_remain_unknown_not_unsupported(performance_bridge, missing):
    bridge = performance_bridge
    bridge.statistics[0] = missing
    row = comparison.collect(bridge, 'session', 'team-root')['comparison']['classifications'][0]
    assert row['state'] == 'unknown'
    assert row['player']['current_team_state'] == 'unavailable_statistics_source'


def test_unavailable_history_is_successful_explicit_source_data(performance_bridge):
    def unavailable(b,n,response):
        response['history'].update(state='unavailable', reason='resident_source_not_decoded',
                                   native_entry_count=None, returned_row_count=0, rows=[], skipped_entries=[])
    performance_bridge.hooks['history'] = unavailable
    history = comparison.collect(performance_bridge, 'session', 'team-root', limit=1)['comparison']['rows'][0]['archived_league_history']
    assert history['state'] == 'unavailable' and history['source_native_entry_count'] is None
    assert history['reason'] == 'resident_source_not_decoded'


def test_checked_empty_roster_has_no_source_reads(performance_bridge):
    performance_bridge.order = []
    result = comparison.collect(performance_bridge, 'session', 'team-root')['comparison']
    assert result['counts']['roster_count'] == 0 and result['rows'] == []
    assert performance_bridge.calls == [('squad',None), ('squad',None), ('save',None)]


@pytest.mark.parametrize('mutation', ['current', 'history', 'save', 'roster_order', 'roster_public',
                                    'duplicate_binding', 'late_child_eviction', 'late_child_identity', 'team_context'])
def test_drift_discards_complete_result_and_cleans_new_refs(performance_bridge, mutation):
    bridge = performance_bridge
    initial = [set(cache) for cache in (bridge.player_refs, bridge.team_refs, bridge.competition_refs)]
    if mutation == 'current':
        bridge.hooks['current'] = lambda b,n,r: r['statistics'].update(extra=True) if n==5 else None
    elif mutation == 'history':
        bridge.hooks['history'] = lambda b,n,r: r['history'].update(extra=True) if n==3 else None
    elif mutation == 'save':
        bridge.hooks['save'] = lambda b,n,r: r['save'].update(current_date='2030-10-29')
    elif mutation == 'roster_order':
        bridge.hooks['history'] = lambda b,n,r: b.order.reverse() if n==4 else None
    elif mutation == 'roster_public':
        bridge.hooks['squad'] = lambda b,n,r: r['players'][0].update(name='Changed') if n==2 else None
    elif mutation == 'duplicate_binding':
        def duplicate(b,n,r):
            first,second = [row['player_ref'] for row in r['players'][:2]]
            b.player_refs[second].update({key:deepcopy(b.player_refs[first][key]) for key in ('address','identity','tables')})
        bridge.hooks['squad'] = duplicate
    elif mutation == 'late_child_eviction':
        bridge.hooks['save'] = lambda b,n,r: b.competition_refs.clear()
    elif mutation == 'late_child_identity':
        def change(b,n,r):
            for key,value in b.team_refs.items():
                if key != 'team-root': value['identity'] = b'changed'
        bridge.hooks['save'] = change
    else:
        bridge.hooks['squad'] = lambda b,n,r: r.update(label='Different squad') if n==2 else None
    with pytest.raises(ValueError): comparison.collect(bridge, 'session', 'team-root')
    for cache, old in zip((bridge.player_refs, bridge.team_refs, bridge.competition_refs), initial):
        assert set(cache) <= old


def test_existing_invalidated_refs_are_never_resurrected(performance_bridge):
    bridge = performance_bridge
    def fail(b,n,response):
        b.player_refs.pop('old-player', None)
        b.competition_refs.clear()
        raise RuntimeError('late archive read failed')
    bridge.hooks['history'] = fail
    with pytest.raises(RuntimeError, match='late archive'):
        comparison.collect(bridge, 'session', 'team-root')
    assert bridge.player_refs == {} and bridge.competition_refs == {}
    assert set(bridge.team_refs) == {'team-root'}


@pytest.mark.parametrize('arguments', [{'minimum_minutes':True}, {'minimum_minutes':-1},
    {'minimum_minutes':32768}, {'limit':False}, {'limit':0}, {'limit':26}, {'include_history':1},
    {'team_ref':''}, {'team_ref':None}])
def test_arguments_reject_before_source_queries(performance_bridge, arguments):
    args = {'team_ref':'team-root', **arguments}
    with pytest.raises(ValueError): comparison.collect(performance_bridge, 'session', **args)
    assert performance_bridge.calls == []


def test_cold_virtual_metadata_survives_complete_unsupported_classification(performance_bridge):
    bridge = performance_bridge
    bridge.players[4].update(
        name=None, display_name=None, birth_date=None, clubs=None,
        native_identity={'database_index':170218,'native_id':2002129873,'random_id':None},
        profile_state='identity_only', profile_unavailable_reason='negative_cache_index',
        unavailable_fields=['name','display_name','birth_date','attributes','clubs'],
        field_sources={'native_identity':'stored_direct','name':'unavailable_from_verified_sources'},
        roster_context={'team_database_index':1155,'team_native_id':1478})
    result = comparison.collect(bridge,'session','team-root',include_history=False)['comparison']
    row = result['classifications'][4]
    assert row['state'] == 'unsupported' and row['reason'] == 'unsupported_record_kind'
    assert row['player']['name'] is None and row['player']['clubs'] is None
    assert row['player']['native_identity']['native_id'] == 2002129873
    assert row['player']['profile_state'] == 'identity_only'
    assert row['player']['roster_context']['team_native_id'] == 1478
    assert row['player']['unavailable_fields'][-1] == 'clubs'
    assert not any(method == 'current' and index == 4 for method,index in bridge.calls)
    assert result['counts']['roster_count'] == 5
    assert result['ranking_complete_for_roster'] is False
