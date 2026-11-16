"""Typed resident PLAYER crossing and dribbling counters, without a native clock association.

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
    (0x204f18, bytes.fromhex('e1d64239e0230091f5fb0795e0630091e2230091a14c8b52410dad72ecc80795')),
    (0x204f80, bytes.fromhex('e1da4239e0230091dbfb0795e0630091e223009161ec8c52410ea472d2c80795')),
    (0x2055e8, bytes.fromhex('e87e4339e9824339e02300912101080b32fa0795e0630091e2230091e1cd895261aea67236c70795')),
    (0x205618, bytes.fromhex('e8864339e98a4339e02300912101080b26fa0795e0630091e2230091e16c8a52c108ab722ac70795')),
    (0x205000, bytes.fromhex('e1864239e0230091bbfb0795e0630091e2230091c18e8e5221a8a972b2c80795')),
    (0x266e00, bytes.fromhex('c98e8e5229a8a9721f01096b411a005401844239c3000014')),
)


def inspect(read, base, engine, *, expected_match_unique_id):
    """Read only named crossing and dribbling fields after same-side PERSON and concrete stats reconciliation.

    No native clock is accepted or derived. A null or mismatched source remains
    unavailable; stored0 is an actual unsigned byte0. No sum claims a side total.
    Caller must recheck every consumed byte after its last lifetime callback.
    """
    if type(expected_match_unique_id) is not int or not 0 < expected_match_unique_id < 1 << 64:
        raise ValueError('A checked nonzero official match unique ID is required')
    people._type(read, base, engine, 0x55FA258, b'10GAME_MATCH')
    if people._u64(read, engine + 0x20) != expected_match_unique_id:
        raise ValueError('PLAYER delivery statistics official match identity changed')
    for offset, raw in (*SOURCE_SPANS, *people.ACTOR_SLOT_SPANS):
        if people._read(read, base + offset, len(raw)) != raw:
            raise ValueError('PLAYER delivery statistics native source changed')
    actors = people.inspect_canonical(read, base, engine, identity_only=True)
    rows = []
    identities = set()
    for actor in actors['rows']:
        side_index, index = actor['side_index'], actor['engine_array_index']
        identity = actor['person']
        row = {'side_index': side_index, 'engine_array_index': index,
               'identity_state': actor['identity_state'], 'person': identity,
               'state': 'unavailable_identity', 'crosses_attempted': None, 'crosses_completed': None,
               'open_play_crosses_attempted': None, 'open_play_crosses_completed': None, 'dribbles_made': None}
        if identity is not None:
            key = side_index, identity['native_identity']['database_index']
            if key in identities:
                raise ValueError('Duplicate canonical PLAYER delivery statistics identity')
            identities.add(key)
            side = people._u64(read, engine + 0x15370 + side_index * 8)
            player = people._u64(read, side + 0x140 + index * 8)
            people._type(read, base, player, 0x569EE68, b'N7simatch12MATCH_PLAYERE')
            if (people._u64(read, player + 0x280) != engine
                    or people._u64(read, player + 0x288) != side):
                raise ValueError('PLAYER delivery statistics owner changed')
            if people._read(read, player + 0x1E27, 1)[0] != index:
                raise ValueError('PLAYER delivery statistics original roster slot changed')
            stats = people._u64(read, player + 0x1880)
            row['state'] = 'unavailable_stats'
            if stats:
                people._type(read, base, stats, 0x55FA800, b'23GAME_MATCH_PLAYER_STATS')
                ordinal = struct.unpack('<I', people._read(read, stats + 0x18, 4))[0]
                row['state'] = 'unavailable_stats_person_mismatch'
                if ordinal == identity['native_identity']['database_index']:
                    attempted, completed = people._read(read, stats + 0xB5, 2)
                    oa, ob, oc, od = people._read(read, stats + 0xDF, 4)
                    dribbles = people._read(read, stats + 0xA1, 1)[0]
                    row.update(state='available_native_statistic_observation',
                               crosses_attempted=attempted, crosses_completed=completed,
                               open_play_crosses_attempted=oa+ob, open_play_crosses_completed=oc+od,
                               dribbles_made=dribbles)
        rows.append(row)
    available = sum(row['state'] == 'available_native_statistic_observation' for row in rows)
    return {'state': 'available' if available == len(rows) else 'available_partial' if available else 'unavailable',
            'source': 'typed_owned_resident_GAME_MATCH_PLAYER_STATS_crossing_and_dribbling',
            'official_match_unique_id': expected_match_unique_id,
            'rows': rows,
            'coverage': {'resident_slots': len(rows), 'available_statistic_rows': available,
                         'unavailable_rows': len(rows) - available,
                         'complete_on_pitch_population_verified': False},
            'statistic_units': 'crosses and DribblesMade: stored unsigned byte0..255; open-play crosses: sum of two unsigned bytes0..510',
            'native_timestamp_association': False,
            'displayed_time_verified': False,
            'counter_publication_fence_verified': False,
            'atomic_snapshot_verified': False,
            'participation_verified': False,
            'complete_side_total_verified': False,
            'scope': 'Resident counter bytes requiring caller recheck. No native tick, displayed minute, '
                     'halftime, completion, live-versus-replay or on-pitch claim. Open-play crossing '
                     'values sum the two native unsigned-byte buckets without byte wrapping. No flank, '
                     'receiver, delivery quality, aerial winner, dribble-attempt denominator, carry '
                     'distance or tactical cause is established; no completion rate is derived.'}
