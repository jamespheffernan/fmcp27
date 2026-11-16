"""Official OpenPlayFinalThirdPasses count; no final-third entry interpretation."""
import struct
from . import saved_match_statistics_wire as wire


def decode_player_final_third(child: bytes) -> dict[str, int]:
    if not isinstance(child, bytes):
        raise ValueError('Final-third pass statistics require a complete bytes child')
    parsed = wire.player(child, 0, version=60, stream_bit1=True)
    if parsed['end'] != len(child):
        raise ValueError('Final-third pass child extent mismatch')
    delta = 4 if parsed['reference']['tag'] < 2 else 0
    value = struct.unpack_from('<h', child, 209 + delta)[0]
    if value < 0:
        raise ValueError('Invalid negative native final-third pass counter')
    return {'open_play_final_third_passes': value}


def final_third_field_registry():
    return {'open_play_final_third_passes': {
        'official_property_label': 'OpenPlayFinalThirdPasses',
        'native_property_key': '0x5a71314f',
        'native_offset': '0x10a',
        'wire_offset_u32_person': 209, 'wire_offset_u64_person': 213,
        'unit': 'count', 'encoding': 'signed int16, nonnegative counter profile',
        'consumer_load_rva': '0x266f24', 'exporter_load_rva': '0x205ac4',
        'native_wire_rva': '0x4ad2efc', 'native_producer_rva': '0x493f690',
        'semantic_proof': 'Official property registration/getter/exporter and native version60 wire; successful pass, stored open-play gate and native third predicate select the counter increment; per-match UI binds the integer directly',
        'scope': 'Official OpenPlayFinalThirdPasses count for one retained fixture/player row. The native into-versus-within coordinate interpretation remains unproved: not an entry count. Separate from progressive passes, progressive carries, dribbles and action locations.',
        'missing_policy': 'Missing source or player row is unavailable, never zero. The signed getter has no special -1 sentinel; negative values reject the capture without clamping.',
        'independent_serialized_team_oracle': False,
    }}


NATIVE_SPANS = ((2518368, b'\xe9)\x86R)N\xabr\x1f\x01\tk\xc0\r\x00T'), (2518820, b'\x01\x14\xc2y\xe0\x03\x00\x91\xe5s\x06\x95~\x00\x00\x14'), (2120388, b'\xe1\x16\xc2y\xe0#\x00\x91\xfd\xf8\x07\x95\xe0c\x00\x91\xe2#\x00\x91\xe1)\x86R!N\xabr\x01\xc6\x07\x95'), (78458472, b'\xf6#@\xf9\xd3\x02\x04\x91\xe87@\xf9\x1f\x01\x13\xeb\x00\x1c\x00T\xe0C\x01\x91\xb3\x99\xe2\x97\xf3/\x00\xf9H\x00\x80R\xd4\n\x04\x91\xe8S\x06\xa9\xe0C\x01\x91\xad\x99\xe2\x97\xd3\x1a\x04\x91H\x00\x80R\xf3\xa3\x05\xa9\xd5"\x04\x91\xf57\x00\xf9\xe0C\x01\x91\xa6\x99\xe2\x97H\x00\x80R\xf4\xa3\x05\xa9\xd4\x12\x04\x91\xf47\x00\xf9\xe0C\x01\x91\xa0\x99\xe2\x97H\x00\x80R\xf5\xa3\x05\xa9\xd5*\x04\x91\xf57\x00\xf9\xe0C\x01\x91\x9a\x99\xe2\x97H\x00\x80R\xf4\xa3\x05\xa9\xf37\x00\xf9\xe0C\x01\x91\x95\x99\xe2\x97H\x00\x80R\xf5\xa3\x05\xa9\xc82\x04\x91\xe87\x00\xf9\xe0C\x01\x91\xc1\x82\x00\x91n\x06\xe2\x97'), (76805556, b'\x08\x05@\xf9\x08\xc9@y\tC\x80R\x1f\x01\tj\xf8\x17\x9f\x1a\x02\x00\x00\x14\x18\x00\x80R'), (76805724, b'\xe0\x03\x17\xaa\xe1\x03\x16\xaa\xdbC\x00\x94\x00\x03\x004\x88\x12Cy\x08\x05\x00\x11\x88\x12\x03y\xbf\x06\x00q\xc1\x01\x00T\x88\x1eCy\x08\x05\x00\x11\x88\x1e\x03y\xf8\x01\x006H!\x80R\x89 \x80RjjixJ\x05\x00\x11jj)x\x06\x00\x00\x14\x18\x01\x006H \x80R\x03\x00\x00\x14\xb8\x00\x006\x88 \x80Rijhx)\x05\x00\x11ij(x'))


def verify_native(read, base):
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError('Unsupported native OpenPlayFinalThirdPasses mapping')
