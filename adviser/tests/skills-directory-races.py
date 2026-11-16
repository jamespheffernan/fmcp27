"""Deterministic real-filesystem replacements at descriptor operations."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('guide_reader', PROJECT / 'pi/fm-skill-reader.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
ORIGINAL_OPEN, ORIGINAL_READ, ORIGINAL_CLOSE = os.open, os.read, os.close
ID = 'fm-tools'
SAFE = b'---\nname: fm-tools\n---\nApproved procedure.\n'
OUTSIDE = b'---\nname: fm-tools\n---\nOUTSIDE_CONTENT_MUST_NOT_BE_READ\n'


def check_race(timing):
    with tempfile.TemporaryDirectory(dir=PROJECT / 'evidence') as scratch:
        scratch = Path(scratch)
        root = scratch / 'skills'
        folder = root / ID
        folder.mkdir(parents=True)
        target = folder / 'SKILL.md'
        target.write_bytes(SAFE)
        outside = scratch / 'outside'
        outside_folder = outside / ID
        outside_folder.mkdir(parents=True)
        outside_file = outside_folder / 'SKILL.md'
        outside_file.write_bytes(OUTSIDE)
        outside_identity = (outside_file.stat().st_dev, outside_file.stat().st_ino)
        fired = False
        opened = set()
        outside_reads = 0

        def swap_root():
            root.rename(scratch / 'old-root')
            if timing == 'after_root_open_regular':
                outside.rename(root)
            else:
                root.symlink_to(outside, target_is_directory=True)

        def swap_folder():
            folder.rename(root / 'old-guide')
            if timing == 'after_guide_open_regular':
                outside_folder.rename(folder)
            else:
                folder.symlink_to(outside_folder, target_is_directory=True)

        def racing_open(path, flags, *args, **kwargs):
            nonlocal fired
            name = os.fspath(path)
            is_root = name == 'skills'
            is_guide = name == ID
            if not fired and ((timing == 'before_root_open' and is_root)
                              or (timing == 'before_guide_open' and is_guide)):
                fired = True
                (swap_root if is_root else swap_folder)()
            if not fired and name == 'SKILL.md' and timing in ('before_leaf_open_symlink', 'before_leaf_open_regular'):
                fired = True
                target.rename(folder / 'old.md')
                if timing == 'before_leaf_open_symlink':
                    target.symlink_to(outside_file)
                else:
                    outside_file.rename(target)
            fd = ORIGINAL_OPEN(path, flags, *args, **kwargs)
            opened.add(fd)
            if not fired and ((timing in ('after_root_open', 'after_root_open_regular') and is_root)
                              or (timing in ('after_guide_open', 'after_guide_open_regular') and is_guide)):
                fired = True
                (swap_root if is_root else swap_folder)()
            return fd

        def guarded_read(fd, size):
            nonlocal fired, outside_reads
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) == outside_identity:
                outside_reads += 1
                raise AssertionError('Outside file reached os.read')
            raw = ORIGINAL_READ(fd, size)
            if not fired and timing in ('after_leaf_read_directory', 'after_leaf_read_file'):
                fired = True
                if timing == 'after_leaf_read_directory':
                    swap_folder()
                else:
                    target.write_bytes(SAFE + b'changed')
            return raw

        def tracked_close(fd):
            ORIGINAL_CLOSE(fd)
            opened.remove(fd)

        os.open, os.read, os.close = racing_open, guarded_read, tracked_close
        try:
            try:
                result = reader.read_guide(str(root), ID)
            except (OSError, ValueError):
                pass
            else:
                raise AssertionError('Changed directory/file must withhold all content: ' + repr(result))
        finally:
            os.open, os.read, os.close = ORIGINAL_OPEN, ORIGINAL_READ, ORIGINAL_CLOSE
        assert fired, timing + ': replacement injection did not execute'
        assert outside_reads == 0 and opened == set(), (timing, outside_reads, opened)
        return dict(timing=timing, withheld=True, outside_file_reads=outside_reads, descriptors_closed=True)


cases = [check_race(timing) for timing in (
    'before_root_open', 'after_root_open', 'after_root_open_regular',
    'before_guide_open', 'after_guide_open', 'after_guide_open_regular',
    'before_leaf_open_symlink', 'before_leaf_open_regular',
    'after_leaf_read_directory', 'after_leaf_read_file',
)]

with tempfile.TemporaryDirectory(dir=PROJECT / 'evidence') as scratch:
    root = Path(scratch)
    (root / ID).mkdir()
    payload = SAFE + b'a' * (reader.MAX_BYTES - len(SAFE))
    (root / ID / 'SKILL.md').write_bytes(payload)
    # Real short reads must accumulate through EOF rather than reject/truncate.
    os.read = lambda fd, size: ORIGINAL_READ(fd, min(size, 7))
    try:
        result = reader.read_guide(str(root), ID)
    finally:
        os.read = ORIGINAL_READ
    assert result['content'].encode() == payload
    assert result['sha256'] == hashlib.sha256(payload).hexdigest()
    # Even a close failure must withhold the otherwise valid result and close
    # all remaining lineage descriptors.
    closed = []
    def failing_close(fd):
        ORIGINAL_CLOSE(fd)
        closed.append(fd)
        if len(closed) == 1:
            raise OSError('controlled close failure')
    os.close = failing_close
    try:
        try:
            reader.read_guide(str(root), ID)
        except OSError:
            pass
        else:
            raise AssertionError('close failure returned guide content')
    finally:
        os.close = ORIGINAL_CLOSE
    assert len(closed) >= 3

print(json.dumps(dict(state='PASS', replacement_cases=cases, short_reads_at_exact_64KiB=True,
                      close_failure_withheld=True, outside_content_returned=False)))
