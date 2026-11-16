"""Real typed memory controls for club location, separate from eligibility."""
import struct

import pytest

from fm_live_mcp import live_club_location, players, world
from test_database import database_memory
from test_player_clubs import club_memory
from test_players import memory
from test_world import world_memory


@pytest.fixture
def location_memory(club_memory, database_memory):
    m = club_memory
    for address, index, native_id, secondary in (
        (m['club'], 0, 688, 688), (m['borrower'], 1, 999, 0),
        (m['team'], 0, 101, 101), (m['loan_team'], 1, 102, 102),
    ):
        m['put'](address + 8, struct.pack('<III', index, native_id, secondary))
    m['vec'](m['headers']['clubs'], [m['club'], m['borrower']])
    m['vec'](m['headers']['teams'], [m['team'], m['loan_team']])
    return m


def resolve(m, *, kind='actual', read=None):
    snapshot = world.ReadSet(m['read'] if read is None else read)
    result = live_club_location.resolve(snapshot, m['base'], m['player'], kind, m['club'])
    snapshot.verify()
    return result


def test_current_club_uses_canonical_identity(location_memory):
    m = location_memory
    result = resolve(m)
    assert result['location_state'] == 'at_managed_club'
    assert result['at_managed_club'] is True
    assert result['current_club_identity'] == result['managed_club_identity']
    assert result['contract_club_identity'] == result['managed_club_identity']
    assert result['loan_club_identity'] is None
    assert result['clubs']['eligibility_evaluated'] is False


def test_duplicate_club_names_do_not_make_away_player_present(location_memory):
    m = location_memory
    m['q'](m['borrower'] + 0xC0, m['text']('Test United'))
    m['q'](m['borrower'] + 0xC8, m['text']('Test'))
    m['enable_loan']()
    result = resolve(m)
    assert result['clubs']['current_club'] == result['clubs']['contract_club']
    assert result['at_managed_club'] is False
    assert result['location_state'] == 'away_from_managed_club'
    assert result['current_club_identity'] == {'database_index': 1, 'native_id': 999, 'random_id': 0}


def test_alias_names_do_not_change_same_club_identity(location_memory):
    m = location_memory
    m['q'](m['club'] + 0xC0, m['text']('An alias'))
    m['q'](m['club'] + 0xC8, m['text']('Alias'))
    assert resolve(m)['at_managed_club'] is True


def test_incoming_loan_is_included_by_current_club_not_contract(location_memory):
    m = location_memory
    m['enable_loan']()
    for contract, team in ((m['player_contract'], m['loan_team']), (m['loan'], m['team'])):
        m['q'](contract + 0x10, team)
        m['q'](contract + 0x18, team)
    m['q'](m['player'] + 0x128, m['team'])
    result = resolve(m)
    assert result['clubs']['on_loan'] is True
    assert result['contract_club_identity']['database_index'] == 1
    assert result['loan_club_identity'] == result['managed_club_identity']
    assert result['at_managed_club'] is True


def test_no_current_team_is_unknown_even_with_home_contract(location_memory):
    m = location_memory
    m['q'](m['player'] + 0x128, 0)
    result = resolve(m)
    assert result['location_state'] == 'current_club_unavailable'
    assert result['at_managed_club'] is None
    assert result['current_club_identity'] is None
    assert result['contract_club_identity'] == result['managed_club_identity']


@pytest.mark.parametrize('fault', ['club_slot', 'club_index', 'team_slot', 'team_index', 'reverse_link', 'native_id'])
def test_invalid_membership_rejects_even_with_matching_names(location_memory, fault):
    m = location_memory
    m['enable_loan']()
    if fault == 'club_slot': m['vec'](m['headers']['clubs'], [m['club'], m['club']])
    if fault == 'club_index': m['put'](m['borrower'] + 8, struct.pack('<I', 0))
    if fault == 'team_slot': m['vec'](m['headers']['teams'], [m['team'], m['team']])
    if fault == 'team_index': m['put'](m['loan_team'] + 8, struct.pack('<I', 0))
    if fault == 'reverse_link': m['vec'](m['borrower'] + 0x18, [])
    if fault == 'native_id': m['put'](m['borrower'] + 0xC, bytes(4))
    with pytest.raises(ValueError): resolve(m)


@pytest.mark.parametrize('field', ['team_pointer', 'club_pointer', 'club_identity', 'club_table'])
def test_late_source_drift_rejected_by_caller_readset(location_memory, field):
    m = location_memory
    snapshot = world.ReadSet(m['read'])
    assert live_club_location.resolve(snapshot, m['base'], m['player'], 'actual', m['club'])['at_managed_club']
    if field == 'team_pointer': m['q'](m['player'] + 0x128, m['loan_team'])
    if field == 'club_pointer': m['q'](m['team'] + 0x30, m['borrower'])
    if field == 'club_identity': m['put'](m['club'] + 0x10, struct.pack('<I', 12345))
    if field == 'club_table': m['vec'](m['headers']['clubs'], [m['borrower'], m['club']])
    with pytest.raises(ValueError, match='changed'): snapshot.verify()


def test_virtual_does_not_read_player_or_generate_profile(location_memory):
    m = location_memory
    def guarded(address, count):
        assert not (address <= m['player'] < address + count or m['player'] <= address < m['player'] + players.SIZE)
        return m['read'](address, count)
    result = resolve(m, kind='virtual', read=guarded)
    assert result['location_state'] == 'unsupported_record_kind'
    assert result['at_managed_club'] is None and result['clubs'] is None


def test_unknown_record_kind_rejects(location_memory):
    with pytest.raises(ValueError, match='record kind'):
        resolve(location_memory, kind='invented')


def test_combined_player_uses_its_distinct_person_offset(location_memory):
    m = location_memory
    m['q'](m['player'], m['base'] + players.STAFF_RVA[0])
    m['q'](m['player'] + 0x3E8, m['player_contract'])
    m['q'](m['player_contract'] + 8, m['player'] + 0x480)
    result = resolve(m, kind='player_staff')
    assert result['at_managed_club'] is True
    assert result['contract_club_identity'] == result['managed_club_identity']


def test_same_native_id_does_not_override_distinct_canonical_club(location_memory):
    m = location_memory
    m['put'](m['borrower'] + 0xC, struct.pack('<II', 688, 688))
    m['enable_loan']()
    result = resolve(m)
    assert result['current_club_identity']['native_id'] == result['managed_club_identity']['native_id']
    assert result['current_club_identity']['database_index'] != result['managed_club_identity']['database_index']
    assert result['at_managed_club'] is False


def test_away_location_is_not_derived_from_on_loan_flag(location_memory):
    m = location_memory
    m['q'](m['player'] + 0x128, m['loan_team'])
    result = resolve(m)
    assert result['clubs']['on_loan'] is False
    assert result['at_managed_club'] is False


def test_contracts_cannot_hide_noncanonical_second_team(location_memory):
    m = location_memory
    second = m['typed']('team', 0xB8)
    m['q'](second + 0x30, m['club'])
    m['put'](second + 8, struct.pack('<III', 0, 321, 321))
    m['vec'](m['club'] + 0x18, [m['team'], second])
    m['q'](m['player_contract'] + 0x18, second)
    with pytest.raises(ValueError, match='team is no longer'):
        resolve(m)
