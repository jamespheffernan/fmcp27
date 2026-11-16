"""Credited-goal line crossings from retained MATCH_STATS60/FIXTURE31.

Native add_goal_to_stats (44A3A24) constructs type-1 area records;4943438
persists them in MATCH_STATS+88. These are goal endpoints, not shot origins.
"""
import hashlib
import math
import struct

from . import saved_match_statistics_wire as wire

MAX_FRAME_BYTES = 1024 * 1024
MAX_TAIL_ROWS = 4096
LOWER_HALF_THRESHOLD = struct.unpack('<f', bytes.fromhex('f6289c3f'))[0]  # Native1.22f.
GOAL_HEIGHT_THRESHOLD = struct.unpack('<f', bytes.fromhex('f6281c40'))[0]  # Native2.44f.


class _Reader:
    def __init__(self, raw, start):
        self.raw = raw
        self.at = start

    def take(self, count):
        if count < 0 or self.at + count > len(self.raw):
            raise ValueError('Truncated retained goal-crossing tail')
        value = self.raw[self.at:self.at + count]
        self.at += count
        return value

    def uint(self, count):
        return int.from_bytes(self.take(count), 'little')

    def reference(self):
        mode = self.uint(1)
        value = self.uint(4 if mode >= 2 else 8)
        if mode < 2 and value != 2**64 - 1 and value > 2**32 - 2:
            raise ValueError('Retained goal-crossing reference overflow')
        return value

    def count16(self):
        count = int.from_bytes(self.take(2), 'little', signed=True)
        if not 0 <= count <= MAX_TAIL_ROWS:
            raise ValueError('Unsupported retained goal-crossing collection count')
        return count


def _zone_tail(raw, start):
    r = _Reader(raw, start)
    if r.uint(1) != 0:
        raise ValueError('Unsupported retained goal-crossing optional tail child')
    r.take(5 + 1 + 2 + 2 + 1 + 1)
    if r.uint(1) < 2:
        raise ValueError('Unsupported retained goal-crossing legacy tail reference')
    r.take(4)
    for _ in range(r.count16()):
        version = r.uint(1)
        if version not in (1, 2, 3):
            raise ValueError('Unsupported retained goal-crossing first tail row')
        r.take(4)
        r.reference()
        r.take(1)
        r.reference()
        if version >= 3:
            r.take(1)
    for _ in range(r.count16()):
        version = r.uint(1)
        if version not in (1, 2, 3):
            raise ValueError('Unsupported retained goal-crossing second tail row')
        r.take(31)
        if version >= 2:
            r.take(5)
        if version <= 2:
            r.take(16)
    rows = []
    for index in range(r.uint(1)):
        at = r.at
        rows.append((index, at, r.take(24)))
    r.take(13)
    wrapper = r.uint(1)
    if wrapper not in (0, 1):
        raise ValueError('Unsupported retained goal-crossing wrapper presence')
    remaining = len(raw) - r.at
    if (wrapper == 0 and remaining) or (wrapper == 1 and not remaining):
        raise ValueError('Retained goal-crossing wrapper extent mismatch')
    return rows, r.at, bool(wrapper)


