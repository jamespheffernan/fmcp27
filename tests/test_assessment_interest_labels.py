"""Self-contained native viewer boundary controls; no game reads or evidence imports."""
import struct
import pytest

from fm_live_mcp import assessment_interest_labels as labels, assessment_interest_source as source, world


def decode(value=10000, **kwargs):
    args = dict(field5_present=True, flag41=0, child_present=True,
                byte79=0, byte7a=None)
    args.update(kwargs)
    return labels.decode(value, **args)


@pytest.mark.parametrize('value,category,keys', [
    (-(1 << 31), 'none', (652340, 652341)),
    (-111112, 'none', (652340, 652341)),
    (-111111, 'native_empty_template', (None, None)),
    (-111110, 'none', (652340, 652341)),
    (-100003, 'none', (652340, 652341)),
    (-100002, 'already_agreed_to_move', (652337, 283690)),
    (-100001, 'none', (652340, 652341)),
    (-100000, 'none', (652340, 652341)),
    (-40001, 'none', (652340, 652341)),
    (-40000, 'extremely_doubtful', (652335, 652336)),
    (-39999, 'extremely_doubtful', (652335, 652336)),
    (-2001, 'extremely_doubtful', (652335, 652336)),
    (-2000, 'dubious', (652331, 652332)),
    (-1999, 'dubious', (652331, 652332)),
    (-1, 'dubious', (652331, 652332)),
    (0, 'dubious', (652331, 652332)),
    (1, 'dubious', (652331, 652332)),
    (4999, 'dubious', (652331, 652332)),
    (5000, 'slight_interest', (652327, 652328)),
    (5001, 'slight_interest', (652327, 652328)),
    (9999, 'slight_interest', (652327, 652328)),
    (10000, 'interested', (652323, 652324)),
    (10001, 'interested', (652323, 652324)),
    (29999, 'interested', (652323, 652324)),
    (30000, 'extremely_interested', (652319, 652320)),
    (30001, 'extremely_interested', (652319, 652320)),
    ((1 << 31) - 1, 'extremely_interested', (652319, 652320)),
])
def test_full_signed_domain_boundaries(value, category, keys):
    result = decode(value)
    assert result['category'] == category
    assert (result['compact']['key'], result['long']['key']) == keys
    assert result['state'] == ('native_empty_template' if keys[0] is None else 'available')


@pytest.mark.parametrize('value,compact,long,senior_compact,senior_long', [
    (30000, 'Extremely Interested', 'Extremely interested in joining our club.',
     'Extremely interested in Senior contract transfer',
     'Extremely interested in joining our club on Senior contract.'),
    (10000, 'Interested', 'Interested in joining our club.',
     'Interested in Senior contract transfer',
     'Interested in joining our club on a Senior contract.'),
    (5000, 'Slight Interest', 'Some interest in joining our club.',
     'Some interest in Senior contract transfer',
     'Some interest in joining our club on a Senior contract.'),
    (0, 'Dubious', 'Would need some convincing to join our club at this time.',
     'Would need some convincing to join on a Senior contract transfer',
     'Would need some convincing to join on a Senior contract at this time.'),
    (-40000, 'Extremely Doubtful', 'Not interested in joining our club at this time.',
     'No interest in Senior contract transfer',
     'Not interested in joining our club on a Senior contract at this time.'),
])
def test_exact_ordinary_and_mls_english(value, compact, long, senior_compact, senior_long):
    ordinary = decode(value)
    senior = decode(value, byte79=0x20)
    assert ordinary['compact']['text'] == compact
    assert ordinary['long']['text'] == long
    assert senior['compact']['text'] == senior_compact
    assert senior['long']['text'] == senior_long


