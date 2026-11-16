import gzip
import json
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from fm_live_mcp import match_data_query
from fm_live_mcp.match_data_query import MatchDataQueries
from fm_live_mcp.match_dataset import build_connection
from fm_live_mcp.match_scope_query import ScopedMatchQueries, column_catalog
from fm_live_mcp.saved_match_player_progression import decode_player_progression, progression_field_registry


@pytest.mark.parametrize('tag', [0, 1, 2, 3, 255])
@pytest.mark.parametrize('value', [0, 1, 255])
def test_counts_preserve_unsigned_domain_and_person_encodings(tag, value):
    delta = 0 if tag >= 2 else 4
    child = bytearray(187 + delta)
    child[0] = tag
    child[186 + delta] = value
    assert decode_player_progression(bytes(child)) == {'progressive_passes': value}
    with pytest.raises(ValueError, match='Truncated'):
        decode_player_progression(bytes(child[:-1]))


@pytest.mark.parametrize('child', [None, '', bytearray(200), b''])
def test_requires_stored_bytes(child):
    with pytest.raises(ValueError):
        decode_player_progression(child)


def test_typed_columns_preserve_zero_vs_uncaptured_and_catalog_limits():
    cap = {'fixtures': [{'native_match_key': 1, 'fixture': {'date': '2030-10-01'}}]}
    db = build_connection(cap, retained_players=[dict(fixture_key=1, person_index_word=1, progressive_passes=0), dict(fixture_key=1, person_index_word=2)])
    try:
        assert db.execute('SELECT progressive_passes,action_source_state FROM player_match_analysis ORDER BY person_index_word').fetchall() == [(0, 'captured'), (None, 'not_captured')]
        assert dict((r[1], r[2]) for r in db.execute('PRAGMA table_info(retained_players)'))['progressive_passes'] == 'INTEGER'
    finally:
        db.close()
    registry = column_catalog()['retained_players']['field_provenance']['progressive_passes']
    assert registry == progression_field_registry()['progressive_passes']
    assert 'final-third entries' in registry['scope']


def test_live_batch_enriches_actual_frame_and_exposes_official_property(monkeypatch):
    from fm_live_mcp import live_match_backing
    raw = gzip.decompress((Path(__file__).parent / 'fixtures/player_actions_b142_132100.bin.gz').read_bytes())
    monkeypatch.setattr(live_match_backing, 'read_selected_matches', lambda *a, **kw: dict(save={}, source_kind='frozen_frame_control', records=[dict(key=132100, fixture_ref='f', state='available', raw=raw, fixture_native={'date': '2030-10-01'})]))
    result = match_data_query._capture_live_batch(SimpleNamespace(), 's', ['f'])
    row, = [r for r in result['retained_players'] if r['person_index_word'] == 49717]
    assert row['progressive_passes'] == 14
    assert result['capture']['action_field_provenance']['progressive_passes']['official_property_label'] == 'ProgressivePasses'


def test_both_query_routes_select_counts_and_reject_unproved_entries():
    def capture(*a, **kw):
        return dict(capture={'fixtures': [{'native_match_key': 1, 'fixture': {'date': '2030-10-01'}}]}, retained_players=[dict(fixture_key=1, progressive_passes=7)])
    explicit = MatchDataQueries(capture, epoch=lambda *_: 1)
    assert explicit.query(None, 's', ['f'], 'retained_players', ['progressive_passes'])['rows'] == [{'progressive_passes': 7}]
    scoped = ScopedMatchQueries(capture, epoch=lambda *_: 1)
    out = scoped.query(None, 's', 688, '2030-10-01', '2030-10-01', tables=['retained_players'], fields={'retained_players': ['progressive_passes']})
    assert out['rows'][0]['row'] == {'progressive_passes': 7}
    with pytest.raises(ValueError, match='Unsupported fields'):
        scoped.query(None, 's', 688, '2030-10-01', '2030-10-01', tables=['retained_players'], fields={'retained_players': ['final_third_entries']})


def test_sustained_volume_and_small_sample_rate_are_distinct():
    control = json.loads((Path(__file__).parent / 'fixtures/newcastle_progression_nine_game.json').read_text())
    result = ScopedMatchQueries(lambda *a, **kw: control, epoch=lambda *_: 1).query(None, 's', 688, '2030-08-01', '2030-10-28', 11, tables=['retained_players'], fields={'retained_players': ['canonical_person_id', 'person_name', 'minutes', 'progressive_passes']})
    assert result['counts']['retained_players'] == 180
    eligible = {p['canonical_person_id'] for p in control['eligible_midfielders'] if max(p['position_ratings'].values()) >= 16}
    totals = defaultdict(lambda: dict(minutes=0, progressive_passes=0, missing_minutes=0))
    for item in result['rows']:
        row = item['row']
        if row['canonical_person_id'] not in eligible:
            continue
        total = totals[row['person_name']]
        total['progressive_passes'] += row['progressive_passes']
        if row['minutes'] is None:
            total['missing_minutes'] += 1
        else:
            total['minutes'] += row['minutes']
    qualifying = {name: r for name, r in totals.items() if r['minutes'] >= 270 and not r['missing_minutes']}
    rates = {name: Fraction(r['progressive_passes'] * 90, r['minutes']) for name, r in qualifying.items()}
    assert max(totals, key=lambda name: totals[name]['progressive_passes']) == 'Adam Wharton'
    assert totals['Adam Wharton']['progressive_passes'] == 56
    assert rates['Adam Wharton'] == Fraction(5040, 671)
    assert max(rates, key=rates.get) == 'Chema Andrés'
    assert totals['Chema Andrés']['minutes'] == 285
    assert rates['Chema Andrés'] == Fraction(156, 19)
