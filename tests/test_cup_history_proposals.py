import struct
import pytest
from fm_live_mcp import cup_history as source,teams,world
from test_world import world_memory
from test_players import memory
from test_database import database_memory
from test_player_clubs import club_memory


@pytest.fixture
def candidate(database_memory):
    m=club_memory.__wrapped__(database_memory)
    for kind in ('team','club'):
        m['q'](m['base']+world.TYPES[kind][0]+24,m['base']+teams.GETTERS[kind])
    m['put'](m['base']+teams.LOOKUP_MODE,b'\x01')
    m['vec'](m['headers']['teams'],[m['team'],m['loan_team']])
    m['vec'](m['headers']['clubs'],[m['club'],m['borrower']])
    for address,index,native in ((m['team'],0,688),(m['loan_team'],1,999),
                                 (m['club'],0,688),(m['borrower'],1,999)):
        m['put'](address+8,struct.pack('<III',index,native,native))
    return m


def resolve(m,kind='actual'):
    return source.candidate_context(m['read'],m['base'],m['player'],kind,m['team'])


def test_actual_same_club_nonloan_supported_without_changing_team(candidate):
    m=candidate;before=m['read'](m['player']+0x128,8)
    row=resolve(m)
    assert row['state']=='compatible' and row['club_links']['on_loan']is False
    assert row['selection_changed']is False and row['match_eligibility']=='not_assessed'
    assert m['read'](m['player']+0x128,8)==before


def test_real_typed_nonclub_and_loan_are_not_calibrated(candidate):
    m=candidate;m['q'](m['player']+0x128,m['loan_team'])
    assert resolve(m)['reason']=='proposed_player_current_club_differs_from_managed_club'
    m['enable_loan']()
    row=resolve(m)
    assert row['state']=='incompatible' and row['club_links']['on_loan']is True
    assert row['reason']=='proposed_player_on_loan_not_calibrated'


def test_supported_profile_does_not_include_virtual_or_combined(candidate):
    for kind in ('virtual','player_staff','human_manager'):
        assert resolve(candidate,kind)['state']=='incompatible'


def test_candidate_and_parent_teams_must_be_canonical(candidate):
    m=candidate
    m['vec'](m['headers']['teams'],[m['loan_team'],m['loan_team']])
    with pytest.raises(ValueError):resolve(m)


def test_missing_contract_and_parent_club_difference_not_calibrated(candidate):
    m=candidate;m['q'](m['player_contract']+0x10,m['loan_team']);m['q'](m['player_contract']+0x18,m['loan_team'])
    assert resolve(m)['reason']=='proposed_player_parent_contract_club_differs'
    m['q'](m['player']+0x2f0,0)
    assert resolve(m)['reason']=='proposed_player_main_contract_unavailable'
