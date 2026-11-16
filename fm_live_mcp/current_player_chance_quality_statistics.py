"""Typed resident PLAYER chance quality and progression counters, without a native clock association.

Caller owns the current fixture/incarnation, runtime/ReadSet and final epoch
checks. This module neither attaches nor publishes a host observation. Native
values are observations, not cursor/halftime totals, appearances,
complete squad membership or evidence of current on-pitch participation.
"""
import math
import struct

from . import active_match_people as people

# Exact named native consumers/exporters; no retained wire offsets are used.
# MATCH_PLAYER+1880 assignment, original-slot setup and canonical actor guards
# are independently pinned by ACTOR_SLOT_SPANS in the caller's same ReadSet.
SOURCE_SPANS = (
    (0x493e900, bytes.fromhex('692e41f9682a41f9290108cb7f0d89eb2228005417796bf8')),
    (0x493eae8, bytes.fromhex('c03240bd616240bd0128211e616200bd570100b4e11e40bd0128211ee11e00bd')),
    (0x27ed34c, bytes.fromhex('614b01f021e40c91a04302d102008012e76e6e94686340bd5c5a709408a00191a80315bca88314f8a02302d1a14302d1')),
    (0x515c339, bytes.fromhex('784700')),
    (0x205028, bytes.fromhex('e02640bde0230091d6fb0795e0630091e2230091e16c8a52e12ca972a8c80795')),
    (0x266bc4, bytes.fromhex('002440bd48010014')),
    (0x205520, bytes.fromhex('e1f64239e023009173fa0795e0630091e2230091e14a8f52c1eea8726ac70795')),
    (0x205288, bytes.fromhex('e1c64339e02300910cfb0795e0630091e223009181ed8852212cac7210c80795')),
    (0x205ac4, bytes.fromhex('e116c279e0230091fdf80795e0630091e2230091e1298652214eab7201c60795')),
    (0x266f24, bytes.fromhex('0114c279e0030091e57306957e000014')),
)


def inspect(read, base, engine, *, expected_match_unique_id):
    """Read only named chance quality and progression fields after same-side PERSON and concrete stats reconciliation.

    No native clock is accepted or derived. A null or mismatched source remains
    unavailable; stored zero remains an actual source value. No sum claims a side total.
    Caller must recheck every consumed byte after its last lifetime callback.
    """
    if type(expected_match_unique_id) is not int or not 0 < expected_match_unique_id < 1 << 64:
        raise ValueError('A checked nonzero official match unique ID is required')
    people._type(read, base, engine, 0x55FA258, b'10GAME_MATCH')
    if people._u64(read, engine + 0x20) != expected_match_unique_id:
        raise ValueError('PLAYER chance quality statistics official match identity changed')
    for offset, raw in (*SOURCE_SPANS, *people.ACTOR_SLOT_SPANS):
        if people._read(read, base + offset, len(raw)) != raw:
            raise ValueError('PLAYER chance quality statistics native source changed')
    actors = people.inspect_canonical(read, base, engine, identity_only=True)
    rows = []
    identities = set()
    for actor in actors['rows']:
        side_index, index = actor['side_index'], actor['engine_array_index']
        identity = actor['person']
        row = {'side_index': side_index, 'engine_array_index': index,
               'identity_state': actor['identity_state'], 'person': identity,
               'state': 'unavailable_identity', 'expected_goals': None, 'expected_assists': None,
               'open_play_key_passes': None, 'progressive_passes': None, 'open_play_final_third_passes': None}
        if identity is not None:
            key = side_index, identity['native_identity']['database_index']
            if key in identities:
                raise ValueError('Duplicate canonical PLAYER chance quality statistics identity')
            identities.add(key)
            side = people._u64(read, engine + 0x15370 + side_index * 8)
            player = people._u64(read, side + 0x140 + index * 8)
            people._type(read, base, player, 0x569EE68, b'N7simatch12MATCH_PLAYERE')
            if (people._u64(read, player + 0x280) != engine
                    or people._u64(read, player + 0x288) != side):
                raise ValueError('PLAYER chance quality statistics owner changed')
            if people._read(read, player + 0x1E27, 1)[0] != index:
                raise ValueError('PLAYER chance quality statistics original roster slot changed')
            stats = people._u64(read, player + 0x1880)
            row['state'] = 'unavailable_stats'
            if stats:
                people._type(read, base, stats, 0x55FA800, b'23GAME_MATCH_PLAYER_STATS')
                ordinal = struct.unpack('<I', people._read(read, stats + 0x18, 4))[0]
                row['state'] = 'unavailable_stats_person_mismatch'
                if ordinal == identity['native_identity']['database_index']:
                    expected_goals = struct.unpack('<f', people._read(read, stats + 0x1C, 4))[0]
                    expected_assists = struct.unpack('<f', people._read(read, stats + 0x24, 4))[0]
                    if any(not math.isfinite(n) or n < 0 for n in (expected_goals, expected_assists)):
                        raise ValueError('Invalid native resident expected statistic')
                    key_passes = people._read(read, stats + 0xBD, 1)[0]
                    progressive = people._read(read, stats + 0xF1, 1)[0]
                    final_third = struct.unpack('<h', people._read(read, stats + 0x10A, 2))[0]
                    if final_third < 0:
                        raise ValueError('Invalid negative native final-third pass counter')
                    row.update(state='available_native_statistic_observation',
                               expected_goals=expected_goals, expected_assists=expected_assists,
                               open_play_key_passes=key_passes, progressive_passes=progressive,
                               open_play_final_third_passes=final_third)
        rows.append(row)
    available = sum(row['state'] == 'available_native_statistic_observation' for row in rows)
    return {'state': 'available' if available == len(rows) else 'available_partial' if available else 'unavailable',
            'source': 'typed_owned_resident_GAME_MATCH_PLAYER_STATS_chance_quality_and_progression',
            'official_match_unique_id': expected_match_unique_id,
            'rows': rows,
            'coverage': {'resident_slots': len(rows), 'available_statistic_rows': available,
                         'unavailable_rows': len(rows) - available,
                         'complete_on_pitch_population_verified': False},
            'statistic_units': 'xG/xA: unscaled native float32; key/progressive passes: unsigned byte; final-third passes: signed int16 nonnegative counter',
            'native_timestamp_association': False,
            'displayed_time_verified': False,
            'counter_publication_fence_verified': False,
            'atomic_snapshot_verified': False,
            'participation_verified': False,
            'complete_side_total_verified': False,
            'scope': 'Resident values requiring caller recheck. No native tick, displayed minute, '
                     'halftime, completion, live-versus-replay or on-pitch claim. xG/xA are aggregates, '
                     'not individual shot values, chance categories or causal credit. Progressive and '
                     'OpenPlayFinalThirdPasses retain FM labels; no distance threshold, final-third '
                     'entry count, carry, action location or tactical cause is established.'}
