"""Live-gated checks of the round-2 screens and screen parameters (skipped unless FM27 runs).

Values move while the owner plays, so the checks are structural: each screen reads most of its
keys, the comparison names two different people, a parameter changes what a getter returns."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fmdb_ui_live import _live_available  # noqa: E402

pytestmark = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')


@pytest.fixture(scope='module')
def vm():
    sys.path.insert(0, str(ROOT / 'scripts'))
    from fmdb_ui_read import open_vm
    session, memory, vm = open_vm()
    yield vm
    memory.close()
    session.close()


@pytest.mark.parametrize('name', ['player_comparison', 'staff_comparison', 'tactics', 'squad_registration',
                                  'training', 'contract_negotiation', 'transfer_negotiation', 'competition_rules'])
def test_screen_reads_most_keys(vm, name):
    from fm_live_mcp.fmdb import ui_recipes_round2 as R
    out = R.screen(vm, name)
    cov = out['coverage']
    # The tactics screen's suggested-team and suggested-changes lists sort with libc qsort when the
    # assistant has suggestions (after a match); the emulator does not model that call yet, so those
    # keys are unavailable with that reason. Any other unavailable key is a failure.
    reasons = [str(r) for s in out['sources'].values() for r in (s.get('unavailable') or {}).values()]
    assert all('external call _qsort' in r for r in reasons), out['sources']
    assert cov['unavailable'] == len(reasons), out['sources']
    assert cov['value'] >= 2 * cov['unset'], cov
    if name == 'player_comparison':
        person, other = out['subject']['person'], out['subject']['other']
        assert person['id'] != other['id'] and person['name'] and other['name']
        assert set(out['fields']['person']) == set(out['fields']['other'])


def test_parameter_changes_the_answer(vm):
    """TEAM_TRAINING 'TrainingBestRatings' reads screen parameter `number`: empty without it,
    that many rows with it."""
    from fm_live_mcp.fmdb import ui_params
    from fm_live_mcp.fmdb.ui_recipes_more import install_param_trace, open_handler, viewer
    install_param_trace(vm)
    view = viewer(vm)
    reader = open_handler(vm, 128, view.record())
    plain = reader.get('eXrB')
    three = reader.get('eXrB', params={ui_params.rva_of('number'): 3})
    assert plain.status == 'unset'
    assert three.status == 'value' and len(three.json_value()) == 3
    assert ui_params.name_of(three.params_read[0]) == 'number'
