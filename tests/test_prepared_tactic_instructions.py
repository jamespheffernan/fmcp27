"""Exact stored selection semantics; no native calls or live game access."""
import pytest

from fm_live_mcp import prepared_tactic_instructions as instructions, world
from prepared_tactic_instruction_fixture import add_instruction_context


@pytest.fixture
def instruction_memory():
    cells = {}
    def put(address, raw):
        cells.update({address + index: value for index, value in enumerate(raw)})
    def read(address, size):
        return bytes(cells[address + index] for index in range(size))
    m = {'base': 0x100000000, 'creator_addresses': (0x10000, 0x20000, 0x30000),
         'put': put, 'read': read}
    return add_instruction_context(m)


def decode(m, index=0, read=None):
    return instructions.decode(read or m['read'], m['creator_addresses'][index])


def test_independent_three_owned_raw_selections(instruction_memory):
    m = instruction_memory
    read = world.ReadSet(m['read'])
    instructions.verify_native(read, m['base'])
    expected = [(3, 'Cautious', 12), (5, 'Positive', 14), (6, 'Attacking', 14)]
    for index, (code, name, count) in enumerate(expected):
        result = decode(m, index, read)
        assert result['mentality'] == {'native_code': code, 'name': name, 'state': 'named'}
        selected = result['team_instructions']
        assert selected['scope'] == 'shared_stored_options'
        assert selected['selected_count'] == count
        assert [row['native_option_id'] for row in selected['selected_options']] == list(m['instruction_samples'][index][1])
        assert selected['unmapped_serialized_bits'] == []
        assert all(row['state'] == 'named' for row in selected['selected_options'])
    assert decode(m, 0)['team_instructions']['selected_options'][:2] == [
        {'native_option_id': 2, 'name': 'More Direct Passing', 'state': 'named'},
        {'native_option_id': 5, 'name': 'Pass Into Space', 'state': 'named'}]
    assert decode(m, 1)['team_instructions']['selected_options'][6] == {
        'native_option_id': 46, 'name': 'Much Higher Tempo', 'state': 'named'}
    read.verify()


@pytest.mark.parametrize('code,name', [(1, 'Very Defensive'), (2, 'Defensive'), (3, 'Cautious'),
    (4, 'Balanced'), (5, 'Positive'), (6, 'Attacking'), (7, 'Very Attacking')])
def test_signed_mentality_named_domain(instruction_memory, code, name):
    m = instruction_memory
    m['set_instruction_details'](m['creator_addresses'][0], code)
    assert decode(m)['mentality'] == {'native_code': code, 'name': name, 'state': 'named'}


@pytest.mark.parametrize('code', [-128, -1, 0, 8, 127])
def test_unknown_signed_mentality_retained_without_default(instruction_memory, code):
    m = instruction_memory
    m['set_instruction_details'](m['creator_addresses'][0], code)
    assert decode(m)['mentality'] == {'native_code': code, 'name': None, 'state': 'unmapped_native_code'}


def test_bit_boundaries_no_text_and_outside_domain(instruction_memory):
    m = instruction_memory
    m['set_instruction_details'](m['creator_addresses'][0], 5, [0, 1, 63, 64, 65, 74, 75, 83, 84, 87, 127])
    selected = decode(m)['team_instructions']
    assert selected['unmapped_serialized_bits'] == [0]
    assert selected['selected_count'] == 7
    assert selected['selected_options'] == [
        {'native_option_id': 1, 'name': 'Much More Direct Passing', 'state': 'named'},
        {'native_option_id': 63, 'name': 'Low Block', 'state': 'named'},
        {'native_option_id': 64, 'name': None, 'state': 'no_native_label'},
        {'native_option_id': 65, 'name': 'Trigger Press Much More Often', 'state': 'named'},
        {'native_option_id': 74, 'name': None, 'state': 'no_native_label'},
        {'native_option_id': 75, 'name': None, 'state': 'no_native_label'},
        {'native_option_id': 83, 'name': 'Invite Crosses', 'state': 'named'},
    ]


