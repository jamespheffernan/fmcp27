import gzip
from pathlib import Path
from types import SimpleNamespace

import pytest

from fm_live_mcp import match_data_query
from fm_live_mcp.match_data_query import MatchDataQueries
from fm_live_mcp.match_dataset import build_connection
from fm_live_mcp.match_scope_query import ScopedMatchQueries, column_catalog

FIELDS = ['possession_won', 'possession_lost', 'pressures_completed']


def test_recovery_columns_are_typed_with_zero_and_unknown_preserved():
    capture = {'fixtures': [{'native_match_key': 1, 'fixture': {'date': '2030-10-01'}}]}
    rows = [dict(fixture_key=1, side_index=0, person_index_word=4, **dict.fromkeys(FIELDS, 0)),
            dict(fixture_key=1, side_index=0, person_index_word=5)]
    db = build_connection(capture, retained_players=rows)
    try:
        assert db.execute('SELECT '+','.join(FIELDS)+' FROM retained_players ORDER BY person_index_word').fetchall() == [(0, 0, 0), (None, None, None)]
        assert db.execute('SELECT '+','.join(FIELDS)+',action_source_state FROM player_match_analysis ORDER BY person_index_word').fetchall() == [(0, 0, 0, 'captured'), (None, None, None, 'not_captured')]
        types = {row[1]: row[2] for row in db.execute('PRAGMA table_info(retained_players)')}
        assert all(types[name] == 'INTEGER' for name in FIELDS)
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    finally:
        db.close()


def test_live_batch_reads_actual_retained_player_counters_and_provenance(monkeypatch):
    from fm_live_mcp import live_match_backing
    path = Path(__file__).parent / 'fixtures/player_actions_b142_132100.bin.gz'
    raw = gzip.decompress(path.read_bytes())
    def backing(*args, **kwargs):
        return {'save': {'current_date': '2030-10-29'}, 'source_kind': 'frozen_frame_control',
                'records': [{'key': 132100, 'fixture_ref': 'f', 'state': 'available', 'raw': raw,
                             'fixture_native': {'date': '2030-10-01'}}]}
    monkeypatch.setattr(live_match_backing, 'read_selected_matches', backing)
    result = match_data_query._capture_live_batch(SimpleNamespace(), 's', ['f'])
    gordon, = [row for row in result['retained_players'] if row['person_index_word'] == 13009]
    assert tuple(gordon[name] for name in FIELDS) == (2, 5, 1)
    provenance = result['capture']['action_field_provenance']
    assert provenance['possession_won']['official_property_label'] == 'PossessionWon'
    assert provenance['pressures_completed']['native_offset'] == '0xed'
    assert provenance['pressures_attempted']['native_offset'] == '0xec'
    assert 'pressure_regains' not in provenance


def test_explicit_and_scoped_queries_select_recoveries_and_expose_limits():
    def capture(*args, **kwargs):
        return {'capture': {'fixtures': [{'native_match_key': 1, 'fixture': {'date': '2030-10-01'}}]},
                'retained_players': [dict(fixture_key=1, side_index=0, person_index_word=4,
                                          possession_won=11, possession_lost=17, pressures_completed=4)]}
    explicit = MatchDataQueries(capture, epoch=lambda *_: 1)
    assert explicit.query(None, 's', ['f'], 'retained_players', FIELDS)['rows'] == [dict(zip(FIELDS, [11, 17, 4]))]
    scoped = ScopedMatchQueries(capture, epoch=lambda *_: 1)
    result = scoped.query(None, 's', 688, '2030-10-01', '2030-10-01',
                          tables=['retained_players'], fields={'retained_players': FIELDS})
    assert result['rows'][0]['row'] == dict(zip(FIELDS, [11, 17, 4]))
    catalog = column_catalog()['retained_players']
    assert all(name in catalog['columns'] for name in FIELDS)
    assert 'pressure-regain' in catalog['field_provenance']['pressures_completed']['scope']
    with pytest.raises(ValueError, match='Unsupported fields'):
        scoped.query(None, 's', 688, '2030-10-01', '2030-10-01', tables=['retained_players'],
                     fields={'retained_players': ['pressure_regains']})


def test_ordinary_midfield_question_keeps_total_and_per90_winners_distinct():
    import json
    from collections import defaultdict
    from fractions import Fraction
    control = json.loads((Path(__file__).parent / 'fixtures/newcastle_recoveries_nine_game.json').read_text())
    calls = []
    def capture(*args, **kwargs):
        calls.append(args[7])
        return control
    fields = ['canonical_person_id', 'person_name', 'minutes', *FIELDS]
    result = ScopedMatchQueries(capture, epoch=lambda *_: 1).query(
        None, 's', 688, '2030-08-01', '2030-10-28', 11,
        tables=['retained_players'], fields={'retained_players': fields})
    assert calls == [True]
    assert result['counts']['retained_players'] == 180
    assert len(control['source_frame_sha256']) == 9
    eligible = {row['canonical_person_id'] for row in control['eligible_midfielders']
                if max(row['position_ratings'].values()) >= 16}
    totals = defaultdict(lambda: {'minutes': 0, 'possession_won': 0})
    for item in result['rows']:
        row = item['row']
        if row['canonical_person_id'] not in eligible:
            continue
        total = totals[row['person_name']]
        total['minutes'] += row['minutes'] or 0
        total['possession_won'] += row['possession_won']
    assert max(totals, key=lambda name: totals[name]['possession_won']) == 'Shea Charles'
    qualifying = {name: row for name, row in totals.items() if row['minutes'] >= control['minimum_minutes']}
    rates = {name: Fraction(row['possession_won'] * 90, row['minutes']) for name, row in qualifying.items()}
    assert max(rates, key=rates.get) == 'Chema Andrés'
    assert totals['Shea Charles'] == {'minutes': 720, 'possession_won': 73}
    assert totals['Chema Andrés'] == {'minutes': 285, 'possession_won': 35}
    assert rates['Chema Andrés'] == Fraction(210, 19)
    assert 'Lewis Miley' not in qualifying and totals['Lewis Miley']['minutes'] == 24
    assert 'Giovanni Fabbian' not in qualifying and totals['Giovanni Fabbian']['minutes'] == 104
    assert 'pressure_regains' not in result['fields']['retained_players']
    assert 'pressures_attempted' not in result['fields']['retained_players']
