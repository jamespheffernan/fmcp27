"""Frozen reader149 joint24-field source; no33-field simultaneous claim."""
from historical_match_identity_fixture import historical_team_identity_contract
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import current_player_match_statistic_groups as statistics, world


class Joint:
    historical_identity_fixture = "current_player_match_statistic_groups147.json.gz"
    def __init__(self):
        raw = gzip.decompress((Path(__file__).resolve().parent/'fixtures/current_player_match_statistic_groups147.json.gz').read_bytes())
        assert hashlib.sha256(raw).hexdigest() == '4645342878a03d98c90b5ba32b04ababa29c0b6cb5aae2f2b7e7d79e9a9ce931'
        self.packet = json.loads(raw); self.memory = {}
        assert self.packet['detach']['detached'] is True
        assert self.packet['collection_stream_exit_policy'] == 'close_reader_only_no_lifetime_callback'
        for region in self.packet['raw_consumed_byte_journal']['regions']:
            at = int(region['address'],16)
            for i,value in enumerate(bytes.fromhex(region['rawhex'])):
                assert at+i not in self.memory or self.memory[at+i] == value
                self.memory[at+i] = value
        self.base = int(self.packet['plugin']['base_private'],16)
        self.engine = self.packet['context_before']['private']['engine']
        self.uid = self.packet['context_before']['official_match_unique_id']

    def read(self,at,size):
        try: return bytes(self.memory[at+i] for i in range(size))
        except KeyError as error: raise ValueError('Missing original joint captured byte') from error


def versioned149(monkeypatch,f):
    # Preserve the genuine149 source and every old qualifier assertion. Current
    #33-field acceptance requires a separate fresh source with its extra bytes.
    expected=f.packet['candidate_projection']['field_qualifiers']
    current=statistics._qualifiers()
    assert {field:current[field] for field in expected}==expected
    legacy=tuple(group for group in statistics.GROUPS if group[0] in ('attacking','defensive','running','recovery','delivery','chance_quality'))
    assert {field for _,_,fields in legacy for field in fields}==set(expected)
    monkeypatch.setattr(statistics,'GROUPS',legacy)
    monkeypatch.setattr(statistics,'_qualifiers',lambda:{field:current[field] for field in expected})


def test_genuine_reader149_joint_capture_all52_rows_and24_fields(monkeypatch):
    f = Joint(); versioned149(monkeypatch,f); read = world.ReadSet(f.read)
    out = statistics.inspect(read,f.base,f.engine,expected_match_unique_id=f.uid);read.verify()
    assert out == f.packet['candidate_projection']
    assert out['coverage'] == {'resident_slots':52,'available_statistic_rows':37,'unavailable_rows':15,'complete_on_pitch_population_verified':False}
    for row,raw in zip(out['rows'],f.packet['rows'],strict=True):
        assert all(row[n]==raw[n] for n in statistics.COMMON[:-1])
        if raw['raw_statistics_bytes'] is None:
            assert all(row[field] is None for _,_,fields in statistics.GROUPS for field in fields)
        else:
            values = raw['raw_statistics_bytes']; as_bytes = lambda key: bytes.fromhex(values[key])
            assert (row['shots'],row['shots_on_target']) == tuple(as_bytes('native90_91'))
            assert (row['tackles_attempted'],row['tackles_completed']) == tuple(as_bytes('nativeC6_C7'))
            assert (row['possession_won'],row['possession_lost']) == tuple(as_bytes('nativeD7_D8'))
            assert (row['pressures_attempted'],row['pressures_completed']) == tuple(as_bytes('nativeEC_ED'))
            assert (row['crosses_attempted'],row['crosses_completed']) == tuple(as_bytes('nativeB5_B6'))
            a,b,c,d = as_bytes('nativeDF_E2')
            assert (row['open_play_crosses_attempted'],row['open_play_crosses_completed']) == (a+b,c+d)
            for field,key in [('distance_metres','native68_f32'),('expected_goals','native1C_f32'),('expected_assists','native24_f32')]:
                assert row[field] == struct.unpack('<f',as_bytes(key))[0]
            assert row['open_play_final_third_passes'] == struct.unpack('<h',as_bytes('native10A_i16'))[0]
            for field,key in [('key_passes','nativeBC'),('chances_created','nativeA0'),('interceptions','nativeCF'),('clearances','nativeD9'),
                              ('sprints','nativeF5'),('dribbles_made','nativeA1'),('open_play_key_passes','nativeBD'),('progressive_passes','nativeF1')]:
                assert row[field] == as_bytes(key)[0]


@pytest.mark.parametrize('offset',[0x90,0xC6,0x68,0xD7,0xDF,0x1C])
def test_reader149_joint_final_physical_recheck_covers_every_group(offset,monkeypatch):
    f=Joint();versioned149(monkeypatch,f);read=world.ReadSet(f.read)
    statistics.inspect(read,f.base,f.engine,expected_match_unique_id=f.uid)
    row=next(r for r in f.packet['rows'] if r['raw_statistics_bytes'])
    at=int(row['stats_private'],16)+offset;f.memory[at]^=1
    with pytest.raises(ValueError,match='Game state changed'):read.verify()
