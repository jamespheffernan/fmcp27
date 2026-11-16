"""Synthetic typed native sources through the real Bridge sealed read scope.

No live process, UI, native game function, generated profile or attributes.
"""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
import struct

import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import assessment_people, bridge as bridge_module
from fm_live_mcp import live_player_contract_expiry as query
from fm_live_mcp import player_contract_expiry_tools as tools, players, world
from fm_live_mcp.bridge import BridgeError
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_database import database_memory
from test_players import memory
from test_shortlist_members import member_memory
from test_teams import team_memory
from test_world import world_memory


def packed(value):
    from datetime import date
    d = date.fromisoformat(value)
    return struct.pack('<I', d.year << 16 | d.timetuple().tm_yday)


@pytest.fixture
def expiry_memory(prepared_tactics_memory, member_memory, bridge, monkeypatch):
    m = prepared_tactics_memory
    assert m is member_memory
    for rva, raw in assessment_people.NATIVE_SPANS:
        m['put'](m['base'] + rva, raw)
    m['people_list'] = [0x1388]
    m['extra_people'] = []
    m['contracts'] = {}

    def contract(primary, person, state='fixed_expiry', expiry='2033-06-30'):
        table = int.from_bytes(m['read'](person, 8), 'little')
        for slot, getter, adjustment in ((73, 0xCA4764, 0x258), (121, 0xCB3724, 0x3D8)):
            m['q'](table + slot * 8, m['base'] + getter)
            m['put'](table - adjustment, struct.pack('<q', -0x110))
        m['q'](primary + 0x128, m['team'])
        m['put'](person - 0x24, packed('2028-02-29'))
        if state == 'no_contract':
            m['q'](person - 0x98, 0)
            return None
        c = m['typed']('basic_contract' if state == 'basic_contract_fields_unavailable' else 'full_contract', 0xC8)
        for off, val in ((8, person), (0x10, m['team']), (0x18, m['team'])):
            m['q'](c + off, val)
        m['q'](person - 0x98, c)
        m['put'](c + 0x44, packed('2030-05-31'))
        m['put'](c + 0x48, packed(expiry))
        m['put'](c + 0x2B, b'\x08' if state == 'dynamic_expiry' else b'\0')
        table = m['base'] + world.TYPES['full_contract'][0]
        m['q'](table + 29 * 8, m['base'] + 0x1005C68)
        m['q'](table + 30 * 8, m['base'] + 0x12920F8)
        m['contracts'][primary] = c
        return c

    def add(kind='actual', state='fixed_expiry', name='Other', expiry='2033-06-30'):
        index = len(m['people_list'])
        primary, person = m['add_person'](kind, index, 100 + index, 100 + index, name)
        m['extra_people'].append((primary, person))
        m['people_list'].append(person)
        m['vec'](m['headers']['people'], m['people_list'])
        if kind in ('actual', 'player_staff'):
            contract(primary, person, state, expiry)
        return primary, person

    contract(0x1000, 0x1388)
    bridge.plugin_identity = ('synthetic pinned plugin', 'synthetic UUID')
    m['layout_calls'] = []
    def layout(process):
        m['layout_calls'].append(process)
        return m['tables']
    monkeypatch.setattr(bridge, '_player_layout', layout)
    m['reads'] = []
    def read(process, address, size):
        m['reads'].append((address, size))
        # Player names/identity/contracts must never decode attribute bytes.
        for primary, person in [(0x1000, 0x1388)] + list(m.get('extra_people', [])):
            if address < primary + 0x18D and address + size > primary + 0x148:
                pytest.fail('Player attribute bytes were read')
        return m['read'](address, size)
    monkeypatch.setattr(bridge, '_read_memory', read)
    monkeypatch.setattr(players, 'decode', lambda *a, **kw: pytest.fail('Rich profile decoder'))
    monkeypatch.setattr(bridge, '_roster_player', lambda *a, **kw: pytest.fail('Rich roster decoder'))
    m['stream_events'] = []
    class Stream:
        def __init__(self, helper, pid):
            self.pid = pid
            m['stream_events'].append('open')
        def close(self):
            m['stream_events'].append('close')
    monkeypatch.setattr(bridge_module, 'ReadStream', Stream)
    m.update(bridge=bridge, add=add, set_contract=contract)
    return m