def test_unknown_precedes_every_formatter_input_and_is_not_stored_none():
    unknown = decode(None, field5_present=False, flag41=None,
                     byte79=None, byte7a=None)
    assert unknown == {
        'state': 'unknown', 'category': None,
        'compact': {'key': 227378, 'text': 'Unknown'},
        'long': {'key': 227378, 'text': 'Unknown'},
        'source': 'stored_assessment_native_viewer_english'}
    assert decode(-100000)['compact'] == {'key': 652340, 'text': 'None'}
    assert decode(-100000)['state'] == 'available'


@pytest.mark.parametrize('child,byte7a', [(False, None), (True, 0), (True, 127)])
def test_na_skips_unused_scalar_and_senior_byte(child, byte7a):
    result = decode(None, flag41=1, child_present=child, byte7a=byte7a, byte79=None)
    assert result == {
        'state': 'not_applicable', 'category': None,
        'compact': {'key': 242522, 'text': 'N/A'},
        'long': {'key': 242522, 'text': 'N/A'},
        'source': 'stored_assessment_native_viewer_english'}


@pytest.mark.parametrize('flag41', [0, 2, 128, 255])
def test_only_exact_flag41_one_has_na_gate(flag41):
    assert decode(flag41=flag41, byte7a=None)['compact']['key'] == 652323


@pytest.mark.parametrize('byte7a', [128, 129, 255])
def test_bit7_bypasses_na(byte7a):
    assert decode(flag41=1, byte7a=byte7a)['compact']['key'] == 652323


def test_all_byte79_values_only_bit5_changes_wording():
    for byte in range(256):
        expected = 652321 if byte & 32 else 652323
        assert decode(byte79=byte)['compact']['key'] == expected


def test_null_child_ignores_child_bytes_and_has_no_senior_wording():
    assert decode(child_present=False, byte79=None)['compact']['key'] == 652323
    assert decode(child_present=False, byte79=255)['compact']['key'] == 652323


@pytest.mark.parametrize('value', [-111111, -100002, -40001, -(1 << 31)])
def test_special_branches_skip_senior_byte(value):
    assert decode(value, byte79=None) == decode(value, byte79=255)


def test_empty_template_has_null_key_and_text():
    result = decode(-111111)
    assert result['state'] == result['category'] == 'native_empty_template'
    assert result['compact'] == result['long'] == {'key': None, 'text': None}


def test_already_agreed_retains_visible_native_surname_marker():
    result = decode(-100002)
    assert result['compact'] == {'key': 652337, 'text': 'Already agreed to move'}
    assert result['long'] == {'key': 283690,
                              'text': '[%person#1-surname] has already agreed to move clubs.'}


@pytest.mark.parametrize('value', [None, True, False, '10000', 10000.0,
                                   -(1 << 31) - 1, 1 << 31])
def test_invalid_used_scalar_rejects(value):
    with pytest.raises(ValueError, match='signed32'):
        decode(value)


@pytest.mark.parametrize('field,value', [
    ('field5_present', 1), ('field5_present', None), ('child_present', 0),
    ('flag41', None), ('flag41', True), ('flag41', -1), ('flag41', 256),
    ('byte79', None), ('byte79', True), ('byte79', -1), ('byte79', 256),
])
def test_invalid_used_input_rejects(field, value):
    with pytest.raises(ValueError):
        decode(**{field: value})


@pytest.mark.parametrize('value', [None, True, -1, 256])
def test_invalid_used_byte7a_rejects(value):
    with pytest.raises(ValueError):
        decode(flag41=1, byte7a=value)


def test_results_are_independent_mutable_dictionaries():
    result = decode()
    result['compact']['text'] = 'changed'
    assert decode()['compact']['text'] == 'Interested'


