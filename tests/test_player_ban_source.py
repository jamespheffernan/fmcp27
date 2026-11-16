"""Stored source state, sparse fields, native text and fail-closed controls."""
import struct

import pytest

from fm_live_mcp import player_ban_source as source, world


@pytest.fixture
def ban_memory():
    cells, reads = {}, []
    base, player, secondary, vector, record = 0x100000000, 0x1000, 0x2000, 0x3000, 0x4000

    def put(address, raw):
        cells.update({address + i: value for i, value in enumerate(raw)})

    def read(address, size):
        reads.append((address, size))
        return bytes(cells[address + i] for i in range(size))

    def set_records(pointers, capacity=None, null=False):
        if null:
            put(secondary + 0x18, bytes(24))
            return
        capacity = len(pointers) if capacity is None else capacity
        put(secondary + 0x18, struct.pack('<QQQ', vector, vector + len(pointers) * 8,
                                        vector + capacity * 8))
        put(vector, struct.pack(f'<{len(pointers)}Q', *pointers))

    def make_record(address=record, *, kind=20, context=0, total=2, minus=0,
                    cutoff=-1, number=1, reason=6, day=283 | 0x7C00, year=2030):
        scope = bytearray(8)
        struct.pack_into('<i', scope, 0, context)
        scope[4:6] = bytes([255, kind])
        put(address, bytes(scope))
        put(address + 0x10, struct.pack('<HH', day, year))
        put(address + 0x16, struct.pack('<hhb', cutoff, number, reason))
        put(address + 0x1C, struct.pack('<bb', total, minus))
        return address

    for rva, raw in source.NATIVE_SPANS:
        put(base + rva, raw)
    put(player + 0xF0, struct.pack('<Q', secondary))
    make_record()
    set_records([record])
    return dict(base=base, player=player, secondary=secondary, vector=vector, record=record,
                put=put, read=read, reads=reads, make_record=make_record, set_records=set_records)


def project(m, kind='actual', read=None):
    return source.project(read or m['read'], m['player'], kind)


def test_independent_kerkez_native_record_and_exact_public_shape(ban_memory):
    m = ban_memory
    result = project(m)
    assert set(result) == {'source_state', 'physical_record_count', 'records'}
    assert result['source_state'] == 'present_records' and result['physical_record_count'] == 1
    assert result['records'] == [{
        'native_slot_index': 0, 'native_kind': 20,
        'scope': {'state': 'mapped_native_english', 'key': 665798, 'text': 'International'},
        'main_text': {'state': 'native_international_match_main_text', 'key': 456216,
                      'text': 'Banned for 2 international matches', 'quantity': 2},
        'stored_start_date': {'value': '2030-10-10', 'state': 'stored_native_start_date',
                              'raw_hex': '1b7dee07'},
        'native_properties': {'badd': 2, 'badm': 0, 'adby': -1, 'reas': 6, 'numb': 1},
        'unmapped_scope_context_word': 0, 'eligibility_state': 'not_evaluated'}]
    assert '0x' not in repr(result) and 'address' not in repr(result)
    # No internal pointer/unknown padding was populated by the fixture.
    assert not any(m['record'] + 8 <= a < m['record'] + 0x10 for a, _ in m['reads'])
    assert all(n <= 24 for _, n in m['reads'])


def test_absent_secondary_is_not_present_empty_or_no_ban(ban_memory):
    m = ban_memory
    m['put'](m['player'] + 0xF0, bytes(8))
    assert project(m) == {'source_state': 'secondary_absent', 'physical_record_count': None, 'records': None}
    assert m['reads'] == [(m['player'] + 0xF0, 8)]


@pytest.mark.parametrize('null', [True, False])
def test_present_empty_sources_have_explicit_zero_count(ban_memory, null):
    m = ban_memory
    m['set_records']([], null=null)
    assert project(m) == {'source_state': 'present_empty', 'physical_record_count': 0, 'records': []}
    assert not any(a == m['record'] for a, _ in m['reads'])


@pytest.mark.parametrize('kind', ['player_staff', 'virtual'])
def test_unsupported_canonical_kind_returns_before_any_read_or_source_address_use(kind):
    result = source.project(lambda *_: pytest.fail('read unsupported source'), None, kind)
    assert result == {'source_state': 'unsupported_record_kind', 'physical_record_count': None, 'records': None}


