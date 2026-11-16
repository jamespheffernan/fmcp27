"""Native sparse presence, renderer inputs and source mutation controls."""
import struct

import pytest

from fm_live_mcp import assessment_interest_source as source, world


@pytest.fixture
def interest_memory():
    cells, reads = {}, []
    base, record, child = 0x100000000, 0x1000, 0x2000

    def put(address, raw):
        cells.update({address + i: value for i, value in enumerate(raw)})

    def read(address, size):
        reads.append((address, size))
        return bytes(cells[address + i] for i in range(size))

    def array(offset, codes, *, capacity=None):
        start = 0x4000 if offset == 0x178 else 0x14000
        end = start + len(codes) * 104
        cap = start + (len(codes) if capacity is None else capacity) * 104
        put(child + offset, struct.pack('<QQQ', start, end, cap))
        for index, code in enumerate(codes):
            put(start + index * 104 + 0x60, bytes([code]))
        return start

    for rva, raw in source.NATIVE_SPANS:
        put(base + rva, raw)
    put(record + 0x30, struct.pack('<Q', child))
    put(record + 0x20, struct.pack('<i', 30000))
    put(record + 0x41, b'\0')
    put(child + 0x79, b'\0\x80')
    array(0x178, [5])
    array(0x160, [])
    return dict(base=base, record=record, child=child, cells=cells,
                put=put, read=read, reads=reads, array=array)


def inspect(m, read=None):
    return source.inspect(read or m['read'], m['record'])


# Raw sparse type projections and values from independent native source batch22.
@pytest.mark.parametrize('first,second,value,selected', [
    ([1, 16, 25, 46, 5], [], -96213, 0x178),
    ([24, 46, 5, 0], [], -32160, 0x178),
    ([24, 46, 2, 5, 0, 0], [], -31366, 0x178),
    ([3, 25, 46, 90, 47], [21, 39, 0, 2, 18, 22, 5], 100000, 0x160),
    ([1, 12, 20, 24, 25, 46, 0, 5], [], -100000, 0x178),
    ([2, 24, 46, 97, 6], [1, 3, 5], 3704, 0x160),
])
def test_independent_six_native_presence_samples(interest_memory, first, second, value, selected):
    m = interest_memory
    m['array'](0x178, first)
    m['array'](0x160, second)
    m['put'](m['record'] + 0x20, struct.pack('<i', value))
    result = inspect(m)
    assert result == {'value': value, 'field5_present': True, 'flag41': 0,
                      'child_present': True, 'byte79': 0 if value >= -40000 else None,
                      'byte7a': None}
    if selected == 0x178:
        assert (m['child'] + 0x160, 24) not in m['reads']
    assert set(result) == {'value', 'field5_present', 'flag41', 'child_present', 'byte79', 'byte7a'}
    assert '0x' not in str(result) and 'address' not in str(result)


def test_null_child_skips_every_array_and_renderer_read(interest_memory):
    m = interest_memory
    m['put'](m['record'] + 0x30, bytes(8))
    assert inspect(m) == {'value': None, 'field5_present': False, 'flag41': None,
                          'child_present': False, 'byte79': None, 'byte7a': None}
    assert m['reads'] == [(m['record'] + 0x30, 8)]


@pytest.mark.parametrize('first,second', [([], []), ([0, 1, 255], [2, 3, 4]), ([6], [])])
def test_absent_field_skips_every_renderer_input(interest_memory, first, second):
    m = interest_memory
    m['array'](0x178, first)
    m['array'](0x160, second)
    assert inspect(m) == {'value': None, 'field5_present': False, 'flag41': None,
                          'child_present': True, 'byte79': None, 'byte7a': None}
    assert not any(address in (m['record'] + 0x20, m['record'] + 0x41,
                              m['child'] + 0x79, m['child'] + 0x7A)
                   for address, _ in m['reads'])


def test_first_native_match_skips_duplicates_and_lower_priority_array(interest_memory):
    m = interest_memory
    first = m['array'](0x178, [1, 5, 5])
    m['put'](m['child'] + 0x160, b'\xff' * 24)
    assert inspect(m)['field5_present']
    assert (first + 2 * 104 + 0x60, 1) not in m['reads']
    assert (m['child'] + 0x160, 24) not in m['reads']


def test_second_array_match_after_complete_first_scan(interest_memory):
    m = interest_memory
    first = m['array'](0x178, [6, 255, 0])
    second = m['array'](0x160, [1, 2, 5, 5])
    assert inspect(m)['field5_present']
    assert all((first + i * 104 + 0x60, 1) in m['reads'] for i in range(3))
    assert (second + 2 * 104 + 0x60, 1) in m['reads']
    assert (second + 3 * 104 + 0x60, 1) not in m['reads']


@pytest.mark.parametrize('flag,byte7a', [(1, 0), (1, 127), (1, 1)])
def test_local_na_skips_scalar_and_senior_wording_byte(interest_memory, flag, byte7a):
    m = interest_memory
    m['put'](m['record'] + 0x41, bytes([flag]))
    m['put'](m['child'] + 0x7A, bytes([byte7a]))
    assert inspect(m) == {'value': None, 'field5_present': True, 'flag41': flag,
                          'child_present': True, 'byte79': None, 'byte7a': byte7a}
    assert (m['record'] + 0x20, 4) not in m['reads']
    assert (m['child'] + 0x79, 1) not in m['reads']


