"""Exercise owned native contract bytes, not supplied arithmetic answer rows."""
import struct

import pytest

from fm_live_mcp import contract_terms, contract_wage_steps as steps, players, world
from test_contract_bonuses import bonus_record, put_entries
from test_contract_dates import dated_record
from test_contract_terms import term_record
from test_database import database_memory
from test_players import memory
from test_staff import staff_record
from test_wages import wage_record
from test_world import world_memory


def decode(m, read=None):
    return steps.decode(read or m['read'], m['base'], m['person'])


def test_repeated_steps_are_independent_targets_not_additive_or_activated(term_record):
    m = term_record
    m['put'](m['staff_contract'] + 0x20, struct.pack('<i', 12121))
    put_entries(m, [(20612, 15, 13, 0), (32979, 25, 13, 128),
                    (162500, 5, 19, 1), (1234, -1, 32, 0), (0, 5, 3, 0)])
    result = decode(m)
    assert result['state'] == 'decoded_scenarios'
    assert result['currency'] == 'GBP' and result['period'] == 'week'
    assert result['native_entry_count'] == 5 and result['complete_current_term_vector']
    assert result['appearance_step_count'] == 3
    assert [r['entry_index'] for r in result['steps']] == [0, 1, 2]
    assert [r['stored_target_weekly_wage_gbp'] for r in result['steps']] == [20612, 32979, 162500]
    assert [r['difference_from_current_weekly_main_wage_gbp'] for r in result['steps']] == [8491, 20858, 150379]
    assert [r['stored_threshold'] for r in result['steps']] == [15, 25, 5]
    assert [r['selected_by_native_property'] for r in result['steps']] == [True, False, True]
    assert [r['native_flags'] for r in result['steps']] == [0, 128, 1]
    assert result['largest_stored_target_increase_gbp'] == 150379
    assert not result['activation_evaluated'] and not result['progress_evaluated']
    for row in result['steps']:
        assert row['trigger_satisfied'] is row['remaining_appearances'] is row['applies_now'] is None
    assert 'annual wage rise' in result['scope'] and 'not additive' in result['scope']


def test_native_selection_keeps_unknown_threshold_and_first_tie(term_record):
    m = term_record
    put_entries(m, [(80000, 10, 13, 0), (90000, -1, 13, 0), (95000, -1, 13, 4),
                    (100000, -32768, 19, 255)])
    result = decode(m)
    assert [row['selected_by_native_property'] for row in result['steps']] == [False, True, False, True]
    assert [row['stored_threshold'] for row in result['steps']] == [10, None, None, None]
    assert [row['threshold_state'] for row in result['steps']] == ['stored', 'unavailable', 'unavailable', 'unavailable']
    assert result['steps'][1]['unavailable_fields'] == [
        {'field': 'league_games', 'reason': 'negative_native_parameter', 'native_value': -1}]
    assert result['steps'][3]['stored_target_weekly_wage_gbp'] == 100000
    assert result['steps'][3]['difference_from_current_weekly_main_wage_gbp'] == 25897


def test_lower_equal_zero_and_maximum_targets_do_not_become_savings(term_record):
    m = term_record
    m['put'](m['staff_contract'] + 0x20, struct.pack('<i', 100))
    put_entries(m, [(0, 0, 13, 0), (100, 32767, 19, 0), (2147483647, 1, 13, 0)])
    result = decode(m)
    assert [row['difference_from_current_weekly_main_wage_gbp'] for row in result['steps']] == [-100, 0, 2147483547]
    assert [row['target_relative_to_current'] for row in result['steps']] == ['lower', 'equal', 'higher']
    assert result['largest_stored_target_increase_gbp'] == 2147483547
    put_entries(m, [(0, 0, 13, 0)])
    assert decode(m)['largest_stored_target_increase_gbp'] == 0
    m['put'](m['staff_contract'] + 0x20, bytes(4))
    assert decode(m)['steps'][0]['difference_from_current_weekly_main_wage_gbp'] == 0


def test_empty_known_scope_preserves_unmapped_contract_entries(term_record):
    m = term_record
    put_entries(m, [(-99, -1, 255, 7), (0, 5, 3, 0), (5000, -1, 32, 0)])
    result = decode(m)
    assert result['steps'] == [] and result['appearance_step_count'] == 0
    assert result['native_entry_count'] == 3 and result['unmapped_entry_count'] == 1
    assert result['largest_stored_target_increase_gbp'] == 0
    assert 'Unmapped entries' in result['scope']
    put_entries(m, [])
    assert decode(m)['native_entry_count'] == 0 and decode(m)['steps'] == []