@pytest.mark.parametrize('kind', [None, '', 'staff', 'unknown', 1, True, [], {}])
def test_invalid_binding_kind_fails_before_reads(kind):
    with pytest.raises(ValueError, match='kind'):
        source.project(lambda *_: pytest.fail('read'), 0x1000, kind)


@pytest.mark.parametrize('kind,total,minus,state,key,text,quantity', [
    (20, 2, 1, 'native_international_match_main_text', 456215, 'Banned for one international match', 1),
    (21, 1, 0, 'native_international_match_main_text', 456215, 'Banned for one international match', 1),
    (20, 0, 127, 'native_zero_total_input', 314612, 'No ban', None),
    (20, -1, 0, 'unsupported_date_renderer_branch', None, None, None),
    (21, -128, -128, 'unsupported_date_renderer_branch', None, None, None),
    (20, 2, 2, 'native_international_match_main_text', 456216, 'Banned for 0 international matches', 0),
    (20, 1, 2, 'native_international_match_main_text', 456216, 'Banned for -1 international matches', -1),
    (21, 127, -128, 'native_international_match_main_text', 456216, 'Banned for 255 international matches', 255),
])
def test_signed_inputs_exact_native_main_template_without_eligibility(ban_memory, kind, total, minus,
                                                                     state, key, text, quantity):
    m = ban_memory
    m['make_record'](kind=kind, total=total, minus=minus)
    row = project(m)['records'][0]
    assert row['main_text'] == {'state': state, 'key': key, 'text': text, 'quantity': quantity}
    assert row['native_properties']['badd'] == total and row['native_properties']['badm'] == minus
    assert row['eligibility_state'] == 'not_evaluated'


@pytest.mark.parametrize('kind,context,total', [(1, 0, 2), (15, 20, 2), (5, -1, 2), (31, 1234, 2), (255, 0, 0)])
def test_unmapped_kinds_do_not_resolve_context_or_synthesize_no_ban(ban_memory, kind, context, total):
    m = ban_memory
    m['make_record'](kind=kind, context=context, total=total)
    row = project(m)['records'][0]
    assert row['native_kind'] == kind and row['scope'] is None
    assert row['unmapped_scope_context_word'] == context
    assert row['main_text'] == {'state': 'unsupported_native_kind', 'key': None, 'text': None, 'quantity': None}


@pytest.mark.parametrize('day,year,value,state', [
    (1, 1900, None, 'native_default_sentinel'),
    (1 | 0xFE00, 1900, None, 'native_default_sentinel'),
    (60, 2000, '2000-02-29', 'stored_native_start_date'),
    (366 | 0xAA00, 2032, '2032-12-31', 'stored_native_start_date'),
    (0, 2030, None, 'unmapped_native_start_date'),
    (366, 2030, None, 'unmapped_native_start_date'),
    (1, 1849, None, 'unmapped_native_start_date'),
    (1, 2201, None, 'unmapped_native_start_date'),
    (511, 2030, None, 'unmapped_native_start_date'),
])
def test_native_date_defaults_flags_and_unmapped_encodings(ban_memory, day, year, value, state):
    m = ban_memory
    m['make_record'](day=day, year=year)
    result = project(m)['records'][0]['stored_start_date']
    assert result == {'value': value, 'state': state, 'raw_hex': struct.pack('<HH', day, year).hex()}


def test_every_named_property_preserves_its_independent_signed_width(ban_memory):
    m = ban_memory
    m['make_record'](cutoff=-32768, number=-32768, reason=-128, total=-128, minus=127)
    assert project(m)['records'][0]['native_properties'] == {
        'badd': -128, 'badm': 127, 'adby': -32768, 'reas': -128, 'numb': -32768}


def test_physical_order_duplicates_and_mutable_result_independence(ban_memory):
    m = ban_memory
    other = m['make_record'](0x5000, kind=21, total=1)
    m['set_records']([other, m['record'], other])
    result = project(m)
    assert result['physical_record_count'] == 3
    assert [r['native_slot_index'] for r in result['records']] == [0, 1, 2]
    assert [r['native_kind'] for r in result['records']] == [21, 20, 21]
    result['records'][0]['main_text']['text'] = 'changed'
    assert result['records'][2]['main_text']['text'] == 'Banned for one international match'


