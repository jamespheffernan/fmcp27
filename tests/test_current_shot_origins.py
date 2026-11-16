import asyncio
import copy
import gzip
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import active_match_shot_timeline as timeline
from fm_live_mcp import current_shot_origins as query


def actual():
    with gzip.open(Path(__file__).parent / 'fixtures/lille_active_shot_origin_source.json.gz', 'rt') as f:
        packet = json.load(f)
    source = packet['source']
    source['events'] = bytes.fromhex(source['events'])
    source['vectors'] = [bytes.fromhex(v) for v in source['vectors']]
    chance = timeline.project(source, packet['bound'])
    return {'state': 'available_fixture_bound', 'fixture': packet['fixture'], 'chance_breakdown': chance}, source, packet['bound']


def test_actual_verified_lille_source_groups_all15_prefix_shots_without_future_totals():
    report, source, bound = actual()
    before = copy.deepcopy(report)
    output = query.project_shot_origins(report)
    assert output['current_time_slice'] == 15064
    assert [side['shots'] for side in output['sides']] == [8, 7]
    assert [side['shots_on_target'] for side in output['sides']] == [5, 4]
    for side in output['sides']:
        assert sum(zone['shots'] for zone in side['by_native_zone'].values()) == side['shots']
        assert sum(area['shots'] for area in side['by_area'].values()) == side['shots']
    assert report == before
    assert 'team_statistics' not in output and 'displayed_score' not in output
    assert output['physical_units'] is None and output['human_left_right'] is None


def test_xg_failure_keeps_origin_counts_but_every_group_xg_null_including_empty_groups():
    report, source, bound = actual()
    for side in source['engine_totals']:
        side['expected_goals'] += .1
    report['chance_breakdown'] = timeline.project(source, bound)
    output = query.project_shot_origins(report)
    assert [side['shots'] for side in output['sides']] == [8, 7]
    for side in output['sides']:
        assert side['expected_goals_sum_computed'] is None
        assert all(zone['expected_goals_sum_computed'] is None for zone in side['by_native_zone'].values())


def test_unknown_count_source_stays_null_while_checked_empty_prefix_is_zero():
    report, source, bound = actual()
    source['engine_totals'][0]['shots'] += 1
    bound['current_time_slice'] = 1
    report['chance_breakdown'] = timeline.project(source, bound)
    output = query.project_shot_origins(report)
    assert output['sides'][0]['shots'] is None and output['sides'][0]['by_native_zone'] is None
    assert output['sides'][1]['shots'] == 0
    assert all(zone['shots'] == 0 and zone['share_of_selected_shots_pct'] is None
               for zone in output['sides'][1]['by_native_zone'].values())


def test_unclassified_location_keeps_denominator_and_native_fallback_is_separate():
    report, _, _ = actual()
    row = report['chance_breakdown']['shots'][0]
    row.update(native_location_bin=None, official_location=None, location_group=None, location_state='unavailable_pitch_geometry')
    output = query.project_shot_origins(report)
    assert output['sides'][0]['shots'] == 8
    assert output['sides'][0]['unclassified_shots'] == 1
    assert output['sides'][0]['by_area']['unclassified']['shots'] == 1
    row.update(native_location_bin=12, official_location='LocationOutsideBoxFarFromGoal',
               location_group='outside_area_or_native_fallback', location_state='native_renderer_predicate')
    output = query.project_shot_origins(report)
    assert output['sides'][0]['by_area']['outside_area_or_native_fallback']['shots'] >= 1


@pytest.mark.parametrize('mutation', ['future_end', 'duplicate', 'wrong_side', 'own_goal', 'zone_name', 'area'])
def test_hostile_attempt_identity_cutoff_or_zone_metadata_fails_closed(mutation):
    report, _, _ = actual()
    chance = report['chance_breakdown']; row = chance['shots'][0]
    if mutation == 'future_end':row['native_clock_end_raw'] = chance['current_time_slice']
    elif mutation == 'duplicate':chance['shots'].append(copy.deepcopy(row))
    elif mutation == 'wrong_side':row['side_index'] = 2
    elif mutation == 'own_goal':row['native_category_code'] = 49
    elif mutation == 'zone_name':row['official_location'] = 'InventedZone'
    else:row['location_group'] = 'outside_area' if row['location_group'] == 'inside_area' else 'inside_area'
    with pytest.raises(ValueError):query.project_shot_origins(report)


def test_unavailable_context_and_unverified_time_domain_never_become_zero_zones():
    assert query.project_shot_origins({'state': 'inactive', 'reason': 'empty', 'fixture': None})['sides'] is None
    report, _, _ = actual()
    report['chance_breakdown']['native_event_clock_domain_verified'] = False
    assert query.project_shot_origins(report)['reason'] == 'unavailable_verified_playback_event_cutoff'


def test_tool_schema_is_read_only_and_exposes_only_session_id():
    from fm_live_mcp.current_shot_origin_tools import register_current_shot_origin_tools
    async def check():
        mcp = FastMCP('Current shot origins')
        register_current_shot_origin_tools(mcp, None)
        tools = await mcp.list_tools()
        assert [tool.name for tool in tools] == ['fm_get_current_match_shot_origins']
        assert set(tools[0].inputSchema['properties']) == {'session_id'}
        assert tools[0].annotations.readOnlyHint is False
    asyncio.run(check())


def test_canonical_server_registers_user_callable_current_origin_tool():
    from fm_live_mcp.server import mcp
    async def check():
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        tool = tools['fm_get_current_match_shot_origins']
        assert set(tool.inputSchema['properties']) == {'session_id'}
        assert tool.annotations.readOnlyHint is False
    asyncio.run(check())


def test_runtime_adapter_uses_one_checked_event_report_and_no_tactics_or_extra_capture(monkeypatch):
    report, _, _ = actual(); report.update(observed_at='verified', saved_file_fallback=False)
    calls = []
    def capture(bridge, sid, **kwargs):
        calls.append((bridge, sid, kwargs))
        return report
    monkeypatch.setattr(query, 'current_match_report', capture)
    output = query.current_shot_origins('bridge', 'session')
    assert calls == [('bridge', 'session', {'include_tactics': False, 'include_shot_events': True})]
    assert [side['shots'] for side in output['sides']] == [8, 7]
    assert output['observed_at'] == 'verified' and output['saved_file_fallback'] is False
