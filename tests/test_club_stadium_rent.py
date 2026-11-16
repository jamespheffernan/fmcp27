"""Source-pinned typed annual-rent cash controls; no process/game access."""
import hashlib
from pathlib import Path
import struct

import pytest

from fm_live_mcp import club_stadium_rent as source, world
from test_club_finance import finance_memory
from test_database import database_memory
from test_players import memory
from test_world import world_memory

import _pinned_build
BINARY = _pinned_build.PLUGIN


@pytest.fixture(scope='module')
def native():
    spans, slots = {}, {}
    with BINARY.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == source.PLUGIN_SHA256
        for rva, expected in source.NATIVE_SPANS:
            stream.seek(0x5ED4000 + rva)
            raw = stream.read(len(expected))
            assert raw == expected
            spans[rva] = raw
        for kind, getter in source.GETTERS.items():
            slot = world.TYPES[kind][0] + source.RENT_SLOT
            stream.seek(0x5ED4000 + slot)
            assert struct.unpack('<Q', stream.read(8))[0] & ((1 << 36) - 1) == getter
            slots[slot] = getter
    return spans, slots


@pytest.fixture
def case(finance_memory, native):
    m = finance_memory
    for rva, raw in native[0].items():
        m['put'](m['base'] + rva, raw)
    for slot, getter in native[1].items():
        m['q'](m['base'] + slot, m['base'] + getter)
    m['binding'] = source.ClubBinding(m['club'], 0, 688, 688)
    m['put'](m['finance'] + 0x7F0, struct.pack('<i', 15000000))
    m['put'](m['finance'] + 0x7F4, struct.pack('<i', 12000000))
    m['put'](m['finance'] + 0x7F8, struct.pack('<i', 975321))
    return m


def read(m, **kwargs):
    return source.read_annual_rent(kwargs.get('read', m['read']), m['base'],
                                  kwargs.get('binding', m['binding']))


@pytest.mark.parametrize('value', [0, 1, 975321, 2147483647, -1, -2147483648])
def test_exact_native_signed_cash_in_whole_gbp_per_year(case, value):
    m = case
    m['put'](m['finance'] + 0x7F8, struct.pack('<i', value))
    result = read(m)
    assert result['amount'] == value
    assert result['currency'] == 'GBP' and result['period'] == 'year'
    assert result['reason'] == 'native_stored_annual_rent'
    assert result['native_property'] == 'Csry'
    assert result['club_native_identity'] == dict(database_index=0, native_id=688, raw_secondary_id=688)
    assert result['native_functions_executed'] is result['game_writes'] is False
    assert result['freshness'] == 'stored_without_refresh'


def test_getter_offset_is_7f8_not_nearby_cash_or_wage_fields(case):
    m = case
    assert read(m)['amount'] == 975321
    m['put'](m['finance'] + 0x7F0, struct.pack('<i', 1))
    m['put'](m['finance'] + 0x7F4, struct.pack('<i', 2))
    assert read(m)['amount'] == 975321
    m['put'](m['finance'] + 0x7F8, struct.pack('<i', 400001))
    assert read(m)['amount'] == 400001
    assert struct.unpack('<i', m['read'](m['finance'] + 0x808, 4))[0] == 6000000


def test_typed_base_finance_replays_zero_leaf_without_reading_nonexistent_field(case):
    m = case
    basic = m['typed']('club_finance_base', 0x38)
    m['q'](m['club'] + 0x150, basic)
    consumed = []
    def recording(address, size):
        consumed.append((address, size))
        return m['read'](address, size)
    result = read(m, read=recording)
    assert result['state'] == 'decoded' and result['amount'] == 0
    assert result['currency'] == 'GBP'
    assert result['reason'] == 'native_base_finance_literal_zero'
    assert (basic + 0x7F8, 4) not in consumed


def test_missing_finance_is_unavailable_not_a_native_zero_or_currency_guess(case):
    m = case
    m['q'](m['club'] + 0x150, 0)
    m['put'](m['currency'] + 0x38, struct.pack('<f', 1.5))
    result = read(m)
    assert result['state'] == 'unavailable' and result['reason'] == 'no_finance_record'
    assert result['amount'] is result['currency'] is None


@pytest.mark.parametrize('fault', ['club_type', 'club_index', 'club_id', 'club_secondary',
    'club_slot', 'club_bounds', 'finance_type', 'finance_pointer', 'finance_rtti'])
def test_malformed_owner_type_and_identity_fail_near_positive(case, fault):
    m = case
    assert read(m)['amount'] == 975321
    if fault == 'club_type': m['q'](m['club'], m['base'] + world.TYPES['team'][0])
    if fault == 'club_index': m['put'](m['club'] + 8, struct.pack('<I', 1))
    if fault == 'club_id': m['put'](m['club'] + 12, struct.pack('<I', 689))
    if fault == 'club_secondary': m['put'](m['club'] + 16, bytes(4))
    if fault == 'club_slot': m['vec'](m['headers']['clubs'], [m['team']])
    if fault == 'club_bounds': m['put'](m['headers']['clubs'], struct.pack('<QQQ', 8192, 4096, 8192))
    if fault == 'finance_type': m['q'](m['finance'], m['base'] + world.TYPES['club'][0])
    if fault == 'finance_pointer': m['q'](m['club'] + 0x150, m['finance'] + 1)
    if fault == 'finance_rtti': m['put'](m['base'] + world.TYPES['club_finance'][0] - 16, struct.pack('<q', 8))
    with pytest.raises(ValueError): read(m)


