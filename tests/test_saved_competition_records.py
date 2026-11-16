import io
import struct

import pytest

from fm_live_mcp import saved_competition_records as records
from fm_live_mcp.saved_component_stream import Reader
from test_saved_competition_prefix import wire


def _record(*, ordinal=0, native_id=1, secondary_id=1, type_code=0,
            gender_code=0, is_extinct=False, history_version=None,
            property_vector=None, row_versions=(), secondary_versions=None,
            nested_counts=None, fixed_child=False, references=False,
            count108=0, count110=0, packed=False, presence=1, **prefix_options):
    data = bytearray(wire(**prefix_options))
    offsets = {}

    def mark(key):
        offsets[key] = len(data)

    data.append(0 if history_version is None else presence)
    if history_version is not None and presence == 1:
        data.append(history_version)
        data.extend(bytes(4 + 2 + 2 + 24 + (4 if history_version >= 2 else 0)
                          + 8 + 1 + (2 if history_version >= 3 else 1) + 8))
    data.extend(bytes(4))
    data.extend(struct.pack('<BBbB', 0x04 if is_extinct else 0, 0,
                            type_code, gender_code))
    data.append(0 if property_vector is None else presence)
    if property_vector is not None and presence == 1:
        data.extend(property_vector)
    mark('rows')
    data.extend(struct.pack('<i', len(row_versions)))
    for version in row_versions:
        data.extend(struct.pack('<b', version))
        data.extend(bytes(7 + (version >= 2)))
    data.append(0 if secondary_versions is None else presence)
    if secondary_versions is not None and presence == 1:
        data.extend(struct.pack('<I', 3))
        mark('secondary_count')
        data.extend(struct.pack('<I', len(secondary_versions)))
        for version in secondary_versions:
            data.extend(struct.pack('<h', version))
            data.extend(bytes(6 + (2 if version >= 2 else 1) + 1
                              + (version >= 3)))
    data.append(0 if nested_counts is None else presence)
    if nested_counts is not None and presence & 1:
        data.append(0)
        mark('outer_count')
        data.extend(struct.pack('<I', len(nested_counts)))
        for index, count in enumerate(nested_counts):
            data.extend(bytes(2))
            mark(f'inner_count_{index}')
            data.extend(struct.pack('<I', count))
            data.extend(bytes(count * 12))
    data.append(presence if fixed_child else 0)
    if fixed_child and presence == 1:
        data.extend(bytes(25))
    data.append(0)
    for _ in range(2):
        data.append(presence if references else 0)
        if references and presence == 1:
            data.extend(bytes(15))
    mark('count108')
    data.extend(struct.pack('<h', count108))
    data.extend(bytes(max(count108, 0) * 5))
    data.append(count110)
    data.extend(bytes(count110 * 13))
    data.extend(bytes(30))
    data.append(presence if packed else 0)
    if packed and presence == 1:
        data.extend(bytes(2))
    data.extend(bytes(11))
    mark('identity')
    data.extend(struct.pack('<III', ordinal, native_id, secondary_id))
    return bytes(data), offsets


def record(**kwargs):
    """Complete COMP wire after (and excluding) the table subtype byte."""
    return _record(**kwargs)[0]


def read(data, ordinal=0, kind=0):
    reader = Reader(io.BytesIO(data), len(data))
    result = records.read_competition(reader, ordinal, kind)
    return result, reader


def test_public_fields_and_exact_next_boundary():
    data = record(ordinal=7, native_id=987, secondary_id=0, branch=4,
                  name='Full é', short_name='', type_code=-128,
                  gender_code=255, is_extinct=True, level=100, reputation=-32768)
    result, reader = read(data + b'NEXT', ordinal=7)
    assert result == {
        'name': 'Full é', 'short_name': '', 'stored_name_state': 'serialized_branch4',
        'reputation': -32768, 'native_level_code': 100, 'level': None,
        'database_index': 7, 'native_id': 987, 'secondary_id': 0,
        'type_code': -128, 'gender_code': 255, 'is_extinct': True,
    }
    assert reader.take(4) == b'NEXT'


@pytest.mark.parametrize('version', [0, 1, 2, 3, 255])
def test_history_threshold_widths(version):
    data = record(history_version=version)
    assert read(data)[1].offset == len(data)


