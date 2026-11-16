"""Suite-wide markers, isolation and live-game serialisation. docs/TESTING.md explains the rules.

Markers are applied here, centrally, so test files do not carry them:

* ``live``: reads the running Football Manager 27. Any file named ``*_live.py`` and every test
  listed in ``tests/suite_profile.json`` (measured: it spawned a reader with the game's pid).
  All live tests share one xdist group, so under ``-n`` they run one at a time on one worker,
  and a file lock serialises them across concurrent pytest processes as well.
* ``slow``: measured at or above the profile's threshold in a full sequential run.
* ``evidence``: measured: it read git-ignored files under ``evidence/``.
* ``pinned_build``: its module imports ``tests/_pinned_build.py`` (the pinned game build's files).
* ``mapped_build``: a file named ``*_mapped.py``: checks the installed build through its address
  map; runs only in a session that addresses the installed build (see "game builds" below).

The default selection (``-m "not slow and not live and not mapped_build"``) is in ``pyproject.toml``. ``--complete``
clears it; naming test files or ids on the command line clears it too, so ``pytest tests/x.py``
runs the whole file.

Isolation. Every test runs between a snapshot and a restore of process-global state: environment
variables, ``sys.path``, the working directory and ``sys.modules``. A module-scoped snapshot does
the same around each test file, so a module fixture may change state for its own tests but not for
later files. In ``sys.modules`` the restore puts back any entry a test replaced or removed and
drops any ``fm_live_mcp.*`` entry that was not loaded from the package itself (frozen fixture
sources, stubs, copies from other checkouts). An audit hook fails any test that writes inside the
repository, and any test not marked ``live`` that starts a reader on the game's pid.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import random
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from fm_live_mcp._filelock import lock_exclusive, unlock

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
PROFILE = TESTS / 'suite_profile.json'
LIVE_GROUP = 'fm27-live'
LIVE_LOCK = Path(os.environ.get('FMCP_TEST_LIVE_LOCK') or Path(tempfile.gettempdir()) / 'fmcp27-live-tests.lock')
DEFAULT_MARKEXPR = 'not slow and not live and not mapped_build'
PINNED_HELPER = '_pinned_build'      # tests/_pinned_build.py: the pinned build's files
_spec = importlib.util.find_spec('fm_live_mcp')
PACKAGE = Path(next(iter(_spec.submodule_search_locations))).resolve() if _spec else ROOT / 'fm_live_mcp'
_MISSING = object()

# fm_db_* tools and the manager view start a detached snapshot or knowledge fill when the cache is
# stale; one such fill outlived its test by 22 minutes. Tests never start them (subprocesses inherit
# this). Set FMCP_NO_BACKGROUND_FILL=0 to let a hand-run test start one.
os.environ.setdefault('FMCP_NO_BACKGROUND_FILL', '1')

# Which game build a session addresses (docs/TESTING.md, "Game builds") is decided in
# pytest_configure, before any test module imports fm_live_mcp: `_configure_build`.

# With PYTHONDONTWRITEBYTECODE=1 (agent shells set it) pytest rewrites the asserts of every test
# module again in every process: about 16 s of the 23 s collection, paid once per xdist worker.
# Keep the compiled files in a cache outside the checkout instead of not keeping them at all.
if sys.dont_write_bytecode and not sys.pycache_prefix:
    sys.pycache_prefix = str(Path(tempfile.gettempdir()) / 'fmcp27-pycache')
    sys.dont_write_bytecode = False


# --------------------------------------------------------------------------- options and markers

def pytest_addoption(parser):
    group = parser.getgroup('fmcp27 suite')
    group.addoption('--complete', action='store_true',
                    help='run every test, including slow and live ones (clears the default -m)')
    group.addoption('--suite-shuffle', metavar='SEED', default=None,
                    help='run test files in an order shuffled by SEED (tests keep their order within a file)')
    group.addoption('--suite-probe', metavar='PATH', default=os.environ.get('FMCP_TEST_PROBE'),
                    help='append one JSON line per test (spawns, evidence reads, repo writes) to PATH')


def _explicit_selection(config) -> bool:
    """True when the command line named test files or ids rather than relying on testpaths."""
    from _pytest.config import Config
    return config.args_source == Config.ArgsSource.ARGS


def _markexpr_given_on_command_line(config) -> bool:
    args = config.invocation_params.args
    return any(a == '-m' or (a.startswith('-m') and not a.startswith('--')) for a in args)


def pytest_configure(config):
    if config.option.markexpr == DEFAULT_MARKEXPR and not _markexpr_given_on_command_line(config):
        if config.getoption('--complete') or _explicit_selection(config):
            config.option.markexpr = ''
    _configure_build(config)
    probe = config.getoption('--suite-probe')
    _GUARD.configure(probe)


def pytest_report_header(config):
    expr = config.option.markexpr
    selection = f'fmcp27 selection: {expr!r}' if expr else 'fmcp27 selection: complete run'
    return [selection, f'fmcp27 game build: {_BUILD.describe()}']


# --------------------------------------------------------------------------- game builds
#
# The fixtures, frozen sources and static proofs were made from the pinned build (27.0.0.2493426);
# a game update replaces the installed one. A session addresses exactly one of them:
#
# * pinned (the default): the address book translates nothing (FMCP_ADDRESS_BOOK=off), and
#   FMCP_PLUGIN_PATH names the pinned build's plugin (fm_live_mcp/build_paths.py finds it), so the
#   package's run-time defaults (editor.fmf, filters.fmf, ...) read the pinned files too. Live tests
#   run only when the installed game is the pinned build; `mapped_build` tests do not run.
# * installed: the address book loads the installed build's map, as the MCP server does. Chosen
#   when -m can select only `live` or `mapped_build` tests (`pytest -m live`, `pytest -m
#   mapped_build`), when every named file is a `*_live.py` or `*_mapped.py` file, or with
#   FMCP_TEST_BUILD=installed. Tests that are neither live nor mapped_build do not run, and live tests
#   that compare the running game with the pinned build's code (`pinned_build`) skip.
# * map: FMCP_ADDRESS_MAP=<file> forces a map on every module (the proof in docs/GAME_UPDATE.md).
#
# `pinned_build` marks every test of a module that imports tests/_pinned_build.py at module level,
# directly or through other test modules; they skip, naming what to provide, when no pinned build
# is available. (A test that imports it inside its body checks for the file itself.)
# The controller's decision reaches xdist workers and subprocesses through FMCP_TEST_BUILD and
# FMCP_TEST_INSTALLED_PLUGIN.

def _selects_only(expr: str, markers: frozenset) -> bool:
    """True when the -m expression can select no test that carries none of `markers`."""
    from itertools import combinations
    from _pytest.mark.expression import Expression
    compiled = Expression.compile(expr)
    others = ('slow', 'evidence', 'pinned_build')
    subsets = [set(c) for n in range(len(others) + 1) for c in combinations(others, n)]
    return not any(compiled.evaluate(lambda name, *_a, s=s, **_k: name in s) for s in subsets)


def _explicit_files_are(config, suffixes: tuple) -> bool:
    if not _explicit_selection(config):
        return False
    files = [str(a).split('::', 1)[0] for a in config.args]
    return bool(files) and all(f.endswith(suffixes) for f in files)


def _session_build(config) -> str:
    chosen = os.environ.get('FMCP_TEST_BUILD')
    if chosen in ('pinned', 'installed', 'map'):
        return chosen
    if os.environ.get('FMCP_ADDRESS_MAP'):
        return 'map'
    if os.environ.get('FMCP_ADDRESS_BOOK') == 'on':
        return 'installed'
    expr = config.option.markexpr
    if expr and _markexpr_given_on_command_line(config) and _selects_only(expr, frozenset({'live', 'mapped_build'})):
        return 'installed'
    if _explicit_files_are(config, ('_live.py', '_mapped.py')):
        return 'installed'
    return 'pinned'


class _Build:
    """The session's game build and the facts the skips need (computed once, lazily)."""

    def __init__(self):
        self.mode = 'pinned'
        self.installed_plugin = None        # the real installed plugin, before the session changed anything
        self._pinned_app = _MISSING
        self._installed_is_pinned = None

    def pinned_app(self):
        if self._pinned_app is _MISSING:
            from fm_live_mcp import build_paths
            self._pinned_app = build_paths.pinned_app()
        return self._pinned_app

    def installed_is_pinned(self) -> bool:
        if self._installed_is_pinned is None:
            from fm_live_mcp import build_paths
            self._installed_is_pinned = build_paths._is_pinned_plugin(Path(self.installed_plugin))
        return self._installed_is_pinned

    def describe(self) -> str:
        if self.mode == 'map':
            return f'forced address map {os.environ.get("FMCP_ADDRESS_MAP")}'
        if self.mode == 'installed':
            from fm_live_mcp import address_book
            active = address_book.ACTIVE
            return f'installed ({active["state"]} {active.get("version")}, plugin {self.installed_plugin})'
        app = self.pinned_app()
        return f'pinned 27.0.0.2493426 ({app if app else "not available: pinned_build tests skip"})'


