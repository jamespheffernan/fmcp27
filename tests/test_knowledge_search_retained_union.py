"""Synthetic canonical retained union; no live source or manager-mode proof."""
from _knowledge_stream_fixture import native_stream_transport
import struct

import pytest

from fm_live_mcp import knowledge_search_population_source as base_source
from fm_live_mcp import knowledge_search_retained_union as union
from fm_live_mcp import virtual_identity, world
from test_knowledge_search_population_source import (
    population_memory, prepared_tactics_memory, member_memory, team_memory,
    database_memory, memory, world_memory)


@pytest.fixture
def retained_memory(population_memory):
    m = population_memory
    base, human = m['base'], m['manager']
    for rva, raw in union.NATIVE_SPANS:
        m['put'](base + rva, raw)
    for rva, person_offset in ((0x5588EE8, 0x388), (0x558EF38, 0x480)):
        m['put'](base + rva - 0x18, struct.pack('<q', person_offset))
    for kind in ('basic_contract', 'full_contract', 'loan_contract', 'trial_contract'):
        m['q'](base + world.TYPES[kind][0] + 0x58, base + 0xD8C3C8)
    m['put'](m['primary_contract'] + 0x26, b'\x02')
    data = m['allocate'](0x1000)
    m['q'](human + 0x388, data)
    actual, actual_person = m['add_person']('actual', 2, 901, 902)
    m['put'](actual_person + 0x18, struct.pack('<Q', 1 << 12))
    # Reserve a guarded gap so no unrelated RTTI/string allocation overlaps
    # the addresses an incorrect ordinary-profile fallback would read.
    compact = m['allocate'](0x400)
    m['typed_at'](compact, world.TYPES['virtual_player'][0],
                  world.TYPES['virtual_player'][1])
    m['typed_at'](compact + 0x20, virtual_identity.PERSON_RVA,
                  world.TYPES['virtual_player'][1], -0x20)
    m['put'](compact + 0x28, struct.pack('<III', 3, 903, 904))
    m['put'](compact + 0x14, struct.pack('<h', -1))
    for rva, raw in virtual_identity.NATIVE_SPANS:
        m['put'](base + rva, raw)
    m['q'](base + virtual_identity.PERSON_RVA + 2 * 8, base + 0x1475750)
    m['q'](base + world.TYPES['virtual_player'][0] + 29 * 8, base + 0x18A4A9C)
    staff, staff_person = m['add_person']('staff', 4, 905, 906)
    people = [0x1388, m['combined_person'], actual_person, compact + 0x20, staff_person]
    m['vec'](m['headers']['people'], people)
    m['vec'](base + base_source.BASE_VECTORS['all_actual'], [0x1000, m['combined'], actual])
    m['vec'](base + base_source.BASE_VECTORS['split_1'], [m['combined'], actual])
    m['vec'](m['roots']['teams'] + 0x68, m['team_addresses'])

    def discard(indices):
        values = []
        for index in indices:
            if index is None:
                values.append(0)
                continue
            record = m['allocate'](8)
            m['put'](record, struct.pack('<i', index))
            values.append(record)
        m['vec'](data + 0xBD8 + 0x30, values)
        return values

    def entry(person):
        record = m['allocate'](0x38)
        m['q'](record, person)
        return record

    records = [entry(0x1388), entry(actual_person), entry(compact + 0x20),
               entry(actual_person), entry(m['combined_person']), 0, entry(0), entry(staff_person)]
    m['vec'](m['search_lists'][1] + 0x80, records)
    discard([1])
    listings = list(m['search_lists'])
    for kind in (7, 10, 11, 3):
        listing = m['allocate'](0x108)
        m['q'](listing + 0xD0, human)
        m['put'](listing + 0x4C, bytes([kind]))
        listings.append(listing)
    m['vec'](human + 0x248, listings)
    # A personal230 header deliberately disagrees; the union must never read it.
    m['q'](human + 0x230, 8)
    m.update(retained_data=data, retained_actual=actual, retained_actual_person=actual_person,
             retained_compact=compact, retained_staff=staff, retained_staff_person=staff_person,
             retained_people=people, retained_records=records, retained_lists=listings,
             set_discard=discard, retained_entry=entry)
    return m


