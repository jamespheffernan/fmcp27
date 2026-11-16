"""Editor fields decided by a targeted full scan (fmdb/editor_live.py), the empty_in_save ledger status and the
superseded responsibility keys (fieldroutes.py): offline tests on the shipped data file and synthetic rows."""
from __future__ import annotations

from fm_live_mcp.fmdb import editor_live, fieldroutes, ledger


def _doc(**pairs):
    return {'pairs': pairs}


def test_decide_value_empty_unreached_and_partial():
    doc = _doc(**{
        'club.AAAA': {'asked': 10, 'of': 100, 'complete': False, 'counts': {'value': 3, 'unset': 7},
                      'examples': [{'index': 4, 'unique_id': 99, 'value': '12'}]},
        'club.BBBB': {'asked': 100, 'of': 100, 'complete': True, 'counts': {'unset': 60, 'nh': 40}, 'examples': []},
        'club.CCCC': {'asked': 100, 'of': 100, 'complete': True, 'counts': {'nh': 100}, 'examples': []},
        'club.DDDD': {'asked': 50, 'of': 100, 'complete': False, 'counts': {'unset': 50}, 'examples': []},
        'club.EEEE': {'asked': 100, 'of': 100, 'complete': True,
                      'counts': {'unavailable:instruction budget exceeded': 80, 'unset': 20}, 'examples': []},
    })
    status, why = editor_live.decide('club.AAAA', doc)
    assert status == 'reads' and 'record index 4' in why and '3+' in why
    assert editor_live.decide('club.BBBB', doc)[0] == 'empty_in_save'
    assert editor_live.decide('club.CCCC', doc)[0] == 'unreached'
    assert editor_live.decide('club.DDDD', doc) is None
    status, why = editor_live.decide('club.EEEE', doc)
    assert status == 'unavailable' and 'instruction budget' in why
    assert editor_live.decide('club.ZZZZ', doc) is None


def test_decide_list_items():
    doc = _doc(**{
        'club.Cstc.Styp': {'asked': 100, 'of': 100, 'complete': True, 'lists': 0, 'counts': {},
                           'examples': [], 'parent_counts': {'unset': 100}},
        'play.PATL.valu': {'asked': 5, 'of': 100, 'complete': False, 'lists': 5, 'counts': {'value': 90},
                           'examples': [{'index': 1, 'unique_id': 2, 'value': '78'}], 'parent_counts': {'value': 5}},
        'play.PATL.WeGK': {'asked': 5, 'of': 100, 'complete': False, 'lists': 5, 'counts': {'unset': 90},
                           'examples': [], 'parent_counts': {'value': 5}},
    })
    assert editor_live.decide('club.Cstc.Styp', doc)[0] == 'empty_in_save'
    assert editor_live.decide('play.PATL.valu', doc)[0] == 'reads'
    assert editor_live.decide('play.PATL.WeGK', doc) is None     # parent not asked of every record


def test_embedded_types():
    doc = _doc(**{
        'recs.database_record#Club': {'asked': 5, 'of': 5, 'complete': True, 'counts': {'value': 5},
                                      'examples': [{'index': 0, 'unique_id': 1}], 'table': 'clubs'},
        'stad.Shts': {'asked': 3, 'of': 3, 'complete': True, 'counts': {'value': 3, 'true': 2, 'false': 1},
                      'examples': [], 'via': 'stad.Ssds'},
        'ktfl.kite': {'asked': 3, 'of': None, 'complete': False, 'counts': {'value': 0, 'unset': 9}, 'examples': []},
    })
    key = editor_live.embedded_key('recs.database_record', 'Club')
    status, why = editor_live.decide(key, doc)
    assert status == 'reads' and 'clubs' in why
    status, why = editor_live.decide('stad.Shts', doc)
    assert status == 'reads' and 'inferred' in why and 'indx 0' in why
    assert editor_live.decide('ktfl.kite', doc)[0] == 'unreached'
    assert editor_live.STAND_KEYS['Shtl'] == 7 and len(editor_live.RECS_TABLES) == 21
    assert len(editor_live.LSTS_TABLES) == 19


def test_shipped_scan_file():
    doc = editor_live.load()
    assert doc['pairs'], 'data/editor_live.json.gz missing or empty'
    summary = editor_live.summary(doc)
    assert summary.get('reads', 0) > 100 and summary.get('empty_in_save', 0) > 400
    # the 25-record census said "unavailable" for the role tables; the full scan reads them on FastVM
    assert editor_live.decide('play.PATL', doc)[0] == 'reads'
    assert editor_live.decide('play.PWEI.WeGK', doc)[0] == 'reads'
    for rtype, info in doc['types'].items():
        if rtype != 'embedded':
            assert info['records'] and info['scanned'], rtype


def test_ledger_status_and_overlay():
    assert 'empty_in_save' in ledger.STATUSES
    assert ledger.STATUSES.index('empty_in_save') < ledger.STATUSES.index('unreached')
    status, route, reason, surfaces = ledger._editor_live('recs.database_record', 'recs', 'database_record', (),
                                                          'unreached', 'none', 'record type not enumerated', [],
                                                          'Person')
    assert status == 'reads' and route == 'direct' and 'people' in reason
    # a not-claimed key keeps its status and gains the field-route proof
    status, _, reason, _ = ledger._editor_live('club.RP07', 'club', 'RP07', (), 'unreached', 'none',
                                               'the record getter does not claim the key', [], 'Person')
    assert status == 'unreached' and 'TCrs' in reason
    rows = [ledger._row('editor', 'x.A', 'people and world database', 'A', status='empty_in_save')]
    counts = ledger._counts(rows)
    assert counts['by_status']['empty_in_save'] == 1 and counts['reads'] == 0


def test_responsibility_rows_are_superseded():
    note = fieldroutes.superseded('club', 'RP42')
    assert note and 'TCrs' in note
    assert fieldroutes.superseded('natc', 'RJ00')
    assert fieldroutes.superseded('club', 'RPxx') is None and fieldroutes.superseded('pers', 'RP01') is None
    assert fieldroutes.reason('club', 'RJ13').startswith('superseded:')
    assert 'superseded' in fieldroutes.CATEGORIES