def get(m, cutoff='2033-06-30', **kwargs):
    return query.get_managed_player_contract_expiry(m['bridge'], m['bridge'].session, cutoff, **kwargs)


def test_inclusive_cutoff_no_profile_and_real_scope(expiry_memory):
    m = expiry_memory
    before = deepcopy(m['cells'])
    r = get(m, coach_name=' test COACH ')
    assert r['matched_count'] == r['classified_count'] == r['scanned_count'] == 1
    row, = r['players']
    assert row['contract_dates']['expires'] == '2033-06-30'
    assert row['main_contract_club']['native_id'] == row['current_club']['native_id'] == 688
    assert row['native_identity'] == {'database_index': 0, 'native_id': 12345, 'random_id': None}
    assert row['name'] == row['display_name'] == 'Test Müller'
    assert m['bridge'].player_refs[row['player_ref']]['identity'] == (12345, 'Test', 'Müller', '2000-02-29', 12345)
    assert r['save']['current_date'] == '2030-09-19'
    assert r['atomic'] is r['native_calls'] is r['saved_file_fallback'] is False
    assert m['cells'] == before and len(m['layout_calls']) == 2
    assert m['stream_events'] == ['open', 'close'] and m['bridge']._reader is None
    assert not any(key in json.dumps(r) for key in ('address', 'attributes'))
    assert get(m, cutoff='2033-06-29')['fixed_nonmatch_count'] == 1
    assert get(m, cutoff='2033-06-29')['matched_count'] == 0


def test_sort_ties_duplicates_nulls_and_complete_manifest(expiry_memory):
    m = expiry_memory
    ada, _ = m['add'](name='Ada', expiry='2031-01-01')
    zed, _ = m['add'](name='Zed', expiry='2031-01-01')
    future, _ = m['add'](name='Future', expiry='2034-01-01')
    m['vec'](m['team'] + 0x38, [zed, 0, 0x1000, ada, ada, future])
    r = get(m, limit=2, unclassified_limit=0)
    assert r['scanned_count'] == r['native_slot_count'] == 6
    assert r['classified_count'] == 5 and r['fixed_nonmatch_count'] == 1
    assert r['matched_count'] == 4 and r['returned_count'] == 2
    assert r['truncated_count'] == 2 and r['truncated'] and r['next_offset'] == 2
    assert r['duplicate_slot_count'] == 1 and r['unclassified_count'] == 1
    assert r['unclassified_returned_count'] == 0 and r['unclassified_truncated_count'] == 1
    assert [p['roster_index'] for p in r['players']] == [3, 4]
    assert len({p['player_ref'] for p in r['players']}) == 1
    assert [p['matches_cutoff'] for p in r['slot_manifest']] == [True, None, True, True, True, False]
    second = get(m, offset=r['next_offset'], expected_source_id=r['source_id'])
    assert [p['roster_index'] for p in second['players']] == [0, 2]
    assert second['source_id'] == r['source_id'] and second['next_offset'] is None
    assert second['observed_at'] != r['observed_at']


def test_all_unclassified_states_and_combined_fixed_player(expiry_memory):
    m = expiry_memory
    roster = [0x1000]
    for state in ('dynamic_expiry', 'no_contract', 'basic_contract_fields_unavailable'):
        roster.append(m['add'](state=state)[0])
    for kind in ('virtual', 'staff'):
        roster.append(m['add'](kind=kind)[0])
    combined, _ = m['add'](kind='player_staff', name='Combined')
    roster.extend((combined, 0))
    m['vec'](m['team'] + 0x38, roster)
    r = get(m, unclassified_limit=256)
    assert r['scanned_count'] == 8 and r['classified_count'] == 2 and r['unclassified_count'] == 6
    assert r['state_counts'] == {'fixed_expiry': 2, 'dynamic_expiry': 1, 'no_contract': 1,
        'basic_contract_fields_unavailable': 1, 'virtual_unsupported': 1,
        'unsupported_person_kind': 1, 'null_slot': 1}
    assert [p['matches_cutoff'] for p in r['slot_manifest']] == [True, None, None, None, None, None, True, None]
    assert [p['state'] for p in r['unclassified_players']] == list(r['state_counts'])[1:]
    row = next(p for p in r['players'] if p['record_kind'] == 'player_staff')
    assert m['bridge'].player_refs[row['player_ref']]['identity'][0] == 'player_staff'
    dynamic = r['unclassified_players'][0]['contract_dates']
    assert dynamic['state'] == 'dynamic_expiry' and dynamic['expiry_anchor_date'] == '2030-09-19'


