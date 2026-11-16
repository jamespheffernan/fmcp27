import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import transfer_cash_context as context, players, world
from test_club_debt_obligations import debt_memory
from test_club_finance import finance_memory
from test_contingent_transfer_appearance import appearance_memory
from test_database import database_memory
from test_finance_person_reference import person_memory
from test_players import memory
from test_retained_transfer_debt import transfer_memory
from test_transfer_payment_timing import current
from test_world import world_memory


def model():
    cells = {}
    def put(at, raw):
        cells.update({at+i: b for i, b in enumerate(raw)})
    def read(at, n):
        return bytes(cells[at+i] for i in range(n))
    return cells, put, read


@pytest.mark.parametrize(('mode', 'index', 'expected', 'state'), [
    (0, 0, 0x53000000, 'native_resident_index_lookup'),
    (0, 1, 0x54010000, 'native_header_index_lookup'),
    (1, 0, 0x54000000, 'native_header_index_lookup'),
    (1, 2, 0, 'native_null_lookup'),
    (0, 2, 0, 'native_null_lookup'),
    (0, -1, None, 'native_prior_index_removal'),
    (0, 3, None, 'native_prior_index_removal'),
])
def test_schedule_lookup_keeps_resident_header_and_equality_paths_distinct(mode, index, expected, state):
    _, put, read = model()
    base, root, header, resident = 0x100000000, 0x50000000, 0x51000000, 0x52000000
    put(base+0x56D34E0, bytes([mode]))
    put(root+0x68, struct.pack('<QQ', resident, resident+8))
    put(resident, struct.pack('<Q', 0x53000000))
    put(header, struct.pack('<QQ', 0x54000000, 0x54010000))
    raw = bytes(28)+struct.pack('<i', index)+bytes(2)
    result = context.schedule_person(read, base, raw, {'root': root, 'start': header, 'count': 2})
    assert result == {'state': state, 'index': index, 'address': expected}


def test_rtti_name_and_original_four_byte_aligned_function_pointer_are_valid():
    _, put, read = model()
    base, record, table, info, name = 0x100000000, 0x50000000, 0x55C3B50, 0x55C4E58, 0x53A2E96
    put(record, struct.pack('<Q', base+table))
    put(base+table-16, struct.pack('<qQ', 0, base+info))
    put(base+info+8, struct.pack('<Q', base+name))
    put(base+name, b'N2db21APPEARANCE_MONEY_INFOE\0'.ljust(128, b'\0'))
    put(base+table+0x28, struct.pack('<Q', base+0x1812D44))
    put(base+0x1812D44, bytes.fromhex('c0008052c0035fd6'))
    result = context._type_prefix(read, base, record, 0x28)
    assert result['native_rtti'] == 'N2db21APPEARANCE_MONEY_INFOE'
    assert result['callee_rva'] == '0x1812d44'


@pytest.mark.parametrize(('start', 'end'), [(4, 8), (0x10000, 0xFFFF), (0x10000, 0x10003),
                                          (0x10000, 0x10000+4097*4)])
def test_reference_vectors_require_actual_native_stride_and_bound(start, end):
    _, put, read = model()
    put(0x50000000, struct.pack('<QQ', start, end))
    with pytest.raises(ValueError):
        context._span(read, 0x50000000, 4, 4096)


def test_offer_reference_probe_preserves_filtered_null_and_outside_indices():
    _, put, read = model()
    base, header, indices, manager, entries, offer = (0x100000000, 0x50000000, 0x50010000,
                                                    0x51000000, 0x51010000, 0x52000000)
    put(header, struct.pack('<QQ', indices, indices+16))
    put(indices, struct.pack('<4i', -1, 0, 1, 2))
    put(base+0x56A67F0, struct.pack('<Q', manager))
    put(manager+8, struct.pack('<QQ', entries, entries+16))
    put(entries, struct.pack('<QQ', offer, 0))
    put(offer+8, struct.pack('<I', 2))
    put(offer+0x8D, b'\x12')
    result = context._offer_references(read, base, header)
    assert [v['state'] for v in result['indexed_entries']] == [
        'native_index_filtered', 'native_kind_filtered', 'native_null_entry', 'native_index_filtered']
    assert result['indexed_entries'][1]['native_kind_byte_8d'] == 18
    assert result['offer_objects_or_predicate_not_evaluated'] is True


