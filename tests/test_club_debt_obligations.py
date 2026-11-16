from datetime import date, timedelta
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import club_debt_obligations as debt, world
from test_club_finance import finance_memory
from test_database import database_memory
from test_players import memory
from test_world import world_memory


SOURCE = json.loads((Path(__file__).parents[1] / 'evidence/obligations-20261109/source-bytes.json').read_text())


def packed(value):
    return struct.pack('<HH', value.timetuple().tm_yday, value.year)


ASOF = date(2031, 1, 1)


def row(*, days=365, original=100000, monthly=1000, interest=100, source=1, interest_only=0):
    return (struct.pack('<4i', original, monthly, interest, 700)
            + packed(ASOF + timedelta(days=days)) + packed(date(2020, 1, 1))
            + bytes([source, 1, interest_only]))


@pytest.fixture
def debt_memory(finance_memory):
    m = finance_memory
    for span in SOURCE['spans']:
        m['put'](m['base'] + span['rva'], bytes.fromhex(span['hex']))
    m['put'](m['base'] + world.CURRENT_DATE, packed(ASOF))
    extension = m['allocate'](0x200)
    loan = m['allocate'](32)
    m['q'](m['club'] + 0x100, extension)
    m['put'](loan, row())
    m['vec'](extension + 0x50, [loan])
    m.update(extension=extension, loan=loan)
    return m


@pytest.mark.parametrize(('days', 'expected'), [(-365, 0), (0, 0), (1, 900), (29, 900),
    (30, 900), (59, 900), (60, 1800), (365, 10800), (5000, 100000)])
def test_native_thirty_day_floor_minimum_and_original_cap(days, expected):
    result = debt.loan_projection(row(days=days), packed(ASOF), 3)
    assert result['remaining_debt']['amount'] == expected
    assert result['remaining_debt']['native_signed32'] == expected
    assert result['remaining_debt']['payment_state'] == 'not_established'
    assert result['next_payment_due_date'] is None
    assert result['counterparty'] is None


@pytest.mark.parametrize('source', [8, 10, 11, 13, 14])
@pytest.mark.parametrize('days', [-365, 0, 365])
def test_native_conditional_and_pik_sources_retain_original(source, days):
    remaining = debt.loan_projection(row(source=source, days=days), packed(ASOF), 0)['remaining_debt']
    assert remaining['amount'] == 100000
    assert remaining['branch'] == 'native_source_retains_original'


@pytest.mark.parametrize('source', [1, 2, 7, 9, 12, 15])
def test_other_sources_do_not_inherit_conditional_retention(source):
    remaining = debt.loan_projection(row(source=source, days=-1), packed(ASOF), 0)['remaining_debt']
    assert remaining['amount'] == 0
    assert remaining['branch'] == 'native_monthly_principal_capped_at_original'


def test_interest_only_retains_original_after_end():
    result = debt.loan_projection(row(days=-100, interest_only=1), packed(ASOF), 0)
    assert result['remaining_debt']['amount'] == 100000
    assert result['remaining_debt']['branch'] == 'native_interest_only_retains_original'


@pytest.mark.parametrize(('fields', 'state', 'native'), [
    ({'monthly': 50, 'interest': 100}, 'negative_native_value', -600),
    ({'monthly': 2**31-1, 'interest': -1}, 'native_signed32_wrap', 0),
    ({'monthly': 2**30, 'interest': 0}, 'native_signed32_wrap', 0),
    ({'original': 2**31-1}, 'unclassified_native_limit', 10800),
])
def test_native_negative_wrap_and_limit_are_not_plausible_cash(fields, state, native):
    result = debt.loan_projection(row(**fields), packed(ASOF), 0)['remaining_debt']
    assert result['state'] == state
    assert result['native_signed32'] == native
    assert result['amount'] is None


