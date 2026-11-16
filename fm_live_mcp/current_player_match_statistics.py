"""Typed resident PLAYER attacking-action counters, without a native clock association.

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
    (0x2f10b94, bytes.fromhex('811201d02134259102008012d6e05194d34242394bcc539408e00091b30318b8a88317f8a0c302d1e1c30291a22302d1d6646197')),
    (0x2f10c00, bytes.fromhex('61120190213c119102008012bbe05194d346423930cc539408e00091b30318b8a88317f8a0c302d1e1c30291a22302d1bb646197')),
    (0x516294d, bytes.fromhex('73686f74735f617474656d7074656400')),
    (0x515c44f, bytes.fromhex('73686f74735f6f6e5f74617267657400')),
    (0x2051a8, bytes.fromhex('e1f24239e023009151fb0795e0630091e2230091e10d8d522129ad7248c80795')),
    (0x204e78, bytes.fromhex('e1824239e02300911dfc0795e0630091e2230091e14d8b520109a67214c90795')),
    (0x266f3c, bytes.fromhex('01f0423978000014')),
    (0x2668cc, bytes.fromhex('0180423914020014')),
)


def inspect(read, base, engine, *, expected_match_unique_id):
    """Read only named attacking fields after same-side PERSON and concrete stats reconciliation.

    No native clock is accepted or derived. A null or mismatched source remains
    unavailable; stored0 is an actual unsigned byte0. No sum claims a side total.
    Caller must recheck every consumed byte after its last lifetime callback.
    """
    if type(expected_match_unique_id) is not int or not 0 < expected_match_unique_id < 1 << 64:
        raise ValueError('A checked nonzero official match unique ID is required')
    people._type(read, base, engine, 0x55FA258, b'10GAME_MATCH')
    if people._u64(read, engine + 0x20) != expected_match_unique_id:
        raise ValueError('PLAYER attacking statistics official match identity changed')
    for offset, raw in (*SOURCE_SPANS, *people.ACTOR_SLOT_SPANS):
        if people._read(read, base + offset, len(raw)) != raw:
            raise ValueError('PLAYER attacking statistics native source changed')
    actors = people.inspect_canonical(read, base, engine, identity_only=True)
    rows = []
    identities = set()
    for actor in actors['rows']:
        side_index, index = actor['side_index'], actor['engine_array_index']
        identity = actor['person']
        row = {'side_index': side_index, 'engine_array_index': index,
               'identity_state': actor['identity_state'], 'person': identity,
               'state': 'unavailable_identity', 'shots': None, 'shots_on_target': None,
               'key_passes': None, 'chances_created': None}
        if identity is not None:
            key = side_index, identity['native_identity']['database_index']
            if key in identities:
                raise ValueError('Duplicate canonical PLAYER attacking statistics identity')
            identities.add(key)
            side = people._u64(read, engine + 0x15370 + side_index * 8)
            player = people._u64(read, side + 0x140 + index * 8)
            people._type(read, base, player, 0x569EE68, b'N7simatch12MATCH_PLAYERE')
            if (people._u64(read, player + 0x280) != engine
                    or people._u64(read, player + 0x288) != side):
                raise ValueError('PLAYER attacking statistics owner changed')
            if people._read(read, player + 0x1E27, 1)[0] != index:
                raise ValueError('PLAYER attacking statistics original roster slot changed')
            stats = people._u64(read, player + 0x1880)
            row['state'] = 'unavailable_stats'
            if stats:
                people._type(read, base, stats, 0x55FA800, b'23GAME_MATCH_PLAYER_STATS')
                ordinal = struct.unpack('<I', people._read(read, stats + 0x18, 4))[0]
                row['state'] = 'unavailable_stats_person_mismatch'
                if ordinal == identity['native_identity']['database_index']:
                    shots, on_target = people._read(read, stats + 0x90, 2)
                    key_passes = people._read(read, stats + 0xBC, 1)[0]
                    chances = people._read(read, stats + 0xA0, 1)[0]
                    row.update(state='available_native_statistic_observation',
                               shots=shots, shots_on_target=on_target,
                               key_passes=key_passes, chances_created=chances)
        rows.append(row)
    available = sum(row['state'] == 'available_native_statistic_observation' for row in rows)
    return {'state': 'available' if available == len(rows) else 'available_partial' if available else 'unavailable',
            'source': 'typed_owned_resident_GAME_MATCH_PLAYER_STATS_attacking_actions',
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
                     'halftime, completion, live-versus-replay or on-pitch claim. ChancesCreated is an '
                     'individual native property, not a team aggregate or a proved shot-supply sequence.'}
