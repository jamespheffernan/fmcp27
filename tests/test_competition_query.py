import struct

import pytest

from fm_live_mcp import competitions, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_competitions import competition_record
from test_database import bind, database_memory
from test_players import memory
from test_world import world_memory


def test_enumeration_search_and_fresh_read(bridge, monkeypatch, competition_record):
    m = competition_record
    bind(bridge, monkeypatch, m)
    result = bridge.find_competitions(bridge.session)
    assert result['complete_table_scan'] and result['stop_reason'] == 'table_end'
    assert result['scanned_records'] == result['count'] == 2
    assert result['start_index'] == 0 and result['next_index'] == 2
    assert result['next_cursor'] is None
    first = result['competitions'][0]
    assert bridge.get_competition(bridge.session, first['competition_ref'])['competition'] == first
    m['q'](m['competitions'][0] + 0x40, m['text']('Changed title'))
    fresh = bridge.get_competition(bridge.session, first['competition_ref'])
    assert fresh['competition']['name'] == 'Changed title'
    assert fresh['save_identity'] == 'native_binding_rechecked'
    assert bridge.find_competitions(bridge.session, name='premier')['count'] == 1  # Short name.
    assert bridge.find_competitions(bridge.session, name='tst')['count'] == 2  # Abbreviation.
    assert bridge.find_competitions(bridge.session, native_id=101)['competitions'][0]['database_index'] == 1
    assert bridge.find_competitions(bridge.session, name='premier', native_id=101)['count'] == 0


def test_null_empty_and_unicode_names(bridge, monkeypatch, competition_record):
    m = competition_record
    bind(bridge, monkeypatch, m)
    for offset in (0x40, 0x48, 0x50):
        m['q'](m['competitions'][0] + offset, 0)
    m['q'](m['competitions'][0] + 0x48, m['text'](''))
    m['q'](m['competitions'][1] + 0x40, m['text']('Straße ÉLITE'))
    all_rows = bridge.find_competitions(bridge.session)
    assert all_rows['unnamed_records_examined'] == 1
    assert all_rows['competitions'][0]['name'] is None
    assert all_rows['competitions'][0]['short_name'] == ''
    assert bridge.find_competitions(bridge.session, name='STRASSE élite')['count'] == 1
    assert bridge.find_competitions(bridge.session, native_id=100)['count'] == 1


def test_cursor_continues_empty_pages_and_binds_criteria(bridge, monkeypatch, competition_record):
    m = competition_record
    bind(bridge, monkeypatch, m)
    first = bridge.find_competitions(bridge.session, native_id=101, record_budget=1)
    assert first['count'] == 0 and first['stop_reason'] == 'record_budget'
    assert not first['complete_table_scan'] and first['next_index'] == 1
    cursor = first['next_cursor']
    for kwargs in ({}, {'native_id': 100}, {'native_id': 101, 'name': 'Cup'}):
        with pytest.raises(BridgeError, match='different query'):
            bridge.find_competitions(bridge.session, cursor=cursor, **kwargs)
    last = bridge.find_competitions(bridge.session, native_id=101, max_matches=1, cursor=cursor)
    assert last['count'] == 1 and last['next_cursor'] is None
    assert last['start_index'] == 1 and last['next_index'] == 2
    assert last['stop_reason'] == 'table_end' and not last['complete_table_scan']
    first = bridge.find_competitions(bridge.session, max_matches=1)
    assert first['stop_reason'] == 'match_limit'
    m['vec'](m['headers']['competitions'], m['competitions'][:1])
    with pytest.raises(BridgeError, match='cursor expired'):
        bridge.find_competitions(bridge.session, cursor=first['next_cursor'])


def test_empty_competition_table(bridge, monkeypatch, competition_record):
    m = competition_record
    bind(bridge, monkeypatch, m)
    m['vec'](m['headers']['competitions'], [])
    result = bridge.find_competitions(bridge.session)
    assert result['complete_table_scan'] and result['count'] == result['scanned_records'] == 0
    assert result['next_cursor'] is None


