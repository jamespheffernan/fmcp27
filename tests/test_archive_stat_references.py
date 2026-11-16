import struct

import pytest

from fm_live_mcp import archive_stat_references as refs, teams, world
from test_database import database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory


def prefix(team=0, competition=0, *, extended=False, tag=0):
    raw = bytes([tag]) + struct.pack('<ih', team, -2 if extended else competition)
    if extended:
        raw += struct.pack('<i', competition)
    return raw


def test_prefix_table_indices_are_not_permanent_ids():
    value = refs.decode_prefix(prefix(123, 456) + bytes(161))
    assert value == {'consumed_bytes': 7,
                     'team_reference': {'tag': 0, 'index': 123, 'state': 'table_index'},
                     'competition_reference': {'marker': 456, 'extended': False, 'index': 456, 'state': 'table_index'}}


def test_null_references_consume_normal_width():
    value = refs.decode_prefix(prefix(-1, -1))
    assert value['consumed_bytes'] == 7
    assert value['team_reference']['index'] is None
    assert value['competition_reference']['index'] is None
    def no_read(*args):
        raise AssertionError('Null references must not read native tables')
    assert refs.resolve(no_read, 0, value) == {'team': None, 'competition': None,
                                             '_bindings': {'team': None, 'competition': None}}


@pytest.mark.parametrize('index', [0, 32767, 32768, 0x7fffffff])
def test_extended_competition_index_has_variable_transport_width(index):
    value = refs.decode_prefix(prefix(9, index, extended=True) + bytes(161))
    assert value['consumed_bytes'] == 11
    assert value['competition_reference'] == {'marker': -2, 'extended': True,
                                              'index': index, 'state': 'table_index'}
    assert len(prefix(9, index, extended=True) + bytes(161)) == 172


@pytest.mark.parametrize('raw', [None, bytearray(7), b'', bytes(6), prefix(0, 2, extended=True)[:10],
                               prefix(-2, 0), prefix(-2147483648, 0), prefix(0, -3), prefix(0, -32768),
                               prefix(0, -1, extended=True), prefix(0, -2, extended=True)])
def test_malformed_or_negative_transport_fails(raw):
    with pytest.raises(ValueError):
        refs.decode_prefix(raw)


@pytest.mark.parametrize('tag', [1, 2, 3, 255])
def test_other_team_tags_fail_explicitly_even_with_null_index(tag):
    with pytest.raises(ValueError, match='Unsupported.*tag'):
        refs.decode_prefix(prefix(-1, -1, tag=tag))


def test_resolve_preserves_independent_ids_and_private_bindings(team_memory):
    m = team_memory
    competition = m['competitions'][1]
    m['put'](competition + 8, struct.pack('<III', 1, 101, 903))
    row = refs.resolve(m['read'], m['base'], refs.decode_prefix(prefix(1, 1)))
    assert row['team']['database_index'] == 1
    assert (row['team']['native_id'], row['team']['random_id']) == (51, 901)
    assert row['competition']['name'] == 'Test Continental Cup'
    assert (row['competition']['native_id'], row['competition']['random_id']) == (101, 903)
    assert row['_bindings']['team']['address'] == m['team_addresses'][1]
    assert row['_bindings']['competition'] == {
        'address': competition, 'identity': struct.pack('<III', 1, 101, 903),
        'database_index': 1, 'native_id': 101, 'random_id': 903, 'kind': 'competition'}
    assert 'address' not in row['team'] and 'address' not in row['competition']


def test_zero_secondary_id_is_preserved_when_primary_differs(team_memory):
    m = team_memory
    m['put'](m['competitions'][0] + 8, struct.pack('<III', 0, 100, 0))
    m['put'](m['team_addresses'][0] + 8, struct.pack('<III', 0, 50, 0))
    row = refs.resolve(m['read'], m['base'], refs.decode_prefix(prefix()))
    assert row['team']['random_id'] == 0
    assert row['competition']['random_id'] == 0


@pytest.mark.parametrize('team,competition', [(-1, 0), (0, -1)])
def test_one_null_link_does_not_discard_the_other(team_memory, team, competition):
    m = team_memory
    row = refs.resolve(m['read'], m['base'], refs.decode_prefix(prefix(team, competition)))
    assert (row['team'] is None) == (team == -1)
    assert (row['competition'] is None) == (competition == -1)


@pytest.mark.parametrize('fault', ['team_membership', 'competition_membership', 'team_index', 'competition_index',
                                  'team_id', 'competition_id', 'team_primary', 'competition_primary'])
