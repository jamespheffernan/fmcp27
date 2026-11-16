"""Synthetic typed compact records with canonical membership; no live warm claim."""
import struct

import pytest

from fm_live_mcp import database, teams, virtual, virtual_identity, world
from test_database import database_memory
from test_players import memory
from test_virtual import virtual_memory
from test_world import world_memory


@pytest.fixture
def compact_virtual_memory(virtual_memory, database_memory):
    """Real typed/canonical cells, default cold, with a synthetic cached warm control.

    Exports the world/database/virtual fixture helpers, compact/person_index,
    compact_person, selected_team_index and warm_cache_address. Tests may alter
    the signed compact cache index to select the existing synthetic warm object.
    """
    m = virtual_memory
    assert m is database_memory
    for rva, expected in virtual_identity.NATIVE_SPANS:
        m['put'](m['base'] + rva, expected)
    m['q'](m['base'] + virtual_identity.PERSON_RVA + 2*8, m['base'] + 0x1475750)
    m['q'](m['base'] + world.TYPES['virtual_player'][0] + 29*8, m['base'] + 0x18A4A9C)
    compact, regular = m['compact'], m['regular']
    m['put'](compact + 0x28, struct.pack('<III', 1, 12345, 12345))
    m['put'](compact + 0x14, struct.pack('<h', -1))
    m['put'](compact + 8, struct.pack('<i', 0))
    # database_memory resets the original test record; restore its cache markers.
    m['put'](0x1390, struct.pack('<III', 0xFFFFFFFF, 12345, 0))
    m['q'](0x1128, m['team'])
    m['vec'](m['headers']['people'], [regular + 0x388, compact + 0x20])
    m['put'](regular + 0x390, struct.pack('<I', 0))
    m['put'](m['team'] + 8, struct.pack('<III', 0, 1478, 1478))
    m['put'](m['club'] + 8, struct.pack('<III', 0, 688, 688))
    m['vec'](m['headers']['teams'], [m['team']])
    m['vec'](m['roots']['teams'] + 0x68, [m['team']])
    m['put'](m['base'] + teams.LOOKUP_MODE, b'\x01')
    for kind, getter in teams.GETTERS.items():
        m['q'](m['base'] + world.TYPES[kind][0] + 3*8, m['base'] + getter)
    m['vec'](m['team'] + 0x38, [regular, compact])
    m.update(compact_person=compact + 0x20, person_index=1,
             selected_team_index=0, warm_cache_address=0x1000)
    return m


def test_cold_stored_identity_with_real_canonical_membership(compact_virtual_memory):
    m = compact_virtual_memory
    result = virtual_identity.inspect(m['read'], m['compact'], m['tables'])
    assert result['identity'] == ('stored_virtual_identity_v1', 1, 12345, 12345)
    assert result['native_identity'] == {'database_index': 1, 'native_id': 12345, 'random_id': None}
    assert result['stored_team_index'] == 0 and result['cache_index'] == -1
    assert result['_raw'] == m['read'](m['compact'], 64)
    assert set(result) == {'identity', 'native_identity', 'stored_team_index', 'cache_index', '_raw'}


@pytest.mark.parametrize('secondary,public', [(12345, None), (0, 0), (54321, 54321),
                                             (0xFFFFFFFF, 0xFFFFFFFF)])
def test_independent_secondary_identity_is_never_collapsed_except_equal_words(
        compact_virtual_memory, secondary, public):
    m = compact_virtual_memory
    m['put'](m['compact'] + 0x30, struct.pack('<I', secondary))
    result = virtual_identity.inspect(m['read'], m['compact'], m['tables'])
    assert result['native_identity']['random_id'] == public
    assert result['identity'] == (virtual_identity.BINDING_KIND, 1, 12345, secondary)


