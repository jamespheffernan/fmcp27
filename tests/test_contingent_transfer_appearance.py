import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import contingent_transfer_appearance as clauses, world
from test_club_debt_obligations import debt_memory
from test_club_finance import finance_memory
from test_database import database_memory
from test_players import memory
from test_retained_transfer_debt import transfer_memory
from test_world import world_memory


def row(base, recipient, amount=150000, target=20, count=8, kind=0):
    return struct.pack('<QIIQiHHb', base + clauses.TABLE, 1234, 1234, recipient, amount, target, count, kind)


@pytest.fixture
def appearance_memory(transfer_memory):
    m = transfer_memory
    source = json.loads((Path(__file__).parents[1] / 'evidence/contingent-transfers-20261109/source-bytes.json').read_text())
    for span in source['spans']:
        m['put'](m['base'] + span['rva'], bytes.fromhex(span['hex']))
    binding_source = json.loads((Path(__file__).parents[1] / 'evidence/finance-person-bindings-20261109/source-bytes.json').read_text())
    for span in binding_source['spans']:
        m['put'](m['base'] + span['rva'], bytes.fromhex(span['hex']))
    m['put'](m['roots']['people'] + 0x64, b'\0')
    name = m['allocate'](64) + 1
    m['put'](name, clauses.TYPE_NAME + b'\0')
    m['put'](m['base'] + clauses.TABLE - 16, struct.pack('<qQ', 0, m['base'] + clauses.TYPE_INFO))
    m['q'](m['base'] + clauses.TYPE_INFO + 8, name)
    for offset, target in ((0x28, 0x1812D44), (0xB0, 0x1812D4C), (0x98, 0x1805118), (0xA8, 0x18053A8)):
        m['q'](m['base'] + clauses.TABLE + offset, m['base'] + target)
    holder = m['allocate'](24)
    m['q'](m['club'] + 0xB0, holder)
    first, second, unrelated = (m['allocate'](40) for _ in range(3))
    m['put'](first, row(m['base'], m['other_club']))
    m['put'](second, row(m['base'], m['club'], count=19, kind=4))
    m['q'](unrelated, m['base'] + 0x1234560)
    m['vec'](holder, [first, 0, unrelated, second, first])
    m.update(clause_holder=holder, first_clause=first, self_clause=second, other_clause=unrelated)
    return m


def test_owner_bound_rows_preserve_aliases_nulls_other_families_and_progress(appearance_memory):
    m = appearance_memory
    before = dict(m['cells'])
    report = clauses.decode(m['read'], m['base'], m['club'])
    assert report['state'] == 'decoded'
    assert report['source_slot_count'] == 5
    assert report['null_source_slot_count'] == report['other_clause_slot_count'] == 1
    assert [r['slot'] for r in report['records']] == [0, 3, 4]
    first, self_row, alias = report['records']
    assert first['recorded_payer'] == report['selected_club']
    assert first['recorded_recipient']['native_id'] != first['recorded_payer']['native_id']
    assert first['native_call_amount'] == {'amount': 150000, 'native_signed32': 150000, 'currency': 'GBP', 'state': 'native_call_argument'}
    assert first['native_trigger_progress']['remaining_to_target'] == 12
    assert first['native_trigger_progress']['comparison'] == 'below'
    assert first['native_trigger_progress']['full_trigger_eligibility'] == 'not_evaluated'
    assert first['native_person_reference']['native_id'] == 1234
    assert first['native_event_kind']['name'] is None
    assert first['payment_state'] == 'not_established'
    assert first['amount_due_now'] is first['next_payment_due_date'] is None
    assert self_row['direction'] == 'self' and alias['native_call_amount'] == first['native_call_amount']
    assert report['incoming_scanned'] is report['complete_liability_ledger'] is False
    assert m['cells'] == before


@pytest.mark.parametrize(('kind', 'rule'), [(0, 'native_counter_threshold'), (1, 'native_counter_threshold'),
    (4, 'native_counter_threshold'), (2, 'each_qualified_native_event_until_counter_limit'),
    (3, 'native_event_increment_threshold'), (-1, 'unmapped_native_event_kind'), (127, 'unmapped_native_event_kind')])
