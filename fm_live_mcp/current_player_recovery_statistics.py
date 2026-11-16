"""Typed resident PLAYER possession and pressure counters, without a native clock association.

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
    (0x205570, bytes.fromhex('e15e4339e023009152fa0795e0630091e223009181488852814ea87256c70795')),
    (0x205598, bytes.fromhex('e1624339e023009148fa0795e0630091e2230091612c8f522168ac724cc70795')),
    (0x2056e4, bytes.fromhex('e1b64339e023009102fa0795e0630091e22300914106875201e6ae72f9c60795')),
    (0x4ad3ff4, bytes.fromhex('4140009021d41391e03740f902008012')),
    (0x52db4f5, bytes.fromhex('7072657373757265735f617474656d7074656400')),
    (0x52db509, bytes.fromhex('7072657373757265735f636f6d706c6574696f6e00')),
    (0x49adb54, bytes.fromhex('81018052e40317aa2500805223090094fc0300aa')),
    (0x49adc20, bytes.fromhex('a101271e0018211e0d00241e0d1d03391a2103391cb1033900b50339')),
    (0x4956450, bytes.fromhex('887241f93f050031a0000054e81b00b40a0140b95f01096be1000054091100911f0100f1c002899ae10313aa9463069480220034151900b4a90240b9887641f93f050031a0000054a81a00b40a0140b95f01096be1000054091100911f0100f1c002899ae10313aa85630694e0200034d51700b4a90240b9887a41f93f050031a0000054681900b40a0140b95f01096b')),
    (0x49568d0, bytes.fromhex('8801805274ffff17a801805272ffff17')),
    (0x493c558, bytes.fromhex('c86a427908050011c86a0279970000b4e8b2433908050011e8b20339')),
    (0x493cc60, bytes.fromhex('1f35007101e20054c86e427908050011c86e027997e100b4e8b6433908050011e8b60339')),
)


def inspect(read, base, engine, *, expected_match_unique_id):
    """Read only named possession and pressure fields after same-side PERSON and concrete stats reconciliation.

    No native clock is accepted or derived. A null or mismatched source remains
    unavailable; stored0 is an actual unsigned byte0. No sum claims a side total.
    Caller must recheck every consumed byte after its last lifetime callback.
    """
    if type(expected_match_unique_id) is not int or not 0 < expected_match_unique_id < 1 << 64:
        raise ValueError('A checked nonzero official match unique ID is required')
    people._type(read, base, engine, 0x55FA258, b'10GAME_MATCH')
    if people._u64(read, engine + 0x20) != expected_match_unique_id:
        raise ValueError('PLAYER recovery statistics official match identity changed')
    for offset, raw in (*SOURCE_SPANS, *people.ACTOR_SLOT_SPANS):
        if people._read(read, base + offset, len(raw)) != raw:
            raise ValueError('PLAYER recovery statistics native source changed')
    actors = people.inspect_canonical(read, base, engine, identity_only=True)
    rows = []
    identities = set()
    for actor in actors['rows']:
        side_index, index = actor['side_index'], actor['engine_array_index']
        identity = actor['person']
        row = {'side_index': side_index, 'engine_array_index': index,
               'identity_state': actor['identity_state'], 'person': identity,
               'state': 'unavailable_identity', 'possession_won': None, 'possession_lost': None,
               'pressures_attempted': None, 'pressures_completed': None}
        if identity is not None:
            key = side_index, identity['native_identity']['database_index']
            if key in identities:
                raise ValueError('Duplicate canonical PLAYER recovery statistics identity')
            identities.add(key)
            side = people._u64(read, engine + 0x15370 + side_index * 8)
            player = people._u64(read, side + 0x140 + index * 8)
            people._type(read, base, player, 0x569EE68, b'N7simatch12MATCH_PLAYERE')
            if (people._u64(read, player + 0x280) != engine
                    or people._u64(read, player + 0x288) != side):
                raise ValueError('PLAYER recovery statistics owner changed')
            if people._read(read, player + 0x1E27, 1)[0] != index:
                raise ValueError('PLAYER recovery statistics original roster slot changed')
            stats = people._u64(read, player + 0x1880)
            row['state'] = 'unavailable_stats'
            if stats:
                people._type(read, base, stats, 0x55FA800, b'23GAME_MATCH_PLAYER_STATS')
                ordinal = struct.unpack('<I', people._read(read, stats + 0x18, 4))[0]
                row['state'] = 'unavailable_stats_person_mismatch'
                if ordinal == identity['native_identity']['database_index']:
                    won, lost = people._read(read, stats + 0xD7, 2)
                    attempted, completed = people._read(read, stats + 0xEC, 2)
                    row.update(state='available_native_statistic_observation',
                               possession_won=won, possession_lost=lost,
                               pressures_attempted=attempted, pressures_completed=completed)
        rows.append(row)
    available = sum(row['state'] == 'available_native_statistic_observation' for row in rows)
    return {'state': 'available' if available == len(rows) else 'available_partial' if available else 'unavailable',
            'source': 'typed_owned_resident_GAME_MATCH_PLAYER_STATS_possession_and_pressure',
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
            'pressures_attempted_source': 'named_QME_STAT_MANAGER_stat12_writer_nativeEC; no supported individual property getter',
            'scope': 'Resident counter bytes requiring caller recheck. No native tick, displayed minute, '
                     'halftime, completion, live-versus-replay or on-pitch claim. Statistical pressure '
                     'completion does not establish possession regained, pressure location, difficulty or '
                     'tactical cause. Native bytes may wrap; no pressure completion rate is derived.'}
