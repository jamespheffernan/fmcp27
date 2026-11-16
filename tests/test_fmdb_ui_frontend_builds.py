"""The front end per game build (ui_frontend.active_source / table, docs/GAME_UPDATE.md).

Offline: the pinned build reads the shipped table; a mapped build reads the table the update
command extracted for it from the cache; a mapped build without one falls back to the shipped table
with a note and keeps only the screen-parameter globals the address map translates. Also the diff
between two tables, the key list of a new build's UI registry, and the exported-name pairing of the
function match.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fm_live_mcp import address_book as ab  # noqa: E402
from fm_live_mcp.fmdb import ui_frontend as F  # noqa: E402
from fm_live_mcp.fmdb import ui_recipes_screens as S  # noqa: E402

SHA = 'ab' * 32


def _table(**over):
    base = {'build': {'metadata_version': 39, 'version': '27.9.9.1', 'plugin_sha256': SHA},
            'registry': {'cvop': 'VisionObjectiveProgress', 'Pohl': 'HierarchyOverallHappinessLevel'},
            'records': {}, 'views': {}, 'tables': {}, 'ui_record_ids': {'PERSON': 28},
            'plugin_params': {'visionobjectivesetter': '0x600000'},
            'data_collections': {'OverallHappinessDataCollection': {'keys': [-1, 100], 'translations': [7, 8]}}}
    base.update(over)
    return base


@pytest.fixture
def fresh(monkeypatch, tmp_path):
    """A clean table cache and a private cache directory; the build state is the pinned one."""
    monkeypatch.setattr(F, '_CACHED', None)
    monkeypatch.setattr(S, '_TABLE', None)
    monkeypatch.setenv('FMCP_CACHE_DIR', str(tmp_path))
    monkeypatch.setitem(ab.ACTIVE, 'state', 'pinned')
    yield tmp_path
    F.reset()


def _mapped(monkeypatch, version='27.9.9.1'):
    monkeypatch.setitem(ab.ACTIVE, 'state', 'mapped')
    monkeypatch.setitem(ab.ACTIVE, 'sha256', SHA)
    monkeypatch.setitem(ab.ACTIVE, 'version', version)


def test_the_pinned_build_reads_the_shipped_table(fresh):
    source = F.active_source()
    assert source == {'path': str(F.DATA), 'build': ab.PINNED_VERSION, 'per_build': False, 'note': None}
    data = F.table()
    assert data['_source'] == source and F.note() is None
    assert data['data_collections']['ClubVisionProgressDataCollection']['translations'][0] == 1743
    assert len(data['plugin_params']) == 231 and S.front_end_note() is None


def test_a_mapped_build_reads_its_own_table(fresh, monkeypatch):
    _mapped(monkeypatch)
    path = F.build_path(SHA)
    assert path.parent == fresh / 'fmdb' / 'anchors'
    path.parent.mkdir(parents=True)
    path.write_bytes(gzip.compress(json.dumps(_table()).encode()))
    source = F.active_source()
    assert source['per_build'] and source['path'] == str(path) and source['build'] == '27.9.9.1'
    assert source['note'] is None
    data = F.table()
    assert data['plugin_params'] == {'visionobjectivesetter': '0x600000'}        # this build's globals
    assert F.load_table() is data                                                # the default is the running build
    assert S._table() is data and S.front_end_note() is None
    assert S.param_rva('visionobjectivetype') == S.PARAMS['visionobjectivetype']  # source literals still win
    assert F.describe()['source']['per_build'] is True


def test_a_mapped_build_without_a_table_falls_back_with_a_note(fresh, monkeypatch):
    _mapped(monkeypatch)
    pinned = F.load_table(F.DATA)['plugin_params']
    name, rva = sorted(pinned.items())[0]
    monkeypatch.setattr(ab, '_VALUES', {int(rva, 16): 0x7000000})
    source = F.active_source()
    assert not source['per_build'] and source['path'] == str(F.DATA)
    assert '27.9.9.1' in source['note'] and ab.UPDATE_COMMAND in source['note']
    data = F.table()
    # pinned plugin addresses are wrong on another build: only the ones the map translates stay
    assert data['plugin_params'] == {name: '0x7000000'}
    assert len(data['_plugin_params_dropped']) == len(pinned) - 1
    assert S.front_end_note() == source['note']
    assert data['registry']['cvop'] == 'VisionObjectiveProgress'                 # the words still come from it


def test_diff_tables_names_what_changed():
    old = _table()
    new = _table(registry={'cvop': 'VisionObjectiveProgress', 'Pohl': 'Renamed', 'UMMa': 'MatchPlaybackTime'},
                 plugin_params={'visionobjectivesetter': '0x600100', 'newparam': '0x600200'},
                 data_collections={'OverallHappinessDataCollection': {'keys': [-1, 100], 'translations': [7, 9]}},
                 ui_record_ids={'PERSON': 29})
    d = F.diff_tables(old, new)
    assert d['registry']['added'] == {'UMMa': 'MatchPlaybackTime'} and d['registry']['removed_count'] == 0
    assert d['registry']['relabelled'] == {'Pohl': ['HierarchyOverallHappinessLevel', 'Renamed']}
    changed = d['data_collections']['changed']['OverallHappinessDataCollection']
    assert changed['old']['translations'] == [7, 8] and changed['new']['translations'] == [7, 9]
    assert d['data_collections']['translation_ids_added'] == [9]
    assert d['data_collections']['translation_ids_removed'] == [8]
    assert d['plugin_params'] == {'old': 1, 'new': 2, 'added': ['newparam'], 'removed': []}
    assert d['ui_record_ids']['renumbered'] == {'PERSON': [28, 29]}
    assert F.diff_tables(old, old)['data_collections']['changed'] == {}


def test_registry_keys_follow_the_front_end_changes_of_the_new_build():
    sys.path.insert(0, str(ROOT / 'scripts'))
    import fm_update_build as U
    old = {'keys': {'cvop': 'VisionObjectiveProgress', 'gone': 'Removed', 'Pohl': 'OldLabel'}}
    new = {'keys': dict(old['keys'])}
    front = {'path': '/nonexistent', 'diff': {'registry': {
        'added': {'UMMa': 'MatchPlaybackTime'}, 'added_count': 1, 'removed': {'gone': 'Removed'},
        'removed_count': 1, 'relabelled': {'Pohl': ['OldLabel', 'NewLabel']}}}}
    got = U.registry_keys(new, old, front)
    assert new['keys'] == {'cvop': 'VisionObjectiveProgress', 'Pohl': 'NewLabel', 'UMMa': 'MatchPlaybackTime'}
    assert got['added'] == ['UMMa'] and got['removed'] == ['gone'] and got['relabelled'] == ['Pohl']
    kept = {'keys': dict(old['keys'])}
    assert 'pinned list kept' in U.registry_keys(kept, old, {'skipped': 'pinned'})['source']
    assert kept['keys'] == old['keys']


def test_exported_functions_of_the_pinned_plugin():
    import _pinned_build as P
    if not P.PLUGIN.is_file():
        pytest.skip(P.MISSING)
    from fm_live_mcp.fmdb import function_match as fm, platform_model
    exported = fm.exported_functions(platform_model.load_binary(P.PLUGIN))
    assert exported['_i_translator_get_instance'] == 0x1C0BC
    assert exported['_sicore__si__translation__marshalling__i_translator_get_translation_from_id'] == 0x1AF38
    assert len(exported) > 10_000


def test_exported_names_pair_before_fingerprints(monkeypatch):
    """The match takes an exported name over a unique fingerprint (27.0.1: the fingerprint of
    `_i_translator_get_instance` of 27.0.0 belongs to `_i_characters_get_instance`)."""
    from collections import Counter
    from fm_live_mcp.fmdb import function_match as fm

    class Side:
        def __init__(self, fps):
            self.fp = fps

    m = fm.Match.__new__(fm.Match)
    m.fwd, m.bwd, m.how, m.stats = {}, {}, {}, Counter()
    m.r, m.t = object(), object()
    m.R = Side({0x100: 'A', 0x200: 'B'})
    m.T = Side({0x300: 'A', 0x400: 'C'})
    exports = {id(m.r): {'_i_translator_get_instance': 0x100}, id(m.t): {'_i_translator_get_instance': 0x400,
                                                                          '_i_characters_get_instance': 0x300}}
    monkeypatch.setattr(fm, 'exported_functions', lambda b: exports[id(b)])
    monkeypatch.setattr(fm, 'similarity', lambda *a: 0.9)
    assert m.exports() == 1
    m.exact()
    assert m.fwd == {0x100: 0x400}                       # the fingerprint twin 0x300 is not taken
    assert m.how[0x100] == ('export', 0.9, '_i_translator_get_instance')


# --------------------------------------------------------------------------- the English language template
def _ltf(tmp_path, lines):
    from fm_live_mcp.fmdb import build_update as B
    path = tmp_path / 'fm.app' / B.ENGLISH_TEMPLATE_IN_APP
    path.parent.mkdir(parents=True)
    path.write_text(''.join(f'KEY-{k}: {v}\n' for k, v in lines), encoding='utf-8')
    return tmp_path / 'fm.app'


def test_english_template_is_rebound_only_when_every_compiled_text_matches(tmp_path, monkeypatch):
    from fm_live_mcp.fmdb import build_update as B
    monkeypatch.setattr(B, '_compiled_english', lambda: [(10, 'Unhappy about club finances[%person#unhappy-hidden]'),
                                                          (11, 'Fair increase in playing time')])
    app = _ltf(tmp_path, [(10, 'Unhappy about club finances[%person#unhappy-hidden] [COMMENT: a note]'),
                          (11, 'Fair increase in playing time'), (12, 'other')])
    got = B.english_template(app)
    assert got['verified'] and got['checked'] == 2 and got['differ'] == []
    assert (got['pinned_sha256'], got['pinned_bytes']) == B.PINNED_ENGLISH
    assert got['bytes'] == (app / B.ENGLISH_TEMPLATE_IN_APP).stat().st_size and len(got['sha256']) == 64
    assert set(got['files']) == set(B.ENGLISH_BOUND_FILES)
    other = tmp_path / 'other'
    other.mkdir()
    changed = B.english_template(_ltf(other, [(10, 'Unhappy about club money'), (11, 'Fair increase in playing time')]))
    assert not changed['verified'] and [d['id'] for d in changed['differ']] == [10]
    assert B.english_template(tmp_path / 'nowhere') == {'skipped': f'no language template at '
                                                                    f'{tmp_path / "nowhere" / B.ENGLISH_TEMPLATE_IN_APP}'}


def test_the_compiled_english_texts_are_the_pinned_modules():
    from fm_live_mcp.fmdb import build_update as B
    from fm_live_mcp import _concern_template_definitions as concern, promise_kind_definitions as kinds
    from fm_live_mcp import live_player_concern_history as query
    pairs = B._compiled_english()
    assert len(pairs) == len(concern.FIRST_KEYS) + 1 + len(kinds.DEFINITIONS)
    assert (concern.ENGLISH_RESOURCE_SHA256, query.ENGLISH_RESOURCE_BYTES) == B.PINNED_ENGLISH
    assert kinds.ENGLISH_SHA256 == B.PINNED_ENGLISH[0]


def test_the_address_book_rebinds_the_english_identity_in_the_listed_files(monkeypatch):
    import ast
    english = {'verified': True, 'pinned_sha256': 'a' * 64, 'sha256': 'b' * 64, 'pinned_bytes': 155367178,
               'bytes': 155509398, 'files': ['live_player_concern_history.py']}
    monkeypatch.setattr(ab, 'MAP', {'english_template': english})
    source = f"SHA = {'a' * 64!r}\nSIZE = 155367178\nOTHER = 155367179\n"

    def run(rel):
        tree = ast.parse(source)
        counts = ab.rewrite(tree, rel)
        ns = {}
        exec(compile(tree, rel, 'exec'), ns)
        return ns, counts
    ns, counts = run('live_player_concern_history.py')
    assert (ns['SHA'], ns['SIZE'], ns['OTHER']) == ('b' * 64, 155509398, 155367179) and counts['identity'] == 2
    ns, _ = run('playing_time.py')                       # not verified for this file: the pinned identity stays
    assert (ns['SHA'], ns['SIZE']) == ('a' * 64, 155367178)
    monkeypatch.setattr(ab, 'MAP', {'english_template': {**english, 'verified': False}})
    ns, _ = run('live_player_concern_history.py')
    assert (ns['SHA'], ns['SIZE']) == ('a' * 64, 155367178)
