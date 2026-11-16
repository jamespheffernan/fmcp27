"""Officially named individual crossing counters from retained player rows.

B143 indexed managed property labels bind native keys to player getters.
Open-play values are sums of two unsigned byte buckets, without byte wrapping.
"""

_FIELDS = {
    'crosses_attempted': ((89,), ('0xb5',), 'CrossAttempts', '0x686a5a65', '0x204f18'),
    'crosses_completed': ((90,), ('0xb6',), 'CrossesCompleted', '0x20726763', '0x204f80'),
    'open_play_crosses_attempted': ((159, 164), ('0xdf', '0xe0'), 'OpenPlayCrossesAttempted', '0x35734e6f', '0x2055e8'),
    'open_play_crosses_completed': ((165, 166), ('0xe1', '0xe2'), 'OpenPlayCrossesCompleted', '0x58465367', '0x205618'),
}


def decode_player_crosses(child: bytes) -> dict[str, int]:
    """Decode counters from a boundary-checked GAME_MATCH_PLAYER_STATS60 child."""
    if not isinstance(child, bytes) or not child:
        raise ValueError('Crossing counters require a stored player child')
    delta = 0 if child[0] >= 2 else 4
    if len(child) < 167 + delta:
        raise ValueError('Truncated stored player crossing counters')
    return {
        name: sum(child[offset + delta] for offset in offsets)
        for name, (offsets, _, _, _, _) in _FIELDS.items()
    }


def cross_field_registry() -> dict[str, dict[str, object]]:
    return {
        name: {
            'wire_offsets_u32_person': list(offsets),
            'wire_offsets_u64_person': [offset + 4 for offset in offsets],
            'native_offsets': list(native),
            'official_property_label': label,
            'native_property_key': key,
            'consumer_load_rva': consumer,
            'unit': 'count; unsigned byte buckets summed without wrapping',
            'semantic_proof': 'B143 indexed managed label to property key to native individual getter',
            'aggregation': 'sum of native buckets' if len(offsets) > 1 else 'single native byte',
            'scope': 'Individual crossing attempts/completions; no receiver, flank, aerial outcome or match-completion inference',
            'independent_serialized_team_oracle': False,
        }
        for name, (offsets, native, label, key, consumer) in _FIELDS.items()
    }
