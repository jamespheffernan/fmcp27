"""Named signed-after-round activation from a checked effective CUP round."""
import hashlib
import struct

from . import competition_stages, competitions, players, world

NATIVE_GUARDS = (
    (0x3C8C030, 1056, '8f0a2eb9602e33e6ed8221d1092cd7d9e34133a3a42e95c16c4d19c04bbbe7d8'),
    (0x3C9C290, 36, '207ba7ab827525f121e1f1951f28642fbbd74ed59c3557da436ba7e9b9e4dc85'),
    (0x3C8D680, 96, '3903346f14d8ed2e4fa619a630d0382d0f57e84a7283640c87575b4772e37b95'),
    (0x3BCC0EC, 84, '85beafb276d4669dfb665bf23699bc2a2a2baa4f934db227bc83f33b0d2425bc'),
    (0x3C96FC0, 128, 'ca23380a076cf9714e8b5fdb03f02b68d211db49ab01ac5961fb31969192f9ca'),
)
NAME = 'players_cup_tied_if_signed_after_round'
MASK = 0x80
SCOPE = ('Activation of the named signed-after-round restriction in the fixture-selected '
         'resident CUP round only. A clear flag bypasses this specific native check. An enabled '
         'flag requires additional player, contract and date checks that are not evaluated. '
         'This is not an overall cup-tied, registration, bench or match-eligibility verdict. '
         'The effective fixture special-rule byte is corroboration, not the activation source.')


def verify_native(read, base):
    for address, length, expected in NATIVE_GUARDS:
        if hashlib.sha256(read(base + address, length)).hexdigest() != expected:
            raise ValueError('Signed-after-round native source changed')
    # Named-table entries contain a string pointer followed by its value byte.
    pointer, value = struct.unpack('<QB', read(base + 0x5671B68, 9))
    if (pointer != base + 0x5299280 or value != MASK
            or read(pointer, len(NAME) + 1) != NAME.encode() + b'\0'):
        raise ValueError('Signed-after-round named option changed')


def activation(flags):
    if type(flags) is not int or not 0 <= flags <= 255:
        raise ValueError('Round flags must be an unsigned byte')
    active = bool(flags & MASK)
    return {'state': 'decoded_named_round_option', 'enabled': active,
            'native_round_flags_u8': flags,
            'specific_check_state': ('enabled_player_and_date_checks_not_evaluated' if active
                                     else 'bypassed_by_clear_round_flag')}


def read_activation(read, base, fixture_raw, competition_address):
    """Resolve only audited typed CUP slots; never call a getter or follow an override."""
    if len(fixture_raw) != 0x58:
        raise ValueError('Signed-after-round source requires a complete fixture prefix')
    verify_native(read, base)
    result = {'state': 'unavailable', 'reason': None, 'enabled': None,
              'native_option': NAME, 'native_option_mask': MASK,
              'source': 'fixture_signed_3B_to_typed_CUP_STAGE_runtime_round_DA',
              'stage_index': None, 'round_index': None, 'native_round_flags_u8': None,
              'fixture_season_code': int.from_bytes(fixture_raw[0x30:0x32], 'little'),
              'effective_fixture_special_flags_u8': fixture_raw[0x3C],
              'fixture_flag_agrees': None, 'specific_check_state': 'not_established',
              'player_eligibility_evaluated': False, 'scope': SCOPE}

    def unavailable(reason):
        return dict(result, reason=reason)

    if not competition_address:
        return unavailable('missing_fixture_competition')
    index = int.from_bytes(read(competition_address + 8, 4), 'little')
    competition = competitions.by_index(read, base, index)
    saved = dict(competition, address=competition_address)
    context, runtime, identity = competition_stages.runtime_context(read, base, saved)
    if runtime is None:
        return unavailable('runtime_competition_absent')
    result['runtime_competition'] = context['runtime_competition']
    result['native_season_code'] = context['native_season_code']
    if result['fixture_season_code'] != context['native_season_code']:
        return unavailable('fixture_runtime_season_mismatch')
    stage_index = struct.unpack_from('<b', fixture_raw, 0x38)[0]
    round_index = struct.unpack_from('<b', fixture_raw, 0x3B)[0]
    result.update(stage_index=stage_index, round_index=round_index)
    stages, _ = competition_stages.vector(read, runtime + 0x1D8, 1024)
    if stage_index < 0 or stage_index >= len(stages):
        return unavailable('stage_index_outside_runtime_vector')
    stage = stages[stage_index]
    if not stage:
        return unavailable('null_stage')
    expected = competition_stages.STAGE_TYPES['cup']
    if world.pointer(read, stage) != base + expected[0]:
        return unavailable('unsupported_stage_kind')
    competition_stages.typed(read, base, stage, expected)
    if world.pointer(read, stage + 0x70) != identity[2]:
        raise ValueError('Signed-after-round stage owner changed')
    table = base + expected[0]
    if (players.u64(read(table + 0x298, 8)) != base + 0x3C8C030
            or players.u64(read(table + 0x368, 8)) != base + 0x3C9C290):
        return unavailable('unsupported_round_consumer_or_getter')
    if round_index < 0:
        return unavailable('negative_round_index')
    details = players.u64(read(stage + 0x90, 8))
    if not details:
        return unavailable('round_details_absent')
    if details < 4096 or details % 8:
        raise ValueError('Invalid CUP round details pointer')
    rounds, _ = competition_stages.vector(read, details + 0x58, 128)
    if round_index >= len(rounds):
        return unavailable('round_index_outside_runtime_vector')
    selected = rounds[round_index]
    if not selected:
        return unavailable('null_round')
    flags = read(selected + 0xDA, 1)[0]
    result.update(activation(flags), reason=None,
                  fixture_flag_agrees=bool(fixture_raw[0x3C] & MASK) == bool(flags & MASK))
    return result
