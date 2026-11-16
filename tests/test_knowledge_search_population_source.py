"""Synthetic source/identity semantics only; no live population or mode proof."""
from _knowledge_stream_fixture import native_stream_transport
import struct

import pytest

from fm_live_mcp import knowledge_search_population_source as source, players, world
from prepared_tactics_fixture import (prepared_tactics_memory, team_memory,
                                     database_memory, memory, world_memory)
from test_shortlist_members import member_memory


@pytest.fixture
def population_memory(prepared_tactics_memory, member_memory):
    m = prepared_tactics_memory
    assert m is member_memory
    base, human = m['base'], m['manager']
    for rva, raw in source.NATIVE_SPANS:
        m['put'](base + rva, raw)
    m['put'](base + world.TYPES['manager'][0] - 0x20, struct.pack('<qq', 0x548, 0x438))
    m['typed_at'](human + 0x438, source.HUMAN_DATA_VTABLE,
                  world.TYPES['manager'][1], -0x438)
    for rva, slot, getter in ((0x55AD820, 0x230, 0xCA4744),
                              (0x55AD820, 0x3C8, 0xCB3724),
                              (0x55AD820, 0x408, 0xC8CF20),
                              (source.HUMAN_DATA_VTABLE, 0x438, 0x12FFE58)):
        m['q'](base + rva + slot, base + getter)
    for rva, slot, value in ((0x55AD820, -0x3D8, -0x110),
                             (0x55AD820, -0x418, -0x548),
                             (source.HUMAN_DATA_VTABLE, -0x450, -0x438)):
        m['put'](base + rva + slot, struct.pack('<q', value))

    def contract(kind='full_contract', team=None, marker=0, category=2):
        address = m['typed'](kind, 0x100)
        m['q'](address + 8, human + 0x548)
        m['q'](address + 0x10, m['team'] if team is None else team)
        m['q'](address + 0x18, m['team'] if team is None else team)
        m['put'](address + 0x26, bytes([marker]))
        m['put'](address + 0xC2, bytes([category]))
        m['q'](base + world.TYPES[kind][0] + 0x70,
               base + (0x129A4B8 if kind == 'full_contract' else 0xD88C6C))
        return address

    primary_contract = contract()
    m['q'](human + 0x4B0, primary_contract)
    m['put'](m['team'] + 0x2F, b'\0')
    m['put'](m['club'] + 0xB9, b'\0')
    m['put'](base + 0x56D4992, b'\x01')
    m['put'](base + 0x56D4993, b'\0')
    m['put'](base + 0x56D4980, b'\x01')

    combined, combined_person = m['add_person']('player_staff', 1, 77, 88)
    m['vec'](m['headers']['people'], [0x1388, combined_person])
    for person_rva, offset in ((players.RVA[2], 0x388), (players.STAFF_RVA[2], 0x480)):
        m['q'](base + person_rva + 0x6E0, base + 0xD5C610)
        m['put'](base + person_rva - 0x6F0, struct.pack('<q', -offset))

    lists = []
    for kind in (1, 3, 2):
        listing = m['allocate'](0x108)
        m['q'](listing + 0xD0, human)
        m['put'](listing + 0x4C, bytes([kind]))
        m['put'](listing + 0x101, b'\x01')
        lists.append(listing)
    m['vec'](human + 0x248, lists)
    m['put'](human + 0x42B, b'\x01')  # Wrong kind at index1 falls back to kind1 at0.
    m['put'](human + 0x41F, b'\x03')
    m['vec'](base + source.BASE_VECTORS['all_actual'], [0x1000, combined])
    m['vec'](base + source.BASE_VECTORS['split_0'], [0x1000])
    m['vec'](base + source.BASE_VECTORS['split_1'], [combined])

    def secondary(team_index=1, code=1):
        owner = m['owners'][team_index]
        m['put'](owner + 0xB9, bytes([code]))
        extra = m['allocate'](0x18)
        secondary_contract = contract(team=m['team_addresses'][team_index])
        m['q'](extra + 0x10, secondary_contract)
        m['q'](human + 0x438 + 0x80, extra)
        m['put'](base + 0x56D4993, b'\x01')
        return secondary_contract

    m.update(search_lists=lists, primary_contract=primary_contract, new_contract=contract,
             add_secondary=secondary, combined=combined, combined_person=combined_person)
    return m


