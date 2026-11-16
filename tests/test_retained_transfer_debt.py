from datetime import date
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import retained_transfer_debt as debt, world
from test_club_debt_obligations import debt_memory, packed
from test_club_finance import finance_memory
from test_database import database_memory
from test_players import memory
from test_world import world_memory


SOURCE = json.loads((Path(__file__).parents[1] / 'evidence/transfer-obligations-20261109/source-bytes.json').read_text())


def row(payer, recipient, amount=1000, count=12, interval=1):
    return (struct.pack('<QQ', payer, recipient) + packed(date(2030, 1, 1)) * 2
            + struct.pack('<iiBb', amount, 42, interval, count) + bytes(6))


@pytest.fixture
def transfer_memory(debt_memory):
    m = debt_memory
    for span in SOURCE['spans']:
        m['put'](m['base'] + span['rva'], bytes.fromhex(span['hex']))
    service = m['allocate'](8)
    m['q'](service, m['base'] + debt.FULL_TABLE)
    m['q'](m['base'] + debt.FULL_ROOT, service)
    info = m['base'] + 0x55DFF18
    name = m['base'] + 0x53B1011
    m['put'](m['base'] + debt.FULL_TABLE - 16, struct.pack('<qQ', 0, info))
    m['q'](info + 8, name)
    m['put'](name, b'17GAME_CLUB_FINANCE\0')
    for table, offset, target in [(debt.FULL_TABLE, 0x50, 0x1FD5728), (debt.FULL_TABLE, 0x168, 0x1FFCFF0),
                                  (world.TYPES['club_finance'][0], 0x1F8, 0xEA8CFC),
                                  (world.TYPES['club_finance'][0], 0x290, 0xEA82CC)]:
        m['q'](m['base'] + table + offset, m['base'] + target)
    manager = m['typed']('transfer_manager', 0x110)
    m['q'](m['base'] + debt.ROOT, manager)
    for offset, target in ((0, 0x2D10D10), (8, 0x2D10D24)):
        m['q'](m['base'] + world.TYPES['transfer_manager'][0] + offset, m['base'] + target)
    other = m['typed']('club', 0x170)
    m['put'](other + 8, struct.pack('<III', 1, 680, 680))
    m['q'](other + 0xC0, m['text']('Counterparty United'))
    m['q'](other + 0xC8, m['text']('Counterparty'))
    m['vec'](m['headers']['clubs'], [m['club'], other])
    outgoing, incoming = m['allocate'](40), m['allocate'](40)
    m['put'](outgoing, row(m['club'], other))
    m['put'](incoming, row(other, m['club'], 500, 2))
    m['vec'](manager + 0xD8, [outgoing, incoming])
    m.update(transfer_manager=manager, other_club=other, outgoing=outgoing, incoming=incoming)
    return m


def test_owned_retained_payable_receivable_and_native_net_have_exact_distinct_semantics(transfer_memory):
    m = transfer_memory
    result = debt.decode(m['read'], m['base'], m['club'])
    assert result['currency'] == 'GBP' and result['state'] == 'decoded'
    assert result['financial_owner']['native_id'] == 688
    assert result['native_transfer_debt'] == {'amount': 11000, 'native_signed32': 11000,
                                             'signed32_wrap': False, 'state': 'native_schedule_net'}
    out, incoming = result['records']
    assert (out['direction'], incoming['direction']) == ('outgoing', 'incoming')
    assert out['recorded_payer']['native_id'] == 688 and out['recorded_recipient']['native_id'] == 680
    assert incoming['recorded_payer']['native_id'] == 680 and incoming['recorded_recipient']['native_id'] == 688
    assert out['native_remaining_amount']['amount'] == 12000
    assert all(r['payment_state'] == 'not_established' and r['next_payment_due_date'] is None for r in result['records'])
    assert result['complete_liability_ledger'] is False


