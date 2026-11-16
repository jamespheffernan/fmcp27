"""Actual typed runtime bytes; invalid-source edits are synthetic controls."""
from historical_match_identity_fixture import historical_team_identity_contract
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import current_player_defensive_statistics as defensive
from fm_live_mcp import current_player_running_statistics as running, world

PACKET = Path(__file__).resolve().parent/'fixtures/current_player_defence_running147.json.gz'
DEFENSIVE = ('tackles_attempted', 'tackles_completed', 'interceptions', 'clearances')
RUNNING = ('distance_metres', 'sprints')


class Original:
    historical_identity_fixture = PACKET.name
    def __init__(self):
        raw = gzip.decompress(PACKET.read_bytes())
        assert hashlib.sha256(raw).hexdigest() == 'b6f6e2c93b40de4fab0101157d4ab9e06a7041c44d914529b3388837800eca7e'
        self.packet = json.loads(raw); self.memory = {}; self.reads = []
        for region in self.packet['raw_consumed_byte_journal']['regions']:
            at = int(region['address'], 16)
            for i, value in enumerate(bytes.fromhex(region['rawhex'])):
                assert at+i not in self.memory or self.memory[at+i] == value
                self.memory[at+i] = value
        self.base = int(self.packet['plugin']['base_private'], 16)
        self.engine = self.packet['context_before']['private']['engine']
        self.uid = self.packet['context_before']['official_match_unique_id']

    def read(self, at, size):
        self.reads.append((at, size))
        try: return bytes(self.memory[at+i] for i in range(size))
        except KeyError as error: raise ValueError('Missing original captured byte') from error

    def write(self, at, raw):
        for i, value in enumerate(raw): self.memory[at+i] = value

    def numeric(self):
        return next(row for row in self.packet['rows'] if row['raw_defence_running_bytes'])

    def run(self, module):
        read = world.ReadSet(self.read)
        value = module.inspect(read, self.base, self.engine, expected_match_unique_id=self.uid)
        read.verify()
        return value


@pytest.mark.parametrize('module,fields', [(defensive, DEFENSIVE), (running, RUNNING)])
def test_actual37_numeric15_unknown_rows_with_original_bytes(module, fields):
    f = Original(); out = f.run(module)
    assert out['state'] == 'available_partial'
    assert out['coverage'] == {'resident_slots': 52, 'available_statistic_rows': 37,
                               'unavailable_rows': 15, 'complete_on_pitch_population_verified': False}
    for row, original in zip(out['rows'], f.packet['rows'], strict=True):
        for key in ('side_index', 'engine_array_index', 'identity_state', 'person'): assert row[key] == original[key]
        raw = original['raw_defence_running_bytes']
        if raw:
            assert row['state'] == 'available_native_statistic_observation'
            if module is defensive:
                a, b = bytes.fromhex(raw['nativeC6_C7'])
                assert tuple(row[n] for n in fields) == (a, b, int(raw['nativeCF'], 16), int(raw['nativeD9'], 16))
            else:
                assert row['distance_metres'] == struct.unpack('<f', bytes.fromhex(raw['native68_f32']))[0]
                assert row['sprints'] == int(raw['nativeF5'], 16)
        else:
            assert row['state'] == original['state'] and all(row[n] is None for n in fields)
    by_name = {r['person']['name']: r for r in out['rows'] if r['person']}
    if module is defensive:
        assert tuple(by_name['Chema Andrés'][n] for n in fields) == (2, 1, 3, 0)
        assert by_name['Chadi Riad']['interceptions'] == 5
        assert by_name['Gregor Kobel']['clearances'] == 1
    else:
        assert by_name['Tino Livramento']['distance_metres'] == 7117.47705078125
        assert by_name['Tino Livramento']['sprints'] == 13
        assert by_name['Gregor Kobel']['sprints'] == 0
    assert any(all(r[n] == 0 for n in fields) for r in out['rows'])
    for flag in ('native_timestamp_association', 'displayed_time_verified', 'counter_publication_fence_verified',
                 'atomic_snapshot_verified', 'participation_verified', 'complete_side_total_verified'):
        assert out[flag] is False
    assert all(at+size <= f.engine+0x154DC or f.engine+0x154DC+4 <= at for at, size in f.reads)
    assert all(size != 0xC0 for _, size in f.reads)