def observe(m, *, read=None, check_current=lambda: ('synthetic-process', 'save-epoch', 'build'), **kwargs):
    return source.observe(read or m['read'], m['base'], m['coach'],
                          check_current=check_current, **kwargs)


def test_complete_split_source_uses_kind_fallback_and_labels_unrestricted_bypass(population_memory):
    m = population_memory
    result = observe(m)
    assert result['vector'] == 'split_0'
    assert result['vector_choice'] == 'native_primary_contract_affiliation'
    assert result['source_total'] == result['scanned_count'] == 1
    assert result['complete_base_source'] and result['next_source_offset'] is None
    assert result['admission_state'] == 'unrestricted_show_all_bypass'
    assert result['list_context'] == dict(native_kind=1, native_container=1, list_index=0,
        stored_signed_index=1, effective_clamped_index=1, current_container_raw=3,
        show_all_raw=1, refresh_byte_ff=0, cached_count=0, cached_freshness='unproved')
    assert result['subjects'] == [dict(native_ordinal=0, state='canonical_actual_subject',
        primary=0x1000, person=0x1388, record_kind='actual',
        native_identity=dict(database_index=0, native_id=12345, random_id=None))]
    assert result['retained_union_state'] == 'unimplemented'
    assert not result['complete_search_population'] and not result['manager_knowledge_verified']
    assert result['save']['current_date'] == '2030-09-19'


def test_combined_identity_uses_its_own_primary_displacement(population_memory):
    m = population_memory
    m['put'](m['club'] + 0xB9, b'\x01')
    result = observe(m)
    assert result['vector'] == 'split_1'
    row = result['subjects'][0]
    assert row['person'] - row['primary'] == 0x480
    assert row['record_kind'] == 'player_staff'
    assert row['native_identity'] == dict(database_index=1, native_id=77, random_id=88)


@pytest.mark.parametrize('mode', [0, 2, 3, 255])
def test_mode_other_than_one_chooses_split_zero_despite_club_bit(population_memory, mode):
    m = population_memory
    m['put'](m['base'] + 0x56D4992, bytes([mode]))
    m['put'](m['club'] + 0xB9, b'\x01')
    result = observe(m)
    assert result['vector'] == 'split_0'
    assert result['vector_mode_992'] == mode


@pytest.mark.parametrize('primary,secondary,expected', [(0, 1, 'split_0'), (1, 0, 'split_1'), (2, 0, 'split_0')])
def test_dual_context_full_byte_mismatch_uses_selected_team_fallback(population_memory, primary, secondary, expected):
    m = population_memory
    m['put'](m['club'] + 0xB9, bytes([primary]))
    m['add_secondary'](code=secondary)
    result = observe(m)
    assert result['vector'] == expected
    assert result['vector_choice'] == 'native_discriminator_three_selected_team_fallback'


def test_unaccepted_primary_without_secondary_uses_global_vector(population_memory):
    m = population_memory
    m['put'](m['primary_contract'] + 0xC2, b'\x01')
    result = observe(m)
    assert result['vector'] == 'all_actual'
    assert [r['record_kind'] for r in result['subjects']] == ['actual', 'player_staff']


@pytest.mark.parametrize('primary,expected_choice', [
    (0, 'native_primary_contract_affiliation'),
    (1, 'native_discriminator_three_selected_team_fallback')])
def test_secondary_team_without_owner_preserves_native_primary_bit_branch(population_memory, primary, expected_choice):
    m = population_memory
    m['put'](m['club'] + 0xB9, bytes([primary]))
    m['add_secondary']()
    m['q'](m['team_addresses'][1] + 0x30, 0)
    result = observe(m)
    assert result['vector_choice'] == expected_choice
    assert result['vector'] == ('split_1' if primary else 'split_0')


@pytest.mark.parametrize('mode', [0, 2, 255])
def test_secondary_mode_requires_exact_one_before_reading_extra_contract(population_memory, mode):
    m = population_memory
    m['put'](m['primary_contract'] + 0xC2, b'\x01')
    m['q'](m['manager'] + 0x438 + 0x80, 8)  # Invalid if the gated pointer is consumed.
    m['put'](m['base'] + 0x56D4993, bytes([mode]))
    assert observe(m)['vector'] == 'all_actual'