@pytest.mark.parametrize('child,present,flag,value,b7a,b79,state,category', [
    (False, False, None, None, None, None, 'unknown', None),
    (True, False, None, None, None, None, 'unknown', None),
    (True, True, 1, None, 0, None, 'not_applicable', None),
    (True, True, 1, 10000, 128, 32, 'available', 'interested'),
    (True, True, 0, 0, None, 0, 'available', 'dubious'),
    (True, True, 2, -40000, None, 32, 'available', 'extremely_doubtful'),
    (True, True, 0, -40001, None, None, 'available', 'none'),
    (True, True, 0, -111111, None, None, 'native_empty_template', 'native_empty_template'),
    (True, True, 0, -100002, None, None, 'available', 'already_agreed_to_move'),
])
def test_real_sparse_source_projection_composes(child, present, flag, value, b7a, b79,
                                              state, category):
    # Unconsumed storage is deliberately absent; an unwanted source read fails.
    data, record, extra, entries = {}, 0x10000, 0x20000, 0x30000

    def put(address, raw):
        data.update({address + i: byte for i, byte in enumerate(raw)})

    def read(address, length):
        return bytes(data[address + i] for i in range(length))

    put(record + 0x30, struct.pack('<Q', extra if child else 0))
    if child:
        put(extra + 0x178, struct.pack('<QQQ', entries, entries + 0x68, entries + 0x68)
            if present else bytes(24))
        if present:
            put(entries + 0x60, b'\x05')
        else:
            put(extra + 0x160, bytes(24))
    for address, scalar in [(record + 0x41, flag), (extra + 0x7a, b7a),
                            (extra + 0x79, b79)]:
        if scalar is not None:
            put(address, bytes([scalar]))
    if value is not None:
        put(record + 0x20, struct.pack('<i', value))
    projected = source.inspect(read, record)
    assert projected == dict(value=value, field5_present=present, flag41=flag,
                             child_present=child, byte79=b79, byte7a=b7a)
    result = labels.decode(**projected)
    assert result['state'] == state
    assert result['category'] == category


@pytest.mark.parametrize('value,compact,long', [
    (-96213, 'None', 'No intention of joining our club on a permanent basis.'),
    (-32160, 'Extremely Doubtful', 'Not interested in joining our club at this time.'),
    (-31366, 'Extremely Doubtful', 'Not interested in joining our club at this time.'),
    (100000, 'Extremely Interested', 'Extremely interested in joining our club.'),
    (-100000, 'None', 'No intention of joining our club on a permanent basis.'),
    (3704, 'Dubious', 'Would need some convincing to join our club at this time.'),
])
def test_six_independently_observed_stored_scalars(value, compact, long):
    result = decode(value)
    assert result['compact']['text'] == compact
    assert result['long']['text'] == long


def native_memory():
    base = 0x100000000
    memory = {base + rva: raw for rva, raw in labels.NATIVE_SPANS}
    return base, memory, lambda address, length: memory[address][:length]


def test_native_guard_matches_readset_and_participates_in_late_recheck():
    base, memory, raw_read = native_memory()
    read = world.ReadSet(raw_read)
    labels.verify_native(read, base)
    read.verify()
    address = next(iter(memory))
    memory[address] = memory[address][:-1] + bytes([memory[address][-1] ^ 1])
    with pytest.raises(ValueError):
        read.verify()


@pytest.mark.parametrize('where', [0, -1, 300])
def test_native_code_mismatch_rejects(where):
    base, memory, read = native_memory()
    address = next(iter(memory))
    data = bytearray(memory[address])
    data[where] ^= 1
    memory[address] = bytes(data)
    with pytest.raises(ValueError, match='native layout changed'):
        labels.verify_native(read, base)


def test_native_short_read_rejects():
    base, memory, read = native_memory()
    with pytest.raises(ValueError, match='native layout changed'):
        labels.verify_native(lambda address, length: read(address, length - 1), base)


@pytest.mark.parametrize('base', [None, True, 0, 4095, 4097, (1 << 64) - 8])
def test_invalid_base_rejects_without_reads(base):
    def forbidden(*args):
        raise AssertionError('invalid base read')
    with pytest.raises(ValueError):
        labels.verify_native(forbidden, base)
