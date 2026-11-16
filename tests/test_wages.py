import struct

import pytest

from fm_live_mcp import database, wages, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_contract_dates import dated_record
from test_database import database_memory
from test_players import memory
from test_staff import staff_record, setup, club_fixture
from test_world import world_memory


@pytest.fixture
def wage_record(dated_record):
    m = dated_record
    currency = m['typed']('currency', 0x58)
    m['put'](currency + 8, struct.pack('<III', 0, 86, 86))
    m['q'](currency + 0x18, m['text']('United Kingdom Pound'))
    m['put'](currency + 0x38, struct.pack('<f', 1.0))
    m['vec'](m['headers']['currencies'], [currency])
    m['put'](m['base'] + 0x538EF50, struct.pack('<I', 86))
    m['q'](m['base'] + world.TYPES['full_contract'][0] + 9*8, m['base'] + 0xD8C3C0)
    m['put'](m['staff_contract'] + 0x20, struct.pack('<i', 74103))
    m.update(currency=currency)
    return m


def decode(m):
    return wages.decode(m['read'], m['base'], m['person'])


def test_weekly_gbp_wage_and_zero(wage_record):
    m = wage_record
    assert decode(m) == {'amount': 74103, 'currency': 'GBP', 'period': 'week', 'state': 'decoded',
                         'evidence': 'native_weekly_cash_field_and_base_currency'}
    m['put'](m['staff_contract'] + 0x20, bytes(4))
    assert decode(m)['amount'] == 0


def test_basic_and_absent_contract(wage_record):
    m = wage_record
    contract = m['typed']('basic_contract', 0x28)
    m['q'](contract + 8, m['person'])
    m['put'](contract + 0x20, struct.pack('<i', 3000))
    m['q'](m['base'] + world.TYPES['basic_contract'][0] + 9*8, m['base'] + 0xD8C3C0)
    m['q'](m['person'] - 0x98, contract)
    assert decode(m)['amount'] == 3000
    m['q'](m['person'] - 0x98, 0)
    assert decode(m)['state'] == 'no_contract' and decode(m)['amount'] is None


@pytest.mark.parametrize('fault', ['negative', 'owner', 'getter', 'base_mapping', 'base_name',
                                  'base_rate', 'base_nan', 'base_index', 'base_identity', 'base_absent',
                                  'base_duplicate', 'base_type', 'table_type'])
def test_wage_rejects_bad_units_and_ownership(wage_record, fault):
    m = wage_record
    if fault == 'negative': m['put'](m['staff_contract'] + 0x20, struct.pack('<i', -1))
    if fault == 'owner': m['q'](m['staff_contract'] + 8, 0x8000)
    if fault == 'getter': m['q'](m['base'] + world.TYPES['full_contract'][0] + 9*8, 0)
    if fault == 'base_mapping': m['put'](m['base'] + 0x538EF50, struct.pack('<I', 87))
    if fault == 'base_name': m['q'](m['currency'] + 0x18, m['text']('US Dollar'))
    if fault == 'base_rate': m['put'](m['currency'] + 0x38, struct.pack('<f', 1.5))
    if fault == 'base_nan': m['put'](m['currency'] + 0x38, struct.pack('<f', float('nan')))
    if fault == 'base_index': m['put'](m['currency'] + 8, struct.pack('<I', 1))
    if fault == 'base_identity': m['put'](m['currency'] + 12, struct.pack('<I', 87))
    if fault == 'base_absent': m['vec'](m['headers']['currencies'], [])
    if fault == 'base_duplicate': m['vec'](m['headers']['currencies'], [m['currency'], m['currency']])
    if fault == 'base_type': m['q'](m['currency'], m['base'] + world.TYPES['club'][0])
    if fault == 'table_type': m['q'](m['roots']['currencies'], 0)
    with pytest.raises(ValueError): decode(m)


def test_wage_options_query_boundaries_and_mutation(bridge, monkeypatch, wage_record):
    m = wage_record
    club_fixture(bridge, monkeypatch, m)
    row = bridge.get_club_staff(bridge.session, include_wage=True)['staff'][0]
    assert 'wage' not in bridge.get_club_staff(bridge.session)['staff'][0]['contract']
    fresh = bridge.get_staff(bridge.session, row['staff_ref'], include_wage=True)['staff']
    assert fresh['contract'] == row['contract']
    result = bridge.query_club_staff_wages(bridge.session, minimum=74103, maximum=74103)
    assert result['matched_count'] == 1 and result['matched_contract_wage_sum'] == 74103
    result = bridge.query_club_staff_wages(bridge.session, maximum=74102)
    assert result['matched_count'] == 0 and result['roster_contract_wage_sum'] == 74103
    assert result['matched_contract_wage_sum'] == 0
    original = wages.decode
    def mutate(*a, **kw):
        result = original(*a, **kw)
        m['put'](m['staff_contract'] + 0x20, struct.pack('<i', 75000))
        return result
    monkeypatch.setattr(wages, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.get_staff(bridge.session, row['staff_ref'], include_wage=True)


def test_wage_query_sort_and_limit_preserve_sums(bridge, monkeypatch):
    rows = [{'display_name': name, 'birth_date': '2000-01-01', 'contract': {'wage': {'amount': amount}}}
            for name, amount in [('Zed', 400), ('Ada', 500), ('Abe', 400)]]
    monkeypatch.setattr(bridge, 'get_club_staff', lambda *a, **kw: {
        'staff': rows, 'count': 3, 'observed_at': 'now', 'save': {}, 'club': {}, 'limitations': ''})
    result = bridge.query_club_staff_wages(bridge.session, maximum=400, limit=1)
    assert result['matched_count'] == 2 and result['returned_count'] == 1 and result['truncated']
    assert result['staff'][0]['display_name'] == 'Abe'
    assert result['roster_contract_wage_sum'] == 1300 and result['matched_contract_wage_sum'] == 800


def test_wage_arguments_strict(bridge, monkeypatch, wage_record):
    setup(bridge, monkeypatch, wage_record)
    for options in ({'minimum': True}, {'minimum': -1}, {'maximum': 1.5}, {'minimum': 50, 'maximum': 20}, {'limit': 0}):
        with pytest.raises(BridgeError): bridge.query_club_staff_wages(bridge.session, **options)
    for value in (1, 'true', None):
        with pytest.raises(BridgeError): bridge.get_staff(bridge.session, 'invalid', include_wage=value)
        with pytest.raises(BridgeError): bridge.get_player(bridge.session, 'invalid', include_wage=value)
        with pytest.raises(BridgeError): bridge.get_club_staff(bridge.session, include_wage=value)
