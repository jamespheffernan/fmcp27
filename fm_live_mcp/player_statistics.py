"""Pure decoding of the native compact PLAYER_STATS record; no refresh or reads."""
import struct


COMPACT_BYTES = 25
ARRAY_COUNT = 68
ARRAY_BYTES = ARRAY_COUNT * 2
BYTE_FIELDS = {
    'starting_appearances': 0x0C,
    'sub_appearances': 0x0D,
    'rating_denominator': 0x0E,
    'goals': 0x0F,
    'assists': 0x10,
    'goals_conceded': 0x11,
    'penalties': 0x12,
    'penalties_scored': 0x13,
    'player_of_the_match': 0x14,
    'red_cards': 0x15,
    'yellow_cards': 0x16,
    'clean_sheets': 0x17,
    'unmapped_enum_81': 0x18,
}
ARRAY_FIELDS = {
    0: 'team_goals', 1: 'team_goals_conceded', 2: 'games_won', 3: 'games_lost',
    4: 'passes_attempted', 5: 'passes_completed', 6: 'tackles_attempted',
    7: 'tackles_completed', 8: 'aerial_challenges_attempted', 9: 'headers_won',
    10: 'dribbles_made', 11: 'fouls_made', 12: 'fouls_against', 13: 'shots',
    14: 'shots_on_target', 19: 'expected_goals_against',
    20: 'mistakes_leading_to_goal', 21: 'minutes_since_last_goal',
    22: 'minutes_since_last_conceded', 23: 'distance_covered', 24: 'offside',
    25: 'open_play_crosses_attempted', 26: 'open_play_crosses_completed',
    27: 'key_passes', 28: 'key_tackles', 29: 'key_headers',
    30: 'interceptions_made', 31: 'clear_cut_chances_created', 32: 'blocks',
    33: 'direct_free_kick_goals', 34: 'possession_lost', 35: 'possession_won',
    36: 'expected_goals', 37: 'expected_assists', 38: 'clearances',
    47: 'expected_goals_prevented', 50: 'progressive_passes',
    51: 'pressures_attempted', 52: 'pressures_completed',
    53: 'open_play_key_passes', 54: 'non_penalty_expected_goals',
    55: 'expected_goals_overperformance', 56: 'crosses_attempted',
    57: 'crosses_completed', 58: 'shots_blocked',
}
LIMITATIONS = (
    'Stored compact statistics without executing refresh or UI normalization. '
    'Starting and substitute appearances are separate native counters. '
    'Byte 255 is unavailable in the integer getter; signed array values are preserved. '
    'Advanced values use unverified native units. A zero rating denominator returns '
    'native average 0.0; it does not establish why no rating was recorded.'
)


def _float32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def decode_compact(raw: bytes, indirect: bytes | None) -> dict:
    """Decode exactly one 25-byte compact record and its optional 136-byte array."""
    if not isinstance(raw, bytes) or len(raw) != COMPACT_BYTES:
        raise ValueError('Compact player statistics must contain exactly 25 bytes')
    pointer = struct.unpack_from('<Q', raw)[0]
    if indirect is not None and (not isinstance(indirect, bytes) or len(indirect) != ARRAY_BYTES):
        raise ValueError('Indirect player statistics must contain exactly 136 bytes')
    if bool(pointer) != (indirect is not None):
        raise ValueError('Player statistics pointer and indirect data disagree')

    native_raw = {name: raw[offset] for name, offset in BYTE_FIELDS.items()}
    native_raw['total_rating_tenths'], native_raw['minutes'] = struct.unpack_from('<hh', raw, 8)
    getters = {name: -1 if value == 255 else value
               for name, value in native_raw.items() if name in BYTE_FIELDS}
    getters.update(total_rating_tenths=native_raw['total_rating_tenths'], minutes=native_raw['minutes'])
    values = {name: None if native_raw[name] == 255 else native_raw[name] for name in BYTE_FIELDS}
    starts, substitutes = values['starting_appearances'], values['sub_appearances']
    denominator = native_raw['rating_denominator']
    average = (0.0 if denominator == 0 else
               _float32(_float32(native_raw['total_rating_tenths'] / 10.0) / denominator))
    array = list(struct.unpack('<68h', indirect)) if indirect is not None else [0] * ARRAY_COUNT
    return {
        **values,
        'total_appearances': None if starts is None or substitutes is None else starts + substitutes,
        'total_rating_tenths': native_raw['total_rating_tenths'],
        'minutes': native_raw['minutes'],
        'average_rating': average,
        'native_raw': native_raw,
        'native_getter_values': getters,
        'advanced': {
            'state': 'resident' if indirect is not None else 'native_zero_default_null_indirect',
            'raw_signed16': array,
            'named_raw_values': {name: array[index] for index, name in ARRAY_FIELDS.items()},
            'units': 'unverified_native_units',
        },
        'limitations': LIMITATIONS,
    }


