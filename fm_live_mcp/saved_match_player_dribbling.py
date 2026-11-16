"""Official DribblesMade aggregate; no attempt denominator or carry distance."""
from . import saved_match_statistics_wire as wire

def decode_player_dribbling(child):
    parsed = wire.player(child, 0, version=60, stream_bit1=True)
    if parsed['end'] != len(child):
        raise ValueError('Player child extent mismatch')
    delta = 4 if parsed['reference']['tag'] < 2 else 0
    return {'dribbles_made': child[58 + delta]}

def dribbling_field_registry():
    return {'dribbles_made': {
        'official_property_label': 'DribblesMade',
        'native_property_key': '0x4d417476',
        'native_offset': '0xa1',
        'wire_offset_u32_person': 58, 'wire_offset_u64_person': 62,
        'consumer_load_rva': '0x266e10', 'exporter_load_rva': '0x205000',
        'native_writer_rva': '0x493c600', 'native_event_kind': 13,
        'unit': 'unsigned byte stored count',
        'semantic_proof': 'Official indexed managed property registration, native individual exporter/getter and native wire block; kind13 producer independently maps to CBE34',
        'scope': 'FM DribblesMade count. No dribble-attempt count, success percentage, progressive carry, distance, action location or tactical cause is established.',
        'independent_serialized_team_oracle': False,
    }}

NATIVE_SPANS = ((2117632, b'\xe1\x86B9\xe0#\x00\x91\xbb\xfb\x07\x95\xe0c\x00\x91\xe2#\x00\x91\xc1\x8e\x8eR!\xa8\xa9r\xb2\xc8\x07\x95'), (2518528, b'\xc9\x8e\x8eR)\xa8\xa9r\x1f\x01\tkA\x1a\x00T\x01\x84B9\xc3\x00\x00\x14'), (76793048, b'?u\x00qH\x1e\x01TKV\x00\xb0k\xb1\x0b\x91\x8c\x00\x00\x10myix\x8c\t\r\x8b\x80\x01\x1f\xd6'), (76793340, b'W\x15\x01\xb4\xe8\x86B9\x08\x05\x00\x11\xe8\x86\x029\xa6\x08\x00\x14'), (78457428, b'\x88\x01\x80R\xe9#@\xf93q\x02\x91\xe8O\x06\xa9\xe0C\x01\x91\xb9\x9a\xe2\x97\xe9#@\xf9'), (78457504, b'\xe8\x01\x80R\xf4\xa3\x05\xa9\xe8#@\xf9\x14\xb9\x02\x91\xf47\x00\xf9\xe0C\x01\x91\xa5\x9a\xe2\x97'), (76099972, b'H\x04\x80R\xd8\xff\xff\x17'), (88101638, b'A\x00'), (88089552, b','))

def verify_native(read, base):
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError('Unsupported native DribblesMade mapping')
