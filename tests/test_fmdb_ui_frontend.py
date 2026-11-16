"""Offline checks of the front-end table (data/ui_frontend.json.gz) and its readers.

The data-file checks need nothing installed. The metadata checks read the pinned build's
GameAssembly/global-metadata.dat (ui_frontend.GA_PATH / META_PATH, fm_live_mcp/build_paths.py) and are
skipped when they are not available.
"""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fm_live_mcp.fmdb import ui_frontend as F  # noqa: E402
from fm_live_mcp.fmdb import ui_recipes_screens as S  # noqa: E402

INSTALLED = F.META_PATH.exists() and F.GA_PATH.exists()


@pytest.fixture(scope='module')
def table():
    return F.load_table()


def test_registry_has_the_record_properties_the_old_extractor_missed(table):
    reg = table['registry']
    assert reg['cvop'] == 'VisionObjectiveProgress'
    assert reg['cvos'] == 'VisionObjectiveStatus'
    assert reg['aZDo'] == 'VisionObjectivePerformance'
    # 'add w0, w8, #1, lsl #12' registrations (the older extractor ignored the shift)
    assert reg['Ymg9'] == 'SelectedCreatedClub'
    assert reg['YmW:'] == 'CanChangeSquadNumber'
    assert reg['0kaf'] == 'LoanDurationValue'
    assert len(reg) >= 9000


def test_record_schema_of_club_vision_objective(table):
    rec = table['records']['cvor']
    assert rec['class'] == 'FM.UI.ClubVisionObjectiveReference'
    assert {'cvon', 'cvop', 'aZDo', 'coip', 'cvos', 'VOdt', 'Viys', 'comp'} <= set(rec['properties'])
    assert rec['refers'].get('comp') == '0x44420019'      # 'DB' + competition table 0x19


def test_ui_record_ids_are_the_handler_types(table):
    ids = table['ui_record_ids']
    assert ids['TeamConfidence'] == 114 and ids['Contract'] == 19 and ids['PersonSearch'] == 73
    assert ids['DatabaseRecord'] == 28 and ids['VersusModeFormat'] == 144


def test_plugin_parameter_globals_match_recipes(table):
    params = {k: int(v, 16) for k, v in table['plugin_params'].items()}
    for name, rva in S.PARAMS.items():
        assert params[name] == rva
    assert len(params) >= 200


def test_views_carry_their_parameters(table):
    board = table['views']['ClubBoardBlock']
    assert board['params']['visionisusingperformancedata'] == ['Bool:1']
    assert board['params']['visionobjectivesetter'] == ['Int:1']
    assert 'club:club' in board['expects']
    assert 'ClubVisionObjectiveProgressWidget' in F.views_binding('VisionObjectiveProgress', table)
    factory = table['tables']['ClubVisionObjectiveTableFactory']
    assert 'VisionObjectiveProgress' in factory['bindings']


def test_progress_collection_matches_fallback(table):
    coll = table['data_collections']['ClubVisionProgressDataCollection']
    assert coll['keys'] == list(range(17))
    assert tuple(coll['translations']) == S.PROGRESS_TRANSLATIONS


def test_describe_lookup():
    out = F.describe(search='VisionObjectiveProgress', record='cvor', parameter='visionobjectivetype', limit=5)
    assert out['properties'] == [{'key': 'cvop', 'label': 'VisionObjectiveProgress'}]
    assert out['record']['labels']['cvop'] == 'VisionObjectiveProgress'
    assert out['parameter']['plugin_global'] == '0x56d1a18'
    assert out['parameter']['views']


@pytest.mark.skipif(not INSTALLED, reason='game not installed')
def test_metadata_reader_on_installed_front_end():
    fe = F.FrontEnd()
    meta = fe.meta
    names = {t.full_name for t in meta.types}
    assert 'FM.GamePlugin.UiRecordID' in names
    assert 'FM.UI.ClubVisionObjectiveReference' in names
    t = next(t for t in meta.types if t.full_name == 'FM.UI.ClubVisionObjectiveReference')
    m = next(m for m in meta.type_methods(t) if m.name == 'get_ID')
    assert m.address and fe.ga.u32(m.address) >> 24 == 0x52      # mov w0, #imm (movz)
    lits = {meta.literal(i) for i in range(meta.literal_count) if meta.literal(i).startswith('VisionObjectivePro')}
    assert 'VisionObjectiveProgress' in lits


def test_clean_text_drops_variable_tokens():
    assert S.clean_text('Alienatedperson#1') == 'Alienated'
    assert S.clean_text('Managerial Supportperson#1') == 'Managerial Support'
    assert S.clean_text('Pleased') == 'Pleased'


def test_happiness_collections_have_bands(table):
    dc = table['data_collections']
    assert dc['OverallHappinessDataCollection']['keys'] == [-81, -61, -41, -21, 19, 39, 59, 79, 100]
    assert dc['PlayingTimeHappinessDataCollection']['keys'] == [-101, -40, -30, -20, 20, 49, 74, 100]
    assert len(dc['PlayingTimeHappinessDataCollection']['translations']) == 8
