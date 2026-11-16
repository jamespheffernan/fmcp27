"""Fault injection at real publication boundaries; no production assertion edits."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

import pytest

from fm_live_mcp import possession_period_attestations as a
from fm_live_mcp.match_period_observations import ObservationStore, canonical, digest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/possession_period_witness_forest_2030_11_11.json'


def setup(monkeypatch, tmp_path, entrypoint):
    fixture = json.loads(FIXTURE.read_text())
    parent, document = fixture['parent_observation'], fixture['attestation']
    store = ObservationStore(tmp_path / 'periods')
    store.save(parent)
    store.finalize(parent['career'], parent['fixture'], 123, digest(parent), 'f' * 64)
    original_index = store.path(parent['career'], parent['fixture'])
    before = original_index.read_bytes()
    if entrypoint == 'stored':
        destination = a._path(store.root, digest(parent))

        def attempt():
            return a.write(store.root, parent, document)
    else:
        terminal = Path(parent['seed_provenance']['terminal_path'])
        if not terminal.exists():
            pytest.skip('Original terminal required for actual importer path; stored-artifact failures still run')
        parent_path = tmp_path / 'reviewed-parent.json'
        parent_raw = canonical({'capture_id': digest(parent), 'observation': parent})
        parent_path.write_bytes(parent_raw)
        destination = tmp_path / 'proposal.json'
        spec = importlib.util.spec_from_file_location('possession_importer_control', ROOT / 'scripts/import_possession_period_attestation.py')
        importer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(importer)
        monkeypatch.setattr(sys, 'argv', [str(ROOT / 'scripts/import_possession_period_attestation.py'),
            '--parent', str(parent_path), '--expected-parent-sha256', hashlib.sha256(parent_raw).hexdigest(),
            '--expected-parent-capture-id', digest(parent), '--terminal', str(terminal),
            '--expected-terminal-sha256', fixture['original_terminal_sha256'], '--output', str(destination)])
        attempt = importer.main
    return attempt, destination, canonical(document), original_index, before


def staging_files(destination):
    return list(destination.parent.glob('.possession-period-artifact-*'))


@pytest.mark.parametrize('entrypoint', ['stored', 'proposal'])
@pytest.mark.parametrize('fault', ['partial_write', 'short_write', 'flush', 'file_fsync', 'staging_readback', 'link'])
def test_before_commit_failures_publish_nothing_and_retry_cleanly(monkeypatch, tmp_path, entrypoint, fault):
    attempt, destination, raw, original_index, before = setup(monkeypatch, tmp_path, entrypoint)
    with monkeypatch.context() as inject:
        real_fdopen = a.os.fdopen
        real_readback = a._publication_bytes

        class BrokenWriter:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): return self.stream.__exit__(*args)
            def __getattr__(self, name): return getattr(self.stream, name)
            def write(self, value):
                if fault in ('partial_write', 'short_write'):
                    self.stream.write(value[:32])
                    self.stream.flush()
                    if fault == 'partial_write': raise OSError('injected partial32 write')
                    return 32
                return self.stream.write(value)
            def flush(self):
                self.stream.flush()
                if fault == 'flush': raise OSError('injected flush failure')

        def fdopen(descriptor, mode, *args, **kwargs):
            stream = real_fdopen(descriptor, mode, *args, **kwargs)
            return BrokenWriter(stream) if mode == 'wb' else stream

        if fault in ('partial_write', 'short_write', 'flush'):
            inject.setattr(a.os, 'fdopen', fdopen)
        elif fault == 'file_fsync':
            inject.setattr(a.os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('injected file fsync')))
        elif fault == 'staging_readback':
            inject.setattr(a, '_publication_bytes', lambda path: b'wrong' if Path(path).name.startswith('.possession-period-artifact-') else real_readback(path))
        elif fault == 'link':
            inject.setattr(a.os, 'link', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('injected link failure')))
        with pytest.raises((OSError, ValueError)):
            attempt()
    assert not destination.exists(), 'No final path may expose the partial/unvalidated staging bytes'
    assert not staging_files(destination), 'Owned unpublished staging inode must be cleaned'
    assert original_index.read_bytes() == before
    attempt()
    assert destination.read_bytes() == raw
    assert not staging_files(destination)
    assert original_index.read_bytes() == before


@pytest.mark.parametrize('entrypoint', ['stored', 'proposal'])
@pytest.mark.parametrize('fault', ['final_readback', 'directory_fsync'])
def test_after_commit_failure_leaves_complete_valid_final_and_retry_is_idempotent(monkeypatch, tmp_path, entrypoint, fault):
    attempt, destination, raw, original_index, before = setup(monkeypatch, tmp_path, entrypoint)
    with monkeypatch.context() as inject:
        real_readback, real_fsync = a._publication_bytes, a.os.fsync

        def readback(path):
            if Path(path) == destination and destination.exists():
                raise OSError('injected final readback failure after publication')
            return real_readback(path)

        def fsync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError('injected directory fsync failure after publication')
            return real_fsync(descriptor)

        inject.setattr(a, '_publication_bytes', readback) if fault == 'final_readback' else inject.setattr(a.os, 'fsync', fsync)
        with pytest.raises(OSError): attempt()
    assert destination.read_bytes() == raw
    assert json.loads(destination.read_bytes())['attestation_id']
    inode = destination.stat().st_ino
    assert not staging_files(destination)
    attempt()
    assert destination.read_bytes() == raw and destination.stat().st_ino == inode
    assert original_index.read_bytes() == before


@pytest.mark.parametrize('entrypoint', ['stored', 'proposal'])
@pytest.mark.parametrize('same_bytes', [False, True])
def test_concurrent_final_creation_never_overwrites_or_deletes_the_other_inode(monkeypatch, tmp_path, entrypoint, same_bytes):
    attempt, destination, raw, original_index, before = setup(monkeypatch, tmp_path, entrypoint)
    other = raw if same_bytes else b'other writer content'
    other_inode = None

    def race(staging, target, **kwargs):
        nonlocal other_inode
        assert Path(target) == destination
        destination.write_bytes(other)
        destination.chmod(0o600)
        other_inode = destination.stat().st_ino
        raise FileExistsError('injected competing publisher')

    with monkeypatch.context() as inject:
        inject.setattr(a.os, 'link', race)
        if same_bytes: attempt()
        else:
            with pytest.raises(ValueError): attempt()
    assert destination.read_bytes() == other and destination.stat().st_ino == other_inode
    assert not staging_files(destination)
    assert original_index.read_bytes() == before


@pytest.mark.parametrize('entrypoint', ['stored', 'proposal'])
def test_replaced_final_is_never_removed_by_failure_cleanup(monkeypatch, tmp_path, entrypoint):
    attempt, destination, _, original_index, before = setup(monkeypatch, tmp_path, entrypoint)
    real_readback = a._publication_bytes
    replacement_inode = None

    def replace_after_commit(path):
        nonlocal replacement_inode
        if Path(path) == destination and destination.exists():
            destination.unlink()  # the deliberately competing writer, not production rollback
            destination.write_bytes(b'raced replacement must survive')
            destination.chmod(0o600)
            replacement_inode = destination.stat().st_ino
        return real_readback(path)

    with monkeypatch.context() as inject:
        inject.setattr(a, '_publication_bytes', replace_after_commit)
        with pytest.raises(ValueError): attempt()
    assert destination.read_bytes() == b'raced replacement must survive'
    assert destination.stat().st_ino == replacement_inode
    assert not staging_files(destination)
    assert original_index.read_bytes() == before


def test_replaced_staging_inode_is_not_deleted_as_our_rollback(monkeypatch, tmp_path):
    attempt, destination, _, original_index, before = setup(monkeypatch, tmp_path, 'stored')
    replacement_path = None
    replacement_inode = None

    def replace_stage_and_fail(staging, target, **kwargs):
        nonlocal replacement_path, replacement_inode
        replacement_path = Path(staging)
        replacement_path.unlink()  # competing actor replaces the private staging name
        replacement_path.write_bytes(b'foreign staging replacement')
        replacement_inode = replacement_path.stat().st_ino
        raise OSError('injected link failure with changed staging inode')

    monkeypatch.setattr(a.os, 'link', replace_stage_and_fail)
    with pytest.raises(OSError): attempt()
    assert not destination.exists()
    assert replacement_path.read_bytes() == b'foreign staging replacement'
    assert replacement_path.stat().st_ino == replacement_inode
    assert original_index.read_bytes() == before
