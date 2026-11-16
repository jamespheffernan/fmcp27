"""Offline checks of the completeness ledger, the label sources and `fm_coverage` (no game needed).

Tests that read the pinned build's files skip when it is not available (tests/_pinned_build.py).
"""
from __future__ import annotations

import pytest

from fm_live_mcp.fmdb import labels, ledger

from fm_live_mcp import build_paths  # noqa: E402

PLUGIN = build_paths.pinned_path(build_paths.PLUGIN_IN_APP)
needs_game = pytest.mark.skipif(not PLUGIN.exists(), reason=build_paths.PINNED_MISSING)


def test_domain_rules():
    assert ledger.domain_of('TRANSFER_MANAGER') == 'transfers and contracts'
    assert ledger.domain_of('SCOUT_MANAGER') == 'scouting and knowledge'
    assert ledger.domain_of('Current Ability', record_type='play') == 'people and world database'
    assert ledger.domain_of(None, record_type='CntF') == 'transfers and contracts'
    assert ledger.class_domain('CryptoPP::SHA256') == ledger.ENGINE
    assert ledger.class_domain('icu_65::UnicodeString') == ledger.ENGINE
    assert set(ledger.DOMAIN_VALUE) == set(ledger.DOMAIN_NAMES)


def test_mini_demangle():
    assert ledger._mini_demangle('N2db9NEWS_ITEME') == 'db::NEWS_ITEM'
    assert ledger._mini_demangle('16TRANSFER_MANAGER') == 'TRANSFER_MANAGER'


def test_class_kind():
    assert ledger.class_kind('TRANSFER_MANAGER', ['BASE_TRANSFER_MANAGER']) == 'manager'
    assert ledger.class_kind('db::DATABASE_TABLE<db::PERSON>', ['db::DATABASE_TABLE_BASE']) == 'table'
    assert ledger.class_kind('X_NEWS', ['db::NEWS_ITEM']) == 'news_item'
    assert ledger.class_kind('PLAYER_FILTER', ['sicore::PERSISTENT']) == 'behaviour'
    assert ledger.class_kind('SQUAD_PLAN', ['sicore::PERSISTENT']) == 'persisted'


def test_words_and_markup():
    assert labels.words('WageAfterTax') == 'Wage after tax'
    assert labels.clean_text('All Time League Goals[COMMENT: player goals]') == 'All Time League Goals'
    assert labels.clean_text('General[%person#1-hidden]') == 'General'


def test_build_ui_statuses():
    class HC:
        def __init__(self, keys):
            self._k = keys

        def keys(self, slot=4):
            return self._k

    class Reg:
        labels = {'AAAA': 'ValueKey', 'BBBB': 'UnsetKey', 'CCCC': 'ParamKey', 'DDDD': 'FailKey', 'EEEE': 'Orphan',
                  'FFFF': 'NotBuilt'}
        classes = {'ONE_UI_HANDLER': HC(('AAAA', 'BBBB', 'CCCC', 'DDDD')), 'TWO_UI_HANDLER': HC(('FFFF',))}

    sweep = [{'job': '7', 'class': 'ONE_UI_HANDLER', 'counts': {'value': 1, 'unset': 2, 'unavailable': 1},
              'keys': {'AAAA': {'status': 'value'}, 'BBBB': {'status': 'unset'},
                       'CCCC': {'status': 'unset', 'params': ['0x56d16e8']},
                       'DDDD': {'status': 'unavailable', 'reason': 'external call _asinf'}}}]
    rows, by_class = ledger.build_ui(Reg(), sweep)
    status = {r[1]: r[7] for r in rows}
    assert status == {'AAAA': 'reads', 'BBBB': 'unset_on_samples', 'CCCC': 'needs_parameter',
                      'DDDD': 'unavailable', 'EEEE': 'unreached', 'FFFF': 'unreached'}
    assert by_class['ONE_UI_HANDLER']['counts']['value'] == 1


def _tiny_ledger(statuses):
    rows = [ledger._row('editor', f'play.K{i}', 'transfers and contracts', f'K{i}', route='emulated', status=s)
            for i, s in enumerate(statuses)]
    ledger.annotate_costs(rows, {'columns': {}, 'direct_us_per_cell': 1.0}, None)
    out = {'meta': {}, 'columns': list(ledger.COLUMNS), 'rows': rows}
    out['headline'] = ledger.headline(out)
    out['gaps'] = ledger.gaps(out)
    return out