_BUILD = _Build()


def _configure_build(config):
    """Set the environment for the session's build before anything imports fm_live_mcp."""
    mode = _session_build(config)
    environ = os.environ
    environ['FMCP_TEST_BUILD'] = mode
    if 'FMCP_TEST_INSTALLED_PLUGIN' not in environ:
        environ['FMCP_TEST_INSTALLED_PLUGIN'] = environ.get('FMCP_PLUGIN_PATH') or str(
            Path.home() / 'Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app/'
            'Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin')
    _BUILD.mode, _BUILD.installed_plugin = mode, environ['FMCP_TEST_INSTALLED_PLUGIN']
    if mode == 'pinned':
        environ.setdefault('FMCP_ADDRESS_BOOK', 'off')
        if 'FMCP_PLUGIN_PATH' not in environ:
            app = _BUILD.pinned_app()          # imports fm_live_mcp with the address book off
            if app is not None:
                from fm_live_mcp import build_paths
                environ['FMCP_PLUGIN_PATH'] = str(app / build_paths.PLUGIN_IN_APP)
    elif mode == 'installed':
        environ['FMCP_ADDRESS_BOOK'] = 'on'
        environ['FMCP_PLUGIN_PATH'] = _BUILD.installed_plugin


def _test_modules_needing_pinned() -> frozenset[str]:
    """Test files (by stem) that import tests/_pinned_build.py at module level, directly or
    through other test modules."""
    local = {p.stem: p for p in TESTS.glob('*.py')}
    # Module-level imports only: a test that imports it inside its body checks the file itself.
    imports_re = re.compile(r'^(?:from[ \t]+(\w+)[ \t]+import|import[ \t]+([\w, \t]+))', re.M)
    graph = {}
    for stem, path in local.items():
        try:
            text = path.read_text(errors='replace')
        except OSError:
            continue
        names = set()
        for frm, imp in imports_re.findall(text):
            names.update([frm] if frm else [n.strip() for n in imp.split(',')])
        graph[stem] = {n for n in names if n in local}
    needing, changed = {PINNED_HELPER}, True
    while changed:
        changed = False
        for stem, deps in graph.items():
            if stem not in needing and deps & needing:
                needing.add(stem)
                changed = True
    return frozenset(needing - {PINNED_HELPER})


