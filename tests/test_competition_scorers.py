import struct

import pytest

from fm_live_mcp import competition_scorers as source, players


class Memory:
    def __init__(self):
        self.values = {}

    def put(self, address, raw):
        self.values.update((address + i, value) for i, value in enumerate(raw))

    def pack(self, address, fmt, *values):
        self.put(address, struct.pack(fmt, *values))

    def read(self, address, length):
        assert length > 0
        return bytes(self.values.get(address + i, 0) for i in range(length))


@pytest.fixture
def census(monkeypatch):
    memory = Memory()
    base, runtime, stats, comp = 0x100000000, 0x10000, 0x20000, 0x30000
    context = {
        'competition': {'database_index': 7, 'native_id': 11,
                        'context': {'competition_type': {'native_code': 0}}},
        'shared_runtime': False, 'native_season_code': 2030,
    }
    binding = (runtime, source.ACTUAL_COMP, comp, 7, 11, 2030)
    for rva, raw in source.NATIVE_SPANS:
        memory.put(base + rva, raw)
    memory.pack(runtime + 0x390, '<Q', stats)
    memory.pack(stats, '<Q', base + source.STATS_TYPE[0])
    memory.pack(stats + 0x7B8, '<Q', comp)
    memory.pack(base + source.STATS_TYPE[0] - 16, '<qQ', 0, 0x90000)
    memory.pack(0x90008, '<Q', 0x91000)
    memory.put(0x91000, source.STATS_TYPE[1] + b'\0')
    # The code pointer is four-aligned; data pointers retain eight alignment.
    memory.pack(base + source.STATS_TYPE[0] + 0x40, '<Q', base + 0xF3CA9C)
    memory.pack(stats + 0x1278, '<QQQ', 0x40000, 0x40010, 0x40010)
    memory.pack(0x40000, '<QQ', 0x50000, 0x500AC)
    for index, address in enumerate((0x50000, 0x500AC)):
        raw = bytearray(16)
        struct.pack_into('<II', raw, 0, index, 545)
        raw[0xC] = 7 - index
        memory.put(address, raw)
        person = 0x70000 + index * 0x10000
        table = players.RVA[2] if index == 0 else players.STAFF_RVA[2]
        memory.pack(0x60000 + index * 8, '<Q', person)
        memory.pack(person, '<QIII', base + table, index, 100 + index, 100 + index)

    def runtime_context(*args):
        return context, runtime, binding

    def person(read, current_base, people, address):
        index = 0 if address == 0x70000 else 1
        kind = 'actual' if index == 0 else 'player_staff'
        identity = {'record_kind': kind, 'native_identity': {
            'database_index': index, 'native_id': 100 + index, 'random_id': None}}
        return address - (0x388 if index == 0 else 0x480), 0, identity, 100 + index, 100 + index

    monkeypatch.setattr(source.competition_stages, 'runtime_context', runtime_context)
    monkeypatch.setattr(source.database, 'table', lambda *args: {'count': 2, 'start': 0x60000})
    monkeypatch.setattr(source.assessment_people, 'verify_native', lambda *args: None)
    monkeypatch.setattr(source.assessment_people, '_person', person)
    return {'memory': memory, 'base': base, 'runtime': runtime, 'stats': stats,
            'comp': comp, 'context': context, 'binding': binding}


def collect(census):
    return source.collect(census['memory'].read, census['base'], {})


def test_complete_pool_accepts_four_aligned_rows_and_code_pointer(census):
    coverage, rows = collect(census)
    assert coverage['physical_count'] == 2
    assert coverage['stored_goals_sum'] == 13
    assert [row['goals'] for row in rows] == [7, 6]
    assert rows[1]['_identity']['record_kind'] == 'player_staff'
    assert coverage['complete_resident_pool']


def test_255_is_a_stored_counter_not_compact_unavailable_sentinel(census):
    census['memory'].put(0x5000C, b'\xff')
    coverage, rows = collect(census)
    assert rows[0]['goals'] == 255
    assert coverage['stored_goals_sum'] == 261


def test_valid_empty_vector_distinct_from_absent_stats(census):
    memory = census['memory']
    memory.pack(census['stats'] + 0x1278, '<QQQ', 0, 0, 0)
    coverage, rows = collect(census)
    assert coverage['source_state'] == 'available' and coverage['physical_count'] == 0
    assert rows == []
    memory.pack(census['runtime'] + 0x390, '<Q', 0)
    coverage, rows = collect(census)
    assert coverage['source_state'] == 'unavailable'
    assert coverage['physical_count'] is None
    assert coverage['unavailable_reason'] == 'current_competition_stats_not_resident'


def test_allocated_empty_vector_issues_no_zero_read(census):
    census['memory'].pack(census['stats'] + 0x1278, '<QQQ', 0x40000, 0x40000, 0x40010)
    assert collect(census)[0]['physical_count'] == 0


def test_missing_runtime_and_cups_cannot_become_league_results(census, monkeypatch):
    monkeypatch.setattr(source.competition_stages, 'runtime_context',
                        lambda *args: (census['context'], None, None))
    assert collect(census)[0]['unavailable_reason'] == 'current_runtime_competition_absent'
    census['context']['competition']['context']['competition_type']['native_code'] = 3
    assert collect(census)[0]['unavailable_reason'] == 'unsupported_competition_kind_for_league_query'


def test_shared_runtime_is_not_silently_parent_competition(census):
    census['context']['shared_runtime'] = True
    assert collect(census)[0]['unavailable_reason'] == 'shared_runtime_competition_owner'


def test_owner_backlink_change_rejected(census):
    census['memory'].pack(census['stats'] + 0x7B8, '<Q', census['comp'] + 8)
    with pytest.raises(ValueError, match='ownership'):
        collect(census)


def test_duplicate_person_rows_not_summed_or_silently_chosen(census):
    census['memory'].pack(0x500AC, '<I', 0)
    coverage, rows = collect(census)
    assert coverage['unavailable_reason'] == 'ambiguous_duplicate_person_entries'
    assert rows == [] and not coverage['complete_resident_pool']


def test_unresolved_person_preserves_counter_and_unknown_identity(census):
    census['memory'].pack(0x60000, '<Q', 0)
    coverage, rows = collect(census)
    assert coverage['unknown_identity_count'] == 1
    assert rows[0]['goals'] == 7 and rows[0]['_identity'] is None


def test_each_native_guard_is_required(census):
    for rva, raw in source.NATIVE_SPANS:
        census['memory'].put(census['base'] + rva, bytes([raw[0] ^ 1]))
        with pytest.raises(ValueError, match='native source'):
            collect(census)
        census['memory'].put(census['base'] + rva, raw)


def test_changed_goal_counter_detected_before_publication(census):
    from fm_live_mcp import world
    read = world.ReadSet(census['memory'].read)
    source.collect(read, census['base'], {})
    census['memory'].put(0x5000C, b'\x08')
    with pytest.raises(ValueError):
        read.verify()
