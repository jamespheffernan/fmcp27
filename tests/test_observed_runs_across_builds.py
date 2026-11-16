"""Observed runs recorded on the pinned build stay readable on a mapped build (27.0.1)."""
import hashlib
import json

import pytest

from fm_live_mcp import active_pass_attempts as apa, address_book, observed_pass_attempts as opa


def test_pinned_digest_is_the_digest_of_the_pinned_spans():
    if address_book.MAP is not None:
        pytest.skip('a map is forced: the spans are rewritten')
    spans = apa.live_retained_pass_events.ATTEMPT_NATIVE_SPANS + apa.pass_field_position.NATIVE_SPANS
    digest = hashlib.sha256(json.dumps([(rva, raw.hex()) for rva, raw in spans], separators=(',', ':')).encode()).hexdigest()
    assert digest == apa.PINNED_GUARD_DIGEST
    assert apa.recorded_policies() == [apa.source_policy()]


def test_mapped_build_accepts_the_pinned_policy_and_its_own_only(monkeypatch):
    pinned = apa.source_policy()
    mapped = dict(pinned, native_plugin_sha256='68adfde2' + '0' * 56, native_guard_digest='1' * 64)
    monkeypatch.setattr(apa, 'source_policy', lambda: mapped)
    policies = apa.recorded_policies()
    assert policies[0] == mapped and policies[1]['native_plugin_sha256'] == address_book.PINNED_SHA256
    assert policies[1]['native_guard_digest'] == apa.PINNED_GUARD_DIGEST
    entry = {'selection_id': 'a' * 64}
    proof = {'producer': 'verified_observed_recorder', 'schema_version': 1, 'source_document_id': opa.DOCUMENT,
             'selection_id': entry['selection_id'], 'source_document_sha256': 'b' * 64,
             'source_incarnation_id': 'c' * 64}
    for policy in policies:
        opa.validate_attestation(entry, dict(proof, policy=policy), check_original=False)
    with pytest.raises(ValueError, match='Unsupported'):
        opa.validate_attestation(entry, dict(proof, policy=dict(mapped, native_guard_digest='2' * 64)),
                                 check_original=False)


def test_tactical_policy_names_the_decoder_contract_on_a_mapped_build(monkeypatch):
    """The recorder's tactical policy hashed the guard spans after the address map had rewritten
    them, so on 27.0.1 `policy()` refused its own digest and every recording lost its tactics."""
    from fm_live_mcp import observed_run_tactical_capture as otc, prepared_tactic_roles as roles
    if address_book.MAP is None:
        assert otc.policy()['native_guard_digest'] == otc.NATIVE_GUARD_DIGEST_V1
        rewritten = tuple((rva + 0x1000, bytes(reversed(raw))) for rva, raw in roles.NATIVE_SPANS)
        monkeypatch.setattr(roles, 'NATIVE_SPANS', rewritten)        # what the import hook does on a mapped build
        monkeypatch.setitem(address_book.ACTIVE, 'state', 'mapped')
    assert otc.policy()['native_guard_digest'] == otc.NATIVE_GUARD_DIGEST_V1
    assert address_book.pinned_constant(roles, 'NATIVE_SPANS') != () and \
        all(type(rva) is int and type(raw) is bytes for rva, raw in address_book.pinned_constant(roles, 'NATIVE_SPANS'))
