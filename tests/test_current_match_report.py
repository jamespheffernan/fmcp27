from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from fm_live_mcp import current_match_report as report


def teams():
    return [{'native_id': 11, 'database_index': 5}, {'native_id': 13, 'database_index': 9}]


def performance():
    def sides(attempts):
        return [{'side_index': i, 'team_native_id': t['native_id'], 'team_index': t['database_index'],
                 'shots': n, 'shots_on_target': 0, 'expected_goals': n * 0.25}
                for i, (n, t) in enumerate(zip(attempts, teams(), strict=True))]
    return {'state': 'available_engine_cumulative_display_time_unverified', 'sides': sides([4, 3]),
            'client_statistics_snapshot': {'sides': sides([3, 0])}}


def binding(monkeypatch, *, bound):
    home, away = teams()
    fixture = dict(date='2030-11-02', competition={'native_id': 72}, home_team=home, away_team=away,
                   scores={'final_score': {'home': 9, 'away': 7}})
    source = {'source_state': 'available_fixture_bound' if bound else 'present_unbound',
              'reason': None if bound else 'ambiguous', 'physical_client_count': 1 if bound else 2,
              'bound_active_fixture': fixture if bound else None}
    private = {'client': 10000, 'engine': 20000, 'team_indices': [5, 9]} if bound else None
    monkeypatch.setattr(report.active_match_source, 'inspect_context', Mock(return_value=(source, private)))
    return source, private


def test_default_scope_has_only_client_observations_and_fixture_identity(monkeypatch):
    binding(monkeypatch, bound=True)
    monkeypatch.setattr(report.active_match_playback, 'capture', Mock(return_value={'state': 'no_playback_match'}))
    monkeypatch.setattr(report.live_match_performance, 'inspect', Mock(return_value=performance()))
    monkeypatch.setattr(report.resident_match_plans, 'inspect', Mock(side_effect=AssertionError))
    result = report._inspect(Mock(), 10, '2030-11-02', 'client_snapshot', False)
    assert 'scores' not in result['fixture']
    assert result['displayed_score'] is None and result['displayed_minute'] is None
    assert result['tactics'] is None
    stats = result['team_statistics']
    assert stats['scope'] == 'client_snapshot' and not stats['displayed_time_verified']
    assert [row['shots'] for row in stats['sides']] == [3, 0]
    assert [row['expected_goals_per_shot'] for row in stats['sides']] == [.25, None]
    assert 'engine' not in str(stats)


def test_explicit_engine_scope_and_wrong_side_fail_closed():
    source = performance()
    engine = report._statistics(source, 'simulation', teams())
    assert [r['shots'] for r in engine['sides']] == [4, 3]
    source['sides'][1]['team_index'] = 7
    with pytest.raises(ValueError, match='disagree'):
        report._statistics(source, 'simulation', teams())
    missing = report._statistics({'state': 'unavailable_engine_statistics_absent', 'sides': None}, 'simulation', teams())
    assert missing['sides'] is None


def test_unbound_does_not_read_match_stats_or_return_guesses(monkeypatch):
    binding(monkeypatch, bound=False)
    monkeypatch.setattr(report.live_match_performance, 'inspect', Mock(side_effect=AssertionError))
    result = report._inspect(Mock(), 10, '2030-11-02', 'client_snapshot', True)
    assert result['state'] == 'present_unbound' and result['reason'] == 'ambiguous'
    assert result['fixture'] is None and result['tactics'] is None and result['team_statistics'] is None


def test_rapid_match_recaptured_then_rechecked(monkeypatch):
    source = Mock()
    source.verify.side_effect = [ValueError('Game state changed during read; retry'), None]
    bridge = Mock()
    bridge.lock = nullcontext()
    bridge._read_scope.side_effect = lambda _, **_kw: nullcontext()
    bridge._player_layout.return_value = [100]
    bridge.plugin_identity = ('isolated-report-projection', b'isolated runtime')
    bridge.world_identity = None
    # Isolated retry fixture has no Mach-O/native layout. The strict runtime
    # publication fixtures exercise the actual verifier and Bridge path.
    monkeypatch.setattr(report.players, 'verify_runtime', lambda *_: [100])
    bridge._world_state.return_value = (source, {'current_date': '2030-11-02'}, None)
    bridge._public_save.return_value = {'current_date': '2030-11-02'}
    monkeypatch.setattr(report, '_inspect', Mock(side_effect=[{'state':'old'}, {'state':'refreshed'}]))
    result = report.current_match_report(bridge, 'sid')
    assert result['state'] == 'refreshed' and result['saved_file_fallback'] is False
    assert source.verify.call_count == 2 and bridge._world_state.call_count == 2


