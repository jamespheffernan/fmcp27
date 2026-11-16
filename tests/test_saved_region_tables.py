import io
import struct

import pytest

from fm_live_mcp import saved_region_tables as records
from fm_live_mcp.saved_component_stream import Reader


def reader(raw):
    return Reader(io.BytesIO(raw), len(raw))


def names(indices):
    return struct.pack('<I', len(indices)) + b''.join(
        struct.pack('<Hi4sH', 65535, index, b'abcd', 17) for index in indices)


def region(index=0):
    return bytes(66) + struct.pack('<III', index, 700, 701)


def local(index=0, languages=()):
    return (bytes(22) + struct.pack('<h', len(languages))
            + b''.join(struct.pack('<IB', *item) for item in languages)
            + struct.pack('<IIII', 33, index, 700, 701))


def test_name_tables_cross_chunk_and_late_original_index():
    size = records.NAME_CHUNK_ROWS + 3
    raw = names(range(size)) + names([0, 1]) + names([])
    stream = reader(raw)
    assert records.skip_name_tables(stream) == (size, 2, 0)
    assert stream.offset == len(raw)
    damaged = names(range(size)) + names([0, 0]) + names([])
    with pytest.raises(ValueError, match='repair or disorder'):
        records.skip_name_tables(reader(damaged))


@pytest.mark.parametrize('index', [-1, 1])
def test_name_invalid_original_index(index):
    with pytest.raises(ValueError, match='negative|repair or disorder'):
        records.skip_name_tables(reader(names([index]) + names([]) * 2))


def test_name_reads_have_bounded_allocations():
    class LimitedReader(Reader):
        def take(self, count):
            assert count <= records.NAME_CHUNK_ROWS * 12
            return super().take(count)
    raw = names(range(records.NAME_CHUNK_ROWS * 2 + 1)) + names([]) * 2
    records.skip_name_tables(LimitedReader(io.BytesIO(raw), len(raw)))


@pytest.mark.parametrize('decode,body,kind', [
    (records.skip_region, region(), -128),
    (records.skip_region, region(), 127),
    (records.skip_local_region, local(languages=[(4, 80), (9, 20)]), 0),
])
def test_complete_bodies_and_every_truncation(decode, body, kind):
    stream = reader(body)
    assert decode(stream, 0, kind) is None
    assert stream.offset == len(body)
    for end in range(len(body)):
        with pytest.raises(ValueError):
            decode(reader(body[:end]), 0, kind)


@pytest.mark.parametrize('decode,body', [
    (records.skip_region, region(1)),
    (records.skip_local_region, local(1)),
])
def test_original_identity_mismatch(decode, body):
    with pytest.raises(ValueError, match='ordinal mismatch'):
        decode(reader(body), 0, 0)


def test_counts_context_and_subtype_fail_closed():
    with pytest.raises(ValueError, match='row budget'):
        records.skip_name_tables(reader(struct.pack('<I', records.MAX_NAME_ROWS + 1)))
    for count in (-1, records.MAX_LANGUAGES + 1):
        with pytest.raises(ValueError, match='language count'):
            records.skip_local_region(reader(bytes(22) + struct.pack('<h', count)), 0, 0)
    for ordinal, kind in [(-1, 0), (True, 0), (0, True), (0, 1)]:
        with pytest.raises(ValueError):
            records.skip_local_region(reader(local()), ordinal, kind)


def test_later_generic_truncation():
    raw = names([0]) + names([0]) + names([0])
    for end in range(len(raw)):
        with pytest.raises(ValueError):
            records.skip_name_tables(reader(raw[:end]))
