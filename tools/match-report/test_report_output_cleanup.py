"""Owned-partial cleanup under concurrent path changes; all files are fixtures."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import report_output

DATA = {'fixture': {'date': '2030-11-30'}, 'teams': [{'short_name': 'N'}, {'short_name': 'L'}]}
HTML = b'<!doctype html>owned original'


def run_case(root, variant, module=report_output):
    root.mkdir(parents=True, exist_ok=True)
    path, moved, target = root/'requested.html', root/'owned-moved.html', root/'target.txt'
    def fail_fsync(fd):
        if variant == 'removed':path.unlink()
        elif variant != 'unchanged':
            path.rename(moved)
            if variant == 'regular':path.write_bytes(b'unrelated replacement')
            elif variant == 'symlink':
                target.write_bytes(b'preserve target');path.symlink_to(target)
            elif variant == 'directory':path.mkdir()
        raise OSError('declared fsync failure')
    try:
        with patch.object(module.os, 'fsync', side_effect=fail_fsync):
            module.publish(DATA, HTML, outputs=root, filename='requested.html')
    except OSError as error:
        assert 'declared fsync failure' in str(error)
    else:raise AssertionError('fsync refusal lost')
    if variant in ('removed', 'renamed'):assert not path.exists()
    if variant == 'unchanged':assert path.read_bytes() == HTML
    if variant == 'regular':assert path.read_bytes() == b'unrelated replacement'
    if variant == 'symlink':assert path.is_symlink() and target.read_bytes() == b'preserve target'
    if variant == 'directory':assert path.is_dir()
    if variant not in ('unchanged', 'removed'):assert moved.read_bytes() == HTML


class Cleanup(unittest.TestCase):
    def test_failed_owned_artifact_and_concurrent_leaf_variants(self):
        for variant in ('unchanged', 'removed', 'renamed', 'regular', 'symlink', 'directory'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                run_case(Path(tmp).resolve()/'Agent Outputs', variant)

    def test_postwrite_identity_failure_retains_artifact_and_closes_descriptor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()/'Agent Outputs'
            descriptors = []
            def failed_fstat(fd):
                descriptors.append(fd);raise OSError('descriptor identity unavailable')
            with patch.object(report_output.os, 'fstat', side_effect=failed_fstat):
                with self.assertRaisesRegex(OSError, 'identity unavailable'):
                    report_output.publish(DATA, HTML, outputs=root, filename='requested.html')
            self.assertEqual((root/'requested.html').read_bytes(), HTML)
            with self.assertRaises(OSError):os.fstat(descriptors[0])

    def test_write_failure_retains_partial_and_never_unlinks_canonical_leaf(self):
        real_fdopen = os.fdopen
        class Partial:
            def __init__(self, file):self.file = file
            def __enter__(self):return self
            def __exit__(self, *args):self.file.close()
            def write(self, raw):
                self.file.write(raw[:8])
                raise OSError('partial write failure')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()/'Agent Outputs'
            with patch.object(report_output.os, 'fdopen', side_effect=lambda *a, **k: Partial(real_fdopen(*a, **k))), patch.object(report_output.os, 'unlink') as unlink:
                with self.assertRaisesRegex(OSError, 'partial write failure'):
                    report_output.publish(DATA, HTML, outputs=root, filename='requested.html')
                unlink.assert_not_called()
            self.assertEqual((root/'requested.html').read_bytes(), HTML[:8])

    def test_replacement_after_former_cleanup_stat_point_is_never_unlinked(self):
        # The removed cleanup stat/unlink seam must not run at all on failure.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()/'Agent Outputs'
            with patch.object(report_output.os, 'stat') as stat_call, patch.object(report_output.os, 'unlink') as unlink, patch.object(report_output.os, 'fsync', side_effect=OSError('fsync failure')):
                with self.assertRaisesRegex(OSError, 'fsync failure'):
                    report_output.publish(DATA, HTML, outputs=root, filename='requested.html')
                stat_call.assert_not_called()
                (root/'requested.html').rename(root/'owned-moved.html')
                (root/'requested.html').write_bytes(b'concurrent replacement')
                unlink.assert_not_called()
            self.assertEqual((root/'requested.html').read_bytes(), b'concurrent replacement')

    @unittest.skipUnless(sys.platform == 'darwin', 'requires actual macOS publisher sandbox')
    def test_same_cleanup_variants_under_actual_publisher_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()/'Agent Outputs';root.mkdir()
            result = subprocess.run(['/usr/bin/sandbox-exec', '-f', str(Path(__file__).parent/'report_publish.sb'),
                '-D', 'OUTPUTS_ROOT='+str(root), '/usr/bin/python3', '-B', str(Path(__file__).resolve()),
                '--sandbox-cases', str(root)], capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--sandbox-cases':
        for variant in ('unchanged', 'removed', 'renamed', 'regular', 'symlink', 'directory'):
            run_case(Path(sys.argv[2])/variant, variant)
        print('Six actual sandbox cleanup variants passed')
    else:unittest.main()
