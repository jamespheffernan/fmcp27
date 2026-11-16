"""Source geometry checks, without treating a prefix as a complete PERSON."""
import struct

import pytest

from fm_live_mcp.saved_player_wire_prefix import prefix_probe


# Checked Calum Macdonald candidate: absolute tag96690219, original ordinal1512.
# Native/current-writer proof lives in B34/B36/B43; this fixture is no start oracle.
CALUM = bytes.fromhex(
    '021c1167127c085e0078005e021102767900ffffffffffc6040000000000000101140e'
    '0101010101010101011202312c2331273c313918402c050f0f050a0f3b380f410f3738'
    '642323373b3c20050a0539272f343a311e2336464841352d14473d2d3c3eb034000008'
    '9732ee0701006c07e4255700bc1b0000000000ff627802b400022aafa1bd100c000000'
    '010100ff000000ffff00ff00ffffffff0c07189c2324241b04fbd801020204057503c4'
    '58ed07caff030001000e0d10011405c458ed070405b801bf7cee074c00020002000201'
    '12011405c47cee07000000000000000002000000ff030009780000160000006f00ff17'
    '01000000000000070500fdff0001006c070001006c0701006c07ff01'
)


def minimal(*, ring=b'', measurement=b'\x02\0\0\0', history=b'\0', typed=b'\0', pairs=0):
    return (b'\x02' + bytes(126) + measurement + bytes(5) + struct.pack('<I', len(ring)) + ring +
            bytes(4) + b'\x0c\x07' + bytes(9) + history + typed +
            struct.pack('<i', pairs) + bytes(max(pairs, 0) * 2) + bytes(3) + b'\x02' + bytes(46))


def test_calum_source_control():
    out = prefix_probe(CALUM, 0, len(CALUM))
    assert len(CALUM) == 273
    assert out['end'] == 273 and out['state'] == 'typed_prefix_stopped'
    assert out['counts'] == {'ring': 12, 'position_history': 2, 'pairs': 0}
    assert out['next_native_reader'] == '0x43836A4'
    assert out['complete_person'] is False
    assert out['native_loader_acceptance'] is False
    assert out['opaque_values_used_as_validation'] is False


def test_offset_coordinate_and_exclusive_limit():
    out = prefix_probe(b'prefix' + CALUM + b'excluded', 6, 6 + len(CALUM))
    assert out['start'] == 6 and out['end'] == 279
    assert out['validated_markers'][0]['offset'] == 6


@pytest.mark.parametrize('ring', [b'', b'\xff', bytes(range(12))])
@pytest.mark.parametrize('measurement', [b'\0' + bytes(8), b'\x01' + bytes(8),
                                         b'\x02' + bytes(3), b'\xff' + bytes(3)])
def test_supported_ring_and_measurement_geometry(ring, measurement):
    raw = minimal(ring=ring, measurement=measurement)
    out = prefix_probe(raw, 0, len(raw))
    assert out['end'] == len(raw) and out['counts']['ring'] == len(ring)


def test_opaque_values_are_not_validation():
    raw = bytearray(minimal())
    raw[1:127] = b'\xff' * 126
    out = prefix_probe(raw, 0, len(raw))
    assert out['end'] == len(raw)


@pytest.mark.parametrize('start', range(1, len(CALUM)))
def test_shifted_starts_reject(start):
    with pytest.raises(ValueError):
        prefix_probe(CALUM, start, len(CALUM))


@pytest.mark.parametrize('limit', range(len(CALUM)))
def test_every_truncated_bound_rejects(limit):
    with pytest.raises(ValueError):
        prefix_probe(CALUM, 0, limit)


@pytest.mark.parametrize('bad', [13, 255, 2**32 - 1])
def test_ring_count_corruption_rejects(bad):
    raw = bytearray(minimal())
    struct.pack_into('<I', raw, 136, bad)
    with pytest.raises(ValueError, match='capacity12'):
        prefix_probe(raw, 0, len(raw))


@pytest.mark.parametrize('kind', ['ACTUAL_PLAYER_tag', '17F1BB8_composite_version',
                                  '17EDD50_parameter_version', '15778F4_history_version',
                                  '1576B28_position_row_version', '138E158_fixed_version'])
def test_meaningful_writer_markers_reject_changes(kind):
    out = prefix_probe(CALUM, 0, len(CALUM))
    offset = next(x['offset'] for x in out['validated_markers'] if x['kind'] == kind)
    raw = bytearray(CALUM)
    raw[offset] ^= 0x80
    with pytest.raises(ValueError):
        prefix_probe(raw, 0, len(raw))


@pytest.mark.parametrize('kind', ['position_history_presence', 'typed_vector_presence',
                                  'fixed_28_presence', 'individual_training_presence',
                                  'individual_oop_training_presence'])
def test_nonboolean_presence_rejects(kind):
    offset = next(x['offset'] for x in prefix_probe(CALUM, 0, len(CALUM))['validated_markers']
                  if x['kind'] == kind)
    raw = bytearray(CALUM)
    raw[offset] = 2
    with pytest.raises(ValueError, match='presence'):
        prefix_probe(raw, 0, len(raw))


def test_positive_typed_vector_stops_before_unparsed_child():
    raw = minimal(typed=b'\x01')
    out = prefix_probe(raw, 0, len(raw))
    assert out['stop_reason'] == 'positive_typed_vector_unparsed'
    assert out['end'] < len(raw)
    assert out['next_native_reader'] == '0x17F090C'


def test_pair_negative_rejects_and_budget_is_explicit():
    raw = minimal(pairs=-1)
    with pytest.raises(ValueError, match='Negative pair'):
        prefix_probe(raw, 0, len(raw))
    raw = minimal(pairs=4097)
    out = prefix_probe(raw, 0, len(raw))
    assert out['stop_reason'] == 'pair_count_exceeds_offline_work_budget'
    assert out['counts']['pairs'] == 4097


@pytest.mark.parametrize('start,limit', [(True, 1), (0, True), (-1, 1), (1, 1), (0, 10000)])
def test_bad_spans(start, limit):
    with pytest.raises(ValueError):
        prefix_probe(CALUM, start, limit)
