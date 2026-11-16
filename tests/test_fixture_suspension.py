"""Real passive field composition, sparse native bytes and no verdict inflation."""
import json
import struct

import pytest

from fm_live_mcp import fixture_suspension as source, fixtures, players, world


@pytest.fixture
def suspension_memory():
    cells, reads = {}, []
    base, primary, secondary, manager, fixture = 0x100000000, 0x1000, 0x2000, 0x3000, 0x5000

    def put(at, raw):
        cells.update((at + i, b) for i, b in enumerate(raw))

    def q(at, value):
        put(at, struct.pack('<Q', value))

    def read(at, size):
        reads.append((at, size))
        try:
            return bytes(cells[at + i] for i in range(size))
        except KeyError as exc:
            raise ValueError('Unreadable synthetic address') from exc

    def type_fixture(kind):
        vt, name = fixtures.TYPES[kind]
        q(fixture, base + vt)
        put(base + vt - 16, struct.pack('<qQ', 0, 0x6000))
        q(0x6008, 0x7001)
        put(0x7001, name + b'\0')
        q(base + vt + 0x108, base + (0x3D030D8 if kind == 'fixture' else 0x3CF9584))

    for rva, raw in source.NATIVE_SPANS:
        put(base + rva, raw)
    q(primary, base + players.RVA[0])
    q(primary + 0xF0, secondary)
    q(base + source.MANAGER_ROOT, manager)
    q(manager, base + source.MANAGER_VTABLE)
    for slot, target in ((0x230, 0x1F8AF7C), (0x260, 0x1F8DB6C)):
        q(base + source.MANAGER_VTABLE + slot, base + target)
    put(secondary + 0x18, bytes(24))
    type_fixture('fixture')
    return dict(base=base, primary=primary, secondary=secondary, manager=manager,
                fixture=fixture, put=put, q=q, read=read, reads=reads, type_fixture=type_fixture)


def check(m, **kwargs):
    return source.check(m['read'], m['base'], m['primary'], 'actual',
                        fixture_address=m['fixture'], manager_address=m['manager'], **kwargs)


def test_exact_live_picked20_and_cal_empty_shape(suspension_memory):
    m = suspension_memory
    source.verify_native(m['read'], m['base'])
    row = check(m)
    assert row == {
        'state': 'ruled_out', 'reason': 'no_stored_personal_bans',
        'evidence_scope': 'native_ordinary_suspension_check_empty_source',
        'applies': False, 'personal_ban_source_state': 'present_empty',
        'physical_record_count': 0, 'overall_eligibility': 'not_assessed',
    }
    assert '0x' not in json.dumps(row) and 'address' not in json.dumps(row)
    # Global queue, TEAM sources, source records and all dates were unpopulated.
    assert all(n <= max(len(raw) for _, raw in source.NATIVE_SPANS) for _, n in m['reads'])


def test_absent_secondary_distinct_from_empty_count(suspension_memory):
    m = suspension_memory
    m['q'](m['primary'] + 0xF0, 0)
    row = check(m)
    assert row['state'] == 'ruled_out' and row['applies'] is False
    assert row['personal_ban_source_state'] == 'secondary_absent'
    assert row['physical_record_count'] is None
    assert (m['secondary'] + 0x18, 24) not in m['reads']


@pytest.mark.parametrize('capacity', [0x8000, 0x1000000])
def test_allocated_empty_ignores_unused_capacity(suspension_memory, capacity):
    m = suspension_memory
    m['put'](m['secondary'] + 0x18, struct.pack('<QQQ', 0x8000, 0x8000, capacity))
    assert check(m)['state'] == 'ruled_out'
    assert not any(at == 0x8000 for at, _ in m['reads'])


@pytest.mark.parametrize('count', [1, 2, 64, 100000])
def test_nonempty_never_means_suspended_or_clear_and_reads_no_record(suspension_memory, count):
    m = suspension_memory
    end = 0x8000 + count * 8
    m['put'](m['secondary'] + 0x18, struct.pack('<QQQ', 0x8000, end, end))
    row = check(m)
    assert row['state'] == 'unavailable' and row['applies'] is None
    assert row['reason'] == 'nonempty_personal_ban_applicability_unsupported'
    assert row['physical_record_count'] == count
    assert not any(at == 0x8000 for at, _ in m['reads'])


def test_result_record_does_not_skip_global_queue_on_empty_personal_source(suspension_memory):
    m = suspension_memory
    m['type_fixture']('result')
    row = check(m)
    assert row['state'] == 'unavailable' and row['applies'] is None
    assert row['reason'] == 'unsupported_result_fixture_branch'
    assert (m['primary'] + 0xF0, 8) not in m['reads']
    assert (m['base'] + source.MANAGER_ROOT, 8) not in m['reads']


@pytest.mark.parametrize('kind', ['player_staff', 'virtual'])
def test_known_unsupported_players_require_no_memory(kind):
    result = source.check(lambda *_: pytest.fail('unsupported read'), None, None, kind,
                          fixture_address=None, manager_address=None)
    assert result['state'] == 'unavailable' and result['applies'] is None
    assert result['reason'] == 'unsupported_player_kind'


