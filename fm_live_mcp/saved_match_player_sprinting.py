"""Official per-fixture Sprints count; no intensity threshold or effort inference."""
from . import saved_match_statistics_wire as wire


def decode_player_sprinting(child: bytes) -> dict[str, int]:
    if not isinstance(child, bytes):
        raise ValueError('Stored sprint statistics require a complete bytes child')
    parsed = wire.player(child, 0, version=60, stream_bit1=True)
    if parsed['end'] != len(child):
        raise ValueError('Player sprint child extent mismatch')
    delta = 4 if parsed['reference']['tag'] < 2 else 0
    return {'sprints': child[190 + delta]}


def sprinting_field_registry():
    return {'sprints': {
        'official_property_label': 'Sprints',
        'native_property_key': '0x7a4b3753',
        'native_offset': '0xf5',
        'wire_offset_u32_person': 190, 'wire_offset_u64_person': 194,
        'unit': 'count', 'encoding': 'unsigned byte',
        'consumer_load_rva': '0x4ad1b18', 'native_property_case_rva': '0x266ccc',
        'exporter_rva': '0x2054f0', 'native_wire_rva': '0x4ad2e3c',
        'semantic_proof': 'Official Sprints registration, native unsigned-byte getter/exporter and version60 wire block; exact per-match table binds Sprints to an unformatted integer cell',
        'ui_cell_asset_guid': 'b32a1a70a1488dc4a9a7248c0eb61eb5',
        'scope': 'Stored Sprints count for one retained fixture/player row. Values 0..255 are preserved; the getter has no 255 sentinel. Zero is a stored count, not proof of participation. Preserve separately proved unused-substitute and null-minute states. No speed/intensity threshold, sprint duration, effort, high-intensity distance or playback-prefix inference.',
        'independent_serialized_team_oracle': False,
        'missing_policy': 'Missing source or player row is unavailable, never zero; invalid or incomplete typed children reject the capture.',
    }}


NATIVE_SPANS = ((2518220, b'i\xea\x86RiI\xafr\x1f\x01\tk\xe1#\x00T\x8f\xab!\x95\xe1\x03\x00\xaa\xfd\x00\x00\x14'), (78453528, b'\x00\xd4C9\xc0\x03_\xd6'), (2118896, b'\xe0\x03\x17\xaa\x891#\x95\xe1\x03\x00\xaa\xe0#\x00\x91p\xfa\x07\x95\xe0c\x00\x91\xe2#\x00\x91a\xea\x86RaI\xafrt\xc7\x07\x95'), (78458320, b'\xe9#@\xf96\xb1\x03\x91\x88\x00\x80R\xf6\xa3\x05\xa94\xc1\x03\x91\xf47\x00\xf9\xe0C\x01\x91\xd8\x99\xe2\x97'), (78458428, b'\xc8\x00\x80R\xf4\xa3\x05\xa9\xf37\x00\xf9\xe0C\x01\x91\xe8#@\xf9\x01\x91\x00\x91\x9e\x06\xe2\x97'))


def verify_native(read, base):
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError('Unsupported native Sprints mapping')
