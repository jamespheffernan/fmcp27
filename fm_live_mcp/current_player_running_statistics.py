"""Typed resident PLAYER running counters, without a native clock association.

Caller owns the current fixture/incarnation, runtime/ReadSet and final epoch
checks. This module neither attaches nor publishes a host observation. Native
unsigned byte counters are observations, not cursor/halftime totals, appearances,
complete squad membership or evidence of current on-pitch participation.
"""
import math
import struct

from . import active_match_people as people

# Exact named native consumers/exporters; no retained wire offsets are used.
# MATCH_PLAYER+1880 assignment, original-slot setup and canonical actor guards
# are independently pinned by ACTOR_SLOT_SPANS in the caller's same ReadSet.
SOURCE_SPANS = (
    (0x266c4c, bytes.fromhex('89cc89526948ae721f01096b40230054')),
    (0x2670c0, bytes.fromhex('010080525aaa219508000014')),
    (0x4ad1a2c, bytes.fromhex('61000034006840bdc0035fd6006840bd284100b001b54fbd0008211e')),
    (0x52f6fb4, bytes.fromhex('6f12833a')),
    (0x266ccc, bytes.fromhex('69ea86526949af721f01096be12300548fab2195e10300aafd000014')),
    (0x4ad1b18, bytes.fromhex('00d44339c0035fd6')),
    (0x2054f0, bytes.fromhex('e00317aa89312395e10300aae023009170fa0795e0630091e223009161ea86526149af7274c70795')),
)


def inspect(read, base, engine, *, expected_match_unique_id):
    """Read only named running fields after same-side PERSON and concrete stats reconciliation.

    No native clock is accepted or derived. A null or mismatched source remains
    unavailable; stored0 is an actual unsigned byte0. No sum claims a side total.
    Caller must recheck every consumed byte after its last lifetime callback.
    """
    if type(expected_match_unique_id) is not int or not 0 < expected_match_unique_id < 1 << 64:
        raise ValueError('A checked nonzero official match unique ID is required')
    people._type(read, base, engine, 0x55FA258, b'10GAME_MATCH')
    if people._u64(read, engine + 0x20) != expected_match_unique_id:
        raise ValueError('PLAYER running statistics official match identity changed')
    for offset, raw in (*SOURCE_SPANS, *people.ACTOR_SLOT_SPANS):
        if people._read(read, base + offset, len(raw)) != raw:
            raise ValueError('PLAYER running statistics native source changed')
    actors = people.inspect_canonical(read, base, engine, identity_only=True)
    rows = []
    identities = set()
    for actor in actors['rows']:
        side_index, index = actor['side_index'], actor['engine_array_index']
        identity = actor['person']
        row = {'side_index': side_index, 'engine_array_index': index,
               'identity_state': actor['identity_state'], 'person': identity,
               'state': 'unavailable_identity', 'distance_metres': None, 'sprints': None}
        if identity is not None:
            key = side_index, identity['native_identity']['database_index']
            if key in identities:
                raise ValueError('Duplicate canonical PLAYER running statistics identity')
            identities.add(key)
            side = people._u64(read, engine + 0x15370 + side_index * 8)
            player = people._u64(read, side + 0x140 + index * 8)
            people._type(read, base, player, 0x569EE68, b'N7simatch12MATCH_PLAYERE')
            if (people._u64(read, player + 0x280) != engine
                    or people._u64(read, player + 0x288) != side):
                raise ValueError('PLAYER running statistics owner changed')
            if people._read(read, player + 0x1E27, 1)[0] != index:
                raise ValueError('PLAYER running statistics original roster slot changed')
            stats = people._u64(read, player + 0x1880)
            row['state'] = 'unavailable_stats'
            if stats:
                people._type(read, base, stats, 0x55FA800, b'23GAME_MATCH_PLAYER_STATS')
                ordinal = struct.unpack('<I', people._read(read, stats + 0x18, 4))[0]
                row['state'] = 'unavailable_stats_person_mismatch'
                if ordinal == identity['native_identity']['database_index']:
                    distance, = struct.unpack('<f', people._read(read, stats + 0x68, 4))
                    if not math.isfinite(distance) or distance < 0:
                        raise ValueError('Invalid native resident distance in metres')
                    sprints = people._read(read, stats + 0xF5, 1)[0]
                    row.update(state='available_native_statistic_observation',
                               distance_metres=distance, sprints=sprints)
        rows.append(row)
    available = sum(row['state'] == 'available_native_statistic_observation' for row in rows)
    return {'state': 'available' if available == len(rows) else 'available_partial' if available else 'unavailable',
            'source': 'typed_owned_resident_GAME_MATCH_PLAYER_STATS_running_statistics',
            'official_match_unique_id': expected_match_unique_id,
            'rows': rows,
            'coverage': {'resident_slots': len(rows), 'available_statistic_rows': available,
                         'unavailable_rows': len(rows) - available,
                         'complete_on_pitch_population_verified': False},
            'statistic_units': {'distance_metres': 'unscaled float32 metres', 'sprints': 'unsigned native stored byte0..255'},
            'native_timestamp_association': False,
            'displayed_time_verified': False,
            'counter_publication_fence_verified': False,
            'atomic_snapshot_verified': False,
            'participation_verified': False,
            'complete_side_total_verified': False,
            'scope': 'Resident counter bytes requiring caller recheck. No native tick, displayed minute, '
                     'halftime, completion, live-versus-replay or on-pitch claim. Distance and Sprints '
                     'do not establish effort, sprint thresholds, high-intensity distance or tactical effects.'}