@pytest.mark.parametrize('kwargs', [
    {'name': ''}, {'name': 5}, {'name': 'bad\nname'}, {'name': 'é' * 65}, {'name': '\ud800'},
    {'native_id': True}, {'native_id': 0}, {'native_id': -1}, {'native_id': 2**32},
    {'max_matches': True}, {'max_matches': 101}, {'record_budget': 1001}, {'record_budget': 0},
    {'cursor': ''}, {'cursor': []},
])
def test_invalid_query_arguments(bridge, kwargs):
    with pytest.raises(BridgeError):
        bridge.find_competitions(bridge.session, **kwargs)


@pytest.mark.parametrize('fault', ['membership', 'identity', 'secondary_identity', 'index', 'type', 'getter'])
def test_stale_references_rejected_and_evicted(bridge, monkeypatch, competition_record, fault):
    m = competition_record
    bind(bridge, monkeypatch, m)
    ref = bridge.find_competitions(bridge.session)['competitions'][0]['competition_ref']
    a = m['competitions'][0]
    if fault == 'membership':
        m['vec'](m['headers']['competitions'], [m['competitions'][1], a])
    elif fault == 'identity':
        m['put'](a + 12, struct.pack('<II', 999, 999))
    elif fault == 'secondary_identity':
        m['put'](a + 16, struct.pack('<I', 999))
    elif fault == 'index':
        m['put'](a + 8, struct.pack('<I', 1))
    elif fault == 'type':
        m['q'](a, m['base'] + world.TYPES['club'][0])
    else:
        m['q'](m['base'] + world.TYPES['competition'][0] + 24, 0)
    with pytest.raises(BridgeError):
        bridge.get_competition(bridge.session, ref)
    assert ref not in bridge.competition_refs


@pytest.mark.parametrize('fault', ['record', 'vector', 'name', 'lookup_mode'])
def test_mutation_never_publishes_partial_rows_or_refs(bridge, monkeypatch, competition_record, fault):
    m = competition_record
    bind(bridge, monkeypatch, m)
    original = competitions.by_index
    def changing(read, base, index, **kwargs):
        row = original(read, base, index, **kwargs)
        if index == 1:
            if fault == 'record':
                m['put'](m['competitions'][0] + 12, struct.pack('<II', 999, 999))
            elif fault == 'vector':
                m['vec'](m['headers']['competitions'], m['competitions'])
            elif fault == 'name':
                m['q'](m['competitions'][0] + 0x40, m['text']('Replaced'))
            else:
                m['put'](m['base'] + competitions.LOOKUP_MODE, b'\x00')
        return row
    monkeypatch.setattr(competitions, 'by_index', changing)
    with pytest.raises(BridgeError, match='changed during read'):
        bridge.find_competitions(bridge.session)
    assert not bridge.competition_refs and not bridge.database_cursors


def test_corrupt_later_record_rejects_entire_query(bridge, monkeypatch, competition_record):
    m = competition_record
    bind(bridge, monkeypatch, m)
    m['q'](m['competitions'][1], 0)
    with pytest.raises(BridgeError, match='no partial result'):
        bridge.find_competitions(bridge.session)
    assert not bridge.competition_refs


def test_detach_and_save_change_invalidate_references(bridge, monkeypatch, competition_record):
    m = competition_record
    bind(bridge, monkeypatch, m)
    ref = bridge.find_competitions(bridge.session, max_matches=1)['competitions'][0]['competition_ref']
    m['q'](m['save'] + 0x28, m['text']('Different career'))
    with pytest.raises(BridgeError, match='identity changed'):
        bridge.get_competition(bridge.session, ref)
    assert not bridge.competition_refs and not bridge.database_cursors
    bridge.attach()
    ref = bridge.find_competitions(bridge.session)['competitions'][0]['competition_ref']
    sid = bridge.session
    bridge.detach()
    assert not bridge.competition_refs
    with pytest.raises(BridgeError, match='Unknown session'):
        bridge.get_competition(sid, ref)


def test_wrong_reference_kind_rejected(bridge, monkeypatch, competition_record):
    bind(bridge, monkeypatch, competition_record)
    bridge.club_refs['club'] = {}
    for ref in ('club', 'unknown', []):
        with pytest.raises(BridgeError, match='Unknown competition'):
            bridge.get_competition(bridge.session, ref)
