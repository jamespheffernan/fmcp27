"""Contract and current-team relationships, including stale and misleading links."""
import struct

import pytest

from fm_live_mcp import players, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_players import memory, reader, TABLES
from test_world import world_memory


@pytest.fixture
def club_memory(world_memory):
    m = world_memory
    player = m['allocate'](players.SIZE)
    m['q'](player,m['base']+players.RVA[0])
    contract = m['typed']('full_contract', 0xC8)
    m['q'](player + 0x2F0, contract)
    m['q'](contract + 8, player + 0x388)
    m['q'](contract + 0x10, m['team'])
    m['q'](contract + 0x18, m['team'])
    m['q'](player + 0x128, m['team'])
    # An unrelated national/former team must never determine club membership.
    m['q'](player + 0x130, 0xDEADBEEF)
    borrower = m['typed']('club', 0x170)
    m['put'](borrower + 0xC, struct.pack('<II', 999, 999))
    m['q'](borrower + 0xC0, m['text']('Borrower United'))
    m['q'](borrower + 0xC8, m['text']('Borrower'))
    loan_team = m['typed']('team', 0xB8)
    m['q'](loan_team + 0x30, borrower)
    m['vec'](borrower + 0x18, [loan_team])
    loan = m['typed']('loan_contract', 0xC8)
    m['q'](loan + 8, player + 0x388)
    m['q'](loan + 0x10, loan_team)
    m['q'](loan + 0x18, loan_team)
    holder = m['allocate'](8)
    m['q'](holder, loan)
    def enable_loan():
        m['q'](player + 0x128, loan_team)
        m['q'](player + 0x2F8, holder)
    m.update(player=player, player_contract=contract, borrower=borrower,
             loan=loan, loan_team=loan_team, holder=holder, enable_loan=enable_loan)
    return m


def resolve(m):
    snapshot = world.ReadSet(m['read'])
    result = world.player_clubs(snapshot, m['base'], m['player'])
    snapshot.verify()
    return result


def test_same_club_ignores_former_or_national_team(club_memory):
    result = resolve(club_memory)
    assert result['on_loan'] is False
    assert result['contract_club']['name'] == 'Test United'
    assert result['current_club'] == result['contract_club']


def test_loan_requires_contract_backlinks(club_memory):
    m = club_memory
    m['enable_loan']()
    result = resolve(m)
    assert result['on_loan'] is True
    assert result['current_club']['name'] == 'Borrower United'
    assert result['contract_club']['name'] == 'Test United'


@pytest.mark.parametrize('fault', ['owner', 'contract_team', 'loan_owner',
                                  'loan_type', 'club_backlink', 'primary_getter','virtual_adjustment','loan_getter','holder'])
def test_inconsistent_clubs_fail_closed(club_memory, fault):
    m = club_memory
    m['enable_loan']()
    q = m['q']
    if fault == 'owner': q(m['player_contract'] + 8, m['player'])
    if fault == 'contract_team': q(m['player_contract'] + 0x18, m['loan_team'])
    if fault == 'loan_owner': q(m['loan'] + 8, m['player'])
    if fault == 'loan_type': q(m['loan'], m['base'] + world.TYPES['full_contract'][0])
    if fault == 'club_backlink': m['vec'](m['borrower'] + 0x18, [])
    if fault == 'primary_getter': q(m['base']+players.RVA[0]+93*8,0)
    if fault == 'virtual_adjustment': q(m['base']+players.RVA[0]-0x20,0)
    if fault == 'loan_getter': q(m['base']+world.TYPES['loan_contract'][0]+18*8,0)
    if fault == 'holder': q(m['player']+0x2F8,7)
    with pytest.raises(ValueError): resolve(m)


def test_current_parent_and_loan_clubs_are_independent(club_memory):
    m=club_memory
    m['enable_loan']()
    m['q'](m['player']+0x128,m['team'])
    r=resolve(m)
    assert r['current_club']==r['contract_club']
    assert r['loan_club']['name']=='Borrower United' and r['on_loan']
    m['q'](m['holder'],0)
    r=resolve(m)
    assert not r['on_loan'] and r['loan_status_reason']=='empty_current_slot'
    m['q'](m['player']+0x128,m['loan_team'])
    m['q'](m['player']+0x2F8,0)
    r=resolve(m)
    assert r['current_club']!=r['contract_club'] and not r['on_loan']


