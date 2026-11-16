"""Synthetic composition controls; historical captures remain separate evidence.

No test joins separately timed captures and calls that a genuine joint source.
The lead's fresh all-group collector supplies that separate acceptance gate.
"""
from historical_match_identity_fixture import historical_team_identity_contract
from copy import deepcopy
import gzip
import json
from pathlib import Path

import pytest

from fm_live_mcp import current_player_match_statistic_groups as statistics, world

FIXTURES = Path(__file__).resolve().parent/'fixtures'
GROUP_FIXTURES = {'attacking': 'current_player_match_statistics147.json.gz',
                  'defensive': 'current_player_defence_running147.json.gz',
                  'running': 'current_player_defence_running147.json.gz',
                  'recovery': 'current_player_recovery147.json.gz',
                  'delivery': 'current_player_delivery147.json.gz',
                  'chance_quality': 'current_player_chance_quality147.json.gz',
                  'keeper_incident':'current_player_keeper_incident147.json.gz',
                  'aerial':'current_player_aerial147.json.gz'}


assert all(name.endswith('147.json.gz') for name in GROUP_FIXTURES.values())


class Original:
    def __init__(self, name):
        self.historical_identity_fixture = name
        assert name in GROUP_FIXTURES.values(), 'This harness supports only the declared historical147 fixtures'
        self.packet = json.loads(gzip.decompress((FIXTURES/name).read_bytes())); self.memory = {}
        for region in self.packet['raw_consumed_byte_journal']['regions']:
            at = int(region['address'], 16)
            for i, value in enumerate(bytes.fromhex(region['rawhex'])):
                assert at+i not in self.memory or self.memory[at+i] == value
                self.memory[at+i] = value
        self.base = int(self.packet['plugin']['base_private'], 16)
        self.engine = self.packet['context_before']['private']['engine']
        self.uid = self.packet['context_before']['official_match_unique_id']

    def read(self, at, size):
        try: return bytes(self.memory[at+i] for i in range(size))
        except KeyError as error: raise ValueError('Missing original captured byte') from error


@pytest.mark.parametrize('name,module,fields', statistics.GROUPS)
def test_each_original_group_capture_stays_independent(name, module, fields):
    f = Original(GROUP_FIXTURES[name]); read = world.ReadSet(f.read)
    out = module.inspect(read, f.base, f.engine, expected_match_unique_id=f.uid); read.verify()
    assert len(statistics._indexed(out, fields, f.uid)) == 52
    assert out['coverage']['available_statistic_rows'] == 37


def synthetic_groups(monkeypatch):
    f = Original(GROUP_FIXTURES['attacking']); read = world.ReadSet(f.read)
    attack = statistics.attacking.inspect(read, f.base, f.engine, expected_match_unique_id=f.uid); read.verify()
    groups = {}; calls = []
    for name, module, fields in statistics.GROUPS:
        projection = deepcopy(attack)
        if name != 'attacking':
            for row in projection['rows']:
                for field in statistics.GROUPS[0][2]: del row[field]
                for field in fields:
                    row[field] = None if row['state'] != statistics.AVAILABLE else 0.0 if field in statistics.FLOATS else 0
        groups[name] = projection
        def inspect(shared, base, engine, *, expected_match_unique_id, name=name):
            calls.append((name, shared, base, engine, expected_match_unique_id))
            return groups[name]
        monkeypatch.setattr(module, 'inspect', inspect)
    return f, groups, calls