_NEEDS_PINNED: frozenset | None = None


def _needs_pinned(path: str) -> bool:
    global _NEEDS_PINNED
    if _NEEDS_PINNED is None:
        _NEEDS_PINNED = _test_modules_needing_pinned()
    return path.startswith('tests/') and Path(path).stem in _NEEDS_PINNED


def pytest_runtest_setup(item):
    """Skip what the session's build cannot run, saying what it needs."""
    marked = {m.name for m in item.iter_markers()}
    mode = _BUILD.mode
    if 'pinned_build' in marked and mode in ('pinned', 'map') and _BUILD.pinned_app() is None:
        pytest.skip(f'pinned_build: this module compares with the pinned build and {_pinned_missing()}')
    if mode == 'pinned':
        if 'mapped_build' in marked:
            pytest.skip('mapped_build: runs in a session that addresses the installed build: pytest -m mapped_build')
        if 'live' in marked and not _BUILD.installed_is_pinned():
            pytest.skip('live: the installed game is not the pinned build, so live tests run in a session that '
                        'addresses it through its address map: pytest -m live')
    elif mode == 'installed':
        if not marked & {'live', 'mapped_build'}:
            pytest.skip('this session addresses the installed build; only live and mapped_build tests run in it '
                        '(the others address the pinned build: run them without -m live / -m mapped_build)')
        if 'live' in marked and 'pinned_build' in marked and not _BUILD.installed_is_pinned():
            pytest.skip('build-specific: compares the running game with the pinned build\'s code or data '
                        '(tests/_pinned_build.py); runs only while the game is build 27.0.0.2493426')


