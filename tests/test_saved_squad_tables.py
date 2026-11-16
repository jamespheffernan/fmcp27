"""Independent wire fixtures and frozen saved-file rows for simple callbacks."""

import io
import struct

import pytest

from fm_live_mcp import saved_squad_tables as tables
from fm_live_mcp.saved_component_stream import Reader


def reader(raw):
    return Reader(io.BytesIO(raw), len(raw))


def text(value):
    raw = value.encode('utf-8')
    return struct.pack('<I', len(raw)) + raw


def identity(index=0, native=42, secondary=0):
    return struct.pack('<III', index, native, secondary)


def media_body(counts=(1, 2, 3, 4, 5, 6, 7), *, name='Media €', index=0):
    a, b, c, d, e, f, g = counts
    return (text(name) + b'\x80' + struct.pack('<I', a) + bytes(a)
            + b'\x01\xff' + struct.pack('<I', b) + bytes(b * 4) + bytes(4)
            + struct.pack('<I', c) + bytes(c * 4)
            + struct.pack('<I', d) + bytes(d * 4) + bytes(4)
            + struct.pack('<I', e) + bytes(e * 8) + bytes(6)
            + bytes([f]) + bytes(f * 4)
            + struct.pack('<I', g) + bytes(g * 4) + b'\x07' + identity(index))


def stadium_body(*, marker=1, name=None, flags=None, index=0):
    flags = (16 if name is not None else 0) if flags is None else flags
    return (bytes(63) + bytes([marker]) + (bytes(66) if marker == 1 else b'')
            + bytes(13) + struct.pack('<H', flags)
            + (text(name) if flags & 16 else b'') + bytes(23) + identity(index))


def stage_body(*, flags=1, name='Stage €', index=0):
    return bytes([flags]) + (text(name) if flags & 1 else b'') + identity(index)


SYNTHETIC = {
    'injury': bytes(range(35)) + identity(),
    'media_source': media_body(),
    'language': text('日本語 ') + bytes(range(17)) + identity(),
    'stadium': stadium_body(name='Tétouan Community Ground'),
    'stadium_change': bytes(range(66)) + identity(),
    'stage_name': stage_body(),
}

# Exact first-row bodies in checked v02, following native-backed B29/B31/B32/
# B33 cursors. These are complete wire bytes after the caller-consumed subtype.
# Their stored ordinals are all zero; names/IDs are not needed by the callbacks.
REAL_ROWS = {
    'injury': bytes.fromhex(
        '0c30000100030001000300320001000000000040400000404000000002030105ffff09'
        '000000000100000001000000'),
    'media_source': bytes.fromhex(
        '0e0000004c69766572706f6f6c204563686f00010000000100010000000025040000'
        '00000000010000008b000000ffffffff08000000cb020000cb020000d9020000d902'
        '0000e0e04d00e0e04d00fa3e8300fa3e8300aa020000aa020000ff3e8300ff3e8300'
        'a4020000a40200008a0200008a0200000102197fee0701b48b01000000000001000000'
        '001200000012000000'),
    'language': bytes.fromhex(
        '08000000416c62616e69616e00000f2c00010014007e00000001000000000000000100000001000000'),
    'stadium': bytes.fromhex(
        'b42d0000b42d000074400000c82c0000ffffffff012b2c00001a04a802ffffffff0101'
        '03406d017607b600dd07b600d5070000040300840326021a04a8020301ac0d00001b00'
        '000d000000000000001498080000330000140000000000000014ac0d00001300000d00'
        '00000000000014c40900001300000d000000000000001401000f9800de0701006c07ff'
        'e927120a00000f040000ffffffffc80001006c07e4f04a429c4debbf000000005802000058020000'),
    'stadium_change': bytes.fromhex(
        'ce150000450600007a450000b600eb07b700f007ffffffff01ffffffff02ffffffff401f'
        '0000d0070000983a0000ffffffffb700f0070c00000000ffffffffffffff0000000008'
        '00000008000000'),
    'stage_name': bytes.fromhex('00000000000100000001000000'),
}


@pytest.mark.parametrize('name', SYNTHETIC)
@pytest.mark.parametrize('fixtures', [SYNTHETIC, REAL_ROWS], ids=['positive', 'real_v02'])
def test_complete_rows_and_next_cursor(name, fixtures):
    raw = fixtures[name]
    wire = reader(raw + b'next')
    assert getattr(tables, 'skip_' + name)(wire, 0, 0) is None
    assert wire.offset == len(raw)
    assert wire.take(4) == b'next'