def test_synthetic_composition_preserves_attack_rows_and_appends_once(monkeypatch):
    f, groups, calls = synthetic_groups(monkeypatch); shared = object(); before = deepcopy(groups)
    out = statistics.inspect(shared, f.base, f.engine, expected_match_unique_id=f.uid)
    assert groups == before
    assert calls == [(name, shared, f.base, f.engine, f.uid) for name, _, _ in statistics.GROUPS]
    assert len(out['rows']) == 52 and len(out['field_qualifiers']) == 33
    for row, attack in zip(out['rows'], groups['attacking']['rows'], strict=True):
        assert all(row[field] == value for field, value in attack.items())
        assert len(row) == len(statistics.COMMON)+33
        if row['state'] != statistics.AVAILABLE:
            assert all(row[field] is None for _, _, fields in statistics.GROUPS for field in fields)
    assert all(out[flag] is False for flag in statistics.FALSE_FLAGS)
    assert out['field_qualifiers']['distance_metres']['unit'] == 'metres'
    assert out['field_qualifiers']['total_saves']['sum_wraps_to_byte'] is True
    assert out['field_qualifiers']['red_cards_received']['incident_chronology_or_current_eligibility_verified'] is False
    assert out['field_qualifiers']['aerial_duels_completed']['official_property_label']=='AerialDuelsCompleted'
    assert out['field_qualifiers']['open_play_crosses_completed']['range'] == [0,510]
    assert out['field_qualifiers']['expected_goals']['encoding'] == 'unscaled native float32'
    assert out['field_qualifiers']['open_play_final_third_passes']['negative_policy'].startswith('reject')


@pytest.mark.parametrize('kind', ['person', 'identity_state', 'state', 'duplicate', 'missing', 'extra', 'boolean_key', 'match', 'timing', 'coverage'])
def test_synthetic_mismatched_identity_keys_availability_or_scope_refuse(monkeypatch, kind):
    f, groups, _ = synthetic_groups(monkeypatch); changed = groups['recovery']
    row = next(r for r in changed['rows'] if r['state'] == statistics.AVAILABLE)
    if kind == 'person': row['person']['native_identity']['database_index'] += 1
    elif kind == 'identity_state': row['identity_state'] += '_changed'
    elif kind == 'state': row['state'] = 'unavailable_stats'
    elif kind == 'duplicate': changed['rows'][-1] = deepcopy(changed['rows'][0])
    elif kind == 'missing': changed['rows'].pop()
    elif kind == 'extra': changed['rows'].append(deepcopy(changed['rows'][0]))
    elif kind == 'boolean_key': changed['rows'][0]['side_index'] = False
    elif kind == 'match': changed['official_match_unique_id'] += 1
    elif kind == 'timing': changed['native_timestamp_association'] = True
    else: changed['coverage']['available_statistic_rows'] += 1
    with pytest.raises(ValueError): statistics.inspect(object(), f.base, f.engine, expected_match_unique_id=f.uid)


def test_synthetic_group_row_reordering_joins_by_checked_key(monkeypatch):
    f, groups, _ = synthetic_groups(monkeypatch)
    groups['defensive']['rows'].reverse()
    out = statistics.inspect(object(), f.base, f.engine, expected_match_unique_id=f.uid)
    assert [(r['side_index'],r['engine_array_index']) for r in out['rows']] == [(s,i) for s in (0,1) for i in range(26)]


@pytest.mark.parametrize('field,value', [('distance_metres',-1.0),('distance_metres',float('nan')),
                                       ('expected_goals',float('inf')),('expected_assists',0),
                                       ('crosses_attempted',True),('open_play_crosses_attempted',511),
                                       ('open_play_final_third_passes',-1),('sprints',256),('total_saves',765),('aerial_duels_completed',256)])
def test_synthetic_field_encoding_or_range_drift_refuses(monkeypatch, field, value):
    f, groups, _ = synthetic_groups(monkeypatch)
    name = next(name for name, _, fields in statistics.GROUPS if field in fields)
    next(r for r in groups[name]['rows'] if r['state'] == statistics.AVAILABLE)[field] = value
    with pytest.raises(ValueError): statistics.inspect(object(), f.base, f.engine, expected_match_unique_id=f.uid)


def test_synthetic_unknown_cannot_become_zero(monkeypatch):
    f, groups, _ = synthetic_groups(monkeypatch)
    next(r for r in groups['running']['rows'] if r['state'] != statistics.AVAILABLE)['sprints'] = 0
    with pytest.raises(ValueError, match='Unavailable resident statistic became'): statistics.inspect(object(), f.base, f.engine, expected_match_unique_id=f.uid)
