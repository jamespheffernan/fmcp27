"""Pure calendar projections and pinned native reads; no live game operations."""
from datetime import date, datetime, timedelta
import struct

import pytest

from fm_live_mcp import training_calendar as calendar, world


# Independent batch16 acceptance capture, joined-source.json wrappers16..18.
PRIOR = bytes.fromhex(
    '000001000000030000006b006400650000009201f401920100002d012c012c01'
    '000005000600070000009201f401920100002d012c012c01')
CURRENT = bytes.fromhex(
    '00006c006500680000002c01f4012c0100002d012c012c010000030001000200'
    '000004000700050000002c01f4012c0100002d012c012c01')
NEXT = bytes.fromhex(
    '00006a0069006400000065006800670000009201f401920100002d012c012c01'
    '0000030000000200000004000600050000006b0064002c01')


def label(index, code):
    return {'slot_index': index, 'native_code': code, 'opaque': [index, code]}


@pytest.fixture
def memory():
    cells, reads = {}, []

    def put(address, raw):
        cells.update({address + index: value for index, value in enumerate(raw)})

    def read(address, size):
        reads.append((address, size))
        return bytes(cells[address + index] for index in range(size))

    return {'put': put, 'read': read, 'reads': reads}


def synthetic_body(values=None, row_bytes=None):
    raw = bytearray(56)
    for row in range(7):
        raw[row * 8] = row if row_bytes is None else row_bytes[row]
        raw[row * 8 + 1] = 255  # Unmapped adjacent byte must not become a code.
        struct.pack_into('<hhh', raw, row * 8 + 2,
                         *(values if values is not None else [row * 3 + i for i in range(3)]))
    return bytes(raw)


def test_default_window_and_exact_inclusive_bounds():
    assert calendar.window(None, 7, '2030-10-28') == [
        date(2030, 10, 28) + timedelta(days=i) for i in range(7)]
    assert calendar.window('2200-12-31', 1, None) == [date(2200, 12, 31)]
    assert len(calendar.window('2032-01-01', 366, None)) == 366
    assert calendar.window('1850-01-01', 1, None) == [date(1850, 1, 1)]


@pytest.mark.parametrize('value', [True, False, 0, -1, 367, 7.0, '7', None])
def test_window_rejects_non_strict_or_out_of_range_count(value):
    with pytest.raises(ValueError, match='day_count'):
        calendar.window('2030-10-28', value, None)


@pytest.mark.parametrize('value', [
    '', '20301028', '2030-W44-1', '2030-1-01', '2030-01-1', '2030-10-28\n',
    ' 2030-10-28', '2030-10-28 ', '2030-10-28T00:00:00', '２０３０-10-28',
    '2030-02-29', '2032-02-30', '2030-00-01', '2030-13-01', '0000-01-01',
    '1849-12-31', '2201-01-01', True, 20301028, date(2030, 10, 28),
])
def test_window_rejects_malformed_or_outside_native_range(value):
    with pytest.raises(ValueError):
        calendar.window(value, 1, None)


@pytest.mark.parametrize('start,count', [('2200-12-31', 2), ('2200-12-30', 3),
                                          ('2200-01-01', 366)])
def test_window_validates_entire_end_date(start, count):
    with pytest.raises(ValueError, match='end date'):
        calendar.window(start, count, None)


@pytest.mark.parametrize('current', [None, '', '2030-02-29', '2201-01-01'])
def test_default_window_validates_current_date(current):
    with pytest.raises(ValueError):
        calendar.window(None, 7, current)


def test_three_independent_real_weeks_and_sunday_monday_rollover(memory):
    m = memory
    for address, body in [(0x10000, PRIOR), (0x20000, CURRENT), (0x30000, NEXT)]:
        m['put'](address + 0x10, body)
    weeks = [(2030, 294, 0x10000), (2030, 301, 0x20000), (2030, 308, 0x30000)]
    dates = calendar.window('2030-10-27', 9, None)
    result = calendar.decode(m['read'], weeks, dates, label)
    assert [d['native_wrapper_index'] for d in result] == [0] + [1] * 7 + [2]
    assert [d['storage_row'] for d in result] == [6, 0, 1, 2, 3, 4, 5, 6, 0]
    assert [d['native_weekday'] for d in result] == [1, 2, 3, 4, 5, 6, 7, 1, 2]
    assert [[x['native_code'] for x in d['slots']] for d in result] == [
        [301, 300, 300], [108, 101, 104], [300, 500, 300], [301, 300, 300],
        [3, 1, 2], [4, 7, 5], [300, 500, 300], [301, 300, 300], [106, 105, 100]]
    assert [d['week_start'] for d in result] == ['2030-10-21'] + ['2030-10-28'] * 7 + ['2030-11-04']
    assert all(d['state'] == 'stored_assigned' and d['unmapped_row_byte'] == 0 for d in result)
    assert m['reads'] == [(0x10010, 56), (0x20010, 56), (0x30010, 56)]
    assert '0x' not in repr(result)


