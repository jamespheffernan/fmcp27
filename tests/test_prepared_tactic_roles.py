"""Stored role-word behavior: exact phase filtering, native priority and safety."""
import struct

import pytest

from fm_live_mcp import prepared_tactic_roles as roles, world


@pytest.fixture
def role_memory():
    cells = {}
    base, creator = 0x100000000, 0x10000

    def put(address, raw):
        cells.update({address + index: byte for index, byte in enumerate(raw)})

    def read(address, size):
        return bytes(cells[address + index] for index in range(size))

    def word(value, phase='in_possession', index=0):
        offset = 0x120 if phase == 'in_possession' else 0x440
        put(creator + offset + index * 0x48 + 0x40, struct.pack('<Q', value))

    for rva, expected in roles.NATIVE_SPANS:
        put(base + rva, expected)
    for phase in ('in_possession', 'out_of_possession'):
        for index in range(11):
            word(0, phase, index)
    return dict(base=base, creator=creator, put=put, read=read, word=word)


def decode(m, value, phase='in_possession', index=0):
    m['word'](value, phase, index)
    return roles.decode(m['read'], m['creator'], phase, index)


@pytest.mark.parametrize('phase,word,name,key', [
    ('in_possession', 1, 'Goalkeeper', 688068),
    ('in_possession', 1 << 3, 'Wing-Back', 688080),
    ('out_of_possession', 1 << 3, 'Centre-Back', 688071),
    ('in_possession', 1 << 16, 'Box-To-Box Midfielder', 688121),
    ('in_possession', 1 << 24, 'Ball-Playing Centre-Back', 688116),
    ('out_of_possession', 1 << 11, 'Holding Full-Back', 688078),
    ('out_of_possession', 1 << 36, 'Tracking Wide Midfielder', 688092),
    ('out_of_possession', 1 << 40, 'Inside Outlet Winger', 696138),
    ('in_possession', 1 << 45, 'Wide Forward', 696156),
    ('in_possession', 1 << 57, 'Midfield Playmaker', 688146),
])
def test_native_names_phase_namespace_and_high_unsigned_bits(role_memory, phase, word, name, key):
    result = decode(role_memory, word, phase, 10)
    assert result == {
        'raw_encoding': f'0x{word:016x}', 'compiled_english_name': name,
        'native_resource_key': key, 'name_state': 'named'}


@pytest.mark.parametrize('phase,word,expected', [
    ('in_possession', (1 << 52) | (1 << 3), 'Inside Full-Back'),
    ('in_possession', (1 << 27) | (1 << 9), 'Inside Forward'),
    ('in_possession', (1 << 53) | (1 << 14), 'No-Nonsense Goalkeeper'),
    ('out_of_possession', (1 << 2) | (1 << 1), 'Line-Holding Goalkeeper'),
    ('out_of_possession', (1 << 5) | (1 << 4), 'Covering Centre-Back'),
    ('out_of_possession', (1 << 40) | (1 << 38), 'Inside Outlet Winger'),
])
def test_role_priority_is_native_order_not_lowest_bit(role_memory, phase, word, expected):
    assert decode(role_memory, word, phase)['compiled_english_name'] == expected


# These have compiled renderer branches but the prepared caller excludes them.
@pytest.mark.parametrize('phase,bit', [
    ('in_possession', 28), ('in_possession', 47), ('in_possession', 50),
    ('in_possession', 20), ('in_possession', 30), ('in_possession', 33),
    ('in_possession', 39), ('in_possession', 36), ('in_possession', 37),
    ('in_possession', 42),
    ('out_of_possession', 46), ('out_of_possession', 52),
])
def test_phase_filtered_bits_never_acquire_a_guessed_role(role_memory, phase, bit):
    result = decode(role_memory, 1 << bit, phase)
    assert result['compiled_english_name'] is None
    assert result['native_resource_key'] is None
    assert result['name_state'] == 'no_matching_native_branch'
    assert result['raw_encoding'] == f'0x{1 << bit:016x}'


@pytest.mark.parametrize('phase', ['in_possession', 'out_of_possession'])
@pytest.mark.parametrize('value', [0, 1 << 58, 1 << 63, (1 << 63) | (1 << 62), 0xE000000000000000])
def test_unknown_and_zero_words_preserve_unsigned_precision(role_memory, phase, value):
    result = decode(role_memory, value, phase)
    assert result['raw_encoding'] == f'0x{value:016x}'
    assert result['compiled_english_name'] is None
    assert set(result) == ROLE_KEYS


# The internal flag bits of the stored role word (roles.DUTY_BRANCHES). They are fixed by the
# role and are returned only inside raw_encoding: no key, name or state is published for them.
ROLE_KEYS = {'raw_encoding', 'compiled_english_name', 'native_resource_key', 'name_state'}
FLAG_BITS = [bit for bit, _key, _text in roles.DUTY_BRANCHES]