def verify_native(read, base):
    """Fail closed if selected copy, enum-dispatch, getter or rating instructions drift."""
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError(f'Player statistics native layout changed at RVA {rva:#x}')


# Native ARM64 spans from the build-verified batch history-01 receipt.
NATIVE_SPANS = (
    (0xf83fe8, bytes.fromhex(
        '1b0080d208884039284400390830427828240079085042b8285001b89c3a02900840407928140079'
    )),
    (0xf84064, bytes.fromhex(
        '880a40f9280100b415697b78'
    )),
    (0xf84190, bytes.fromhex(
        '883e407968120079889242b8680e00b988b640396842003988ba403968520039'
    )),
    (0xf75588, bytes.fromhex(
        '3f480171080100543f0c017128010054080040f9880200b408d96178003d0013c0035fd6e8ff9f52003d0013c0035fd6'
        '28100151a92002f0290129918a0000102b6968384a090b8b40011fd6083040391ffd037108119f5a003d0013c0035fd6'
        '08144079003d0013c0035fd6083840391ffd037108119f5a003d0013c0035fd6084840391ffd037108119f5a003d0013'
        'c0035fd6085c40391ffd037108119f5a003d0013c0035fd6085040391ffd037108119f5a003d0013c0035fd6083c4039'
        '1ffd037108119f5a003d0013c0035fd6084440391ffd037108119f5a003d0013c0035fd6085840391ffd037108119f5a'
        '003d0013c0035fd6083440391ffd037108119f5a003d0013c0035fd6084c40391ffd037108119f5a003d0013c0035fd6'
        '086040391ffd037108119f5a003d0013c0035fd6084040391ffd037108119f5a003d0013c0035fd608104079003d0013'
        'c0035fd6085440391ffd037108119f5a003d0013c0035fd6'
    )),
    (0x538ca40, bytes.fromhex(
        '002b1c210d303a2642173f08123505'
    )),
    (0xf75c00, bytes.fromhex(
        '295c00513f310271684e00540814c0790101221e00e4002faa2002f04a4129918b0000104c7969786b090c8b60011fd6'
        '0010407d00a4100f00a4200f00d8615e0190641e0018611e0040621e083840390101231e0018211e1f01007101e4002f'
        '200c201ec0035fd6'
    )),
    (0x538caca, bytes.fromhex(
        '07016902000000000000'
    )),
    (0xf7604c, bytes.fromhex(
        '08304039093440392801080b0001231ec0035fd6'
    )),
    (0xf8906c, bytes.fromhex(
        'ff4301d1f44f03a9fd7b04a9fd030191f30301aae80300aac93802f0201146f91f7d0271e8150154e803082a092002f0'
        '29a138918a0000102b7968784a090b8b40011fd6'
    )),
    (0x538ce28, bytes.fromhex(
        '00002e04ff045d05a3051e053e057904d404e70389041306c8050c046906a708a708a708a7087906fe02b8066e034e05'
        'bf027d03ae04d203e805a803aa026c02bd033e04fd055304310244033306a708a708a708a708a708a708a708a7085307'
        'a708a7089502b3058002460292039904a306b301e902a708a708a708a708a708a708a708a708a7080f0593057d072e05'
        '2102c801dc0728071002d8058e06a708fb01a708fe06d406e8008d07ec07c706ca0613031307fe006807b707f7031108'
        'e9062301d4026d056f015008d70034037100b2005b02a708a708a70883051301ea016100cc0724034a01490692007108'
        '5500c200830140003b088108a2072100a708a708a708a708a708a708a708a708a708a708a7086108a708590326085a01'
        '0108a2005906680498013807e4041000390181001d04c3043500d90196082306'
    )),
    (0xf857fc, bytes.fromhex(
        '7562009128038052f52301a968c60091e81300f9'
    )),
    (0xf85854, bytes.fromhex(
        'df1e007188088052890780523a31889ac83a1f121f11007161010054'
    )),
    (0xf858b8, bytes.fromhex(
        '7fff00a97f8301f842fb7fd3880240f9081940f9e1a30091e00314aa00013fd6'
    )),
    (0xf8592c, bytes.fromhex(
        '680a40f914793c789c0700919f1301f1e00900549f031aeb'
    )),
)
