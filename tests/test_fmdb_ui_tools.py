"""Offline checks for the UI handler tools: cache keys and invalidation, schema and search
output, record/grade decoding, the board-confidence shape and guarded registration."""
import json
import sys
import types

import pytest

from fm_live_mcp import players
from fm_live_mcp.fmdb import ui_cache, ui_tools


# --------------------------------------------------------------------------- cache
def test_save_key_matches_snapshot_lane_formula():
    assert ui_cache.save_key('Newcastle Career', '2026-07-01', 3) == \
        'newcastle-career-2026-07-01-' + __import__('hashlib').sha256(
            'Newcastle Career\x002026-07-01\x003'.encode()).hexdigest()[:10]


def test_cache_root_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv('FMCP_CACHE_DIR', str(tmp_path))
    assert ui_cache.cache_root() == tmp_path / 'fmdb'
    monkeypatch.delenv('FMCP_CACHE_DIR')
    assert ui_cache.cache_root() == ui_cache.DEFAULT_CACHE / 'fmdb'


def test_entry_name_is_stable_and_input_sensitive():
    a = ui_cache.entry_name('handler:114', {'record': {'Ttea': 1, 'Xxxx': 2}})
    b = ui_cache.entry_name('handler:114', {'record': {'Xxxx': 2, 'Ttea': 1}})
    c = ui_cache.entry_name('handler:114', {'record': {'Ttea': 2}})
    d = ui_cache.entry_name('handler:75', {'record': {'Ttea': 1, 'Xxxx': 2}})
    assert a == b and a != c and a != d
    assert a.startswith('handler-114-') and a.endswith('.json')


def _cache(tmp_path, date='2030-12-10', count=7, build='b1'):
    return ui_cache.UiCache('career-x', date, save_count=count, build=build, root=tmp_path)


def test_cache_roundtrip_records_when_computed(tmp_path):
    cache = _cache(tmp_path)
    assert cache.get('handler:114', {'record': {'Ttea': 1}}) is None
    put = cache.put('handler:114', {'record': {'Ttea': 1}}, {'rows': {'4zmg': {'value': 8}}}, computed_at=1_000.0)
    got = cache.get('handler:114', {'record': {'Ttea': 1}})
    assert got['rows'] == {'4zmg': {'value': 8}}
    assert got['computed_at'] == '1970-01-01T00:16:40+00:00' == put['computed_at']
    assert got['age_seconds'] > 0
    assert cache.path('handler:114', {'record': {'Ttea': 1}}).parent == tmp_path / 'career-x' / 'ui' / '2030-12-10'
    described = ui_cache.describe(got, hit=True)
    assert described['hit'] and described['computed_at'] == got['computed_at'] and 'fresh=true' in described['note']
    assert ui_cache.describe(None, hit=False) == {'hit': False}


@pytest.mark.parametrize('other', [dict(count=8), dict(build='b2')])
def test_cache_rejects_other_save_count_or_build(tmp_path, other):
    _cache(tmp_path).put('k', {'a': 1}, {'x': 1})
    assert _cache(tmp_path, **other).get('k', {'a': 1}) is None


def test_cache_date_change_invalidates_and_prunes(tmp_path):
    _cache(tmp_path).put('k', {'a': 1}, {'x': 1})
    later = _cache(tmp_path, date='2030-12-11')
    assert later.get('k', {'a': 1}) is None
    later.put('k', {'a': 1}, {'x': 2})
    assert not (tmp_path / 'career-x' / 'ui' / '2030-12-10').exists()
    assert later.get('k', {'a': 1})['x'] == 2


def test_cache_other_save_is_separate_and_tampered_entry_ignored(tmp_path):
    _cache(tmp_path).put('k', {'a': 1}, {'x': 1})
    other = ui_cache.UiCache('career-y', '2030-12-10', save_count=7, build='b1', root=tmp_path)
    assert other.get('k', {'a': 1}) is None
    path = _cache(tmp_path).path('k', {'a': 1})
    entry = json.loads(path.read_text())
    entry['inputs'] = {'a': 2}
    path.write_text(json.dumps(entry))
    assert _cache(tmp_path).get('k', {'a': 1}) is None


