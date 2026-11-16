"""Offline checks of ui_recipes_more shaping and the sweep's binding/blocker logic."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

from fm_live_mcp.fmdb import ui_recipes_more as M  # noqa: E402
from fm_live_mcp.fmdb.vm import Unavailable  # noqa: E402


class FakeRefs(M.Refs):
    def __init__(self, names):
        self.names = lambda target: names.get(target)


def test_refs_resolve_nested_references_and_drop_null_ids():
    refs = FakeRefs({0x18000221: {'type': 'TEAM', 'name': 'Newcastle United'}})
    value = {'Team': {'110 ': 28, 'dref': 0x18000221}, 'none': {'110 ': 28, 'dref': 0xFF7FFFFF},
             'list': [{'110 ': 28, 'dref': 0x18000221}], 'record': {'110 ': 50, 'fhmT': 1}}
    out = refs(value)
    assert out['Team'] == {'id': 0x18000221, 'type': 'TEAM', 'name': 'Newcastle United'}
    assert out['none'] is None
    assert out['list'][0]['name'] == 'Newcastle United'
    assert out['record'] == {'110 ': 50, 'fhmT': 1}          # other UI records stay records


def test_fixture_without_result_blanks_the_minus_one_scores():
    shaped = M._fixture_shape({'has_result': False, 'home_score': '-1', 'away_score': '-1',
                               'result': '-1 - -1', 'kickoff': '20:00'})
    assert shaped['home_score'] is None and shaped['result'] is None and shaped['kickoff'] == '20:00'
    played = M._fixture_shape({'has_result': True, 'home_score': '0', 'result': '0 - 0'})
    assert played['result'] == '0 - 0'


def test_league_table_rows():
    refs = FakeRefs({402653644: {'type': 'TEAM', 'name': 'Arsenal'}})
    rows = M._table([{'Team': {'110 ': 28, 'dref': 402653644}, 'ztvp': 1, 'gpld': 16, 'gwon': 12, 'gdrw': 2,
                      'glos': 2, 'glfr': 29, 'GAgn': 10, 'lgdf': 19, 'glor': 38, 'Pqxg': 1}], refs)
    assert rows == [{'position': 1, 'played': 16, 'won': 12, 'drawn': 2, 'lost': 2, 'goals_for': 29,
                     'goals_against': 10, 'goal_difference': 19, 'points': 38, 'colour_group': 1,
                     'team': {'id': 402653644, 'type': 'TEAM', 'name': 'Arsenal'}}]


def test_key_reading_status():
    assert M.KeyReading('x', None, 'null', None, 0).status == 'unset'
    assert M.KeyReading('x', None, 'int', 0, 0).status == 'value'
    assert M.KeyReading('x', None, None, Unavailable('no'), 0).status == 'unavailable'
    assert M.counts([M.KeyReading('a', None, 'int', 1, 0), M.KeyReading('b', None, None, [], 0)]) == \
        {'value': 1, 'unset': 1, 'unavailable': 0}


def test_fixture_record_is_the_games_own_form():
    rec = M.fixture_record(1, 2, 3, 4)
    assert rec == {'fhmT': 1, 'fawT': 2, 'fdte': 3, 'ctxt': 4, 'VMty': 0xFFFFFFFF, 'frhi': 0xFFFFFFFF,
                   'frht': 0xFFFFFFFF}


def test_viewer_record_carries_every_context_field():
    view = M.Viewer(0, 109669, 0x01000000 | 109669, 0, 0x18000221, 0x0300019E, '2030-12-10')
    rec = view.record(comp=7)
    assert rec['Hhum'] == rec['PbPY'] == 0x01000000 | 109669 and rec['huma'] == 109669
    assert rec['Ttea'] == rec['Team'] == rec['iyrZ'] == 0x18000221 and rec['club'] == 0x0300019E
    assert rec['comp'] == 7


BINDINGS = {'game_date': '2030-12-10', 'human_person_index': 5, 'human': 0x01000005, 'team': 0x18000001,
            'club': 0x03000001, 'player': 0x01000010, 'scouted_player': None, 'scout': 0x01000020,
            'league': 0x19000007, 'ucl': None, 'next_fixture': None,
            'last_fixture': {'home': 0x18000001, 'away': 0x18000002, 'si_date': 99, 'ref': 0x35000001,
                             'competition': 0x19000007},
            'news_unid': 12, 'recruitment_focus': 18, 'today_si': 100}


def test_sweep_profiles_and_relevance():
    import fmdb_ui_sweep as S
    profiles = S.profiles(BINDINGS)
    assert 'scouted_player' not in profiles and profiles['staff']['Pers'] == 0x01000020
    assert profiles['last_fixture']['Topp'] == 0x18000002
    assert profiles['recruitment_focus'] == {'rfid': 18}
    ctx = S.context(BINDINGS)
    assert ctx['iyrZ'] == ctx['Ttea'] == 0x18000001 and ctx['nMzT'] == 100
    assert S.relevant_profiles({'Pers', 'comp'}, profiles) == ['squad_player', 'staff', 'league']
    assert S.relevant_profiles({'xxxx'}, profiles) == ['none']
    assert S.relevant_profiles({'rfid'}, profiles) == ['recruitment_focus']


def test_sweep_first_blocker():
    import fmdb_ui_sweep as S
    assert S.first_blocker({'build_error': 'factory made no client handler'}).startswith('build:')
    nothing = {'counts': {'unset': 2}, 'keys': {'a': {'status': 'unset'}, 'b': {'status': 'unset'}}}
    assert S.first_blocker(nothing) == 'every key unset (no binding produced data)'
    failing = {'counts': {'unavailable': 2}, 'inputs': {'x': 'unavailable: null or low pointer dereference 0x0 after 5 insns [..]'},
               'keys': {'a': {'status': 'unavailable', 'reason': 'server key CNGr: external call _foo'},
                        'b': {'status': 'unavailable', 'reason': 'server key CNGr: external call _foo'}}}
    assert S.first_blocker(failing) == 'external call _foo'
    params = {'counts': {'value': 1, 'unset': 1}, 'keys': {'a': {'status': 'value'},
                                                           'b': {'status': 'unset', 'params': ['0x56d1248']}}}
    assert S.first_blocker(params) == 'needs screen parameter 0x56d1248'
