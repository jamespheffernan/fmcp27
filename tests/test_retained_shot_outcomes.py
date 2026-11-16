import gzip
import json
from pathlib import Path

import pytest

from fm_live_mcp.live_retained_shots import decode_attempts, _empty_sides
from fm_live_mcp.retained_shot_outcomes import OUTCOMES, outcome_fields

CONTROLS = json.loads(gzip.decompress((Path(__file__).parent / 'fixtures/retained_shot_maps.json.gz').read_bytes()))

@pytest.mark.parametrize('code,label', [(1,'goal'),(2,'missed_target'),(3,'hit_woodwork'),(4,'saved'),(5,'blocked')])
def test_official_end_state_namespace(code,label):
    assert outcome_fields(code)['outcome'] == label
    assert outcome_fields(code)['native_outcome_label'] == OUTCOMES[code][1]

@pytest.mark.parametrize('code', [True,-1,256,None])
def test_invalid_category_rejected(code):
    with pytest.raises(ValueError):
        outcome_fields(code)

@pytest.mark.parametrize('control', CONTROLS, ids=lambda c:str(c['key']))
def test_actual_attempt_outcomes_reconcile_shots_sot_and_score(control):
    result = decode_attempts([bytes.fromhex(v) for v in control['vectors']], bytes.fromhex(control['events']),control['teams'])
    assert result['state'] == ('available_partial' if control['key'] == 136157 else 'available')
    for side, oracle in enumerate(control['teams']):
        counts = result['side_coverage'][side]['outcome_counts']
        if counts is None:
            assert control['key'] == 136157 and side == 1
            continue
        assert sum(counts.values()) == oracle['shots']
        assert counts['goal'] + counts['saved'] == oracle['shots_on_target']
        assert counts['unknown'] == 0
    assert all(row['native_category_code'] != 49 for row in result['shots'])
    if control['key'] == 136157:
        saved_penalty = next(row for row in result['shots'] if row['event_id'] == 1984)
        assert saved_penalty['is_penalty'] and saved_penalty['outcome'] == 'saved'
        assert any(row['outcome'] == 'saved' and not row['is_penalty'] for row in result['shots'])

def test_unknown_category_preserves_unknown_and_known_zero_is_distinct():
    assert outcome_fields(255)['outcome'] is None
    assert outcome_fields(49)['outcome'] is None
    zero = decode_attempts([b'',b''],b'',[dict(shots=0,shots_on_target=0,expected_goals=0.)]*2)
    assert zero['side_coverage'][0]['outcome_counts'] == dict(goal=0,missed_target=0,hit_woodwork=0,saved=0,blocked=0,unknown=0)
    assert _empty_sides({},'unavailable')[0]['outcome_counts'] is None

def test_actual_newcastle_everton_terminal_woodwork_control():
    c=json.loads(gzip.decompress((Path(__file__).parent/'fixtures/retained_outcome_woodwork.json.gz').read_bytes()))
    result=decode_attempts([bytes.fromhex(v) for v in c['vectors']],bytes.fromhex(c['events']),c['teams'])
    assert result['state']=='available'
    assert result['side_coverage'][0]['outcome_counts']==dict(goal=4,missed_target=1,hit_woodwork=1,saved=5,blocked=6,unknown=0)
    assert result['side_coverage'][1]['outcome_counts']==dict(goal=0,missed_target=2,hit_woodwork=0,saved=2,blocked=2,unknown=0)
    woodwork,=[s for s in result['shots'] if s['outcome']=='hit_woodwork']
    assert woodwork['event_id']==168