def test_native_first_null_returns_current_sum_and_preserves_outside_scope(transfer_memory):
    m = transfer_memory
    m['vec'](m['transfer_manager'] + 0xD8, [m['outgoing'], 0, m['incoming'], 0xBAD0])
    result = debt.decode(m['read'], m['base'], m['club'])
    assert result['native_transfer_debt']['amount'] == 12000
    assert result['source_slot_count'] == 4 and result['native_prefix_slot_count'] == 1
    assert result['first_null_slot'] == 1 and result['outside_native_prefix_slot_count'] == 2
    assert len(result['records']) == 1


def test_aliases_self_club_and_negative_net_preserve_original_branch_order(transfer_memory):
    m = transfer_memory
    m['vec'](m['transfer_manager'] + 0xD8, [m['incoming'], m['incoming']])
    result = debt.decode(m['read'], m['base'], m['club'])
    assert result['native_transfer_debt']['amount'] == -2000 and len(result['records']) == 2
    m['put'](m['outgoing'], row(m['club'], m['club']))
    m['vec'](m['transfer_manager'] + 0xD8, [m['outgoing']])
    result = debt.decode(m['read'], m['base'], m['club'])
    assert result['records'][0]['direction'] == 'self'
    assert result['native_transfer_debt']['amount'] == 12000


@pytest.mark.parametrize(('amount', 'count'), [(-1, 12), (1000, -1), (1000, 0), (2**31-1, 1), (2**30, 12)])
def test_unclassified_amount_count_and_native_wrap_are_not_valid_cash(transfer_memory, amount, count):
    m = transfer_memory
    m['put'](m['outgoing'], row(m['club'], m['other_club'], amount, count))
    result = debt.decode(m['read'], m['base'], m['club'])
    assert result['native_transfer_debt']['amount'] is None
    assert result['native_transfer_debt']['state'] == 'unclassified_native_terms'
    assert result['records'][0]['native_remaining_amount']['amount'] is None


def test_empty_observed_source_is_distinct_from_absent_manager(transfer_memory):
    m = transfer_memory
    m['vec'](m['transfer_manager'] + 0xD8, [])
    result = debt.decode(m['read'], m['base'], m['club'])
    assert result['records'] == [] and result['native_transfer_debt']['amount'] == 0
    m['q'](m['base'] + debt.ROOT, 0)
    result = debt.decode(m['read'], m['base'], m['club'])
    assert result['state'] == 'unavailable' and result['records'] is None
    assert result['native_transfer_debt'] is None and result['source_slot_count'] is None


@pytest.mark.parametrize('fault', ['native', 'service', 'manager', 'money_dispatch', 'membership', 'vector'])
def test_wrong_or_changed_retained_source_fails_closed(transfer_memory, fault):
    m = transfer_memory
    if fault == 'native':
        m['put'](m['base'] + debt.SOURCE[0][0], b'\0')
    elif fault == 'service':
        m['q'](m['base'] + debt.FULL_ROOT, 0)
    elif fault == 'manager':
        m['q'](m['transfer_manager'], 0)
    elif fault == 'money_dispatch':
        m['q'](m['base'] + debt.FULL_TABLE + 0x168, 0)
    elif fault == 'membership':
        m['vec'](m['headers']['clubs'], [m['club'], m['club']])
    else:
        m['put'](m['transfer_manager'] + 0xD8, struct.pack('<QQQ', 4096, 4105, 4112))
    with pytest.raises(ValueError):
        debt.decode(m['read'], m['base'], m['club'])


def test_final_source_changes_and_large_valid_vectors_have_bounded_physical_reads(transfer_memory):
    m = transfer_memory
    m['vec'](m['transfer_manager'] + 0xD8, [0] + [m['outgoing']] * 3000)
    reads = []
    def read(address, size):
        reads.append((address, size))
        assert 0 < size <= 8192
        return m['read'](address, size)
    snapshot = world.ReadSet(read)
    result = debt.decode(snapshot, m['base'], m['club'])
    assert result['native_transfer_debt']['amount'] == 0 and result['native_prefix_slot_count'] == 0
    assert result['outside_native_prefix_slot_count'] == 3000
    m['q'](m['base'] + debt.ROOT, 0)
    with pytest.raises(ValueError, match='changed during read'):
        snapshot.verify()
