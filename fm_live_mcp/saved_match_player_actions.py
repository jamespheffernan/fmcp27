"""Native-named stored player counters, B142 static consumer/wire proof.

Counters are unsigned bytes; expected goals are unscaled native float32.
Values do not establish appearances,
match completion, player identity, or historical runtime factory dispatch.
"""

import math
import struct

# (u32 PERSON wire byte, native object byte, consumer load RVA)
_FIELDS = {
    'shots': (41, 0x90, 0x2F10BA4),
    'shots_on_target': (42, 0x91, 0x2F10C10),
    'passes_attempted': (86, 0xBA, 0x2F109F4),
    'passes_completed': (87, 0xBB, 0x2F10A60),
    'tackles_attempted': (92, 0xC6, 0x2F10ACC),
    'tackles_completed': (93, 0xC7, 0x2F10B38),
    'fouls_committed': (60, 0xA3, 0x2F10C7C),
    'yellow_cards_received': (63, 0xA6, 0x2F10CE8),
    'red_cards_received': (64, 0xA7, 0x2F10D5C),
    'key_passes': (88, 0xBC, 0x2051A8),
    'open_play_key_passes': (176, 0xBD, 0x205520),
    'chances_created': (57, 0xA0, 0x204E78),
}


def decode_player_actions(child: bytes) -> dict[str, int | float]:
    """Decode an already boundary-checked GAME_MATCH_PLAYER_STATS60 child."""
    if not isinstance(child, bytes) or not child:
        raise ValueError('Player action counters require a stored player child')
    delta = 0 if child[0] >= 2 else 4
    if len(child) < 195 + delta:
        raise ValueError('Truncated stored player action counters')
    values = {name: child[offset + delta] for name, (offset, _, _) in _FIELDS.items()}
    expected_goals = struct.unpack_from('<f', child, 25 + delta)[0]
    if not math.isfinite(expected_goals) or expected_goals < 0:
        raise ValueError('Invalid stored player expected goals')
    # Native493EAE8..493EB04 adds the same event float to named SIDE_STATS+60
    # and its player-vector member+1c. Reader4AD2A04 emits+1c at wire25.
    values['expected_goals'] = expected_goals
    expected_assists = struct.unpack_from('<f', child, 191 + delta)[0]
    if not math.isfinite(expected_assists) or expected_assists < 0:
        raise ValueError('Invalid stored player expected assists')
    values['expected_assists'] = expected_assists
    return values


def field_registry() -> dict[str, dict[str, object]]:
    """Return independent metadata for proved counters and expected goals."""
    registry = {
        name: {
            'wire_offset_u32_person': offset,
            'wire_offset_u64_person': offset + 4,
            'native_offset': hex(native),
            'consumer_load_rva': hex(consumer),
            'unit': 'unsigned byte stored action count',
            'semantic_proof': 'B142 native consumer name and default wire reader',
            'independent_team_sum_verified': name in ('shots', 'shots_on_target'),
        }
        for name, (offset, native, consumer) in _FIELDS.items()
    }
    registry['expected_goals'] = {
        'wire_offset_u32_person': 25,
        'wire_offset_u64_person': 29,
        'native_offset': '0x1c',
        'unit': 'unscaled native IEEE754 float32 expected goals',
        'semantic_proof': 'B142 same event addend to named team xG and player accumulator',
        'producer_rva': '0x493eae8',
        'team_name_rva': '0x27ed34c',
        'independent_team_sum_verified': True,
        'team_sum_absolute_tolerance': 1e-5,
        'scope': 'Stored aggregate; xG/shots is an aggregate average, not individual-shot records or xA',
    }
    for name, label, key in (
        ('key_passes', 'KeyPasses', '0x6949686f'),
        ('open_play_key_passes', 'OpenPlayKeyPasses', '0x47767a57'),
        ('chances_created', 'ChancesCreated', '0x30485a6f'),
    ):
        registry[name].update({
            'official_property_label': label,
            'native_property_key': key,
            'semantic_proof': 'B142 managed property registration and native player UI exporter',
        })
    registry['chances_created']['scope'] = 'Native individual property; team property with same label has different aggregation'
    registry['expected_assists'] = {
        'wire_offset_u32_person': 191,
        'wire_offset_u64_person': 195,
        'native_offset': '0x24',
        'consumer_load_rva': '0x205028',
        'native_property_key': '0x49675367',
        'official_property_label': 'ExpectedAssists',
        'unit': 'unscaled native IEEE754 float32 expected assists',
        'semantic_proof': 'B142 managed property registration and native player UI exporter',
        'independent_team_sum_verified': False,
        'scope': 'FM aggregate credit; no open-play xA split or causal skill attribution',
    }
    return registry