def lifetime():
    return ('synthetic-process', 'save', 'build')


def frame(m, **kwargs):
    return base_source.observe(m['read'], m['base'], m['coach'], check_current=lifetime, **kwargs)


def observe(m, frames=None, read=None, **kwargs):
    return union.observe(read or m['read'], m['base'], m['coach'],
                         [frame(m)] if frames is None else frames,
                         check_current=kwargs.pop('check_current', lifetime), **kwargs)


def test_exact_retained_decisions_use_base_seed_discard_canonical_index_and_types(retained_memory):
    m = retained_memory
    result, continuation = observe(m)
    assert continuation is None
    assert result['native_union_active'] and result['native_container'] == 1
    assert result['source_total'] == result['scanned_count'] == 8
    assert result['complete_returned_source'] and result['base_coverage_complete']
    assert result['all_union_decisions_resolved']
    assert [row['state'] for row in result['subjects']] == [
        'duplicate_base_admitted', 'retained_union_addition', 'retained_union_addition',
        'duplicate_prior_retained', 'discarded_native_person_lookup', 'null_entry',
        'null_subject', 'retained_union_addition']
    assert [row['record_kind'] for row in result['subjects'] if row['would_append']] == [
        'actual', 'virtual', 'staff']
    assert not result['complete_search_population'] and not result['manager_knowledge_verified']
    assert result['current_date'] == '2030-09-19'
    assert [header['state'] for header in result['list_headers']] == [
        'destination_skipped', 'retained_source', 'native_kind_skipped',
        'native_kind_skipped', 'native_kind_skipped', 'native_kind_skipped', 'retained_source']


def test_native_contract_context_absence_skips_union_without_reading_discard_data(retained_memory):
    m = retained_memory
    m['put'](m['primary_contract'] + 0x26, b'\x01')
    m['q'](m['manager'] + 0x388, 8)
    result, continuation = observe(m)
    assert result['source_state'] == 'native_union_context_absent'
    assert not result['native_union_active'] and result['source_total'] == 0
    assert result['subjects'] == [] and continuation is None
    assert not result['complete_search_population']


@pytest.mark.parametrize('kind', ['basic_contract', 'full_contract', 'loan_contract', 'trial_contract'])
def test_context_contract_getter_is_byte26_for_each_supported_type(retained_memory, kind):
    m = retained_memory
    contract = m['new_contract'](kind, marker=2)
    m['q'](m['base'] + world.TYPES[kind][0] + 0x58, m['base'] + 0xD8C3C8)
    m['q'](m['manager'] + 0x4B0, contract)
    assert observe(m)[0]['native_union_active']


def test_skipped_kind_and_destination_payloads_and_personal230_are_never_consumed(retained_memory):
    m = retained_memory
    forbidden = [(m['manager'] + 0x230, m['manager'] + 0x248)]
    for listing in [m['retained_lists'][i] for i in (2, 3, 4, 5)]:
        m['q'](listing + 0x80, 8)  # Invalid geometry would fail if a skipped list were read.
        forbidden.append((listing + 0x80, listing + 0x98))
    forbidden_record = m['allocate'](8)
    m['q'](forbidden_record, 8)
    m['vec'](m['retained_lists'][0] + 0x80, [forbidden_record])
    forbidden.append((forbidden_record, forbidden_record + 8))
    def read(address, size):
        assert all(address + size <= low or address >= high for low, high in forbidden)
        return m['read'](address, size)
    assert observe(m, read=read)[0]['source_total'] == 8


@pytest.mark.parametrize('kind', [0, 3, 5, 9, 12, 255])
def test_other_native_kinds_remain_union_sources_without_guessed_labels(retained_memory, kind):
    m = retained_memory
    m['put'](m['retained_lists'][1] + 0x4C, bytes([kind]))
    result, _ = observe(m)
    assert result['source_total'] == 8
    assert result['subjects'][1]['state'] == 'retained_union_addition'