def test_unstored_entry_is_described(tmp_path):
    entry = _cache(tmp_path).entry('k', {'a': 1}, {'stored': False})
    assert ui_cache.describe(entry, hit=False)['stored'] is False
    assert not _cache(tmp_path).path('k', {'a': 1}).exists()


def test_cache_rejects_bad_identity(tmp_path):
    with pytest.raises(ValueError):
        ui_cache.UiCache('../x', '2030-12-10', root=tmp_path)
    with pytest.raises(ValueError):
        ui_cache.UiCache('x', '10/12/2030', root=tmp_path)


# --------------------------------------------------------------------------- schema
def test_schema_lists_buildable_types():
    out = ui_tools.ui_schema()
    types_ = {row['type']: row for row in out['handler_types']}
    assert len(types_) == 138
    assert types_[114]['client'] == 'TEAM_CONFIDENCE_UI_HANDLER'
    assert types_[114]['input_keys'] == [{'key': 'Tcnf', 'label': None}]
    assert types_[114]['key_count'] >= 70 and 'Ttea' in types_[114]['record_fields']
    assert 'keys' not in types_[114]
    assert set(out['not_buildable']) == {1, 2, 28, 101, 102, 113}


@pytest.mark.parametrize('handler', [114, '114', 'TEAM_CONFIDENCE', 'team_confidence_ui_handler',
                                     'game_plugin::TEAM_CONFIDENCE_UI_HANDLER'])
def test_schema_one_handler(handler):
    out = ui_tools.ui_schema(handler=handler)
    assert out['type'] == 114
    labels = {k['key']: k['label'] for k in out['keys']}
    assert labels['4zmg'] == 'BoardConfidenceOverallGrade' and labels['niy['] == 'BoardSquadConfidenceGrade'


def test_schema_search_by_label():
    out = ui_tools.ui_schema(search='boardconfidenceoverall')
    hits = {m['key']: m for m in out['matches']}
    assert hits['4zmg']['handler_types'] == [114]
    assert hits['tRDU']['label'] == 'BoardConfidenceOverallString'


@pytest.mark.parametrize('handler,text', [(28, 'not buildable'), (999, 'unknown handler type'),
                                          ('NO_SUCH_THING', 'no buildable handler'), (True, 'type number')])
def test_schema_errors(handler, text):
    with pytest.raises(ui_tools.UiToolError, match=text):
        ui_tools.ui_schema(handler=handler)


def test_registry_build_is_checked(monkeypatch):
    monkeypatch.setattr(players, 'SHA256', 'other')
    with pytest.raises(ui_tools.UiToolError, match='another plugin build'):
        ui_tools.ui_schema()


# --------------------------------------------------------------------------- inputs and keys
def test_normalize_record():
    assert ui_tools.normalize_record({'Ttea': 'managed_team', 'Pers': '0x01000010', 'abc': 5, 'Hhum': 'person:12'}) \
        == {'Ttea': 'managed_team', 'Pers': 0x01000010, 'abc ': 5, 'Hhum': 'person:12'}
    assert ui_tools.normalize_record(None) == {}


@pytest.mark.parametrize('inputs', [{'110 ': 3}, {'Ttea': -1}, {'Ttea': 1 << 32}, {'Ttea': True},
                                    {'toolong': 1}, {'Ttea': 'banana'}, {'Ttea': 1.5}, [1]])
def test_normalize_record_rejects(inputs):
    with pytest.raises(ui_tools.UiToolError):
        ui_tools.normalize_record(inputs)


def test_resolve_keys_by_code_and_label():
    reg = ui_tools.registry()
    assert ui_tools.resolve_keys(reg, 'TEAM_CONFIDENCE_UI_HANDLER', ['4zmg', 'BoardMatchGrade', '4zmg']) == ['4zmg', 'YCq7']
    assert len(ui_tools.resolve_keys(reg, 'TEAM_CONFIDENCE_UI_HANDLER', None)) >= 70
    with pytest.raises(ui_tools.UiToolError, match='unknown key'):
        ui_tools.resolve_keys(reg, 'TEAM_CONFIDENCE_UI_HANDLER', ['NotALabelAnywhere'])