@pytest.mark.parametrize('name', SYNTHETIC)
@pytest.mark.parametrize('fixtures', [SYNTHETIC, REAL_ROWS], ids=['positive', 'real_v02'])
def test_each_row_truncation_fails(name, fixtures):
    raw = fixtures[name]
    for end in range(len(raw)):
        with pytest.raises(ValueError):
            getattr(tables, 'skip_' + name)(reader(raw[:end]), 0, 0)


@pytest.mark.parametrize('name', SYNTHETIC)
@pytest.mark.parametrize('ordinal', [-1, True, 0.0, None, tables.MAX_DATABASE_SLOTS])
def test_invalid_ordinal_before_consumption(name, ordinal):
    wire = reader(b'')
    with pytest.raises(ValueError, match='ordinal'):
        getattr(tables, 'skip_' + name)(wire, ordinal, 0)
    assert wire.offset == 0


@pytest.mark.parametrize('name', SYNTHETIC)
def test_independent_identity_words_and_ordinal_mismatch(name):
    body = SYNTHETIC[name][:-12]
    raw = body + identity(tables.MAX_DATABASE_SLOTS - 1, 0, 0xFFFFFFFF)
    wire = reader(raw)
    getattr(tables, 'skip_' + name)(wire, tables.MAX_DATABASE_SLOTS - 1, 0)
    assert wire.offset == len(raw)
    with pytest.raises(ValueError, match='ordinal mismatch'):
        getattr(tables, 'skip_' + name)(reader(raw), 0, 0)


@pytest.mark.parametrize('name', [name for name in SYNTHETIC if name != 'stage_name'])
@pytest.mark.parametrize('kind', [-128, -1, 1, 12, 127, True, 0.0, None])
def test_other_tables_require_exact_zero_subtype(name, kind):
    wire = reader(b'')
    with pytest.raises(ValueError, match='subtype'):
        getattr(tables, 'skip_' + name)(wire, 0, kind)
    assert wire.offset == 0


def test_stage_accepts_every_signed_subtype_without_dropping_rows():
    for kind in range(-128, 128):
        wire = reader(stage_body(flags=0))
        tables.skip_stage_name(wire, 0, kind)
        assert wire.offset == 13


@pytest.mark.parametrize('kind', [-129, 128, 255, True, 0.0, None])
def test_stage_subtype_argument_is_signed_byte(kind):
    wire = reader(b'')
    with pytest.raises(ValueError, match='subtype'):
        tables.skip_stage_name(wire, 0, kind)
    assert wire.offset == 0


@pytest.mark.parametrize('marker', [0, 1, 2, 127, 255])
@pytest.mark.parametrize('name', [None, '', '東京 € '])
def test_stadium_child_exact_one_and_inline_bit16(marker, name):
    raw = stadium_body(marker=marker, name=name)
    wire = reader(raw)
    tables.skip_stadium(wire, 0, 0)
    assert wire.offset == len(raw)


@pytest.mark.parametrize('flags', [0, 2, 128, 254])
def test_stage_other_flag_bits_do_not_serialize_text(flags):
    wire = reader(stage_body(flags=flags))
    tables.skip_stage_name(wire, 0, -1)
    assert wire.offset == 13


def test_media_per_collection_and_whole_row_work_bounds():
    raw = media_body((10_000, 10_000, 10_000, 10_000, 10_000, 0, 0))
    wire = reader(raw)
    tables.skip_media_source(wire, 0, 0)
    assert wire.offset == len(raw)
    for counts in [(10_001, 0, 0, 0, 0, 0, 0),
                   (10_000, 10_000, 10_000, 10_000, 10_000, 1, 0),
                   (10_000, 10_000, 10_000, 10_000, 10_000, 0, 1)]:
        with pytest.raises(ValueError, match='work budget'):
            tables.skip_media_source(reader(media_body(counts)), 0, 0)


@pytest.mark.parametrize('name', ['media_source', 'language', 'stadium', 'stage_name'])
@pytest.mark.parametrize('bad_text', [struct.pack('<I', 8193), struct.pack('<I', 1) + b'\xff'])
def test_all_text_paths_are_bounded_utf8(name, bad_text):
    prefix = b''
    if name == 'stadium':
        prefix = bytes(63) + b'\0' + bytes(13) + struct.pack('<H', 16)
    elif name == 'stage_name':
        prefix = b'\1'
    with pytest.raises(ValueError):
        getattr(tables, 'skip_' + name)(reader(prefix + bad_text), 0, 0)


def test_late_media_count_rejects_even_after_all_previous_collections():
    raw = media_body((0, 0, 0, 0, 0, 0, 0))
    # Last collection count precedes +C3 and the12-byte identity.
    raw = raw[:-17] + struct.pack('<I', 0xFFFFFFFF) + raw[-13:]
    with pytest.raises(ValueError, match='work budget'):
        tables.skip_media_source(reader(raw), 0, 0)
