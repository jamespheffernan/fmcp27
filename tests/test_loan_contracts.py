import struct

import pytest

from fm_live_mcp import loan_contracts as loans, players, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import database_memory, bind, receipt
from test_players import memory
from test_world import world_memory
from test_virtual import virtual_memory
from test_competitions import competition_fixture


def loan_fixture(m, address=0x1000, offset=0x388):
    person = address + offset
    main = m['typed']('full_contract', 0xC8)
    loan = m['typed']('loan_contract', 0x100)
    holder = m['allocate'](8)
    m['q'](holder, loan)
    m['q'](person - 0x98, main)
    m['q'](person - 0x90, holder)
    borrower = m['typed']('club', 0x170)
    m['put'](borrower + 0xC, struct.pack('<II', 999, 999))
    m['q'](borrower + 0xC0, m['text']('Borrower United'))
    m['q'](borrower + 0xC8, m['text']('Borrower'))
    team = m['typed']('team', 0xB8)
    m['q'](team + 0x30, borrower)
    m['vec'](borrower + 0x18, [team])
    for contract, target in ((main, m['team']), (loan, team)):
        m['q'](contract + 8, person)
        m['q'](contract + 0x10, target)
        m['q'](contract + 0x18, target)
    m['q'](address + 0x128, team)
    for slot, getter in loans.GETTERS.items():
        m['q'](m['base'] + world.TYPES['loan_contract'][0] + slot * 8, m['base'] + getter)
    m['put'](loan + 0x44, struct.pack('<II', 2030 << 16 | 207 | 0x7C00, 2031 << 16 | 181))
    for i, (field, (at, _)) in enumerate(loans.CASH_FIELDS.items()):
        m['put'](loan + at, struct.pack('<i', i * 1000))
    m['put'](loan + 0xC0, struct.pack('<ii', 500000, -1))
    m['put'](loan + 0xF7, struct.pack('<bb', 25, 5))
    m.update(player=address, person=person, offset=offset, main=main, loan=loan,
             holder=holder, borrower=borrower, loan_team=team)
    return m


@pytest.fixture
def loan_record(database_memory):
    return loan_fixture(database_memory)


def decode(m):
    return loans.decode(m['read'], m['base'], m['player'], m['offset'], 'GBP')


def components(m, entries):
    header = m['allocate'](24)
    data = m['allocate'](max(8, len(entries) * 8))
    for i, (amount, parameter) in enumerate(entries):
        m['put'](data + i * 8, struct.pack('<ib3x', amount, parameter))
    m['put'](header, struct.pack('<QQQ', data, data + len(entries)*8, data + len(entries)*8))
    m['q'](m['loan'] + 0x68, header)
    return header, data


def test_dates_amounts_ownership_and_native_counters(loan_record):
    m = loan_record
    r = decode(m)
    assert r['state'] == 'decoded' and r['currency'] == 'GBP'
    assert r['parent_club']['name'] == 'Test United' and r['parent_club_state'] == 'decoded'
    assert r['borrowing_club']['name'] == 'Borrower United'
    assert r['current_club_relationship'] == 'same_as_borrowing_club'
    assert r['signed_date'] == '2030-07-26' and r['end_date'] == '2031-06-30'
    assert r['playing_weekly_wage_gbp'] == {'amount': 0, 'state': 'stored'}
    assert r['unused_weekly_wage_gbp']['amount'] == 1000
    assert r['playing_monthly_fee_gbp']['amount'] == 2000
    assert r['unused_monthly_fee_gbp']['amount'] == 3000
    assert r['future_buy_back_fee_gbp']['amount'] == 4000
    assert r['purchase']['trigger'] == 'after_matches'
    assert r['purchase']['match_threshold'] == 25 and r['purchase']['matches_played'] == 5
    assert r['purchase']['trigger_satisfied'] is None and not r['eligibility_evaluated']


@pytest.mark.parametrize('threshold,competition,trigger', [(100,-1,'mandatory_future_fee'),
    (0,-1,'after_matches'), (127,-1,'after_matches'), (-1,-1,'optional_future_fee'),
    (-2,-1,'optional_future_fee'), (-128,0,'competition_condition')])
