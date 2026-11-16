"""Typed resident PLAYER keeper-save and discipline counters, without a native clock association.

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
    (0x2052b0, bytes.fromhex('e1664239e02300910ffb0795e0630091e223009161668c5261acac7206c80795')),
    (0x2052d8, bytes.fromhex('e16a4239e023009105fb0795e0630091e2230091012b865241efaa72fcc70795')),
    (0x205330, bytes.fromhex('e16e4239e0230091effa0795e0630091e2230091010d8952e1ada972e6c70795')),
    (0x205734, bytes.fromhex('e86e4239e96a4239ea6642392801080b08010a0be0230091011d0012e9f90795e0630091e2230091a12c8752a1aaa872e0c60795')),
    (0x2f10c6c, bytes.fromhex('811201d02174259102008012a0e05194d38e423915cc539408e00091b30318b8a88317f8a0c302d1e1c30291a22302d1a0646197a08357f8')),
    (0x2f10cd8, bytes.fromhex('811201d021b425910200801285e05194d39a4239facb53947f060071e8179f1a09e00091a80318b8a98317f8a0c302d1e1c30291a22302d1')),
    (0x2f10d4c, bytes.fromhex('811201d0210c26910200801268e05194d39e4239ddcb539408e00091b30318b8a88317f8a0c302d1e1c30291a22302d168646197a08357f8')),
    (0x516295d, bytes.fromhex('666f756c735f636f6d6d697474656400')),
    (0x516296d, bytes.fromhex('79656c6c6f775f63617264735f726563656976656400')),
    (0x5162983, bytes.fromhex('7265645f63617264735f726563696576656400')),
)


def inspect(read, base, engine, *, expected_match_unique_id):
    """Read only named keeper-save and discipline fields after same-side PERSON and concrete stats reconciliation.

    No native clock is accepted or derived. A null or mismatched source remains
    unavailable; stored0 is an actual unsigned byte0. No sum claims a side total.
    Caller must recheck every consumed byte after its last lifetime callback.
    """
    if type(expected_match_unique_id) is not int or not 0 < expected_match_unique_id < 1 << 64:
        raise ValueError('A checked nonzero official match unique ID is required')
    people._type(read, base, engine, 0x55FA258, b'10GAME_MATCH')
    if people._u64(read, engine + 0x20) != expected_match_unique_id:
        raise ValueError('PLAYER keeper/incident statistics official match identity changed')
    for offset, raw in (*SOURCE_SPANS, *people.ACTOR_SLOT_SPANS):
        if people._read(read, base + offset, len(raw)) != raw:
            raise ValueError('PLAYER keeper/incident statistics native source changed')
    actors = people.inspect_canonical(read, base, engine, identity_only=True)
    rows = []
    identities = set()
    for actor in actors['rows']:
        side_index, index = actor['side_index'], actor['engine_array_index']
        identity = actor['person']
        row = {'side_index': side_index, 'engine_array_index': index,
               'identity_state': actor['identity_state'], 'person': identity,
               'state': 'unavailable_identity', 'saves_held': None, 'saves_parried': None, 'saves_tipped': None, 'total_saves': None,
               'fouls_committed': None, 'yellow_cards_received': None, 'red_cards_received': None}
        if identity is not None:
            key = side_index, identity['native_identity']['database_index']
            if key in identities:
                raise ValueError('Duplicate canonical PLAYER keeper/incident statistics identity')
            identities.add(key)
            side = people._u64(read, engine + 0x15370 + side_index * 8)
            player = people._u64(read, side + 0x140 + index * 8)
            people._type(read, base, player, 0x569EE68, b'N7simatch12MATCH_PLAYERE')
            if (people._u64(read, player + 0x280) != engine
                    or people._u64(read, player + 0x288) != side):
                raise ValueError('PLAYER keeper/incident statistics owner changed')
            if people._read(read, player + 0x1E27, 1)[0] != index:
                raise ValueError('PLAYER keeper/incident statistics original roster slot changed')
            stats = people._u64(read, player + 0x1880)
            row['state'] = 'unavailable_stats'
            if stats:
                people._type(read, base, stats, 0x55FA800, b'23GAME_MATCH_PLAYER_STATS')
                ordinal = struct.unpack('<I', people._read(read, stats + 0x18, 4))[0]
                row['state'] = 'unavailable_stats_person_mismatch'
                if ordinal == identity['native_identity']['database_index']:
                    held, parried, tipped = people._read(read, stats + 0x99, 3)
                    fouls = people._read(read, stats + 0xA3, 1)[0]
                    yellow, red = people._read(read, stats + 0xA6, 2)
                    row.update(state='available_native_statistic_observation',
                               saves_held=held, saves_parried=parried, saves_tipped=tipped,
                               total_saves=(held+parried+tipped)&255, fouls_committed=fouls,
                               yellow_cards_received=yellow, red_cards_received=red)
        rows.append(row)
    available = sum(row['state'] == 'available_native_statistic_observation' for row in rows)
    return {'state': 'available' if available == len(rows) else 'available_partial' if available else 'unavailable',
            'source': 'typed_owned_resident_GAME_MATCH_PLAYER_STATS_keeper_saves_and_discipline',
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
            'total_saves_expression': '(saves_held+saves_parried+saves_tipped)&255; native TotalSaves exporter',
            'native_red_card_consumer_label': 'red_cards_recieved',
            'scope': 'Resident counter bytes requiring caller recheck. No native tick, displayed minute, '
                     'halftime, completion, live-versus-replay or on-pitch claim. Stored save values do '
                     'not establish goalkeeper role, shot difficulty, save quality or post-shot xG. '
                     'Discipline counts do not establish incident chronology, a second-yellow dismissal, '
                     'current/future disciplinary eligibility or tactical cause. Native byte wrapping '
                     'is preserved, including the explicitly wrapped TotalSaves expression.'}
