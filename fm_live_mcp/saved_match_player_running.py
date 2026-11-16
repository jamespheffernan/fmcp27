"""Official per-fixture DistanceRan: stored metres, unrelated to tracking length."""
import math
import struct
from . import saved_match_statistics_wire as wire


def decode_player_running(child: bytes) -> dict[str, float]:
    if not isinstance(child, bytes):
        raise ValueError('Stored running statistics require a complete bytes child')
    parsed = wire.player(child, 0, version=60, stream_bit1=True)
    if parsed['end'] != len(child):
        raise ValueError('Player running child extent mismatch')
    delta = 4 if parsed['reference']['tag'] < 2 else 0
    distance = struct.unpack_from('<f', child, 140 + delta)[0]
    if not math.isfinite(distance) or distance < 0:
        raise ValueError('Invalid stored player distance in metres')
    return {'distance_metres': distance}


def running_field_registry():
    return {'distance_metres': {
        'official_property_label': 'DistanceRan',
        'native_property_key': '0x72434e64',
        'native_offset': '0x68',
        'wire_offset_u32_person': 140, 'wire_offset_u64_person': 144,
        'unit': 'metres', 'encoding': 'unscaled IEEE754 float32',
        'consumer_load_rva': '0x4ad1a2c', 'native_property_case_rva': '0x2670c0',
        'native_wire_rva': '0x4ad2d94',
        'semantic_proof': 'Official DistanceRan registration, native stored-float getter and wire reader; exact PlayerMatchRunCell binds the getter output to distance (input in kilometres), after native multiplication by 0.001',
        'unit_proof_asset_guid': '71c9d105dfada174aafe5e3fd1458c1c',
        'scope': 'Stored aggregate for one retained fixture/player row. Zero is stored zero, not proof of participation. Preserve separately proved unused-substitute and null-minute states. No sprint, high-intensity, effort, tracking-length or playback-prefix inference.',
        'independent_serialized_team_oracle': False,
        'missing_policy': 'Missing source or player row is unavailable, never zero; negative/nonfinite values reject the capture.',
    }}


NATIVE_SPANS = ((2518092, b'\x89\xcc\x89RiH\xaer\x1f\x01\tk@#\x00T'), (2519232, b'\x01\x00\x80RZ\xaa!\x95\x08\x00\x00\x14'), (78453292, b'a\x00\x004\x00h@\xbd\xc0\x03_\xd6\x00h@\xbd(A\x00\xb0\x01\xb5O\xbd\x00\x08!\x1e\xc0\x03_\xd6'), (78458236, b'\xe0C\x01\x91\xf3\x99\xe2\x97\x88\x00\x80R\xf8\xa3\x05\xa9\xf97\x00\xf9\xe0C\x01\x91\xe8#@\xf9\x01\xa1\x01\x91\xcc\x06\xe2\x97'), (86994868, b'o\x12\x83:'))


def verify_native(read, base):
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError('Unsupported native DistanceRan mapping')