# --------------------------------------------------------------------------- grades
@pytest.mark.parametrize('value,letter', [(5, 'C'), (6, 'C+'), (7, 'B-'), (8, 'B'), (9, 'B+'), (11, 'A')])
def test_board_grades_verified(value, letter):
    assert ui_tools.board_grade(value) == {'value': value, 'letter': letter}


def test_board_grades_inferred_and_unknown():
    assert ui_tools.board_grade(10) == {'value': 10, 'letter': 'A-', 'letter_verified': False}
    assert ui_tools.board_grade(0)['letter'] is None and ui_tools.board_grade(0)['note'] == 'no grade yet'
    assert ui_tools.board_grade(2)['letter'] is None
    assert ui_tools.board_grade(None) == {'value': None, 'letter': None}


def test_supporter_grades():
    assert ui_tools.supporter_grade(1)['wording'] == 'very pleased'
    assert ui_tools.supporter_grade(6)['wording'] == 'disappointed'
    assert ui_tools.supporter_grade(2)['wording'] is None and 'note' in ui_tools.supporter_grade(2)


# --------------------------------------------------------------------------- board shape
class _Names:
    names = {16819419: 'Silas Huber', 402653729: 'Newcastle United', 402654600: 'FC Zürich',
             16790225: 'Anthony Gordon'}

    def name(self, ref):
        oid = ref.get('dref') if isinstance(ref, dict) else ref
        return self.names.get(oid)


VALUES = {
    '4zmg': 8, 'tRDU': 'To summarise, the board are very pleased with your overall leadership of the team.',
    '4ssg': 6, 'YCq7': 5, 'mA5F': 8, '0otV': 6, 'niy[': 9, 'WQXS': 'vision', 'vxPz': 'match', 'jU9W': 'recruit',
    'oayd': 'tactics', 'CZQm': 'squad', '4CUZ': [{'haz1': True, 'Strn': 'Pleased to see passing.'}],
    'iajq': ['Delighted.'], 'SZtr': ['Disappointed.'], 'Gc5S': 45, 'nnrF': 1, 'ScoS': 'Overall, very pleased.',
    'bi6D': 1, 'asbd': 0,
    'TjWO': [{'Pcww': 64060, 'K0qE': 5340963, 'twlj': False, 'LDNp': 0, 'QhuE': 0, 'lsUe': 0, 'CqMA': '1900-01-01',
              'plyr': {'110 ': 28, 'dref': 16819419}, 'TObt': {'110 ': 28, 'dref': 402653729},
              'TOst': {'110 ': 28, 'dref': 402654600},
              'pbk5': {'desc': 'The board are very pleased with the deal to sign Silas Huber.', 'r5Fk': 9},
              '0Uxv': {'desc': 'Happy to give him a chance to prove himself.', 'r5Fk': 3}}],
    '71fR': [{'y789': 'Generally satisfied.', 'r5Fk': 4, 'plyr': {'110 ': 28, 'dref': 16790225}, 'Posi': 1792}],
    'FAtR': [{'fdte': {'date': '2030-10-23', 'low': 57}, 'fxrs': '2-2', 'y4WE': 9, 'YCq7': 3, 'GuH4': 4,
              'vxPz': 'Disappointed vs Olympiacos.', 'PUk1': 'Fans satisfied.', 'iajq': [], 'SZtr': ['x'],
              'GUph': ['y'], '3hBS': ['z']}],
    '8l7J': [{'110 ': 50, 'fdte': 266151936, 'fhmT': 402654600, 'fawT': 402653729},
             {'110 ': 50, 'fdte': (2030 << 17) | (360 << 8), 'fhmT': 402653729, 'fawT': 402654600}],
}