def test_headline_compare_and_gaps():
    before = _tiny_ledger(['reads', 'unreached', 'unavailable'])
    after = _tiny_ledger(['reads', 'reads', 'unavailable'])
    assert before['headline']['editor']['reads'] == 1 and before['headline']['editor']['total'] == 3
    cmp = ledger.compare(before, after)
    assert {k: cmp['editor'][k] for k in ('before', 'after', 'gained')} == {'before': '1/3', 'after': '2/3', 'gained': 1}
    assert cmp['editor']['availability_after']['on_demand'] == 2
    assert cmp['newly_read'] == 1 and cmp['newly_read_examples'] == [('editor', 'play.K1')]
    assert [g['status'] for g in before['gaps']] == ['unreached', 'unavailable']
    q = ledger.query(after, search='K2')
    assert q['matches']['total'] == 1 and q['items'][0]['status'] == 'unavailable'
    md = ledger.render_markdown(after, before)
    assert '## Before and after' in md and '| editor | 1/3 | 2/3 | +1 |' in md


def test_packaged_ledger_and_tool():
    data = ledger.load(ledger.CURRENT) or ledger.load(ledger.BEFORE)
    if data is None:
        pytest.skip('no packaged ledger')
    total = sum(p.stat().st_size for p in ledger.DATA_DIR.glob('ledger*.json.gz'))
    assert total < 2_000_000
    assert set(ledger.DENOMINATORS) <= set(data['headline'])
    assert data['headline']['ui']['total'] == 7720
    assert data['headline']['native']['total'] > 6000
    assert len(data['gaps']) == 60
    from fm_live_mcp.fmdb import ledger_tools
    head = ledger_tools.coverage()
    assert head['headline']['editor']['total'] == data['headline']['editor']['total'] and head['top_gaps']
    hit = ledger_tools.coverage(search='TRANSFER_MANAGER', denominator='native')
    row = next(i for i in hit['items'] if i['key'] == 'TRANSFER_MANAGER')
    assert row['status'] in ledger.STATUSES and row['availability'] in ledger.AVAILABILITY


@needs_game
def test_rtti_inventory_matches_known_classes():
    from fm_live_mcp.fmdb.image import PluginImage
    rtti = ledger.rtti_inventory(PluginImage.load(PLUGIN))
    assert len(rtti) > 6500 and sum(1 for v in rtti.values() if v['vt']) > 5500
    assert 'BASE_TRANSFER_MANAGER' in rtti['TRANSFER_MANAGER']['parents']
    assert sum(1 for n in rtti if 'db::NEWS_ITEM' in ledger.ancestors(rtti, n)) == 698
    assert sum(1 for n in rtti if 'sicore::PERSISTENT' in ledger.ancestors(rtti, n)) == 524
    # The table vtables agree with the hand-built reader's pinned constants.
    from fm_live_mcp import database
    for kind, (_, vtable, mangled) in database.TABLES.items():
        name = ledger._demangle([mangled.decode()])[0]
        assert rtti[name]['vt'] == vtable, kind


@needs_game
def test_label_sources_from_game_files():
    filters = labels.person_filters()
    assert len(filters) > 400
    assert filters['PAap']['name'] == 'All Time Career Appearances'
    census = labels.census()
    assert census['extra_keys'] == 1896
    assert census['from_game_source'] + census['inferred'] == census['extra_keys']
    assert census['by_source'].get('filters', 0) > 200
    assert labels.label_for('play', 'PCAB') == ('Current Ability', 'editor')
    if not labels.ltf_path().is_file():    # the editor/language comparison reads the English template
        pytest.skip("needs the pinned build's English language template (example.ltf), which was not preserved")
    assert labels.editor_language_check()['same'] > 2900