def test_loaned_out_membership_keeps_distinct_main_and_current_clubs(expiry_memory):
    m = expiry_memory
    # Existing checked TEAM owned by a different canonical league-body club.
    m['q'](0x1128, m['team_addresses'][2])
    r = get(m)
    row, = r['players']
    assert row['main_contract_club']['native_id'] == 688
    assert row['current_club']['native_id'] == 702
    assert row['main_contract_teams'][0]['native_id'] == 50
    assert row['current_club_team']['native_id'] == 52
    assert r['matched_count'] == 1 and 'loaned-out' in r['scope']
    assert 'on_loan' not in row and 'loan_contract' not in row


def test_empty_roster_and_256_duplicate_matches_are_retrievable(expiry_memory):
    m = expiry_memory
    m['vec'](m['team'] + 0x38, [])
    empty = get(m)
    assert empty['complete_native_roster_scan'] and empty['scanned_count'] == 0
    assert empty['slot_manifest'] == empty['players'] == []
    m['vec'](m['team'] + 0x38, [0x1000] * 256)
    page = get(m)
    assert page['matched_count'] == 256 and page['duplicate_slot_count'] == 255
    union = page['players']
    while page['next_offset'] is not None:
        page = get(m, offset=page['next_offset'], expected_source_id=page['source_id'])
        union.extend(page['players'])
    assert [p['roster_index'] for p in union] == list(range(256))


@pytest.mark.parametrize('cutoff', ['20330630', '2033-6-30', '2033-02-30', '2201-01-01', None, True, 123])
def test_bad_cutoff_before_scope(expiry_memory, monkeypatch, cutoff):
    m = expiry_memory
    monkeypatch.setattr(m['bridge'], '_read_scope', lambda *a, **kw: pytest.fail('Invalid input reached source'))
    with pytest.raises(BridgeError, match='YYYY-MM-DD'):
        get(m, cutoff)


@pytest.mark.parametrize('kwargs', [{'limit': True}, {'limit': 0}, {'limit': 101},
    {'unclassified_limit': -1}, {'unclassified_limit': 257}, {'unclassified_limit': False},
    {'offset': -1}, {'offset': 257}, {'offset': True}, {'coach_name': ''}, {'coach_name': True},
    {'expected_source_id': 'A' * 64}, {'expected_source_id': True}, {'offset': 1}])
def test_bad_bounds_before_scope(expiry_memory, monkeypatch, kwargs):
    m = expiry_memory
    monkeypatch.setattr(m['bridge'], '_read_scope', lambda *a, **kw: pytest.fail('Invalid input reached source'))
    with pytest.raises(BridgeError):
        get(m, **kwargs)


@pytest.mark.parametrize('fault', ['pointer', 'primary', 'person', 'canonical', 'cast', 'contract_owner',
    'contract_type', 'date', 'getter', 'main_team', 'current_team', 'roster_bound', 'roster_geometry'])
