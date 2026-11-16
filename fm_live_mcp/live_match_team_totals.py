"""Decode named team totals from bounded retained MATCH_STATS60 sides.

Native mapping: B142 team-statistics/decoder, binary SHA774cacde63567f.
Shots/target and corners are u8; pass counters are i16; xG is float32.
Possession raw units and official UI provider bindings remain unproved.
"""
import math
import struct

from . import saved_match_statistics_wire as wire

MAX_FRAME_BYTES = 1 << 20
MAX_PLAYER_ROWS = 256


def crossing_field_registry() -> dict:
    """Bounded common provenance for reconstructed team crossing columns."""
    return {
        'crosses_attempted': {'unit': 'unsigned stored action count in nonnegative signed16 team domain',
                              'official_property': 'CrossAttempts', 'property_key': '0x686a5a65',
                              'native_team_offset': '0xd4', 'native_player_offset': '0xb5'},
        'crosses_completed': {'unit': 'unsigned stored action count in nonnegative signed16 team domain',
                              'official_property': 'CrossesCompleted', 'property_key': '0x20726763',
                              'native_team_offset': '0xd6', 'native_player_offset': '0xb6'},
        'source': 'Native side reader reconstructs signed16 team counters by summing stored unsigned8 player counters.',
        'independent_serialized_team_oracle': False,
        'cross_completion_percentage_derived': 'Arithmetic completed/attempted times100; null for zero or unavailable counts.',
        'crossing_counts_state': ['native_aggregate_available', 'unavailable_signed16_overflow',
                                  'unavailable_inconsistent_player_counters'],
        'limits': ['No delivery-side, origin, destination, headed-chance or open-play oracle from total counters.',
                   'A separate proved player/open-play source is required for open-play metrics.',
                   'These counts alone do not establish current tactical assignments.'],
    }


def _float32(value: float) -> float:
    return struct.unpack('<f', struct.pack('<f', value))[0]


def _possession_shares(counters: list[int]) -> list[tuple[int | None, str]]:
    """Mirror native ratio/float32/fcvtas for the proved nonnegative domain."""
    if any(value < 0 for value in counters):
        return [(None, 'unavailable_negative_raw_counter')] * 2
    denominator = sum(counters)
    if denominator > 0x7fffffff:
        return [(None, 'unavailable_denominator_overflow')] * 2
    if not denominator:
        return [(0, 'native_ratio_computed')] * 2
    return [(math.floor(_float32(_float32(_float32(value) / _float32(denominator)) * 100) + 0.5),
             'native_ratio_computed') for value in counters]


def _crossing_counts(raw: bytes, children: list[dict]) -> tuple[int | None, int | None, str]:
    """Native494531c..5338 sums player+b5/+b6 into signed16 team fields."""
    attempts = completed = 0
    for child in children:
        delta = 0 if child['reference']['tag'] >= 2 else 4
        if child['end'] - child['start'] <= 90 + delta:
            raise ValueError('Truncated retained crossing counters')
        at = child['start'] + delta
        player_attempts, player_completed = raw[at + 89], raw[at + 90]
        if player_completed > player_attempts:
            return None, None, 'unavailable_inconsistent_player_counters'
        attempts += player_attempts
        completed += player_completed
    # Native stores16bits then exports signed16. The negative/overflow domain
    # has no proved football meaning, so do not return wrapped negative counts.
    if attempts > 32767 or completed > 32767:
        return None, None, 'unavailable_signed16_overflow'
    return attempts, completed, 'native_aggregate_available'


def decode_team_totals(raw: bytes) -> dict:
    """Validate both complete sides before exposing named team totals."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_FRAME_BYTES:
        raise ValueError('Invalid retained match frame or expanded-frame budget exceeded')
    prefix = wire.fixture_prefix(raw)
    fixture = wire.continue_fixture(raw, prefix['end'], wire.parse_person, wire.fixture_extra)
    key = fixture['fields']['scalar_u32'][0]
    stats = wire.stats_prefix(raw, fixture['end'])
    at = stats['end']
    teams = []
    row_count = 0
    for index, team in enumerate(prefix['fixture_fields8_10_team_references']):
        side = wire.side(raw, at, version=60, parse_child=wire.player,
                         parse_collection=wire.collection)
        at = side['end']
        fields = side['fields']
        if fields['0x5c_raw_reference'] != team['index_word']:
            raise ValueError('Retained side differs from fixture TEAM reference')
        row_count += side['child_count']
        if row_count > MAX_PLAYER_ROWS:
            raise ValueError('Retained player-row work budget exceeded')
        shots, target = fields['0x16f'], fields['0x170']
        xg = struct.unpack('<f', bytes.fromhex(fields['0x60_float_raw']))[0]
        if not math.isfinite(xg) or xg < 0 or target > shots:
            raise ValueError('Invalid retained team totals')
        attempts = int.from_bytes(bytes.fromhex(fields['0xd8']), 'little', signed=True)
        completed = int.from_bytes(bytes.fromhex(fields['0xda']), 'little', signed=True)
        corners = int.from_bytes(bytes.fromhex(fields['0x19d']), 'little')
        possession = int.from_bytes(bytes.fromhex(fields['0x7c']), 'little', signed=True)
        if not 0 <= completed <= attempts:
            raise ValueError('Invalid retained pass counters')
        crosses_attempted, crosses_completed, crossing_state = _crossing_counts(raw, side['children'])
        teams.append({'side_index': index, 'side': 'home' if index == 0 else 'away',
                      'team_index': team['index_word'],
                      'team_identity_word': team['identity_word'],
                      'shots': shots, 'shots_on_target': target, 'expected_goals': xg,
                      'expected_goals_raw_hex': fields['0x60_float_raw'],
                      'passes_attempted': attempts, 'passes_completed': completed,
                      'pass_completion_percentage_derived': 100 * completed / attempts if attempts else None,
                      'corners': corners, 'possession_time_raw': possession,
                      'crosses_attempted': crosses_attempted, 'crosses_completed': crosses_completed,
                      'crossing_counts_state': crossing_state,
                      'cross_completion_percentage_derived':
                          100 * crosses_completed / crosses_attempted if crosses_attempted else None})
    shares = _possession_shares([team['possession_time_raw'] for team in teams])
    for team, (share, state) in zip(teams, shares):
        team['possession_share_percentage_computed'] = share
        team['possession_share_state'] = state
    return {'result_key': key, 'teams': teams,
            'coverage': {'complete_side_sections': True, 'parsed_until': at,
                         'raw_frame_bytes': len(raw), 'unparsed_tail_bytes': len(raw) - at,
                         'whole_payload_wire_parsed': False,
                         'wire_profile': 'MATCH_STATS60/FIXTURE31',
                         'expected_goals_units': 'unscaled_float32',
                         'possession_time_raw_units': None,
                         'possession_share_semantics': 'native_time_ratio_float32_rounded_to_nearest_away',
                         'official_displayed_possession_percentage_verified': False,
                         'pass_completion_percentage_semantics': 'derived_completed_over_attempted',
                         'crossing_counts_source': 'native_signed16_team_sum_of_stored_player_unsigned8_counts',
                         'crossing_locations_verified': False,
                         'cross_completion_percentage_semantics': 'derived_completed_over_attempted'}}