@pytest.mark.parametrize('weeks,state', [(None, 'unavailable_source'),
                                         ([], 'unavailable_resident_week'),
                                         ((), 'unavailable_resident_week'),
                                         ([(2030, 294, 0x10000)], 'unavailable_resident_week')])
def test_unavailable_days_keep_every_date_and_all_metadata(memory, weeks, state):
    dates = calendar.window('2030-10-28', 7, None)
    result = calendar.decode(memory['read'], weeks, dates, label)
    assert len(result) == 7
    for i, day in enumerate(result):
        assert day == {'date': dates[i].isoformat(), 'week_start': '2030-10-28',
                       'native_weekday': [2, 3, 4, 5, 6, 7, 1][i], 'storage_row': i,
                       'state': state, 'native_wrapper_index': None,
                       'unmapped_row_byte': None, 'slots': None}
    assert memory['reads'] == []


def test_missing_middle_week_does_not_shift_later_days(memory):
    memory['put'](0x10010, CURRENT)
    memory['put'](0x30010, NEXT)
    result = calendar.decode(memory['read'], [(2030, 301, 0x10000), (2030, 315, 0x30000)],
                             calendar.window('2030-10-28', 15, None), label)
    assert [d['state'] for d in result] == ['stored_assigned'] * 7 + ['unavailable_resident_week'] * 7 + ['stored_assigned']
    assert result[-1]['date'] == '2030-11-11' and result[-1]['storage_row'] == 0


def test_first_exact_native_duplicate_wins_without_reading_later_or_unselected(memory):
    memory['put'](0x20010, CURRENT)
    # The earlier unrelated key and later duplicate point to deliberately unreadable bodies.
    weeks = [(0, 0, 0x10000), (2030, 301, 0x20000), (2030, 301, 0x30000),
             (65535, 511, 0x40000)]
    days = calendar.decode(memory['read'], weeks, calendar.window('2030-10-28', 7, None), label)
    assert all(d['native_wrapper_index'] == 1 for d in days)
    assert memory['reads'] == [(0x20010, 56)]


def test_native_keys_are_exact_not_nearest_or_reinterpreted_raw_flags(memory):
    memory['put'](0x20010, CURRENT)
    days = calendar.decode(memory['read'], [(2030, 300, 0x10000), (2030, 302, 0x20000)],
                           calendar.window('2030-10-28', 1, None), label)
    assert days[0]['state'] == 'unavailable_resident_week' and memory['reads'] == []
    # Source supplies low9 already. An unmasked raw key violates its three-tuple contract.
    with pytest.raises(ValueError, match='week key'):
        calendar.decode(memory['read'], [(2030, 301 | (61 << 9), 0x10000)], [], label)


def test_signed_zero_unknown_and_all_row_bytes_remain_exact(memory):
    body = synthetic_body([-32768, -1, 600], [255, 128, 1, 0, 17, 42, 254])
    memory['put'](0x10010, body)
    days = calendar.decode(memory['read'], [(2030, 301, 0x10000)],
                           calendar.window('2030-10-28', 7, None), label)
    assert [d['unmapped_row_byte'] for d in days] == [255, 128, 1, 0, 17, 42, 254]
    assert all(d['slots'] == [label(0, -32768), label(1, -1), label(2, 600)] for d in days)
    memory['put'](0x10010, synthetic_body([0, 300, 32767]))
    again = calendar.decode(memory['read'], [(2030, 301, 0x10000)], [date(2030, 10, 28)], label)
    assert again[0]['slots'] == [label(0, 0), label(1, 300), label(2, 32767)]
    assert memory['reads'] == [(0x10010, 56), (0x10010, 56)]  # No persistent body cache.


