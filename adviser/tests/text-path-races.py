"""Force filesystem replacements at the OS call, without sleeps or fake writes."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile


root = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('text_writer', root / 'pi/fm-text-files.py')
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)
original_open = os.open

for timing in ('before_parent_open', 'after_parent_open', 'before_file_open'):
    with tempfile.TemporaryDirectory(dir=root / 'evidence') as scratch:
        scratch = Path(scratch)
        parent = scratch / 'checked'
        parent.mkdir()
        redirected = scratch / 'redirected'
        redirected.mkdir()
        target = parent / 'report.txt'
        moved = scratch / 'original'
        swapped = False

        def racing_open(path, flags, *args, **kwargs):
            global swapped
            if not swapped and Path(path).name == 'checked':
                if timing == 'before_parent_open':
                    parent.rename(moved)
                    parent.symlink_to(redirected, target_is_directory=True)
                    swapped = True
                elif timing == 'after_parent_open':
                    fd = original_open(path, flags, *args, **kwargs)
                    parent.rename(moved)
                    parent.symlink_to(redirected, target_is_directory=True)
                    swapped = True
                    return fd
            if not swapped and Path(path).name == 'report.txt' and timing == 'before_file_open':
                target.symlink_to(redirected / 'stolen.txt')
                swapped = True
            return original_open(path, flags, *args, **kwargs)

        os.open = racing_open
        try:
            try:
                writer.write_text({'path': str(target), 'content': 'safe'})
                raise AssertionError('a replaced destination must be rejected')
            except OSError:
                pass
        finally:
            os.open = original_open
        assert swapped, f'{timing}: race injection did not run'
        assert list(redirected.iterdir()) == [], f'{timing}: write was redirected'
        if timing == 'after_parent_open':
            assert not (moved / 'report.txt').exists(), 'remove output when its receipt path became stale'

print(json.dumps({'checked_interleavings': 3}))
