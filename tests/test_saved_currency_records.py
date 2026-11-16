"""Wire fixtures use bodies after the caller-consumed table subtype byte."""

import hashlib
import io
import struct

import pytest

from fm_live_mcp import saved_currency_records as records
from fm_live_mcp.saved_component_stream import Reader


def text(value):
    raw = value.encode('utf-8')
    return struct.pack('<I', len(raw)) + raw


def currency_body(index=0, native=1, secondary=1, name='British Pound',
                  rate_raw=None, history=(), extra_texts=('', '', '')):
    rate_raw = struct.pack('<f', 1.0) if rate_raw is None else rate_raw
    return (b''.join(text(value) for value in (name, *extra_texts)) + rate_raw
            + struct.pack('<I', len(history))
            + b''.join(struct.pack('<BH', marker, year) + raw
                       for marker, year, raw in history)
            + struct.pack('<III', index, native, secondary))


def currency(*args, **kwargs):
    return b'\0' + currency_body(*args, **kwargs)


def continent_body(index=0, native=1, secondary=1, optionals=None, maps=None):
    optionals = [None] * 6 if optionals is None else optionals
    maps = [struct.pack('<I', 0)] * 2 if maps is None else maps
    assert len(optionals) == 6 and len(maps) == 2
    return (bytes(21)
            + b''.join(b'\0' if value is None else b'\1' + value for value in optionals)
            + b''.join(maps) + struct.pack('<III', index, native, secondary))


def continent(*args, **kwargs):
    return b'\0' + continent_body(*args, **kwargs)


def reader(raw):
    return Reader(io.BytesIO(raw), len(raw))


# B29 following_tables/result.json: v02 CURRENCY ordinal0 at25523763..25524049.
# Complete serialized body (without subtype), also identical in the other three
# saved snapshots. Kept inline so tests need neither private saves nor evidence/.
ALBANIAN_BODY = bytes.fromhex(
    '0c000000416c62616e69616e204c656b030000004c656b00000000030000004c656b'
    'c50ce1422100000001c80716e6084301c90751821e4301ca07f419084301cb076e9e0943'
    '01cc07edfa284301cd07ebe1864301ce07d226764301cf07901a744301d0073c7f6043'
    '01d107b830514301d2071c1c514301d30721d2464301d407ee37404301d507fe843543'
    '01d6074891344301d70786a3344301d807e2641a4301d907e653144301da0732bd2043'
    '01db07aeb9214301dc07ed702b4301dd075e3a254301de07a1af2d4301df0793814043'
    '01e0070c10284301e107a915194301e2077742104301e3076f450c4301e407ae410b43'
    '01e507a5750e4301e607f9480b4301e7074d80f94201e80729c5ed42'
    '000000000200000002000000'
)


def test_real_complete_albanian_currency():
    assert hashlib.sha256(ALBANIAN_BODY).hexdigest() == (
        '1bb25c4b51bb4784c96adefa3a5dddb2b23c3b9794bd60a99423657caeb684cc')
    wire = reader(ALBANIAN_BODY + b'next')
    row = records.read_currency(wire, 0, 0, include_history=True)
    assert wire.offset == 285
    assert wire.take(4) == b'next'
    assert row['name'] == 'Albanian Lek'
    assert (row['database_index'], row['native_id'], row['secondary_id']) == (0, 2, 2)
    assert row['exchange_rate'] == {
        'value': 112.52494049072266, 'native_float32_hex': 'c50ce142',
        'state': 'stored', 'basis': 'currency_units_per_GBP'}
    assert row['history_count'] == len(row['history']) == 33
    assert [entry['native_year'] for entry in row['history']] == list(range(1992, 2025))
    assert row['history'][0]['exchange_rate']['native_float32_hex'] == '16e60843'
    assert row['history'][-1]['exchange_rate']['native_float32_hex'] == '29c5ed42'
    assert row['history'][-1]['native_index'] == 32


def test_history_not_requested_still_consumes_complete_row():
    wire = reader(ALBANIAN_BODY)
    row = records.read_currency(wire, 0, 0)
    assert row['history_count'] == 33 and 'history' not in row
    assert set(row) == {'database_index', 'native_id', 'secondary_id', 'name',
                        'exchange_rate', 'history_count'}
    assert wire.offset == len(ALBANIAN_BODY)


@pytest.mark.parametrize('name', ['', 'European Euro', 'Pound £ € 円 ', 'a\0b'])
def test_explicit_stored_text_and_independent_identity(name):
    raw = currency_body(19, 0, 0xFFFFFFFF, name=name, extra_texts=('€', '', '終'))
    wire = reader(raw)
    row = records.read_currency(wire, 19, 0, include_history=True)
    assert row['name'] == name
    assert row['native_id'] == 0 and row['secondary_id'] == 0xFFFFFFFF
    assert row['history_count'] == 0 and row['history'] == []
    assert wire.offset == len(raw)


