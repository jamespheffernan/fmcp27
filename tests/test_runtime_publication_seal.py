"""Causal157 runtime/default-report proofs over actual Bridge/native verifiers."""
import hashlib
from pathlib import Path
import types

import pytest

from fm_live_mcp import current_match_report as report, live_individual_training as training, players, world
from fm_live_mcp.bridge import BridgeError
from runtime_publication_fixture import RuntimeRig, seed_absent_match
from test_bridge import bridge
from test_players import memory
from test_database import database_memory
from test_shortlist_members import member_memory
from test_teams import team_memory
from prepared_tactics_fixture import prepared_tactics_memory
from test_world import world_memory
from test_individual_training_focus import focus_memory, native_image
from test_default_training_intensity import default_memory, training_source_memory


def baseline(name):
    path = Path(__file__).parent / f'fixtures/{name}157.py.txt'
    expected = {'live_individual_training': 'b5d788982cf918cde2b42fe68be2b13d74e2f2ee508dc9a17ff34f383f19859d',
                'current_match_report': '6a4fbbf017362f57b84a134d918fabc353654c2a988770b358e17204d3adccb5'}
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected[name]
    module = types.ModuleType(f'fm_live_mcp._publication157_{name}')
    module.__package__ = 'fm_live_mcp'
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


@pytest.fixture
def strict_training(focus_memory, prepared_tactics_memory, bridge, monkeypatch, tmp_path):
    m = focus_memory
    assert m is prepared_tactics_memory
    bridge.player_refs['p1'] = m['focus_binding'].copy()
    return RuntimeRig(m, bridge, monkeypatch, tmp_path)


@pytest.fixture
def strict_report(world_memory, bridge, monkeypatch, tmp_path):
    seed_absent_match(world_memory)
    return RuntimeRig(world_memory, bridge, monkeypatch, tmp_path)


def train(rig, module=training, **kwargs):
    return module.get_player_individual_training(rig.bridge, rig.bridge.session, ['p1'], **kwargs)


def current_report(rig, module=report, **kwargs):
    return module.current_match_report(rig.bridge, rig.bridge.session, **kwargs)


@pytest.mark.parametrize('operand', ['uuid', 'rtti_displacement', 'rtti_name'])
def test_exact157_training_late_runtime_escape(strict_training, operand):
    rig = strict_training
    rig.hooks[5] = lambda r: r.mutate(operand)
    result = train(rig, baseline('live_individual_training'))
    assert result['players'][0]['additional_focus']['raw_code'] == 24
    assert (rig.m['base'], 16384) not in rig.read_sets[0].observed
    with pytest.raises(ValueError, match='UUID differs|displacement changed|runtime type changed'):
        players.verify_runtime(rig.read, rig.m['base'], rig.uuid)
    rig.closed()


@pytest.mark.parametrize('operand', ['uuid', 'rtti_displacement', 'rtti_name'])
def test_exact157_default_report_runtime_escape(strict_report, operand):
    rig = strict_report
    rig.hooks[4] = lambda r: r.mutate(operand)
    result = current_report(rig, baseline('current_match_report'))
    assert result['state'] == 'unknown' and result['reason'] == 'manager_absent'
    assert 'player_statistics' not in result and 'player_passing' not in result
    with pytest.raises(ValueError, match='UUID differs|displacement changed|runtime type changed'):
        players.verify_runtime(rig.read, rig.m['base'], rig.uuid)
    rig.closed()


@pytest.mark.parametrize('late', ['body_current', 'public_save', 'scope_current'])
def test_exact157_default_report_field_escape(strict_report, late):
    rig = strict_report
    if late == 'public_save': rig.public_hook = lambda r: r.mutate('save_count')
    else: rig.hooks[3 if late == 'body_current' else 4] = lambda r: r.mutate('save_count')
    result = current_report(rig, baseline('current_match_report'))
    assert result['save']['save_count'] == 418
    assert int.from_bytes(rig.read(rig.m['game'] + 0xC8, 4), 'little') == 419
    rig.closed()


@pytest.mark.parametrize('operand', ['uuid', 'rtti_displacement', 'rtti_name'])
@pytest.mark.parametrize('late', [3, 4, 5])
def test_training_runtime_publication_refuses_late_drift(strict_training, operand, late):
    rig = strict_training
    rig.hooks[late] = lambda r: r.mutate(operand)
    with pytest.raises(BridgeError, match='no partial result'):
        train(rig)
    assert (rig.m['base'], 16384) in rig.read_sets[0].observed
    rig.closed()