def test_shape_board_confidence():
    out = ui_tools.shape_board_confidence(VALUES, _Names(), '2030-12-10')
    assert out['overall'] == {'grade': {'value': 8, 'letter': 'B'}, 'sentence': VALUES['tRDU']}
    letters = {k: v['grade']['letter'] for k, v in out['areas'].items()}
    assert letters == {'club_vision': 'C+', 'match': 'C', 'recruitment': 'B', 'tactics': 'C+', 'squad': 'B+'}
    assert out['areas']['tactics']['feedback'] == [{'text': 'Pleased to see passing.', 'positive': True}]
    (signing,) = out['signings']
    assert signing['name'] == 'Silas Huber' and signing['from_club'] == 'FC Zürich' and signing['wage'] == 64060
    assert signing['fee_raw'] == 5340963 and 'Not verified' in signing['fee_note']
    assert signing['board']['grade']['letter'] == 'B+' and signing['supporters']['grade']['wording'] == 'pleased'
    assert out['supporters']['overall']['grade']['wording'] == 'very pleased'
    assert out['supporters']['players'][0]['name'] == 'Anthony Gordon'
    assert out['job_security']['value'] == 45
    assert out['recent_matches'][0]['date'] == '2030-10-23' and out['recent_matches'][0]['board']['grade']['value'] == 3
    past, upcoming = out['match_fixtures']
    assert past['date'] == '2030-10-23' and not past['upcoming']
    assert upcoming['upcoming'] and upcoming['home'] == 'Newcastle United'
    assert out['next_match_expectation']['available'] is False
    assert out['next_match_expectation']['fixture'] == upcoming


def test_board_rng_marking_is_explicit():
    entry = {'answer': {}, 'game_date': '2030-12-10', 'rng_uses': 8, 'input_status': {'Tcnf': 'ok (data)'},
             'summary': {}, 'unavailable_keys': [], 'timing': {}, 'computed_at': 'x'}
    out = ui_tools._board_answer(entry, hit=True)
    assert out['rng']['draws'] == 8 and out['rng']['fields_depending_on_draws'] == []
    assert 'warning' not in out
    entry['input_status'] = {'Tcnf': 'unavailable: stopped by the instruction or time budget'}
    assert 'did not complete' in ui_tools._board_answer(entry, hit=False)['warning']


# --------------------------------------------------------------------------- registration
class _FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, annotations=None, description=None, **_):
        def decorator(fn):
            self.tools[fn.__name__] = (annotations, description, fn)
            return fn
        return decorator


CORE = {'fm_ui_schema', 'fm_ui_read', 'fm_get_board_confidence'}
# The match lane's tool reads the snapshot's match tables and registers unconditionally.
MATCH = {'fm_get_match'}


def test_registration_without_recipe_modules(monkeypatch):
    monkeypatch.setattr(ui_tools, 'recipe_module', lambda name: None)
    mcp = _FakeMCP()
    assert set(ui_tools.register_fmdb_ui_tools(mcp, bridge=None)) == CORE | MATCH == set(mcp.tools)
    for name, (annotations, description, _) in mcp.tools.items():
        assert annotations.readOnlyHint is True and annotations.destructiveHint is False
        if name != 'fm_ui_schema' and name not in MATCH:    # fm_get_match reads SQL tables, not a UI handler
            assert 'emulating shipped game code' in description and 'tens of seconds' in description
            assert 'random' in description


def test_recipe_module_absent_is_none():
    assert ui_tools.recipe_module('ui_recipes_does_not_exist') is None


def test_registration_with_recipe_modules(monkeypatch):
    news = types.ModuleType('fm_live_mcp.fmdb.ui_recipes_news')
    news.inbox = lambda vm, limit=50, unread_only=False: [{'subject': 'hi', 'limit': limit}]
    news.calendar = lambda vm, team=None, days=60: []
    person = types.ModuleType('fm_live_mcp.fmdb.ui_recipes_person')
    person.player_status = lambda vm, player: {}
    monkeypatch.setitem(sys.modules, 'fm_live_mcp.fmdb.ui_recipes_news', news)
    monkeypatch.setitem(sys.modules, 'fm_live_mcp.fmdb.ui_recipes_person', person)
    monkeypatch.setitem(sys.modules, 'fm_live_mcp.fmdb.ui_recipes_more',
                        types.ModuleType('fm_live_mcp.fmdb.ui_recipes_more'))
    for name in ('ui_recipes_screens', 'ui_frontend'):     # screens lane tools absent here
        monkeypatch.setitem(sys.modules, f'fm_live_mcp.fmdb.{name}', types.ModuleType(f'fm_live_mcp.fmdb.{name}'))
    mcp = _FakeMCP()
    names = set(ui_tools.register_fmdb_ui_tools(mcp, bridge=None))
    assert names == CORE | MATCH | {'fm_get_inbox', 'fm_get_calendar', 'fm_get_player_status'}   # no club_vision


