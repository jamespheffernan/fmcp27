"""Live-gated checks of ui_recipes_screens (skipped unless FM27 runs).

Ground truth (owner's Club Vision / Board / Supporters screens, Newcastle, 10 Dec 2030) runs
only with FMDB_REFERENCE_SAVE=1 because the save moves on.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fmdb_ui_live import _live_available  # noqa: E402

pytestmark = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')
REFERENCE = os.environ.get('FMDB_REFERENCE_SAVE') == '1'

GROUND_TRUTH = {
    'board': {
        'Work within wage budget': 'On Course',
        'Sign players to sell for a profit': 'Pleased',
        'Maximum one-year contracts for players over the age of 33': 'Not Judging',
        'Maximum two-year contracts for players over the age of 31': 'Not Judging',
        'Maximum three-year contracts for players over the age of 29': 'Not Judging',
        'Minimum 4-year contracts for first-team players': 'Not Judging',
        'Make the most of set pieces': 'Pleased',
        'Play attacking football': 'Pleased',
        'Play entertaining football': 'Pleased',
        'Play high-tempo pressing football': 'Pleased',
        'Reach the latter stages of the UEFA Champions League': 'Pleased',
        'Qualify for the UEFA Champions League': 'Pleased',
        'Challenge for the FA Cup': 'Reserving Judgement',
        'Be competitive in the EFL Cup': 'Pleased',
        'Be competitive in the Community Shield': 'Passed',
    },
    'supporters': {
        'Finish above Sunderland in the league': 'Pleased',
        'Qualify for the UEFA Europa League': 'Pleased',
        'Play attacking football': 'Delighted',
        'Play high-tempo pressing football': 'Pleased',
        'Play entertaining football': 'Very Pleased',
        'Play possession football': 'Pleased',
        'Make the most of set pieces': 'Pleased',
    },
}


@pytest.fixture(scope='module')
def live():
    sys.path.insert(0, str(ROOT / 'scripts'))
    from fmdb_ui_read import open_vm
    session, memory, vm = open_vm()
    yield session, vm
    memory.close()
    session.close()


@pytest.fixture(scope='module')
def vision(live):
    from fm_live_mcp.fmdb import ui_recipes_screens as S
    session, vm = live
    return S.club_vision_progress(vm, read=session.reader.read)


def test_translator_gives_progress_words(live):
    from fm_live_mcp.fmdb import ui_recipes_screens as S
    _, vm = live
    assert S.progress_text(vm, 6) == 'Not Judging'
    assert S.progress_text(vm, 11) == 'Pleased'
    assert S.progress_text(vm, 9) == 'Delighted'


def test_views_parameter_reaches_the_getter(vision, live):
    from fm_live_mcp.fmdb import ui_recipes_screens as S
    assert vision['context'] == [('CVpe', True)]
    rows = vision['objectives']['board']['all']
    assert isinstance(rows, list) and rows
    # the evaluated list carries the board's sentence (the screen's info tooltip) and a
    # judgement word for every row; the raw database list has 6 everywhere and no sentence
    assert any(r['performance'] for r in rows)
    assert all(r['progress'] for r in rows)
    # the importance word beside the raw value, from the game's own strings
    words = {w for _, w in S.collection_words(live[1], S.IMPORTANCE_COLLECTION)}
    assert all(r['importance'] in words for r in rows if isinstance(r['importance_value'], int))


def test_context_record_is_restored(live):
    import struct
    from fm_live_mcp.fmdb import ui_recipes_screens as S
    _, vm = live
    vm._restore()
    header = bytes(vm.read(vm.base + S.GLOBAL_CONTEXT_RVA, 24))
    S.club_vision_progress(vm, club=None, read=live[0].reader.read)
    vm._restore()
    assert bytes(vm.read(vm.base + S.GLOBAL_CONTEXT_RVA, 24)) == header


@pytest.mark.skipif(not REFERENCE, reason='reference-save ground truth (FMDB_REFERENCE_SAVE=1)')
def test_judgements_match_the_screens(vision):
    for owner, expected in GROUND_TRUTH.items():
        got = {r['objective']: r['progress'] for r in vision['objectives'][owner]['all']}
        for objective, word in expected.items():
            assert got.get(objective) == word, (owner, objective, got.get(objective))


def test_squad_happiness_one_call(live):
    from fm_live_mcp.fmdb import ui_recipes_screens as S
    session, vm = live
    out = S.squad_happiness(vm, read=session.reader.read, reasons='none')
    assert len(out['players']) >= 20
    words = {w for _, w in out['words']['overall']}
    assert {'Delighted', 'Content', 'Devastated'} <= words
    assert all(r['overall'] in words for r in out['players'] if isinstance(r['overall_level'], int))
    if REFERENCE:
        by = {r['name']: r for r in out['players']}
        assert by['L. Miley']['playing_time'] == 'Alienated'
        assert by['J. Robinson']['playing_time'] == 'Alienated'
