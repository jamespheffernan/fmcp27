"""Portable recorded semantics survive harmless producer source changes."""
import hashlib

import pytest

from fm_live_mcp import observed_run_tactical_capture as producer
from fm_live_mcp import observed_run_registry as registry
from fm_live_mcp.observed_match_runs import ObservedRunQueries, open_run
from fm_live_mcp.observed_run_recorder import write_prefix
from fm_live_mcp.observed_tactical_settings import SNAPSHOTS_TABLE
from tests.test_observed_run_recorder import packet, tactical_document


def record(packet, tmp_path, monkeypatch):
    monkeypatch.setattr(registry, 'REGISTRY_PATH', tmp_path / 'registry.json')
    packet['tactical_observation'] = tactical_document(packet, monkeypatch)
    receipt = write_prefix(packet, tmp_path / 'store')
    proof = producer.attestation(packet, receipt)
    registry.register_original(receipt['path'], receipt['source_id'], receipt['sha256'],
                               producer_attestation=proof)
    return receipt


def test_comment_only_helper_preserves_registered_projection_and_dedupe(packet, tmp_path, monkeypatch):
    receipt = record(packet, tmp_path, monkeypatch)
    query = lambda: ObservedRunQueries().query(receipt['source_id'], receipt['sha256'], SNAPSHOTS_TABLE)
    before = query()['rows']
    old_policy = producer.policy()
    module = producer.resident_match_plans
    from pathlib import Path
    formatted = tmp_path / 'same_helper.py'
    formatted.write_bytes(Path(module.__file__).read_bytes() + b'\n# harmless formatting control\n')
    monkeypatch.setattr(module, '__file__', str(formatted))
    assert producer.policy()['source_policy_digest'] != old_policy['source_policy_digest']
    assert producer.policy()['native_guard_digest'] == old_policy['native_guard_digest']
    assert query()['rows'] == before
    assert write_prefix(packet, tmp_path / 'store')['state'] == 'already_recorded'
    assert producer.attestation(packet, receipt)['policy'] == old_policy
    assert registry.inspect_original(receipt['path'])['sha256'] == receipt['sha256']


@pytest.mark.parametrize('change', ['semantic_version', 'native_guard', 'source_hash', 'schema', 'flags', 'label'])
def test_unknown_semantics_or_tampering_still_rejected(packet, tmp_path, monkeypatch, change):
    document = tactical_document(packet, monkeypatch)
    if change == 'semantic_version': document['policy']['policy_id'] = 'same_source_resident_manager_settings_v2'
    elif change == 'native_guard': document['policy']['native_guard_digest'] = 'a' * 64
    elif change == 'source_hash': document['policy']['source_policy_digest'] = 'G' * 64
    elif change == 'schema': document['schema_version'] = 2
    elif change == 'flags': document['samples'][0]['sides'][0]['raw_selection_flags_hex'] = '00' * 11
    else: document['samples'][0]['sides'][0]['options'][0]['name'] = 'Invented semantic label'
    sample = document['samples'][0]
    sample['summary_sha256'] = hashlib.sha256(producer._json({k: v for k, v in sample.items()
        if k not in ('summary_sha256', 'observed_at_unix')}).encode()).hexdigest()
    with pytest.raises(ValueError): producer.validate(document, packet)


def test_changed_host_native_contract_is_not_implicitly_supported(packet, monkeypatch):
    document = tactical_document(packet, monkeypatch)
    module = producer.prepared_tactics_fields
    spans = list(module.NATIVE_SPANS)
    address, raw = spans[0]
    spans[0] = (address, bytes([raw[0] ^ 1]) + raw[1:])
    monkeypatch.setattr(module, 'NATIVE_SPANS', spans)
    with pytest.raises(ValueError, match='semantic policy'): producer.validate(document, packet)
    with pytest.raises(ValueError, match='semantic policy'): producer.policy()


@pytest.mark.parametrize('state', [None, 'not_requested', 'unavailable'])
def test_legacy_absent_optional_tactics_still_opens(packet, tmp_path, monkeypatch, state):
    monkeypatch.setattr(registry, 'REGISTRY_PATH', tmp_path / 'registry.json')
    if state is not None: packet['tactical_observation'] = {'state': state}
    receipt = write_prefix(packet, tmp_path / 'store')
    registry.register_original(receipt['path'], receipt['source_id'], receipt['sha256'])
    with open_run(receipt['source_id']) as (_, provenance):
        assert provenance['counts']['completed_pass_events'] == 1


def test_changed_host_label_semantics_do_not_relabel_old_capture(packet, monkeypatch):
    document = tactical_document(packet, monkeypatch)
    names = dict(producer.prepared_tactic_instructions.OPTION_NAMES)
    names[64] = 'Different semantic label'
    monkeypatch.setattr(producer.prepared_tactic_instructions, 'OPTION_NAMES', names)
    with pytest.raises(ValueError, match='label policy'):
        producer.validate(document, packet)
