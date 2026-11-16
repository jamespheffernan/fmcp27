import ctypes
import io
import struct
from types import SimpleNamespace

import pytest

from fm_live_mcp.saved_component_stream import Reader, _library, open_component
from fm_live_mcp.saved_team_records import read_team
from fm_live_mcp import saved_team_records


def text(value):
    raw = value.encode('utf-8')
    return struct.pack('<I', len(raw)) + raw


def record(*, kind=10, ordinal=545, native_id=688, secondary_id=12, team_type=0,
           owner_kind=0, owner=414, name='', short_name='', roster=(13009, 13248),
           national_count=0):
    national = b''
    if kind == 11:
        national = bytes(53) + struct.pack('<b', national_count)
        national += bytes(max(national_count, 0) * 10)
    specialized = bytes(33) + struct.pack('<H', len(roster))
    specialized += b''.join(struct.pack('<i', word) for word in roster) + bytes(18)
    common = struct.pack('<bB', team_type, owner_kind) + bytes(4) + struct.pack('<I', owner)
    common += text(name) + b'\0' + text(short_name) + b'\0'
    common += struct.pack('<III', ordinal, native_id, secondary_id)
    return national + specialized + common


@pytest.mark.parametrize('kind', [10, 11])
def test_exact_saved_identity_owner_and_ordered_roster(kind):
    data = record(kind=kind, roster=(13248, 13009, 13248, -1), name='Stored Team', short_name='ST')
    reader = Reader(io.BytesIO(data + b'N'), len(data) + 1)
    assert read_team(reader, 545, kind) == {
        'database_index': 545, 'native_id': 688, 'secondary_id': 12,
        'team_type_code': 0, 'owner_kind': 'club', 'owner_index': 414,
        'name': 'Stored Team', 'short_name': 'ST', 'roster_count': 4,
        'person_indices': [13248, 13009, 13248, None],
    }
    assert reader.offset == len(data) and reader.take(1) == b'N'


@pytest.mark.parametrize('kind', [10, 11])
def test_roster_not_requested_preserves_count_and_cursor(kind):
    data = record(kind=kind, roster=(-1, -2, 10))
    reader = Reader(io.BytesIO(data), len(data))
    result = read_team(reader, 545, kind, include_roster=False)
    assert result['roster_count'] == 3 and reader.offset == len(data)
    assert 'person_indices' not in result and 'unverified_negative_person_indices' not in result


def test_empty_names_are_serialized_empty_and_roster_is_empty():
    data = record(roster=())
    result = read_team(Reader(io.BytesIO(data), len(data)), 545, 10)
    assert result['name'] == result['short_name'] == ''
    assert result['roster_count'] == 0 and result['person_indices'] == []


@pytest.mark.parametrize('team_type', [-128, -1, 100, 127])
@pytest.mark.parametrize('owner_kind', [0, 1, 2, 255])
def test_native_signed_team_type_and_owner_branch(team_type, owner_kind):
    data = record(team_type=team_type, owner_kind=owner_kind, owner=0xffffffff)
    result = read_team(Reader(io.BytesIO(data), len(data)), 545, 10)
    assert result['team_type_code'] == team_type
    assert result['owner_kind'] == ('club' if owner_kind == 0 else 'national')
    assert result['owner_index'] is None


def test_only_proved_null_sentinels_become_null():
    data = record(owner=0xfffffffe, roster=(-1, -2, -2147483648, 0, 2147483647))
    result = read_team(Reader(io.BytesIO(data), len(data)), 545, 10)
    assert result['owner_index'] == 0xfffffffe
    assert result['owner_index_state'] == 'unverified_negative_word'
    assert result['person_indices'] == [None, -2, -2147483648, 0, 2147483647]
    assert result['unverified_negative_person_indices'] == [
        {'native_slot': 1, 'raw_word': -2}, {'native_slot': 2, 'raw_word': -2147483648},
    ]


