"""Exact frozen33-field source through current composition and report opt-in.

Only unrelated fixture/playback/team dispatch is isolated in the report test;
the statistic rows, native guards and final physical rechecks are actual code.
"""
from historical_match_identity_fixture import historical_team_identity_contract
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from fm_live_mcp import current_match_report as report,world
from fm_live_mcp import current_player_match_statistic_groups as statistics
from test_current_player_match_statistic_groups_joint import Joint

NEW_FIELDS = {'saves_held','saves_parried','saves_tipped','total_saves','fouls_committed',
    'yellow_cards_received','red_cards_received','aerial_duels_attempted','aerial_duels_completed'}


class Joint33:
    historical_identity_fixture = "current_player_match_statistic_groups33_153.json.gz"
    def __init__(self):
        raw = gzip.decompress((Path(__file__).parent/'fixtures/current_player_match_statistic_groups33_153.json.gz').read_bytes())
        assert hashlib.sha256(raw).hexdigest()=='a9326919abee50f3b6e12af7cf02fa23ee9b3187f909ffccef45770b1a9a4a40'
        self.packet = json.loads(raw)
        assert self.packet['accepted'] is True and self.packet['detach']=={'detached':True}
        assert self.packet['context_before']==self.packet['context_after']
        assert self.packet['all_consumed_bytes_rechecked_after_final_callback'] is True
        self.memory = {}
        for region in self.packet['raw_consumed_byte_journal']['regions']:
            at = int(region['address'],16)
            for index,value in enumerate(bytes.fromhex(region['rawhex'])):
                assert at+index not in self.memory or self.memory[at+index]==value
                self.memory[at+index] = value
        self.base = int(self.packet['plugin']['base_private'],16)
        self.engine = self.packet['context_before']['private']['engine']
        self.uid = self.packet['context_before']['official_match_unique_id']

    def read(self,at,n):
        try:return bytes(self.memory[at+index]for index in range(n))
        except KeyError as error:raise ValueError(('Missing qualified33-field byte',hex(error.args[0])))from error


def test_frozen33_source_replays_all52_slots_with38_numeric_and14_unknown_rows():
    f = Joint33()
    read = world.ReadSet(f.read)
    result = statistics.inspect(read,f.base,f.engine,expected_match_unique_id=f.uid)
    read.verify()
    assert result==f.packet['candidate_projection']
    assert result['coverage']==dict(resident_slots=52,available_statistic_rows=38,unavailable_rows=14,
        complete_on_pitch_population_verified=False)
    assert sum(row['person'] is not None for row in result['rows'])==41
    for row,physical in zip(result['rows'],f.packet['rows'],strict=True):
        raw = physical['raw_statistics150_bytes']
        if raw is None:
            assert all(row[field] is None for _,_,fields in statistics.GROUPS for field in fields)
        else:
            held,parried,tipped = bytes.fromhex(raw['native99_9B'])
            yellow,red = bytes.fromhex(raw['nativeA6_A7'])
            attempted,completed = bytes.fromhex(raw['nativeCA_CB'])
            expected = dict(saves_held=held,saves_parried=parried,saves_tipped=tipped,
                total_saves=(held+parried+tipped)&255,fouls_committed=int(raw['nativeA3'],16),
                yellow_cards_received=yellow,red_cards_received=red,
                aerial_duels_attempted=attempted,aerial_duels_completed=completed)
            assert {field:row[field]for field in NEW_FIELDS}==expected
    assert all(result[flag] is False for flag in statistics.FALSE_FLAGS)


def test_all_existing24_qualifiers_are_preserved_and_only_nine_are_added():
    old = Joint().packet['candidate_projection']['field_qualifiers']
    current = statistics._qualifiers()
    assert len(old)==24 and len(current)==33 and set(current)-set(old)==NEW_FIELDS
    assert {field:current[field]for field in old}==old
    assert current['total_saves']['native_expression']=='(saves_held+saves_parried+saves_tipped)&255'
    assert current['total_saves']['sum_wraps_to_byte'] is True
    assert current['red_cards_received']['exact_native_consumer_label']=='red_cards_recieved'


def test_actual_report_opt_in_exposes_exact33_projection_while_default_stays_unchanged(monkeypatch):
    f = Joint33()
    context = f.packet['context_before']['fixture']
    binding = f.packet['context_before']['private']
    monkeypatch.setattr(report.active_match_source,'inspect_context',lambda *_args,**_kwargs:(context,binding))
    monkeypatch.setattr(report.live_match_performance,'inspect',lambda *_args:{'isolated_team_source':True})
    monkeypatch.setattr(report,'_statistics',lambda *_args:{'isolated_team_projection':True})
    monkeypatch.setattr(report,'_playback_report',lambda *_args:{})
    read = world.ReadSet(f.read)
    result = report._inspect(read,f.base,f.packet['context_before']['save']['current_date'],
        'client_snapshot',False,include_player_statistics=True)
    read.verify()
    assert result['player_statistics']==f.packet['candidate_projection']
    default = report._inspect(world.ReadSet(f.read),f.base,f.packet['context_before']['save']['current_date'],
        'client_snapshot',False)
    assert 'player_statistics' not in default and 'player_passing' not in default


@pytest.mark.parametrize('offset',[0x99,0x9A,0x9B,0xA3,0xA6,0xA7,0xCA,0xCB])
def test_final_physical_fence_covers_every_new_source_byte(offset):
    f = Joint33()
    read = world.ReadSet(f.read)
    statistics.inspect(read,f.base,f.engine,expected_match_unique_id=f.uid)
    source = next(row for row in f.packet['rows']if row['raw_statistics150_bytes'] is not None)
    at = int(source['stats_private'],16)+offset
    f.memory[at] ^= 1
    with pytest.raises(ValueError,match='Game state changed'):read.verify()