@pytest.mark.parametrize('header,reason', [((0, 8, 8), 'pointer'),
    ((0x10000, 0xFFF8, 0x10000), 'vector'), ((0x10000, 0x10008, 0x10000), 'vector'),
    ((0x10001, 0x10001, 0x10001), 'pointer'), ((0x10000, 0x10001, 0x10008), 'vector'),
    ((0x10000, 0x10008, 0x10000 + (union.ENTRY_LIMIT + 1) * 8), 'vector')])
def test_retained_vector_bounds_and_reader_budget_reject_before_payloads(retained_memory, header, reason):
    m = retained_memory
    m['put'](m['retained_lists'][1] + 0x80, struct.pack('<QQQ', *header))
    with pytest.raises(ValueError, match=reason):
        observe(m)


@pytest.mark.parametrize('mode', [1, 3, 255])
def test_discard_mode_uses_bit_zero_for_canonical_people(retained_memory, mode):
    m = retained_memory
    m['put'](m['base'] + 0x56D34E0, bytes([mode]))
    m['vec'](m['roots']['people'] + 0x68, [0] * 5)
    assert observe(m)[0]['subjects'][4]['state'] == 'discarded_native_person_lookup'


@pytest.mark.parametrize('mode', [0, 2, 254])
def test_in_range_null_fallback_slot_does_not_use_canonical_people(retained_memory, mode):
    m = retained_memory
    m['put'](m['base'] + 0x56D34E0, bytes([mode]))
    m['vec'](m['roots']['people'] + 0x68, [0, 0])
    assert observe(m)[0]['subjects'][4]['state'] == 'retained_union_addition'


def test_out_of_range_fallback_index_uses_canonical_people(retained_memory):
    m = retained_memory
    m['put'](m['base'] + 0x56D34E0, b'\0')
    m['vec'](m['roots']['people'] + 0x68, [0])
    assert observe(m)[0]['subjects'][4]['state'] == 'discarded_native_person_lookup'


def test_discard_lookup_compares_resolved_person_pointer_and_skips_negative_indices(retained_memory):
    m = retained_memory
    m['put'](m['base'] + 0x56D34E0, b'\0')
    m['vec'](m['roots']['people'] + 0x68, [0, m['retained_actual_person']])
    m['set_discard']([None, -1, 500, 1])
    rows = observe(m)[0]['subjects']
    assert rows[1]['state'] == rows[3]['state'] == 'discarded_native_person_lookup'
    assert rows[4]['state'] == 'retained_union_addition'


def test_discard_record_uses_person_index_not_primary_id_and_precedes_base_dedup(retained_memory):
    m = retained_memory
    m['set_discard']([77])  # Combined subject's primary ID, not its PERSON index1.
    assert observe(m)[0]['subjects'][4]['state'] == 'retained_union_addition'
    m['set_discard']([0])
    assert observe(m)[0]['subjects'][0]['state'] == 'discarded_native_person_lookup'


def test_equal_primary_ids_do_not_merge_different_person_indices(retained_memory):
    m = retained_memory
    m['put'](m['retained_actual_person'] + 0xC, struct.pack('<I', 12345))
    row = observe(m)[0]['subjects'][1]
    assert row['native_identity']['native_id'] == 12345
    assert row['native_identity']['database_index'] == 2 and row['would_append'] is True


@pytest.mark.parametrize('cache_index', [-1, 0, 7])
def test_compact_retained_identity_never_reads_generated_profile_or_scalar_fields(retained_memory, cache_index):
    m = retained_memory
    compact = m['retained_compact']
    m['put'](compact + 0x14, struct.pack('<h', cache_index))
    def read(address, size):
        assert address + size <= compact + 0x40 or address >= compact + 0x400
        return m['read'](address, size)
    row = observe(m, read=read)[0]['subjects'][2]
    assert row['record_kind'] == 'virtual' and row['would_append'] is True
    assert row['native_identity'] == dict(database_index=3, native_id=903, random_id=904)