@pytest.mark.parametrize('count', [-128, -1, 0, 1, 127])
def test_national_signed_population_branch(count):
    data = record(kind=11, national_count=count, owner_kind=1)
    reader = Reader(io.BytesIO(data), len(data))
    assert read_team(reader, 545, 11)['owner_kind'] == 'national'
    assert reader.offset == len(data)


@pytest.mark.parametrize('kind', [10, 11])
def test_every_truncated_record_fails(kind):
    data = record(kind=kind, national_count=2, name='Équipe', short_name='É')
    for end in range(len(data)):
        with pytest.raises(ValueError):
            read_team(Reader(io.BytesIO(data[:end]), end), 545, kind)


@pytest.mark.parametrize('ordinal,kind,include', [(True, 10, True), (-1, 10, True),
    (2000000, 10, True), (0, True, True), (0, 0, True), (0, 12, True), (0, 10, 1)])
def test_invalid_contract_rejects_before_reading(ordinal, kind, include):
    reader = Reader(io.BytesIO(b''), 0)
    with pytest.raises(ValueError):
        read_team(reader, ordinal, kind, include_roster=include)
    assert reader.offset == 0


def test_wrong_ordinal_and_name_bound():
    data = record(ordinal=1)
    with pytest.raises(ValueError, match='ordinal'):
        read_team(Reader(io.BytesIO(data), len(data)), 545, 10)
    data = record(name='x' * 8193)
    with pytest.raises(ValueError, match='budget'):
        read_team(Reader(io.BytesIO(data), len(data)), 545, 10)


def test_full_production_compressed_stream_multiple_records():
    first = record(roster=(10, 9, 10))
    second = record(kind=11, ordinal=546, national_count=1, owner_kind=1, owner=7,
                    name='National team', roster=(32,))
    raw = first + second + b'FOLLOWING'
    library = _library()
    library.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                    ctypes.c_size_t, ctypes.c_int]
    library.ZSTD_compress.restype = ctypes.c_size_t
    output = ctypes.create_string_buffer(len(raw) + 1024)
    size = library.ZSTD_compress(output, len(output), raw, len(raw), 1)
    assert not library.ZSTD_isError(size)
    packed = output.raw[:size]
    component = SimpleNamespace(start=0, compressed_size=size, uncompressed_size=len(raw))
    with open_component(io.BytesIO(bytes(26) + packed), component) as reader:
        assert read_team(reader, 545, 10)['person_indices'] == [10, 9, 10]
        assert read_team(reader, 546, 11)['owner_index'] == 7
        assert reader.take(9) == b'FOLLOWING'


@pytest.mark.parametrize('kind', [10, 11])
@pytest.mark.parametrize('include_roster', [False, True])
def test_matched_slots_preserve_duplicates_and_original_positions(kind, include_roster):
    roster = (32, -1, 10, 32, -2, 9, 32, 10)
    data = record(kind=kind, roster=roster)
    reader = Reader(io.BytesIO(data + b'NEXT'), len(data) + 4)
    result = read_team(reader, 545, kind, include_roster=include_roster,
                       match_person_indices=frozenset({10, 32}))
    assert result['matched_person_slots'] == [
        {'slot_index': 0, 'person_index': 32},
        {'slot_index': 2, 'person_index': 10},
        {'slot_index': 3, 'person_index': 32},
        {'slot_index': 6, 'person_index': 32},
        {'slot_index': 7, 'person_index': 10},
    ]
    assert result['roster_count'] == len(roster)
    if include_roster:
        assert result['person_indices'] == [32, None, 10, 32, -2, 9, 32, 10]
        assert result['unverified_negative_person_indices'] == [
            {'native_slot': 4, 'raw_word': -2}]
    else:
        assert 'person_indices' not in result
        assert 'unverified_negative_person_indices' not in result
    assert reader.offset == len(data) and reader.take(4) == b'NEXT'