@pytest.mark.parametrize('kind', [None, '', 'staff', True, 1, [], {}])
def test_invalid_player_kind_rejects(kind):
    with pytest.raises(ValueError, match='kind'):
        source.check(lambda *_: pytest.fail('read'), 0, 0, kind,
                     fixture_address=0, manager_address=0)


def test_absent_manager_is_unavailable_not_empty(suspension_memory):
    m = suspension_memory
    m['q'](m['base'] + source.MANAGER_ROOT, 0)
    result = source.check(m['read'], m['base'], m['primary'], 'actual',
                          fixture_address=m['fixture'], manager_address=0)
    assert result['state'] == 'unavailable' and result['physical_record_count'] is None
    assert result['reason'] == 'native_eligibility_manager_absent'
    assert (m['primary'] + 0xF0, 8) not in m['reads']


@pytest.mark.parametrize('fault', ['root', 'manager_type', 'manager230', 'manager260',
                                  'player_type', 'fixture_type', 'fixture108', 'rtti', 'displacement'])
def test_wrong_context_fails_without_negative_result(suspension_memory, fault):
    m = suspension_memory
    at, value = {
        'root': (m['base'] + source.MANAGER_ROOT, 0x9000),
        'manager_type': (m['manager'], m['base'] + players.RVA[0]),
        'manager230': (m['base'] + source.MANAGER_VTABLE + 0x230, m['base'] + 0x1F8CFB0),
        'manager260': (m['base'] + source.MANAGER_VTABLE + 0x260, m['base'] + 0x1F8CFB0),
        'player_type': (m['primary'], m['base'] + players.STAFF_RVA[0]),
        'fixture_type': (m['fixture'], m['base'] + players.RVA[0]),
        'fixture108': (m['base'] + fixtures.TYPES['fixture'][0] + 0x108, m['base'] + 0x3CF9584),
        'rtti': (0x6008, 0x7002),
        'displacement': (m['base'] + fixtures.TYPES['fixture'][0] - 16, 8),
    }[fault]
    m['q'](at, value)
    with pytest.raises(ValueError): check(m)


@pytest.mark.parametrize('header', [(0, 0, 8), (0, 0x8000, 0x8000),
                                    (0x8008, 0x8000, 0x8010), (0x8000, 0x8010, 0x8008),
                                    (0x8000, 0x8001, 0x8008), (0x8000, 0x8000, 1 << 48)])
def test_malformed_vector_not_supported_absence(suspension_memory, header):
    m = suspension_memory
    m['put'](m['secondary'] + 0x18, struct.pack('<QQQ', *header))
    with pytest.raises(ValueError): check(m)


@pytest.mark.parametrize('pointer', [8, 0x2004, (1 << 48)])
def test_bad_secondary_pointer_rejects(suspension_memory, pointer):
    m = suspension_memory
    m['q'](m['primary'] + 0xF0, pointer)
    with pytest.raises(ValueError): check(m)


@pytest.mark.parametrize('pointer', [None, False, True, -1, 8, 0x3004])
def test_bad_manager_argument_rejects(suspension_memory, pointer):
    m = suspension_memory
    with pytest.raises(ValueError):
        source.check(m['read'], m['base'], m['primary'], 'actual',
                     fixture_address=m['fixture'], manager_address=pointer)


@pytest.mark.parametrize('rva,raw', source.NATIVE_SPANS)
def test_each_native_guard_rejects_drift(suspension_memory, rva, raw):
    m = suspension_memory
    m['put'](m['base'] + rva, bytes([raw[0] ^ 1]))
    with pytest.raises(ValueError, match='native branch'):
        source.verify_native(m['read'], m['base'])


@pytest.mark.parametrize('fault', ['root', 'manager230', 'fixture108', 'secondary', 'vector', 'native'])
def test_outer_readset_detects_late_changes(suspension_memory, fault):
    m = suspension_memory
    read = world.ReadSet(m['read'])
    source.verify_native(read, m['base'])
    row = source.check(read, m['base'], m['primary'], 'actual',
                       fixture_address=m['fixture'], manager_address=m['manager'])
    assert row['state'] == 'ruled_out'
    at = {
        'root': m['base'] + source.MANAGER_ROOT,
        'manager230': m['base'] + source.MANAGER_VTABLE + 0x230,
        'fixture108': m['base'] + fixtures.TYPES['fixture'][0] + 0x108,
        'secondary': m['primary'] + 0xF0,
        'vector': m['secondary'] + 0x18,
        'native': m['base'] + source.NATIVE_SPANS[0][0],
    }[fault]
    old = m['read'](at, 1)
    m['put'](at, bytes([old[0] ^ 1]))
    with pytest.raises(ValueError, match='changed'): read.verify()


def test_transport_failure_rejects_before_result(suspension_memory):
    m = suspension_memory
    def short_read(at, size):
        data = m['read'](at, size)
        return data[:-1] if at == m['secondary'] + 0x18 else data
    with pytest.raises(ValueError, match='Incomplete'):
        source.check(short_read, m['base'], m['primary'], 'actual',
                     fixture_address=m['fixture'], manager_address=m['manager'])