def test_partial_base_has_explicit_unknown_overlap_but_later_duplicate_is_certain(retained_memory):
    m = retained_memory
    # Even a complete pointer scan does not prove index-bit absence for this
    # retained primary: only the unrelated combined pointer is in the tail.
    m['vec'](m['base'] + base_source.BASE_VECTORS['split_0'], [0x1000, m['combined']])
    result, _ = observe(m, frames=[frame(m, source_limit=1)])
    assert not result['base_coverage_complete']
    assert result['subjects'][1]['state'] == 'base_overlap_unresolved'
    assert result['subjects'][1]['would_append'] is None
    assert result['subjects'][3]['state'] == 'duplicate_prior_retained'
    assert result['subjects'][3]['would_append'] is False
    assert result['subjects'][2]['would_append'] is True  # Compact cannot occur in actual base.
    assert not result['all_union_decisions_resolved'] and not result['complete_search_population']


@pytest.mark.parametrize('kind', ['actual', 'player_staff'])
def test_partial_identity_frame_resolves_exact_raw_base_pointer_match(retained_memory, kind):
    m = retained_memory
    primary = m['retained_actual'] if kind == 'actual' else m['combined']
    person = m['retained_actual_person'] if kind == 'actual' else m['combined_person']
    m['set_discard']([])
    # Unsorted physical duplicates/nulls are preserved as source metadata. The
    # only fully bound base identity frame covers ordinal0, not this subject.
    m['vec'](m['base'] + base_source.BASE_VECTORS['split_0'], [0x1000, primary, 0, primary])
    m['vec'](m['retained_lists'][1] + 0x80, [m['retained_entry'](person), m['retained_entry'](person)])
    result, _ = observe(m, frames=[frame(m, source_limit=1)])
    assert [row['state'] for row in result['subjects']] == ['duplicate_base_admitted'] * 2
    assert all(row['would_append'] is False for row in result['subjects'])
    assert not result['base_coverage_complete']
    assert result['known_base_seed_subjects'] == 1
    assert result['base_pointer_metadata'] == dict(
        selected_vector='split_0', stored_slots=4, null_slots=1, complete_pointer_scan=True,
        complete_identity_coverage=False, additional_base_matches_in_scanned_prefix=1,
        scope='positive_canonical_retained_primary_matches_only')
    assert not result['complete_search_population'] and not result['manager_knowledge_verified']


def test_pointer_alias_with_same_person_index_is_not_false_absence_proof(retained_memory):
    m = retained_memory
    alias, _ = m['add_person']('actual', 2, 901, 902)
    # Only the original retained PERSON is canonical. The different raw primary
    # could seed the same native index; absence of the canonical primary cannot
    # establish that the native bit is clear.
    m['vec'](m['base'] + base_source.BASE_VECTORS['split_0'], [0x1000, alias])
    result, _ = observe(m, frames=[frame(m, source_limit=1)])
    row = result['subjects'][1]
    assert row['native_identity']['database_index'] == 2
    assert row['state'] == 'base_overlap_unresolved' and row['would_append'] is None
    assert result['base_pointer_metadata']['complete_pointer_scan']
    assert not result['base_pointer_metadata']['complete_identity_coverage']


@pytest.fixture
def wide_raw_base(retained_memory):
    m = retained_memory
    values = [0x1000] + [0] * 2047 + [m['retained_actual']] + [m['combined']] * 2048
    header = m['base'] + base_source.BASE_VECTORS['split_0']
    m['vec'](header, values)
    start = struct.unpack('<Q', m['read'](header, 8))[0]
    m.update(raw_base_header=header, raw_base_start=start)
    return m


def test_full_raw_pointer_scan_respects_16kb_cap_with_partial_identity_coverage(wide_raw_base):
    m = wide_raw_base
    frames = [frame(m, source_limit=1)]
    sizes = []
    def read(address, size):
        if size > 16384:
            raise ValueError('Bridge read cap exceeded')
        sizes.append(size)
        return m['read'](address, size)
    result, _ = observe(m, frames=frames, read=read)
    assert result['subjects'][1]['state'] == 'duplicate_base_admitted'
    assert result['base_pointer_metadata']['stored_slots'] == 4097
    assert result['base_pointer_metadata']['null_slots'] == 2047
    assert result['base_pointer_metadata']['complete_pointer_scan']
    assert not result['base_coverage_complete'] and not result['complete_search_population']
    assert max(sizes) == 16384