@pytest.mark.parametrize('byte7a', [128, 129, 255])
def test_na_override_allows_scalar_and_senior_byte(interest_memory, byte7a):
    m = interest_memory
    m['put'](m['record'] + 0x41, b'\1')
    m['put'](m['child'] + 0x7A, bytes([byte7a]))
    m['put'](m['child'] + 0x79, b'\x20')
    assert inspect(m) == {'value': 30000, 'field5_present': True, 'flag41': 1,
                          'child_present': True, 'byte79': 32, 'byte7a': byte7a}


@pytest.mark.parametrize('flag', [0, 2, 255])
def test_only_exact_flag_one_reads_byte7a(interest_memory, flag):
    m = interest_memory
    m['put'](m['record'] + 0x41, bytes([flag]))
    assert inspect(m)['byte7a'] is None
    assert (m['child'] + 0x7A, 1) not in m['reads']


@pytest.mark.parametrize('value', [-2147483648, -111111, -100002, -100000, -40001])
def test_lower_special_values_skip_senior_byte(interest_memory, value):
    m = interest_memory
    m['put'](m['record'] + 0x20, struct.pack('<i', value))
    assert inspect(m)['value'] == value and inspect(m)['byte79'] is None
    assert (m['child'] + 0x79, 1) not in m['reads']


@pytest.mark.parametrize('value', [-40000, -39999, -2000, 0, 5000, 2147483647])
def test_range_values_read_senior_byte(interest_memory, value):
    m = interest_memory
    m['put'](m['record'] + 0x20, struct.pack('<i', value))
    m['put'](m['child'] + 0x79, b'\xff')
    assert inspect(m)['value'] == value and inspect(m)['byte79'] == 255


@pytest.mark.parametrize('count', [0, 1, source.MAX_FIELD_ENTRIES])
def test_reserved_capacity_is_neither_population_nor_examined_slot_bound(interest_memory, count):
    m = interest_memory
    m['array'](0x178, [1] * count, capacity=1000000)
    m['array'](0x160, [])
    assert inspect(m)['field5_present'] is False
    assert sum(size == 1 for _, size in m['reads']) == count


@pytest.mark.parametrize('header', [
    (0, 8, 8), (8, 8, 8), (0x4001, 0x4001, 0x4001),
    (0x4000, 0x3FF8, 0x5000), (0x4000, 0x5000, 0x4000),
    (0x4000, 0x4008, 0x4068), (0x4000, 0x4068, 0x4069),
    (0x4000, 0x4000 + 257 * 104, 0x4000 + 257 * 104),
])
def test_invalid_or_unbounded_used_extent_is_not_missing_field(interest_memory, header):
    m = interest_memory
    m['put'](m['child'] + 0x178, struct.pack('<QQQ', *header))
    with pytest.raises(ValueError):
        inspect(m)


@pytest.mark.parametrize('address', [True, False, 0, 8, 4097, 1.5, '4096', (1 << 64) - 8, 1 << 64])
def test_bad_record_address_rejects_before_reads(address):
    with pytest.raises(ValueError):
        source.inspect(lambda *_: pytest.fail('read'), address)


@pytest.mark.parametrize('child', [8, 0x2001, (1 << 64) - 8])
def test_bad_child_address_is_not_absent(interest_memory, child):
    m = interest_memory
    m['put'](m['record'] + 0x30, struct.pack('<Q', child))
    with pytest.raises(ValueError):
        inspect(m)


def test_short_read_fails_and_io_error_propagates(interest_memory):
    m = interest_memory
    with pytest.raises(ValueError, match='Incomplete'):
        inspect(m, lambda *_: b'')
    with pytest.raises(OSError, match='unmapped'):
        inspect(m, lambda *_: (_ for _ in ()).throw(OSError('unmapped')))


def test_presence_does_not_read_variant_payload_or_invoke_native_code(interest_memory):
    m = interest_memory
    assert inspect(m)['field5_present']
    assert not any(size > 24 for _, size in m['reads'])
    assert not any(address == 0x4000 + 0x48 for address, _ in m['reads'])


def test_caller_readset_rejects_consumed_source_mutation(interest_memory):
    m = interest_memory
    read = world.ReadSet(m['read'])
    assert inspect(m, read)['field5_present']
    m['put'](0x4000 + 0x60, b'\6')
    with pytest.raises(ValueError, match='changed'):
        read.verify()


def test_unused_lower_array_changes_do_not_invalidate_exact_consumed_set(interest_memory):
    m = interest_memory
    read = world.ReadSet(m['read'])
    inspect(m, read)
    m['put'](m['child'] + 0x160, b'\xff' * 24)
    read.verify()


def test_separate_native_verification_and_no_repeated_implicit_checks(interest_memory):
    m = interest_memory
    read = world.ReadSet(m['read'])
    source.verify_native(read, m['base'])
    assert len(read.observed) == len(source.NATIVE_SPANS)
    m['reads'].clear()
    inspect(m, read)
    assert not any(address >= m['base'] for address, _ in m['reads'])
    read.verify()


@pytest.mark.parametrize('index', range(len(source.NATIVE_SPANS)))
def test_every_changed_native_span_rejects(interest_memory, index):
    m = interest_memory
    rva, raw = source.NATIVE_SPANS[index]
    m['put'](m['base'] + rva, bytes([raw[0] ^ 1]) + raw[1:])
    with pytest.raises(ValueError, match='native layout changed'):
        source.verify_native(m['read'], m['base'])


@pytest.mark.parametrize('base', [True, False, 0, 8, 4097, '4096', 1.5, (1 << 64) - 8])
def test_bad_native_base_rejects_before_reads(base):
    with pytest.raises(ValueError):
        source.verify_native(lambda *_: pytest.fail('read'), base)