@pytest.mark.parametrize('source', [0, 16, 255])
def test_unknown_english_source_label_does_not_hide_proved_native_numeric_branch(source):
    result = debt.loan_projection(row(source=source), packed(ASOF), 0)
    assert result['source_name'] is None and result['source_name_state'] == 'unmapped_enum'
    assert result['remaining_debt']['amount'] == 10800
    assert result['remaining_debt']['state'] == 'native_schedule_calculation'
    assert result['remaining_debt']['branch'] == 'native_monthly_principal_capped_at_original'
    assert result['remaining_debt']['payment_state'] == 'not_established'
    assert result['counterparty'] is None and result['next_payment_due_date'] is None


def test_unknown_end_date_does_not_turn_into_settled_zero():
    raw = bytearray(row())
    raw[16:20] = packed(date(1900, 1, 1))
    result = debt.loan_projection(raw, packed(ASOF), 0)['remaining_debt']
    assert result['native_signed32'] == 0
    assert result['state'] == 'unknown_end_date' and result['amount'] is None
    raw[24] = 13
    assert debt.loan_projection(raw, packed(ASOF), 0)['remaining_debt']['amount'] == 100000
    raw[16:20] = bytes(4)
    result = debt.loan_projection(raw, packed(ASOF), 0)['remaining_debt']
    assert result['state'] == 'unsupported_date' and result['native_signed32'] is None


def test_unmapped_date_flags_are_preserved_but_masked_by_original_calculation():
    raw = bytearray(row())
    day = int.from_bytes(raw[16:18], 'little')
    struct.pack_into('<H', raw, 16, day | 0xFE00)
    result = debt.loan_projection(raw, packed(ASOF), 0)
    assert result['end_date']['unmapped_low_word_flags'] == 0xFE00
    assert result['remaining_debt']['amount'] == 10800


def test_owner_bound_projection_and_positive_original_source(debt_memory):
    m = debt_memory
    result = debt.decode(m['read'], m['base'], m['club'])
    assert result['financial_owner'] == result['selected_club']
    assert result['state'] == 'decoded' and result['currency'] == 'GBP'
    assert result['records'][0]['remaining_debt']['amount'] == 10800
    assert not result['complete_liability_ledger']
    assert result['records'][0]['monthly_repayment'] == 1000
    assert result['records'][0]['conditional_repayment'] == 700
    assert result['as_of_date'] == '2031-01-01'


@pytest.mark.parametrize('code', range(22))
def test_financial_owner_matches_native_relationship_mask(debt_memory, code):
    m = debt_memory
    parent = m['typed']('club', 0x170)
    m['put'](parent + 8, struct.pack('<III', 1, 4321, 9876))
    for offset in (0xC0, 0xC8):
        m['q'](parent + offset, m['text']('Debt parent'))
    m['q'](parent + 0x150, m['finance'])
    m['q'](parent + 0x100, m['extension'])
    m['vec'](m['headers']['clubs'], [m['club'], parent])
    relation = m['allocate'](0x38)
    m['q'](relation, parent)
    m['q'](relation + 8, m['club'])
    m['put'](relation + 0x30, bytes([code]))
    m['vec'](m['club'] + 0x118, [relation])
    m['put'](m['club'] + 0x163, b'\0')
    result = debt.decode(m['read'], m['base'], m['club'])
    qualifying = code <= 20 and bool((1 << code) & 0x1001F0)
    assert result['financial_owner']['database_index'] == (1 if qualifying else 0)


def test_null_first_matching_owner_falls_back_without_searching_later(debt_memory):
    m = debt_memory
    relations = [m['allocate'](0x38) for _ in range(2)]
    for relation in relations:
        m['q'](relation + 8, m['club'])
        m['put'](relation + 0x30, b'\x04')
    m['q'](relations[1], 0xBAD0)
    m['vec'](m['club'] + 0x118, relations)
    m['put'](m['club'] + 0x163, b'\0')
    result = debt.decode(m['read'], m['base'], m['club'])
    assert result['financial_owner'] == result['selected_club']
    assert result['owner_relationship']['null_parent_fallback']


