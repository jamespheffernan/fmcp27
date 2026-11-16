import struct
from datetime import date

import pytest

from fm_live_mcp import player_injury_status as source, players, world


def packed(day, year=2030):
    return struct.pack('<HH', day, year)


def instance(start=291, year=2030, duration=64, phase=44, kind=2,
             native_phase=3, weeks=-1):
    raw = bytearray(0x38)
    raw[0x20:0x24] = packed(start, year)
    struct.pack_into('<hh', raw, 0x28, duration, phase)
    raw[0x2E] = native_phase
    raw[0x30] = kind
    struct.pack_into('<b', raw, 0x33, weeks)
    return bytes(raw)


def evaluate(raw, today=301, year=2030, sentinel=None):
    return source.evaluate(raw, packed(today, year), sentinel or packed(1, 1900))


def test_observed_ramsey_positive_is_named_status_not_clearance_or_estimate():
    result = evaluate(instance())
    assert result['state'] == 'checked' and result['flagged'] is True
    assert result['native_status_code'] == 2
    assert result['computed_flag_bit'] == {'word_index': 0, 'bit_index': 41}
    assert result['english_label']['text'] == 'Injured'
    assert 'return_date' not in result and 'raw38_hex' not in result


def test_synthetic_status_one_has_same_english_label_without_severity_claim():
    result = evaluate(instance(kind=4))
    assert result['native_status_code'] == 1
    assert result['computed_flag_bit']['bit_index'] == 8
    assert result['english_label']['text'] == 'Injured'


def test_present_expired_record_is_checked_negative_not_missing_record():
    result = evaluate(instance(), today=356)
    assert result['state'] == 'checked' and result['flagged'] is False
    assert result['native_status_code'] == 0
    assert result['reason'] == 'expired_single_injury_source'


def test_same_day_zero_status_is_not_inferred_from_record_presence():
    result = evaluate(instance(kind=0), today=291)
    assert result['state'] == 'checked' and result['flagged'] is False


@pytest.mark.parametrize('raw,today,year,reason', [
    (instance(year=2029), 301, 2030, 'cross_year_injury_branch'),
    (instance(duration=-1), 301, 2030, 'negative_duration_branch'),
    (instance(duration=100), 301, 2030, 'injury_end_crosses_audited_year_range'),
    (instance(start=302, duration=50), 301, 2030, 'future_start_injury_branch'),
])
def test_unproved_branch_is_unknown_never_negative(raw, today, year, reason):
    result = evaluate(raw, today, year)
    assert result['state'] == 'unsupported' and result['flagged'] is None
    assert result['reason'] == reason and result['native_status_code'] is None


def test_wrong_duration_sentinel_is_unknown():
    result = evaluate(instance(), sentinel=packed(2, 1900))
    assert result['flagged'] is None
    assert result['reason'] == 'native_duration_sentinel_changed'


def test_positive_week_byte_uses_exact_seven_times_branch():
    for weeks in range(128):
        result = evaluate(instance(weeks=weeks))
        expected = 2 if 10 < 7 * weeks else 1
        assert result['native_status_code'] == expected


def test_all_status_input_bytes_retain_native_branch_order():
    for kind in range(256):
        result = evaluate(instance(kind=kind))
        assert result['native_status_code'] == (1 if kind == 4 else 2)


class Memory:
    def __init__(self):
        self.values = {}

    def put(self, address, raw):
        self.values.update((address + i, byte) for i, byte in enumerate(raw))

    def pack(self, address, fmt, *values):
        self.put(address, struct.pack(fmt, *values))

    def read(self, address, size):
        assert size > 0
        return bytes(self.values.get(address + i, 0) for i in range(size))


@pytest.fixture
def memory(monkeypatch):
    memory = Memory()
    base, primary = 0x100000000, 0x10000
    memory.pack(primary, '<Q', base + players.RVA[0])
    for rva, raw in source.NATIVE_SPANS:
        memory.put(base + rva, raw)
    memory.pack(base + players.RVA[0] + 0x460, '<Q', base + 0xD1FDD4)
    monkeypatch.setattr(source.database, 'table', lambda *args: {'count': 1})
    monkeypatch.setattr(source.player_health, 'injury', lambda *args: {
        'name': 'hip injury', 'started': '2030-10-18', 'evidence': 'typed_test_definition',
    })
    return memory, base, primary


def project(fixture, kind='actual'):
    memory, base, primary = fixture
    return source.project(memory.read, base, primary, kind, packed(301), packed(1, 1900))


def test_null_and_checked_empty_sources_are_native_checked_negative(memory):
    data, _, primary = memory
    assert project(memory)['flagged'] is False
    data.pack(primary + 0xF0, '<Q', 0x20000)
    data.pack(0x20000, '<QQQ', 0, 0, 0)
    result = project(memory)
    assert result['state'] == 'checked' and result['stored_injury_record_count'] == 0
    assert result['stored_injuries'] == []


def test_allocated_empty_vector_never_issues_zero_size_read(memory):
    data, _, primary = memory
    data.pack(primary + 0xF0, '<Q', 0x20000)
    data.pack(0x20000, '<QQQ', 0x30000, 0x30000, 0x30008)
    assert project(memory)['flagged'] is False


def test_single_named_record_and_multiple_source_unknown_are_distinct(memory):
    data, _, primary = memory
    data.pack(primary + 0xF0, '<Q', 0x20000)
    data.pack(0x20000, '<QQQ', 0x30000, 0x30008, 0x30010)
    data.pack(0x30000, '<Q', 0x40000)
    data.put(0x40000, instance())
    result = project(memory)
    assert result['flagged'] is True and result['stored_injury_record_count'] == 1
    assert result['stored_injuries'][0]['name'] == 'hip injury'
    data.pack(0x20000, '<QQQ', 0x30000, 0x30010, 0x30010)
    result = project(memory)
    assert result['flagged'] is None and result['stored_injury_record_count'] == 2
    assert result['stored_injuries'] is None


@pytest.mark.parametrize('kind', ['player_staff', 'virtual'])
def test_other_player_types_unknown_without_reading_unproved_offsets(memory, kind):
    result = project(memory, kind)
    assert result['flagged'] is None and result['stored_injury_record_count'] is None


def test_changed_source_detected_before_publish(memory):
    data, base, primary = memory
    read = world.ReadSet(data.read)
    source.project(read, base, primary, 'actual', packed(301), packed(1, 1900))
    data.put(primary + 0xF0, b'X')
    with pytest.raises(ValueError):
        read.verify()


def test_every_native_guard_and_actual_vslot_are_required(memory):
    data, base, _ = memory
    source.verify_native(data.read, base)
    for rva, raw in source.NATIVE_SPANS:
        data.put(base + rva, bytes([raw[0] ^ 1]))
        with pytest.raises(ValueError):
            source.verify_native(data.read, base)
        data.put(base + rva, raw)
    data.pack(base + players.RVA[0] + 0x460, '<Q', base + 0xD1FDD8)
    with pytest.raises(ValueError):
        source.verify_native(data.read, base)


def test_calendar_uses_today_and_rejects_invalid_nonleap_day():
    assert source.calendar(packed(301))[0] == date(2030, 10, 28)
    with pytest.raises(ValueError):
        source.calendar(packed(366, 2030))
