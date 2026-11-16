"""Execute the complete pinned E58E5C and all reached original callees."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import struct

import pytest

from fm_live_mcp import knowledge_club_admission_source as source
from fm_live_mcp import knowledge_club_score_source as score
from fm_live_mcp import knowledge_competition_context_source as competition
from fm_live_mcp import world
from test_knowledge_club_score_source import memory_fixture as score_fixture, install_stage
from test_knowledge_search_preliminary_source import identity, restore_metadata
from _knowledge_state_native import execute


def memory_fixture(combined=False):
    m = score_fixture(combined)
    for rva, size, digest in source.NATIVE_GUARDS:
        raw = m.disk(rva, size)
        assert hashlib.sha256(raw).hexdigest() == digest
        m.put(m.base + rva, raw)
    m.put(m.base + 0x56d4950, b'\0')
    m.put(m.base + 0x56d496e, b'\0')
    m.put(m.base + 0x56d4992, b'\0')
    m.put(m.base + world.TYPES['manager'][0] - 0x20, m.disk(world.TYPES['manager'][0] - 0x20, 8))
    for table in (0x558a780, 0x55908e0):
        for slot in (0x4e0, 0x658, 0x4d8):
            target = int.from_bytes(m.disk(table + slot, 8), 'little') & 0xffffffff
            m.q(m.base + table + slot, m.base + target)
        m.put(m.base + table - 0x668, m.disk(table - 0x668, 8))
    restore_metadata(m)
    return m


def actual(m, mode=0, **kwargs):
    result = source.evaluate(m.read, m.base, m.club, identity(m, m.club), m.person,
        identity(m, m.person), mode=mode,
        check_current=kwargs.pop('check_current', lambda: ('process', 'save', 'build')), **kwargs)
    assert result['complete_search_population_evaluated'] is False
    assert result['field_visibility_evaluated'] is False
    return result['native_result']


def native(m, mode=0):
    result, _, _, writes, trace = execute(m, 0xe58e5c, [m.club, m.primary, mode],
        extra=source.NATIVE_GUARDS + score.NATIVE_GUARDS + competition.NATIVE_GUARDS)
    assert all(0x200000000 <= at < at + size <= 0x200010000 for _, at, size in writes)
    return bool(result), trace


def ordinary(m):
    m.put(m.base + 0x56d4951, b'\0')
    m.put(m.primary + 0x25a, struct.pack('<h', 4999))
    m.put(m.personal + 0xda4, b'\0')


def full(m, flags=0):
    main = m.contract('full_contract', m.person, m.team)
    m.q(m.common + 0x78, main)
    m.q(main + 0x18, m.team)
    m.put(main + 0x57, bytes([flags]))
    m.q(m.base + world.TYPES['full_contract'][0] + 0x128, m.base + 0x1005c90)
    restore_metadata(m)
    return main


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('mode', [0, 1])
def test_global_and_scalar_shortcuts_execute_full_original(combined, mode):
    m = memory_fixture(combined)
    assert actual(m, mode) == native(m, mode)[0] is True
    m.put(m.base + 0x56d4951, b'\0')
    assert actual(m, mode) == native(m, mode)[0] is True


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('mode', [0, 1])
def test_full_contract_negative_and_range_positive_match_original(combined, mode):
    m = memory_fixture(combined)
    ordinary(m)
    full(m)
    assert actual(m, mode) == native(m, mode)[0] is False
    m.put(m.personal + 0xda4, b'\7')
    assert actual(m, mode) == native(m, mode)[0] is True


@pytest.mark.parametrize('combined', [False, True])
def test_owner_absent_never_admits_in_mode_one_without_shortcut(combined):
    m = memory_fixture(combined)
    ordinary(m)
    m.q(m.team + 0x80, 0)
    assert actual(m, 1) == native(m, 1)[0] is False
    m.put(m.base + 0x56d4950, b'\1')
    assert actual(m) == native(m)[0] is True


@pytest.mark.parametrize('combined', [False, True])
def test_discard_ordinal_resolves_current_canonical_person_before_shortcuts(combined):
    m = memory_fixture(combined)
    m.put(m.base + 0x56d4951, b'\0')
    row = m.allocate(8)
    m.put(row, struct.pack('<i', 0))
    m.vec(m.personal + 0xbd8 + 0x30, [row])
    assert actual(m) == native(m)[0] is False
    m.put(row, struct.pack('<i', -1))
    assert actual(m) == native(m)[0] is True


@pytest.mark.parametrize('alternate', [[], [0], ['subject'], ['owner']])
def test_discard_alternate_table_precedes_canonical_fallback(alternate):
    m = memory_fixture()
    m.put(m.base + 0x56d4951, b'\0')
    m.put(m.base + 0x56d34e0, b'\0')
    row = m.allocate(8)
    m.put(row, struct.pack('<i', 0))
    m.vec(m.personal + 0xbd8 + 0x30, [row])
    values = [m.person if v == 'subject' else m.human_person if v == 'owner' else v for v in alternate]
    root = m.tables['people'][0]
    m.vec(root + 0x68, values)
    assert actual(m) == native(m)[0] == (alternate not in ([], ['subject']))


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('flags', [0, 1, 2, 4, 8, 16, 255])
def test_full_contract_flags_match_original(combined, flags):
    m = memory_fixture(combined)
    ordinary(m)
    full(m, flags)
    assert actual(m) == native(m)[0] == bool(flags & 11)


def foreign(m):
    ordinary(m)
    team = m.typed('team', 0x180)
    m.identity(team, 2, 7001, 7002)
    m.database('teams', [m.team, m.national, team])
    m.q(team + 0x30, m.other)
    m.q(team + 0x50, m.competition)
    m.q(m.other + 0xd8, m.target)
    m.vec(m.other + 0x18, [team])
    m.q(m.primary + 0x128, team)
    m.put(m.common + 0x58, struct.pack('<HH', 100, 2000))
    m.put(m.target_projection + 0x1ea, struct.pack('<h', 10000))
    restore_metadata(m)


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('simulation_mode', [0, 1, 2, 3, 4])
@pytest.mark.parametrize('threshold', [0, 4999, 5000, 7499, 7500, 10000])
def test_foreign_score_threshold_preserves_float32(combined, simulation_mode, threshold):
    m = memory_fixture(combined)
    foreign(m)
    install_stage(m, 'national', 20)
    m.put(m.base + 0x56d4950, bytes([simulation_mode]))
    m.put(m.primary + 0x258, struct.pack('<h', threshold))
    assert actual(m) == native(m)[0]


def test_unproved_association_is_unavailable_not_false():
    m = memory_fixture()
    ordinary(m)
    m.q(m.primary + 0x128, 0)
    m.q(m.common + 0x78, 0)
    m.q(m.base + 0x558a780 + 0x4e0, m.base + 0xca4954)
    with pytest.raises(ValueError, match='route'):
        actual(m)


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('fallback', ['contract', 'stored_club', 'nation', 'null', 'secondary_contract', 'secondary_team'])
def test_association_fallbacks_execute_whole_original(combined, fallback):
    m = memory_fixture(combined)
    ordinary(m)
    m.q(m.primary + 0x128, 0)
    if fallback == 'contract':
        m.put(m.main + 0x26, b'\2')
    else:
        m.q(m.common + 0x78, 0)
    if fallback == 'stored_club':
        m.q(m.common + 0xd8, m.club)
    elif fallback in ('secondary_contract', 'secondary_team'):
        # Actual's literal-false4e0 must ignore these synthetic staff-looking
        # operands; combined follows the real NON_PLAYER fallback instead.
        if fallback == 'secondary_contract':
            secondary = m.contract('full_contract', m.person, m.team)
            m.q(m.holder + 0x10, secondary)
        else:
            m.q(m.primary + 0x278 + 0x60, m.team)
    if fallback == 'null':
        m.q(m.common + 0xd8, 0)
        m.q(m.common + 0x38, 0)
    restore_metadata(m)
    assert actual(m) == native(m)[0]


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('role', [0, 1, 2, 255])
def test_actual_and_combined_secondary_getter_are_not_conflated(combined, role):
    m = memory_fixture(combined)
    ordinary(m)
    m.put(m.main + 0x26, bytes([role]))
    expected = not combined or role < 2
    assert actual(m) == native(m)[0] == expected


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('birth_year', [2012, 2013, 2014, 2015, 2016])
@pytest.mark.parametrize('owner', [False, True])
def test_original_conditional_age_owner_comparison_is_preserved(combined, birth_year, owner):
    m = memory_fixture(combined)
    foreign(m)
    install_stage(m, 'national', 40)
    m.put(m.common + 0x58, struct.pack('<HH', 100, birth_year))
    if not owner:
        m.q(m.team + 0x80, 0)
    assert actual(m) == native(m)[0]


@pytest.mark.parametrize('scalar', [4999, 5000, 6250, 6251, 7000, 7001, 7999, 8000])
@pytest.mark.parametrize('native_mode', [0, 2, 3, 4])
@pytest.mark.parametrize('flag', [0, 1])
def test_prominence_scalar_mode_flag_boundaries_match_original(scalar, native_mode, flag):
    m = memory_fixture()
    ordinary(m)
    full(m)
    m.put(m.primary + 0x25a, struct.pack('<h', scalar))
    m.put(m.base + 0x56d4951, bytes([native_mode]))
    m.put(m.base + 0x56d496e, bytes([flag]))
    assert actual(m) == native(m)[0]


@pytest.mark.parametrize('value', [0, 1, 20, 100, 106, 107, 120, 121, 255, 65535])
@pytest.mark.parametrize('scalar', [4999, 6251, 7000])
def test_prominence_unsigned_value_and_projection_thresholds(value, scalar):
    m = memory_fixture()
    ordinary(m)
    full(m)
    m.put(m.common + 0x104, struct.pack('<H', value))
    m.put(m.primary + 0x25a, struct.pack('<h', scalar))
    assert actual(m) == native(m)[0]


@pytest.mark.parametrize('fault', ['code', 'identity', 'owner', 'lifetime', 'operand'])
def test_stale_or_missing_sources_are_unavailable(fault):
    m = memory_fixture()
    kwargs = {}
    if fault == 'code':
        m.put(m.base + 0xe58e5c, b'\0')
    if fault == 'identity':
        m.identity(m.person, 3, 1001, 1002)
    if fault == 'owner':
        kwargs['expected_owner_identity'] = (1, 1, 1)
    if fault == 'lifetime':
        calls = []
        def current():
            calls.append(1)
            return ('save', len(calls))
        kwargs['check_current'] = current
    if fault == 'operand':
        m.blocked.append((m.base + 0x56d4951, m.base + 0x56d4951 + 1))
    with pytest.raises((ValueError, OSError)):
        actual(m, **kwargs)
