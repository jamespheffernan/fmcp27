from datetime import date, timedelta
import struct

import pytest

from fm_live_mcp import contract_terms as terms, players, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_contract_bonuses import bonus_record, put_entries
from test_contract_dates import dated_record
from test_database import database_memory
from test_players import memory
from test_staff import staff_record, setup, club_fixture
from test_virtual import virtual_memory
from test_wages import wage_record
from test_world import world_memory


@pytest.fixture
def term_record(bonus_record):
    m = bonus_record
    for slot, getter in terms.GETTERS.items():
        m['q'](m['base'] + world.TYPES['full_contract'][0] + slot * 8, m['base'] + getter)
    m['put'](m['base'] + 0x56D4950, b'\0')
    return m


def decode(m):
    return terms.decode(m['read'], m['base'], m['person'])


def test_all_kinds_all_fields_and_preserved_native_order(term_record):
    m = term_record
    kinds = list(reversed(terms.KINDS))
    put_entries(m, [(1000 + kind, kind + 1, kind, 128) for kind in kinds])
    result = decode(m)
    assert result['state'] == 'decoded' and result['currency'] == 'GBP'
    assert result['native_entry_count'] == result['mapped_entry_count'] == len(terms.KINDS)
    assert not result['unmapped_entries'] and result['complete_native_vector']
    assert not result['activation_evaluated']
    assert [row['native_kind'] for row in result['terms']] == kinds
    assert [row['entry_index'] for row in result['terms']] == list(range(len(terms.KINDS)))
    for row in result['terms']:
        kind = row['native_kind']
        assert row['native_flags'] == 128 and row['selected_by_native_property']
        assert row['kind'] == terms.KINDS[kind] and row['unavailable_fields'] == []
        for field_kind, field, slot, *_ in terms.FIELDS:
            if field_kind != kind: continue
            if slot == 52: assert row['values'][field] == 1000 + kind
            elif slot == 54: assert row['values'][field] == kind + 1
            elif slot == 46: assert row['values'][field] is True
            else:
                assert row['values'][field]['date'] == (date(2030, 5, 31) + timedelta(days=kind + 1)).isoformat()
                assert row['values'][field]['days_after_signed'] == kind + 1


def test_repeated_landmarks_lowest_parameter_first_tie_and_unmapped(term_record):
    m = term_record
    put_entries(m, [(300, 30, 10, 0), (100, 10, 10, 0), (200, 20, 10, 0),
                    (101, 10, 10, 1), (500, 1, 32, 0), (501, -1, 32, 0),
                    (-7, -32768, 255, 9)])
    result = decode(m)
    assert [row['selected_by_native_property'] for row in result['terms']] == [False, True, False, False, True, False]
    assert [row['values']['amount_gbp'] for row in result['terms'][:4]] == [300, 100, 200, 101]
    assert result['unmapped_entries'] == [{'entry_index': 6, 'native_kind': 255, 'native_flags': 9,
        'selected_by_native_property': True, 'native_value': -7, 'native_parameter': -32768, 'state': 'unmapped_entry_kind'}]
    assert result['native_entry_count'] == 7 and result['unmapped_entry_count'] == 1


def test_unknown_and_negative_parameters_are_not_absence(term_record):
    m = term_record
    put_entries(m, [(100, 10, 10, 0), (50, -1, 10, 0), (0, -32768, 3, 0)])
    result = decode(m)
    assert [row['selected_by_native_property'] for row in result['terms']] == [False, True, True]
    assert result['terms'][1]['values'] == {'amount_gbp': 50, 'goals': None}
    assert result['terms'][1]['unavailable_fields'] == [{'field': 'goals', 'reason': 'negative_native_parameter', 'native_value': -1}]
    assert result['terms'][2]['values']['percentage'] is None
    put_entries(m, [(0, 32767, 3, 0)])
    assert decode(m)['terms'][0]['values']['percentage'] == 32767  # stored value; no editor-range clamp


