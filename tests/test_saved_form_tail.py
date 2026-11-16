import json
import struct
from pathlib import Path

import pytest

from fm_live_mcp.saved_form_tail import read_tail


def row151():
    return b'\2' + bytes(47) + b'\7' + bytes(19) + b'\0'


def row155(nested=0):
    return (b'\1' + bytes(4) + b'\0' + bytes(4) + b'\0' + bytes(4) +
            bytes(6) + struct.pack('<I', nested) + (b'\1' + bytes(10))*nested)


def test_absent_empty_and_absolute_bounds():
    raw = b'\0\0'
    r = read_tail(b'prefix'+raw+b'excluded', 6, 8)
    assert r['state'] == 'complete' and r['end'] == 8
    assert r['siblings_complete'] is True
    assert [s['present'] for s in r['siblings']] == [False, False]
    raw = b'\1'+bytes(4)+b'\1'+bytes(2)
    r = read_tail(raw, 0, len(raw))
    assert [s['count'] for s in r['siblings']] == [0, 0]
    assert r['end'] == len(raw)


def test_positive_and_every_truncation():
    raw = b'\1'+struct.pack('<I', 2)+row151()*2+b'\1'+struct.pack('<h', 2)+row155(2)+row155(1)
    r = read_tail(raw, 0, len(raw))
    assert r['state'] == 'complete' and r['end'] == len(raw)
    assert r['siblings'][1]['nested_item_count'] == 3
    for limit in range(len(raw)):
        with pytest.raises(ValueError):
            read_tail(raw, 0, limit)


def test_narrow_unknown_branches():
    raw = bytearray(b'\1'+struct.pack('<I', 1)+row151()+b'\0')
    for offset, value in [(5, 3), (53, 8), (73, 1)]:
        changed = raw.copy(); changed[offset] = value
        r = read_tail(changed, 0, len(changed))
        assert r['state'] == 'stopped' and r['end'] == offset
        assert r['siblings_complete'] is False
    raw = bytearray(b'\0\1'+struct.pack('<h', 1)+row155())
    for offset in (4, 9, 14):
        changed = raw.copy(); changed[offset] = 2
        r = read_tail(changed, 0, len(changed))
        assert r['state'] == 'stopped' and r['end'] == offset
    for marker in (2, 255):
        assert read_tail(bytes((marker,)), 0, 1)['state'] == 'stopped'


def test_invalid_budgets_context_and_bounds():
    for raw in (b'\1'+struct.pack('<I', 4097), b'\0\1'+struct.pack('<h', -1),
                b'\0\1'+struct.pack('<h', 4097)):
        with pytest.raises(ValueError):read_tail(raw, 0, len(raw))
    oversized = b'\0\1'+struct.pack('<h', 1)+row155()[:-4]+struct.pack('<I', 32769)
    with pytest.raises(ValueError):read_tail(oversized, 0, len(oversized))
    with pytest.raises(ValueError):read_tail(b'\0\0', 0, 2, reference_profile='guessed')
    with pytest.raises(ValueError):read_tail(b'\0\0', 0, 2, source_major=4000)
    for start, limit in [(-1, 2), (0, 3), (2, 1)]:
        with pytest.raises(ValueError):read_tail(b'\0\0', start, limit)


def test_all28_actual_sibling_seams():
    x = json.loads((Path(__file__).parent/'fixtures/saved_form_tail.json').read_text())
    assert len(x['rows']) == 28
    for case in x['rows']:
        raw = bytes.fromhex(case['raw_hex'])
        out = read_tail(raw, 0, len(raw))
        assert out['state'] == 'complete', case['ordinal']
        assert out['end'] + case['source_start'] == case['source_end']
        # Neither a larger backing buffer nor an unrelated suffix expands bounds.
        assert read_tail(raw+b'excluded', 0, len(raw))['end'] == len(raw)
        with pytest.raises(ValueError):read_tail(raw, 0, len(raw)-1)
