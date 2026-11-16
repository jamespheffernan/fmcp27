import io
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp.saved_component_stream import Reader
from fm_live_mcp.saved_player_tail import read_tail


def decode(raw, **kwargs):
    return read_tail(Reader(io.BytesIO(raw), len(raw)), **kwargs)


def minimal(scale=128):
    return b'\0\0\0\0' + bytes(8 + 14) + struct.pack('<I', 0) + bytes(8) + bytes([scale]) + bytes(7)


def test_absent_tail_and_scale():
    for scale in (0, 127, 128, 255):
        raw = minimal(scale)
        result = decode(raw)
        assert result['end'] == result['actual_person_start'] == len(raw)
        assert result['scale_byte'] == scale
        assert result['stored_attribute_scale_flag_bit7'] == bool(scale & 128)


def test_every_truncation():
    raw = minimal()
    for stop in range(len(raw)):
        with pytest.raises(ValueError):
            decode(raw[:stop])


def test_fail_closed_versions_profiles_and_budget():
    for kwargs in ({'source_major': True}, {'minor': 8}, {'reference_mode': 'raw32'},
                   {'direct_references': False}):
        with pytest.raises(ValueError):
            decode(minimal(), **kwargs)
    for raw in (b'\x02', b'\x01\xff', b'\0\x01\0\0', b'\0\0\x01\x05',
                b'\0\0\0\0' + bytes(22) + struct.pack('<I', 4097)):
        with pytest.raises(ValueError):
            decode(raw)


def test_positive_optional_families():
    e0 = b'\x01\x04' + bytes(57)
    child118 = (b'\x01' + struct.pack('<h', 31) + bytes(2) + struct.pack('<I', 1)
                + bytes(24) + struct.pack('<I', 1) + b'\x02' + bytes(7)
                + bytes(43) + b'\x02' + bytes(13) + b'\x01' + bytes(17)
                + struct.pack('<hI', 2, 1) + bytes(14) + bytes(21))
    polymorphic = b'\x02\xff\0' + bytes(4)
    f8 = b'\x01\x02\x04' + struct.pack('<I', 1) + bytes(19)
    f8 += (struct.pack('<I', 1) + bytes(5)) * 6 + bytes(5)
    raw = e0 + child118 + polymorphic + f8 + minimal()[4:]
    assert decode(raw)['end'] == len(raw)
    for stop in range(len(raw)):
        with pytest.raises(ValueError):
            decode(raw[:stop])


def test_checked_corpus():
    root = Path(__file__).resolve().parents[1]
    batches = root / 'evidence/batches'
    path = batches / 'saved-person-population-42/roster_identity/main-game-db.bin'
    if not path.exists():
        pytest.skip('Pinned research corpus unavailable')
    roster = json.loads((batches / 'saved-person-population-42/roster_boundaries/full-roster-result.json').read_text())
    adjacent = json.loads((batches / 'saved-person-population-42/regular_player/adjacent-result.json').read_text())
    cases = []
    for row in roster['rows']:
        attempt = next(a for a in row['attempts'] if a.get('state') == 'full_source_profile_record_decoded')
        tail = attempt['parts']['remaining_tail']
        cases.append((attempt['body_start'] + tail['start'], attempt['body_start'] + tail['end'], tail))
    for row in adjacent['rows']:
        parsed = row['parsed']
        tail = parsed['parts']['remaining_tail']
        origin = row['body_absolute'] - parsed['start']
        cases.append((origin + tail['start'], origin + tail['end'], tail))
    import hashlib
    with path.open('rb') as handle:
        assert hashlib.file_digest(handle, 'sha256').hexdigest() == '4d563471a32d61d36faf78f1302597cb82e9e8c56ca870234d6ec797c62d58e0'
        for start, end, tail in cases:
            handle.seek(start)
            raw = handle.read(end - start)
            result = decode(raw)
            assert result['end'] == end - start
            assert result['scale_byte'] == bytes.fromhex(tail['parts']['player270_277_raw'])[0]
    assert len(cases) == 30