@pytest.mark.parametrize('drift', ['header', 'pointer_after_capture', 'chunk_recheck'])
def test_raw_base_header_pointer_and_chunk_drift_reject(wide_raw_base, drift):
    m = wide_raw_base
    frames = [frame(m, source_limit=1)]
    start, hits = m['raw_base_start'], 0
    def read(address, size):
        nonlocal hits
        if size > 16384:
            raise ValueError('Bridge read cap exceeded')
        raw = m['read'](address, size)
        if (address, size) == (start + 16384, 16384):
            hits += 1
            if drift == 'header' and hits == 1:
                m['q'](m['raw_base_header'] + 8, start + 4096 * 8)
            elif drift == 'chunk_recheck' and hits >= 2:
                return struct.pack('<Q', 0x1000) + raw[8:]
        elif drift == 'pointer_after_capture' and (address, size) == (start + 32768, 8):
            m['q'](start + 16384, 0x1000)
        return raw
    with pytest.raises(ValueError, match='changed'):
        observe(m, frames=frames, read=read)


def test_raw_pointer_match_does_not_bind_unrelated_base_objects_or_read_attributes(retained_memory):
    m = retained_memory
    other, other_person = m['add_person']('actual', 5, 999, 999)
    m['vec'](m['headers']['people'], [*m['retained_people'], other_person])
    m['vec'](m['base'] + base_source.BASE_VECTORS['split_0'], [0x1000, other, m['retained_actual']])
    frames = [frame(m, source_limit=1)]
    forbidden = [(other, other + 0x4A0),
                 (m['retained_actual'] + 0x148, m['retained_actual'] + 0x278),
                 (m['retained_actual_person'] + 0x18, m['retained_actual_person'] + 0x20)]
    def read(address, size):
        assert all(address + size <= low or address >= high for low, high in forbidden)
        return m['read'](address, size)
    result, _ = observe(m, frames=frames, read=read)
    assert result['subjects'][1]['state'] == 'duplicate_base_admitted'
    assert not result['base_pointer_metadata']['complete_identity_coverage']


def test_zero_raw_pointer_cells_do_not_become_resolved_absence(retained_memory):
    m = retained_memory
    m['vec'](m['base'] + base_source.BASE_VECTORS['split_0'], [0, 0])
    result, _ = observe(m, frames=[frame(m, source_limit=1)])
    assert result['base_pointer_metadata']['null_slots'] == 2
    assert result['base_pointer_metadata']['complete_pointer_scan']
    assert result['subjects'][1]['state'] == 'base_overlap_unresolved'
    assert result['subjects'][1]['would_append'] is None
    assert not result['base_coverage_complete'] and not result['complete_search_population']


def test_missing_raw_pointer_read_is_an_error_not_empty_membership(retained_memory):
    m = retained_memory
    header = m['base'] + base_source.BASE_VECTORS['split_0']
    m['vec'](header, [0x1000, m['retained_actual']])
    start = struct.unpack('<Q', m['read'](header, 8))[0]
    frames = [frame(m, source_limit=1)]
    def read(address, size):
        if (address, size) == (start, 16):
            raise ValueError('Raw base pointer read unavailable')
        return m['read'](address, size)
    with pytest.raises(ValueError, match='read unavailable'):
        observe(m, frames=frames, read=read)


@pytest.mark.parametrize('pointer', [8, 0x1001])
def test_invalid_nonzero_raw_pointer_is_not_treated_as_an_empty_slot(retained_memory, pointer):
    m = retained_memory
    m['vec'](m['base'] + base_source.BASE_VECTORS['split_0'], [0x1000, pointer])
    with pytest.raises(ValueError, match='pointer'):
        observe(m, frames=[frame(m, source_limit=1)])


