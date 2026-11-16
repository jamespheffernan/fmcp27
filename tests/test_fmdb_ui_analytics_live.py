"""Live-gated read of the Data Hub analytics screens (skipped unless FM27 runs).

The charts change as the season goes on, so the checks are structural: six columns that add up to
100, the game's own summary and competition on every zone map, a chart selected by its name."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fmdb_ui_live import _live_available  # noqa: E402

pytestmark = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')


def test_live_team_analytics_reads_the_zone_maps():
    sys.path.insert(0, str(ROOT / 'scripts'))
    from fm_live_mcp.fmdb import ui_recipes_analytics as A
    from fmdb_ui_read import open_vm
    session, memory, vm = open_vm()
    try:
        out = A.team_analytics(vm)
        if out['state'] != 'available':
            pytest.skip(f"no analytics on this save: {out['state']}")
        zone_maps = [c for c in out['charts'] if c['kind'] == 'zone_map']
        assert zone_maps and all(len(c['zones']) == 6 for c in zone_maps)
        assert all(abs(sum(z['percent'] for z in c['zones']) - 100) < 0.5 for c in zone_maps)
        assert all(c['summary'] and c['competition'] and c['time_frame'] for c in zone_maps)
        assert out['chart_count'] == len(out['charts']) + len(out['other_charts'])
        assert out['recipe']['context_objects'].keys() == {'Hhum', 'mCLv'} and out['team']['name']
        named = A.team_analytics(vm, chart=zone_maps[0]['name'])
        assert [c['name'] for c in named['charts']] == [zone_maps[0]['name']]
        players = A.player_analytics(vm, chart='all')
        assert players['state'] in ('available', 'no_charts')
        assert all(c['kind'] == 'scatter_graph' and c['points'] for c in players['charts'])
    finally:
        memory.close()
        session.close()


@pytest.mark.parametrize('name', ['player_analytics', 'person_analytics', 'opposition_analytics', 'match_analytics'])
def test_live_other_data_hub_screens(name):
    sys.path.insert(0, str(ROOT / 'scripts'))
    from fm_live_mcp.fmdb import ui_recipes_analytics as A
    from fmdb_ui_read import open_vm
    session, memory, vm = open_vm()
    try:
        out = A.SCREENS[name](vm, chart='all')
        if out['state'] not in ('available',):
            pytest.skip(f"{name}: {out['state']} on this save")
        if name == 'match_analytics':
            assert out['match']['home']['name'] and out['match']['date'] and out['matches'][0]['match'] == 1
            assert set(out['charts']) <= set(A.MATCH_CHARTS) | set(A.LAST_MATCH_CHARTS) and 'action_zones' in out['charts']
            assert not out['unavailable']
            if 'xg_story' in out['charts']:           # the latest match's analysis names the same fixture
                story = out['charts']['xg_story']
                assert story['GraphType'] == 'xG Match Story' and out['summary']
                assert story['HomeTeam']['id'] == out['match']['home']['id'] and story['AwayTeam']['id'] == out['match']['away']['id']
                assert 'xg_story' not in A.match_analytics(vm, match=2, chart='all')['charts'] if len(out['matches']) > 1 else True
            shots = out['charts'].get('home_shot_map') or {}
            assert shots.get('GraphType') == 'Shot Map' and 'ShotLocationPitch' in shots
            positions = out['charts'].get('home_average_positions') or {}
            assert all(row['Player']['name'] for row in positions.get('CombinedPlayerData', []))
            return
        assert out['chart_count'] == len(out['charts']) and out['charts']
        assert all(c['name'] and c['kind'] in ('scatter_graph', 'polygon', 'zone_map', 'first_contact_zone_map') for c in out['charts'])
        if name == 'player_analytics':
            assert all(c['group'] and c['kind'] == 'scatter_graph' and c['points'] for c in out['charts'])
            assert any(c['on_data_hub'] for c in out['charts'])
        if name == 'person_analytics':
            assert out['person']['name'] and any(c['kind'] == 'polygon' and c['data_points'] for c in out['charts'])
    finally:
        memory.close()
        session.close()