def test_unknown_event_labels_do_not_suppress_proved_amounts_or_counters(kind, rule):
    result = clauses.describe(row(0x10000000, 0x20000, kind=kind))
    assert result['native_call_amount']['amount'] == 150000
    assert result['native_trigger_progress']['count'] == 8
    assert result['native_trigger_progress']['cash_rule'] == rule
    assert result['native_event_kind']['name'] is None


@pytest.mark.parametrize(('count', 'comparison', 'remaining', 'visible'), [(0, 'below', 20, True),
    (19, 'below', 1, True), (20, 'equal', 0, False), (21, 'above', None, False), (65535, 'above', None, False)])
def test_threshold_comparison_does_not_become_paid_or_full_trigger_eligibility(count, comparison, remaining, visible):
    result = clauses.describe(row(0x10000000, 0x20000, count=count))
    progress = result['native_trigger_progress']
    assert (progress['comparison'], progress['remaining_to_target'], progress['native_report_count_amount_predicate']) == (comparison, remaining, visible)
    assert progress['full_trigger_eligibility'] == 'not_evaluated'
    assert result['payment_state'] == 'not_established'


@pytest.mark.parametrize('amount', [-1, -2147483648, 2147483647])
def test_unclassified_amount_retains_native_bits_and_independent_progress(amount):
    result = clauses.describe(row(0x10000000, 0x20000, amount=amount))
    assert result['native_call_amount']['amount'] is None
    assert result['native_call_amount']['native_signed32'] == amount
    assert result['native_trigger_progress']['count'] == 8


def test_missing_container_empty_source_and_null_recipient_are_distinct(appearance_memory):
    m = appearance_memory
    m['q'](m['club'] + 0xB0, 0)
    report = clauses.decode(m['read'], m['base'], m['club'])
    assert report['state'] == 'unavailable' and report['records'] is None
    m['q'](m['club'] + 0xB0, m['clause_holder'])
    m['vec'](m['clause_holder'], [])
    report = clauses.decode(m['read'], m['base'], m['club'])
    assert report['state'] == 'decoded' and report['records'] == [] and report['source_slot_count'] == 0
    m['put'](m['first_clause'], row(m['base'], 0))
    m['vec'](m['clause_holder'], [m['first_clause']])
    record = clauses.decode(m['read'], m['base'], m['club'])['records'][0]
    assert record['recorded_recipient'] is None and record['recipient_state'] == 'native_null_recipient'


@pytest.mark.parametrize('fault', ['native_source', 'dispatch', 'rtti', 'container', 'recipient_membership'])
def test_bad_source_or_owner_bindings_fail_closed(appearance_memory, fault):
    m = appearance_memory
    if fault == 'native_source':
        m['put'](m['base'] + clauses.SOURCE[0][0], b'\0')
    elif fault == 'dispatch':
        m['q'](m['base'] + clauses.TABLE + 0xB0, 0)
    elif fault == 'rtti':
        m['q'](m['base'] + clauses.TABLE - 8, 0)
    elif fault == 'container':
        m['q'](m['club'] + 0xB0, 123)
    else:
        m['put'](m['other_club'] + 8, struct.pack('<I', 0))
    with pytest.raises(ValueError):
        clauses.decode(m['read'], m['base'], m['club'])


@pytest.mark.parametrize('field', ['row', 'container', 'owner_link', 'recipient', 'type', 'other_family'])
def test_every_consumed_family_requires_a_final_physical_recheck(appearance_memory, field):
    m = appearance_memory
    read = world.ReadSet(m['read'])
    clauses.decode(read, m['base'], m['club'])
    address = {'row': m['first_clause'] + 30, 'container': m['clause_holder'],
               'owner_link': m['club'] + 0xB0, 'recipient': m['other_club'] + 12,
               'type': m['base'] + clauses.TABLE + 0x28, 'other_family': m['other_clause']}[field]
    m['put'](address, bytes([m['read'](address, 1)[0] ^ 1]))
    with pytest.raises(ValueError, match='changed during read'):
        read.verify()