def test_missing_contract_team_and_basic_contract_are_supported(club_memory):
    m=club_memory;m['enable_loan']()
    m['q'](m['player']+0x2F0,0)
    r=resolve(m)
    assert r['contract_club'] is None and r['contract_club_state']=='no_contract' and r['on_loan']
    basic=m['typed']('basic_contract',0x30)
    m['q'](basic+8,m['player']+0x388);m['q'](m['player']+0x2F0,basic)
    assert resolve(m)['contract_club_state']=='no_contract_team'
    m['q'](basic+0x10,m['team']);m['q'](basic+0x18,m['team'])
    assert resolve(m)['contract_club']['name']=='Test United'
    m['q'](m['player']+0x128,0)
    assert resolve(m)['current_club'] is None


def test_reserve_team_pairs_resolve_same_club(club_memory):
    m=club_memory
    second=m['typed']('team',0xB8);m['q'](second+0x30,m['club'])
    m['vec'](m['club']+0x18,[m['team'],second]);m['q'](m['player_contract']+0x18,second)
    assert resolve(m)['contract_club']['name']=='Test United'


@pytest.mark.parametrize('kind,linked,team_flag,expected',[(18,True,0,False),(18,False,0,True),
    (17,True,0,True),(18,True,1,True),(18,True,255,True)])
def test_native_affiliation_exception(club_memory,kind,linked,team_flag,expected):
    m=club_memory;m['enable_loan']()
    link=m['allocate'](0x38);m['q'](link+8,m['borrower'] if linked else m['club'])
    m['put'](link+0x30,bytes([kind]));m['vec'](m['borrower']+0x118,[link])
    m['put'](m['loan_team']+0x2F,bytes([team_flag]))
    r=resolve(m)
    assert r['on_loan'] is expected
    assert r['loan_status_reason']==('loan_contract' if expected else 'suppressed_by_affiliation_kind_18')
    assert r['loan_club']['name']=='Borrower United' and not r['eligibility_evaluated']


def test_trial_auxiliary_contract_is_not_a_loan(club_memory):
    m=club_memory;m['enable_loan']()
    trial=m['typed']('trial_contract',0x30);m['q'](trial+8,m['player']+0x388)
    m['q'](m['holder'],trial)
    r=resolve(m)
    assert r['loan_status_reason']=='trial_contract' and not r['on_loan'] and r['loan_club'] is None
    m['q'](trial+8,m['player'])
    with pytest.raises(ValueError,match='Trial contract owner'):resolve(m)


def test_combined_player_uses_its_virtual_base(club_memory):
    m=club_memory
    player=m['allocate'](0x4A0);m['q'](player,m['base']+players.STAFF_RVA[0])
    m['q'](player+0x480-0x98,m['player_contract']);m['q'](m['player_contract']+8,player+0x480)
    m['q'](player+0x128,m['team'])
    r=world.player_clubs(m['read'],m['base'],player,player_staff=True)
    assert r['contract_club']==r['current_club'] and not r['on_loan']


def test_loan_without_team_uses_native_true_branch(club_memory):
    m=club_memory;m['enable_loan']()
    m['q'](m['loan']+0x10,0);m['q'](m['loan']+0x18,0)
    r=resolve(m)
    assert r['on_loan'] and r['loan_club'] is None


@pytest.mark.parametrize('fault',['kind','linked_club','vector','dispatch'])
def test_native_status_inputs_are_rechecked(club_memory,fault):
    m=club_memory;m['enable_loan']()
    link=m['allocate'](0x38);m['q'](link+8,m['borrower']);m['put'](link+0x30,b'\x12')
    m['vec'](m['borrower']+0x118,[link])
    snap=world.ReadSet(m['read'])
    assert not world.player_clubs(snap,m['base'],m['player'])['on_loan']
    if fault=='kind':m['put'](link+0x30,b'\x11')
    elif fault=='linked_club':m['q'](link+8,m['club'])
    elif fault=='vector':m['vec'](m['borrower']+0x118,[])
    else:m['q'](m['base']+players.RVA[0]+93*8,0)
    with pytest.raises(ValueError,match='changed'):snap.verify()


