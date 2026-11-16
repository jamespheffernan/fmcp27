"""Real SDK dispatch + complete synthetic spatial witnesses; no live proof."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from fm_live_mcp import retained_period_width as width, retained_period_width_tools as tools
from fm_live_mcp import spatial_period_witness as witness
from fm_live_mcp.spatial_period_observations import SpatialPeriodStore
from test_spatial_period_witness import synthetic

TOOL = 'fm_report_retained_lateral_width_by_period'
ARGS = dict(session_id='session', fixture_ref='selected', team_native_id=688)


def control(monkeypatch, tmp_path, *, present=True):
    save, fixture, parent, _, actors, tracking, captured = synthetic()
    fixture['fixture_ref'] = 'selected'
    actors[1]['side_index'] = tracking['players'][1]['side_index'] = 1
    for actor in actors:
        actor.update(fixture_key=7, canonical_team_id=688 if actor['side_index'] == 0 else 705,
                     team_index_word=9 if actor['side_index'] == 0 else 10)
    captured['tracking_fingerprint'] = witness.tracking_fingerprint(tracking, actors, 145)
    candidate = dict(bound=dict(current_time_slice=145, official_match_unique_id=9001),
                     split=dict(period_markers=parent['period_markers']))
    observation = witness.make_observation(save, fixture, candidate, captured, 'a' * 64, '2030-11-11T20:00:00Z')
    store = SpatialPeriodStore(tmp_path / 'observations')
    if present:
        store.save(observation)
    before = snapshot(store.root)
    def forbidden(*args, **kwargs):
        pytest.fail('Read-only report attempted host metadata publication')
    for name in ('save', 'finalize', '_mutate'):
        monkeypatch.setattr(store, name, forbidden)
    monkeypatch.setattr(width, 'SpatialPeriodStore', lambda: store)
    packet = dict(_live_capture_epoch='epoch', capture=dict(save=save,
        fixtures=[dict(fixture=fixture, native_match_key=7)]), retained_players=actors,
        team_totals=dict(records=[dict(result_key=7, teams=[
            dict(team_index=9, team_identity_word=688), dict(team_index=10, team_identity_word=705)])]))
    source = dict(state='available', tracking=dict(tracking, state='available'),
                  owner_team_native_id=688, coach_index=0, coach_name='Synthetic')
    captures, sources, scopes = [], [], []
    def capture(bridge, sid, refs, **kwargs):
        assert sid == 'session' and refs == ['selected'] and kwargs == {'include_players': True}
        captures.append(deepcopy(packet))
        return captures[-1]
    def retained(bridge, sid, ref, key, native_fixture, **kwargs):
        assert (sid, ref, key) == ('session', 'selected', 7) and native_fixture == fixture
        assert kwargs == {'include_tracking': True}
        sources.append(deepcopy(source))
        return sources[-1]
    monkeypatch.setattr(width, 'capture_live', capture)
    monkeypatch.setattr(width.retained, 'capture_source', retained)
    monkeypatch.setattr(width, 'capture_epoch', lambda bridge, sid: 'epoch')
    monkeypatch.setattr(width, 'process_epoch', lambda bridge: 'd' * 64)
    spans = {}
    for at, raw in width.current_spatial_axes.NATIVE_SPANS + witness.PERIOD_CLOCK_SPANS + width.active_match_tracking.CLOCK_BINDING_SPANS:
        for i, byte in enumerate(raw):
            assert at + i not in spans or spans[at + i] == byte
            spans[at + i] = byte
    class Read:
        def __call__(self, at, size): return bytes(spans[at - 4096 + i] for i in range(size))
        def verify(self): scopes.append('verified_readset')
    @contextmanager
    def scope(sid):
        assert sid == 'session'
        scopes.append('enter')
        try: yield
        finally: scopes.append('exit')
    def current(sid):
        assert sid == 'session'
        return object()
    bridge = SimpleNamespace(lock=scope('session'), _read_scope=scope, _current=current,
        _player_layout=lambda process: (4096 + width.players.RVA[0],),
        _world_state=lambda process, tables: (Read(), save, None))
    mcp = FastMCP()
    tools.register_retained_period_width_tools(mcp, bridge)
    return SimpleNamespace(mcp=mcp, store=store, before=before, packet=packet, source=source,
                           captures=captures, sources=sources, spans=spans, scopes=scopes)


def snapshot(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_mode)
            for p in root.rglob('*') if p.is_file()}


def invoke(c, **changes):
    return asyncio.run(c.mcp.call_tool(TOOL, {**ARGS, **changes}))[1]


def test_real_sdk_schema_declares_exact_selector_bounds_and_readonly_effects():
    mcp = FastMCP(); tools.register_retained_period_width_tools(mcp, object())
    tool, = asyncio.run(mcp.list_tools())
    assert tool.name == TOOL and tool.outputSchema
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is tool.annotations.openWorldHint is False
    assert set(tool.inputSchema['properties']) == set(tool.inputSchema['required']) == set(ARGS)
    assert tool.inputSchema['properties']['fixture_ref']['minLength'] == 1
    assert tool.inputSchema['properties']['fixture_ref']['maxLength'] == 128
    assert tool.inputSchema['properties']['team_native_id']['type'] == 'integer'
    assert tool.inputSchema['properties']['team_native_id']['exclusiveMinimum'] == 0
    assert 'Reads existing host observations only' in tool.description
    assert 'periods=null' in tool.description and 'native coordinate units' in tool.description


def test_sdk_complete_synthetic_witness_projects_exact_mean_abs_denominators_and_unknown(monkeypatch, tmp_path):
    c = control(monkeypatch, tmp_path)
    r = invoke(c)
    assert r['state'] == 'available' and r['native_match_key'] == 7 and r['team_native_id'] == 688
    first, second = r['periods']
    assert [(p['start_tick'], p['end_tick']) for p in r['periods']] == [(1, 49), (73, 145)]
    assert [[p['canonical_person_id'] for p in period['players']] for period in r['periods']] == [[100, 102], [100, 102]]
    assert first['players'][0]['all_samples']['mean_absolute_lateral_native'] == 10
    assert second['players'][0]['all_samples']['sample_count'] == 3
    assert second['players'][0]['all_samples']['mean_absolute_lateral_native'] == pytest.approx(20 / 3)
    assert second['players'][0]['in_possession']['sample_count'] == 2
    assert second['players'][0]['all_samples']['zero_pair_sample_count'] == 2
    assert first['players'][1]['all_samples'] is None  # no stream is not a zero mean
    assert r['fixture_observed_sample_count'] == 12 and r['fixture_unassigned_observed_sample_count'] == 2
    assert r['physical_units'] is r['human_left_right'] is r['minute_conversion'] is None
    assert r['source_rechecked'] is True and r['source_epoch_matches_current'] is False
    assert len(c.captures) == len(c.sources) == 2 and 'verified_readset' in c.scopes
    assert snapshot(c.store.root) == c.before


def test_sdk_exact_away_team_selection_keeps_own_players_and_full_fixture_denominators(monkeypatch, tmp_path):
    c = control(monkeypatch, tmp_path)
    r = invoke(c, team_native_id=705)
    assert all([row['canonical_person_id'] for row in p['players']] == [101] for p in r['periods'])
    assert r['periods'][0]['players'][0]['all_samples']['mean_absolute_lateral_native'] == 5
    assert r['fixture_observed_sample_count'] == 12
    assert snapshot(c.store.root) == c.before


def test_sdk_missing_witness_stays_null_without_creating_host_directory(monkeypatch, tmp_path):
    c = control(monkeypatch, tmp_path, present=False)
    r = invoke(c)
    assert r['state'] == 'unavailable_no_verified_spatial_period_source' and r['periods'] is None
    assert r['reason'] == 'prospective_tracking_specific_period_witness_missing_or_unmatched'
    assert len(c.captures) == len(c.sources) == 1 and not c.store.root.exists()


@pytest.mark.parametrize('field', ['coordinates', 'phase', 'actor'])
def test_sdk_existing_witness_cannot_authorize_changed_source(monkeypatch, tmp_path, field):
    c = control(monkeypatch, tmp_path)
    if field == 'coordinates': c.source['tracking']['players'][0]['samples'] = bytes(24)
    if field == 'phase': c.source['tracking']['possession_samples'] = b'\0'
    if field == 'actor': c.packet['retained_players'][0]['canonical_person_id'] += 1000
    r = invoke(c)
    assert r['state'] == 'unavailable_no_verified_spatial_period_source' and r['periods'] is None
    assert snapshot(c.store.root) == c.before


@pytest.mark.parametrize('field', ['actor', 'tracking', 'owner', 'epoch', 'native_clock'])
def test_sdk_drift_rejects_before_publishing_result(monkeypatch, tmp_path, field):
    c = control(monkeypatch, tmp_path)
    if field == 'actor':
        original = width.capture_live
        def capture(*args, **kwargs):
            packet = original(*args, **kwargs)
            if len(c.captures) == 2: packet['retained_players'][2]['person_name'] = 'Changed untracked actor'
            return packet
        monkeypatch.setattr(width, 'capture_live', capture)
    if field in ('tracking', 'owner'):
        original = width.retained.capture_source
        def source(*args, **kwargs):
            value = original(*args, **kwargs)
            if len(c.sources) == 2:
                if field == 'tracking': value['tracking']['players'][0]['samples'] = bytes(24)
                else: value['owner_team_native_id'] = 705
            return value
        monkeypatch.setattr(width.retained, 'capture_source', source)
    if field == 'epoch':
        epochs = iter(['epoch', 'changed'])
        monkeypatch.setattr(width, 'capture_epoch', lambda *args: next(epochs))
    if field == 'native_clock': c.spans[witness.PERIOD_CLOCK_SPANS[0][0]] ^= 1
    with pytest.raises(ToolError, match='changed'):
        invoke(c)
    assert snapshot(c.store.root) == c.before


@pytest.mark.parametrize('changes', [dict(team_native_id=True), dict(team_native_id='688'),
    dict(team_native_id=0), dict(team_native_id=-1), dict(team_native_id=999),
    dict(fixture_ref=''), dict(fixture_ref='x' * 129)])
def test_sdk_selector_failures_never_use_other_fixture_or_invent_zero(monkeypatch, tmp_path, changes):
    c = control(monkeypatch, tmp_path)
    with pytest.raises(ToolError):
        invoke(c, **changes)
    assert snapshot(c.store.root) == c.before


@pytest.mark.parametrize('field', ['fixture_ref', 'team_oracle', 'unresolved_actor'])
def test_sdk_checked_fixture_and_team_sources_cannot_be_substituted(monkeypatch, tmp_path, field):
    c = control(monkeypatch, tmp_path)
    if field == 'fixture_ref': c.packet['capture']['fixtures'][0]['fixture']['fixture_ref'] = 'other'
    if field == 'team_oracle': c.packet['team_totals']['records'][0]['teams'][0]['team_identity_word'] = 705
    if field == 'unresolved_actor': c.packet['retained_players'][0]['canonical_team_id'] = 705
    if field == 'unresolved_actor':
        r = invoke(c)
        assert r['periods'] is None and r['reason'] == 'unavailable_canonical_fixture_roster'
    else:
        with pytest.raises(ToolError, match='fixture|TEAM'):
            invoke(c)
    assert snapshot(c.store.root) == c.before


@pytest.mark.parametrize('state', ['unavailable_not_retained', 'unavailable_null_retained_source'])
def test_sdk_absent_native_source_stays_null_without_loading_host_observations(monkeypatch, tmp_path, state):
    c = control(monkeypatch, tmp_path)
    c.source.clear(); c.source['state'] = state
    monkeypatch.setattr(c.store, 'observations', lambda *args: pytest.fail('Absent source read host witnesses'))
    r = invoke(c)
    assert r['periods'] is None and r['reason'] == 'unavailable_retained_tracking_source'
    assert snapshot(c.store.root) == c.before
