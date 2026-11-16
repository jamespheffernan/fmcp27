import json
import struct
from pathlib import Path

import pytest

from fm_live_mcp.saved_form_player import locate_f0


def minimal(*, typed=b'\0', training=b'\0', fixed28=b'\0', oop=b'\0', optional108=b'\0', f0=1):
    return (b'\x02' + bytes(126) + b'\x02' + bytes(3) + bytes(5) +
            bytes(8) + b'\x0c\x07' + bytes(9) + b'\0' + typed + bytes(4) +
            fixed28 + training + oop + b'\x02' + bytes(46) +
            bytes(4) + bytes(12) + optional108 + bytes((f0,)))


def test_present_absent_and_coordinates():
    for marker, state in [(0, 'absent'), (1, 'present')]:
        raw = minimal(f0=marker)
        out = locate_f0(b'prefix' + raw + b'excluded', 6, len(raw) + 6)
        assert out['state'] == state and out['end'] == len(raw) + 6
        assert out['f0_start'] == (out['end'] if marker else None)
        assert out['native_loader_acceptance'] is False
        assert out['complete_person'] is False


def test_positive_children_and_all_truncations():
    # Typed row carries nested property map with one scalar17 value.
    variant = b'\1\x0a' + struct.pack('<I', 1) + bytes(4) + b'\1\x11\xff'
    typed = b'\1\2' + struct.pack('<i', 1) + bytes(6) + variant
    raw = minimal(typed=typed, training=b'\1\3'+bytes(10),
                  fixed28=b'\1'+bytes(7), oop=b'\1'+bytes(13),
                  optional108=b'\1'+bytes(30))
    assert locate_f0(raw, 0, len(raw))['f0_start'] == len(raw)
    for limit in range(len(raw)):
        with pytest.raises(ValueError):
            locate_f0(raw, 0, limit)


def test_unknown_positive_variant_is_gap():
    typed = b'\1\2' + struct.pack('<i', 1) + bytes(6) + b'\1\xff'
    raw = minimal(typed=typed)
    out = locate_f0(raw, 0, len(raw))
    assert out['state'] == 'stopped' and out['f0_start'] is None
    assert out['next_native_reader'] == '0x43FC9B4'
    assert 'Unsupported saved property variant 255' in out['stop_reason']


def test_enclosing_limit_and_marker_corruption():
    raw = minimal()
    with pytest.raises(ValueError):
        locate_f0(raw, 0, len(raw)-1)
    with pytest.raises(ValueError):
        locate_f0(minimal(f0=2), 0, len(raw))
    with pytest.raises(ValueError):
        locate_f0(raw, -1, len(raw))
    with pytest.raises(ValueError):
        locate_f0(raw, 0, len(raw)+1)
    typed = b'\1\2' + struct.pack('<i', -1)
    raw = minimal(typed=typed)
    with pytest.raises(ValueError):
        locate_f0(raw, 0, len(raw))


def test_all_source_roster_and_nonclub_controls():
    receipt = json.loads((Path(__file__).parent/'fixtures/saved_form_player.json').read_text())
    assert len(receipt['rows']) == 30
    for row in receipt['rows']:
        raw = bytes.fromhex(row['raw_hex'])
        out = locate_f0(raw, 0, len(raw))
        assert out['state'] == row['expected_state'], row['label']
        assert (row['source_start'] + out['f0_start'] if out['f0_start'] is not None else None) == row['expected_f0_start'], row['label']