@pytest.mark.parametrize('change', ['pointer_cell', 'header_storage'])
def test_raw_base_snapshot_is_bound_across_union_continuations(retained_memory, change):
    m = retained_memory
    header = m['base'] + base_source.BASE_VECTORS['split_0']
    pointers = [0x1000, m['retained_actual'], m['combined']]
    m['vec'](header, pointers)
    frames = [frame(m, source_limit=1)]
    _, cursor = observe(m, frames=frames, source_limit=2)
    assert cursor is not None
    if change == 'pointer_cell':
        start = struct.unpack('<Q', m['read'](header, 8))[0]
        m['q'](start + 16, 0)
    else:
        m['vec'](header, pointers)
    with pytest.raises(ValueError, match='changed across pages'):
        observe(m, frames=frames, continuation=cursor)


@pytest.mark.parametrize('fault', ['native_person_adjustment', 'compact_raw_base', 'selected_vector', 'showall'])
def test_raw_overlap_rejects_wrong_cast_type_context_or_showall(retained_memory, fault):
    m = retained_memory
    m['vec'](m['base'] + base_source.BASE_VECTORS['split_0'], [0x1000, m['retained_actual']])
    if fault == 'native_person_adjustment':
        m['put'](m['base'] + 0x5588EE8 - 0x18, struct.pack('<q', 0x480))
    elif fault == 'compact_raw_base':
        m['vec'](m['base'] + base_source.BASE_VECTORS['split_0'], [0x1000, m['retained_compact']])
    elif fault == 'showall':
        m['put'](m['retained_lists'][0] + 0x101, b'\x02')
    frames = [frame(m, source_limit=1)]
    if fault == 'selected_vector':
        frames[0]['vector'] = 'all_actual'
    with pytest.raises(ValueError):
        observe(m, frames=frames)


@pytest.mark.parametrize('rva', [0x208BB88, 0x208C2CC])
def test_native_showall_and_index_seed_guards_are_required(retained_memory, rva):
    m = retained_memory
    frames = [frame(m)]
    m['put'](m['base'] + rva, b'X')
    with pytest.raises(ValueError, match='native source changed'):
        observe(m, frames=frames)


def test_eight_resolved_slots_do_not_claim_complete_1706_slot_union(retained_memory):
    m = retained_memory
    m['vec'](m['base'] + base_source.BASE_VECTORS['split_0'], [0x1000, m['retained_actual']])
    m['vec'](m['retained_lists'][1] + 0x80, [m['retained_entry'](m['retained_actual_person'])] * 1706)
    result, cursor = observe(m, frames=[frame(m, source_limit=1)], source_limit=8)
    assert result['source_total'] == 1706 and result['scanned_count'] == 8
    assert all(row['state'] == 'duplicate_base_admitted' for row in result['subjects'])
    assert result['all_scanned_union_decisions_resolved']
    assert not result['complete_returned_source'] and not result['all_union_decisions_resolved']
    assert not result['base_coverage_complete'] and not result['complete_search_population']
    assert cursor is not None and cursor.next_offset == 8


def test_complete_contiguous_base_frames_seed_dedup_across_pages(retained_memory):
    m = retained_memory
    m['vec'](m['base'] + base_source.BASE_VECTORS['split_0'], [0x1000, m['retained_actual']])
    frames = [frame(m, source_limit=1), frame(m, source_offset=1, source_limit=1)]
    result, _ = observe(m, frames=frames)
    assert result['base_coverage_complete'] and result['all_union_decisions_resolved']
    assert result['subjects'][1]['state'] == 'duplicate_base_admitted'


def test_union_pagination_replays_prefix_and_matches_whole_source(retained_memory):
    m = retained_memory
    frames = [frame(m)]
    whole, _ = observe(m, frames=frames)
    rows, cursor = [], None
    while True:
        page, cursor = observe(m, frames=frames, source_limit=2, continuation=cursor)
        rows.extend(page['subjects'])
        if cursor is None:
            assert page['all_scanned_union_decisions_resolved']
            assert not page['all_union_decisions_resolved']
            assert not page['complete_returned_source']
            break
    assert rows == whole['subjects']
    assert rows[3]['state'] == 'duplicate_prior_retained'


