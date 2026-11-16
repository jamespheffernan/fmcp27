"""Bind the direct-import tactic tests (test_tactic_*.py) to the installed game build.

The tactic writer's files carry the pinned build's addresses, guard hashes and identity. On a
later build with an address map, production runs them through the map's rewrite
(fm_live_mcp/adviser_book.py): the two scripts re-run themselves as `__main__`, and their
siblings load through its import finder. A test that imports those files directly gets neither,
so on such a build it would run pinned addresses against the installed plugin and fail its
identity checks.

This file gives the tests the same binding: the siblings imported by name load through the
finder, and a file of adviser/pi loaded by path loads through the same rewriting loader. On the
pinned build, on an unsupported build, or without the reader, nothing here changes anything.
"""
import importlib.util
import os
from pathlib import Path
import sys

PI = Path(__file__).resolve().parents[1] / 'pi'
REPOSITORY = Path(__file__).resolve().parents[2]

# The reader that ships beside this adviser, unless the caller named another.
if (REPOSITORY / 'fm_live_mcp').is_dir():
    os.environ.setdefault('PI_FM_TACTIC_READER_ROOT', str(REPOSITORY))
_reader_root = os.environ.get('PI_FM_TACTIC_READER_ROOT')
if _reader_root and _reader_root not in sys.path:
    sys.path.insert(0, _reader_root)

try:
    from fm_live_mcp import adviser_book
except ImportError:
    adviser_book = None

if adviser_book is not None and adviser_book.state()['state'] == 'mapped':
    adviser_book.install(PI)
    _plain_spec = importlib.util.spec_from_file_location

    def _bound_spec(name, location=None, *, loader=None, **kwargs):
        if loader is None and location is not None:
            path = Path(location).resolve()
            if path.parent == PI and path.suffix == '.py':
                loader = adviser_book.source_loader(name, path)
        return _plain_spec(name, location, loader=loader, **kwargs)

    importlib.util.spec_from_file_location = _bound_spec