def test_empty_options_and_logical_bit0_are_distinct(instruction_memory):
    m = instruction_memory
    for bits, opaque in [((), []), ((0,), [0]), ((84, 127), [])]:
        m['set_instruction_details'](m['creator_addresses'][0], option_ids=bits)
        assert decode(m)['team_instructions'] == {'scope': 'shared_stored_options',
            'selected_count': 0, 'selected_options': [], 'unmapped_serialized_bits': opaque}


def test_all83_options_in_native_order_and_conflicts_preserved(instruction_memory):
    m = instruction_memory
    m['set_instruction_details'](m['creator_addresses'][0], option_ids=range(1, 84))
    selected = decode(m)['team_instructions']
    assert selected['selected_count'] == 83
    assert [row['native_option_id'] for row in selected['selected_options']] == list(range(1, 84))
    assert sum(row['state'] == 'named' for row in selected['selected_options']) == 80
    assert [row['native_option_id'] for row in selected['selected_options'] if row['name'] is None] == [64, 74, 75]
    assert [row['name'] for row in selected['selected_options'][:4]] == [
        'Much More Direct Passing', 'More Direct Passing', 'Shorter Passing', 'Much Shorter Passing']
    assert set(decode(m)) == {'mentality', 'team_instructions'}


@pytest.mark.parametrize('address', [None, True, 0, 4095, 4097, -8, 1 << 64, (1 << 64) - 8])
def test_invalid_creator_address_rejects_before_read(address):
    with pytest.raises(ValueError, match='address'):
        instructions.decode(lambda *_: pytest.fail('unexpected source read'), address)


@pytest.mark.parametrize('base', [None, False, 0, 4097, 1 << 64, (1 << 64) - 8])
def test_invalid_base_rejects_before_read(base):
    with pytest.raises(ValueError, match='address'):
        instructions.verify_native(lambda *_: pytest.fail('unexpected source read'), base)


@pytest.mark.parametrize('index', range(len(instructions.NATIVE_SPANS)))
def test_every_compact_native_or_meaning_guard_rejects_change(instruction_memory, index):
    m = instruction_memory
    rva, raw = instructions.NATIVE_SPANS[index]
    m['put'](m['base'] + rva, bytes([raw[0] ^ 1]))
    with pytest.raises(ValueError, match='native layout changed'):
        instructions.verify_native(m['read'], m['base'])


@pytest.mark.parametrize('target', ['native', 'flags', 'mentality'])
def test_short_consumed_reads_fail(instruction_memory, target):
    m = instruction_memory
    address = {'native': m['base'] + instructions.NATIVE_SPANS[0][0],
               'flags': m['creator_addresses'][0] + 0xE0,
               'mentality': m['creator_addresses'][0] + 0x105}[target]
    def read(at, size):
        raw = m['read'](at, size)
        return raw[:-1] if at == address else raw
    with pytest.raises(ValueError, match='Incomplete'):
        if target == 'native':
            instructions.verify_native(read, m['base'])
        else:
            decode(m, read=read)


@pytest.mark.parametrize('target', ['native', 'flags', 'mentality'])
def test_request_readset_detects_late_source_or_meaning_mutation(instruction_memory, target):
    m = instruction_memory
    read = world.ReadSet(m['read'])
    instructions.verify_native(read, m['base'])
    decode(m, read=read)
    address = {'native': m['base'] + instructions.NATIVE_SPANS[-1][0],
               'flags': m['creator_addresses'][0] + 0xE0,
               'mentality': m['creator_addresses'][0] + 0x105}[target]
    m['put'](address, bytes([m['read'](address, 1)[0] ^ 1]))
    with pytest.raises(ValueError, match='changed during read'):
        read.verify()


def test_reads_only_logical_bits_and_mentality(instruction_memory):
    m = instruction_memory
    seen = []
    def read(address, size):
        seen.append((address, size))
        return m['read'](address, size)
    decode(m, read=read)
    creator = m['creator_addresses'][0]
    assert seen == [(creator + 0xE0, 11), (creator + 0x105, 1)]