@pytest.fixture
def cash_memory(person_memory):
    m = person_memory
    profile = json.loads((Path(__file__).parents[1] / 'evidence/transfer-cash-context-20261109/source-bytes.json').read_text())
    for span in profile['spans']:
        m['put'](m['base']+span['rva'], bytes.fromhex(span['hex']))
    for record in profile['types']:
        m['put'](m['base']+record['table']-16, struct.pack('<qQ', record['displacement'], m['base']+record['info']))
        m['q'](m['base']+record['info']+8, m['base']+record['name'])
        m['put'](m['base']+record['name'], bytes.fromhex(record['name_hex']))
    for record in profile['dispatch_prefixes']:
        m['q'](m['base']+record['table']+record['slot'], m['base']+record['target'])
        m['put'](m['base']+record['target'], bytes.fromhex(record['captured_prefix_hex']))
    m['q'](m['base']+0x55C3A90+0x28, m['base']+0x1804AA4)
    m['q'](m['base']+0x55C3A90+0x18, m['base']+0x18043D4)
    m['q'](m['base']+0x55C3A90+0x98, m['base']+0x180459C)
    m['q'](m['base']+0x55C3A90+0xA8, m['base']+0x180481C)
    m['q'](m['base']+world.TYPES['game_club'][0]+0x120, m['base']+0x1FAB7EC)
    m['q'](m['base']+0x56B5438, 0)
    for slot, target in ((0x3C8, 0xCB3724), (0x530, 0xCD9558), (0x6D0, 0xCA4A50), (0x6E0, 0xD5C610)):
        m['q'](m['base']+players.RVA[2]+slot, m['base']+target)
    raw = bytearray(m['read'](m['incoming'], 34))
    struct.pack_into('<i', raw, 28, 1)
    m['put'](m['incoming'], raw)
    for club in (m['club'], m['other_club']):
        m['q'](club+0xD8, 0x80000000)
        m['put'](club+0x18, bytes(24))
    raw = struct.pack('<QIIQiiHbbB', m['base']+0x55C3A90, 12345, 12345, m['other_club'], 100000, 0, 255, 20, 0, 0)
    m['put'](m['first_clause'], raw)
    m['q'](m['other_clause'], m['base']+0x55C3B50)
    m['put'](m['base']+world.CURRENT_DATE, current())
    m['put'](m['base']+0x56D4953, b'\0')
    return m


def test_bounded_context_captures_actual_inputs_without_claiming_net_or_settlement(cash_memory):
    m = cash_memory
    before = dict(m['cells'])
    result = context.decode(m['read'], m['base'], m['club'])
    assert result['state'] == 'captured_bounded_research_context'
    assert result['selected_schedule_slot'] == 1
    assert result['person']['identity']['name'] == 'Test Müller'
    assert result['person']['native_reference'] == [12345, 12345]
    assert result['person']['main_contract']['state'] == 'native_null_contract'
    assert result['recipient']['rule_context']['state'] == 'native_no_first_team'
    assert result['recipient_retained_sell_on_clauses']['records'][0]['native_percentage'] == 20
    assert len(result['recipient_clause_types']) == 5
    assert result['full_cash_replay_performed'] is result['actual_payment_or_final_net_established'] is False
    assert m['cells'] == before


def test_no_incoming_branch_is_unavailable_not_empty_cash_ledger(cash_memory):
    m = cash_memory
    m['vec'](m['transfer_manager']+0xD8, [m['outgoing']])
    result = context.decode(m['read'], m['base'], m['club'])
    assert result['state'] == 'unavailable'
    assert result['reason'] == 'no_supported_incoming_native_cash_branch_in_observed_prefix'


def test_foreign_base_finance_is_typed_balance_only(cash_memory):
    m = cash_memory
    finance = m['allocate'](0x40)
    m['q'](finance, m['base']+world.TYPES['club_finance_base'][0])
    m['put'](finance+12, struct.pack('<i', -1500))
    m['q'](m['other_club']+0x150, finance)
    result = context.decode(m['read'], m['base'], m['club'])['payer']['finance']
    assert result['state'] == 'typed_base_finance_balance_only'
    assert result['native_signed32_fields'] == {'0xc': -1500}
    assert len(result['dispatches']) == 6


def test_owned_full_contract_raw_flags_are_inputs_not_eligibility_or_paid_state(cash_memory):
    m = cash_memory
    contract = m['allocate'](0x100)
    m['q'](contract, m['base']+world.TYPES['full_contract'][0])
    m['q'](contract+8, m['binding_person'])
    m['q'](m['binding_person']-0x98, contract)
    m['put'](contract+0xC2, b'\x01')
    m['q'](m['base']+world.TYPES['full_contract'][0]+0x70, m['base']+0x129A4B8)
    result = context.decode(m['read'], m['base'], m['club'])
    assert result['person']['main_contract']['state'] == 'typed_native_contract'
    assert result['person']['main_contract']['native_byte_c2'] == 1
    assert result['person']['main_contract']['native_dispatch_70']['callee_rva'] == '0x129a4b8'
    assert result['actual_payment_or_final_net_established'] is False


@pytest.mark.parametrize('field', ['schedule', 'person', 'clause', 'callee', 'flags'])
def test_context_consumed_inputs_remain_physically_fenced(cash_memory, field):
    m = cash_memory
    read = world.ReadSet(m['read'])
    context.decode(read, m['base'], m['club'])
    at = {'schedule': m['incoming']+28, 'person': m['binding_person']+12,
          'clause': m['first_clause']+28, 'callee': m['base']+0x1812D44,
          'flags': m['base']+0x56D4953}[field]
    m['put'](at, bytes([m['read'](at, 1)[0]^1]))
    with pytest.raises(ValueError, match='changed during read'):
        read.verify()
