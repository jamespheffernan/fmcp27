"""Explicit host-only import from a reviewed original terminal and immutable parent.

Default is preflight: writes only the proposed NEW attestation file. --apply
requires that the exact parent already exists in the selected ObservationStore;
it never saves an observation, finalizes a link or reads/attaches to the game.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fm_live_mcp.match_period_observations import ObservationStore, canonical, digest
from fm_live_mcp.possession_period_attestations import build, write, publish_new_artifact


def read_pinned(path, expected, limit):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('Absolute reviewed input path required')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_size > limit:
            raise ValueError('Invalid reviewed input metadata')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        after = os.fstat(descriptor)
        if ((before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns)
                or path.lstat().st_ino != before.st_ino or len(raw) > limit):
            raise ValueError('Reviewed source changed during read')
    finally:
        os.close(descriptor)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Reviewed source SHA differs')
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('parent', 'expected-parent-sha256', 'expected-parent-capture-id',
                 'terminal', 'expected-terminal-sha256', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--store-root')
    args = parser.parse_args()
    parent_raw = read_pinned(args.parent, args.expected_parent_sha256, 262144)
    bundle = json.loads(parent_raw)
    parent = bundle['observation']
    if bundle['capture_id'] != digest(parent) or bundle['capture_id'] != args.expected_parent_capture_id:
        raise ValueError('Reviewed parent capture identity differs')
    terminal_raw = read_pinned(args.terminal, args.expected_terminal_sha256, 4 * 1024 * 1024)
    document = build(terminal_raw, parent)
    output = Path(args.output)
    if not output.is_absolute():
        raise ValueError('Absolute new derived-artifact path required')
    raw = canonical(document)
    publish_new_artifact(output, raw)
    receipt = dict(state='reviewed_original_source_attestation_preflight',
        parent_capture_id=digest(parent), original_parent_sha256=args.expected_parent_sha256,
        original_terminal_sha256=args.expected_terminal_sha256, proposed_path=str(output),
        proposed_sha256=hashlib.sha256(raw).hexdigest(), attestation_id=document['attestation_id'],
        original_observation_modified=False, finalized_links_modified=False,
        game_access=False, new_native_observation=False, retained_bytes_used_to_create_witness=False)
    if args.apply:
        store = ObservationStore(args.store_root)
        original_path = store.path(parent['career'], parent['fixture'])
        before = original_path.read_bytes()
        existing = store.observations(parent['career'], parent['fixture'])
        if existing['observations'].get(digest(parent)) != parent:
            raise ValueError('Exact immutable parent is not already in selected store')
        imported = write(store.root, parent, document)
        if original_path.read_bytes() != before or store.observations(parent['career'], parent['fixture']) != existing:
            raise ValueError('Parent index or finalized links changed during metric import')
        receipt.update(state='imported_separate_metric_attestation_parent_and_pins_unchanged', import_result=imported)
    if read_pinned(args.parent, args.expected_parent_sha256, 262144) != parent_raw:
        raise ValueError('Original parent changed')
    if read_pinned(args.terminal, args.expected_terminal_sha256, 4 * 1024 * 1024) != terminal_raw:
        raise ValueError('Original terminal changed')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