_TESTS_DIRECTORY = os.path.normcase(str(Path(__file__).resolve().parent)) + os.sep
_STANDARD_LIBRARY = os.path.normcase(os.path.dirname(os.__file__)) + os.sep


def _refused_in_the_test_itself(error: BaseException) -> bool:
    """True when the refused file operation was called by test code, not by the package.

    The call may sit in a callback the package runs (a patched function that swaps the file at
    a chosen moment), so what counts is the caller nearest the refusal, outside the standard
    library (``pathlib``, ``shutil``): it must be a file under ``tests``.
    """
    files = []
    trace = error.__traceback__
    while trace is not None:
        files.append(os.path.normcase(trace.tb_frame.f_code.co_filename))
        trace = trace.tb_next
    for name in reversed(files):
        if not name.startswith(_STANDARD_LIBRARY):
            return name.startswith(_TESTS_DIRECTORY)
    return False


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """On Windows, skip a test whose own replace or delete of an open file was refused.

    Many tests replace or delete a save file while a reader holds it open, to prove the reader
    notices. Windows refuses that operation for a file opened through ``os.open`` (sharing
    violation, error 5 or 32), so the change the test sets up cannot happen there. The skip
    applies only when test code made the refused call; the same error from a call the package
    makes is a failure.
    """
    try:
        return (yield)
    except PermissionError as error:
        if os.name == 'nt' and getattr(error, 'winerror', None) in (5, 32) and _refused_in_the_test_itself(error):
            pytest.skip('Windows refuses to replace or delete a file that is open, so the change this test '
                        'makes cannot happen there')
        raise


def _pinned_missing() -> str:
    from fm_live_mcp import build_paths
    return build_paths.PINNED_MISSING


def _load_profile() -> dict:
    try:
        data = json.loads(PROFILE.read_text())
    except FileNotFoundError:
        return {}
    return data


_PROFILE = _load_profile()
_LIVE_FILES = frozenset(_PROFILE.get('live_files', ()))
_LIVE_TESTS = frozenset(_PROFILE.get('live_tests', ()))
_SLOW_TESTS = frozenset(_PROFILE.get('slow_tests', {}))
_EVIDENCE_FILES = frozenset(_PROFILE.get('evidence_files', ()))
_EVIDENCE_TESTS = frozenset(_PROFILE.get('evidence_tests', ()))


def _listed(nodeid: str, entries) -> bool:
    """An id matches its own entry or its test function's (the id without parameters)."""
    return nodeid in entries or nodeid.split('[', 1)[0] in entries


