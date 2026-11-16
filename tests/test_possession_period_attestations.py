from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from fm_live_mcp import possession_period_attestations as a
from fm_live_mcp.match_period_observations import ObservationStore, digest

FIXTURE = Path(__file__).parent / 'fixtures/possession_period_witness_forest_2030_11_11.json'


def sample():
    value = json.loads(FIXTURE.read_text())
    return value['parent_observation'], value['attestation']


@pytest.fixture
def original():
    parent, document = sample()
    path = Path(parent['seed_provenance']['terminal_path'])
    if not path.exists():
        pytest.skip('Original authentic terminal required for build-source proof; portable storage/projection controls still run')
    return path.read_bytes(), parent, document


def test_actual_original_source_reproduces_new_attestation_without_touching_parent(original):
    raw, parent, expected = original
    before = deepcopy(parent)
    assert hashlib.sha256(raw).hexdigest() == '9ee6e05dd61b20ba3b4d0a1aa71e72825768f0ced6204889c003c5bb7ebc9a9c'
    assert a.build(raw, parent) == expected
    assert parent == before
    assert expected['attestation']['fingerprint']['event_count'] == 354
    assert digest(parent) == expected['attestation']['parent_capture_id']


def test_original_hash_guard_and_cannot_replace_parent_from_current_retained_bytes(original):
    raw, parent, _ = original
    with pytest.raises(ValueError, match='SHA'):
        a.build(raw + b'\n', parent)
    with pytest.raises(ValueError, match='SHA'):
        a.build(b'current_retained_source', parent)
    changed = deepcopy(parent)
    changed['source_hashes']['events'] = '0' * 64
    with pytest.raises(ValueError, match='reproduce'):
        a.build(raw, changed)


def test_append_only_readback_never_changes_original_observation_or_finalized_links(tmp_path):
    parent, document = sample()
    store = ObservationStore(tmp_path / 'periods')
    store.save(parent)
    store.finalize(parent['career'], parent['fixture'], 123, digest(parent), 'a' * 64)
    path = store.path(parent['career'], parent['fixture'])
    before = path.read_bytes()
    result = a.write(store.root, parent, document)
    assert result['state'] == 'imported'
    assert a.load(store.root, parent) == document
    assert path.read_bytes() == before
    assert a.write(store.root, parent, document)['state'] == 'already_imported'
    assert path.read_bytes() == before
    assert not (store.root / 'possession-period-attestations-v1').is_symlink()
    assert Path(result['path']).stat().st_mode & 0o077 == 0
    changed = deepcopy(document)
    changed['attestation']['fingerprint']['semantic_sha256'] = '0' * 64
    changed['attestation_id'] = digest(changed['attestation'])
    with pytest.raises(ValueError, match='never overwrite'):
        a.write(store.root, parent, changed)
    assert a.load(store.root, parent) == document
    assert path.read_bytes() == before


@pytest.mark.parametrize('field', ['parent_capture_id', 'original_terminal_sha256', 'parent_event_source_sha256',
    'policy', 'provenance', 'original_observation_modified', 'existing_links_modified', 'fresh_match_observation', 'schema'])
def test_forged_backlink_or_provenance_fails_even_with_recomputed_digest(field):
    parent, document = sample()
    document['attestation'][field] = True if field.endswith('modified') or field == 'fresh_match_observation' or field == 'schema' else '0' * 64
    document['attestation_id'] = digest(document['attestation'])
    with pytest.raises(ValueError): a.validate(document, parent)


@pytest.mark.parametrize('field,value', [('schema', True), ('event_count', True), ('event_count', -1),
    ('cutoff_exclusive', 65536), ('report_policy', 'pass_period_network'), ('semantic_sha256', 'x' * 64)])
def test_invalid_fingerprint_shapes_cannot_authorize_period_numbers(field, value):
    parent, document = sample()
    document['attestation']['fingerprint'][field] = value
    document['attestation_id'] = digest(document['attestation'])
    with pytest.raises(ValueError): a.validate(document, parent)


def test_missing_file_is_unknown_and_symlink_or_world_readable_file_refuses(tmp_path):
    parent, document = sample()
    root = tmp_path / 'periods'
    assert a.load(root, parent) is None
    result = a.write(root, parent, document)
    path = Path(result['path'])
    path.chmod(0o644)
    with pytest.raises(ValueError, match='metadata'):
        a.load(root, parent)
    path.chmod(0o600)
    unsafe = tmp_path / 'link-root'
    unsafe.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match='directory'):
        a.load(unsafe, parent)
    assert a.load(root, parent) == document


def test_raw_source_capture_ids_and_cutoff_drift_are_not_silently_upgraded(tmp_path):
    parent, document = sample()
    a.write(tmp_path / 'periods', parent, document)
    changed = deepcopy(parent)
    changed['fingerprint_cursor'] -= 1
    with pytest.raises(ValueError): a.validate(document, changed)
    assert a.load(tmp_path / 'periods', changed) is None