def test_invalid_affiliation_vector_and_trial_getter_fail(club_memory):
    m=club_memory;m['enable_loan']()
    m['put'](m['borrower']+0x118,struct.pack('<QQQ',4096,4097,4104))
    with pytest.raises(ValueError,match='vector'):resolve(m)
    trial=m['typed']('trial_contract',0x30);m['q'](trial+8,m['player']+0x388);m['q'](m['holder'],trial)
    m['q'](m['base']+world.TYPES['trial_contract'][0]+18*8,0)
    with pytest.raises(ValueError,match='getter'):resolve(m)


def test_cached_team_bytes_still_rechecked(club_memory):
    m = club_memory
    snapshot = world.ReadSet(m['read'])
    cache = {}
    world.player_clubs(snapshot, m['base'], m['player'], cache)
    m['q'](m['team'] + 0x30, m['borrower'])
    world.player_clubs(snapshot, m['base'], m['player'], cache)
    with pytest.raises(ValueError, match='changed'): snapshot.verify()


def test_club_links_changing_during_read_are_rejected(club_memory):
    m = club_memory
    snapshot = world.ReadSet(m['read'])
    world.player_clubs(snapshot, m['base'], m['player'])
    m['enable_loan']()
    with pytest.raises(ValueError, match='changed'): snapshot.verify()


def test_club_read_option_preserves_default_and_rechecks_identity(bridge, monkeypatch, memory):
    monkeypatch.setattr(bridge, '_player_layout', lambda p: TABLES)
    monkeypatch.setattr(bridge, '_read_memory', lambda p,a,n: reader(memory)(a,n))
    record, identity = players.decode(reader(memory), 0x1000, TABLES)
    bridge.player_refs['player'] = {'address': 0x1000, 'identity': identity, 'tables': TABLES}
    calls = []
    def clubs(read, base, address, cache=None):
        calls.append(address)
        return {'on_loan': True, 'current_club': {'name': 'Borrower'}}
    monkeypatch.setattr(world, 'player_clubs', clubs)
    assert 'clubs' not in bridge.get_player(bridge.session, 'player')['player']
    assert calls == []
    assert bridge.get_player(bridge.session, 'player', True)['player']['clubs']['on_loan']
    struct.pack_into('<II', memory, 0x1394, 678, 678)
    with pytest.raises(BridgeError, match='identity changed'):
        bridge.get_player(bridge.session, 'player', True)
    assert 'player' not in bridge.player_refs


@pytest.mark.parametrize('value', [1, 'true', None])
def test_invalid_club_option_rejected_before_reads(bridge, monkeypatch, value):
    monkeypatch.setattr(bridge, '_player_layout', lambda p: pytest.fail('read before validation'))
    with pytest.raises(BridgeError, match='boolean'): bridge.get_player(bridge.session, 'p', value)
    with pytest.raises(BridgeError, match='boolean'): bridge.get_managed_squad(bridge.session, include_clubs=value)


def test_failed_squad_club_check_publishes_no_player_refs(bridge, monkeypatch, memory):
    record = {'coaches': [{'name': 'Test Coach', 'club': {'name': 'Test'}, 'team_address': 0x4000}]}
    monkeypatch.setattr(bridge, '_player_layout', lambda p: TABLES)
    snapshot = world.ReadSet(reader(memory))
    monkeypatch.setattr(bridge, '_world_state', lambda *a: (snapshot, record, ()))
    # The loan-failure projection uses synthetic fields, not a runtime image.
    bridge.world_identity = ()
    bridge.plugin_identity = ('isolated-loan-fields', b'fixture runtime')
    monkeypatch.setattr(players, 'verify_runtime', lambda *_: TABLES)
    struct.pack_into('<QQQ', memory, 0x4038, 0x4100, 0x4108, 0x4108)
    struct.pack_into('<Q', memory, 0x4100, 0x1000)
    def reject(*args):
        raise ValueError('Loan contract disagrees')
    monkeypatch.setattr(world, 'player_clubs', reject)
    with pytest.raises(BridgeError, match='no partial roster'):
        bridge.get_managed_squad(bridge.session, include_clubs=True)
    assert bridge.player_refs == {}