def test_synthetic_unsigned_counts_keep255_and_zero_without_invented_rates():
    f = Original(); raw = f.numeric(); stats = int(raw['stats_private'], 16)
    f.write(stats+0xC6, bytes([0, 255])); f.write(stats+0xCF, b'\xFF'); f.write(stats+0xD9, b'\x00')
    row = f.run(defensive)['rows'][raw['side_index']*26+raw['engine_array_index']]
    assert tuple(row[n] for n in DEFENSIVE) == (0, 255, 255, 0)
    assert not any('percentage' in n for n in row)
    f.write(stats+0xF5, b'\xFF')
    assert f.run(running)['rows'][raw['side_index']*26+raw['engine_array_index']]['sprints'] == 255


@pytest.mark.parametrize('value', [-1.0, float('nan'), float('inf'), float('-inf')])
def test_synthetic_invalid_distance_refuses_instead_of_zero(value):
    f = Original(); f.write(int(f.numeric()['stats_private'], 16)+0x68, struct.pack('<f', value))
    with pytest.raises(ValueError, match='Invalid native resident distance'): f.run(running)


@pytest.mark.parametrize('value', [0.0, 1.0, 1234.5])
def test_synthetic_raw_distance_keeps_native_metres_without_1000x_change(value):
    f = Original(); raw = f.numeric(); f.write(int(raw['stats_private'], 16)+0x68, struct.pack('<f', value))
    assert f.run(running)['rows'][raw['side_index']*26+raw['engine_array_index']]['distance_metres'] == value


@pytest.mark.parametrize('module,offset', [(defensive, 0xC6), (defensive, 0xC7), (defensive, 0xCF), (defensive, 0xD9), (running, 0x68), (running, 0x6B), (running, 0xF5)])
def test_missing_real_statistic_byte_refuses(module, offset):
    f = Original(); del f.memory[int(f.numeric()['stats_private'], 16)+offset]
    with pytest.raises(ValueError, match='Missing original captured byte'): f.run(module)


@pytest.mark.parametrize('module', [defensive, running])
def test_changed_named_native_sources_refuse(module):
    for at, raw in (*module.SOURCE_SPANS, *module.people.ACTOR_SLOT_SPANS):
        f = Original(); f.write(f.base+at, bytes([raw[0]^1])+raw[1:])
        with pytest.raises(ValueError, match='native source changed'): f.run(module)


@pytest.mark.parametrize('module,fields', [(defensive, DEFENSIVE), (running, RUNNING)])
@pytest.mark.parametrize('kind', ['null_stats', 'stats_person_mismatch', 'absent_owner'])
def test_unavailable_context_keeps_all_fields_null(module, fields, kind):
    f = Original(); raw = f.numeric(); mp = int(raw['match_player_private'], 16)
    if kind == 'null_stats': f.write(mp+0x1880, bytes(8)); state = 'unavailable_stats'
    elif kind == 'absent_owner': f.write(mp+0x288, bytes(8)); state = 'unavailable_identity'
    else: f.write(int(raw['stats_private'], 16)+0x18, struct.pack('<I', raw['stats_person_index']+1)); state = 'unavailable_stats_person_mismatch'
    row = f.run(module)['rows'][raw['side_index']*26+raw['engine_array_index']]
    assert row['state'] == state and all(row[n] is None for n in fields)


@pytest.mark.parametrize('module,offset', [(defensive, 0xCF), (running, 0x68)])
def test_final_physical_recheck_rejects_late_changes(module, offset):
    f = Original(); read = world.ReadSet(f.read)
    module.inspect(read, f.base, f.engine, expected_match_unique_id=f.uid)
    at = int(f.numeric()['stats_private'], 16)+offset; f.write(at, bytes([f.read(at, 1)[0]^1]))
    with pytest.raises(ValueError, match='Game state changed'): read.verify()