def test_malformed_sources_reject_entire_result_without_refs(expiry_memory, fault):
    m = expiry_memory
    c = m['contracts'][0x1000]
    if fault == 'pointer': m['vec'](m['team'] + 0x38, [3])
    elif fault == 'primary': m['q'](0x1000, m['base'] + world.TYPES['club'][0])
    elif fault == 'person': m['q'](0x1388, 0)
    elif fault == 'canonical': m['vec'](m['headers']['people'], [m['club']])
    elif fault == 'cast': m['q'](m['base'] + players.RVA[2] + 0x668, 0)
    elif fault == 'contract_owner': m['q'](c + 8, m['manager'])
    elif fault == 'contract_type': m['q'](c, m['base'] + world.TYPES['club'][0])
    elif fault == 'date': m['put'](c + 0x48, bytes(4))
    elif fault == 'getter': m['q'](m['base'] + world.TYPES['full_contract'][0] + 30 * 8, 0)
    elif fault == 'main_team': m['q'](c + 0x18, m['team_addresses'][2])
    elif fault == 'current_team': m['q'](0x1128, m['team_addresses'][1])
    elif fault == 'roster_bound': m['vec'](m['team'] + 0x38, [0x1000] * 257)
    else: m['put'](m['team'] + 0x38, struct.pack('<QQQ', 4001, 4009, 4009))
    with pytest.raises(BridgeError, match='no partial result'):
        get(m)
    assert m['bridge'].player_refs == {} and m['bridge']._reader is None


@pytest.mark.parametrize('fault', ['date', 'date_flags', 'membership', 'classification', 'main_club', 'current_club', 'cutoff'])
def test_source_pinned_continuation_refuses_changes(expiry_memory, fault):
    m = expiry_memory
    m['vec'](m['team'] + 0x38, [0x1000] * 2)
    first = get(m, limit=1)
    if fault == 'date': m['put'](m['contracts'][0x1000] + 0x48, packed('2032-01-01'))
    elif fault == 'date_flags':
        value = int.from_bytes(packed('2033-06-30'), 'little') | (1 << 9)
        m['put'](m['contracts'][0x1000] + 0x48, struct.pack('<I', value))
    elif fault == 'membership': m['vec'](m['team'] + 0x38, [0x1000] * 3)
    elif fault == 'classification': m['put'](m['contracts'][0x1000] + 0x2B, b'\x08')
    elif fault == 'main_club':
        for off in (0x10, 0x18): m['q'](m['contracts'][0x1000] + off, m['team_addresses'][2])
    elif fault == 'current_club': m['q'](0x1128, m['team_addresses'][2])
    with pytest.raises(BridgeError, match='source or selectors changed'):
        get(m, cutoff='2034-01-01' if fault == 'cutoff' else '2033-06-30',
            offset=1, expected_source_id=first['source_id'])


@pytest.mark.parametrize('callback', [3, 4, 5])
@pytest.mark.parametrize('fault', ['date', 'canonical', 'roster', 'ref', 'plugin', 'world', 'process'])
def test_real_scope_postyield_and_final_callbacks_cannot_hide_mutations(expiry_memory, monkeypatch, callback, fault):
    m = expiry_memory
    original = m['bridge']._current
    calls = 0
    def current(session):
        nonlocal calls
        calls += 1
        p = original(session)
        if calls == callback:
            if fault == 'date': m['put'](m['contracts'][0x1000] + 0x48, packed('2034-01-01'))
            elif fault == 'canonical': m['vec'](m['headers']['people'], [m['club']])
            elif fault == 'roster': m['vec'](m['team'] + 0x38, [])
            elif fault == 'ref':
                for ref in m['bridge'].player_refs.values(): ref['identity'] = ('changed',)
            elif fault == 'plugin': m['bridge'].plugin_identity = ('changed',)
            elif fault == 'world': m['bridge'].world_identity = ('changed',)
            elif fault == 'process':
                m['bridge'].process = replace(p, started='replacement')
                return m['bridge'].process
        return p
    monkeypatch.setattr(m['bridge'], '_current', current)
    with pytest.raises(BridgeError, match='no partial result'):
        get(m)
    assert m['bridge'].player_refs == {} and m['bridge']._reader is None


