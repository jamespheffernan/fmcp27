"""Stored-source examples and bounded read failures; no live game access."""
import struct

import pytest

from fm_live_mcp import prepared_tactics_fields as fields, world


# Independently captured Newcastle owned creators, tactic-selection-09.
IP = [1, 4, 0x200010, 0x100010, 8, 0x200080, 0x100080,
      0x800, 0x2000, 0x1000, 0x4000]
OOP_DEF = [1, 4, 0x200010, 0x100010, 8, 0x200080, 0x100080,
           0x100, 0x200, 0x2000, 0x4000]
OOP_ATT = [1, 4, 0x200010, 0x100010, 8, 0x200080, 0x100080,
           0x800, 0x1000, 0x2000, 0x4000]
IP_NAMES = ['GK', 'D(R)', 'D(CR)', 'D(CL)', 'D(L)', 'DM(CR)', 'DM(CL)',
            'AM(R)', 'AM(C)', 'AM(L)', 'ST(C)']


@pytest.fixture
def field_memory():
    cells = {}
    base, creator, text = 0x100000000, 0x10000, 0x20003

    def put(address, raw):
        cells.update({address + index: byte for index, byte in enumerate(raw)})

    def read(address, size):
        return bytes(cells[address + index] for index in range(size))

    def name(value):
        if value is None:
            put(creator + 0x790, bytes(8))
            return
        raw = value.encode('utf-8') if isinstance(value, str) else value
        put(creator + 0x790, struct.pack('<Q', text))
        put(text, struct.pack('<I', len(raw)) + raw + b'\0')

    def phase(offset, masks):
        for index, mask in enumerate(masks):
            put(creator + offset + index * 0x48, struct.pack('<I', mask))

    for rva, expected in fields.NATIVE_SPANS:
        put(base + rva, expected)
    name('4231 FM27 Def')
    phase(0x120, IP)
    phase(0x440, OOP_DEF)
    return dict(base=base, creator=creator, text=text, put=put, read=read,
                name=name, phase=phase)


def decode(m, read=None):
    return fields.decode(read or m['read'], m['base'], m['creator'])


@pytest.mark.parametrize('tactic_name,oop,oop_names', [
    ('4231 FM27 Def', OOP_DEF,
     IP_NAMES[:7] + ['M(R)', 'M(L)', 'AM(C)', 'ST(C)']),
    ('4231 FM27 ', OOP_DEF,
     IP_NAMES[:7] + ['M(R)', 'M(L)', 'AM(C)', 'ST(C)']),
    ('Copy of: 4231 FM27 Att', OOP_ATT,
     IP_NAMES[:7] + ['AM(R)', 'AM(L)', 'AM(C)', 'ST(C)']),
])
def test_independent_owned_creator_phase_samples(field_memory, tactic_name, oop, oop_names):
    m = field_memory
    m['name'](tactic_name)
    m['phase'](0x440, oop)
    read = world.ReadSet(m['read'])
    result = decode(m, read)
    read.verify()
    assert set(result) == {'name', 'name_state', 'phases'}
    assert result['name'] == tactic_name and result['name_state'] == 'stored'
    for key, masks, names in [('in_possession', IP, IP_NAMES),
                              ('out_of_possession', oop, oop_names)]:
        phase = result['phases'][key]
        assert phase['formation'] is None
        assert phase['positions'] == [
            {'position_index': i, 'native_mask': mask, 'name': name, 'state': 'named'}
            for i, (mask, name) in enumerate(zip(masks, names))]
    assert '0x' not in repr(result)


@pytest.mark.parametrize('value,state', [(None, 'null_native_string'), ('', 'empty'),
                                          (' ', 'stored'), ('  4231  ', 'stored'),
                                          ('São Paulo ⚽ 日本', 'stored'),
                                          ('é' * 256, 'stored'), ('a' * 512, 'stored')])
def test_native_name_states_unicode_and_trailing_space(field_memory, value, state):
    m = field_memory
    m['name'](value)
    result = decode(m)
    assert result['name'] == value and result['name_state'] == state
    assert len(result['phases']['in_possession']['positions']) == 11


@pytest.mark.parametrize('raw', [b'\xff', b'\xc0\x80', b'\xed\xa0\x80', b'\xf0\x80\x80\x80',
                                b'a\0b', b'a\nb', b'\t', b'\x7f'])
def test_malformed_utf8_or_control_names_reject_whole_creator(field_memory, raw):
    m = field_memory
    m['name'](raw)
    with pytest.raises(ValueError):
        decode(m)


@pytest.mark.parametrize('length', [513, 65535, 0xFFFFFFFF])
def test_name_length_budget_rejects_before_reading_payload(field_memory, length):
    m = field_memory
    m['put'](m['text'], struct.pack('<I', length))
    with pytest.raises(ValueError, match='bound'):
        decode(m)


@pytest.mark.parametrize('value', ['', 'valid'])
def test_empty_and_nonempty_native_strings_require_terminator(field_memory, value):
    m = field_memory
    m['name'](value)
    m['put'](m['text'] + 4 + len(value), b'x')
    with pytest.raises(ValueError, match='terminator'):
        decode(m)


