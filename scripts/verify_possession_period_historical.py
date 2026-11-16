"""Real original/host-artifact readback; frozen retained source, never a live run.

Copies the existing normal host period index into this task's private tmp store,
derives/imports a new artifact from the original pinned terminal, then projects
the genuine retained fixture. No original index/observation/link is modified.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fm_live_mcp.match_period_observations import ObservationStore, digest
from fm_live_mcp.possession_period_attestations import load
from fm_live_mcp.retained_possession_periods import project

WORKTREE = Path(__file__).resolve().parents[1]
CANONICAL = Path('/Volumes/4TB Private/Offloaded/FMCP 27')
EVIDENCE = CANONICAL / 'evidence/batches/period-report-continuity-187'
PARENT = EVIDENCE / 'observation.json'
TERMINAL = CANONICAL / 'evidence/batches/forest-halftime-live-182/terminal-1794090520907917000.json'
DEST = WORKTREE / 'tmp/possession-period-historical-readback'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def exclusive(path, raw, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError('Existing historical readback source differs')
    else:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)


parent_raw = PARENT.read_bytes()
assert sha(parent_raw) == '8f635affabe2c9746c1e8ab5d6a14807011af52cfdca6bf1e5be943a72cf2747'
parent = json.loads(parent_raw)['observation']
assert digest(parent) == '96a4c9a070ecea5badb975a5146dc61aadc63f19e2fc675b06463a9e45cd439f'
normal_path = Path(json.loads((EVIDENCE / 'normal-import-receipt.json').read_text())['fixture_path'])
normal_store = ObservationStore(normal_path.parents[1])
normal_document = normal_store.observations(parent['career'], parent['fixture'])
assert normal_document['observations'][digest(parent)] == parent
index_before = normal_path.read_bytes()
assert normal_document == json.loads(index_before)
store = ObservationStore(DEST / 'periods')
store.root.mkdir(parents=True, exist_ok=True, mode=0o700)
index_path = store.path(parent['career'], parent['fixture'])
exclusive(index_path, index_before)
assert store.observations(parent['career'], parent['fixture']) == normal_document
artifact_path = DEST / 'new-derived-attestation.json'
command = [sys.executable, str(WORKTREE / 'scripts/import_possession_period_attestation.py'),
    '--parent', str(PARENT), '--expected-parent-sha256', sha(parent_raw),
    '--expected-parent-capture-id', digest(parent), '--terminal', str(TERMINAL),
    '--expected-terminal-sha256', '9ee6e05dd61b20ba3b4d0a1aa71e72825768f0ced6204889c003c5bb7ebc9a9c',
    '--output', str(artifact_path), '--apply', '--store-root', str(store.root)]
result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
import_receipt = json.loads(result.stdout)
assert import_receipt['state'] == 'imported_separate_metric_attestation_parent_and_pins_unchanged'
document = load(store.root, parent)
assert document == json.loads(artifact_path.read_bytes())
assert index_path.read_bytes() == index_before
assert normal_path.read_bytes() == index_before
fixture_path = WORKTREE / 'tests/fixtures/possession_events_forest_2030_11_11.json.gz'
with gzip.open(fixture_path, 'rt') as stream:
    packet = json.load(stream)
link = json.loads((EVIDENCE / 'period-link.json').read_text())
assert link['capture_id'] == digest(parent)
report = project(bytes.fromhex(packet['events_hex']), packet['players'], packet['fixture'],
    packet['native_match_key'], link, parent, attestation=document)
assert report['state'] == 'available'
assert [[(period['possession_won_events'], period['possession_lost_events']) for period in side['periods']]
        for side in report['sides']] == [[(47, 44), (45, 45)], [(39, 48), (36, 50)]]
exclusive(DEST / 'historical-report.json', (json.dumps(report, indent=2) + '\n').encode())
receipt = dict(state='genuine_original_new_host_artifact_import_and_frozen_retained_readback_verified',
    fixture_scope='Newcastle-Forest 2030-11-11 historical immutable original/retained sources, not a fresh match',
    fixture_sha256=sha(fixture_path.read_bytes()), original_parent_sha256=sha(parent_raw),
    original_terminal_sha256=sha(TERMINAL.read_bytes()), original_normal_index_sha256=sha(index_before),
    original_normal_index_unchanged=normal_path.read_bytes() == index_before,
    copied_parent_and_finalized_links_unchanged=index_path.read_bytes() == index_before,
    import_receipt=import_receipt, report_path=str(DEST / 'historical-report.json'),
    report_sha256=sha((DEST / 'historical-report.json').read_bytes()),
    new_artifact_read_back_from_store=True, game_access=False, fresh_native_observation=False,
    installed_or_ordinary_capability_verified=False, parent_epoch_or_pin_policy_bypassed=False)
(DEST / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