def _is_live(nodeid: str) -> bool:
    path = nodeid.split('::', 1)[0]
    return path.endswith('_live.py') or path in _LIVE_FILES or _listed(nodeid, _LIVE_TESTS)


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_make_scheduler(config, log):
    """Under -n, every live test goes to one worker, as one unit, first (it is the largest unit);
    every other test is its own unit, spread over the remaining workers.

    xdist's own loadgroup reads an `@group` suffix that pytest 9 no longer shows in item.nodeid,
    so it would spread the live tests; this decides from the node id with the rules above."""
    if config.getvalue('dist') not in ('load', 'loadgroup'):
        return None
    from xdist.scheduler import LoadScopeScheduling

    class LiveGroupScheduling(LoadScopeScheduling):
        def _split_scope(self, nodeid: str) -> str:
            return LIVE_GROUP if _is_live(nodeid.split('@', 1)[0]) else nodeid

    return LiveGroupScheduling(config, log)


def pytest_itemcollected(item):
    """Markers go on as each test is collected, before any pytest_collection_modifyitems: xdist's
    loadgroup reads xdist_group there, and -m deselection reads live/slow."""
    nodeid = item.nodeid
    path = nodeid.split('::', 1)[0]
    live = _is_live(nodeid) or item.get_closest_marker('live') is not None
    if live:
        if item.get_closest_marker('live') is None:
            item.add_marker(pytest.mark.live)
        item.add_marker(pytest.mark.xdist_group(LIVE_GROUP))
    if _listed(nodeid, _SLOW_TESTS) and item.get_closest_marker('slow') is None:
        item.add_marker(pytest.mark.slow)
    if (path in _EVIDENCE_FILES or _listed(nodeid, _EVIDENCE_TESTS)) and item.get_closest_marker('evidence') is None:
        item.add_marker(pytest.mark.evidence)
    if path.endswith('_mapped.py') and item.get_closest_marker('mapped_build') is None:
        item.add_marker(pytest.mark.mapped_build)
    if _needs_pinned(path) and item.get_closest_marker('pinned_build') is None:
        item.add_marker(pytest.mark.pinned_build)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(session, config, items):
    seed = config.getoption('--suite-shuffle')
    if seed is not None:
        order: dict[str, list] = {}
        for item in items:
            order.setdefault(item.nodeid.split('::', 1)[0], []).append(item)
        files = sorted(order)
        random.Random(seed).shuffle(files)
        items[:] = [item for name in files for item in order[name]]


# --------------------------------------------------------------------------- live serialisation

@contextlib.contextmanager
def _live_lock():
    with open(LIVE_LOCK, 'a+') as handle:
        lock_exclusive(handle)
        try:
            yield
        finally:
            unlock(handle)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    _GUARD.begin(item)
    try:
        if item.get_closest_marker('live') is not None:
            with _live_lock():
                return (yield)
        return (yield)
    finally:
        _GUARD.end(item)


# --------------------------------------------------------------------------- state snapshots

def _module_is_foreign(name: str, module) -> bool:
    """An entry no normal import of this checkout would have produced."""
    if name != 'fm_live_mcp' and not name.startswith('fm_live_mcp.'):
        # Stubs inserted by hand (no spec, no file) under any name.
        return getattr(module, '__spec__', None) is None and getattr(module, '__file__', None) is None \
            and not isinstance(module, type(sys))
    origin = getattr(module, '__file__', None)
    locations = [origin] if origin else list(getattr(module, '__path__', None) or ())
    if not locations:
        return True
    for location in locations:
        try:
            resolved = Path(location).resolve()
        except (OSError, TypeError, ValueError):
            return True
        if resolved != PACKAGE and PACKAGE not in resolved.parents:
            return True
    return False


def _restore_modules(before: dict) -> list[str]:
    changed = []
    modules = sys.modules
    for name, module in list(modules.items()):
        old = before.get(name, _MISSING)
        if old is module:
            continue
        if old is not _MISSING:
            modules[name] = old
            _rebind_parent(name, module, old)
            changed.append(f'replaced {name}')
        elif _module_is_foreign(name, module):
            del modules[name]
            _rebind_parent(name, module, _MISSING)
            changed.append(f'dropped {name}')
    for name, old in before.items():
        if name not in modules:
            modules[name] = old
            changed.append(f'restored {name}')
    return changed