def test_first_ten_physical_slots_preserve_duplicates_and_exclude_extra_rows(debt_memory):
    m = debt_memory
    m['vec'](m['extension'] + 0x50, [m['loan']] * 10 + [0xBAD0])
    result = debt.decode(m['read'], m['base'], m['club'])
    assert len(result['records']) == 10
    assert [r['slot'] for r in result['records']] == list(range(10))
    assert result['source_slot_count'] == 11 and result['outside_report_slot_count'] == 1
    assert all(r['remaining_debt']['amount'] == 10800 for r in result['records'])


def test_null_source_slot_is_partial_not_empty_or_zero(debt_memory):
    m = debt_memory
    m['vec'](m['extension'] + 0x50, [0, m['loan']])
    result = debt.decode(m['read'], m['base'], m['club'])
    assert result['state'] == 'partial_null_source_slot'
    assert result['records'][0]['remaining_debt'] is None
    assert result['records'][1]['remaining_debt']['amount'] == 10800


def test_empty_source_is_distinct_from_missing_source(debt_memory):
    m = debt_memory
    m['vec'](m['extension'] + 0x50, [])
    result = debt.decode(m['read'], m['base'], m['club'])
    assert result['state'] == 'decoded' and result['records'] == []
    m['q'](m['club'] + 0x100, 0)
    result = debt.decode(m['read'], m['base'], m['club'])
    assert result['state'] == 'unavailable' and result['records'] is None
    assert result['source_slot_count'] is None


@pytest.mark.parametrize('basic', [False, True])
def test_missing_and_base_finance_do_not_imply_no_debt(debt_memory, basic):
    m = debt_memory
    finance = m['typed']('club_finance_base', 0x38) if basic else 0
    m['q'](m['club'] + 0x150, finance)
    result = debt.decode(m['read'], m['base'], m['club'])
    assert result['state'] == 'unavailable' and result['records'] is None
    assert result['source_slot_count'] is None and result['currency'] is None


@pytest.mark.parametrize('target', ['row', 'date', 'extension', 'vector', 'club_identity', 'source'])
def test_consumed_sources_must_survive_request_final_physical_recheck(debt_memory, target):
    m = debt_memory
    snapshot = world.ReadSet(m['read'])
    debt.decode(snapshot, m['base'], m['club'])
    address = {'row': m['loan'], 'date': m['base'] + world.CURRENT_DATE,
               'extension': m['club'] + 0x100, 'vector': m['extension'] + 0x50,
               'club_identity': m['club'] + 12, 'source': m['base'] + debt.SOURCE[0][0]}[target]
    original = m['read'](address, 1)
    m['put'](address, bytes([original[0] ^ 1]))
    with pytest.raises(ValueError, match='changed during read'):
        snapshot.verify()


@pytest.mark.parametrize('fault', ['source', 'discriminator', 'club_membership', 'club_rtti', 'boolean',
                                  'vector', 'date', 'owner_null_relation'])
def test_changed_or_malformed_owning_sources_fail_closed(debt_memory, fault):
    m = debt_memory
    if fault == 'source':
        m['put'](m['base'] + debt.SOURCE[0][0], b'\0')
    elif fault == 'discriminator':
        m['q'](m['base'] + world.TYPES['club_finance'][0] + 0x40, 0)
    elif fault == 'club_membership':
        m['vec'](m['headers']['clubs'], [m['finance']])
    elif fault == 'club_rtti':
        m['q'](m['club'], 0)
    elif fault == 'boolean':
        m['put'](m['loan'] + 26, b'\x02')
    elif fault == 'vector':
        m['put'](m['extension'] + 0x50, struct.pack('<QQQ', 0x1000, 0x1009, 0x1010))
    elif fault == 'date':
        m['put'](m['base'] + world.CURRENT_DATE, b'\0' * 4)
    else:
        m['put'](m['club'] + 0x163, b'\0')
        m['vec'](m['club'] + 0x118, [0])
    with pytest.raises(ValueError):
        debt.decode(m['read'], m['base'], m['club'])
