"""Genuine qualified shot packet through retained adapter, normalizer and HTML renderer."""
import base64
import copy
import gzip
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import general_report
import report_sources
from render_match_report import render
from fm_live_mcp import live_retained_shots
from fm_live_mcp.retained_shot_quality import summarize_shot_quality

PACKET = json.loads(gzip.decompress((HERE / 'fixtures/retained_liverpool_138871.json.gz').read_bytes()))


def bundle():
    fixture = copy.deepcopy(PACKET['fixture'])
    save = copy.deepcopy(PACKET['save'])
    key = PACKET['qualified']['native_match_key']
    request = dict(source='retained', fixture_date=fixture['date'],
        home_team_native_id=fixture['home_team']['native_id'], away_team_native_id=fixture['away_team']['native_id'],
        competition_native_id=fixture['competition']['native_id'], expected_home_goals=1, expected_away_goals=2,
        career_name=save['name'], career_created_date=save['created_date'], career_created_version=save['created_version'],
        native_match_key=key)
    bridge = Mock()
    bridge.attach.return_value = {'session_id': 'isolated-packet-replay'}
    bridge.get_save.return_value = {'save': save}
    bridge.find_fixtures.return_value = {'fixtures': [fixture], 'next_cursor': None}
    totals = [dict(side_index=r['side_index'], shots=r['official_shots'],
        shots_on_target=r['official_shots_on_target'], expected_goals=r['official_expected_goals'])
        for r in PACKET['qualified']['side_coverage']]
    # This test isolates shot integration; player/tracking/pass tables are not synthesized.
    frame = {'capture': {'fixtures': [{'native_match_key': key}]}, 'retained_players': [],
        'team_totals': {'records': [{'teams': totals}]}}
    def captured(*args, include_source_observed=False, **kwargs):
        return {'records': [copy.deepcopy(PACKET['qualified' if include_source_observed else 'strict'])]}
    with (
        patch('fm_live_mcp.match_data_query.capture_live', return_value=frame),
        patch('fm_live_mcp.match_data_query.capture_epoch', return_value='stable-packet-epoch'),
        patch('fm_live_mcp.live_retained_shots.capture_retained_shot_maps', side_effect=captured),
        patch('fm_live_mcp.retained_spatial_report.capture_spatial', return_value={
            'state': 'shot-integration-only', 'pitch_geometry': PACKET['qualified']['pitch_geometry']}),
        patch('fm_live_mcp.live_retained_pass_events.capture_retained_pass_attempts', return_value={'attempts': [], 'next_offset': None, 'source_id': 'no-pass-data'}),
        patch('fm_live_mcp.match_period_tools.report_retained_periods', return_value={'state': 'unavailable_not_captured'}),
    ):
        result = report_sources.retained(report_sources.validate(request), lambda: bridge)
    bridge.detach.assert_called_once()
    return result


class RetainedObservedIntegration(unittest.TestCase):
    def test_genuine_six_observed_rows_reach_separate_rendered_collection(self):
        result = bundle()
        self.assertEqual(len(result.get('source_observed_shots', [])), 6)
        self.assertEqual(result['source_observed_shots'], PACKET['qualified']['source_observed_shots'])
        self.assertEqual(result['source_observed_coverage'], PACKET['qualified']['source_observed_coverage'])
        self.assertEqual(result['shots'], PACKET['strict']['shots'])
        self.assertEqual(result['shot_coverage'], PACKET['strict']['side_coverage'])
        self.assertEqual(result['provenance']['shot_source_id'], PACKET['qualified']['source_id'])
        self.assertEqual(result['provenance']['source_observed_policy'], PACKET['qualified']['source_observed_policy'])
        data = general_report.normalise(result)
        strict, observed = data['shots'], data['source_observed_shots']
        self.assertEqual((len(strict), len(observed)), (11, 6))
        self.assertEqual({r['side'] for r in strict}, {1})
        self.assertEqual({r['side'] for r in observed}, {0})
        identities = [(r['side'], r['event_id']) for r in strict + observed]
        self.assertEqual(len(set(identities)), 17)
        self.assertNotIn(1313, [r['event_id'] for r in strict + observed])
        self.assertEqual([r['xg'] for r in observed], [r['native_expected_goals'] for r in PACKET['qualified']['source_observed_shots']])
        self.assertTrue(all(r['verification_scope'] == 'source_observed_counts_actors_verified_xg_unreconciled' for r in observed))
        self.assertEqual(data['shot_coverage'][0]['xg_float32_ulp_distance'], 3)
        self.assertIsNone(data['shot_coverage'][0]['expected_goals'])
        self.assertEqual(data['team_totals'][0]['expected_goals'], 1.4353783130645752)
        self.assertFalse(data['half_split_available'])
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'report.html'
            render(data, output)
            html = output.read_text()
            embedded = re.search(r'id="match-data">([^<]+)</script>', html)[1]
            readback = json.loads(gzip.decompress(base64.b64decode(embedded)))
            self.assertEqual(readback['source_observed_shots'], observed)
            self.assertEqual(readback['shots'], strict)
            self.assertIn('source-observed attempts', html)
            self.assertIn('xG unreconciled', html)
        # Preserve existing public defaults and strict quality/ranking behavior.
        import inspect
        self.assertIs(inspect.signature(live_retained_shots.capture_retained_shot_maps).parameters['include_source_observed'].default, False)
        self.assertIs(inspect.signature(live_retained_shots.get_retained_shot_map).parameters['include_source_observed'].default, False)
        own = summarize_shot_quality([PACKET['qualified']], 688, 'for', .2, 15)
        self.assertEqual(own['coverage'], 'unavailable')
        self.assertIsNone(own['covered_fixture_totals'])
        self.assertEqual(PACKET['qualified']['reconciliation_policy']['expected_goals_max_float32_ulps'], 1)

    def test_absent_qualified_collection_stays_empty_without_fabricated_rows(self):
        saved = copy.deepcopy(PACKET['qualified'])
        try:
            PACKET['qualified'].pop('source_observed_shots')
            PACKET['qualified'].pop('source_observed_coverage')
            result = bundle()
            self.assertEqual(result['source_observed_shots'], [])
            self.assertEqual(result['source_observed_coverage'], [])
            self.assertEqual(len(general_report.normalise(result)['shots']), 11)
        finally:
            PACKET['qualified'] = saved


if __name__ == '__main__':
    unittest.main()
