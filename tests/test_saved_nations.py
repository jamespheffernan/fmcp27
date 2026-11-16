"""NATION streaming bodies begin after the caller-consumed subtype byte."""
import io
import struct

import pytest

from fm_live_mcp import saved_nations
from fm_live_mcp.saved_component_stream import Reader, open_component


def wire(raw):
    return Reader(io.BytesIO(raw), len(raw))


def text(value):
    raw = value.encode('utf8')
    return struct.pack('<I', len(raw)) + raw


def body(ordinal=0, *, negative=False, version=2):
    count = -1 if negative else 1
    raw = bytes(4)
    raw += struct.pack('<h', count) + (b'' if negative else bytes(4))
    raw += struct.pack('<i', count) + (b'' if negative else bytes(4))
    raw += struct.pack('<h', count)
    if not negative:
        raw += b'\xff' + b''.join(text(x) for x in ('A', 'é', '', 'x ')) + bytes(20)
    raw += bytes(48) + struct.pack('<i', count)
    if not negative:
        raw += bytes([version]) + bytes(22 + (2 if version >= 2 else 0))
    for width in (12, 14):
        raw += struct.pack('<I', 0 if negative else 1) + (b'' if negative else bytes(width))
    raw += bytes(24) + struct.pack('<b', count) + (b'' if negative else bytes(5))
    for width in (28, 28, 12):
        raw += struct.pack('<i', count) + (b'' if negative else bytes(width))
    return raw + bytes(54) + struct.pack('<III', ordinal, 42, 0xFFFFFFFF)


@pytest.mark.parametrize('version', [0, 1, 2, 255])
def test_complete_opaque_children_leave_next_record_untouched(version):
    raw = body(7, version=version)
    reader = wire(raw + b'next')
    assert saved_nations.skip_nation(reader, 7, 0) is None
    assert reader.offset == len(raw)
    assert reader.take(4) == b'next'


@pytest.mark.parametrize('negative', [False, True])
def test_all_truncations_reject(negative):
    raw = body(negative=negative)
    for end in range(len(raw)):
        with pytest.raises(ValueError):
            saved_nations.skip_nation(wire(raw[:end]), 0, 0)


def test_nonpositive_signed_populations_consume_no_children():
    raw = body(negative=True)
    reader = wire(raw)
    saved_nations.skip_nation(reader, 0, 0)
    assert reader.offset == len(raw)


@pytest.mark.parametrize('secondary', [0, 0xffffffff, 73])
def test_read_identity_preserves_independent_words_and_boundary(secondary):
    raw = body(7)[:-12] + struct.pack('<III', 7, 42, secondary)
    reader = wire(raw + b'NEXT')
    assert saved_nations.read_nation_identity(reader, 7, 0) == {
        'database_index': 7, 'native_id': 42, 'secondary_id': secondary,
    }
    assert reader.take(4) == b'NEXT'


def test_read_identity_rejects_truncation_and_wrong_ordinal():
    raw = body(1, negative=True)
    for end in range(len(raw)):
        with pytest.raises(ValueError):
            saved_nations.read_nation_identity(wire(raw[:end]), 1, 0)
    with pytest.raises(ValueError, match='ordinal mismatch'):
        saved_nations.read_nation_identity(wire(raw), 0, 0)


@pytest.mark.parametrize('ordinal,kind', [(True, 0), (-1, 0), (10000, 0),
                                         (0, True), (0, 1), (0, -1)])
def test_context_rejects_before_read(ordinal, kind):
    with pytest.raises(ValueError):
        saved_nations.skip_nation(wire(b''), ordinal, kind)


def test_stored_ordinal_mismatch_rejects():
    with pytest.raises(ValueError, match='ordinal mismatch'):
        saved_nations.skip_nation(wire(body(1)), 0, 0)


def test_count_text_and_cumulative_budgets_reject(monkeypatch):
    raw = body()
    # +160 follows4B,+130count2B and its4Bbody.
    with pytest.raises(ValueError, match='item budget'):
        saved_nations.skip_nation(wire(raw[:10] + struct.pack('<i', 100001)), 0, 0)
    # First child string begins after4+2+4+4+4+2+1 bytes.
    with pytest.raises(ValueError, match='text'):
        saved_nations.skip_nation(wire(raw[:21] + struct.pack('<I', 8193)), 0, 0)
    monkeypatch.setattr(saved_nations, 'MAX_RECORD_ITEMS', 1)
    with pytest.raises(ValueError, match='record exceeds item'):
        saved_nations.skip_nation(wire(raw), 0, 0)


def test_row_byte_budget_rejects(monkeypatch):
    monkeypatch.setattr(saved_nations, 'MAX_RECORD_BYTES', len(body()) - 1)
    with pytest.raises(ValueError, match='byte budget'):
        saved_nations.skip_nation(wire(body()), 0, 0)


# Independently established B32 full-table boundaries; no evidence module import.
SAVES = [
    ('Cesar Jules - Newcastle (v02).fm', 'ef221d1ec222494e8f3d874dad27a1190e124d2d096d74f17338ca477f8bf5d5', 25656740, 25788862),
    ('Cesar Jules - Newcastle (v03).fm', '1d31d9563e5d6e009aff780c3df7875b5c851d7e4a3e416e5088d8b339b0115f', 25656244, 25788666),
    ('Cesar Jules - Newcastle.fm', '8ff7b7053760d72f9389fbe8ef36b00a46a3a08cb40a477234006df2330d70d3', 25657560, 25789682),
    ('last save overwrite backup.fm', 'f305511fdb53971561a4bed140e05979237d8651ecd28a2dce5844fb48f6a0b7', 25631782, 25764156),
]


@pytest.mark.parametrize('filename,snapshot_id,start,end', SAVES)
def test_actual_four_file_streaming_boundaries(filename, snapshot_id, start, end):
    from fm_live_mcp import snapshot_catalog as catalog
    if not (catalog.DEFAULT_DIRECTORY / filename).is_file():
        pytest.skip('Private pinned save unavailable')
    with catalog.checked_snapshot(filename) as (handle, entries, identity):
        if catalog.snapshot_id(identity) != snapshot_id:
            pytest.skip('Private save changed since the pinned corpus verification')
        entry, = [x for x in entries if x.path.count('/') == 1 and x.path.endswith('/game_db.dat')]
        with open_component(handle, entry) as reader:
            reader.skip(start)
            assert (reader.u32(), reader.u8()) == (251, 0)
            identities = []
            for ordinal in range(251):
                identities.append(saved_nations.read_nation_identity(reader, ordinal, reader.u8()))
            assert identities[0] == {'database_index': 0, 'native_id': 5, 'secondary_id': 5}
            assert identities[139] == {'database_index': 139, 'native_id': 765, 'secondary_id': 765}
            assert identities[189] == {'database_index': 189, 'native_id': 1651, 'secondary_id': 1651}
            assert reader.offset == end - 9
            assert (reader.u32(), reader.u8(), reader.u32()) == (0, 1, 82082540)
            assert reader.offset == end

        # The native-proved first record occupies447 bytes including subtype.
        # Exercise actual bytes, not just the synthetic rich-body fixture.
        with open_component(handle, entry) as reader:
            reader.skip(start + 5)
            raw = reader.take(447)
        assert raw[0] == 0
        first = wire(raw[1:])
        saved_nations.skip_nation(first, 0, raw[0])
        assert first.offset == 446
        for extent in range(446):
            with pytest.raises(ValueError):
                saved_nations.skip_nation(wire(raw[1:1 + extent]), 0, raw[0])