def test_playback_projection_uses_only_checked_cursor_and_matching_half_boundary(monkeypatch):
    private = {'client': 10000, 'engine': 20000}
    bound = {'current_time_slice': 23000, 'frame_provider_address': 50000}
    boundary = {'state': 'verified_first_half_boundary'}
    split = {'state': 'available', 'reason': None, 'first_half_boundary': boundary,
             'period_source': {'source_state': 'available', 'simulation_period': 'SecondHalf', 'reason': None}}
    monkeypatch.setattr(report.active_match_playback, 'capture', Mock(return_value={'state': 'bound_playback_cursor', 'bound_playback': bound}))
    monkeypatch.setattr(report.active_match_half_boundaries, 'inspect', Mock(return_value=split))
    score = Mock(return_value={'state': 'available_at_bound_playback_cursor',
                               'current_score': {'state': 'available', 'home_goals': 2, 'away_goals': 1},
                               'first_half_score': {'state': 'available', 'home_goals': 1, 'away_goals': 0}})
    monkeypatch.setattr(report.active_match_score, 'capture', score)
    timeline = Mock(return_value={'state': 'available_partial', 'sides': [], 'shots': [], 'own_goal_markers': []})
    monkeypatch.setattr(report.active_match_shot_timeline, 'inspect_bound', timeline)
    read = Mock()
    value = report._playback_report(read, 10, private, False)
    score.assert_called_once_with(read, 10, bound_playback=bound, trusted_first_half_boundary=boundary)
    timeline.assert_called_once_with(read, 10, 10000, 20000, bound, period_split=split, capture_observation=True)
    assert value['displayed_score'] == {'home': 2, 'away': 1}
    assert value['half_time_score'] == {'home': 1, 'away': 0}
    assert value['displayed_period'] == 'SecondHalf'
    assert 'frame_provider_address' not in str(value)
    assert 'shots' not in value['chance_breakdown']


def test_report_pages_verify_consumed_bytes_and_cross_page_reads():
    from fm_live_mcp.current_match_report import ReportReadSet
    memory = bytearray(12288)
    calls = []
    def raw(address, length):
        calls.append((address, length))
        return bytes(memory[address:address+length])
    read = ReportReadSet(raw)
    assert read(4094, 6) == bytes(6)
    assert read(4096, 2) == bytes(2)
    assert len(calls) == 2
    memory[4105] = 1  # Unconsumed padding may change.
    read.verify()
    memory[4097] = 1  # A consumed byte must reject.
    import pytest
    with pytest.raises(ValueError, match='Game state changed'):
        read.verify()


def test_report_page_cache_is_not_shared_between_queries():
    from fm_live_mcp.current_match_report import ReportReadSet
    memory = bytearray(4096)
    raw = lambda address, length: bytes(memory[address:address+length])
    assert ReportReadSet(raw)(1, 1) == b'\0'
    memory[1] = 7
    assert ReportReadSet(raw)(1, 1) == b'\7'


def test_conditional_playback_recheck_rejects_rewind_period_change_and_large_jump():
    import struct
    from fm_live_mcp.current_match_report import _cursor_advance, _period_advance
    pack = lambda a, b: struct.pack('<II', a, b)
    assert _cursor_advance(pack(100, 120), pack(105, 125))
    assert not _cursor_advance(pack(100, 120), pack(99, 125))
    assert not _cursor_advance(pack(100, 120), pack(105, 119))
    assert not _cursor_advance(pack(100, 120), pack(105, 104))
    assert not _cursor_advance(pack(100, 120), pack(5000, 5100))
    assert _period_advance(struct.pack('<iB', 100, 6), struct.pack('<iB', 105, 6))
    assert not _period_advance(struct.pack('<iB', 100, 6), struct.pack('<iB', 105, 1))
    assert not _period_advance(struct.pack('<iB', 100, 6), struct.pack('<iB', 99, 6))


def test_precise_statistics_reader_preserves_selected_zero_and_identity():
    import struct
    from fm_live_mcp.current_match_report import _statistics_reader
    client, engine, stats = 0x1000, 0x2000, 0x3000
    memory = bytearray(0x20000)
    struct.pack_into('<Q', memory, engine + 0x14e90, stats)
    for source, sides in ((stats, (0x5000, 0x6000)), (client+8, (0x7000, 0x8000))):
        struct.pack_into('<QQ', memory, source + 0x68, *sides)
        for side in sides:
            struct.pack_into('<I', memory, side + 0x5c, 545)
            struct.pack_into('<i', memory, side + 0x7c, 1234)
            memory[side+0x80] = 99
    consumed = []
    def read(a, n):
        consumed.append((a, n))
        return bytes(memory[a:a+n])
    project = _statistics_reader(read, client, engine, 'client_snapshot')
    project(stats, 0x78)
    engine_row = project(0x5000, 0x1a0)
    project(client+8, 0x78)
    client_row = project(0x7000, 0x1a0)
    assert struct.unpack_from('<I', engine_row, 0x5c)[0] == 545
    assert struct.unpack_from('<i', engine_row, 0x7c)[0] == 0
    assert struct.unpack_from('<i', client_row, 0x7c)[0] == 1234
    assert client_row[0x16f] == 0
    assert (0x5000 + 0x7c, 4) not in consumed
    assert client_row[0x80] == 0  # Unused memory was neither read nor projected.