def test_zero_empty_and_unavailable_contracts(term_record):
    m = term_record
    put_entries(m, [(0, 0, 9, 0)])
    assert decode(m)['terms'][0]['values'] == {'percentage': 0, 'original_transfer_fee_gbp': 0}
    put_entries(m, [])
    result = decode(m)
    assert result['terms'] == [] and result['unmapped_entries'] == [] and result['complete_native_vector']
    basic = m['typed']('basic_contract', 0x28)
    m['q'](basic + 8, m['person'])
    m['q'](m['person'] - 0x98, basic)
    result = decode(m)
    assert result['state'] == 'basic_contract_terms_unavailable' and result['terms'] is None
    assert not result['complete_native_vector']
    m['q'](m['person'] - 0x98, 0)
    assert decode(m)['state'] == 'no_contract'


@pytest.mark.parametrize('slot', list(terms.GETTERS))
def test_changed_dispatch_is_rejected(term_record, slot):
    m = term_record
    m['q'](m['base'] + world.TYPES['full_contract'][0] + slot * 8, 0)
    with pytest.raises(ValueError, match='getter changed'): decode(m)


def test_invalid_cash_in_unselected_entry_is_rejected(term_record):
    m = term_record
    put_entries(m, [(100, 10, 10, 0), (-1, 20, 10, 0)])
    with pytest.raises(ValueError, match='negative'): decode(m)


def test_expiry_modes_negative_offsets_overflow_and_bad_date(term_record):
    m = term_record
    for mode in (1, 2, 3):
        m['put'](m['base'] + 0x56D4950, bytes([mode]))
        put_entries(m, [(20000000, 365, 0, 0)])
        assert decode(m)['terms'][0]['values']['expiry'] == {'date': None, 'state': 'native_default', 'reason': 'native_date_mode'}
    for mode in (0, 4, 255):
        m['put'](m['base'] + 0x56D4950, bytes([mode]))
        assert decode(m)['terms'][0]['values']['expiry']['date'] == '2031-05-31'
    put_entries(m, [(1, -1, 0, 0)])
    assert decode(m)['terms'][0]['values']['expiry']['reason'] == 'negative_expiry_parameter'
    put_entries(m, [(1, 32767, 0, 0)])
    assert decode(m)['terms'][0]['values']['expiry']['reason'] == 'native_day_arithmetic_overflow'
    put_entries(m, [(1, 365, 0, 0)])
    m['put'](m['staff_contract'] + 0x44, bytes(4))
    with pytest.raises(ValueError, match='date'): decode(m)


def test_expiry_matches_native_calendar_arithmetic():
    # Independent transcription of 0x42E9B44, checked by the native layout verifier.
    def native(year, day, offset):
        count = day + offset - 1
        while True:
            mask = 15 if (year * 0x5C29 & 0xFFFF) < 0xA3E else 3
            length = 366 if not mask & year else 365
            if count < length: return year, count + 1
            count -= length
            year += 1
    for year in range(1850, 2201):
        for day in (1, 59, 60, 61, 181, 365, 366):
            anchor = date(year, 1, 1) + timedelta(days=day - 1)
            if anchor.year != year: continue
            raw = struct.pack('<I', year << 16 | day | 127 << 9)
            read = lambda address, length: b'\0' if length == 1 else raw
            for offset in (0, 1, 365, 1461, 32768 - day):
                result = terms.expiry(read, 0, 4096, offset)
                expected_year, expected_day = native(year, day, offset)
                if expected_year > 2200: assert result['reason'] == 'date_outside_verified_range'
                else:
                    expected = date(expected_year, 1, 1) + timedelta(days=expected_day - 1)
                    assert result['date'] == expected.isoformat()