def test_purchase_trigger_branches(loan_record, threshold, competition, trigger):
    m = loan_record
    if competition >= 0:
        competition_fixture(m)
        m['put'](m['loan']+0x90,struct.pack('<iiiB',-1,-1,-1,0))
    m['put'](m['loan'] + 0xF7, struct.pack('<bb', threshold, -1))
    m['put'](m['loan'] + 0xC4, struct.pack('<i', competition))
    result = decode(m)['purchase']
    assert result['trigger'] == trigger
    assert result['matches_played'] is None and result['native_matches_played'] == -1
    assert result['native_match_threshold'] == threshold
    assert result['match_threshold'] == (threshold if trigger == 'after_matches' else None)


@pytest.mark.parametrize('kind,achievement',[(0,'win_competition'),(3,'promotion'),
    (6,'avoid_relegation'),(10,'qualify_for_competition'),(14,'win_competition'),(20,'avoid_fine')])
def test_competition_achievements_and_named_targets(loan_record,kind,achievement):
    m=competition_fixture(loan_record)
    m['put'](m['loan']+0xC4,struct.pack('<i',0))
    m['put'](m['loan']+0xF7,struct.pack('<b',-1))
    m['put'](m['loan']+0x90,struct.pack('<iiiB',1 if kind==10 else -1,-1,-1,kind))
    purchase=decode(m)['purchase'];r=purchase['competition_condition']
    assert purchase['trigger']=='competition_condition'
    assert r['state']=='decoded' and r['achievement']==achievement
    assert r['competition']['name']=='Test Premier Division'
    assert r['target_competition']==(None if kind!=10 else
        {'native_id':101,'random_id':None,'database_index':1,'name':'Test Continental Cup','short_name':'Test Continental Cup',
         'abbreviation':'TST','name_source':'stored_native_strings'})
    assert r['trigger_satisfied'] is None and purchase['trigger_satisfied'] is None


@pytest.mark.parametrize('kind,target,stage,state',[(1,-1,42,'achievement_not_decoded'),
    (255,-1,-1,'achievement_not_decoded'),(10,-1,-1,'qualification_target_unavailable'),
    (0,-1,42,'stage_names_not_decoded')])
def test_incomplete_competition_conditions_stay_explicit(loan_record,kind,target,stage,state):
    m=competition_fixture(loan_record)
    m['put'](m['loan']+0xC4,struct.pack('<i',0))
    m['put'](m['loan']+0x90,struct.pack('<iiiB',target,stage,-1,kind))
    r=decode(m)['purchase']['competition_condition']
    assert r['state']==state and r['native_achievement_code']==kind
    assert r['native_stage_name_ids']==[stage,-1]
    assert r['trigger_satisfied'] is None


def test_native_future_fee_sums_components_once_with_signed_guards(loan_record):
    m = loan_record
    components(m, [(100,12), (200,1), (300,0), (400,-1), (0,12), (-50,12)])
    result = decode(m)['purchase']
    assert result['future_fee_gbp']['amount'] == 500300
    assert result['initial_future_fee_gbp']['amount'] == 500000
    assert [r['included_in_native_total'] for r in result['additional_fee_components']] == [True,True,False,False,False,False]
    m['put'](m['loan'] + 0xC0, struct.pack('<i', 0x7FFFFFFF))
    assert decode(m)['purchase']['future_fee_gbp'] == {'amount': None, 'state': 'unavailable_native_integer_overflow'}


def test_absence_zero_and_short_circuit_do_not_conflate(loan_record):
    m = loan_record
    for at,_ in loans.CASH_FIELDS.values(): m['put'](m['loan'] + at, struct.pack('<i', -1))
    m['put'](m['loan'] + 0xC0, struct.pack('<i', -1))
    m['q'](m['loan'] + 0x68, 123)  # Native getter does not access components in this branch.
    r = decode(m)
    assert all(r[k] == {'amount': None, 'state': 'not_specified'} for k in loans.CASH_FIELDS)
    assert r['purchase']['trigger'] == 'no_future_fee_specified'
    assert r['purchase']['fee_components_state'] == 'not_evaluated_without_initial_fee'
    m['q'](m['holder'], 0)
    assert decode(m)['state'] == 'no_current_loan'
    m['q'](m['person'] - 0x90, 0)
    assert decode(m)['state'] == 'no_current_loan'


@pytest.mark.parametrize('slot', list(loans.GETTERS))
def test_changed_native_dispatch_is_rejected(loan_record, slot):
    m = loan_record
    m['q'](m['base'] + world.TYPES['loan_contract'][0] + slot*8, 0)
    with pytest.raises(ValueError, match='getter'): decode(m)