@pytest.mark.parametrize(('raw_hex', 'value', 'state'), [
    ('00000000', 0.0, 'stored'), ('00000080', -0.0, 'stored'),
    ('000080bf', -1.0, 'negative_native_rate'), ('0000803f', 1.0, 'stored'),
    ('0000807f', None, 'non_finite'), ('000080ff', None, 'non_finite'),
    ('0100c07f', None, 'non_finite'), ('0100807f', None, 'non_finite'),
])
def test_float32_bits_units_and_nonfinite(raw_hex, value, state):
    raw = bytes.fromhex(raw_hex)
    row = records.read_currency(reader(currency_body(rate_raw=raw,
        history=((255, 0, raw), (0, 65535, raw), (2, 2024, raw), (1, 2024, raw)))),
        0, 0, include_history=True)
    expected = {'value': value, 'native_float32_hex': raw_hex, 'state': state,
                'basis': 'currency_units_per_GBP'}
    assert row['exchange_rate'] == expected
    assert [entry['exchange_rate'] for entry in row['history']] == [expected] * 4
    assert [entry['native_year'] for entry in row['history']] == [0, 65535, 2024, 2024]
    assert [entry['year'] for entry in row['history']] == [None, None, 2024, 2024]
    assert [entry['year_state'] for entry in row['history']] == [
        'invalid_native_year', 'invalid_native_year', 'stored', 'stored']
    if raw_hex == '00000080':
        assert struct.pack('<f', row['exchange_rate']['value']).hex() == raw_hex


@pytest.mark.parametrize('include_history', [False, True])
def test_history_bound(include_history):
    history = ((1, 9999, bytes(4)),) * records.MAX_HISTORY
    raw = currency_body(history=history)
    wire = reader(raw)
    row = records.read_currency(wire, 0, 0, include_history=include_history)
    assert row['history_count'] == records.MAX_HISTORY
    assert wire.offset == len(raw)
    raw = b''.join(text('') for _ in range(4)) + bytes(4) + struct.pack('<I', 2049)
    with pytest.raises(ValueError, match='history'):
        records.read_currency(reader(raw), 0, 0, include_history=include_history)


@pytest.mark.parametrize('include_history', [False, True])
def test_every_currency_truncation_rejects(include_history):
    for end in range(len(ALBANIAN_BODY)):
        with pytest.raises(ValueError):
            records.read_currency(reader(ALBANIAN_BODY[:end]), 0, 0,
                                  include_history=include_history)


@pytest.mark.parametrize('field', range(4))
def test_all_currency_texts_are_bounded_utf8(field):
    prefix = b''.join(text('') for _ in range(field))
    for invalid in (struct.pack('<I', 8193), struct.pack('<I', 1) + b'\xff'):
        with pytest.raises(ValueError):
            records.read_currency(reader(prefix + invalid), 0, 0)


def test_text_byte_limit_includes_unused_native_texts():
    raw = currency_body(name='x' * 8192, extra_texts=('é' * 4096, '', ''))
    wire = reader(raw)
    assert len(records.read_currency(wire, 0, 0)['name']) == 8192
    assert wire.offset == len(raw)


@pytest.mark.parametrize('function', [records.read_currency, records.skip_continent])
@pytest.mark.parametrize('ordinal', [-1, True, 1.0, None, records.MAX_DATABASE_SLOTS])
def test_bad_ordinal_rejects_before_read(function, ordinal):
    wire = reader(b'')
    with pytest.raises(ValueError, match='ordinal'):
        function(wire, ordinal, 0)
    assert wire.offset == 0


@pytest.mark.parametrize('function', [records.read_currency, records.skip_continent])
@pytest.mark.parametrize('kind', [1, 12, -1, True, 0.0, None])
def test_bad_subtype_rejects_before_read(function, kind):
    wire = reader(b'')
    with pytest.raises(ValueError, match='subtype'):
        function(wire, 0, kind)
    assert wire.offset == 0


@pytest.mark.parametrize('value', [0, 1, None, 'true'])
def test_history_flag_requires_boolean_before_read(value):
    wire = reader(b'')
    with pytest.raises(ValueError, match='Boolean'):
        records.read_currency(wire, 0, 0, include_history=value)
    assert wire.offset == 0


def test_stored_currency_ordinal_is_not_repaired():
    with pytest.raises(ValueError, match='ordinal mismatch'):
        records.read_currency(reader(currency_body(index=1)), 0, 0)


def test_continent_consumes_all_six_optional_vectors_and_both_maps():
    # Native variants carry an ignored marker, then type and payload.
    vector = struct.pack('<I', 2) + b'\xff\1' + bytes(4) + b'\0\x06'
    mapping = struct.pack('<II', 1, 0xFFFFFFFF) + b'\x02\x20' + b'abcd'
    raw = continent_body(index=5, optionals=[vector] * 6, maps=[mapping] * 2)
    wire = reader(raw + b'end')
    assert records.skip_continent(wire, 5, 0) is None
    assert wire.offset == len(raw) and wire.take(3) == b'end'


@pytest.mark.parametrize('marker', [0, 2, 127, 255])
def test_continent_only_marker_one_has_optional_payload(marker):
    raw = bytes(21) + bytes([marker]) * 6 + bytes(8) + bytes(12)
    wire = reader(raw)
    records.skip_continent(wire, 0, 0)
    assert wire.offset == len(raw)


def test_every_continent_truncation_rejects():
    raw = continent_body(optionals=[struct.pack('<I', 0)] * 6)
    for end in range(len(raw)):
        with pytest.raises(ValueError):
            records.skip_continent(reader(raw[:end]), 0, 0)


def test_continent_rejects_late_unsupported_property_and_bad_ordinal():
    invalid_vector = struct.pack('<I', 1) + b'\1\xff'
    with pytest.raises(ValueError, match='Unsupported saved property'):
        records.skip_continent(reader(continent_body(optionals=[None] * 5
                                  + [invalid_vector])), 0, 0)
    invalid_map = struct.pack('<II', 1, 7) + b'\1\xff'
    with pytest.raises(ValueError, match='Unsupported saved property'):
        records.skip_continent(reader(continent_body(maps=[bytes(4), invalid_map])), 0, 0)
    with pytest.raises(ValueError, match='ordinal mismatch'):
        records.skip_continent(reader(continent_body(index=1)), 0, 0)