def test_wrong_canonical_membership_or_identity_fails(team_memory, fault):
    m = team_memory
    if fault == 'team_membership':
        m['vec'](m['headers']['teams'], list(reversed(m['team_addresses'])))
    elif fault == 'competition_membership':
        m['vec'](m['headers']['competitions'], list(reversed(m['competitions'])))
    elif fault == 'team_index':
        m['put'](m['team_addresses'][0] + 8, struct.pack('<I', 7))
    elif fault == 'competition_index':
        m['put'](m['competitions'][0] + 8, struct.pack('<I', 7))
    elif fault == 'team_id':
        m['put'](m['team_addresses'][0] + 12, bytes(4))
    elif fault == 'competition_id':
        m['put'](m['competitions'][0] + 12, bytes(4))
    else:
        m['put'](m['base'] + teams.LOOKUP_MODE, b'\0')
        m['vec'](m['roots']['teams'] + 0x68, m['team_addresses'])
        m['vec'](m['roots']['competitions'] + 0x68, m['competitions'])
        kind = 'teams' if fault == 'team_primary' else 'competitions'
        values = m['team_addresses'] if kind == 'teams' else m['competitions']
        m['vec'](m['roots'][kind] + 0x68, list(reversed(values)))
    with pytest.raises(ValueError):
        refs.resolve(m['read'], m['base'], refs.decode_prefix(prefix()))


@pytest.mark.parametrize('kind', ['teams', 'competitions'])
def test_consumed_membership_mutation_fails_final_readset_check(team_memory, kind):
    m = team_memory
    snapshot = world.ReadSet(m['read'])
    refs.resolve(snapshot, m['base'], refs.decode_prefix(prefix()))
    values = m['team_addresses'] if kind == 'teams' else m['competitions']
    m['vec'](m['headers'][kind], list(reversed(values)))
    with pytest.raises(ValueError, match='changed'):
        snapshot.verify()


def test_identity_mutation_during_linking_fails(team_memory):
    m = team_memory
    address = m['competitions'][0] + 8
    count = 0
    def changing(where, size):
        nonlocal count
        if where == address and size == 12:
            count += 1
            if count == 2:
                m['put'](address, struct.pack('<III', 0, 777, 999))
        return m['read'](where, size)
    with pytest.raises(ValueError, match='identity changed'):
        refs.resolve(changing, m['base'], refs.decode_prefix(prefix()))


def test_multiple_team_history_rows_preserve_membership_and_order(team_memory):
    m = team_memory
    rows = [refs.resolve(m['read'], m['base'], refs.decode_prefix(prefix(team, comp)))
            for team, comp in [(2, 0), (0, 1), (2, 1)]]
    assert [row['team']['database_index'] for row in rows] == [2, 0, 2]
    assert [row['team']['owner']['name'] for row in rows] == ['League', 'Test United', 'League']
    assert [row['competition']['native_id'] for row in rows] == [100, 101, 101]


@pytest.mark.parametrize('mutation', ['bool_length', 'unsupported_tag', 'bool_index', 'bad_state',
                                      'marker_disagreement', 'extended_null', 'missing_reference', 'missing_index'])
def test_malformed_prefix_dictionaries_fail(team_memory, mutation):
    value = refs.decode_prefix(prefix())
    if mutation == 'bool_length': value['consumed_bytes'] = True
    elif mutation == 'unsupported_tag': value['team_reference']['tag'] = 2
    elif mutation == 'bool_index': value['team_reference']['index'] = True
    elif mutation == 'bad_state': value['team_reference']['state'] = 'null'
    elif mutation == 'marker_disagreement': value['competition_reference']['marker'] = 1
    elif mutation == 'extended_null':
        value = refs.decode_prefix(prefix(0, 2, extended=True))
        value['competition_reference'].update(index=None, state='null')
    elif mutation == 'missing_index': del value['team_reference']['index']
    else: del value['competition_reference']
    with pytest.raises(ValueError):
        refs.resolve(team_memory['read'], team_memory['base'], value)


def test_native_transport_and_encoding_guards(team_memory):
    m = team_memory
    for rva, data in refs.NATIVE_SPANS.items():
        m['put'](m['base'] + rva, bytes.fromhex(data))
    m['put'](m['base'] + refs.REFERENCE_MODE, b'\0')
    m['put'](m['base'] + refs.REFERENCE_SWITCHES, b'\0\0')
    refs.verify_native(m['read'], m['base'])
    for rva, raw in refs.NATIVE_SPANS.items():
        data = bytes.fromhex(raw)
        m['put'](m['base'] + rva, bytes([data[0] ^ 1]) + data[1:])
        with pytest.raises(ValueError, match='transport changed'):
            refs.verify_native(m['read'], m['base'])
        m['put'](m['base'] + rva, data)
    for rva, size in [(refs.REFERENCE_MODE, 1), (refs.REFERENCE_SWITCHES, 2)]:
        m['put'](m['base'] + rva, b'\1' * size)
        with pytest.raises(ValueError, match='Unsupported.*encoding'):
            refs.verify_native(m['read'], m['base'])
        m['put'](m['base'] + rva, bytes(size))
