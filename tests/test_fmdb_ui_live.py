"""Live-gated UiHandlerVM checks (skipped unless one supported FM27 process and the helper run).

Slow: each TEAM_CONFIDENCE build runs ~130 M emulated instructions (~30-50 s).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _live_available():
    if sys.platform != 'darwin':
        return False
    try:
        from fm_live_mcp.bridge import Bridge, discover_processes
        return Bridge().helper.is_file() and len(discover_processes()) == 1
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')

STABLE_KEYS = ('4zmg', 'tRDU', 'YCq7', 'vxPz', 'niy[', '0otV', 'mA5F', '4ssg', 'WQXS', 'nnrF',
               'SZtr', 'iajq', 'TjWO', 'bi6D')


@pytest.fixture(scope='module')
def live():
    sys.path.insert(0, str(ROOT / 'scripts'))
    from fmdb_ui_read import open_vm, managed_team
    session, memory, vm = open_vm()
    yield session, vm, managed_team(session)
    memory.close()
    session.close()


def _values(reading):
    return {r.code: r.value for r in reading.readings}


def test_team_confidence_stable_and_plausible(live):
    from fm_live_mcp.fmdb import ui_handlers
    from fm_live_mcp.fmdb.vm import Unavailable
    session, vm, team = live
    first = _values(ui_handlers.team_confidence(vm, team, keys=STABLE_KEYS))
    second = _values(ui_handlers.team_confidence(vm, team, keys=STABLE_KEYS))
    assert first == second
    assert not any(isinstance(v, Unavailable) for v in first.values()), first
    for code in ('4zmg', 'YCq7', 'niy[', '0otV', 'mA5F', '4ssg'):
        assert 0 <= first[code] <= 12          # letter-grade scale (5 = C ... 11 = A)
    assert first['tRDU'].startswith('To summarise, the board')
    team_id = vm.object_ref(team)
    for signing in first['TjWO']:             # every transfer is the managed team's ('TObt')
        assert signing['TObt']['dref'] == team_id
    assert first['bi6D'] == len(first['TjWO'])


def test_generic_reader_two_handler_types(live):
    from fm_live_mcp.fmdb import ui_handlers, ui_registry
    session, vm, team = live
    registry = ui_registry.default()
    tc = ui_handlers.read_handler(vm, 114, {'Ttea': vm.object_ref(team)}, keys=('4zmg', 'Gc5S'))
    assert tc.client_class == 'TEAM_CONFIDENCE_UI_HANDLER'
    assert all(r.ok for r in tc.readings)
    assert registry.types[128]['client'] == 'TEAM_TRAINING_UI_HANDLER'
    training = ui_handlers.read_handler(vm, 128, {'Ttea': vm.object_ref(team)})
    assert training.client_class == 'TEAM_TRAINING_UI_HANDLER'
    values = training.by_label()
    assert values['TrainingIntensities'][2]['qvJ6'] == 'Normal Intensity'
    assert training.summary()['value'] > 10