def decode_frame(raw, fixture_key, *, scoreline=None):
    """Decode credited-goal endpoints; optional scoreline must be independently proved.

    PERSON/TEAM indices belong to this frame's source. Native horizontal axis
    viewpoint and coordinate units remain unresolved. Never attribute a keeper.
    """
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_FRAME_BYTES:
        raise ValueError('Retained goal-crossing frame budget exceeded')
    if type(fixture_key) is not int or not 0 <= fixture_key < 2**31:
        raise ValueError('Invalid retained goal-crossing fixture key')
    if scoreline is not None and (not isinstance(scoreline, (tuple, list))
            or len(scoreline) != 2 or any(type(g) is not int or not 0 <= g <= 255 for g in scoreline)):
        raise ValueError('Supply two independently proved scoreline counts')
    prefix = wire.fixture_prefix(raw)
    fixture = wire.continue_fixture(raw, prefix['end'], wire.parse_person, wire.fixture_extra)
    if fixture['fields']['scalar_u32'][0] != fixture_key:
        raise ValueError('Retained goal-crossing inner key differs from requested key')
    stats = wire.stats_prefix(raw, fixture['end'])
    teams = [t['index_word'] for t in prefix['fixture_fields8_10_team_references']]
    at = stats['end']
    players = []
    for si, team in enumerate(teams):
        side = wire.side(raw, at, parse_child=wire.player, parse_collection=wire.collection)
        if side['fields']['0x5c_raw_reference'] != team:
            raise ValueError('Retained goal-crossing side differs from fixture TEAM')
        at = side['end']
        rows = []
        for slot, child in enumerate(side['children']):
            ref = child['reference']
            delta = 0 if ref['tag'] >= 2 else 4
            rows.append({'stored_player_slot': slot,
                         'person_index': int.from_bytes(bytes.fromhex(ref['raw']), 'little'),
                         'goals': raw[child['start'] + 20 + delta]})
        players.append(rows)
    if sum(map(len, players)) > 512:
        raise ValueError('Retained goal-crossing player work budget exceeded')
    zones, end, appended = _zone_tail(raw, at)
    crossings = []
    counts = [[0] * len(p) for p in players]
    for index, offset, row in zones:
        if row[16] != 1:
            continue
        si, slot = row[14], row[13]
        if si >= len(players) or slot >= len(players[si]):
            raise ValueError('Retained goal-crossing scorer outside stored side players')
        person = players[si][slot]['person_index']
        if person >= 2**32 - 1:
            raise ValueError('Retained goal-crossing scorer reference unavailable')
        if sum(p['person_index'] == person for side in players for p in side) != 1:
            raise ValueError('Retained goal-crossing scorer reference is ambiguous')
        horizontal, height = struct.unpack_from('<ff', row)
        if not math.isfinite(horizontal) or not math.isfinite(height) or height < 0:
            raise ValueError('Invalid retained goal-crossing geometry')
        # Native goal-line writer partitions heights at1.22f and2.44f.
        band = ('lower_half' if height <= LOWER_HALF_THRESHOLD else
                'upper_half' if height <= GOAL_HEIGHT_THRESHOLD else 'above_native_goal_height')
        crossings.append({'record_index': index, 'source_byte_start': offset,
                          'side_index': si, 'team_index': teams[si],
                          'scorer_person_index': person, 'stored_player_slot': slot,
                          'native_horizontal': horizontal, 'native_height': height,
                          'height_band': band, 'coordinate_units': None,
                          'horizontal_viewpoint': 'unresolved_native_signed_axis',
                          'native_source_zone_mask': int.from_bytes(row[8:10], 'little'),
                          'native_target_zone_mask': int.from_bytes(row[10:12], 'little'),
                          'native_phase_bytes': [row[17], row[18]],
                          'native_clock_word': int.from_bytes(row[19:23], 'little'),
                          'wire24': row.hex()})
        counts[si][slot] += 1
    for side, credited in zip(counts, players):
        if any(n != p['goals'] for n, p in zip(side, credited)):
            raise ValueError('Retained goal crossings do not reconstruct credited player goals')
    goals = [sum(side) for side in counts]
    if scoreline is not None and any(n > scoreline[i] for i, n in enumerate(goals)):
        raise ValueError('Retained credited goals exceed supplied scoreline')
    gaps = None if scoreline is None else [scoreline[i] - n for i, n in enumerate(goals)]
    return {'fixture_key': fixture_key, 'source_state': 'available',
            'raw_sha256': hashlib.sha256(raw).hexdigest(), 'goal_crossings': crossings,
            'coverage': {'scope': 'credited-player goal-line crossings only',
                         'credited_goals_per_side': goals, 'player_credit_reconstruction': True,
                         'scoreline': None if scoreline is None else list(scoreline),
                         'unrepresented_scoreline_goals_per_side': gaps,
                         'complete_scoreline_goals': None if gaps is None else not any(gaps),
                         'own_goal_reason_proved': False, 'all_attempts': False,
                         'individual_keeper_attribution': False,
                         'typed_zone_rows': len(zones), 'parsed_until': end,
                         'opaque_appended_payload': appended,
                         'whole_payload_wire_parsed': not appended}}