@pytest.mark.parametrize('at', [0x20,0xC0,0xC8,0xCC,0xD0,0xD4])
def test_unrecognized_negative_cash_is_rejected(loan_record, at):
    m = loan_record
    m['put'](m['loan'] + at, struct.pack('<i', -2))
    with pytest.raises(ValueError, match='negative'): decode(m)


@pytest.mark.parametrize('fault', ['owner','type','club_backlink','paired_club','date','holder',
    'vector_pointer','misalignment','reversed','capacity','huge'])
def test_invalid_loan_links_dates_and_vectors_fail_closed(loan_record, fault):
    m = loan_record
    header,data = components(m,[(50,1)])
    if fault == 'owner': m['q'](m['loan']+8, m['player'])
    elif fault == 'type': m['q'](m['loan'], m['base']+world.TYPES['full_contract'][0])
    elif fault == 'club_backlink': m['vec'](m['borrower']+0x18, [])
    elif fault == 'paired_club': m['q'](m['loan']+0x18, m['team'])
    elif fault == 'date': m['put'](m['loan']+0x48, struct.pack('<I',2031<<16|366))
    elif fault == 'holder': m['q'](m['person']-0x90, 9)
    elif fault == 'vector_pointer': m['q'](m['loan']+0x68,9)
    elif fault == 'misalignment': m['q'](header+8,data+7)
    elif fault == 'reversed': m['q'](header+8,data-8)
    elif fault == 'capacity': m['q'](header+16,data)
    else: m['q'](header+16,data+(loans.MAX_FEE_COMPONENTS+1)*8)
    with pytest.raises(ValueError): decode(m)


def test_parent_absence_and_current_club_differences_stay_explicit(loan_record):
    m = loan_record
    m['q'](m['main']+0x10,0);m['q'](m['main']+0x18,0)
    assert decode(m)['parent_club_state'] == 'no_main_contract_team'
    m['q'](m['person']-0x98,0)
    assert decode(m)['parent_club_state'] == 'no_main_contract'
    m['q'](m['player']+0x128,m['team'])
    r = decode(m)
    assert r['current_club']['name'] == 'Test United'
    assert r['current_club_relationship'] == 'differs_from_borrowing_club'
    m['q'](m['player']+0x128,0)
    assert decode(m)['current_club_relationship'] == 'no_current_team'


def test_different_teams_within_same_club_and_combined_layout(loan_record):
    m = loan_record
    extra = m['typed']('team',0xB8)
    m['q'](extra+0x30,m['club'])
    m['vec'](m['club']+0x18,[m['team'],extra])
    m['q'](m['main']+0x18,extra)
    assert decode(m)['parent_club_state'] == 'decoded'
    # Relocate PERSON_DATA/owner pointers as in the combined native player/staff layout.
    m['q'](m['player']+0x480-0x98,m['main']);m['q'](m['player']+0x480-0x90,m['holder'])
    m['q'](m['main']+8,m['player']+0x480);m['q'](m['loan']+8,m['player']+0x480)
    m['offset'] = 0x480
    assert decode(m)['state'] == 'decoded'


@pytest.mark.parametrize('fault', ['amount','date','counter','holder','component','membership','save','base_flags','override_flags',
    'competition_index','condition_kind','condition_target','stage_id','competition_name','competition_member','lookup_mode'])