@pytest.mark.parametrize('mode,code,expected', [(1, 1, 'split_1'), (1, 0, 'split_0'), (0, 1, 'split_0')])
def test_unaccepted_primary_with_secondary_obeys_native_discriminator(population_memory, mode, code, expected):
    m = population_memory
    m['put'](m['primary_contract'] + 0xC2, b'\x01')
    m['put'](m['base'] + 0x56D4992, bytes([mode]))
    m['add_secondary'](code=code)
    assert observe(m)['vector'] == expected


@pytest.mark.parametrize('kind,marker,category,expected', [
    ('full_contract', 0, 1, 'all_actual'), ('full_contract', 0, 2, 'split_0'),
    ('full_contract', 2, 0, 'split_0'), ('basic_contract', 0, 2, 'all_actual'),
    ('basic_contract', 2, 0, 'split_0'), ('loan_contract', 0, 2, 'all_actual'),
    ('trial_contract', 0, 2, 'all_actual')])
def test_contract_acceptance_uses_actual_kind_getter_and_marker(population_memory, kind, marker, category, expected):
    m = population_memory
    m['q'](m['manager'] + 0x4B0, m['new_contract'](kind, marker=marker, category=category))
    assert observe(m)['vector'] == expected


@pytest.mark.parametrize('flag,expected', [(0, 'restricted_admission_unimplemented'),
    (2, 'restricted_admission_unimplemented'), (3, 'unrestricted_show_all_bypass')])
def test_showall_uses_bit_zero_without_overriding_game_flag(population_memory, flag, expected):
    m = population_memory
    m['put'](m['search_lists'][0] + 0x101, bytes([flag]))
    result = observe(m)
    assert result['admission_state'] == expected
    assert result['list_context']['show_all_raw'] == flag
    assert not result['complete_search_population']


def test_base_ordinal_pages_preserve_nulls_and_duplicates_without_union_dedup(population_memory):
    m = population_memory
    m['vec'](m['base'] + source.BASE_VECTORS['split_0'], [0x1000, 0, 0x1000])
    whole = observe(m)
    assert [r['native_ordinal'] for r in whole['subjects']] == [0, 1, 2]
    assert whole['subjects'][1]['state'] == 'null_base_slot'
    assert whole['subjects'][0]['native_identity'] == whole['subjects'][2]['native_identity']
    pages = [observe(m, source_offset=i, source_limit=1) for i in range(3)]
    assert [row for page in pages for row in page['subjects']] == whole['subjects']
    assert all(not page['complete_base_source'] for page in pages)
    assert [p['next_source_offset'] for p in pages] == [1, 2, None]
    assert observe(m, source_offset=3)['subjects'] == []


@pytest.fixture
def full_page_memory(population_memory):
    m = population_memory
    pointers = [0x1000, 0, m['combined'], 0x1000] * 1024
    header = m['base'] + source.BASE_VECTORS['split_0']
    m['vec'](header, pointers)
    start = struct.unpack('<Q', m['read'](header, 8))[0]
    m.update(full_page_pointers=pointers, full_page_start=start)
    return m


def test_full_4096_page_respects_bridge_16kb_cap_and_preserves_typed_ordinals(full_page_memory):
    m = full_page_memory
    sizes = []
    def read(address, size):
        if size > 16384:
            raise ValueError(f'Canonical Bridge read cap exceeded: {size} > 16384')
        sizes.append(size)
        return m['read'](address, size)
    result = observe(m, read=read, source_limit=4096)
    rows = result['subjects']
    assert source.PAGE_LIMIT == 4096
    assert result['source_total'] == result['scanned_count'] == len(rows) == 4096
    assert result['complete_base_source'] and result['next_source_offset'] is None
    assert [r['native_ordinal'] for r in rows] == list(range(4096))
    assert sum(r['state'] == 'null_base_slot' for r in rows) == 1024
    assert sum(r.get('record_kind') == 'actual' for r in rows) == 2048
    assert sum(r.get('record_kind') == 'player_staff' for r in rows) == 1024
    assert rows[0]['native_identity'] == rows[4095]['native_identity']
    assert rows[2]['native_identity'] == dict(database_index=1, native_id=77, random_id=88)
    assert max(sizes) == 16384