def test_negative_roster_words_never_become_matching_candidates():
    data = record(roster=(-1, -2, -2147483648, 0, 2147483647, -1))
    result = read_team(Reader(io.BytesIO(data), len(data)), 545, 10,
                       include_roster=False,
                       match_person_indices=frozenset({-1, -2, -2147483648, 0, 2147483647}))
    assert result['matched_person_slots'] == [
        {'slot_index': 3, 'person_index': 0},
        {'slot_index': 4, 'person_index': 2147483647},
    ]


@pytest.mark.parametrize('requested', [frozenset(), frozenset({12345})])
@pytest.mark.parametrize('roster', [(), (-1, -2, 10, 10)])
def test_empty_and_unmatched_projection_has_no_full_roster(requested, roster):
    data = record(roster=roster)
    result = read_team(Reader(io.BytesIO(data), len(data)), 545, 10,
                       include_roster=False, match_person_indices=requested)
    assert result['matched_person_slots'] == []
    assert 'person_indices' not in result
    assert 'unverified_negative_person_indices' not in result


@pytest.mark.parametrize('include_roster', [False, True])
def test_match_projection_iterates_the_native_roster_once(monkeypatch, include_roster):
    data = record(roster=(10, 20, 10))
    original = saved_team_records.struct.iter_unpack
    calls, iterations = [], []

    def unpack(format, raw):
        calls.append((format, len(raw)))
        for index, value in enumerate(original(format, raw)):
            iterations.append(index)
            yield value

    monkeypatch.setattr(saved_team_records.struct, 'iter_unpack', unpack)
    result = read_team(Reader(io.BytesIO(data), len(data)), 545, 10,
                       include_roster=include_roster,
                       match_person_indices=frozenset({10}))
    assert calls == [('<i', 12)] and iterations == [0, 1, 2]
    assert result['matched_person_slots'] == [
        {'slot_index': 0, 'person_index': 10}, {'slot_index': 2, 'person_index': 10}]


def test_maximum_unmatched_roster_only_projects_summary_and_empty_matches():
    data = record(roster=(10,) * 65535)
    result = read_team(Reader(io.BytesIO(data), len(data)), 545, 10,
                       include_roster=False, match_person_indices=frozenset({11}))
    assert result['roster_count'] == 65535 and result['matched_person_slots'] == []
    assert 'person_indices' not in result
    assert 'unverified_negative_person_indices' not in result


@pytest.mark.parametrize('kind', [10, 11])
def test_matched_projection_still_validates_every_trailing_byte(kind):
    data = record(kind=kind, roster=(10, -1, 10), name='Équipe', short_name='É')
    for end in range(len(data)):
        with pytest.raises(ValueError):
            read_team(Reader(io.BytesIO(data[:end]), end), 545, kind,
                      include_roster=False, match_person_indices=frozenset({10}))
    corrupt = data[:-12] + struct.pack('<III', 546, 688, 12)
    with pytest.raises(ValueError, match='ordinal'):
        read_team(Reader(io.BytesIO(corrupt), len(corrupt)), 545, kind,
                  include_roster=False, match_person_indices=frozenset({999}))


@pytest.mark.parametrize('requested', [set(), [], (), {10}, True, 10, '10'])
def test_match_projection_type_rejects_before_consumption(requested):
    reader = Reader(io.BytesIO(b''), 0)
    with pytest.raises(ValueError, match='match selection'):
        read_team(reader, 545, 10, match_person_indices=requested)
    assert reader.offset == 0


def test_explicit_none_keeps_default_output_identical():
    data = record(roster=(10, -1, -2, 10))
    implicit = read_team(Reader(io.BytesIO(data), len(data)), 545, 10)
    explicit = read_team(Reader(io.BytesIO(data), len(data)), 545, 10,
                         include_roster=True, match_person_indices=None)
    assert list(implicit.items()) == list(explicit.items())
    assert 'matched_person_slots' not in implicit