MORE = {'fm_get_scouting', 'fm_get_transfer_activity', 'fm_get_squad_dynamics', 'fm_get_training_schedule',
        'fm_get_medical_centre', 'fm_get_finance_projections', 'fm_get_youth_intake', 'fm_get_manager_profile',
        'fm_get_season_expectations', 'fm_get_league_table'}


def test_registration_of_more_screens(monkeypatch):
    more = types.ModuleType('fm_live_mcp.fmdb.ui_recipes_more')
    for name in ('scouting', 'transfers', 'squad_dynamics', 'training', 'medical', 'finances', 'youth_intake',
                 'manager_profile', 'season_expectations', 'league_table'):
        setattr(more, name, lambda vm, **kw: {})
    monkeypatch.setattr(ui_tools, 'recipe_module',
                        lambda name: more if name == 'ui_recipes_more' else None)
    mcp = _FakeMCP()
    assert set(ui_tools.register_fmdb_ui_tools(mcp, bridge=None)) == CORE | MATCH | MORE == set(mcp.tools)
    for name in MORE:
        annotations, description, _ = mcp.tools[name]
        assert annotations.readOnlyHint is True and annotations.destructiveHint is False
        assert 'emulating shipped game code' in description and 'random' in description
        assert 'First call' in description


class _FakeVM:
    rng_uses = 0


class _FakeSession:
    def __init__(self, tmp_path):
        import threading
        self.lock = threading.RLock()
        self.tmp = tmp_path
        self.vms = 0

    def save_state(self):
        return {'save_key': 'career-x', 'game_date': '2030-12-10', 'save_count': 1, 'record': {'coaches': []}}

    def cache(self, state):
        return ui_cache.UiCache(state['save_key'], state['game_date'], save_count=1, build=players.SHA256,
                                root=self.tmp)

    def vm(self, mode, state, fresh=False, max_instructions=None):
        self.vms += 1
        return _FakeVM()


def test_recipe_wrapper_caches_per_day(monkeypatch, tmp_path):
    session = _FakeSession(tmp_path)
    monkeypatch.setattr(ui_tools, 'session_for', lambda bridge, sid: session)
    calls = []

    def inbox(vm, limit=50, unread_only=False):
        calls.append(limit)
        return [{'subject': '\x01aGVsbG8=\x02Board meeting\x01', 'unread': True}]
    first = ui_tools.recipe_read(None, 's', 'inbox', inbox, {'limit': 5, 'unread_only': False})
    second = ui_tools.recipe_read(None, 's', 'inbox', inbox, {'limit': 5, 'unread_only': False})
    third = ui_tools.recipe_read(None, 's', 'inbox', inbox, {'limit': 5, 'unread_only': False}, fresh=True)
    assert calls == [5, 5] and session.vms == 2
    assert first['result'] == [{'subject': 'Board meeting', 'unread': True}]
    assert not first['cache']['hit'] and second['cache']['hit'] and not third['cache']['hit']
    assert second['cache']['computed_at'] == first['cache']['computed_at']


