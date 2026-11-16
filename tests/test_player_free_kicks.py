import gzip
import json
from pathlib import Path

import pytest

from fm_live_mcp.match_dataset import build_connection
from fm_live_mcp.match_data_query import MatchDataQueries
from fm_live_mcp.match_scope_query import ScopedMatchQueries, column_catalog
from fm_live_mcp.saved_match_player_free_kicks import decode_player_free_kicks, free_kick_field_registry


@pytest.mark.parametrize('tag', [0, 1, 2, 255])
@pytest.mark.parametrize('value', [0, 1, 255])
def test_unsigned_counts_and_person_widths(tag, value):
    delta = 0 if tag >= 2 else 4
    child = bytearray(159 + delta)
    child[0] = tag
    child[158 + delta] = value
    assert decode_player_free_kicks(bytes(child)) == {'direct_free_kick_goals': value}
    with pytest.raises(ValueError, match='Truncated'):
        decode_player_free_kicks(bytes(child[:-1]))


@pytest.mark.parametrize('child', [None, b'', bytearray(200), ''])
def test_missing_or_wrong_child_is_not_zero(child):
    with pytest.raises(ValueError):
        decode_player_free_kicks(child)


def test_typed_zero_unknown_and_provenance():
    cap = {'fixtures': [{'native_match_key': 1, 'fixture': {'date': '2030-10-26'}}]}
    db = build_connection(cap, retained_players=[dict(fixture_key=1, person_index_word=1, direct_free_kick_goals=0), dict(fixture_key=1, person_index_word=2)])
    try:
        assert db.execute('SELECT direct_free_kick_goals,action_source_state FROM player_match_analysis ORDER BY person_index_word').fetchall() == [(0, 'captured'), (None, 'not_captured')]
        assert dict((r[1], r[2]) for r in db.execute('PRAGMA table_info(retained_players)'))['direct_free_kick_goals'] == 'INTEGER'
    finally:
        db.close()
    registry = column_catalog()['retained_players']['field_provenance']['direct_free_kick_goals']
    assert registry == free_kick_field_registry()['direct_free_kick_goals']
    assert 'canonical_source_identity' in registry['identity_policy']
    assert 'no corner or indirect' in registry['scope']
    assert 'exactly one total goal' in registry['scope']


def test_real_positive_negative_controls_and_identity():
    rows = json.loads(gzip.decompress((Path(__file__).parent/'fixtures/direct_free_kick_goals_b156.json.gz').read_bytes()))
    positives = []
    target = []
    for row in rows:
        value = decode_player_free_kicks(bytes.fromhex(row['raw_child_hex']))['direct_free_kick_goals']
        assert value <= row['goals']
        if row['native_match_key'] in (135904, 136157):
            target.append(value)
        if value:
            assert row['identity_state'] == 'canonical_source_identity'
            assert row['canonical_person_id'] and row['person_index_word']
            positives.append((row['native_match_key'], row['person_name'], row['goals'], value))
    assert len(target) == 80 and sum(target) == 0
    assert positives == [(135117, 'Elliot Anderson', 1, 1), (135903, 'Martin Ødegaard', 1, 1), (136440, 'Florian Wirtz', 1, 1)]


def test_both_live_query_routes_return_counter_without_inventing_missing_fixture():
    def capture(*args, **kwargs):
        return dict(capture={'fixtures': [{'native_match_key': 1, 'fixture': {'date': '2030-10-26'}}]}, retained_players=[dict(fixture_key=1, direct_free_kick_goals=1)])
    explicit = MatchDataQueries(capture, epoch=lambda *_: 1)
    assert explicit.query(None, 's', ['f'], 'retained_players', ['direct_free_kick_goals'])['rows'] == [{'direct_free_kick_goals': 1}]
    scoped = ScopedMatchQueries(capture, epoch=lambda *_: 1)
    out = scoped.query(None, 's', 713, '2030-10-26', '2030-10-26', tables=['retained_players'], fields={'retained_players': ['direct_free_kick_goals']})
    assert out['rows'][0]['row'] == {'direct_free_kick_goals': 1}


def test_capture_enriches_observed_frame(monkeypatch):
    from types import SimpleNamespace
    from fm_live_mcp import live_match_backing, match_data_query
    raw = gzip.decompress((Path(__file__).parent/'fixtures/player_actions_b142_132100.bin.gz').read_bytes())
    monkeypatch.setattr(live_match_backing, 'read_selected_matches', lambda *a, **kw: dict(save={}, source_kind='frozen_frame_control', records=[dict(key=132100, fixture_ref='f', state='available', raw=raw, fixture_native={'date': '2030-10-01'})]))
    result = match_data_query._capture_live_batch(SimpleNamespace(), 's', ['f'])
    assert len(result['retained_players']) == 41
    assert all('direct_free_kick_goals' in row for row in result['retained_players'])
    assert result['capture']['action_field_provenance']['direct_free_kick_goals']['official_property_label'] == 'DirectFreeKickGoals'
