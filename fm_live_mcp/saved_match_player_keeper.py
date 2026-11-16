"""Officially named stored save counts; no inferred post-shot expected goals."""
from . import saved_match_statistics_wire as wire

_FIELDS = {
    'saves_held': (0x99, 50, 'SavesHeld', 0x65636333, 0x2052b0),
    'saves_parried': (0x9a, 51, 'SavesParried', 0x577a3158, 0x2052d8),
    'saves_tipped': (0x9b, 52, 'SavesTipped', 0x4d6f4868, 0x205330),
}


def decode_player_keeper(child):
    """Decode a complete default v60 child; participation has separate authority."""
    parsed = wire.player(child, 0, version=60, stream_bit1=True)
    if parsed['end'] != len(child):
        raise ValueError('Player child extent mismatch')
    delta = 4 if parsed['reference']['tag'] < 2 else 0
    values = {name: child[offset + delta] for name, (_, offset, _, _, _) in _FIELDS.items()}
    # Native TotalSaves exporter sums the three bytes and masks to an unsigned byte.
    values['total_saves'] = sum(values.values()) & 255
    return values


def field_registry():
    limits = ('Stored save count; zero does not establish participation. '
              'No post-shot expected goals, shot difficulty, save quality or causal attribution.')
    fields = {name: {'native_offset': hex(native), 'wire_offset_u32_person': offset,
                     'wire_offset_u64_person': offset + 4, 'width': 1,
                     'encoding': 'unsigned byte', 'frontend_literal': label,
                     'property_key': hex(key), 'native_load_rva': hex(rva),
                     'semantic_state': 'official_frontend_property_to_native_player_exporter_and_wire',
                     'limits': limits}
              for name, (native, offset, label, key, rva) in _FIELDS.items()}
    fields['total_saves'] = {'frontend_literal': 'TotalSaves', 'property_key': '0x45553965',
                             'native_expression_rva': '0x205734',
                             'native_expression': '(saves_held+saves_parried+saves_tipped)&255',
                             'semantic_state': 'official_frontend_property_to_native_player_exporter_and_wire',
                             'limits': limits}
    return fields