def _ui_rows():
    rows = [ledger._row('ui', 'uvRT', 'people and world database', 'TEAM_UI_HANDLER', 'TeamAnalytics', 'ui_registry', 'ui',
                        'needs_parameter', 'reads screen parameter 0x56d1168', ['fm_ui_read(28:TEAM_UI_HANDLER)']),
            ledger._row('ui', 'UZlS', 'tactics and matches', '', 'PitchZonesList', 'ui_registry', 'ui'),
            ledger._row('ui', 'GfON', 'people and world database', 'TEAM_UI_HANDLER', 'DataHubLastMatchFixtureDropdown',
                        'ui_registry', 'ui', 'reads', '', ['fm_ui_read(28:TEAM_UI_HANDLER)']),
            ledger._row('ui', 'ZZZZ', 'tactics and matches', '', 'PossessionShare', 'ui_registry', 'ui', 'reads'),
            ledger._row('tools', 'tool:fm_get_retained_possession_events', 'tactics and matches',
                        'fm_get_retained_possession_events', 'Read named possession-won and possession-lost events',
                        'tool description', 'hand_built', 'reads', '', ['fm_get_retained_possession_events']),
            ledger._row('tools', 'staff.attributes.possession', 'youth, staff and career', 'possession', None, None,
                        'hand_built', 'reads', '', ['fm_get_staff'])]
    return {'rows': rows}


def test_search_matches_every_word_through_synonyms_and_topics():
    data = _ui_rows()
    keys = lambda q: [i['key'] for i in ledger.query(data, search=q)['items']]  # noqa: E731
    # the game's screen says "gained", the match record and the tool say "won"
    assert keys('possession gained') == ['tool:fm_get_retained_possession_events', 'uvRT', 'UZlS']
    assert 'staff.attributes.possession' in keys('possession') and 'staff.attributes.possession' not in keys('possession gained')
    # "data hub" leads with the analytics rows, then the rows that only spell DataHub
    hub = keys('data hub')
    assert set(hub[:3]) == {'uvRT', 'tool:fm_get_retained_possession_events', 'UZlS'} and hub[3:] == ['GfON']
    assert keys('zone map') == ['uvRT', 'UZlS']
    # every word must match: a word no row or topic holds gives nothing
    assert keys('possession gained xylophone') == [] and keys('PossessionShare') == ['ZZZZ']


def test_screen_reads_mark_the_analytics_keys():
    data = _ui_rows()
    assert ledger.apply_screen_reads(data['rows']) == 2
    by_key = {r[1]: r for r in data['rows']}
    parent, field = by_key['uvRT'], by_key['UZlS']
    assert parent[7] == field[7] == 'reads' and parent[12] == field[12] == 'on_demand'
    assert 'fm_get_ui_screen(team_analytics)' in parent[9] and 'fm_ui_read(28:TEAM_UI_HANDLER)' in parent[9]
    assert 'Hhum' in parent[8] and 'uvRT' in field[8] and field[3] == 'TEAM_UI_HANDLER'
    assert ledger.apply_screen_reads(data['rows']) == 0          # a second pass changes nothing
    packaged = ledger.load(ledger.CURRENT)
    if packaged is not None:
        status = {r[1]: r[7] for r in packaged['rows'] if r[0] == 'ui'}
        assert status['uvRT'] == status['fGjn'] == status['UZlS'] == status['pyZE'] == 'reads'
        from fm_live_mcp.fmdb import ledger_tools
        found = ledger_tools.coverage(search='possession gained')
        assert found['matches']['total'] and found['items'][0]['key'] in ('uvRT', 'fGjn')
        assert any(i['key'] == 'tool:fm_get_retained_possession_events' for i in found['items'])
        hub = [i['key'] for i in ledger_tools.coverage(search='data hub')['items']]
        topic = {key for _text, keys in ledger.SEARCH_TOPICS for _denom, key in keys}
        assert {'uvRT', 'fGjn', 'FyDK', 'rijN', 'LtKt', 'EHW7', 'MU5d'} <= set(hub) and set(hub[:12]) <= topic
        assert status['FyDK'] == status['rijN'] == status['LtKt'] == status['EHW7'] == status['8Z0D'] == status['xlO9'] == 'reads'
        assert ledger_tools.coverage(search='pass map')['items'][0]['key'] in ('LtKt', 'UIwU', 'EHW7', 'FOjz', 'MU5d', 'TqMq', 'k3hM')