@pytest.mark.parametrize('mask', [0, 2, 0x100010 | 8, 0xFFFFFFFF, 0x80000000])
def test_every_unproved_mask_retains_unsigned_value_without_guess(field_memory, mask):
    m = field_memory
    m['put'](m['creator'] + 0x120 + 5 * 0x48, struct.pack('<I', mask))
    result = decode(m)
    assert result['phases']['in_possession']['positions'][5] == {
        'position_index': 5, 'native_mask': mask,
        'name': None, 'state': 'unmapped_native_mask'}
    assert result['phases']['out_of_possession']['positions'][5]['name'] == 'DM(CR)'


def test_source_slot_order_is_retained_without_sort_or_dedup(field_memory):
    m = field_memory
    masks = [0x200, 1, 0, 1, 4, 4, 0xFFFFFFFF, 8, 0x800, 0x2000, 0x1000]
    m['phase'](0x120, masks)
    positions = decode(m)['phases']['in_possession']['positions']
    assert [p['native_mask'] for p in positions] == masks
    assert [p['position_index'] for p in positions] == list(range(11))


@pytest.mark.parametrize('address', [None, True, 0, 4095, 4097, 1 << 64, (1 << 64) - 8])
def test_invalid_creator_pointer_rejects_before_read(field_memory, address):
    m = field_memory
    with pytest.raises(ValueError, match='address'):
        fields.decode(lambda *_: pytest.fail('unexpected read'), m['base'], address)


@pytest.mark.parametrize('pointer', [1, 4095, (1 << 64) - 1])
def test_invalid_nonnull_string_pointer_rejects(field_memory, pointer):
    m = field_memory
    m['put'](m['creator'] + 0x790, struct.pack('<Q', pointer))
    with pytest.raises(ValueError, match='address'):
        decode(m)


@pytest.mark.parametrize('index', range(len(fields.NATIVE_SPANS)))
def test_every_native_guard_rejects_mismatch(field_memory, index):
    m = field_memory
    rva, raw = fields.NATIVE_SPANS[index]
    m['put'](m['base'] + rva, bytes([raw[0] ^ 1]))
    with pytest.raises(ValueError, match='native layout changed'):
        decode(m)


@pytest.mark.parametrize('target', ['native', 'pointer', 'length', 'text', 'ip', 'oop'])
def test_short_reads_reject(field_memory, target):
    m = field_memory
    address = {'native': m['base'] + fields.NATIVE_SPANS[0][0],
               'pointer': m['creator'] + 0x790, 'length': m['text'],
               'text': m['text'] + 4, 'ip': m['creator'] + 0x120,
               'oop': m['creator'] + 0x440}[target]
    def read(at, size):
        raw = m['read'](at, size)
        return raw[:-1] if at == address else raw
    with pytest.raises(ValueError, match='Incomplete'):
        decode(m, read)


@pytest.mark.parametrize('target', ['native', 'pointer', 'length', 'text', 'ip', 'oop'])
def test_supplied_readset_detects_every_consumed_lifetime_change(field_memory, target):
    m = field_memory
    read = world.ReadSet(m['read'])
    decode(m, read)
    address = {'native': m['base'] + fields.NATIVE_SPANS[0][0],
               'pointer': m['creator'] + 0x790, 'length': m['text'],
               'text': m['text'] + 4, 'ip': m['creator'] + 0x120,
               'oop': m['creator'] + 0x440 + 10 * 0x48}[target]
    m['put'](address, bytes([m['read'](address, 1)[0] ^ 1]))
    with pytest.raises(ValueError, match='changed during read'):
        read.verify()


def test_decoder_only_reads_proved_fields_not_whole_creator(field_memory):
    m = field_memory
    reads = []
    def read(address, size):
        reads.append((address, size))
        return m['read'](address, size)
    decode(m, read)
    creator_reads = [(a, n) for a, n in reads if m['creator'] <= a < m['creator'] + 0x7C0]
    assert creator_reads == [(m['creator'] + 0x790, 8)] + [
        (m['creator'] + offset + index * 0x48, 4)
        for offset in [0x120, 0x440] for index in range(11)]


@pytest.mark.parametrize('mask,label', [
    (128, 'DM(C)'), (2098176, 'M(CR)'), (1049600, 'M(CL)'),
])
def test_source_bound_central_midfield_slots_in_both_phases(field_memory, mask, label):
    m = field_memory
    for phase, offset in fields.PHASE_OFFSETS.items():
        m['phase'](offset, [mask] + IP[1:])
    result = decode(m)
    for phase in fields.PHASE_OFFSETS:
        position = result['phases'][phase]['positions'][0]
        assert position == {'position_index': 0, 'native_mask': mask,
                            'name': label, 'state': 'named'}


@pytest.mark.parametrize('mask', [0x300400, 0x200480, 0x100480, 0x400])
def test_unproved_composite_masks_remain_unknown(field_memory, mask):
    m = field_memory
    m['phase'](0x120, [mask] + IP[1:])
    position = decode(m)['phases']['in_possession']['positions'][0]
    assert position['native_mask'] == mask
    assert position['name'] is None
    assert position['state'] == 'unmapped_native_mask'


@pytest.mark.parametrize('mask,label', [(16,'D(C)'), (32,'WB(R)'), (64,'WB(L)'), (1064960,'ST(CL)'), (2113536,'ST(CR)'), (1056768,'AM(CL)'), (2105344,'AM(CR)')])
def test_additional_exact_position_masks(mask, label):
    assert fields.POSITION_NAMES[mask] == label