def test_requested_shot_events_bind_names_in_same_readset_and_bound_match(monkeypatch):
    read=Mock();private={'client':10000,'engine':20000}
    bound={'current_time_slice':100,'frame_provider_address':50000,'official_match_unique_id':123}
    split={'state':'available','reason':None,'first_half_boundary':None,
           'period_source':{'source_state':'available','simulation_period':'FirstHalf','reason':None}}
    monkeypatch.setattr(report.active_match_playback,'capture',Mock(return_value={'state':'bound_playback_cursor','bound_playback':bound}))
    monkeypatch.setattr(report.active_match_half_boundaries,'inspect',Mock(return_value=split))
    monkeypatch.setattr(report.active_match_score,'capture',Mock(return_value={'state':'unknown','current_score':None,'first_half_score':None}))
    actors={'state':'validated_native_stored_slots','official_match_unique_id':123,'players':[]}
    actor_read=Mock(return_value=actors);monkeypatch.setattr(report.active_match_people,'inspect_actor_bindings',actor_read)
    timeline=Mock(return_value={'state':'available','shots':[],'own_goal_markers':[]})
    monkeypatch.setattr(report.active_match_shot_timeline,'inspect_bound',timeline)
    result=report._playback_report(read,10,private,True)
    actor_read.assert_called_once_with(read,10,20000,expected_match_unique_id=123)
    timeline.assert_called_once_with(read,10,10000,20000,bound,period_split=split,capture_observation=True,actor_binding=actors)
    assert result['chance_breakdown']['shots']==[]


def _mapped(monkeypatch, sites):
    """A mapped build whose unresolved sites are `sites` (no real map is loaded)."""
    from fm_live_mcp import address_book
    monkeypatch.setattr(address_book, 'MAP', {'values': {}})
    monkeypatch.setattr(address_book, 'unresolved_sites', lambda: sites)
    for section in (report._tactics_section, report.current_match_native_playback._changes,
                    report.current_match_native_playback._events):
        section._blocked = None
        section.blocked()           # walked over the real code, before a test replaces any of it


def test_tactics_section_reports_the_build_sites_that_refuse(monkeypatch):
    from fm_live_mcp import address_book
    assert report.tactics_unavailable_on_build() == [] or address_book.MAP is not None
    _mapped(monkeypatch, {
        ('fm_live_mcp.resident_match_plans', 'module:NATIVE_SPANS'): [(0x451F248, 'code differs')],
        ('fm_live_mcp.live_match_performance', 'module:NATIVE_SPANS'): [(0x27EA20C, 'code differs')]})
    blocked = report.tactics_unavailable_on_build()
    assert blocked and all('resident_match_plans' in r for r in blocked)
    assert not any('live_match_performance' in r for r in blocked)


def test_mapped_build_answers_with_only_the_tactics_section_unavailable(monkeypatch):
    _mapped(monkeypatch, {('fm_live_mcp.resident_match_plans', 'module:NATIVE_SPANS'): [(0x451F248, 'code differs')]})
    binding(monkeypatch, bound=True)
    monkeypatch.setattr(report.active_match_playback, 'capture', Mock(return_value={'state': 'no_playback_match'}))
    monkeypatch.setattr(report.live_match_performance, 'inspect', Mock(return_value=performance()))
    monkeypatch.setattr(report.resident_match_plans, 'inspect', Mock(side_effect=AssertionError))
    for include_tactics in (True, False):
        result = report._inspect(Mock(), 10, '2030-11-02', 'client_snapshot', include_tactics)
        assert [r['shots'] for r in result['team_statistics']['sides']] == [3, 0]
        if include_tactics:
            assert result['tactics']['state'] == 'unavailable'
            assert result['tactics']['reason'] == 'stored_plan_decoders_unavailable_on_this_build'
            assert '0x451f248' in result['tactics']['native_sites'][0]
        else:
            assert result['tactics'] is None


def test_mapped_build_marks_player_changes_unavailable_and_keeps_the_rest(monkeypatch):
    nat = report.current_match_native_playback
    _mapped(monkeypatch, {('fm_live_mcp.native_player_removal_source', 'module:NATIVE_SPANS'): [(0x4A796D0, 'no match')]})
    monkeypatch.setattr(nat.active_match_entity_identity, 'capture_actor_source', Mock(return_value={'reason': 'x'}))
    monkeypatch.setattr(nat.native_player_removal_source, 'capture', Mock(side_effect=AssertionError))
    out = nat.inspect(Mock(), 10, {'engine': 1}, {'source_match_address': 2, 'official_match_unique_id': 3},
                      include_events=False, event_limit=5, include_changes=True)
    assert out['player_changes']['state'] == 'unavailable' and out['player_changes']['rows'] is None
    assert '0x4a796d0' in out['player_changes']['native_sites'][0]


def test_partial_tools_lists_sections_and_unavailable_tools_skips_them(monkeypatch):
    from fm_live_mcp import address_book
    _mapped(monkeypatch, {('fm_live_mcp.resident_match_plans', 'module:NATIVE_SPANS'): [(0x451F248, 'code differs')]})
    tools = {'current': report.current_match_report, 'plans': report.resident_match_plans.inspect}
    assert set(address_book.unavailable_tools(tools)) == {'plans'}
    assert set(address_book.partial_tools(tools)) == {'current'}
    assert set(address_book.partial_tools(tools)['current']) == {'tactics'}