@pytest.mark.parametrize('drift', ['first_chunk_after_capture', 'second_chunk_during_recheck'])
def test_full_4096_page_rejects_chunk_drift_under_strict_bridge_cap(full_page_memory, drift):
    m = full_page_memory
    start = m['full_page_start']
    second_hits = 0
    def read(address, size):
        nonlocal second_hits
        if size > 16384:
            raise ValueError(f'Canonical Bridge read cap exceeded: {size} > 16384')
        raw = m['read'](address, size)
        if (address, size) == (start + 16384, 16384):
            second_hits += 1
            if drift == 'first_chunk_after_capture' and second_hits == 1:
                m['q'](start, m['combined'])
            elif drift == 'second_chunk_during_recheck' and second_hits >= 2:
                return struct.pack('<Q', m['combined']) + raw[8:]
        return raw
    with pytest.raises(ValueError, match='changed during read'):
        observe(m, read=read, source_limit=4096)


def test_bypass_base_does_not_read_or_apply_retained_discard_pool_or_profiles(population_memory, monkeypatch):
    m = population_memory
    monkeypatch.setattr(players, 'decode', lambda *_args, **_kw: pytest.fail('profile decoder'))
    forbidden = [(0x1000 + 0x148, 0x1000 + 0x278),
                 (m['combined'] + 0x148, m['combined'] + 0x278)]
    # Native retained-only discard context; a base bypass never consults it.
    data = m['allocate'](0x1000)
    m['q'](m['manager'] + 0x388, data)
    discard = m['allocate'](8)
    m['put'](discard, struct.pack('<I', 0))  # Matches the actual subject's PERSON index.
    m['vec'](data + 0xBD8 + 0x30, [discard])
    forbidden.append((data + 0xBD8, data + 0xDD8))
    def read(address, size):
        assert all(address + size <= start or address >= end for start, end in forbidden)
        return m['read'](address, size)
    assert observe(m, read=read)['subjects'][0]['native_identity']['native_id'] == 12345


def test_empty_base_and_empty_cached_list_do_not_establish_zero_known_players(population_memory):
    m = population_memory
    for rva in source.BASE_VECTORS.values():
        m['put'](m['base'] + rva, bytes(24))
    result = observe(m)
    assert result['source_total'] == 0 and result['complete_base_source']
    assert result['all_actual_source_empty'] and result['native_empty_diagnostic_not_replayed']
    assert result['list_context']['cached_freshness'] == 'unproved'
    assert not result['complete_search_population'] and not result['manager_knowledge_verified']


def test_negative_native_selector_clamps_to_zero(population_memory):
    m = population_memory
    m['put'](m['manager'] + 0x42B, b'\xff')
    result = observe(m)
    assert result['list_context']['stored_signed_index'] == -1
    assert result['list_context']['effective_clamped_index'] == 0
    assert result['list_context']['list_index'] == 0


def test_null_header_on_fallback_scan_is_not_silently_skipped(population_memory):
    m = population_memory
    m['vec'](m['manager'] + 0x248, [0, m['search_lists'][1], m['search_lists'][0]])
    with pytest.raises(source.SourceUnavailable, match='Null header'):
        observe(m)


@pytest.mark.parametrize('fault', ['list_owner', 'selected_null', 'selected_bounds', 'no_kind1',
    'canonical_slot', 'person_type', 'primary_type', 'cast_getter', 'cast_adjustment',
    'human_data_type', 'contract_getter', 'native_guard', 'current_date'])
