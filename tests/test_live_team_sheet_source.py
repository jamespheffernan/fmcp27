import struct
from unittest.mock import patch

import pytest

from fm_live_mcp import live_team_sheet_source as source


class Memory:
    def __init__(self):
        self.values = {}

    def put(self, address, data):
        self.values.update((address + index, byte) for index, byte in enumerate(data))

    def pack(self, address, fmt, *values):
        self.put(address, struct.pack(fmt, *values))

    def read(self, address, size):
        return bytes(self.values.get(address + index, 0) for index in range(size))


@pytest.fixture
def fixture(monkeypatch):
    memory = Memory()
    base, human, team, session = 0x100000000, 0x10000, 0x20000, 0x30000
    for rva, raw in source.NATIVE_SPANS:
        memory.put(base + rva, raw)
    memory.pack(human + 0x218, '<QQQ', 0, 0, 0)
    memory.pack(human + 0x200, '<QQQ', 0x80000, 0x80008, 0x80008)
    memory.pack(0x80000, '<Q', session)
    memory.pack(session, '<QQ', base + source.EDIT_VTABLE, human)
    memory.pack(session + 0x3590, '<Q', team)
    memory.pack(team + 8, '<I', 545)
    memory.pack(base + source.EDIT_VTABLE - 16, '<qQ', 0, 0x90000)
    memory.pack(0x90008, '<Q', 0x91000)
    memory.put(0x91000, source.EDIT_NAME + b'\0')
    memory.pack(base + source.EDIT_VTABLE + 0x10, '<Q', base + 0x22CED60)
    memory.pack(base + source.EDIT_VTABLE + 0x28, '<Q', base + 0x22CE460)
    indices = list(range(20)) + [-1] * 6
    memory.pack(session + 0x2200, '<26i', *indices)
    memory.pack(session + 0x35B1, '<b', 20)
    team_row = {'database_index': 545, 'native_id': 688, 'kind': 'team'}
    monkeypatch.setattr(source.prepared_tactics_source, 'verify_native', lambda *args: None)
    monkeypatch.setattr(source.prepared_tactics_source, '_team_and_human',
                        lambda *args: (team_row, human))
    monkeypatch.setattr(source.assessment_people, 'verify_native', lambda *args: None)
    monkeypatch.setattr(source.database, 'table', lambda *args: {'count': 100})
    monkeypatch.setattr(source, '_person', lambda read, base, people, index: {
        'database_index': index, 'native_id': 9000 + index, 'name': f'Player {index}',
        'display_name': f'Player {index}', 'record_kind': 'actual'})
    coach = {'team_address': team, 'manager_address': human}
    return memory, base, human, team, session, coach


def inspect(fixture):
    memory, base, human, team, session, coach = fixture
    return source.inspect(memory.read, base, coach)


def test_working_selection_not_zero_or_backup_copy(fixture):
    memory, base, human, team, session, coach = fixture
    memory.pack(session + 0x10 + 0x1020, '<26i', *([-1] * 26))
    memory.pack(session + 0x2398 + 0x1020, '<26i', *([70] * 26))
    result = inspect(fixture)
    assert result['source_state'] == 'available'
    assert (result['starting_count'], result['bench_count'], result['selected_count']) == (11, 9, 20)
    assert len(result['slots']) == 26 and result['empty_slot_count'] == 6
    assert result['slots'][0]['person']['database_index'] == 0
    assert result['slots'][11]['bench_ordinal'] == 1
    assert result['slots'][19]['bench_ordinal'] == 9
    assert result['slots'][20]['category'] == 'outside_selected_bench_boundary'
    assert result['slots'][20]['state'] == 'empty_slot'
    assert result['match_submission_state'] == 'not_established'
    assert result['foreground_screen_state'] == 'not_observed'


def test_empty_slots_are_not_missing_source(fixture):
    memory, _, _, _, session, _ = fixture
    memory.pack(session + 0x2200, '<26i', *([-1] * 26))
    result = inspect(fixture)
    assert result['source_state'] == 'available'
    assert result['empty_slot_count'] == 26
    assert result['starting_count'] == result['bench_count'] == 0
    assert all(row['person'] is None for row in result['slots'])


def test_missing_source_does_not_invent_empty_selection(fixture):
    memory, _, human, _, _, _ = fixture
    memory.pack(human + 0x200, '<QQQ', 0, 0, 0)
    result = inspect(fixture)
    assert result['source_state'] == 'unavailable'
    assert result['unavailable_reason'] == 'existing_tactic_edit_session_missing'
    assert result['slots'] is None and result['selected_count'] is None