@pytest.mark.parametrize('cache_index', [-32768, -2, -1, 0, 4095, 32767])
def test_cache_index_is_signed_availability_only_without_cache_validation(
        compact_virtual_memory, cache_index):
    m = compact_virtual_memory
    m['put'](m['compact'] + 0x14, struct.pack('<h', cache_index))
    result = virtual_identity.inspect(m['read'], m['compact'], m['tables'])
    assert result['cache_index'] == cache_index
    assert result['identity'] == (virtual_identity.BINDING_KIND, 1, 12345, 12345)


@pytest.mark.parametrize('team_index', [-2147483648, -1, 0, 1155, 2147483647])
def test_stored_team_index_remains_private_signed_raw_for_the_roster_caller(
        compact_virtual_memory, team_index):
    m = compact_virtual_memory
    m['put'](m['compact'] + 8, struct.pack('<i', team_index))
    result = virtual_identity.inspect(m['read'], m['compact'], m['tables'])
    assert result['stored_team_index'] == team_index
    assert result['identity'] == (virtual_identity.BINDING_KIND, 1, 12345, 12345)


def test_inspection_never_reads_virtual_manager_or_generated_profile(compact_virtual_memory):
    m = compact_virtual_memory
    reads = []
    def read(address, size):
        assert not (address <= m['base'] + virtual.MANAGER_ROOT < address + size)
        assert not (address < m['warm_cache_address'] + 0x3A8 and
                    address + size > m['warm_cache_address'])
        assert not (address < m['cache_manager'] + 0x2A8 and
                    address + size > m['cache_manager'])
        reads.append((address, size))
        return m['read'](address, size)
    for index in (-1, 0, 32767):
        m['put'](m['compact'] + 0x14, struct.pack('<h', index))
        assert virtual_identity.inspect(read, m['compact'], m['tables'])['cache_index'] == index
    assert reads


def test_rtti_name_may_be_unaligned(compact_virtual_memory):
    m = compact_virtual_memory
    info = int.from_bytes(m['read'](m['base'] + virtual_identity.PERSON_RVA - 8, 8), 'little')
    name = b'N2db14VIRTUAL_PLAYERE\0'
    unaligned = m['allocate'](len(name) + 1) + 1
    m['put'](unaligned, name)
    m['q'](info + 8, unaligned)
    assert virtual_identity.inspect(m['read'], m['compact'], m['tables'])['native_identity']['native_id'] == 12345


@pytest.mark.parametrize('fault', [
    'primary_type', 'primary_displacement', 'primary_rtti', 'person_type',
    'person_displacement', 'person_info', 'person_rtti', 'person_name_pointer',
    'person_setter', 'team_getter', 'primary_zero', 'index_outside',
    'canonical_member', 'people_type', 'people_rtti', 'people_bounds',
])
def test_malformed_types_identity_and_canonical_membership_fail_closed(compact_virtual_memory, fault):
    m = compact_virtual_memory
    primary_table = m['base'] + world.TYPES['virtual_player'][0]
    person_table = m['base'] + virtual_identity.PERSON_RVA
    if fault == 'primary_type': m['q'](m['compact'], m['tables'][0])
    elif fault == 'primary_displacement': m['q'](primary_table - 16, 8)
    elif fault == 'primary_rtti':
        info = int.from_bytes(m['read'](primary_table - 8, 8), 'little')
        name = m['allocate'](32)
        m['put'](name, b'Wrong type\0')
        m['q'](info + 8, name)
    elif fault == 'person_type': m['q'](m['compact'] + 0x20, m['tables'][2])
    elif fault == 'person_displacement': m['put'](person_table - 16, struct.pack('<q', -16))
    elif fault == 'person_info': m['q'](person_table - 8, 0)
    elif fault == 'person_rtti':
        info = int.from_bytes(m['read'](person_table - 8, 8), 'little')
        name = m['allocate'](32)
        m['put'](name, b'N2db13ACTUAL_PLAYERE\0')
        m['q'](info + 8, name)
    elif fault == 'person_name_pointer':
        info = int.from_bytes(m['read'](person_table - 8, 8), 'little')
        m['q'](info + 8, 0)
    elif fault == 'person_setter': m['q'](person_table + 2*8, 0)
    elif fault == 'team_getter': m['q'](primary_table + 29*8, 0)
    elif fault == 'primary_zero': m['put'](m['compact'] + 0x2C, bytes(4))
    elif fault == 'index_outside': m['put'](m['compact'] + 0x28, struct.pack('<I', 2))
    elif fault == 'canonical_member': m['vec'](m['headers']['people'], [m['regular'] + 0x388, m['manager']])
    elif fault == 'people_type': m['q'](m['roots']['people'], 0)
    elif fault == 'people_rtti': m['q'](m['base'] + database.TABLES['people'][1] - 16, 8)
    else: m['put'](m['headers']['people'], struct.pack('<QQQ', 4096, 4095, 8192))
    with pytest.raises(ValueError):
        virtual_identity.inspect(m['read'], m['compact'], m['tables'])