def test_public_save_callback_precedes_fence_and_short_reads_reject(expiry_memory, monkeypatch):
    m = expiry_memory
    original = m['bridge']._public_save
    def public(save):
        result = original(save)
        m['put'](m['contracts'][0x1000] + 0x48, packed('2034-01-01'))
        return result
    monkeypatch.setattr(m['bridge'], '_public_save', public)
    with pytest.raises(BridgeError, match='changed during read'):
        get(m)
    monkeypatch.setattr(m['bridge'], '_public_save', original)
    read = m['bridge']._read_memory
    monkeypatch.setattr(m['bridge'], '_read_memory', lambda p, a, n:
        read(p, a, n)[:-1] if a == m['contracts'][0x1000] + 0x48 else read(p, a, n))
    with pytest.raises(BridgeError, match='Incomplete world read'):
        get(m)


@pytest.mark.parametrize('fault', ['layout', 'plugin', 'date', 'save_count', 'career', 'coach_team'])
def test_final_fresh_context_rejects_drift(expiry_memory, monkeypatch, fault):
    m = expiry_memory
    original = m['bridge']._player_layout
    calls = 0
    def layout(process):
        nonlocal calls
        calls += 1
        tables = original(process)
        if calls == 2:
            if fault == 'layout': return (tables[0] + 8, *tables[1:])
            if fault == 'plugin': m['bridge'].plugin_identity = ('changed',)
            elif fault == 'date': m['put'](m['base'] + world.CURRENT_DATE, packed('2030-09-20'))
            elif fault == 'save_count': m['put'](m['game'] + 0xC8, struct.pack('<I', 419))
            elif fault == 'career': m['q'](m['save'] + 0x28, m['text']('Another career'))
            elif fault == 'coach_team': m['q'](m['team'] + 0x80, m['manager'] + 8)
        return tables
    monkeypatch.setattr(m['bridge'], '_player_layout', layout)
    with pytest.raises(BridgeError, match='no partial result'):
        get(m)
    assert m['bridge'].player_refs == {}


def test_failure_preserves_unrelated_cached_references(expiry_memory, monkeypatch):
    m = expiry_memory
    sentinel = {'unrelated': 'preserved'}
    m['bridge'].player_refs['prior-ref'] = deepcopy(sentinel)
    original = m['bridge']._public_save
    def public(save):
        result = original(save)
        m['put'](m['contracts'][0x1000] + 0x48, packed('2034-01-01'))
        return result
    monkeypatch.setattr(m['bridge'], '_public_save', public)
    with pytest.raises(BridgeError, match='no partial result'):
        get(m)
    assert m['bridge'].player_refs == {'prior-ref': sentinel}


def test_main_and_current_club_absence_is_explicit_without_reclassification(expiry_memory):
    m = expiry_memory
    for off in (0x10, 0x18): m['q'](m['contracts'][0x1000] + off, 0)
    m['q'](0x1128, 0)
    row, = get(m)['players']
    assert row['state'] == 'fixed_expiry'
    assert row['main_contract_teams'] == [None, None]
    assert row['main_contract_club'] is row['current_club_team'] is row['current_club'] is None


def test_registration_schema_dispatches_real_adapter(expiry_memory):
    m = expiry_memory
    async def check():
        mcp = FastMCP('Managed expiry controls')
        tools.register_player_contract_expiry_tools(mcp, m['bridge'])
        tool, = await mcp.list_tools()
        assert tool.name == 'fm_get_managed_player_contract_expiry'
        assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
        assert not tool.annotations.openWorldHint
        assert set(tool.inputSchema['required']) == {'session_id', 'expires_on_or_before'}
        assert set(tool.inputSchema['properties']) == {'session_id', 'expires_on_or_before', 'coach_name',
            'limit', 'unclassified_limit', 'offset', 'expected_source_id'}
        assert tool.inputSchema['properties']['limit']['maximum'] == 100
        assert tool.inputSchema['properties']['unclassified_limit']['maximum'] == 256
        _, r = await mcp.call_tool(tool.name,
            {'session_id': m['bridge'].session, 'expires_on_or_before': '2033-06-30'})
        assert r['matched_count'] == 1 and r['players'][0]['display_name'] == 'Test Müller'
    asyncio.run(check())