def _rebind_parent(name, current, old):
    parent_name, _, child = name.rpartition('.')
    parent = sys.modules.get(parent_name) if parent_name else None
    if parent is None or getattr(parent, child, _MISSING) is not current:
        return
    if old is _MISSING:
        with contextlib.suppress(AttributeError):
            delattr(parent, child)
    else:
        setattr(parent, child, old)


def _environ() -> dict:
    """os.environ without the variable pytest itself rewrites at every phase."""
    environ = dict(os.environ)
    environ.pop('PYTEST_CURRENT_TEST', None)
    return environ


class _Snapshot:
    """Process-global state a test may change. `keep_path` leaves sys.path alone: a test module
    may add a directory at import for its own tests to import from later."""
    __slots__ = ('environ', 'path', 'cwd', 'modules', 'bytecode')

    def __init__(self, keep_path=False):
        self.environ = _environ()
        self.path = None if keep_path else list(sys.path)
        self.cwd = os.getcwd()
        self.modules = dict(sys.modules)
        self.bytecode = (sys.dont_write_bytecode, sys.pycache_prefix)

    def restore(self) -> list[str]:
        changed = []
        environ = _environ()
        if environ != self.environ:
            changed += [f'environ {k}' for k in sorted(set(environ) | set(self.environ))
                        if environ.get(k) != self.environ.get(k)]
            for key in set(environ) - set(self.environ):
                del os.environ[key]
            os.environ.update(self.environ)
        if self.path is not None and sys.path != self.path:
            changed.append('sys.path')
            sys.path[:] = self.path
        if os.getcwd() != self.cwd:
            changed.append('cwd')
            os.chdir(self.cwd)
        if (sys.dont_write_bytecode, sys.pycache_prefix) != self.bytecode:
            # Several evidence scripts set sys.dont_write_bytecode = True when a test loads them.
            changed.append('sys.dont_write_bytecode')
            sys.dont_write_bytecode, sys.pycache_prefix = self.bytecode
        changed += _restore_modules(self.modules)
        return changed


def _close_cached_game_sessions() -> list[str]:
    """The fmdb and UI tools keep one attached engine or UI session (each with a memory reader
    process) in a module global for the server's lifetime. In tests that global outlived its test
    module: later live modules reused another module's attachment, and its reader outlived the
    module. Close and forget them, as a test module run alone would find them."""
    closed = []
    for name, key in (('fm_live_mcp.fmdb.tools', 'engine'), ('fm_live_mcp.fmdb.ui_tools', 'session')):
        module = sys.modules.get(name)
        state = getattr(module, '_STATE', None)
        if isinstance(state, dict) and state.get(key) is not None:
            with contextlib.suppress(Exception):
                state[key].close()
            state[key] = None
            closed.append(f'{name}._STATE[{key!r}]')
    tools = sys.modules.get('fm_live_mcp.fmdb.tools')
    manager = getattr(tools, '_MANAGER', None)
    thread = manager.get('thread') if isinstance(manager, dict) else None
    if thread is not None and thread.is_alive():
        thread.join(timeout=120)  # a manager-view build started by the module
        closed.append('fm_live_mcp.fmdb.tools manager-view thread')
    return closed


@pytest.fixture(scope='module', autouse=True)
def _isolate_module_state():
    snapshot = _Snapshot()
    _GUARD.module_spawned = False
    yield
    _GUARD.note_leaks('module', _close_cached_game_sessions())
    _GUARD.note_leaks('module', snapshot.restore())
    # Torn down after the module's own fixtures: anything the module started must be gone by now.
    if _GUARD.module_spawned:
        leftovers = _stop_leftover_children()
        if leftovers:
            pytest.fail('suite isolation guard: this test module left child processes running '
                        '(stopped now): ' + '; '.join(leftovers), pytrace=False)


@pytest.fixture(autouse=True)
def _isolate_test_state():
    snapshot = _Snapshot()
    yield
    _GUARD.note_leaks('test', snapshot.restore())


# --------------------------------------------------------------------------- child processes