@pytest.mark.parametrize('fault', ['prior_subject', 'discard', 'list_header', 'entry_array', 'base_id', 'date'])
def test_crosspage_consumed_drift_rejects_before_publishing_next_page(retained_memory, fault):
    m = retained_memory
    frames = [frame(m)]
    _, cursor = observe(m, frames=frames, source_limit=2)
    if fault == 'prior_subject': m['q'](m['retained_records'][1], m['retained_compact'] + 0x20)
    elif fault == 'discard': m['set_discard']([2])
    elif fault == 'list_header': m['q'](m['retained_lists'][1] + 0xD0, m['manager'] + 8)
    elif fault == 'entry_array': m['vec'](m['retained_lists'][1] + 0x80, m['retained_records'])
    elif fault == 'base_id': m['put'](0x1388 + 0xC, struct.pack('<I', 888))
    else: m['put'](m['base'] + world.CURRENT_DATE, struct.pack('<HH', 263, 2030))
    with pytest.raises(ValueError, match='changed across pages'):
        observe(m, frames=frames, continuation=cursor)


def test_continuation_lifetime_and_base_frame_set_cannot_be_replaced(retained_memory):
    m = retained_memory
    frames = [frame(m)]
    _, cursor = observe(m, frames=frames, source_limit=1)
    with pytest.raises(ValueError, match='lifetime changed across pages'):
        observe(m, frames=frames, continuation=cursor, check_current=lambda: ('new-process',))
    with pytest.raises(ValueError, match='frame set changed'):
        observe(m, frames=frames * 2, continuation=cursor)


@pytest.mark.parametrize('fault', ['fake_seed', 'overlap', 'restricted', 'other_owner',
    'retained_index', 'retained_primary_id', 'compact_primary_id', 'context_getter', 'native_guard'])
def test_unknown_or_corrupt_binding_never_becomes_a_union_member(retained_memory, fault):
    m = retained_memory
    frames = [frame(m)]
    if fault == 'fake_seed': frames[0]['subjects'][0]['native_identity']['native_id'] = 999
    elif fault == 'overlap': frames *= 2
    elif fault == 'restricted':
        m['put'](m['retained_lists'][0] + 0x101, b'\0')
        frames = [frame(m)]
    elif fault == 'other_owner': m['q'](m['retained_lists'][1] + 0xD0, m['manager'] + 8)
    elif fault == 'retained_index': m['put'](m['retained_actual_person'] + 8, struct.pack('<I', 4))
    elif fault == 'retained_primary_id': m['put'](m['retained_actual_person'] + 0xC, bytes(4))
    elif fault == 'compact_primary_id': m['put'](m['retained_compact'] + 0x2C, bytes(4))
    elif fault == 'context_getter': m['q'](m['base'] + world.TYPES['full_contract'][0] + 0x58, 0)
    else: m['put'](m['base'] + union.NATIVE_SPANS[0][0], b'X')
    with pytest.raises(ValueError): observe(m, frames=frames)


def test_known_empty_retained_source_is_complete_only_for_that_component(retained_memory):
    m = retained_memory
    m['put'](m['retained_lists'][1] + 0x80, bytes(24))
    result, cursor = observe(m)
    assert result['native_union_active'] and result['complete_returned_source']
    assert result['subjects'] == [] and cursor is None
    assert not result['complete_search_population'] and not result['manager_knowledge_verified']


def test_in_read_discard_drift_is_caught_by_consumed_byte_verification(retained_memory):
    m = retained_memory
    frames = [frame(m)]
    address = m['retained_data'] + 0xBD8 + 0x30
    hits = 0
    def read(a, n):
        nonlocal hits
        raw = m['read'](a, n)
        if (a, n) == (address, 24):
            hits += 1
            if hits >= 2:
                return raw[:8] + bytes([raw[8] ^ 8]) + raw[9:]
        return raw
    with pytest.raises(ValueError, match='changed'):
        observe(m, frames=frames, read=read)


@pytest.mark.parametrize('limit', [0, True, 2049])
def test_invalid_page_rejects_without_memory_reads(limit):
    with pytest.raises(ValueError, match='page size'):
        union.observe(lambda *_: pytest.fail('read'), 0, {}, [], check_current=lifetime,
                      source_limit=limit)
