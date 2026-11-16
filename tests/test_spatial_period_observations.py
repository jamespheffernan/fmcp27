from copy import deepcopy
import json
import os

import pytest

from fm_live_mcp.spatial_period_observations import SpatialPeriodStore
from fm_live_mcp.spatial_period_witness import make_observation
from fm_live_mcp.match_period_observations import digest
from test_spatial_period_witness import synthetic


def record():
    save, fixture, parent, _, _, _, captured = synthetic()
    candidate = dict(bound=dict(current_time_slice=145, official_match_unique_id=9001),
                     split=dict(period_markers=parent['period_markers']))
    return save, fixture, make_observation(save, fixture, candidate, captured, 'a' * 64, '2030-11-11T20:00:00Z')


def test_zero_shot_spatial_record_roundtrips_in_own_isolated_namespace(tmp_path):
    save, fixture, observation = record()
    store = SpatialPeriodStore(root=tmp_path / 'spatial')
    assert store.observations(save, fixture)['observations'] == {}
    receipt = store.save(observation)
    assert receipt == dict(state='captured', capture_id=digest(observation))
    assert store.observations(save, fixture)['observations'] == {receipt['capture_id']: observation}
    assert store.save(deepcopy(observation))['state'] == 'already_captured'
    assert 'attempt_prefix' not in observation
    assert os.stat(store.path(save, fixture)).st_mode & 0o077 == 0


@pytest.mark.parametrize('mutation', ['digest', 'epoch', 'permissions', 'symlink', 'oversize'])
def test_typed_spatial_store_rejects_changed_or_unsafe_source(tmp_path, mutation):
    save, fixture, observation = record()
    store = SpatialPeriodStore(root=tmp_path / 'spatial')
    store.save(observation)
    path = store.path(save, fixture)
    if mutation in ('digest', 'epoch'):
        document = json.loads(path.read_text())
        key = next(iter(document['observations']))
        if mutation == 'digest': document['observations'][key]['observed_at'] += ' altered'
        else: document['observations'][key]['process_load_epoch'] = 'b' * 64
        path.write_text(json.dumps(document))
    if mutation == 'permissions': path.chmod(0o644)
    if mutation == 'symlink':
        original = path.with_suffix('.original'); path.rename(original); path.symlink_to(original)
    if mutation == 'oversize': path.write_bytes(b' ' * (256 * 1024 + 1))
    with pytest.raises(ValueError): store.observations(save, fixture)


def test_legacy_event_only_observation_cannot_be_published_as_spatial(tmp_path):
    _, _, parent, _, _, _, _ = synthetic()
    parent['attempt_prefix'] = []
    store = SpatialPeriodStore(root=tmp_path / 'spatial')
    with pytest.raises(ValueError, match='spatial-only'): store.save(parent)
    assert not store.root.exists()
