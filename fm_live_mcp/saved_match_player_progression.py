"""Official FM progressive-pass count from a boundary-checked retained player.

No native distance/angle threshold, final-third entry, carry, location or
played-role interpretation is asserted by this aggregate.
"""


def decode_player_progression(child: bytes) -> dict[str, int]:
    """Read the unsigned count in the verified parent-version60 wire layout."""
    if not isinstance(child, bytes) or not child:
        raise ValueError('Progressive passes require a stored player child')
    delta = 0 if child[0] >= 2 else 4
    if len(child) < 187 + delta:
        raise ValueError('Truncated stored player progressive passes')
    return {'progressive_passes': child[186 + delta]}


def progression_field_registry() -> dict[str, dict[str, object]]:
    return {'progressive_passes': {
        'wire_offset_u32_person': 186,
        'wire_offset_u64_person': 190,
        'native_offset': '0xf1',
        'official_property_label': 'ProgressivePasses',
        'native_property_key': '0x6161476c',
        'consumer_load_rva': '0x205288',
        'generic_getter_load_rva': '0x266d80',
        'managed_registration_rva': '0xab76b4',
        'unit': 'unsigned byte stored count',
        'semantic_proof': 'Indexed managed label to native individual property getter/exporter and parent-version60 retained wire',
        'scope': 'FM-defined progressive passes; no verified distance/angle threshold, final-third entries, carries, action location or played-role split',
        'independent_serialized_team_oracle': False,
    }}
