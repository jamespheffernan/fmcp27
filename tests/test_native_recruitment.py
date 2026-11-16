import json
import subprocess

import pytest

from test_native import HELPER, native, pytestmark
from test_native_index import index_target, args


def query(t, filters=(), start=0, budget=200000, limit=100):
    return native(t, 'scan-player-index', *args(t, name='', start=start, budget=budget, limit=limit),
        '--query-players', '--player-staff-primary', str(0x55500), '--player-staff-person', str(0x66600),
        *[arg for f in filters for arg in ('--player-filter', f)])


@pytest.mark.parametrize('index_target', [False, True], indirect=True)
def test_native_recruitment_units_combined_unknowns_and_known_exclusions(index_target):
    t = index_target
    # Passing >=15 includes fifths 77/88 and direct 20; PA -95 remains unknown.
    result = query(t, ['r:350:15:20', 's:606:170:200'])
    assert [p['first_name'] for p in result['matches']] == ['Adam', 'Sheku']
    assert [p['filter_state'] for p in result['matches']] == ['unknown_potential', 'match']
    assert result['actual_players_examined'] == 3 and result['other_person_records'] == 1
    result = query(t, ['s:606:170:200', 's:604:170:200'])
    assert [p['first_name'] for p in result['matches']] == ['Sheku']
    result = query(t, ['p:68:16:20', 'b:340:19:20'])
    assert [p['first_name'] for p in result['matches']] == ['Adam', 'Sheku']
    result = query(t, ['r:350:15:15'])
    assert [p['first_name'] for p in result['matches']] == ['Scott']


def test_native_birth_bounds_and_lossless_unknown_pagination(index_target):
    t = index_target
    filters = [f'd:720:{2010*512+60}:{2012*512+60}', 's:606:170:200']
    first = query(t, filters, budget=2)
    assert first['matches'] == [] and first['stop_reason'] == 'record_budget' and first['next_index'] == 2
    second = query(t, filters, start=2, limit=1)
    assert second['matches'][0]['filter_state'] == 'unknown_potential'
    assert second['next_index'] == 3 and second['stop_reason'] == 'match_limit'
    third = query(t, filters, start=3, limit=1)
    assert third['matches'][0]['first_name'] == 'Sheku' and third['stop_reason'] == 'table_end'


@pytest.mark.parametrize('index_target', [False, True], indirect=True)
@pytest.mark.parametrize('mutation', ['generated', 'alternate_id'])
def test_independent_person_ids_preserve_complete_pagination(index_target, mutation):
    t = index_target
    t['child'].stdin.write(mutation+'\n'); t['child'].stdin.flush()
    assert t['child'].stdout.readline().strip() == 'changed'
    pages, start = [], 0
    while start < 4:
        page = query(t, start=start, limit=1)
        pages.append(page)
        assert page['next_index'] > start
        start = page['next_index']
    assert sum(p['scanned_records'] for p in pages) == 4
    assert [p['first_name'] for page in pages for p in page['matches']] == ['Scott', 'Adam', 'Sheku']


def test_native_recruitment_still_rejects_zero_primary_identity(index_target):
    t = index_target
    t['child'].stdin.write('zero_id\n'); t['child'].stdin.flush()
    assert t['child'].stdout.readline().strip() == 'changed'
    result = subprocess.run([str(HELPER), 'scan-player-index', '--pid', str(t['pid']),
        *args(t, name=''), '--query-players'], capture_output=True, text=True, timeout=5)
    assert result.returncode != 0 and json.loads(result.stdout)['ok'] is False


@pytest.mark.parametrize('mutation,filter_text', [('badfilter', 'r:350:0:20'), ('baddate', 'd:720:0:1126766')])
def test_native_invalid_selected_fields_fail_whole_page(index_target, mutation, filter_text):
    t = index_target
    t['child'].stdin.write(mutation+'\n'); t['child'].stdin.flush()
    assert t['child'].stdout.readline().strip() == 'changed'
    result = subprocess.run([str(HELPER), 'scan-player-index', '--pid', str(t['pid']),
        *args(t, name=''), '--query-players', '--player-filter', filter_text], capture_output=True, text=True, timeout=5)
    assert result.returncode != 0 and json.loads(result.stdout)['ok'] is False


@pytest.mark.parametrize('text', ['r:350:-1:20', 'r:350:0:21', 's:606:0:201', 'b:350:0:20', 'p:72:0:20',
    'r:350:20:1', 'r:350:0:20junk', 'r:18446744073709551616:0:20', 's:606:0:99999999999999999', 'z:350:0:20'])
def test_native_filter_argument_bounds_reject(index_target, text):
    result = subprocess.run([str(HELPER), 'scan-player-index', '--pid', str(index_target['pid']),
        *args(index_target, name=''), '--query-players', '--player-filter', text], capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
