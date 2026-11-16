"""Current raw attacking fields; synthetic edits remain explicitly controls."""
from historical_match_identity_fixture import historical_team_identity_contract
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import current_player_match_statistics as statistics, world

FIELDS = ('shots', 'shots_on_target', 'key_passes', 'chances_created')
PACKET = Path(__file__).resolve().parent/'fixtures/current_player_match_statistics147.json.gz'


class Original:
    historical_identity_fixture = PACKET.name
    def __init__(self):
        raw = gzip.decompress(PACKET.read_bytes())
        assert hashlib.sha256(raw).hexdigest() == '12e51bfd9224e8d5a535202823e7a2c4d8ac465ef1295b249ba395fc5f924ed8'
        self.packet = json.loads(raw); self.memory = {}; self.reads = []
        for region in self.packet['raw_consumed_byte_journal']['regions']:
            at = int(region['address'], 16)
            for i, byte in enumerate(bytes.fromhex(region['rawhex'])):
                assert at+i not in self.memory or self.memory[at+i] == byte
                self.memory[at+i] = byte
        self.base = int(self.packet['plugin']['base_private'], 16)
        self.engine = self.packet['context_before']['private']['engine']
        self.uid = self.packet['context_before']['official_match_unique_id']

    def read(self, at, size):
        self.reads.append((at, size))
        try:
            return bytes(self.memory[at+i] for i in range(size))
        except KeyError as error:
            raise ValueError('Missing original captured byte') from error

    def write(self, at, raw):
        for i, byte in enumerate(raw): self.memory[at+i] = byte

    def run(self):
        read = world.ReadSet(self.read)
        result = statistics.inspect(read, self.base, self.engine, expected_match_unique_id=self.uid)
        read.verify()
        return result

    def numeric(self):
        return next(row for row in self.packet['rows'] if row['raw_action_bytes'])


def test_actual52_rows37_numeric15_unknown_with_original_bytes():
    f = Original(); result = f.run()
    assert result['state'] == 'available_partial'
    assert result['coverage'] == {'resident_slots': 52, 'available_statistic_rows': 37,
                                  'unavailable_rows': 15, 'complete_on_pitch_population_verified': False}
    for public, raw in zip(result['rows'], f.packet['rows'], strict=True):
        for field in ('side_index', 'engine_array_index', 'identity_state', 'person'):
            assert public[field] == raw[field]
        if raw['raw_action_bytes']:
            data = raw['raw_action_bytes']
            shots, target = bytes.fromhex(data['native90_91'])
            key, = bytes.fromhex(data['nativeBC']); chances, = bytes.fromhex(data['nativeA0'])
            assert public['state'] == 'available_native_statistic_observation'
            assert tuple(public[n] for n in FIELDS) == (shots, target, key, chances)
        else:
            assert public['state'] == raw['state'] and all(public[n] is None for n in FIELDS)
    by_name = {row['person']['name']: row for row in result['rows'] if row['person']}
    assert tuple(by_name['Luiz Henrique'][n] for n in FIELDS) == (3, 2, 4, 3)
    assert tuple(by_name['Chema Andrés'][n] for n in FIELDS) == (0, 0, 2, 0)
    assert tuple(by_name['Nick Woltemade'][n] for n in FIELDS) == (2, 2, 1, 0)
    assert any(all(row[n] == 0 for n in FIELDS) for row in result['rows'])
    for flag in ('native_timestamp_association', 'displayed_time_verified', 'counter_publication_fence_verified',
                 'atomic_snapshot_verified', 'participation_verified', 'complete_side_total_verified'):
        assert result[flag] is False
    assert all(at+size <= f.engine+0x154DC or f.engine+0x154DC+4 <= at for at, size in f.reads)
    assert all(size != 0xC0 for _, size in f.reads)


@pytest.mark.parametrize('values', [(0, 0, 0, 0), (255, 255, 255, 255), (0, 255, 128, 127)])
def test_synthetic_unsigned_extremes_preserved_without_invented_rates(values):
    f = Original(); raw = f.numeric(); stats = int(raw['stats_private'], 16)
    f.write(stats+0x90, bytes(values[:2])); f.write(stats+0xBC, bytes([values[2]])); f.write(stats+0xA0, bytes([values[3]]))
    row = f.run()['rows'][raw['side_index']*26+raw['engine_array_index']]
    assert tuple(row[n] for n in FIELDS) == values
    assert not any('percentage' in n for n in row)


@pytest.mark.parametrize('offset', [0x90, 0x91, 0xA0, 0xBC])
def test_missing_actual_statistic_byte_refuses(offset):
    f = Original(); del f.memory[int(f.numeric()['stats_private'], 16)+offset]
    with pytest.raises(ValueError, match='Missing original captured byte'): f.run()


def test_changed_native_field_sources_refuse():
    for at, raw in (*statistics.SOURCE_SPANS, *statistics.people.ACTOR_SLOT_SPANS):
        f = Original(); f.write(f.base+at, bytes([raw[0]^1])+raw[1:])
        with pytest.raises(ValueError, match='native source changed'): f.run()


@pytest.mark.parametrize('kind', ['null_stats', 'stats_person_mismatch'])
def test_unavailable_stats_preserve_nulls(kind):
    f = Original(); raw = f.numeric(); mp = int(raw['match_player_private'], 16)
    if kind == 'null_stats':
        f.write(mp+0x1880, bytes(8)); state = 'unavailable_stats'
    else:
        f.write(int(raw['stats_private'], 16)+0x18, struct.pack('<I', raw['stats_person_index']+1)); state = 'unavailable_stats_person_mismatch'
    row = f.run()['rows'][raw['side_index']*26+raw['engine_array_index']]
    assert row['state'] == state and all(row[n] is None for n in FIELDS)


def test_changed_type_owner_and_original_slot_refuse():
    for field, offset, value in [('stats_private', 0, None), ('match_player_private', 0x280, bytes(8)),
                                 ('match_player_private', 0x288, struct.pack('<Q', 0x1000)), ('match_player_private', 0x1E27, b'\xFF')]:
        f = Original(); raw = f.numeric()
        f.write(int(raw[field], 16)+offset, value if value is not None else struct.pack('<Q', f.base+0x55FA850))
        with pytest.raises(ValueError): f.run()


def test_absent_side_owner_is_unknown_instead_of_a_fake_statistic():
    f = Original(); raw = f.numeric(); f.write(int(raw['match_player_private'], 16)+0x288, bytes(8))
    row = f.run()['rows'][raw['side_index']*26+raw['engine_array_index']]
    assert row['identity_state'] == 'side_owner_absent_unclassified'
    assert row['person'] is None and all(row[n] is None for n in FIELDS)


def test_final_physical_recheck_rejects_late_statistic_change():
    f = Original(); read = world.ReadSet(f.read)
    statistics.inspect(read, f.base, f.engine, expected_match_unique_id=f.uid)
    at = int(f.numeric()['stats_private'], 16)+0xBC; f.write(at, bytes([f.read(at, 1)[0]^1]))
    with pytest.raises(ValueError, match='Game state changed'): read.verify()


@pytest.mark.parametrize('uid', [None, False, True, 0, -1, 1 << 64])
def test_strict_official_match_identity(uid):
    f = Original()
    with pytest.raises(ValueError):
        statistics.inspect(f.read, f.base, f.engine, expected_match_unique_id=uid)
