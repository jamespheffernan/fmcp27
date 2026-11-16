"""Official individual possession and pressure counters.

These retained aggregates do not identify event locations, played roles,
pressure regains or effects of tactical pressing changes.
"""

_FIELDS = {
    'possession_won': (151, '0xd7', 'PossessionWon', '0x42744244', '0x205570'),
    'possession_lost': (152, '0xd8', 'PossessionLost', '0x63417963', '0x205598'),
    'pressures_attempted': (160, '0xec', 'PressuresAttempted', '0x62413643', None),
    'pressures_completed': (161, '0xed', 'PressuresCompleted', '0x77303832', '0x2056e4'),
}


def decode_player_recoveries(child: bytes) -> dict[str, int]:
    """Read counters from an already boundary-checked stored player child."""
    if not isinstance(child, bytes) or not child:
        raise ValueError('Possession counters require a stored player child')
    delta = 0 if child[0] >= 2 else 4
    if len(child) < 162 + delta:
        raise ValueError('Truncated stored player possession counters')
    return {name: child[offset + delta] for name, (offset, _, _, _, _) in _FIELDS.items()}


def recovery_field_registry() -> dict[str, dict[str, object]]:
    fields = {
        name: {
            'wire_offset_u32_person': offset,
            'wire_offset_u64_person': offset + 4,
            'native_offset': native,
            'official_property_label': label,
            'native_property_key': key,
            'consumer_load_rva': consumer,
            'unit': 'unsigned byte stored count',
            'semantic_proof': 'B145 indexed managed label to native individual property getter and wire blocks',
            'scope': 'Native individual aggregate; no event location, role, pressure-regain or tactical causality attribution',
            'independent_serialized_team_oracle': False,
        }
        for name, (offset, native, label, key, consumer) in _FIELDS.items()
    }
    fields['pressures_attempted'].update(
        semantic_proof='QME_STAT_MANAGER named pressures_attempted string maps to statID12, generator result writes native EC; native EC4-byte wire block',
        native_writer_rva='0x49adc34', named_stat_lookup_rva='0x4956450..0x49568d0',
        named_string_binding_rva='0x4ad3ff4', native_stat_id=12,
        supported_individual_property_getter=False)
    for name in ('pressure_completion_percentage_computed', 'pressure_completion_state'):
        fields[name] = {'source': 'arithmetic from both named same-row pressure counters',
            'denominator': 'pressures_attempted', 'numerator': 'pressures_completed',
            'formula': '100 * completed / attempted; zero/missing/inconsistent denominator returns null percentage',
            'scope': 'Native statistical pressure completion only; not possession regains, beaten presses, location, current displayed time or tactical causality'}
    return fields


def pressure_completion_fields(row):
    """Derived rate; missing, zero and byte-counter inconsistency stay distinct."""
    attempted, completed = row.get('pressures_attempted'), row.get('pressures_completed')
    if any(type(value) is not int or value < 0 for value in (attempted, completed)):
        state, value = 'unavailable_missing_pressure_counters', None
    elif completed > attempted:
        state, value = 'unavailable_completed_exceeds_attempted', None
    elif attempted == 0:
        state, value = 'undefined_zero_pressure_attempts', None
    else:
        state, value = 'available', 100.0 * completed / attempted
    return {'pressure_completion_percentage_computed': value, 'pressure_completion_state': state}