def test_basic_known_wage_does_not_imply_absent_steps_and_no_contract_is_distinct(term_record):
    m = term_record
    basic = m['typed']('basic_contract', 0x28)
    m['q'](basic + 8, m['person'])
    m['q'](m['base'] + world.TYPES['basic_contract'][0] + 9 * 8, m['base'] + 0xD8C3C0)
    m['put'](basic + 0x20, struct.pack('<i', 3000))
    m['q'](m['person'] - 0x98, basic)
    result = decode(m)
    assert result['state'] == 'basic_contract_terms_unavailable'
    assert result['current_weekly_main_wage']['amount'] == 3000
    assert result['steps'] is None and result['largest_stored_target_increase_gbp'] is None
    assert not result['complete_current_term_vector']
    m['q'](m['person'] - 0x98, 0)
    result = decode(m)
    assert result['state'] == 'no_contract' and result['steps'] is None
    assert result['current_weekly_main_wage']['amount'] is None


@pytest.mark.parametrize('fault', ['owner', 'wage_getter', 'terms_getter', 'person_getter',
                                  'currency', 'negative_wage', 'negative_target', 'negative_unselected_target',
                                  'negative_other_cash', 'bound', 'vector_order', 'unreadable'])
def test_rejects_bad_owned_sources_without_partial_scenarios(term_record, fault):
    m = term_record
    address = put_entries(m, [(80000, 10, 13, 0), (90000, 20, 13, 0)])
    if fault == 'owner': m['q'](m['staff_contract'] + 8, 0)
    if fault == 'wage_getter': m['q'](m['base'] + world.TYPES['full_contract'][0] + 9 * 8, 0)
    if fault == 'terms_getter': m['q'](m['base'] + world.TYPES['full_contract'][0] + 54 * 8, 0)
    if fault == 'person_getter': m['q'](players.u64(m['read'](m['person'], 8)) + 121 * 8, 0)
    if fault == 'currency': m['put'](m['base'] + 0x538EF50, struct.pack('<I', 87))
    if fault == 'negative_wage': m['put'](m['staff_contract'] + 0x20, struct.pack('<i', -1))
    if fault == 'negative_target': m['put'](address, struct.pack('<i', -1))
    if fault == 'negative_unselected_target': m['put'](address + 8, struct.pack('<i', -1))
    if fault == 'negative_other_cash': put_entries(m, [(1, 10, 13, 0), (-1, 1, 32, 0)])
    if fault == 'bound': m['q'](m['staff_contract'] + 0x78, address + 257 * 8)
    if fault == 'vector_order': m['q'](m['staff_contract'] + 0x70, address - 8)
    if fault == 'unreadable':
        original = m['read']
        def read(a, n):
            if a == address: raise ValueError('Unreadable contract bytes')
            return original(a, n)
        with pytest.raises(ValueError, match='Unreadable'): decode(m, read)
        return
    with pytest.raises(ValueError): decode(m)


def test_contract_pointer_change_between_sources_rejected(term_record):
    m = term_record
    put_entries(m, [(90000, 10, 13, 0)])
    original = m['read'];calls = 0
    pointer_address = m['person'] - 0x98
    # Change after the complete term read; never accept a mixed/changed agreement.
    def read(a, n):
        nonlocal calls
        if a == pointer_address:
            calls += 1
            if calls == 4: return bytes(8)
        return original(a, n)
    with pytest.raises(ValueError, match='current contract changed'): decode(m, read)


@pytest.mark.parametrize('fault', ['wage', 'target', 'threshold', 'flags', 'vector', 'owner', 'currency'])
def test_caller_consumed_read_set_rejects_postdecode_drift(term_record, fault):
    m = term_record
    address = put_entries(m, [(90000, 10, 13, 0)])
    read = world.ReadSet(m['read'])
    result = decode(m, read)
    assert result['steps'][0]['stored_target_weekly_wage_gbp'] == 90000
    read.verify()
    if fault == 'wage': m['put'](m['staff_contract'] + 0x20, struct.pack('<i', 75000))
    if fault == 'target': m['put'](address, struct.pack('<i', 90001))
    if fault == 'threshold': m['put'](address + 4, struct.pack('<h', 11))
    if fault == 'flags': m['put'](address + 7, b'\x01')
    if fault == 'vector': m['q'](m['staff_contract'] + 0x70, address)
    if fault == 'owner': m['q'](m['staff_contract'] + 8, 0)
    if fault == 'currency': m['put'](m['currency'] + 0x38, struct.pack('<f', 2.0))
    with pytest.raises(ValueError, match='changed'): read.verify()