@pytest.mark.parametrize('flags', range(64))
@pytest.mark.parametrize('phase', ['in_possession', 'out_of_possession'])
def test_internal_flag_bits_never_name_anything_and_stay_in_the_stored_word(role_memory, flags, phase):
    assert FLAG_BITS == [21, 25, 26, 22, 23, 34]
    word = sum(1 << bit for index, bit in enumerate(FLAG_BITS) if flags & (1 << index))
    result = decode(role_memory, word, phase)
    assert result == {'raw_encoding': f'0x{word:016x}', 'compiled_english_name': None,
                      'native_resource_key': None, 'name_state': 'no_matching_native_branch'}
    with_role = decode(role_memory, word | 1 | (1 << 63), phase)
    assert with_role == {'raw_encoding': f'0x{word | 1 | (1 << 63):016x}', 'compiled_english_name': 'Goalkeeper',
                         'native_resource_key': 688068, 'name_state': 'named'}


def test_full_unsigned_word_priority_and_fixed_hex_format(role_memory):
    result = decode(role_memory, (1 << 64) - 1)
    assert result['raw_encoding'] == '0xffffffffffffffff'
    assert result['compiled_english_name'] == 'Goalkeeper'
    assert set(result) == ROLE_KEYS


def test_exact_phase_index_stride_and_read_size(role_memory):
    m = role_memory
    for phase, offset in [('in_possession', 0x120), ('out_of_possession', 0x440)]:
        for index in range(11):
            m['word']((1 << 63) | (1 << 34), phase, index)
            calls = []

            def read(address, size):
                calls.append((address, size))
                return m['read'](address, size)

            assert roles.decode(read, m['creator'], phase, index)['raw_encoding'] == '0x8000000400000000'
            assert calls == [(m['creator'] + offset + index * 0x48 + 0x40, 8)]


@pytest.mark.parametrize('creator', [None, True, False, 0, 4095, 4097, 1 << 64, (1 << 64) - 8])
def test_invalid_creator_rejects_without_read(role_memory, creator):
    with pytest.raises(ValueError, match='address'):
        roles.decode(lambda *_: pytest.fail('unexpected read'), creator, 'in_possession', 0)


@pytest.mark.parametrize('phase', [None, True, 0, [], {}, '', 'IP', 'out_of_possession '])
def test_invalid_phase_rejects_without_read(role_memory, phase):
    with pytest.raises(ValueError, match='phase'):
        roles.decode(lambda *_: pytest.fail('unexpected read'), role_memory['creator'], phase, 0)


@pytest.mark.parametrize('index', [None, True, False, -1, 11, 256, 1.0, '1'])
def test_invalid_index_rejects_without_read(role_memory, index):
    with pytest.raises(ValueError, match='index'):
        roles.decode(lambda *_: pytest.fail('unexpected read'), role_memory['creator'], 'in_possession', index)


@pytest.mark.parametrize('length', [0, 1, 7, 9])
def test_incomplete_role_read_rejects(role_memory, length):
    with pytest.raises(ValueError, match='Incomplete'):
        roles.decode(lambda *_: bytes(length), role_memory['creator'], 'in_possession', 0)


def test_readset_detects_role_mutation_before_publication(role_memory):
    m = role_memory
    m['word'](1)
    snapshot = world.ReadSet(m['read'])
    assert roles.decode(snapshot, m['creator'], 'in_possession', 0)['compiled_english_name'] == 'Goalkeeper'
    m['word'](8)
    with pytest.raises(ValueError):
        snapshot.verify()


def test_native_guards_pass_and_are_readset_tracked(role_memory):
    m = role_memory
    snapshot = world.ReadSet(m['read'])
    assert roles.verify_native(snapshot, m['base']) is None
    snapshot.verify()
    rva, raw = roles.NATIVE_SPANS[0]
    m['put'](m['base'] + rva, bytes([raw[0] ^ 1]))
    with pytest.raises(ValueError):
        snapshot.verify()


@pytest.mark.parametrize('guard_index', range(len(roles.NATIVE_SPANS)))
def test_every_native_guard_rejects_changed_instruction(role_memory, guard_index):
    m = role_memory
    rva, raw = roles.NATIVE_SPANS[guard_index]
    m['put'](m['base'] + rva + len(raw) - 1, bytes([raw[-1] ^ 1]))
    with pytest.raises(ValueError, match='native layout changed'):
        roles.verify_native(m['read'], m['base'])


@pytest.mark.parametrize('base', [None, True, 0, 4095, 4097, (1 << 64) - 8])
def test_invalid_native_base_rejects_without_read(base):
    with pytest.raises(ValueError, match='address'):
        roles.verify_native(lambda *_: pytest.fail('unexpected read'), base)


def test_truncated_native_guard_rejects(role_memory):
    with pytest.raises(ValueError, match='Incomplete'):
        roles.verify_native(lambda *_: b'', role_memory['base'])
