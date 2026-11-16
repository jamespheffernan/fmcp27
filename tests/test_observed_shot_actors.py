from hashlib import sha256

import pytest

from fm_live_mcp.active_pass_network import select_events
from fm_live_mcp.active_match_shot_timeline import project
from fm_live_mcp.observed_shot_actors import project_named_chances, derive_shot_actors
from test_active_match_shot_timeline import sample
from test_active_pass_network import event


def blob(raw):
    return {'hex':raw.hex(), 'sha256':sha256(raw).hexdigest()}


@pytest.fixture
def observations():
    native, clock, split = sample()
    clock.update(playback_address=200, frame_provider_address=500, source_match_address=501,
                 local_playback_handle=1, current_time_slice=25)
    split['period_markers'] = [{'next_stop_reason':'EndOfGame','stop_time_slice':25}]
    native['events'] += event(100, start=1, end=2, sender=7)
    native.update(fixture_identity=['fixture'],source_identity=[111,112,['fixture']])
    stored = project(native, clock, period_split=split)['shots']
    source = dict(native,events=blob(native['events']),vectors=[blob(v) for v in native['vectors']])
    terminal = dict(state='verified_terminal_resident_source', verified_readset=True, displayed_period='FullTime',
                    period_split=split,bound_playback=clock,raw_source=source)
    players = [dict(side_index=s,stored_player_slot=7,canonical_person_id=101+s,person_name=n,
                    identity_state='canonical_PERSON_table_same_team_and_typed_stats') for s,n in enumerate(('Home','Away'))]
    packet = dict(bound=dict(clock,current_time_slice=7),binding={'client':111,'engine':112},
                  actors=dict(state='validated_native_stored_slots',players=players,official_match_unique_id=123),
                  source=dict(events=select_events(native['events'],7),fixture_identity=['fixture'],match_unique_id=123))
    return terminal,packet,stored


def test_names_follow_event_side_and_original_slot(observations):
    rows = project_named_chances(*observations)
    assert len(rows)==5 and {r['shooter_name'] for r in rows}=={'Home'}
    assert {r['shooter_person_native_id'] for r in rows}=={101}
    assert [r['period'] for r in rows].count(None)==2


def test_missing_original_actor_stays_unknown(observations):
    terminal,packet,stored = observations
    del packet['actors']['players'][0]
    assert all(r['shooter_name'] is None for r in project_named_chances(terminal,packet,stored))


@pytest.mark.parametrize('fault', ['rewound','uid','regame','changed_prefix','shot','duplicate','vector','slot','period'])
def test_reject_mismatched_witnesses(observations,fault):
    terminal,packet,stored = observations
    if fault=='rewound': packet['bound']['current_time_slice']=27
    elif fault=='uid': packet['actors']['official_match_unique_id']=5
    elif fault=='regame': packet['binding']['engine']+=4
    elif fault=='changed_prefix': packet['source']['events'][0]['start']+=1
    elif fault=='shot': stored[0]['expected_goals']=1.
    elif fault=='duplicate': stored[0]=stored[1]
    elif fault=='vector': terminal['raw_source']['vectors'][0]['sha256']='1'*64
    elif fault=='slot': stored[0]['native_actor_slot']=8
    else: stored[0]['period']='SecondHalf'
    with pytest.raises(ValueError):
        project_named_chances(terminal,packet,stored)


def test_unattested_source_does_not_gain_names():
    assert derive_shot_actors(None,{'capture_id':'0'*64}) is None