def test_corrupt_ownership_type_and_source_never_publish_partial_results(population_memory, fault):
    m = population_memory
    if fault == 'list_owner': m['q'](m['search_lists'][2] + 0xD0, m['manager'] + 8)
    elif fault == 'selected_null': m['vec'](m['manager'] + 0x248, [m['search_lists'][0], 0])
    elif fault == 'selected_bounds': m['put'](m['manager'] + 0x42B, b'\x7f')
    elif fault == 'no_kind1': m['put'](m['search_lists'][0] + 0x4C, b'\x02')
    elif fault == 'canonical_slot': m['vec'](m['headers']['people'], [m['combined_person'], m['combined_person']])
    elif fault == 'person_type': m['q'](0x1388, 0)
    elif fault == 'primary_type': m['q'](0x1000, m['base'] + world.TYPES['club'][0])
    elif fault == 'cast_getter': m['q'](m['base'] + players.RVA[2] + 0x6E0, m['base'] + 0xCA4A6C)
    elif fault == 'cast_adjustment': m['put'](m['base'] + players.RVA[2] - 0x6F0, struct.pack('<q', -0x480))
    elif fault == 'human_data_type': m['q'](m['manager'] + 0x438, 0)
    elif fault == 'contract_getter': m['q'](m['base'] + world.TYPES['full_contract'][0] + 0x70, 0)
    elif fault == 'native_guard': m['put'](m['base'] + source.NATIVE_SPANS[0][0], b'X')
    else: m['put'](m['base'] + world.CURRENT_DATE, struct.pack('<HH', 1, 1900))
    with pytest.raises(ValueError): observe(m)


@pytest.mark.parametrize('header', [(0, 8, 8), (0x10000, 0xFFF8, 0x10000),
    (0x10000, 0x10008, 0x10000), (0x10001, 0x10001, 0x10001),
    (0x10000, 0x10001, 0x10008), (0x10000, 0x10008, 0x10009)])
def test_invalid_base_vector_bounds_reject(population_memory, header):
    m = population_memory
    m['put'](m['base'] + source.BASE_VECTORS['split_0'], struct.pack('<QQQ', *header))
    with pytest.raises(ValueError, match='vector|pointer'): observe(m)


def test_compact_base_never_uses_ordinary_offsets_or_generation(population_memory):
    m = population_memory
    compact = m['allocate'](8)  # No readable ordinary profile exists after the type word.
    m['q'](compact, m['base'] + world.TYPES['virtual_player'][0])
    m['vec'](m['base'] + source.BASE_VECTORS['split_0'], [compact])
    with pytest.raises(source.SourceUnavailable, match='Compact virtual'): observe(m)


@pytest.mark.parametrize('target', ['date', 'owner', 'identity', 'vector', 'showall'])
def test_consumed_byte_drift_rejects_snapshot(population_memory, target):
    m = population_memory
    address, size = {
        'date': (m['base'] + world.CURRENT_DATE, 4),
        'owner': (m['search_lists'][0] + 0xD0, 8),
        'identity': (0x1388, 20),
        'vector': (m['base'] + source.BASE_VECTORS['split_0'], 24),
        'showall': (m['search_lists'][0] + 0x101, 1),
    }[target]
    hits = 0
    def read(a, n):
        nonlocal hits
        raw = m['read'](a, n)
        if (a, n) == (address, size):
            hits += 1
            if hits >= 2:
                return bytes([raw[0] ^ 1]) + raw[1:]
        return raw
    with pytest.raises(ValueError, match='changed'): observe(m, read=read)


def test_checked_lifetime_callback_detects_process_or_save_replacement(population_memory):
    calls = 0
    def current():
        nonlocal calls
        calls += 1
        return ('process', calls)
    with pytest.raises(ValueError, match='lifetime changed'):
        observe(population_memory, check_current=current)


def test_selected_coach_must_match_fresh_loaded_save(population_memory):
    m = population_memory
    coach = {**m['coach'], 'manager_address': m['manager'] + 8}
    with pytest.raises(ValueError, match='loaded save'):
        source.observe(m['read'], m['base'], coach, check_current=lambda: ('process', 'save'))


def test_process_check_cannot_be_omitted_or_return_an_empty_identity(population_memory):
    with pytest.raises(ValueError, match='lifetime identity'):
        observe(population_memory, check_current=lambda: ())
    with pytest.raises(ValueError, match='identity check'):
        observe(population_memory, check_current=None)


@pytest.mark.parametrize('offset,limit', [(-1, 1), (True, 1), (0, 0), (0, 4097)])
def test_invalid_page_rejects_before_any_reads(offset, limit):
    with pytest.raises(ValueError, match='ordinal page'):
        source.observe(lambda *_: pytest.fail('read'), 0, {}, check_current=lambda: (),
                       source_offset=offset, source_limit=limit)