@pytest.mark.parametrize('index', range(len(virtual_identity.NATIVE_SPANS)))
def test_every_accepted_native_span_mismatch_fails(compact_virtual_memory, index):
    m = compact_virtual_memory
    rva, expected = virtual_identity.NATIVE_SPANS[index]
    m['put'](m['base'] + rva, bytes([expected[0] ^ 1]) + expected[1:])
    with pytest.raises(ValueError, match='native layout changed'):
        virtual_identity.inspect(m['read'], m['compact'], m['tables'])


@pytest.mark.parametrize('offset,replacement', [(0x14, struct.pack('<h', 0)),
                                               (0x28, struct.pack('<I', 0)),
                                               (0x2C, struct.pack('<I', 999)),
                                               (0x30, struct.pack('<I', 888))])
def test_mid_inspection_source_transition_is_drift(compact_virtual_memory, offset, replacement):
    m = compact_virtual_memory
    count = 0
    def read(address, size):
        nonlocal count
        if address == m['compact'] and size == 64:
            count += 1
            if count == 2:
                m['put'](m['compact'] + offset, replacement)
        return m['read'](address, size)
    with pytest.raises(ValueError, match='changed during identity inspection'):
        virtual_identity.inspect(read, m['compact'], m['tables'])


def test_readset_rechecks_canonical_membership_after_inspection(compact_virtual_memory):
    m = compact_virtual_memory
    snapshot = world.ReadSet(m['read'])
    virtual_identity.inspect(snapshot, m['compact'], m['tables'])
    m['vec'](m['headers']['people'], [m['regular'] + 0x388])
    with pytest.raises(ValueError, match='changed during read'):
        snapshot.verify()


@pytest.mark.parametrize('address', [None, True, 0, 4095, 4097, 4096.0])
def test_invalid_address_rejects_before_reads(compact_virtual_memory, address):
    with pytest.raises(ValueError, match='address'):
        virtual_identity.inspect(lambda *args: pytest.fail('Unexpected read'), address,
                                 compact_virtual_memory['tables'])


@pytest.mark.parametrize('tables', [None, (), (1, 2), [1, 2, 3], (True, 2, 3), (1, 2, 3)])
def test_invalid_layout_rejects_before_reads(compact_virtual_memory, tables):
    with pytest.raises(ValueError, match='layout'):
        virtual_identity.inspect(lambda *args: pytest.fail('Unexpected read'),
                                 compact_virtual_memory['compact'], tables)


def test_incomplete_compact_bytes_fail(compact_virtual_memory):
    m = compact_virtual_memory
    def read(address, size):
        data = m['read'](address, size)
        return data[:-1] if address == m['compact'] and size == 64 else data
    with pytest.raises(ValueError, match='type changed'):
        virtual_identity.inspect(read, m['compact'], m['tables'])