def test_public_query_rejects_mutation_and_invalidates_reference(bridge, monkeypatch, loan_record, fault):
    m = loan_record
    bind(bridge,monkeypatch,m)
    monkeypatch.setattr(bridge,'_run',lambda *a:receipt())
    monkeypatch.setattr(loans.wages,'base_currency',lambda *a:'GBP')
    competition_fixture(m)
    m['put'](m['loan']+0xC4,struct.pack('<i',0))
    m['put'](m['loan']+0x90,struct.pack('<iiiB',1,-1,-1,10))
    _,data = components(m,[(50,1)])
    ref = bridge.find_save_players(bridge.session,'Test')['players'][0]['player_ref']
    first = bridge.get_loan_contract(bridge.session,ref)
    assert first['loan_contract']['purchase']['future_fee_gbp']['amount'] == 500050
    assert 'loan_contract' not in bridge.get_player(bridge.session,ref)['player']
    original = loans.decode
    def mutate(*a,**kw):
        r = original(*a,**kw)
        if fault == 'amount': m['put'](m['loan']+0x20,struct.pack('<i',42))
        elif fault == 'date': m['put'](m['loan']+0x48,struct.pack('<I',2031<<16|182))
        elif fault == 'counter': m['put'](m['loan']+0xF8,b'\x06')
        elif fault == 'holder': m['q'](m['holder'],0)
        elif fault == 'component': m['put'](data,struct.pack('<i',99))
        elif fault == 'membership': m['vec'](m['headers']['people'],[m['manager']])
        elif fault == 'base_flags': m['q'](m['loan']+0xB0,4)
        elif fault == 'override_flags': m['q'](m['loan']+0xB8,4)
        elif fault == 'competition_index': m['put'](m['loan']+0xC4,struct.pack('<i',1))
        elif fault == 'condition_kind': m['put'](m['loan']+0x9C,b'\x03')
        elif fault == 'condition_target': m['put'](m['loan']+0x90,struct.pack('<i',0))
        elif fault == 'stage_id': m['put'](m['loan']+0x94,struct.pack('<i',42))
        elif fault == 'competition_name': m['q'](m['competitions'][1]+0x40,m['text']('Changed name'))
        elif fault == 'competition_member': m['vec'](m['headers']['competitions'],list(reversed(m['competitions'])))
        elif fault == 'lookup_mode': m['put'](m['base']+loans.competitions.LOOKUP_MODE,b'\x00')
        else: m['put'](m['game']+0xC8,struct.pack('<I',420))
        return r
    monkeypatch.setattr(loans,'decode',mutate)
    with pytest.raises(BridgeError,match='changed'):bridge.get_loan_contract(bridge.session,ref)
    assert ref not in bridge.player_refs


@pytest.mark.parametrize('name,bit', list(loans.CLAUSE_BITS.items()))
def test_each_stored_clause_is_independent(loan_record, name, bit):
    m = loan_record
    m['q'](m['loan']+0xB0, 1 << bit)
    r = decode(m)
    assert {key for key,value in r['clauses'].items() if value} == {name}
    assert r['clause_flags'] == {'source':'base', 'native_flags_hex':f'0x{1 << bit:016x}',
                                  'unmapped_flags_hex':'0x0000000000000000'}
    assert r['eligibility_evaluated'] is False


def test_override_replaces_base_and_unknown_flags_are_preserved(loan_record):
    m = loan_record
    m['q'](m['loan']+0xB0,4)
    m['q'](m['loan']+0xB8,(1 << 63) | 2)
    r = decode(m)
    assert r['clauses']['can_play_in_cup_matches']
    assert not r['clauses']['can_be_recalled']
    assert r['clause_flags'] == {'source':'override', 'native_flags_hex':'0x8000000000000002',
                                  'unmapped_flags_hex':'0x8000000000000000'}
    # Native code short-circuits base reads when override is nonzero.
    def read(address, size):
        assert address != m['loan']+0xB0
        return m['read'](address,size)
    assert loans.decode(read,m['base'],m['player'],m['offset'],'GBP') == r
    m['q'](m['loan']+0xB8,0)
    assert decode(m)['clauses']['can_be_recalled']


def test_clause_permissions_do_not_cancel_independent_restrictions(loan_record):
    m = loan_record
    m['q'](m['loan']+0xB0,1 | (1 << 37) | 4 | (1 << 12))
    r = decode(m)
    assert all(r['clauses'][name] for name in ('can_play_against_parent_club',
        'cannot_play_against_parent_club_in_cup_matches','can_be_recalled','loan_cannot_be_terminated'))
    assert not r['eligibility_evaluated']


@pytest.mark.parametrize('ref',[None,1,True,''])
def test_bad_reference_is_rejected(bridge, ref):
    with pytest.raises(BridgeError):bridge.get_loan_contract(bridge.session,ref)


def test_virtual_loan_is_explicitly_unsupported(bridge, monkeypatch, virtual_memory):
    from test_virtual import bind
    bind(bridge,monkeypatch,virtual_memory)
    team = bridge.get_club_squads(bridge.session)['squads'][0]
    rows = bridge.get_team_squad(bridge.session,team['team_ref'])['players']
    ref = next(p['player_ref'] for p in rows if p.get('record_kind')=='virtual')
    with pytest.raises(BridgeError,match='unsupported'):bridge.get_loan_contract(bridge.session,ref)
