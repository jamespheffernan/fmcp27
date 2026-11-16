import asyncio
from contextlib import contextmanager
import sys
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import captured_crossing_tools as tools


PIN = 'a' * 64


def test_pinned_report_uses_source_connection_and_finishes_verification_before_return(monkeypatch):
    db = object()
    calls = []
    provenance = {'capture_id': PIN, 'source_kind': 'captured_live_export',
                  'captured_save': {'current_date': '2030-10-28'}}

    @contextmanager
    def open_source(source_id, **pins):
        calls.append(('open', source_id, pins))
        yield db, provenance
        calls.append(('verified_after_read',))

    def report(connection, **selectors):
        assert connection is db
        calls.append(('report', selectors))
        return {'coverage': {'fixtures': 9}}

    monkeypatch.setitem(sys.modules, 'fm_live_mcp.captured_match_sources',
                        SimpleNamespace(open_source=open_source))
    monkeypatch.setitem(sys.modules, 'fm_live_mcp.match_crossing_report',
                        SimpleNamespace(report_connection=report, ReportUnavailable=LookupError))
    result = tools.report_captured_crossing(
        'premier_league_2030_10_28', expected_capture_id=PIN,
        competition_id=11, team_id=713, date_from='2030-08-01', date_to='2030-10-28',
        venue='away', leaders=5, minimum_minutes=90)
    assert calls[-1] == ('verified_after_read',)
    assert calls[0][2]['expected_capture_id'] == PIN
    assert calls[1][1]['venue'] == 'away'
    assert result['dataset_source'] == provenance
    assert not result['current_game_verified']
    assert result['evidence_kind'] == 'historical_captured_live_export'
    assert 'No automatic live fallback' in result['claim_scope']


def test_source_change_rejection_returns_no_report(monkeypatch):
    @contextmanager
    def changed(*args, **kwargs):
        yield object(), {'capture_id': PIN}
        raise ValueError('Dataset changed during read')

    monkeypatch.setitem(sys.modules, 'fm_live_mcp.captured_match_sources',
                        SimpleNamespace(open_source=changed))
    monkeypatch.setitem(sys.modules, 'fm_live_mcp.match_crossing_report',
                        SimpleNamespace(report_connection=lambda *_args, **_kwargs: {}, ReportUnavailable=LookupError))
    with pytest.raises(ValueError, match='changed during read'):
        tools.report_captured_crossing('premier_league_2030_10_28', expected_capture_id=PIN,
                                     competition_id=11, team_id=713,
                                     date_from='2030-08-01', date_to='2030-10-28')


def test_tool_discovery_requires_source_pin_and_has_no_path_or_sql_arguments():
    async def check():
        mcp = FastMCP('Captured crossing test')
        tools.register_captured_crossing_tools(mcp)
        tool, = await mcp.list_tools()
        assert tool.name == 'fm_report_captured_match_crossing'
        assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
        schema = tool.inputSchema
        assert set(schema['required']) == {'source_id', 'expected_capture_id', 'competition_id',
                                          'team_id', 'date_from', 'date_to'}
        assert not {'path', 'sql', 'session_id'} & schema['properties'].keys()
        assert schema['properties']['leaders']['maximum'] == 20
        assert schema['properties']['date_from']['maxLength'] == 10
        assert schema['properties']['date_to']['pattern'] == '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
        assert schema['properties']['venue']['enum'] == ['all', 'home', 'away']
        assert schema['properties']['source_id']['pattern'] == '^[a-z0-9_]{1,80}$'
    asyncio.run(check())


def test_uncaptured_crossing_fields_preserve_source_provenance(monkeypatch):
    class ReportUnavailable(ValueError):
        missing_fields = {'team_totals': ['crosses_attempted']}

    @contextmanager
    def source(*args, **kwargs):
        yield object(), {'capture_id': PIN, 'captured_save': {'current_date': '2030-10-29'},
                         'captured_scope': {'date_to': '2030-10-28'}}

    def unavailable(*args, **kwargs):
        raise ReportUnavailable('Fields not captured')

    monkeypatch.setitem(sys.modules, 'fm_live_mcp.captured_match_sources', SimpleNamespace(open_source=source))
    monkeypatch.setitem(sys.modules, 'fm_live_mcp.match_crossing_report',
                        SimpleNamespace(report_connection=unavailable, ReportUnavailable=ReportUnavailable))
    result = tools.report_captured_crossing('premier_league_2030_10_28', expected_capture_id=PIN,
                                         competition_id=11, team_id=713,
                                         date_from='2030-08-01', date_to='2030-10-28')
    assert result['state'] == 'unavailable'
    assert result['report']['missing_fields'] == {'team_totals': ['crosses_attempted']}
    assert result['dataset_source']['captured_save']['current_date'] == '2030-10-29'
    assert result['dataset_source']['captured_scope']['date_to'] == '2030-10-28'


def test_large_tied_leader_groups_are_bounded_and_explicit(monkeypatch):
    @contextmanager
    def source(*args, **kwargs):
        yield object(), {'capture_id': PIN, 'available_tables': {'retained_players': ['x']},
                         'field_provenance': {'unneeded': 'large registry'}}

    monkeypatch.setitem(sys.modules, 'fm_live_mcp.captured_match_sources', SimpleNamespace(open_source=source))
    monkeypatch.setitem(sys.modules, 'fm_live_mcp.match_crossing_report',
                        SimpleNamespace(report_connection=lambda *_args, **_kwargs: {
                            'leaders': {'all': [{'rank': 1}] * 101}}, ReportUnavailable=LookupError))
    result = tools.report_captured_crossing('premier_league_2030_10_28', expected_capture_id=PIN,
                                         competition_id=11, team_id=713,
                                         date_from='2030-08-01', date_to='2030-10-28')
    assert len(result['report']['leaders']['all']) == 100
    assert result['response_bounds']['truncated_lists'] == [
        {'path': 'report.leaders.all', 'total_rows': 101, 'returned_rows': 100,
         'cutoff_ties_may_be_truncated': True}]
    assert 'field_provenance' not in result['dataset_source']
    assert 'available_tables' not in result['dataset_source']