def _live_children() -> list[tuple[int, str]]:
    """Processes whose parent is this one, except zombies (exited, not yet reaped)."""
    try:
        with subprocess.Popen(['/bin/ps', '-axo', 'pid=,ppid=,stat=,command='], stdout=subprocess.PIPE,
                              text=True) as ps:
            out = ps.communicate(timeout=20)[0]
    except (OSError, subprocess.SubprocessError):
        return []
    me, children = os.getpid(), []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if (len(parts) == 4 and parts[1] == str(me) and not parts[2].startswith('Z')
                and parts[0] != str(ps.pid)):
            children.append((int(parts[0]), parts[3][:160]))
    return children


def _stop_leftover_children() -> list[str]:
    """Stop (TERM, then KILL, with the process group a detached child leads) and describe them."""
    children = _live_children()
    for pid, _ in children:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            with contextlib.suppress(OSError):
                if os.getpgid(pid) == pid:
                    os.killpg(pid, sig)
                else:
                    os.kill(pid, sig)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                with contextlib.suppress(ChildProcessError, OSError):
                    if os.waitpid(pid, os.WNOHANG)[0]:
                        break
                with contextlib.suppress(OSError):
                    os.kill(pid, 0)
                    time.sleep(0.05)
                    continue
                break
    return [f'{pid} {command}' for pid, command in children]


def pytest_sessionfinish(session, exitstatus):
    """Last check, in every process that ran tests (not the xdist controller, whose children
    are the workers)."""
    if hasattr(session.config, 'workerinput') or not session.config.pluginmanager.hasplugin('dsession'):
        leftovers = _stop_leftover_children()
        if leftovers:
            sys.stderr.write('\nsuite isolation guard: child processes still running at the end of the '
                             'session (stopped now): ' + '; '.join(leftovers) + '\n')
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


# --------------------------------------------------------------------------- audit guard

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
# event -> (index of the path written, index of its dir_fd argument or None)
_MUTATING_EVENTS = {'os.remove': (0, 1), 'os.rmdir': (0, 1), 'os.mkdir': (0, 2), 'shutil.rmtree': (0, 1),
                    'os.rename': (1, 3), 'os.truncate': (0, None), 'os.symlink': (1, 2), 'os.link': (1, 3)}
_WATCHED = frozenset({'open', 'subprocess.Popen', *_MUTATING_EVENTS})
_ROOT_PREFIX = str(ROOT) + os.sep
_EVIDENCE_PREFIX = str(ROOT / 'evidence') + os.sep
_EXEMPT_PARTS = (os.sep + '__pycache__' + os.sep, os.sep + '.pytest_cache' + os.sep)


