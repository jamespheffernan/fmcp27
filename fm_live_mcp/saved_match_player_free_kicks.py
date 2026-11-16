"""Named per-match direct-free-kick goal count from retained player bytes."""


def decode_player_free_kicks(child: bytes) -> dict[str, int]:
    if not isinstance(child, bytes) or not child:
        raise ValueError('Direct free-kick goals require a stored player child')
    delta = 0 if child[0] >= 2 else 4
    if len(child) < 159 + delta:
        raise ValueError('Truncated stored player direct free-kick goals')
    return {'direct_free_kick_goals': child[158 + delta]}


def free_kick_field_registry() -> dict[str, dict[str, object]]:
    return {'direct_free_kick_goals': {
        'official_property_label': 'DirectFreeKickGoals',
        'native_property_key': '0x30616977',
        'native_offset': '0xde',
        'wire_offset_u32_person': 158,
        'wire_offset_u64_person': 162,
        'managed_registration_rva': '0xab88a0',
        'consumer_load_rva': '0x2058a8',
        'generic_getter_load_rva': '0x266f1c',
        'unit': 'unsigned byte stored per-player per-match goal count',
        'scope': 'Recorded direct free-kick goals only; no corner or indirect-free-kick origin, open-play classification, attempt linkage or event clock is implied. A count can identify a particular goal only when that player has exactly one total goal and one direct-free-kick goal in this exact fixture.',
        'identity_policy': 'Attribute to a named player only with canonical_source_identity and canonical_person_id, source PERSON word, canonical fixture and side; unresolved identities remain unassigned.',
        'coverage': 'Zero is observed only for a decoded stored player child. Missing fixture/player source remains null, never zero.',
        'semantic_proof': 'Official indexed managed label, native individual getter/exporter and parent-version60 retained D0..DF wire segment; source receipt setpiece-goal-origin-156',
    }}
