from io import BytesIO
import struct
import pytest
from fm_live_mcp import saved_fixed_history_index as fixed
from fm_live_mcp.saved_component_stream import Reader


def stream(raw): return Reader(BytesIO(raw), len(raw))
def vector(values): return struct.pack('<I', len(values)) + b''.join(struct.pack('<i', v) for v in values)
def sample(width=16, version=2):
    return (fixed.LIST_HEADER + vector([48]) + struct.pack('<I', 3) +
            vector([0, 32, -16]) + vector([16, -16, 16]) + vector([]) + vector([2]) +
            struct.pack('<IH', width, version))


def test_native_adjacent_words_order_and_empty_states():
    for key, expected, state in [(0, [0, 32, 16], 'selected_owner'), (1, [16, 0, 0], 'selected_owner'),
                                 (2, [], 'selected_owner'), (-1, [], 'no_history_index'),
                                 (3, [], 'outside_owner_table')]:
        out, summary = fixed.read_index(stream(sample()), key, width=16, data_version=2)
        assert out == expected and summary['state'] == state
        assert summary['other_owner_offsets_validated'] is False


def test_all_index_truncations_and_selected_data_extent():
    raw = sample()
    for end in range(len(raw)):
        with pytest.raises(ValueError): fixed.read_index(stream(raw[:end]), 0, width=16, data_version=2)
    data = b'\x03\x01tmc.\x02\0' + b'A' * 16 + b'B' * 16 + b'C' * 16
    assert fixed.read_rows(stream(data), [32, 0, 32, -1], width=16, data_version=2) == {0: b'A' * 16, 32: b'C' * 16}
    for end in range(len(data)):
        with pytest.raises(ValueError): fixed.read_rows(stream(data[:end]), [32], width=16, data_version=2)


@pytest.mark.parametrize('width,version', [(0, 2), (True, 2), (65537, 2), (16, -1), (16, True), (16, 65536)])
def test_invalid_profile(width, version):
    with pytest.raises(ValueError): fixed.read_index(stream(sample()), 0, width=width, data_version=version)


@pytest.mark.parametrize('offsets', [[1], [48], [1 << 31], [True], [None]])
def test_bad_selected_offsets(offsets):
    data = b'\x03\x01tmc.\x02\0' + bytes(48)
    with pytest.raises(ValueError): fixed.read_rows(stream(data), offsets, width=16, data_version=2)


def test_cross_family_mismatch_rejects():
    with pytest.raises(ValueError): fixed.read_index(stream(sample(168, 7)), 0, width=16, data_version=2)
    with pytest.raises(ValueError): fixed.read_rows(stream(b'\x03\x01tmc.\x07\0' + bytes(168)), [], width=16, data_version=2)