def test_null_contexts_and_foreign_team_are_skipped(fixture):
    memory, _, human, team, session, _ = fixture
    memory.pack(human + 0x200, '<QQQ', 0x80000, 0x80010, 0x80010)
    memory.pack(0x80000, '<QQ', 0, session)
    assert inspect(fixture)['source_state'] == 'available'
    memory.pack(session + 0x3590, '<Q', team + 0x1000)
    memory.pack(team + 0x1008, '<I', 99)
    assert inspect(fixture)['slots'] is None


def test_wrong_human_or_reused_team_is_rejected(fixture):
    memory, _, human, team, session, _ = fixture
    memory.pack(session + 8, '<Q', human + 8)
    with pytest.raises(ValueError, match='HUMAN ownership'):
        inspect(fixture)
    memory.pack(session + 8, '<Q', human)
    memory.pack(session + 0x3590, '<Q', team + 0x1000)
    memory.pack(team + 0x1008, '<I', 545)
    with pytest.raises(ValueError, match='canonical team'):
        inspect(fixture)


def test_duplicate_sessions_are_explicitly_unavailable(fixture):
    memory, _, human, _, session, _ = fixture
    memory.pack(human + 0x200, '<QQQ', 0x80000, 0x80010, 0x80010)
    memory.pack(0x80000, '<QQ', session, session)
    assert inspect(fixture)['unavailable_reason'] == 'multiple_matching_tactic_edit_sessions'


def test_preserves_duplicate_players_and_outside_boundary_people(fixture):
    memory, _, _, _, session, _ = fixture
    indices = [0] * 2 + list(range(2, 20)) + [70] + [-1] * 5
    memory.pack(session + 0x2200, '<26i', *indices)
    result = inspect(fixture)
    assert result['duplicate_person_indices'] == [0]
    assert result['slots'][0]['person'] == result['slots'][1]['person']
    assert result['selected_count'] == 20 and result['stored_nonnull_count'] == 21
    assert result['slots'][20]['state'] == 'stored_outside_selected_extent'


@pytest.mark.parametrize('boundary', [-1, 0, 10, 27, 127])
def test_unmapped_bench_boundary_preserves_independent_formation_slots(fixture, boundary):
    memory, _, _, _, session, _ = fixture
    memory.pack(session + 0x35B1, '<b', boundary)
    result = inspect(fixture)
    assert result['source_state'] == 'available'
    assert len(result['slots']) == 26 and result['stored_nonnull_count'] == 20
    assert result['selected_count'] is None and result['bench_count'] is None
    assert result['role_boundary_state'] == 'stored_boundary_unmapped'
    assert result['formation_boundary_state'] == 'native_first_11'
    assert result['starting_count'] == 11
    assert all(row['category'] == 'starting_position' and row['state'] == 'selected_person'
               for row in result['slots'][:11])
    assert all(row['category'] is None and row['bench_ordinal'] is None
               for row in result['slots'][11:])


def test_bad_negative_slot_and_vector_budget(fixture):
    memory, _, human, _, session, _ = fixture
    memory.pack(session + 0x2200, '<i', -2)
    with pytest.raises(ValueError, match='negative selected PERSON'):
        inspect(fixture)
    memory.pack(human + 0x200, '<QQQ', 0x80000, 0x80208, 0x80208)
    with pytest.raises(ValueError, match='budget'):
        inspect(fixture)


def test_every_embedded_native_guard_rejects_mutation(fixture):
    memory, base, _, _, _, _ = fixture
    for rva, raw in source.NATIVE_SPANS:
        memory.put(base + rva, bytes([raw[0] ^ 1]) + raw[1:])
        with pytest.raises(ValueError, match='native source changed'):
            inspect(fixture)
        memory.put(base + rva, raw)


def test_unknown_kind_getter_is_not_silently_skipped(fixture):
    memory, base, _, _, _, _ = fixture
    method = base + 0x12340
    memory.pack(base + source.EDIT_VTABLE + 0x10, '<Q', method)
    memory.pack(method, '<II', 0xD503201F, 0xD65F03C0)
    assert inspect(fixture)['unavailable_reason'] == 'unsupported_edit_context_kind_getter'