@pytest.mark.parametrize('count', [0, 1, 64])
def test_reserved_capacity_is_not_population_or_a_read_limit(ban_memory, count):
    m = ban_memory
    m['set_records']([m['record']] * count, capacity=1000000)
    result = project(m)
    assert result['physical_record_count'] == len(result['records']) == count


@pytest.mark.parametrize('header', [
    (0, 8, 8), (8, 8, 8), (0x3001, 0x3001, 0x3001),
    (0x3000, 0x2FF8, 0x4000), (0x3000, 0x3010, 0x3008),
    (0x3000, 0x3001, 0x3010), (0x3000, 0x3008, 0x3011),
    (0x3000, 0x3000 + 65 * 8, 0x3000 + 65 * 8),
])
def test_bad_or_unbounded_used_vector_never_becomes_empty(ban_memory, header):
    m = ban_memory
    m['put'](m['secondary'] + 0x18, struct.pack('<QQQ', *header))
    with pytest.raises(ValueError):
        project(m)


@pytest.mark.parametrize('field,value', [('secondary', 8), ('secondary', 0x2001),
                                        ('secondary', (1 << 64) - 8), ('record', 0),
                                        ('record', 8), ('record', 0x4001), ('record', (1 << 64) - 8)])
def test_invalid_selected_source_pointers_fail_closed(ban_memory, field, value):
    m = ban_memory
    m['put'](m['player'] + 0xF0 if field == 'secondary' else m['vector'], struct.pack('<Q', value))
    with pytest.raises(ValueError):
        project(m)


@pytest.mark.parametrize('address', [None, True, False, 0, 8, 4097, 1.5, '4096', (1 << 64) - 8, 1 << 64])
def test_actual_bad_address_fails_before_reads(address):
    with pytest.raises(ValueError):
        source.project(lambda *_: pytest.fail('read'), address, 'actual')


def test_incomplete_source_reads_fail_and_io_errors_propagate(ban_memory):
    m = ban_memory
    with pytest.raises(ValueError, match='Incomplete'):
        project(m, read=lambda *_: b'')
    with pytest.raises(OSError, match='unreadable'):
        project(m, read=lambda *_: (_ for _ in ()).throw(OSError('unreadable')))


@pytest.mark.parametrize('mutate', ['header', 'record_pointer', 'kind', 'counts', 'date'])
def test_caller_readset_rejects_consumed_source_changes(ban_memory, mutate):
    m = ban_memory
    read = world.ReadSet(m['read'])
    project(m, read=read)
    address = {'header': m['secondary'] + 0x18, 'record_pointer': m['vector'],
               'kind': m['record'] + 5, 'counts': m['record'] + 0x1C,
               'date': m['record'] + 0x10}[mutate]
    m['put'](address, bytes([m['read'](address, 1)[0] ^ 1]))
    with pytest.raises(ValueError, match='changed'):
        read.verify()


def test_unused_internal_pointer_changes_are_outside_consumed_set(ban_memory):
    m = ban_memory
    read = world.ReadSet(m['read'])
    project(m, read=read)
    m['put'](m['record'] + 8, b'no read!')
    read.verify()


def test_native_verification_is_separate_and_once_per_request(ban_memory):
    m = ban_memory
    read = world.ReadSet(m['read'])
    source.verify_native(read, m['base'])
    m['reads'].clear()
    project(m, read=read)
    assert not any(a >= m['base'] for a, _ in m['reads'])
    read.verify()


@pytest.mark.parametrize('index', range(len(source.NATIVE_SPANS)))
def test_every_changed_native_span_rejects(ban_memory, index):
    m = ban_memory
    rva, raw = source.NATIVE_SPANS[index]
    m['put'](m['base'] + rva, bytes([raw[0] ^ 1]) + raw[1:])
    with pytest.raises(ValueError, match='native layout changed'):
        source.verify_native(m['read'], m['base'])


@pytest.mark.parametrize('base', [None, True, False, 0, 8, 4097, 1.5, '4096', (1 << 64) - 8])
def test_bad_native_base_rejects_before_reads(base):
    with pytest.raises(ValueError):
        source.verify_native(lambda *_: pytest.fail('read'), base)