@pytest.mark.parametrize('start,week,key,row', [
    ('1850-01-01', '1849-12-31', (1849, 365), 1),
    ('2031-01-01', '2030-12-30', (2030, 364), 2),
    ('2032-02-29', '2032-02-23', (2032, 54), 6),
    ('2032-03-01', '2032-03-01', (2032, 61), 0),
    ('1900-01-01', '1900-01-01', (1900, 1), 0),
])
def test_civil_year_leap_and_native_sentinel_boundaries(memory, start, week, key, row):
    memory['put'](0x10010, synthetic_body())
    d = calendar.decode(memory['read'], [(*key, 0x10000)], calendar.window(start, 1, None), label)[0]
    assert d['state'] == 'stored_assigned' and d['week_start'] == week
    assert d['storage_row'] == row and d['slots'][0]['native_code'] == row * 3


@pytest.mark.parametrize('entry', [
    (), (2030, 301), (2030, 301, 0x10000, 1), (True, 301, 0x10000),
    (2030, True, 0x10000), (-1, 301, 0x10000), (65536, 301, 0x10000),
    (2030, -1, 0x10000), (2030, 512, 0x10000),
    (2030, 301, None), (2030, 301, True), (2030, 301, 0),
    (2030, 301, 0x10004), (2030, 301, (1 << 64) - 64),
])
def test_malformed_week_entries_reject_even_when_not_selected(memory, entry):
    with pytest.raises(ValueError):
        calendar.decode(memory['read'], [entry], [], label)
    assert memory['reads'] == []


@pytest.mark.parametrize('dates', [None, '2030-10-28', ['2030-10-28'],
                                   [datetime(2030, 10, 28)], [date(1849, 12, 31)],
                                   [date(2201, 1, 1)], [None]])
def test_decode_rejects_invalid_civil_input(memory, dates):
    with pytest.raises(ValueError):
        calendar.decode(memory['read'], [], dates, label)


@pytest.mark.parametrize('length', [0, 1, 55, 57])
def test_selected_body_must_have_exact_length(length):
    with pytest.raises(ValueError, match='Incomplete'):
        calendar.decode(lambda *_: bytes(length), [(2030, 301, 0x10000)],
                        [date(2030, 10, 28)], label)


def test_unavailable_or_unselected_bodies_are_never_read(memory):
    assert calendar.decode(memory['read'], None, [], label) == []
    assert calendar.decode(memory['read'], [(2030, 301, 0x10000)], [], label) == []
    assert memory['reads'] == []


def test_label_output_is_passed_verbatim_and_label_failures_propagate(memory):
    memory['put'](0x10010, CURRENT)
    markers = [{'marker': i} for i in range(3)]
    d = calendar.decode(memory['read'], [(2030, 301, 0x10000)],
                        [date(2030, 10, 28)], lambda i, _: markers[i])[0]
    assert all(d['slots'][i] is markers[i] for i in range(3))

    def fail(*_):
        raise ValueError('label changed')

    with pytest.raises(ValueError, match='label changed'):
        calendar.decode(memory['read'], [(2030, 301, 0x10000)], [date(2030, 10, 28)], fail)


def test_selected_body_readset_detects_late_mutation(memory):
    memory['put'](0x10010, CURRENT)
    read = world.ReadSet(memory['read'])
    calendar.decode(read, [(2030, 301, 0x10000)], [date(2030, 10, 28)], label)
    memory['put'](0x10012, b'\0')
    with pytest.raises(ValueError):
        read.verify()


def test_native_layout_spans_verify_and_any_mismatch_fails(memory):
    base = 0x100000000
    for rva, expected in calendar.NATIVE_SPANS:
        memory['put'](base + rva, expected)
    calendar.verify_native(memory['read'], base)
    for rva, expected in calendar.NATIVE_SPANS:
        memory['put'](base + rva, bytes([expected[0] ^ 1]))
        with pytest.raises(ValueError, match='native layout changed'):
            calendar.verify_native(memory['read'], base)
        memory['put'](base + rva, expected)


@pytest.mark.parametrize('base', [None, True, 0, 0x10004, (1 << 64) - 8])
def test_native_layout_rejects_invalid_base(memory, base):
    with pytest.raises(ValueError, match='address'):
        calendar.verify_native(memory['read'], base)