def test_staff_tool_bulk_parity_and_selector_validation(bridge, monkeypatch, term_record):
    m = term_record
    club_fixture(bridge, monkeypatch, m)
    put_entries(m, [(5000000, -1, 0, 0), (0, 10, 3, 0)])
    row = bridge.get_club_staff(bridge.session, include_contract_terms=True)['staff'][0]
    result = bridge.get_contract_terms(bridge.session, staff_ref=row['staff_ref'])
    assert result['contract_terms'] == row['contract']['terms']
    assert result['person']['name'] == row['name']
    assert 'terms' not in bridge.get_staff(bridge.session, row['staff_ref'])['staff'].get('contract', {})
    for options in ({}, {'player_ref': 'p', 'staff_ref': 's'}, {'player_ref': ''}, {'staff_ref': 1}):
        with pytest.raises(BridgeError): bridge.get_contract_terms(bridge.session, **options)
    for value in (1, 'true', None):
        with pytest.raises(BridgeError, match='boolean'): bridge.get_club_staff(bridge.session, include_contract_terms=value)
        with pytest.raises(BridgeError, match='boolean'): bridge.get_staff(bridge.session, 'bad', include_contract_terms=value)
        with pytest.raises(BridgeError, match='boolean'): bridge.get_player(bridge.session, 'bad', include_contract_terms=value)


@pytest.mark.parametrize('fault', ['parameter', 'amount', 'kind', 'flags', 'vector', 'signed_date', 'date_mode'])
def test_changes_reject_staff_reference(bridge, monkeypatch, term_record, fault):
    m = term_record
    club_fixture(bridge, monkeypatch, m)
    address = put_entries(m, [(5000000, 365, 0, 0)])
    row = bridge.get_club_staff(bridge.session)['staff'][0]
    original = terms.decode
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        if fault == 'parameter': m['put'](address + 4, struct.pack('<h', 366))
        elif fault == 'amount': m['put'](address, struct.pack('<i', 6))
        elif fault == 'kind': m['put'](address + 6, b'\x01')
        elif fault == 'flags': m['put'](address + 7, b'\x01')
        elif fault == 'vector': m['q'](m['staff_contract'] + 0x70, 0)
        elif fault == 'signed_date': m['put'](m['staff_contract'] + 0x44, struct.pack('<I', 2031 << 16 | 1))
        else: m['put'](m['base'] + 0x56D4950, b'\x01')
        return result
    monkeypatch.setattr(terms, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.get_contract_terms(bridge.session, staff_ref=row['staff_ref'])
    assert row['staff_ref'] not in bridge.staff_refs


def test_regular_player_terms_and_stale_identity(bridge, monkeypatch, database_memory):
    from test_database import bind, receipt
    m = database_memory
    bind(bridge, monkeypatch, m)
    monkeypatch.setattr(bridge, '_run', lambda *a: receipt())
    person, table = 0x1388, m['base'] + players.RVA[2]
    m['q'](table + 121 * 8, m['base'] + 0xCB3724)
    m['put'](table - 0x3D8, struct.pack('<q', -0x110))
    contract = m['typed']('full_contract', 0xC8)
    m['q'](contract + 8, person)
    m['q'](person - 0x98, contract)
    m['staff_contract'] = contract
    from fm_live_mcp.contract_bonuses import GETTERS
    for slot, getter in (GETTERS | terms.GETTERS).items():
        m['q'](m['base'] + world.TYPES['full_contract'][0] + slot * 8, m['base'] + getter)
    put_entries(m, [(0, 2, 22, 0)])
    monkeypatch.setattr(terms.wages, 'base_currency', lambda *a: 'GBP')
    ref = bridge.find_save_players(bridge.session, 'Test')['players'][0]['player_ref']
    assert bridge.get_contract_terms(bridge.session, player_ref=ref)['contract_terms']['terms'][0]['values'] == {'years': 2}
    m['q'](contract + 8, 0x8000)
    with pytest.raises(BridgeError): bridge.get_contract_terms(bridge.session, player_ref=ref)
    assert ref not in bridge.player_refs


def test_virtual_terms_fail_explicitly(bridge, monkeypatch, virtual_memory):
    from test_virtual import bind
    bind(bridge, monkeypatch, virtual_memory)
    team = bridge.get_club_squads(bridge.session)['squads'][0]
    rows = bridge.get_team_squad(bridge.session, team['team_ref'])['players']
    ref = next(p['player_ref'] for p in rows if p.get('record_kind') == 'virtual')
    with pytest.raises(BridgeError, match='unsupported'):
        bridge.get_contract_terms(bridge.session, player_ref=ref)