@pytest.mark.parametrize('presence', [0, 2, 3, 255])
def test_exact_one_children_and_low_bit_nested_presence(presence):
    data = record(history_version=3, property_vector=b'not consumed',
                  secondary_versions=(3,), nested_counts=(1, 2), fixed_child=True,
                  references=True, packed=True, presence=presence)
    assert read(data)[1].offset == len(data)


def rich_record():
    # A recursive map/vector, text and native extension32 are consumed by the
    # real production property walker, rather than a substituted child result.
    properties = (struct.pack('<I', 2) + bytes((1, 10)) + struct.pack('<I', 1)
                  + struct.pack('<I', 42) + bytes((1, 11)) + struct.pack('<I', 1)
                  + bytes((1, 26)) + struct.pack('<I', 2) + b'ok'
                  + bytes((1, 32)) + bytes(4))
    return record(branch=4, name='All children', history_version=3,
                  property_vector=properties, row_versions=(-128, 1, 2, 127),
                  secondary_versions=(-32768, 0, 1, 2, 3, 32767),
                  nested_counts=(0, 1, 2), fixed_child=True, references=True,
                  count108=3, count110=2, packed=True)


def test_all_children_composed_and_consecutive_records():
    first, second = rich_record(), record(ordinal=1, native_id=100, secondary_id=200)
    reader = Reader(io.BytesIO(first + second), len(first + second))
    assert records.read_competition(reader, 0, 0)['name'] == 'All children'
    assert reader.offset == len(first)
    assert records.read_competition(reader, 1, 0)['secondary_id'] == 200
    assert reader.offset == len(first + second)


def test_every_rich_record_truncation_rejects():
    data = rich_record()
    for end in range(len(data)):
        with pytest.raises(ValueError):
            read(data[:end])


@pytest.mark.parametrize('count', [-2147483648, -1])
def test_signed_nonpositive_row_counts_follow_native_empty_branch(count):
    data, offsets = _record(count108=-32768)
    data = bytearray(data)
    struct.pack_into('<i', data, offsets['rows'], count)
    assert read(bytes(data))[1].offset == len(data)


@pytest.mark.parametrize('field,fmt', [('rows', '<i'), ('secondary_count', '<I'),
                                     ('outer_count', '<I'), ('inner_count_0', '<I'),
                                     ('count108', '<h')])
def test_each_untrusted_large_count_fails_before_skip(field, fmt):
    data, offsets = _record(secondary_versions=(), nested_counts=(0,))
    data = bytearray(data)
    struct.pack_into(fmt, data, offsets[field], records.MAX_CHILD_ITEMS + 1)
    with pytest.raises(ValueError, match='item budget'):
        read(bytes(data))


def test_cumulative_nested_item_budget():
    # Individually allowed vectors must not multiply into an unbounded walk.
    data = record(nested_counts=(10_000, 10_000))
    with pytest.raises(ValueError, match='cumulative'):
        read(data)


def test_opaque_rows_are_skipped_without_materialization():
    class SkipReader(Reader):
        def take(self, count):
            assert count <= 4
            return super().take(count)

    data = record(nested_counts=(1000,), count108=1000, count110=255)
    reader = SkipReader(io.BytesIO(data), len(data))
    records.read_competition(reader, 0, 0)
    assert reader.offset == len(data)


@pytest.mark.parametrize('ordinal,kind', [(True, 0), (-1, 0), (2_000_000, 0),
                                         (0, True), (0, 1), (0, -1)])
def test_invalid_contract_rejects_without_reading(ordinal, kind):
    with pytest.raises(ValueError):
        read(b'', ordinal, kind)


def test_ordinal_mismatch_and_unknown_property_variant_fail_closed():
    with pytest.raises(ValueError, match='ordinal mismatch'):
        read(record(ordinal=1))
    with pytest.raises(ValueError, match='Unsupported saved property'):
        read(record(property_vector=struct.pack('<I', 1) + bytes((0, 255))))


@pytest.mark.parametrize('flag,extinct', [(0, False), (1, False), (4, True),
                                       (16, False), (20, True), (128, False), (255, True)])
def test_extinct_uses_native_mask_four_not_bit_index_four(flag, extinct):
    data = bytearray(record())
    prefix_length = len(wire())
    data[prefix_length + 1 + 4] = flag
    assert read(bytes(data))[0]['is_extinct'] is extinct