@pytest.mark.parametrize('operand', ['uuid', 'rtti_displacement', 'rtti_name'])
@pytest.mark.parametrize('late', [3, 4, 5, 6])
def test_report_runtime_publication_refuses_late_drift(strict_report, operand, late):
    rig = strict_report
    rig.hooks[late] = lambda r: r.mutate(operand)
    with pytest.raises((ValueError, BridgeError), match='UUID|displacement|type changed|state changed|binding|plugin'):
        current_report(rig)
    rig.closed()


@pytest.mark.parametrize('late', ['body_current', 'public_save', 'scope_current'])
def test_default_report_field_publication_refuses_late_drift(strict_report, late):
    rig = strict_report
    if late == 'public_save': rig.public_hook = lambda r: r.mutate('save_count')
    else: rig.hooks[3 if late == 'body_current' else 4] = lambda r: r.mutate('save_count')
    with pytest.raises((ValueError, BridgeError), match='save|context|state changed'):
        current_report(rig)
    rig.closed()


@pytest.mark.parametrize('route', ['training', 'report'])
def test_clean_payload_defaults_equal_exact157_and_both_runtime_journals_enrolled(request, route):
    rig = request.getfixturevalue('strict_training' if route == 'training' else 'strict_report')
    invoke, name = (train, 'live_individual_training') if route == 'training' else (current_report, 'current_match_report')
    expected = invoke(rig, baseline(name))
    rig.reset_trace()
    actual = invoke(rig)
    assert expected.pop('observed_at') and actual.pop('observed_at')
    assert actual == expected
    assert len(rig.read_sets) == 2
    for read in rig.read_sets:
        assert (rig.m['base'], 16384) in read.observed
        assert (rig.m['base'] + players.RVA[1] - 16, 16) in read.observed
        assert (rig.runtime_texts[1], len(b'N2db12PLAYING_DATAE') + 1) in read.observed
    last = max(i for i, event in enumerate(rig.events) if event[0] not in ('physical', 'close'))
    assert all(event[0] in ('physical', 'close') for event in rig.events[last + 1:])
    assert any(event[0] == 'physical' for event in rig.events[last + 1:])
    rig.closed()


@pytest.mark.parametrize('route', ['training', 'report'])
def test_extra_final_context_operand_is_fenced_after_last_callback(request, route):
    rig = request.getfixturevalue('strict_training' if route == 'training' else 'strict_report')
    extra = 0x700008
    rig.put(extra, b'\0' * 4)
    def world_hook(r, count, read):
        if count % 2 == 0: read(extra, 4)
    rig.world_hook = world_hook
    rig.hooks[5 if route == 'training' else 6] = lambda r: r.put(extra, b'\1\0\0\0')
    if route == 'report':rig.hooks[12] = lambda r:r.put(extra, b'\2\0\0\0')
    invoke = train if route == 'training' else current_report
    with pytest.raises((ValueError, BridgeError), match='changed during read'):
        invoke(rig)
    assert (extra, 4) in rig.read_sets[1].observed
    rig.closed()


def test_actual_runtime_default_resolution_payload_matches157(default_memory, strict_training):
    rig = strict_training
    assert rig.m is default_memory
    expected = train(rig, baseline('live_individual_training'), include_default_resolution=True)
    rig.reset_trace()
    actual = train(rig, include_default_resolution=True)
    assert expected.pop('observed_at') and actual.pop('observed_at')
    assert actual == expected
    row = actual['players'][0]
    assert row['default_intensity_resolution']['native_code'] == 1
    assert row['club_training_intensity']['applied_intensity'] is None
    assert all((rig.m['base'], 16384) in read.observed for read in rig.read_sets)
    rig.closed()


def test_actual_runtime_default_resolution_still_fences_policy_fields(default_memory, strict_training):
    rig = strict_training
    assert rig.m is default_memory
    rig.hooks[5] = lambda r:r.put(r.m['training_team_node'] + 0x8A, b'\2')
    with pytest.raises(BridgeError, match='changed during read'):
        train(rig, include_default_resolution=True)
    rig.closed()