def test_no_addresses_in_public_result(fixture):
    result = inspect(fixture)
    forbidden = {'pointer', 'address', 'human_owner', 'owner_key', 'payload'}
    def walk(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(result)


# ----------------------------------------------------------------- the bench end without a bound fixture
def _next_fixture(fixture, monkeypatch, *, code=58, side='away', day=18, today=16, year=2031):
    """Give the TEAM a cached next fixture the way 17743B8 finds it: [[team+A0]+B8]."""
    memory, base, _, team, session, _ = fixture
    holder, match, other = 0x40000, 0x50000, 0x60000
    for rva, raw in source.NEXT_FIXTURE_SPANS:
        memory.put(base + rva, raw)
    memory.pack(session + 0x35B0, '<bb', 0, 0)
    memory.pack(team + 0xA0, '<Q', holder)
    memory.pack(holder + 0xB8, '<Q', match)
    table = base + source.fixtures.TYPES['fixture'][0]
    memory.pack(match, '<QQQ', table, *((team, other) if side == 'home' else (other, team)))
    memory.pack(match + 0x3E, '<b', code)
    memory.pack(match + 0x4C, '<HH', day, year)
    memory.pack(base + source.world.CURRENT_DATE, '<HH', today, year)
    memory.pack(table + 0xB0, '<Q', base + 0x3CFAB7C)
    monkeypatch.setattr(source.fixtures, 'typed', lambda *args: None)
    monkeypatch.setattr(source.fixture_rules, 'verify_native', lambda *args: None)
    return holder, match


def test_unbound_session_takes_the_selection_screens_count_for_the_cached_next_fixture(fixture, monkeypatch):
    """Both extent bytes zero (no fixture bound): slots 11.. are the bench as far as the named
    substitutes of the TEAM's cached next fixture allow (code 58: nine)."""
    _next_fixture(fixture, monkeypatch)
    result = inspect(fixture)
    assert result['role_boundary_state'] == source.NEXT_FIXTURE_END
    assert result['bench_boundary_source'] == 'selection_screen_rule_for_cached_next_fixture'
    assert result['session_fixture_extent_state'] == 'unset_no_fixture_bound'
    assert result['stored_selected_end'] == 0 and result['bench_end'] == 20
    assert (result['starting_count'], result['bench_count'], result['selected_count']) == (11, 9, 20)
    assert [row['bench_ordinal'] for row in result['slots'][11:20]] == list(range(1, 10))
    assert all(row['category'] == 'bench' and row['state'] == 'selected_person' for row in result['slots'][11:20])
    assert all(row['category'] == 'outside_selected_bench_boundary' for row in result['slots'][20:])
    assert result['bench_fixture'] == {
        'date': '2031-01-18', 'days_from_current_date': 2, 'managed_side': 'away',
        'native_rule_code': 58, 'named_substitute_cap': 9, 'used_substitute_cap': 5,
        'fixture_ceiling': 15, 'source': 'team_cached_next_fixture_pointer'}
    assert result['bench_boundary_unavailable_reason'] is None
    assert result['match_submission_state'] == 'not_established'
    assert source.bench_known(result)


@pytest.mark.parametrize('code', [0, 3, 20, 24, 44, 58, 67, 90])
@pytest.mark.parametrize('side', ['home', 'away'])
def test_next_fixture_bench_end_is_eleven_plus_the_named_cap_of_that_side(fixture, monkeypatch, code, side):
    _next_fixture(fixture, monkeypatch, code=code, side=side)
    memory, _, _, _, session, _ = fixture
    memory.pack(session + 0x2200, '<26i', *range(26))
    cap = source.fixture_rules.substitutions(code, side == 'away', 15)['named_substitute_cap']
    result = inspect(fixture)
    assert result['bench_end'] == 11 + cap and result['bench_count'] == cap
    assert result['selected_count'] == 11 + cap and result['stored_nonnull_count'] == 26
    assert [row['category'] for row in result['slots']] == (
        ['starting_position'] * 11 + ['bench'] * cap + ['outside_selected_bench_boundary'] * (15 - cap))
    assert all(row['state'] == 'stored_outside_selected_extent' for row in result['slots'][11 + cap:])


def test_a_stored_session_end_is_used_as_before_and_the_next_fixture_is_not_read(fixture, monkeypatch):
    memory, _, _, _, session, _ = fixture
    _next_fixture(fixture, monkeypatch, code=67, side='home')         # would give twelve
    memory.pack(session + 0x35B0, '<bb', 20, 18)
    result = inspect(fixture)
    assert result['role_boundary_state'] == source.STORED_END
    assert result['bench_boundary_source'] == 'session_stored_fixture_extent'
    assert result['session_fixture_extent_state'] == 'stored_for_a_bound_fixture'
    assert (result['bench_end'], result['bench_count'], result['bench_fixture']) == (18, 7, None)
    assert result['slots'][18]['state'] == 'stored_outside_selected_extent'


@pytest.mark.parametrize('change, reason', [
    (lambda m, base, team, holder, match: m.pack(team + 0xA0, '<Q', 0), 'team_fixture_cache_absent'),
    (lambda m, base, team, holder, match: m.pack(team + 0xA0, '<Q', holder + 1), 'team_fixture_cache_pointer_invalid'),
    (lambda m, base, team, holder, match: m.pack(holder + 0xB8, '<Q', 0), 'next_fixture_not_cached'),
    (lambda m, base, team, holder, match: m.pack(holder + 0xB8, '<Q', 0x800), 'cached_next_fixture_pointer_invalid'),
    (lambda m, base, team, holder, match: m.pack(match, '<Q', base + source.fixtures.TYPES['result'][0]),
     'cached_next_fixture_unsupported_type'),
    (lambda m, base, team, holder, match: m.pack(match + 8, '<QQ', 0x60000, 0x70000),
     'team_not_exactly_one_side_of_cached_next_fixture'),
    (lambda m, base, team, holder, match: m.pack(match + 8, '<QQ', team, team),
     'team_not_exactly_one_side_of_cached_next_fixture'),
    (lambda m, base, team, holder, match: m.pack(match + 0x4C, '<HH', 15, 2031), 'cached_next_fixture_before_current_date'),
    (lambda m, base, team, holder, match: m.pack(match + 0x4C, '<HH', 1, 1900) or
     m.pack(base + source.world.CURRENT_DATE, '<HH', 0, 2031), 'cached_next_fixture_date_unsupported'),
    (lambda m, base, team, holder, match: m.pack(match + 0x3E, '<b', -1), 'next_fixture_substitution_rule_unsupported'),
    (lambda m, base, team, holder, match: m.pack(match + 0x3E, '<b', 91), 'next_fixture_substitution_rule_unsupported'),
    (lambda m, base, team, holder, match: m.pack(base + source.fixtures.TYPES['fixture'][0] + 0xB0, '<Q', base + 0x3CFAB80),
     'fixture_substitution_rule_unavailable'),
    (lambda m, base, team, holder, match: m.put(base + source.NEXT_FIXTURE_SPANS[2][0], b'\0' * 4),
     'next_fixture_rule_native_source_changed'),
])
def test_what_the_next_fixture_rule_cannot_establish_stays_unresolved(fixture, monkeypatch, change, reason):
    """No cached fixture, another object, a past date, a rule code outside the game's table or
    changed native code: slots 11.. keep no category, and the first eleven still answer."""
    memory, base, _, team, _, _ = fixture
    holder, match = _next_fixture(fixture, monkeypatch)
    change(memory, base, team, holder, match)
    result = inspect(fixture)
    assert result['source_state'] == 'available' and result['formation_boundary_state'] == 'native_first_11'
    assert result['role_boundary_state'] == 'stored_boundary_unmapped'
    assert result['bench_boundary_unavailable_reason'] == reason
    assert result['bench_end'] is None and result['bench_boundary_source'] is None
    assert result['selected_count'] is None and result['bench_count'] is None and result['bench_fixture'] is None
    assert all(row['category'] is None and row['bench_ordinal'] is None for row in result['slots'][11:])
    assert all(row['state'] == 'stored_person_boundary_unresolved' for row in result['slots'][11:20])
    assert not source.bench_known(result)


@pytest.mark.parametrize('permitted, selected', [(20, 0), (0, 5), (20, 27), (-1, -1)])
def test_a_stored_extent_the_reader_does_not_understand_is_not_replaced_by_the_rule(
        fixture, monkeypatch, permitted, selected):
    """Only the constructor's zero pair means no fixture was bound; any other pair that is not a
    valid end stays unresolved, with the next fixture left unread."""
    memory, _, _, _, session, _ = fixture
    _next_fixture(fixture, monkeypatch)
    memory.pack(session + 0x35B0, '<bb', permitted, selected)
    result = inspect(fixture)
    assert result['role_boundary_state'] == 'stored_boundary_unmapped'
    assert result['session_fixture_extent_state'] == 'unsupported_stored_value'
    assert result['bench_boundary_unavailable_reason'] == 'unsupported_stored_selected_end'
    assert result['bench_fixture'] is None and result['bench_count'] is None


def test_the_rule_is_withheld_on_a_build_where_its_code_is_not_mapped(fixture, monkeypatch):
    _next_fixture(fixture, monkeypatch)
    monkeypatch.setattr(source._next_fixture_bench, 'blocked', lambda: ['0x2e4dbe4 unresolved'])
    result = inspect(fixture)
    assert result['role_boundary_state'] == 'stored_boundary_unmapped'
    assert result['bench_boundary_unavailable_reason'] == 'next_fixture_rule_not_mapped_on_this_build'
