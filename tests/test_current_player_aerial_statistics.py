"""Actual typed runtime bytes; invalid-source edits are synthetic controls."""
from historical_match_identity_fixture import historical_team_identity_contract
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import current_player_aerial_statistics as aerial
from fm_live_mcp import world

PACKET = Path(__file__).resolve().parent/'fixtures/current_player_aerial147.json.gz'
FIELDS = ('aerial_duels_attempted','aerial_duels_completed')


class Original:
    historical_identity_fixture = PACKET.name
    def __init__(self):
        raw = gzip.decompress(PACKET.read_bytes())
        assert hashlib.sha256(raw).hexdigest() == '8295f6ea0381fba648a92708fb2aaf1f6bc734a1ae2a707275568a2245490982'
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
        return next(row for row in self.packet['rows'] if row['raw_aerial_bytes'])

    def run(self, module):
        read = world.ReadSet(self.read)
        value = module.inspect(read, self.base, self.engine, expected_match_unique_id=self.uid)
        read.verify()
        return value


@pytest.mark.parametrize('module,fields', [(aerial, FIELDS)])
def test_actual37_numeric15_unknown_rows_with_original_bytes(module, fields):
    f = Original(); out = f.run(module)
    assert out['state'] == 'available_partial'
    assert out['coverage'] == {'resident_slots': 52, 'available_statistic_rows': 37,
                               'unavailable_rows': 15, 'complete_on_pitch_population_verified': False}
    for row, original in zip(out['rows'], f.packet['rows'], strict=True):
        for key in ('side_index', 'engine_array_index', 'identity_state', 'person'): assert row[key] == original[key]
        raw = original['raw_aerial_bytes']
        if raw:
            assert row['state'] == 'available_native_statistic_observation'
            assert tuple(row[n] for n in fields)==tuple(bytes.fromhex(raw['nativeCA_CB']))
        else:
            assert row['state'] == original['state'] and all(row[n] is None for n in fields)
    assert any(all(r[n] == 0 for n in fields) for r in out['rows'])
    by_name={row['person']['name']:row for row in out['rows'] if row['person']}
    assert tuple(by_name['Nick Woltemade'][n] for n in fields)==(3,2)
    assert tuple(by_name['Chema Andrés'][n] for n in fields)==(2,0)
    assert out['official_property_labels']['aerial_duels_completed']=='AerialDuelsCompleted'
    for flag in ('native_timestamp_association', 'displayed_time_verified', 'counter_publication_fence_verified',
                 'atomic_snapshot_verified', 'participation_verified', 'complete_side_total_verified'):
        assert out[flag] is False
    assert all(at+size <= f.engine+0x154DC or f.engine+0x154DC+4 <= at for at, size in f.reads)
    assert all(size != 0xC0 for _, size in f.reads)


def test_synthetic_unsigned_counts_keep255_and_zero_without_invented_rates():
    f = Original(); raw = f.numeric(); stats = int(raw['stats_private'], 16)
    f.write(stats+0xCA,bytes([0,255]))
    row = f.run(aerial)['rows'][raw['side_index']*26+raw['engine_array_index']]
    assert tuple(row[n] for n in FIELDS) == (0,255)
    assert not any('percentage' in n for n in row)


@pytest.mark.parametrize('module,offset', [(aerial,0xCA),(aerial,0xCB)])
def test_missing_real_statistic_byte_refuses(module, offset):
    f = Original(); del f.memory[int(f.numeric()['stats_private'], 16)+offset]
    with pytest.raises(ValueError, match='Missing original captured byte'): f.run(module)


@pytest.mark.parametrize('module', [aerial])
def test_changed_named_native_sources_refuse(module):
    for at, raw in (*module.SOURCE_SPANS, *module.people.ACTOR_SLOT_SPANS):
        f = Original(); f.write(f.base+at, bytes([raw[0]^1])+raw[1:])
        with pytest.raises(ValueError, match='native source changed'): f.run(module)


@pytest.mark.parametrize('module,fields', [(aerial, FIELDS)])
@pytest.mark.parametrize('kind', ['null_stats', 'stats_person_mismatch', 'absent_owner'])
def test_unavailable_context_keeps_all_fields_null(module, fields, kind):
    f = Original(); raw = f.numeric(); mp = int(raw['match_player_private'], 16)
    if kind == 'null_stats': f.write(mp+0x1880, bytes(8)); state = 'unavailable_stats'
    elif kind == 'absent_owner': f.write(mp+0x288, bytes(8)); state = 'unavailable_identity'
    else: f.write(int(raw['stats_private'], 16)+0x18, struct.pack('<I', raw['stats_person_index']+1)); state = 'unavailable_stats_person_mismatch'
    row = f.run(module)['rows'][raw['side_index']*26+raw['engine_array_index']]
    assert row['state'] == state and all(row[n] is None for n in fields)


@pytest.mark.parametrize('module,offset', [(aerial,0xCA),(aerial,0xCB)])
def test_final_physical_recheck_rejects_late_changes(module, offset):
    f = Original(); read = world.ReadSet(f.read)
    module.inspect(read, f.base, f.engine, expected_match_unique_id=f.uid)
    at = int(f.numeric()['stats_private'], 16)+offset; f.write(at, bytes([f.read(at, 1)[0]^1]))
    with pytest.raises(ValueError, match='Game state changed'): read.verify()


@pytest.mark.parametrize('kind', ['wrong_match', 'wrong_owner', 'wrong_stats_type', 'wrong_original_slot'])
def test_fixture_and_concrete_source_invariants_refuse(kind):
    f = Original(); raw = f.numeric(); mp = int(raw['match_player_private'], 16)
    if kind == 'wrong_match': f.write(f.engine+0x20, struct.pack('<Q', f.uid+1))
    elif kind == 'wrong_owner': f.write(mp+0x288, struct.pack('<Q', f.engine))
    elif kind == 'wrong_stats_type': f.write(int(raw['stats_private'], 16), struct.pack('<Q', f.base+0x55FA258))
    else: f.write(mp+0x1E27, bytes([(raw['engine_array_index']+1) % 26]))
    with pytest.raises(ValueError): f.run(aerial)