def test_selected_other_canonical_club_cannot_silently_replace_owner(case):
    m = case
    other = m['typed']('club', 0x170)
    m['put'](other + 8, struct.pack('<III', 1, 111, 222))
    m['q'](other + 0x150, m['finance'])
    m['vec'](m['headers']['clubs'], [m['club'], other])
    assert read(m)['amount'] == 975321
    with pytest.raises(ValueError, match='selected CLUB identity'):
        read(m, binding=source.ClubBinding(other, 0, 688, 688))
    assert read(m, binding=source.ClubBinding(other, 1, 111, 222))['club_native_identity']['native_id'] == 111


@pytest.mark.parametrize('rva,expected', source.NATIVE_SPANS)
def test_changed_csry_comparison_caller_or_leaf_rejects_positive(case, rva, expected):
    m = case
    assert read(m)['amount'] == 975321
    m['put'](m['base'] + rva, bytes([expected[0] ^ 1]))
    with pytest.raises(ValueError, match='native property changed'): read(m)


@pytest.mark.parametrize('kind,slot', [('club', 24), ('game_club', 176),
                                    ('club_finance', 0x380), ('club_finance_base', 0x380)])
def test_wrong_typed_virtual_target_rejects_without_calling_it(case, kind, slot):
    m = case
    assert read(m)['amount'] == 975321
    m['q'](m['base'] + world.TYPES[kind][0] + slot, 0)
    with pytest.raises(ValueError, match='virtual dispatch'): read(m)


@pytest.mark.parametrize('target', ['cash', 'owner_pointer', 'identity', 'table', 'native', 'currency'])
def test_consumed_bytes_are_rechecked_and_drift_fails(case, target):
    m = case
    address, size = {
        'cash': (m['finance'] + 0x7F8, 4), 'owner_pointer': (m['club'] + 0x150, 8),
        'identity': (m['club'] + 8, 12), 'table': (m['headers']['clubs'], 24),
        'native': (m['base'] + 0xEB8768, 8), 'currency': (m['currency'] + 0x38, 4),
    }[target]
    count = 0
    def changing(at, length):
        nonlocal count
        raw = m['read'](at, length)
        if (at, length) == (address, size):
            count += 1
            if count > 1:
                return bytes([raw[0] ^ 1]) + raw[1:]
        return raw
    with pytest.raises(ValueError): read(m, read=changing)


@pytest.mark.parametrize('fault', ['base_mapping', 'currency_rate', 'currency_name'])
def test_native_cash_unit_requires_actual_checked_base_currency(case, fault):
    m = case
    if fault == 'base_mapping': m['put'](m['base'] + 0x538EF50, struct.pack('<I', 87))
    if fault == 'currency_rate': m['put'](m['currency'] + 0x38, struct.pack('<f', 1.5))
    if fault == 'currency_name': m['q'](m['currency'] + 0x18, m['text']('US Dollar'))
    with pytest.raises(ValueError): read(m)


@pytest.mark.parametrize('kind', ['club', 'club_finance', 'club_finance_base'])
def test_native_rtti_character_pointers_need_not_be_object_aligned(case, kind):
    m = case
    if kind == 'club_finance_base':
        m['q'](m['club'] + 0x150, m['typed'](kind, 0x38))
    table, name = world.TYPES[kind]
    info = m['allocate'](16)
    text = m['allocate'](len(name) + 2) + 1
    m['put'](text, name + b'\0')
    m['q'](info + 8, text)
    m['put'](m['base'] + table - 16, struct.pack('<qQ', 0, info))
    assert read(m)['amount'] == (0 if kind == 'club_finance_base' else 975321)


@pytest.mark.parametrize('values', [(True, 0, 1, 1), (0x1000, True, 1, 1),
                                   (0x1000, 0, 0, 1), (0x1000, 0xFFFFFFFF, 1, 1)])
def test_binding_refuses_boolean_or_missing_canonical_identity(values):
    with pytest.raises(ValueError): source.ClubBinding(*values)


@pytest.mark.parametrize('base', [True, 0, 4097, 1 << 64, (1 << 64) - 4096])
def test_invalid_native_base_rejects_before_any_read(base):
    def forbidden_read(address, size):
        raise AssertionError('Malformed native base reached memory reader')
    with pytest.raises(ValueError, match='native base'):
        source.verify_native(forbidden_read, base)


@pytest.mark.parametrize('pointer', [1, (1 << 64) - 8])
def test_invalid_finance_pointer_rejects_before_dereference(case, pointer):
    m = case
    m['q'](m['club'] + 0x150, pointer)
    def checked(address, size):
        if address == pointer:
            raise AssertionError('Malformed finance pointer was dereferenced')
        return m['read'](address, size)
    with pytest.raises(ValueError, match='finance pointer'):
        read(m, read=checked)