def test_ui_read_serves_cached_rows(monkeypatch, tmp_path):
    session = _FakeSession(tmp_path)
    monkeypatch.setattr(ui_tools, 'session_for', lambda bridge, sid: session)
    computed = []

    def compute(vm, number, record, keys, *, deadline, reg):
        computed.append(list(keys))
        rows = [ui_tools.row_json(k, reg.label(k), 'int', 8, 0.001) for k in keys]
        return {'handler_type': number, 'client': 'C', 'server': 'S', 'record': record,
                'input_status': {'Tcnf': 'ok'}, 'rows': rows, 'rng_uses': 8, 'files_read': [],
                'timing': {'total_s': 1.0}}
    monkeypatch.setattr(ui_tools, 'compute_handler', compute)
    a = ui_tools.ui_read(None, 's', 114, {'Ttea': 402653729}, keys=['4zmg'])
    b = ui_tools.ui_read(None, 's', 114, {'Ttea': 402653729}, keys=['4zmg'])
    c = ui_tools.ui_read(None, 's', 114, {'Ttea': 402653729}, keys=['YCq7'])
    assert computed == [['4zmg'], ['YCq7', '4zmg']]      # a miss recomputes the cached keys too
    assert not a['cache']['hit'] and b['cache']['hit'] and not c['cache']['hit']
    assert b['rows'][0]['value'] == 8 and b['rng_uses'] == 8 and c['summary'] == {'value': 1, 'unset': 0, 'unavailable': 0}


def test_ui_read_does_not_cache_budget_stops(monkeypatch, tmp_path):
    session = _FakeSession(tmp_path)
    monkeypatch.setattr(ui_tools, 'session_for', lambda bridge, sid: session)

    def compute(vm, number, record, keys, *, deadline, reg):
        return {'handler_type': number, 'client': 'C', 'server': 'S', 'record': record,
                'input_status': {'Tcnf': 'unavailable: stopped by the instruction or time budget'},
                'rows': [ui_tools.row_json('4zmg', 'x', 'int', 0, 0.0)], 'rng_uses': 0, 'files_read': [],
                'timing': {}}
    monkeypatch.setattr(ui_tools, 'compute_handler', compute)
    out = ui_tools.ui_read(None, 's', 114, {'Ttea': 1}, keys=['4zmg'])
    assert out['cache']['stored'] is False and 'did not transfer' in out['warning']
    assert ui_tools.ui_read(None, 's', 114, {'Ttea': 1}, keys=['4zmg'])['cache']['hit'] is False


def test_row_json_status_and_budget_reason():
    from fm_live_mcp.fmdb.vm import Unavailable
    assert ui_tools.row_json('a', 'A', 'null', None, 0)['status'] == 'unset'
    assert ui_tools.row_json('a', 'A', 'string', '\x01eA==\x02Text\x01', 0)['value'] == 'Text'
    row = ui_tools.row_json('a', 'A', None, Unavailable('emulation stopped early (timeout)'), 0)
    assert row['status'] == 'unavailable' and row['reason'] == 'stopped by the instruction or time budget'


def test_object_ref_forms():
    assert ui_tools.object_ref(None, 0x18, 'team') is None
    assert ui_tools.object_ref(402653729, 0x18, 'team') == 402653729
    assert ui_tools.object_ref('team:545', 0x18, 'team') == 0x18000221
    assert ui_tools.object_ref('0x01000010', 1, 'person') == 0x01000010
    assert ui_tools.object_ref('club:7', 3, 'club') == 0x03000007
    with pytest.raises(ui_tools.UiToolError):
        ui_tools.object_ref('team:5', 1, 'person')


def test_club_vision_importance_words_come_from_the_front_end_collection():
    """fm_get_club_vision_progress rows carry `importance` beside `importance_value`: the word of
    the front end's ClubVisionImportanceDataCollection row (IntDataSet, inclusive maximum per row),
    translated by the game (here: the VM's translation cache, which `translate` consults first)."""
    from types import SimpleNamespace
    from fm_live_mcp.fmdb import ui_recipes_screens as S
    collection = S._table()['data_collections'][S.IMPORTANCE_COLLECTION]
    assert collection == {'keys': [0, 3, 6, 8, 10], 'translations': [1738, 1739, 1740, 1741, 1742]}
    vm = SimpleNamespace(_translations={tid: f'word {tid}' for tid in collection['translations']})
    got = {value: S.importance_text(vm, value) for value in range(11)}
    assert got == {0: 'word 1738', 1: 'word 1739', 2: 'word 1739', 3: 'word 1739', 4: 'word 1740',
                   5: 'word 1740', 6: 'word 1740', 7: 'word 1741', 8: 'word 1741', 9: 'word 1742',
                   10: 'word 1742'}
    assert S.importance_text(vm, None) is None and S.importance_text(vm, True) is None
