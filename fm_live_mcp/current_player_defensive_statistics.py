"""Typed resident PLAYER defensive-action counters, without a native clock association.

Caller owns the current fixture/incarnation, runtime/ReadSet and final epoch
checks. This module neither attaches nor publishes a host observation. Native
unsigned byte counters are observations, not cursor/halftime totals, appearances,
complete squad membership or evidence of current on-pitch participation.
"""
import struct

from . import active_match_people as people

# Exact named native consumers/exporters; no retained wire offsets are used.
# MATCH_PLAYER+1880 assignment, original-slot setup and canonical actor guards
# are independently pinned by ACTOR_SLOT_SPANS in the caller's same ReadSet.
SOURCE_SPANS = (
    (0x2f10abc, bytes.fromhex('811201d021a42491020080120ce15194d31a433981cc539408e00091b30318b8a88317f8a0c302d1e1c30291a22302d10c656197')),
    (0x2f10b28, bytes.fromhex('811201d021ec249102008012f1e05194d31e433966cc539408e00091b30318b8a88317f8a0c302d1e1c30291a22302d1f1646197')),
    (0x5162929, bytes.fromhex('7461636b6c65735f617474656d7074656400')),
    (0x516293b, bytes.fromhex('7461636b6c65735f636f6d706c6574656400')),
    (0x205180, bytes.fromhex('e13e4339e02300915bfb0795e0630091e223009101268e5241acac7252c80795')),
    (0x204ec8, bytes.fromhex('e1664339e0230091fcfb0795e0630091e223009141c688526148af7200c90795')),
)


def inspect(read, base, engine, *, expected_match_unique_id):
    """Read only named defensive fields after same-side PERSON and concrete stats reconciliation.

    No native clock is accepted or derived. A null or mismatched source remains
    unavailable; stored0 is an actual unsigned byte0. No sum claims a side total.
    Caller must recheck every consumed byte after its last lifetime callback.
    """
    if type(expected_match_unique_id) is not int or not 0 < expected_match_unique_id < 1 << 64:
        raise ValueError('A checked nonzero official match unique ID is required')
    people._type(read, base, engine, 0x55FA258, b'10GAME_MATCH')
    if people._u64(read, engine + 0x20) != expected_match_unique_id:
        raise ValueError('PLAYER defensive statistics official match identity changed')
    for offset, raw in (*SOURCE_SPANS, *people.ACTOR_SLOT_SPANS):
        if people._read(read, base + offset, len(raw)) != raw:
            raise ValueError('PLAYER defensive statistics native source changed')
    actors = people.inspect_canonical(read, base, engine, identity_only=True)
    rows = []
    identities = set()
    for actor in actors['rows']:
        side_index, index = actor['side_index'], actor['engine_array_index']
        identity = actor['person']
        row = {'side_index': side_index, 'engine_array_index': index,
               'identity_state': actor['identity_state'], 'person': identity,
               'state': 'unavailable_identity', 'tackles_attempted': None, 'tackles_completed': None,
               'interceptions': None, 'clearances': None}
        if identity is not None:
            key = side_index, identity['native_identity']['database_index']
            if key in identities:
                raise ValueError('Duplicate canonical PLAYER defensive statistics identity')
            identities.add(key)
            side = people._u64(read, engine + 0x15370 + side_index * 8)
            player = people._u64(read, side + 0x140 + index * 8)
            people._type(read, base, player, 0x569EE68, b'N7simatch12MATCH_PLAYERE')
            if (people._u64(read, player + 0x280) != engine
                    or people._u64(read, player + 0x288) != side):
                raise ValueError('PLAYER defensive statistics owner changed')
            if people._read(read, player + 0x1E27, 1)[0] != index:
                raise ValueError('PLAYER defensive statistics original roster slot changed')
            stats = people._u64(read, player + 0x1880)
            row['state'] = 'unavailable_stats'
            if stats:
                people._type(read, base, stats, 0x55FA800, b'23GAME_MATCH_PLAYER_STATS')
                ordinal = struct.unpack('<I', people._read(read, stats + 0x18, 4))[0]
                row['state'] = 'unavailable_stats_person_mismatch'
                if ordinal == identity['native_identity']['database_index']:
                    tackles_attempted, on_target = people._read(read, stats + 0xC6, 2)
                    interceptions = people._read(read, stats + 0xCF, 1)[0]
                    chances = people._read(read, stats + 0xD9, 1)[0]
                    row.update(state='available_native_statistic_observation',
                               tackles_attempted=tackles_attempted, tackles_completed=on_target,
                               interceptions=interceptions, clearances=chances)
        rows.append(row)
    available = sum(row['state'] == 'available_native_statistic_observation' for row in rows)
    return {'state': 'available' if available == len(rows) else 'available_partial' if available else 'unavailable',
            'source': 'typed_owned_resident_GAME_MATCH_PLAYER_STATS_defensive_actions',
            'official_match_unique_id': expected_match_unique_id,
            'rows': rows,
            'coverage': {'resident_slots': len(rows), 'available_statistic_rows': available,
                         'unavailable_rows': len(rows) - available,
                         'complete_on_pitch_population_verified': False},
            'statistic_units': 'unsigned native stored byte0..255',
            'native_timestamp_association': False,
            'displayed_time_verified': False,
            'counter_publication_fence_verified': False,
            'atomic_snapshot_verified': False,
            'participation_verified': False,
            'complete_side_total_verified': False,
            'scope': 'Resident counter bytes requiring caller recheck. No native tick, displayed minute, '
                     'halftime, completion, live-versus-replay or on-pitch claim. Defensive action counts '
                     'do not identify possession regains, locations, difficulty or tactical cause.'}
