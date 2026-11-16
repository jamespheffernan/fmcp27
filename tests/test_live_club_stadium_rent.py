"""Actual rent core + canonical adapter/schema on synthetic native memory only."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct

import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import club_stadium_rent as core, club_stadium_rent_tools as tools
from fm_live_mcp import live_club_stadium_rent as query, players, prepared_tactics_source, world
from fm_live_mcp.bridge import BridgeError
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_club_finance import finance_memory
from test_database import database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory

import _pinned_build
BINARY = _pinned_build.PLUGIN


@pytest.fixture(scope='module')
def native_rent_image():
    spans, slots = {}, {}
    with BINARY.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == core.PLUGIN_SHA256
        for rva, expected in core.NATIVE_SPANS:
            stream.seek(0x5ED4000 + rva);raw = stream.read(len(expected))
            assert raw == expected;spans[rva] = raw
        for kind, getter in core.GETTERS.items():
            slot = world.TYPES[kind][0] + core.RENT_SLOT
            stream.seek(0x5ED4000 + slot)
            assert struct.unpack('<Q', stream.read(8))[0] & ((1 << 36)-1) == getter
            slots[slot] = getter
    return spans, slots


@pytest.fixture
def live_rent(prepared_tactics_memory, finance_memory, native_rent_image, bridge, monkeypatch):
    m = prepared_tactics_memory
    assert m is finance_memory
    for rva, raw in native_rent_image[0].items():m['put'](m['base'] + rva, raw)
    for slot, getter in native_rent_image[1].items():m['q'](m['base'] + slot, m['base'] + getter)
    m['put'](m['finance'] + 0x7F8, struct.pack('<i', 975321))
    m['bridge'], m['scopes'], m['layout_calls'], m['adapter_reads'] = bridge, [], [], []
    bridge.plugin_identity = ('synthetic verified plugin stamp', core.PLUGIN_SHA256)
    @contextmanager
    def scope(session):
        m['scopes'].append(('enter', session))
        try:yield
        finally:m['scopes'].append(('exit', session))
    monkeypatch.setattr(bridge, '_read_scope', scope)
    def layout(process):
        m['layout_calls'].append(process);return m['tables']
    monkeypatch.setattr(bridge, '_player_layout', layout)
    def read(process, address, size):
        m['adapter_reads'].append((address, size))
        if 0x1000 <= address < 0x1000 + players.SIZE:
            pytest.fail('Club rent adapter read a player/profile/attribute source')
        if address < m['team'] + 0x50 and address + size > m['team'] + 0x38:
            pytest.fail('Club rent adapter read the player roster')
        return m['read'](address, size)
    monkeypatch.setattr(bridge, '_read_memory', read)
    monkeypatch.setattr(bridge, '_run', lambda *a: pytest.fail('Unexpected native helper operation'))
    monkeypatch.setattr(bridge, '_roster_player', lambda *a: pytest.fail('Player profile expansion'))
    monkeypatch.setattr(players, 'decode', lambda *a: pytest.fail('Player decoder'))
    return m


def get(m, coach=None):
    return query.get_club_stadium_rent(m['bridge'], m['bridge'].session, coach)


def test_current_selected_club_positive_has_exact_annual_units_and_no_game_or_profile_activity(live_rent):
    m = live_rent;before = dict(m['cells'])
    result = get(m, ' test   COACH ')
    assert result['save']['current_date'] == '2030-09-19'
    assert result['coach'] == 'Test Coach'
    assert result['team']['native_id'] == 50
    assert result['club'] == {'name': 'Test United', 'short_name': 'Test', 'database_index': 0,
                              'native_id': 688, 'random_id': None}
    rent = result['annual_stadium_rent']
    assert rent['amount'] == 975321 and rent['currency'] == 'GBP' and rent['period'] == 'year'
    assert rent['state'] == 'decoded' and rent['reason'] == 'native_stored_annual_rent'
    assert rent['club_native_identity'] == {'database_index': 0, 'native_id': 688, 'raw_secondary_id': 688}
    assert rent['native_functions_executed'] is rent['game_writes'] is False
    assert rent['freshness'] == 'stored_without_refresh'
    assert result['save_identity'] == 'native_binding_rechecked'
    assert result['atomic'] is result['saved_file_fallback'] is False
    assert 'weekly wages and transfer budgets' in result['scope'] and 'legal lease' in result['scope']
    assert len(m['layout_calls']) == 2 and m['cells'] == before
    assert m['scopes'] == [('enter', m['bridge'].session), ('exit', m['bridge'].session)]
    assert not any(key in json.dumps(result) for key in ('address', 'attributes', 'player_ref', 'manager_address'))


@pytest.mark.parametrize('amount', [0, 1, 2147483647, -1, -2147483648])
def test_concrete_signed_cash_is_neither_pence_weekly_conversion_nor_negative_refund(live_rent, amount):
    m = live_rent;m['put'](m['finance'] + 0x7F8, struct.pack('<i', amount))
    result = get(m)['annual_stadium_rent']
    assert result['amount'] == amount and result['currency'] == 'GBP' and result['period'] == 'year'
    assert result['reason'] == 'native_stored_annual_rent'
    assert result['state'] == 'decoded'


def test_absent_finance_and_base_literal_zero_stay_distinct_without_deep_field_reads(live_rent):
    m = live_rent;m['q'](m['club'] + 0x150, 0)
    missing = get(m)['annual_stadium_rent']
    assert missing['state'] == 'unavailable' and missing['reason'] == 'no_finance_record'
    assert missing['amount'] is missing['currency'] is None
    basic = m['typed']('club_finance_base', 0x38)
    m['q'](m['club'] + 0x150, basic)
    m['adapter_reads'].clear()
    result = get(m)['annual_stadium_rent']
    assert result['amount'] == 0 and result['currency'] == 'GBP' and result['period'] == 'year'
    assert result['reason'] == 'native_base_finance_literal_zero'
    assert (basic + 0x7F8, 4) not in m['adapter_reads']


@pytest.mark.parametrize('session', ['', None, True, 1, 'x' * 129])
def test_invalid_session_rejected_before_source_scope(live_rent, monkeypatch, session):
    m = live_rent
    monkeypatch.setattr(m['bridge'], '_read_scope', lambda *_: pytest.fail('Invalid session reached read scope'))
    with pytest.raises(BridgeError, match='session_id'):
        query.get_club_stadium_rent(m['bridge'], session)


@pytest.mark.parametrize('coach', ['', True, 1, 'x' * 257])
def test_invalid_coach_rejected_before_source_scope(live_rent, monkeypatch, coach):
    m = live_rent
    monkeypatch.setattr(m['bridge'], '_read_scope', lambda *_: pytest.fail('Invalid coach reached read scope'))
    with pytest.raises(BridgeError, match='coach_name'):get(m, coach)


def test_unknown_coach_or_session_fails_without_partial_amount(live_rent):
    with pytest.raises(BridgeError, match='Select one active coach'):get(live_rent, 'Another Coach')
    with pytest.raises(BridgeError, match='Unknown session'):
        query.get_club_stadium_rent(live_rent['bridge'], 'other-session')


@pytest.mark.parametrize('fault', ['human_type', 'human_person', 'human_cast', 'human_displacement',
                                  'contract_owner', 'contract_team', 'team_human', 'team_owner', 'team_index',
                                  'canonical_team', 'club_type', 'club_index', 'club_id', 'club_secondary',
                                  'canonical_club', 'club_backlink', 'finance_type', 'finance_pointer',
                                  'currency', 'native_leaf'])
def test_wrong_owner_type_membership_and_native_source_reject_whole_query(live_rent, fault):
    m = live_rent
    # Establish the attached career/club identity before a counterexample changes it.
    m['bridge']._world_state(m['bridge'].process, m['tables'])
    if fault == 'human_type':m['q'](m['manager'], m['base'] + world.TYPES['club'][0])
    if fault == 'human_person':m['q'](m['manager'] + 0x548, 0)
    if fault == 'human_cast':m['q'](m['base'] + prepared_tactics_source.PERSON_VTABLE + 0x6F0, 0)
    if fault == 'human_displacement':m['put'](m['base'] + world.TYPES['manager'][0] - 0x20, bytes(8))
    if fault == 'contract_owner':m['q'](m['contract'] + 8, m['manager'])
    if fault == 'contract_team':m['q'](m['contract'] + 0x18, m['team'] + 8)
    if fault == 'team_human':m['q'](m['team'] + 0x80, m['manager'] + 8)
    if fault == 'team_owner':m['q'](m['team'] + 0x30, m['owners'][2])
    if fault == 'team_index':m['put'](m['team'] + 8, struct.pack('<I', 1))
    if fault == 'canonical_team':m['vec'](m['headers']['teams'], list(reversed(m['team_addresses'])))
    if fault == 'club_type':m['q'](m['club'], m['base'] + world.TYPES['team'][0])
    if fault == 'club_index':m['put'](m['club'] + 8, struct.pack('<I', 1))
    if fault == 'club_id':m['put'](m['club'] + 12, bytes(4))
    if fault == 'club_secondary':m['put'](m['club'] + 16, struct.pack('<I', 999))
    if fault == 'canonical_club':m['vec'](m['headers']['clubs'], [m['owners'][2], m['club']])
    if fault == 'club_backlink':m['vec'](m['club'] + 0x18, [])
    if fault == 'finance_type':m['q'](m['finance'], m['base'] + world.TYPES['club'][0])
    if fault == 'finance_pointer':m['q'](m['club'] + 0x150, m['finance'] + 1)
    if fault == 'currency':m['put'](m['currency'] + 0x38, struct.pack('<f', 1.5))
    if fault == 'native_leaf':m['put'](m['base'] + 0xEB8768, b'\x01')
    with pytest.raises(BridgeError, match='no partial result'):get(m)


@pytest.mark.parametrize('fault', ['layout', 'plugin', 'date', 'save_count', 'career', 'team_human', 'club_owner',
                                  'club_identity', 'finance_pointer', 'amount', 'currency', 'native_leaf'])
def test_fresh_after_context_and_consumed_source_reject_late_change(live_rent, monkeypatch, fault):
    m = live_rent;original = m['bridge']._player_layout;calls = 0
    def layout(process):
        nonlocal calls
        calls += 1;tables = original(process)
        if calls == 2:
            if fault == 'layout':return (tables[0] + 8, *tables[1:])
            if fault == 'plugin':m['bridge'].plugin_identity = ('changed',)
            if fault == 'date':m['put'](m['base'] + world.CURRENT_DATE, struct.pack('<I', 2030 << 16 | 263))
            if fault == 'save_count':m['put'](m['game'] + 0xC8, struct.pack('<I', 419))
            if fault == 'career':m['q'](m['save'] + 0x28, m['text']('Another career'))
            if fault == 'team_human':m['q'](m['team'] + 0x80, m['manager'] + 8)
            if fault == 'club_owner':m['q'](m['team'] + 0x30, m['owners'][2])
            if fault == 'club_identity':m['put'](m['club'] + 16, struct.pack('<I', 999))
            if fault == 'finance_pointer':m['q'](m['club'] + 0x150, 0)
            if fault == 'amount':m['put'](m['finance'] + 0x7F8, struct.pack('<i', 975322))
            if fault == 'currency':m['put'](m['currency'] + 0x38, struct.pack('<f', 2.0))
            if fault == 'native_leaf':m['put'](m['base'] + 0xEB8768, b'\x01')
        return tables
    monkeypatch.setattr(m['bridge'], '_player_layout', layout)
    with pytest.raises(BridgeError, match='no partial result'):get(m)


@pytest.mark.parametrize('fault', ['process', 'plugin', 'world', 'date', 'save_count', 'amount', 'club_identity', 'human_contract'])
def test_final_lifetime_callback_cannot_hide_changed_context_or_consumed_bytes(live_rent, monkeypatch, fault):
    m = live_rent;original = m['bridge']._current;calls = 0
    def current(session):
        nonlocal calls
        calls += 1;process = original(session)
        if calls == 3:
            if fault == 'process':return replace(process, started='replacement')
            if fault == 'plugin':m['bridge'].plugin_identity = ('changed',)
            if fault == 'world':m['bridge'].world_identity = ('changed',)
            if fault == 'date':m['put'](m['base'] + world.CURRENT_DATE, struct.pack('<I', 2030 << 16 | 263))
            if fault == 'save_count':m['put'](m['game'] + 0xC8, struct.pack('<I', 419))
            if fault == 'amount':m['put'](m['finance'] + 0x7F8, struct.pack('<i', 1))
            if fault == 'club_identity':m['put'](m['club'] + 16, struct.pack('<I', 999))
            if fault == 'human_contract':m['q'](m['contract'] + 0x18, m['team'] + 8)
        return process
    monkeypatch.setattr(m['bridge'], '_current', current)
    with pytest.raises(BridgeError, match='no partial result'):get(m)


def test_read_scope_exit_failure_discards_positive(live_rent, monkeypatch):
    m = live_rent
    @contextmanager
    def scope(session):
        yield
        raise BridgeError('Process changed while closing read scope')
    monkeypatch.setattr(m['bridge'], '_read_scope', scope)
    with pytest.raises(BridgeError, match='closing read scope'):get(m)


def test_actual_mcp_schema_and_dispatch_return_real_core_amount(live_rent):
    m = live_rent
    async def check():
        mcp = FastMCP('Annual stadium rent adapter controls')
        tools.register_club_stadium_rent_tools(mcp, m['bridge'])
        tool, = await mcp.list_tools()
        assert tool.name == 'fm_get_club_stadium_rent'
        assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint and not tool.annotations.openWorldHint
        schema = tool.inputSchema
        assert set(schema['properties']) == {'session_id', 'coach_name'}
        assert schema['required'] == ['session_id']
        assert schema['properties']['session_id']['minLength'] == 1
        assert schema['properties']['session_id']['maxLength'] == 128
        assert 'per year' in tool.description and 'signed32' in tool.description
        assert 'weekly wages and transfer budgets' in tool.description
        content, result = await mcp.call_tool(tool.name,
            {'session_id': m['bridge'].session, 'coach_name': 'Test Coach'})
        assert result['annual_stadium_rent']['amount'] == 975321
        assert result['annual_stadium_rent']['period'] == 'year'
        assert result['club']['native_id'] == 688 and '975321' in content[0].text
    asyncio.run(check())


def test_stable_distinct_secondary_club_identity_is_valid_not_missing(live_rent):
    m = live_rent;m['put'](m['club'] + 16, struct.pack('<I', 999))
    result = get(m)
    assert result['club']['native_id'] == 688 and result['club']['random_id'] == 999
    assert result['annual_stadium_rent']['club_native_identity']['raw_secondary_id'] == 999
    assert result['annual_stadium_rent']['amount'] == 975321


def add_second_managed_club(m):
    """Build a second genuine synthetic canonical HUMAN/TEAM/CLUB, not a selected result stub."""
    human = m['typed']('manager', 0x568)
    m['typed_at'](human + 0x548, prepared_tactics_source.PERSON_VTABLE,
                  world.TYPES['manager'][1], -0x548)
    for off, value in ((0x458, 'Other'), (0x460, 'Coach')):
        handle = m['allocate'](8);m['q'](handle, m['text'](value));m['q'](human + off, handle)
    club = m['typed']('club', 0x170);m['put'](club + 8, struct.pack('<III', 3, 999, 1001))
    m['q'](club + 0xC0, m['text']('Other United'));m['q'](club + 0xC8, m['text']('Other'))
    finance = m['typed']('club_finance', 0x840);m['q'](club + 0x150, finance)
    m['put'](finance + 0x7F8, struct.pack('<i', 700001))
    team = m['typed']('team', 0xB8);m['put'](team + 8, struct.pack('<III', 3, 777, 779))
    m['q'](team + 0x30, club);m['q'](team + 0x80, human);m['put'](team + 0x28, bytes(2))
    m['vec'](club + 0x18, [team])
    m['vec'](m['headers']['clubs'], m['owners'] + [club])
    m['vec'](m['headers']['teams'], m['team_addresses'] + [team])
    contract = m['allocate'](32);m['q'](human + 0x4B0, contract)
    for off, value in ((8, human + 0x548), (0x10, team), (0x18, team)):m['q'](contract + off, value)
    user = m['allocate'](0x150);m['q'](user + 0x148, human);m['vec'](user + 0xC0, [human])
    info = world.pointer(m['read'], m['game'] + 0x58)
    users = world.vector(m['read'], info, 64);m['vec'](info, list(users) + [user])
    return human, team, club, finance


def test_multiple_active_coaches_require_selection_and_return_selected_canonical_club(live_rent):
    m = live_rent;add_second_managed_club(m)
    with pytest.raises(BridgeError, match='Select one active coach'):get(m)
    first = get(m, 'Test Coach');second = get(m, ' other  COACH ')
    assert first['club']['native_id'] == 688 and first['annual_stadium_rent']['amount'] == 975321
    assert second['coach'] == 'Other Coach'
    assert second['team']['native_id'] == 777
    assert second['club']['native_id'] == 999 and second['club']['random_id'] == 1001
    assert second['annual_stadium_rent']['amount'] == 700001
    assert second['annual_stadium_rent']['club_native_identity'] == {
        'database_index': 3, 'native_id': 999, 'raw_secondary_id': 1001}
    with pytest.raises(BridgeError, match='Select one active coach'):get(m, 'Unknown Coach')