def _game_pids() -> frozenset[str]:
    try:
        out = subprocess.run(['/bin/ps', '-axo', 'pid=,comm='], capture_output=True, text=True,
                             timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    return frozenset(line.split(maxsplit=1)[0] for line in out.splitlines()
                     if re.search(r'/(Football Manager (26|27)|fm)$', line.strip()))


class _Guard:
    """Per-test record of game access, repository writes and (when probing) evidence reads."""

    def __init__(self):
        self.item = None
        self.module_spawned = False
        self.pids = frozenset()
        self.probe = None
        self.tracked = None
        self.reset()
        sys.addaudithook(self._hook)

    def reset(self):
        self.live_spawns = []
        self.repo_writes = set()
        self.spawns = []
        self.evidence_reads = set()
        self.leaks = []
        self.started = time.perf_counter()

    def configure(self, probe):
        self.pids = _game_pids()
        self.probe = probe
        if probe:
            listed = subprocess.run(['git', 'ls-files', '-z', 'evidence'], cwd=ROOT, capture_output=True,
                                    check=False).stdout.decode(errors='replace')
            self.tracked = frozenset(str(ROOT / p) for p in listed.split('\0') if p)

    def begin(self, item):
        self.reset()
        self.item = item

    def note_leaks(self, scope, changed):
        if changed:
            self.leaks.append({'scope': scope, 'changed': changed[:20]})

    # The hook runs for every audited event in the process, so it returns at once for the rest.
    def _hook(self, event, args):
        if event not in _WATCHED or self.item is None:
            return
        try:
            if event == 'open':
                path, mode, flags = args
                if not isinstance(path, (str, bytes, os.PathLike)):
                    return
                path = os.path.abspath(os.fsdecode(path))
                if not path.startswith(_ROOT_PREFIX):
                    return
                writing = (mode is not None and any(c in mode for c in 'wax+')) or \
                    (mode is None and flags & _WRITE_FLAGS)
                if writing:
                    if not any(part in path for part in _EXEMPT_PARTS):
                        self.repo_writes.add(path)
                elif self.tracked is not None and path.startswith(_EVIDENCE_PREFIX) and path not in self.tracked:
                    self.evidence_reads.add(path)
            elif event == 'subprocess.Popen':
                self.module_spawned = True
                executable, argv = args[0], args[1]
                argv = [os.fsdecode(a) for a in argv] if isinstance(argv, (list, tuple)) else [os.fsdecode(argv)]
                if self.probe:
                    self.spawns.append(os.path.basename(argv[0]) if argv else str(executable))
                if self.pids:
                    for flag, value in zip(argv, argv[1:]):
                        if flag in ('--pid', '-p') and value in self.pids:
                            entry = ' '.join(argv[:4])
                            # Report a reader before the `ps -p` identity checks that surround it.
                            if os.path.basename(argv[0]) == 'ps':
                                self.live_spawns.append(entry)
                            else:
                                self.live_spawns.insert(0, entry)
                            break
            else:
                position, dir_fd = _MUTATING_EVENTS[event]
                path = args[position]
                if dir_fd is not None and len(args) > dir_fd and args[dir_fd] not in (None, -100):
                    return  # relative to an open directory (shutil.rmtree's walk); the top call is checked
                if isinstance(path, (str, bytes, os.PathLike)):
                    path = os.path.abspath(os.fsdecode(path))
                    if path.startswith(_ROOT_PREFIX) and not any(p in path for p in _EXEMPT_PARTS):
                        self.repo_writes.add(path)
        except Exception:  # noqa: BLE001 - an audit hook must never break the code it watches
            return

    def end(self, item, phase='test'):
        self.item = None
        if self.probe:
            record = {'nodeid': item.nodeid, 'phase': phase, 'worker': os.environ.get('PYTEST_XDIST_WORKER', 'main'),
                      'seconds': round(time.perf_counter() - self.started, 4),
                      'spawns': self.spawns, 'live': self.live_spawns,
                      'evidence_reads': sorted(self.evidence_reads), 'repo_writes': sorted(self.repo_writes),
                      'leaks': self.leaks}
            with open(f"{self.probe}.{record['worker']}", 'a') as stream:
                stream.write(json.dumps(record) + '\n')


_GUARD = _Guard()


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector):
    """Importing a test module may not change state for the modules imported after it, except
    sys.path. When probing, evidence reads made during the import are attributed to the module."""
    if not isinstance(collector, pytest.Module):
        return (yield)
    snapshot = _Snapshot(keep_path=True)
    if _GUARD.probe:
        _GUARD.begin(collector)
    try:
        return (yield)
    finally:
        _GUARD.note_leaks('import', snapshot.restore())
        if _GUARD.probe:
            _GUARD.end(collector, phase='collect')


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if call.when != 'teardown' or report.failed or _GUARD.probe:
        return report
    problems = []
    if _GUARD.repo_writes:
        problems.append('wrote inside the repository (use tmp_path): ' + ', '.join(
            os.path.relpath(p, ROOT) for p in sorted(_GUARD.repo_writes)[:10]))
    if _GUARD.live_spawns and item.get_closest_marker('live') is None:
        problems.append('read the running game but is not marked live (add it to tests/suite_profile.json '
                        'live_tests, or name the file *_live.py): ' + _GUARD.live_spawns[0])
    if problems:
        report.outcome = 'failed'
        report.longrepr = 'suite isolation guard: ' + '; '.join(problems)
    return report
