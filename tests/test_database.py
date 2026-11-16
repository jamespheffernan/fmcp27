import struct

import pytest

from fm_live_mcp import database, players, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_players import memory
from test_world import world_memory


@pytest.fixture
def database_memory(world_memory, memory):
    m = world_memory
    tables = tuple(m['base'] + rva for rva in players.RVA)
    for offset, table in zip((0, 0x140, 0x388), tables):
        struct.pack_into('<Q', memory, 0x1000 + offset, table)
    m['put'](0x1000, memory[0x1000:])
    roots, headers = {}, {}
    for kind, (root_rva, table_rva, name) in database.TABLES.items():
        root = m['allocate'](0x90)
        info, name_address, header = m['allocate'](16), m['allocate'](len(name) + 1), m['allocate'](24)
        m['put'](name_address, name + b'\0')
        m['q'](info + 8, name_address)
        m['put'](m['base'] + table_rva - 16, struct.pack('<qQ', 0, info))
        m['q'](m['base'] + root_rva, root)
        m['q'](root, m['base'] + table_rva)
        m['q'](root + 0x88, header)
        m['vec'](header, [0x1388] if kind == 'people' else [m['club']])
        roots[kind], headers[kind] = root, header
    m.update(tables=tables, roots=roots, headers=headers)
    return m


def bind(bridge, monkeypatch, m):
    # Historical field fixtures have no Mach-O image. Strict core roster runtime
    # publication is tested separately through actual Bridge/native verifiers.
    bridge.plugin_identity = ('isolated-database-fields', b'fixture runtime')
    monkeypatch.setattr(players, 'verify_runtime', lambda read, base, uuid: m['tables'])
    monkeypatch.setattr(bridge, '_player_layout', lambda p: m['tables'])
    monkeypatch.setattr(bridge, '_read_memory', lambda p,a,n: m['read'](a,n))


def receipt(**kw):
    return {'matches': [{'address': '0x1000'}], 'next_index': 1, 'scanned_records': 1,
            'actual_players_examined': 1, 'other_person_records': 0, 'stop_reason': 'table_end', **kw}


def test_catalog_and_search_recheck_actual_membership(bridge, monkeypatch, database_memory):
    m = database_memory
    bind(bridge, monkeypatch, m)
    assert bridge.get_database_catalog(bridge.session)['native_table_counts'] == dict.fromkeys(database.TABLES, 1)
    monkeypatch.setattr(bridge, '_run', lambda *a: receipt())
    found = bridge.find_save_players(bridge.session, 'Test')
    assert found['complete_table_scan'] and found['count'] == 1
    ref = found['players'][0]['player_ref']
    fresh = bridge.get_player(bridge.session, ref)
    assert fresh['player']['name'] == 'Test Müller'
    assert fresh['save_identity'] == 'native_binding_rechecked'
    # An unchanged object must still be rejected after it leaves the live table.
    m['vec'](m['headers']['people'], [m['club']])
    with pytest.raises(BridgeError, match='membership changed'):
        bridge.get_player(bridge.session, ref)
    assert ref not in bridge.player_refs


@pytest.mark.parametrize('fault', ['type', 'rtti', 'bounds', 'membership', 'index'])
def test_bad_database_links_fail_without_refs(bridge, monkeypatch, database_memory, fault):
    m = database_memory
    bind(bridge, monkeypatch, m)
    monkeypatch.setattr(bridge, '_run', lambda *a: receipt())
    if fault == 'type': m['q'](m['roots']['people'], 0)
    if fault == 'rtti': m['q'](m['base'] + database.TABLES['people'][1] - 16, 8)
    if fault == 'bounds': m['put'](m['headers']['people'], struct.pack('<QQQ', 4096, 4095, 8192))
    if fault == 'membership': m['vec'](m['headers']['people'], [m['club']])
    if fault == 'index': m['put'](0x1390, struct.pack('<I', 7))
    with pytest.raises(BridgeError): bridge.find_save_players(bridge.session, 'Test')
    assert bridge.player_refs == {}


def test_pagination_binds_query_and_header(bridge, monkeypatch, database_memory):
    m = database_memory
    bind(bridge, monkeypatch, m)
    m['vec'](m['headers']['people'], [0x1388, m['manager']])
    monkeypatch.setattr(bridge, '_run', lambda *a: receipt(stop_reason='match_limit'))
    first = bridge.find_save_players(bridge.session, 'Test', max_matches=1)
    cursor = first['next_cursor']
    assert cursor and not first['complete_table_scan']
    with pytest.raises(BridgeError, match='different query'):
        bridge.find_save_players(bridge.session, 'Other', cursor=cursor)
    monkeypatch.setattr(bridge, '_run', lambda *a: receipt(matches=[], next_index=2, actual_players_examined=0, other_person_records=1))
    last = bridge.find_save_players(bridge.session, 'Test', cursor=cursor)
    assert last['next_cursor'] is None and not last['complete_table_scan'] and last['count'] == 0
    m['vec'](m['headers']['people'], [0x1388])
    with pytest.raises(BridgeError, match='cursor expired'):
        bridge.find_save_players(bridge.session, 'Test', cursor=cursor)
    bridge.detach()
    assert bridge.database_cursors == {}


@pytest.mark.parametrize('changes', [{'next_index': 0}, {'next_index': 2}, {'scanned_records': 2},
                                    {'other_person_records': 1}, {'stop_reason': 'match_limit'},
                                    {'matches': [{'address': '0x1000'}] * 2}])
def test_bad_scan_receipts_never_publish_refs(bridge, monkeypatch, database_memory, changes):
    bind(bridge, monkeypatch, database_memory)
    monkeypatch.setattr(bridge, '_run', lambda *a: receipt(**changes))
    with pytest.raises(BridgeError): bridge.find_save_players(bridge.session, 'Test')
    assert bridge.player_refs == {}


def test_table_mutation_during_native_scan_rejects_results(bridge, monkeypatch, database_memory):
    m = database_memory
    bind(bridge, monkeypatch, m)
    def scan(*a):
        m['vec'](m['headers']['people'], [0x1388])
        return receipt()
    monkeypatch.setattr(bridge, '_run', scan)
    with pytest.raises(BridgeError, match='changed during read'):
        bridge.find_save_players(bridge.session, 'Test')
    assert bridge.player_refs == {}


@pytest.mark.parametrize('kind', ['awards', 'removed_records', 'derbies', 'agreements'])
@pytest.mark.parametrize('fault', ['wrong_type', 'wrong_name', 'reversed_bounds'])
def test_additional_catalog_roots_reject_corrupt_sources(database_memory, kind, fault):
    m = database_memory
    root_rva, table_rva, name = database.TABLES[kind]
    if fault == 'wrong_type':
        m['q'](m['roots'][kind], m['base'] + database.TABLES['people'][1])
    elif fault == 'wrong_name':
        info = int.from_bytes(m['read'](m['base'] + table_rva - 8, 8), 'little')
        name_address = int.from_bytes(m['read'](info + 8, 8), 'little')
        m['put'](name_address, b'X' + name[1:] + b'\0')
    else:
        m['put'](m['headers'][kind], struct.pack('<QQQ', 8192, 4096, 8192))
    with pytest.raises(ValueError):
        database.table(m['read'], m['base'], kind)
