import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import contingent_transfer_sell_on as clauses, world
from test_contingent_transfer_appearance import appearance_memory
from test_club_debt_obligations import debt_memory
from test_club_finance import finance_memory
from test_database import database_memory
from test_players import memory
from test_retained_transfer_debt import transfer_memory
from test_world import world_memory


def row(base, recipient, basis=100000, used=40000, percentage=20, override=0, flags=255, flag=0):
    return struct.pack('<QIIQiiHbbB', base + clauses.TABLE, 1234, 1234, recipient,
                       basis, used, flags, percentage, override, flag)


@pytest.fixture
def sell_on_memory(appearance_memory):
    m = appearance_memory
    source = json.loads((Path(__file__).parents[1] / 'evidence/transfer-payment-lifecycle-20261109/source-bytes.json').read_text())
    for span in source['spans']:
        m['put'](m['base'] + span['rva'], bytes.fromhex(span['hex']))
    name = m['allocate'](64) + 1
    m['put'](name, clauses.TYPE_NAME + b'\0')
    m['put'](m['base'] + clauses.TABLE - 16, struct.pack('<qQ', 0, m['base'] + clauses.TYPE_INFO))
    m['q'](m['base'] + clauses.TYPE_INFO + 8, name)
    for offset, target in ((0x18, 0x18043D4), (0x28, 0x1804AA4), (0x98, 0x180459C), (0xA8, 0x180481C)):
        m['q'](m['base'] + clauses.TABLE + offset, m['base'] + target)
    m['put'](m['first_clause'], row(m['base'], m['other_club']))
    m['put'](m['self_clause'], row(m['base'], m['club'], percentage=-1, override=15))
    return m


def test_literal_owner_slots_aliases_and_unknown_payment_state(sell_on_memory):
    m = sell_on_memory
    before = dict(m['cells'])
    report = clauses.decode(m['read'], m['base'], m['club'])
    assert report['state'] == 'decoded'
    assert report['source_slot_count'] == 5
    assert report['null_source_slot_count'] == report['other_clause_slot_count'] == 1
    assert [r['slot'] for r in report['records']] == [0, 3, 4]
    first, second, alias = report['records']
    assert first['recorded_container_owner'] == report['selected_club']
    assert first['native_basis_amount']['native_signed32'] == 100000
    assert first['native_basis_used']['native_signed32'] == 40000
    assert first['native_percentage'] == 20 and first['native_flags'] == 255
    assert second['native_percentage'] == -1 and second['native_override_percentage'] == 15
    assert first['native_person_reference']['native_id'] == 1234
    assert first['amount_due_now'] is first['next_payment_due_date'] is None
    assert first['payment_state'] == 'not_established'
    assert alias['native_basis_used'] == first['native_basis_used']
    assert m['cells'] == before


@pytest.mark.parametrize(('cash', 'basis', 'used', 'percent', 'override', 'category', 'amount', 'after'), [
    (500, 100000, 40000, 20, 0, 2, None, 40000),
    (501, 100000, 40000, 20, 0, 2, 0, 40501),
    (160000, 100000, 40000, 20, 0, 2, 20000, 100000),
    (160000, 100000, 40000, 20, 15, 2, 15000, 100000),
    (160000, 100000, 40000, 20, 15, 1, 20000, 100000),
    (160000, 100000, 40000, -1, 0, 2, 0, 100000),
    (160000, 100000, 40000, 127, 0, 2, 127000, 100000),
    (1000, 0, 0, 1, 0, 2, 10, 0),
    (1000, 0, 1000, 20, 0, 2, 400, 0),
    (2147483647, 0, 0, 127, 0, 2, 2147483647, 0),
])
def test_conditional_native_scalar_branch(cash, basis, used, percent, override, category, amount, after):
    raw = row(0x10000000, 0x20000000, basis, used, percent, override)
    result = clauses.project_native_allocation(raw, cash, category)
    assert result['native_recursive_call_amount'] == amount
    assert result['native_basis_used_after'] == after
    assert result['actual_cash_payment'] is result['final_recipient_net_cash'] is None
    assert result['full_native_selection_evaluated'] is False


@pytest.mark.parametrize('cash', [-2147483648, -1, 0, 1, 499, 500])
def test_skipped_branch_does_not_mutate_basis_or_claim_zero_payment(cash):
    result = clauses.project_native_allocation(row(0, 0), cash)
    assert result['native_recursive_call_amount'] is None
    assert result['native_basis_used_after'] == 40000


@pytest.mark.parametrize('value', [True, 1.5, 2147483648, -2147483649])
def test_native_argument_domain_is_explicit(value):
    with pytest.raises(ValueError):
        clauses.project_native_allocation(row(0, 0), value)
    with pytest.raises(ValueError):
        clauses.project_native_allocation(row(0, 0), 1000, value)


def test_missing_empty_and_null_recipient_are_distinct(sell_on_memory):
    m = sell_on_memory
    m['q'](m['club'] + 0xB0, 0)
    assert clauses.decode(m['read'], m['base'], m['club'])['records'] is None
    m['q'](m['club'] + 0xB0, m['clause_holder'])
    m['vec'](m['clause_holder'], [])
    assert clauses.decode(m['read'], m['base'], m['club'])['records'] == []
    m['put'](m['first_clause'], row(m['base'], 0))
    m['vec'](m['clause_holder'], [m['first_clause']])
    record = clauses.decode(m['read'], m['base'], m['club'])['records'][0]
    assert record['recorded_recipient'] is None


@pytest.mark.parametrize('fault', ['source', 'dispatch', 'rtti', 'container', 'recipient'])
def test_source_and_canonical_bindings_fail_closed(sell_on_memory, fault):
    m = sell_on_memory
    if fault == 'source':
        m['put'](m['base'] + clauses.SOURCE[0][0], b'\0')
    elif fault == 'dispatch':
        m['q'](m['base'] + clauses.TABLE + 0x28, 0)
    elif fault == 'rtti':
        m['q'](m['base'] + clauses.TABLE - 8, 0)
    elif fault == 'container':
        m['q'](m['club'] + 0xB0, 123)
    else:
        m['put'](m['other_club'] + 8, struct.pack('<I', 0))
    with pytest.raises(ValueError):
        clauses.decode(m['read'], m['base'], m['club'])


@pytest.mark.parametrize('field', ['basis', 'flags', 'owner', 'recipient', 'other_family', 'dispatch'])
def test_final_physical_recheck_covers_consumed_fields(sell_on_memory, field):
    m = sell_on_memory
    reads = world.ReadSet(m['read'])
    clauses.decode(reads, m['base'], m['club'])
    at = {'basis': m['first_clause'] + 28, 'flags': m['first_clause'] + 36,
          'owner': m['club'] + 0xB0, 'recipient': m['other_club'] + 12,
          'other_family': m['other_clause'], 'dispatch': m['base'] + clauses.TABLE + 0x28}[field]
    m['put'](at, bytes([m['read'](at, 1)[0] ^ 1]))
    with pytest.raises(ValueError, match='changed during read'):
        reads.verify()
