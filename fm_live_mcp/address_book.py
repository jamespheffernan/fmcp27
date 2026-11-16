"""The reader's address book: every plugin address it uses, for the game build that is installed.

The source keeps the addresses of build 27.0.0.2493426 as integer literals (thousands, across
the hand-built tools, the knowledge engine and the fmdb core). On that build nothing here does
anything. On another build this module installs an import hook, before any other module of
the package loads, that rewrites exactly the literals the address census marks as addresses
(fmdb/address_census.py; by file and value) to that build's addresses from its address map
(`$FMCP_CACHE_DIR/fmdb/anchors/<plugin sha256>.addresses.json`, written by
scripts/fm_update_build.py). It also rewrites the expected code bytes and hashes of the
native guards next to those addresses when the new build's code is the same under masking,
and turns decoders the per-build self-check disabled into refusals.

The build identity the scattered gates compare with (`players.VERSION`, `players.SHA256` and
the modules that copy them) is rewritten the same way, so every gate accepts exactly the
build whose map is loaded.

An address that did not resolve becomes an `Unresolved` object: any arithmetic, comparison,
conversion or formatting inside a function raises `UnresolvedAddress`, naming the build and
the pinned address, so exactly the code that uses it refuses; it is never a wrong number and
never zero. (At module level arithmetic yields another `Unresolved`, so a module still
imports and only the functions that use the value refuse.) `report()` lists which tools that
disables, for fm_status and fm_coverage.

Which build: `FMCP_ADDRESS_MAP=<file>` forces a map (used to prove the procedure on the pinned
build); otherwise the installed plugin (`FMCP_PLUGIN_PATH`, default: the Steam install) is
hashed once per file identity (cached in `$FMCP_CACHE_DIR/fmdb/anchors/plugin-sha256.json`).
A build without a map stays on the pinned numbers and the Bridge refuses it, naming the
command to run. Nothing here reads the game's memory.
"""
from __future__ import annotations

import ast
import gzip
import hashlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import sys

PACKAGE_DIR = Path(__file__).resolve().parent
PACKAGE = __name__.rsplit('.', 1)[0]
PINNED_VERSION = '27.0.0.2493426'
PINNED_SHA256 = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
MAP_FORMAT = 'fmcp-address-map/1'
CENSUS_PATH = PACKAGE_DIR / 'fmdb' / 'data' / 'address_census.json.gz'
DEFAULT_PLUGIN = Path.home() / ('Library/Application Support/Steam/steamapps/common/Football Manager 27/'
                                'fm.app/Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin')
DEFAULT_CACHE = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmcp-source-cache')
UPDATE_COMMAND = 'scripts/fm_update_build.py'

# The active build. state: pinned | mapped | unsupported (another build, no map) | error
ACTIVE = {'state': 'pinned', 'sha256': PINNED_SHA256, 'version': PINNED_VERSION, 'map': None,
          'installed_sha256': None, 'error': None}
MAP: dict | None = None            # the loaded address map document
_VALUES: dict = {}                 # {pinned int: new int | None}
_REASONS: dict = {}                # {pinned int: why it did not resolve}
_PER_FILE: dict = {}               # {relative file: {pinned int: new int | None}}
_GUARDS: dict = {}                 # {relative file: {old constant: new constant}}
_DISABLED: dict = {}               # {relative file: {qualname: reason}}
_OFFSETS: dict = {}                # {structure: {pinned field offset: offset on this build | None}}
_CENSUS: dict | None = None
_REWRITTEN: dict = {}              # {module name: {'addresses': n, 'unresolved': n, 'guards': n}}


class UnresolvedAddress(RuntimeError):
    """A plugin address the reader needs has no counterpart on the running build."""


def cache_dir() -> Path:
    env = os.environ.get('FMCP_CACHE_DIR')
    return (Path(env) if env else DEFAULT_CACHE) / 'fmdb' / 'anchors'


def map_path(sha256: str) -> Path:
    return cache_dir() / f'{sha256}.addresses.json'


def build_label() -> str:
    return f"{ACTIVE.get('version') or 'unknown version'} (plugin {str(ACTIVE.get('sha256'))[:12]})"


# --------------------------------------------------------------------------- the refusing value
def _module_level() -> bool:
    """True when the operation runs in a module or class body (not in a function)."""
    return not sys._getframe(2).f_code.co_flags & 0x1          # CO_OPTIMIZED: function bodies only


class Unresolved:
    """Stands for a pinned plugin address that does not resolve on the running build."""

    __slots__ = ('pinned', 'reason', 'where')
    _interned: dict = {}

    def __new__(cls, pinned: int, reason: str = '', where: str = ''):
        key = (pinned, where)
        obj = cls._interned.get(key)
        if obj is None:
            obj = object.__new__(cls)
            obj.pinned, obj.reason, obj.where = pinned, reason, where
            cls._interned[key] = obj
        return obj

    def message(self) -> str:
        why = f': {self.reason}' if self.reason else ''
        return (f'This needs plugin address {self.pinned:#x} of build {PINNED_VERSION}, which has no counterpart '
                f'on the running build {build_label()}{why}. Tools that use it are unavailable on this build; '
                f'fm_status lists them.')

    def _refuse(self, *_args):
        if _module_level():
            return Unresolved(self.pinned, self.reason, 'derived')
        raise UnresolvedAddress(self.message())

    def _refuse_hard(self, *_args):
        raise UnresolvedAddress(self.message())

    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = _refuse
    __floordiv__ = __rfloordiv__ = __truediv__ = __rtruediv__ = __mod__ = __rmod__ = _refuse
    __and__ = __rand__ = __or__ = __ror__ = __xor__ = __rxor__ = _refuse
    __lshift__ = __rlshift__ = __rshift__ = __rrshift__ = __pow__ = __rpow__ = _refuse
    __neg__ = __pos__ = __abs__ = __invert__ = _refuse
    __lt__ = __le__ = __gt__ = __ge__ = _refuse_hard
    __index__ = __int__ = __float__ = __bool__ = __format__ = __str__ = __bytes__ = _refuse_hard
    __round__ = __trunc__ = __floor__ = __ceil__ = __len__ = __iter__ = _refuse_hard

    def __eq__(self, other):
        if other is self:
            return True
        if isinstance(other, Unresolved):
            return False
        raise UnresolvedAddress(self.message())

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(('fmcp-unresolved-address', self.pinned, self.where))

    def __repr__(self):
        return f'<unresolved plugin address {self.pinned:#x} on {build_label()}>'

    def __reduce__(self):
        raise UnresolvedAddress(self.message())


def _address(pinned: int):
    """What a rewritten unresolved literal evaluates to (injected as `__fmcp_address__`)."""
    return Unresolved(pinned, _REASONS.get(pinned, 'not resolved'))


def _refuse_call(qualname: str, reason: str):
    raise UnresolvedAddress(f'{qualname} is disabled on build {build_label()}: {reason}')


# --------------------------------------------------------------------------- choosing the build
def plugin_sha256(path: Path) -> str:
    """sha256 of the plugin, cached by (path, size, mtime) so a start does not rehash 190 MB."""
    stat = path.stat()
    stamp = [str(path), stat.st_size, stat.st_mtime_ns]
    cache = cache_dir() / 'plugin-sha256.json'
    try:
        doc = json.loads(cache.read_text())
        if doc.get('stamp') == stamp:
            return doc['sha256']
    except (OSError, ValueError, KeyError):
        pass
    with path.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({'stamp': stamp, 'sha256': sha}))
    except OSError:
        pass
    return sha


def load_map(path: Path) -> dict:
    doc = json.loads(Path(path).read_text())
    if doc.get('format') != MAP_FORMAT:
        raise ValueError(f'{path}: not an address map ({doc.get("format")!r})')
    return doc


def verified(doc: dict) -> tuple[bool, str]:
    """(True, '') when an address map may be used: it was derived statically for this plugin,
    every required fmdb anchor resolved, and no check it ran failed."""
    v = doc.get('verified') or {}
    if not v.get('static'):
        return False, 'the static derivation did not complete'
    failed = [k for k, ok in (v.get('checks') or {}).items() if ok is False]
    if failed:
        return False, 'checks failed: ' + ', '.join(sorted(failed))
    return True, ''


def install_from_environment() -> dict:
    """Pick the build at package import and install the hook when it is not the pinned one."""
    if os.environ.get('FMCP_ADDRESS_BOOK') == 'off':
        return ACTIVE
    try:
        forced = os.environ.get('FMCP_ADDRESS_MAP')
        if forced:
            doc = load_map(Path(forced))
            install(doc, source=f'forced:{forced}')
            return ACTIVE
        plugin = Path(os.environ.get('FMCP_PLUGIN_PATH') or DEFAULT_PLUGIN)
        if not plugin.is_file():
            return ACTIVE
        sha = plugin_sha256(plugin)
        ACTIVE['installed_sha256'] = sha
        if sha == PINNED_SHA256:
            return ACTIVE
        path = map_path(sha)
        if not path.exists():
            ACTIVE.update(state='unsupported', sha256=sha, version=_app_version(plugin), map=None)
            return ACTIVE
        doc = load_map(path)
        ok, why = verified(doc)
        if not ok:
            ACTIVE.update(state='unsupported', sha256=sha, version=doc.get('version'), map=str(path),
                          error=f'address map not usable: {why}')
            return ACTIVE
        install(doc, source=str(path))
    except Exception as exc:  # noqa: BLE001 - never break the package import; the Bridge refuses instead
        ACTIVE.update(state='error', error=f'{type(exc).__name__}: {exc}')
    return ACTIVE


def _app_version(plugin: Path) -> str | None:
    import plistlib
    for parent in plugin.parents:
        if parent.name == 'Contents' and parent.parent.suffix == '.app':
            try:
                return plistlib.loads((parent / 'Info.plist').read_bytes()).get('CFBundleShortVersionString')
            except (OSError, ValueError):
                return None
    return None


def census() -> dict:
    global _CENSUS
    if _CENSUS is None:
        _CENSUS = json.loads(gzip.decompress(CENSUS_PATH.read_bytes()))
    return _CENSUS


def pinned_constant(module, name: str):
    """A module-level constant as the source writes it: its value on the pinned build.

    On a mapped build the import hook has rewritten the module's addresses and guard bytes, each
    re-derived or reviewed by the address map. A digest that names a decoder contract and not a
    build (a recorded run's policy) is taken over the source values, so it is the same on every
    build that accepts the contract."""
    if ACTIVE['state'] != 'mapped':
        return getattr(module, name)
    tree = ast.parse(Path(module.__file__).read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                isinstance(node.targets[0], ast.Name) and node.targets[0].id == name:
            return eval(compile(ast.Expression(node.value), module.__file__, 'eval'),    # noqa: S307
                        {'__builtins__': {}, 'bytes': bytes})
    raise AttributeError(f'{module.__name__} has no module-level literal {name}')


def install(doc: dict, *, source: str) -> None:
    """Make `doc` the active address map and hook the package's imports to it."""
    global MAP
    MAP = doc
    _VALUES.clear()
    _REASONS.clear()
    for key, entry in doc['values'].items():
        _VALUES[int(key, 16)] = entry['value']
        if entry['value'] is None:
            _REASONS[int(key, 16)] = entry.get('detail') or entry.get('method', '')
    _PER_FILE.clear()
    for rel, values in (doc.get('per_file') or {}).items():
        _PER_FILE[rel] = {int(k, 16): e['value'] for k, e in values.items()}
    _GUARDS.clear()
    for rel, consts in ((doc.get('guards') or {}).get('files') or {}).items():
        _GUARDS[rel] = dict(consts)
    _DISABLED.clear()
    for rel, fns in (doc.get('disabled') or {}).items():
        _DISABLED[rel] = dict(fns)
    _OFFSETS.clear()
    for structure, table in (doc.get('offsets') or {}).items():
        _OFFSETS[structure] = {int(k, 16): v for k, v in table.items()}
    ACTIVE.update(state='mapped', sha256=doc['plugin_sha256'], version=doc.get('version'), map=source, error=None)
    _set_code_cache(doc)
    if not any(isinstance(f, _Finder) for f in sys.meta_path):
        sys.meta_path.insert(0, _Finder())


def uninstall() -> None:
    """Remove the hook (tests); modules already imported keep their rewritten constants."""
    global MAP
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, _Finder)]
    MAP = None
    _OFFSETS.clear()
    ACTIVE.update(state='pinned', sha256=PINNED_SHA256, version=PINNED_VERSION, map=None, error=None)


def refusal(version: str | None, sha256: str | None = None) -> str:
    """The Bridge's refusal for a running build that the loaded address book does not address."""
    shown = f'{version or "unknown version"}' + (f' (plugin {sha256[:12]})' if sha256 else '')
    sha = sha256 or ACTIVE.get('installed_sha256')
    if ACTIVE['state'] == 'mapped' or (sha and sha != ACTIVE['sha256'] and map_path(sha).exists()):
        if sha and map_path(sha).exists():
            return (f'The game runs build {shown}, but this server loaded the addresses of {build_label()}. '
                    f'Restart the MCP server so it loads the address map of the running build.')
    note = f' ({ACTIVE["error"]})' if ACTIVE.get('error') else ''
    return (f'Unsupported player layout. The game runs build {shown}, which this reader has no verified address map for{note}; it is '
            f'verified for {PINNED_VERSION}. Run once, with or without the game running: '
            f'PYTHONPATH=. python {UPDATE_COMMAND} --installed   then restart the MCP server.')


# --------------------------------------------------------------------------- the import hook
def _rel(path: str) -> str | None:
    try:
        return str(Path(path).resolve().relative_to(PACKAGE_DIR))
    except ValueError:
        return None


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(PACKAGE + '.') or fullname == __name__:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or not isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            return spec
        rel = _rel(spec.origin)
        if rel is None or not _needs_rewrite(rel):
            return spec
        spec.loader = _Loader(spec.loader.name, spec.loader.path, rel)
        return spec


def _needs_rewrite(rel: str) -> bool:
    return MAP is not None      # every module: address literals, build identity strings, guards


class _Loader(importlib.machinery.SourceFileLoader):
    def __init__(self, fullname, path, rel):
        super().__init__(fullname, path)
        self.rel = rel

    def get_code(self, fullname):
        import marshal
        import struct
        stat = os.stat(self.path)
        stamp = struct.pack('<qq', stat.st_mtime_ns, stat.st_size)
        cached = _code_cache_path(self.rel)
        if cached is not None:
            try:
                blob = cached.read_bytes()
                if blob[:16] == stamp:
                    counts, code = marshal.loads(blob[16:])
                    _REWRITTEN[fullname] = counts
                    return code
            except (OSError, ValueError, EOFError, TypeError):
                pass
        source = self.get_data(self.path)
        tree = ast.parse(source, self.path)
        counts = rewrite(tree, self.rel)
        _REWRITTEN[fullname] = counts
        code = compile(tree, self.path, 'exec', dont_inherit=True)
        if cached is not None:
            try:
                cached.parent.mkdir(parents=True, exist_ok=True)
                tmp = cached.with_suffix(f'.{os.getpid()}.tmp')
                tmp.write_bytes(stamp + marshal.dumps((counts, code)))
                os.replace(tmp, cached)
            except OSError:
                pass
        return code

    def set_data(self, *_args, **_kwargs):
        return None                         # never cache rewritten bytecode

    def exec_module(self, module):
        module.__dict__['__fmcp_address__'] = _address
        module.__dict__['__fmcp_refuse__'] = _refuse_call
        super().exec_module(module)


_CODE_CACHE: Path | None = None


def _code_cache_path(rel: str) -> Path | None:
    """Where the rewritten bytecode of `rel` is kept for the active map (outside the checkout,
    keyed by the map, the census and this module, and checked against the source's stat)."""
    return None if _CODE_CACHE is None else _CODE_CACHE / (rel[:-3] + '.pyc')


def _set_code_cache(doc: dict) -> None:
    global _CODE_CACHE
    try:
        h = hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode())
        h.update(CENSUS_PATH.read_bytes())
        h.update(Path(__file__).read_bytes())
        h.update(sys.version.encode())
        _CODE_CACHE = cache_dir() / 'code' / h.hexdigest()[:24]
    except OSError:
        _CODE_CACHE = None


def rewrite(tree: ast.AST, rel: str) -> dict:
    """Rewrite the address literals, guard constants and disabled functions of one module."""
    counts = {'addresses': 0, 'unresolved': 0, 'guards': 0, 'disabled': 0, 'unknown': 0, 'identity': 0}
    _Rewriter(rel, counts).visit(tree)
    disabled = _DISABLED.get(rel)
    if disabled:
        for qualname, fn in _functions(tree):
            if qualname in disabled:
                call = ast.parse(f'__fmcp_refuse__({qualname!r}, {disabled[qualname]!r})').body[0]
                ast.copy_location(call, fn.body[0])
                fn.body.insert(0, call)
                counts['disabled'] += 1
    ast.fix_missing_locations(tree)
    return counts


class _Rewriter(ast.NodeTransformer):
    def __init__(self, rel, counts):
        self.rows = census()['files'].get(rel, {})
        self.per_file = _PER_FILE.get(rel, {})
        self.guards = _GUARDS.get(rel, {})
        self.image_end = census()['image_end']
        self.counts = counts
        # the build identity the gates compare with (players.VERSION / SHA256 and their copies)
        self.identity = {PINNED_SHA256: ACTIVE['sha256'], PINNED_VERSION: ACTIVE['version'] or PINNED_VERSION}
        # the English language template the compiled concern and promise texts are bound to, when the
        # update found every compiled text unchanged in this build's file (build_update.english_template)
        self.sizes = {}
        english = (MAP or {}).get('english_template') or {}
        if english.get('verified') and rel in (english.get('files') or ()):
            self.identity[english['pinned_sha256']] = english['sha256']
            self.sizes = {english['pinned_bytes']: english['bytes']}
        # the tactic role names pi-fm's tactic writer imports from the reader, re-bound when the
        # update found every tactic English text the writer carries in this build's file
        # (fmdb/adviser_update.py, `adviser.identity.english`)
        tactic = (((MAP or {}).get('adviser') or {}).get('identity') or {}).get('english') or {}
        if tactic.get('verified') and rel in (tactic.get('reader_files') or ()):
            self.identity[tactic['pinned_sha256']] = tactic['sha256']

    def visit_Constant(self, node):
        v = node.value
        if type(v) is int and v in self.sizes:
            self.counts['identity'] += 1
            return ast.copy_location(ast.Constant(self.sizes[v]), node)
        if type(v) is int and 0 <= v < self.image_end and (v >= 0x10000 or f'{v:#x}' in self.rows):
            # below 0x10000 the census lists only the addresses of native guards
            row = self.rows.get(f'{v:#x}')
            if row is None:
                self.counts['unknown'] += 1
                return node
            if row['d'] != 'A':
                return node
            new = self.per_file[v] if v in self.per_file else _VALUES.get(v)
            if new is None:
                self.counts['unresolved'] += 1
                call = ast.Call(ast.Name('__fmcp_address__', ast.Load()), [ast.Constant(v)], [])
                return ast.copy_location(call, node)
            self.counts['addresses'] += 1
            return ast.copy_location(ast.Constant(new), node)
        if isinstance(v, str) and v in self.identity:
            self.counts['identity'] += 1
            return ast.copy_location(ast.Constant(self.identity[v]), node)
        if isinstance(v, (str, bytes)) and self.guards:
            key = v.hex() if isinstance(v, bytes) else v
            if key in self.guards:
                new = self.guards[key]
                self.counts['guards'] += 1
                return ast.copy_location(ast.Constant(bytes.fromhex(new) if isinstance(v, bytes) else new), node)
        return node


def _functions(tree, prefix=''):
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            q = prefix + node.name
            yield q, node
            yield from _functions(node, q + '.<locals>.')
        elif isinstance(node, ast.ClassDef):
            yield from _functions(node, prefix + node.name + '.')
        elif not isinstance(node, (ast.Lambda,)):
            yield from _functions(node, prefix)


# --------------------------------------------------------------------------- structure offsets
def field(structure: str, offset: int) -> int:
    """The offset of a field of a game structure on the active build, for hand-built decoders.

    The pinned build's offset is the default and the argument: a decoder writes
    `field('GAME_MATCH_TEAM', 0x1D0)` where it read `+ 0x1D0`. Only a map that lists that
    structure and that pinned offset (`offsets`: {structure: {hex pinned offset: new offset}},
    filled from proven structure changes) changes the result; a listed offset whose new place is
    unknown (null) raises `UnresolvedAddress`, so the decoder refuses instead of reading the
    wrong bytes. Nothing else consults the table: the import rewrite never touches an integer
    that is not an address, so no unrelated number can change."""
    table = _OFFSETS.get(structure)
    if not table or offset not in table:
        return offset
    new = table[offset]
    if new is None:
        raise UnresolvedAddress(f'Field +{offset:#x} of {structure} (build {PINNED_VERSION}) moved on build '
                                f'{build_label()} to a place the update could not establish; the decoders that read '
                                f'it are unavailable on this build.')
    return new


def disabled_manager(name: str) -> str | None:
    """Why the walker of native manager `name` is disabled on this build (None: it is not)."""
    reason = ((MAP or {}).get('disabled_managers') or {}).get(name)
    return f'manager {name} is disabled on build {build_label()}: {reason}' if reason else None


# --------------------------------------------------------------------------- withheld fields
def apply_withheld(bridge) -> int:
    """Wrap the hand-built decoders the per-build self-check found disagreeing with the generic
    getter (map `withheld`: {Bridge method or 'module:function': {JSON path: reason}}): each
    such field of their result is replaced by {'withheld': reason} instead of its value."""
    import functools
    import importlib
    count = 0
    for method, paths in ((MAP or {}).get('withheld') or {}).items():
        if ':' in method:
            module_name, fn_name = method.split(':', 1)
            owner = importlib.import_module(module_name)
        else:
            owner, fn_name = bridge, method
        original = getattr(owner, fn_name, None)
        if original is None:
            continue
        root = _call_root(method)

        @functools.wraps(original)
        def wrapped(*args, __original=original, __paths=paths, __root=root, **kwargs):
            result = __original(*args, **kwargs)
            for path, reason in __paths.items():
                _withhold(result, '.'.join(p for p in (__root, path) if p), reason)
            return result
        setattr(owner, fn_name, wrapped)
        count += 1
    return count


def _call_root(method: str) -> str:
    try:
        from .fmdb import oracle_map
    except ImportError:
        return ''
    return next((c.root for c in oracle_map.CALLS.values() if c.method == method), '')


def _withhold(doc, path: str, reason: str) -> None:
    from .fmdb.oracle_map import MISSING, get_path
    parent_path, _, last = path.rpartition('.')
    name = last.partition('[')[0]
    parent = get_path(doc, parent_path) if parent_path else doc
    note = {'withheld': f'not trusted on build {build_label()}: {reason}'}
    if isinstance(parent, dict) and name in parent:
        parent[name] = note
    elif isinstance(doc, dict) and parent is not MISSING:
        doc.setdefault('withheld_fields', {})[path] = note['withheld']


# --------------------------------------------------------------------------- what is unavailable
def unresolved_sites() -> dict:
    """{(module, scope): [(pinned address, reason)]} for the active map (empty when pinned)."""
    if MAP is None:
        return {}
    out = {}
    for rel, entry in census()['files'].items():
        module = PACKAGE + '.' + rel[:-3].replace('/', '.').removesuffix('.__init__')
        per_file = _PER_FILE.get(rel, {})
        for key, row in entry.items():
            v = int(key, 16)
            if row['d'] != 'A' or (per_file[v] if v in per_file else _VALUES.get(v)) is not None:
                continue
            for _line, _col, scope in row['sites']:
                out.setdefault((module, scope), []).append((v, _REASONS.get(v, 'not resolved')))
    for rel, fns in _DISABLED.items():
        module = PACKAGE + '.' + rel[:-3].replace('/', '.').removesuffix('.__init__')
        for qualname, reason in fns.items():
            out.setdefault((module, qualname), []).append((None, reason))
    # native guards whose code changed on this build: the guard keeps the pinned bytes and fails
    # at run time, so the tools that check it refuse; list them with the verdict
    for span in ((MAP.get('guards') or {}).get('spans') or ()):
        rel, v = span['file'], span['address']
        row = census()['files'].get(rel, {}).get(f'{v:#x}')
        if row is None:
            continue
        module = PACKAGE + '.' + rel[:-3].replace('/', '.').removesuffix('.__init__')
        reason = (f'native guard at {v:#x}: the code differs on this build '
                  f'({span["verdict"]}; {len(span.get("changes") or ())} instruction(s))')
        for _line, _col, scope in row['sites']:
            out.setdefault((module, scope), []).append((v, reason))
    return out


def tool_functions(mcp) -> dict:
    """{tool name: function} of a FastMCP server."""
    manager = getattr(mcp, '_tool_manager', None)
    tools = getattr(manager, '_tools', {}) if manager is not None else {}
    return {name: getattr(tool, 'fn', None) for name, tool in tools.items()}


class OptionalSection:
    """One optional section of a tool's result whose native code may be unavailable on a build.

    Wraps the function that computes the section. Calling it runs the function when its code
    reaches no unresolved address or changed guard on the loaded build (the same static walk as
    `unavailable_tools`), and otherwise returns `unavailable(reasons)` without running it. The
    walk does not descend into a section: a tool whose only refusing code sits inside sections
    is listed under `partial_tools` with the section names, not under `unavailable_tools`.

    `check=True` marks a section that returns no part of the result: a check of the pinned
    build's code that another check replaces on a build where it cannot run. The tool's whole
    result is returned there, so it is listed under `replaced_checks`, not `partial_tools`."""

    def __init__(self, name: str, fn, unavailable, check: bool = False):
        self.name, self.fn, self.unavailable, self.check = name, fn, unavailable, check
        self._blocked = None
        self._blocked_map = None

    def blocked(self) -> list:
        """[reason] that keep this section from running on the loaded build ([] when pinned)."""
        if MAP is None:
            return []
        if self._blocked is None or self._blocked_map is not MAP:
            self._blocked = _section_reasons(self.fn)
            self._blocked_map = MAP
        return self._blocked

    def __call__(self, *args, **kwargs):
        reasons = self.blocked()
        if reasons:
            return self.unavailable(reasons)
        return self.fn(*args, **kwargs)


def optional_section(name: str, unavailable, check: bool = False):
    """Decorator: `unavailable(reasons)` builds the section's result when it cannot run."""
    return lambda fn: OptionalSection(name, fn, unavailable, check)


def _taint():
    sites = unresolved_sites()
    tainted_functions, tainted_globals = {}, {}
    for (module, scope), reasons in sites.items():
        if scope.startswith('module:'):
            for name in scope[7:].split(','):
                if name:
                    tainted_globals.setdefault((module, name), []).extend(reasons)
        elif scope.startswith('class:'):
            tainted_globals.setdefault((module, scope[6:].split('.')[0]), []).extend(reasons)
        else:
            tainted_functions.setdefault((module, scope), []).extend(reasons)
    return tainted_functions, tainted_globals


def _section_reasons(fn) -> list:
    tainted_functions, tainted_globals = _taint()
    found = _reach(fn, tainted_functions, tainted_globals, {}, sections=None)
    return sorted({_reason_text(where, v, why) for where, v, why in found})


def partial_tools(tools: dict, checks: bool = False) -> dict:
    """{tool name: {section: [reason]}} for tools that answer with some sections unavailable.

    `checks=True` lists instead the tools that return their whole result while a check of the
    pinned build's code is replaced on this build (`OptionalSection.check`)."""
    if not unresolved_sites():
        return {}
    tainted_functions, tainted_globals = _taint()
    out = {}
    for name, fn in tools.items():
        if fn is None:
            continue
        sections = []
        if _reach(fn, tainted_functions, tainted_globals, {}, sections=sections):
            continue
        blocked = {s.name: s.blocked()[:3] for s in sections if s.check is checks and s.blocked()}
        if blocked:
            out[name] = blocked
    return out


def unavailable_tools(tools: dict, limit_reasons: int = 3) -> dict:
    """{tool name: [reason]} for every tool whose code can reach an unresolved address.

    Static reach over live objects: a function reaches the functions, classes and module
    attributes its code names (co_names), through its globals, its closure cells (the Bridge
    instance a register_* function captured) and the class that defines it; nested code
    objects are followed. Conservative by name: a method counts as reached when a reached
    function names it and its class is reachable."""
    if not unresolved_sites():
        return {}
    tainted_functions, tainted_globals = _taint()
    memo = {}
    out = {}
    for name, fn in tools.items():
        if fn is None:
            continue
        found = _reach(fn, tainted_functions, tainted_globals, memo, sections=[])
        if found:
            out[name] = [_reason_text(where, v, why) for where, v, why in found[:limit_reasons]]
    return out


def _reason_text(where, v, why):
    if v is None:
        return f'{where} disabled: {why}'
    return f'{where} uses {v:#x}: {why}'


def _reach(fn, tainted_functions, tainted_globals, memo, budget=4000, sections=None):
    """Tainted sites reachable from fn. With `sections` (a list), an OptionalSection met on the way
    is appended to it and not entered; with None (the walk of one section) it is entered."""
    import types
    seen = set()
    if isinstance(fn, OptionalSection):
        fn = fn.fn
    stack = [(fn, None)]
    found = []
    while stack and budget > 0:
        budget -= 1
        obj, cls_ctx = stack.pop()
        if isinstance(obj, OptionalSection):
            if sections is None:
                obj = obj.fn
            else:
                if obj not in sections:
                    sections.append(obj)
                continue
        while hasattr(obj, '__wrapped__'):
            obj = obj.__wrapped__
        if isinstance(obj, (staticmethod, classmethod)):
            obj = obj.__func__
        if isinstance(obj, types.MethodType):
            obj = obj.__func__
        if not isinstance(obj, types.FunctionType) or id(obj) in seen:
            continue
        seen.add(id(obj))
        g = obj.__globals__
        module = g.get('__name__', '')
        if not module.startswith(PACKAGE):
            continue
        key = (module, obj.__code__.co_qualname)
        if key in tainted_functions:
            found.extend((f'{module}.{key[1]}', v, why) for v, why in tainted_functions[key][:2])
        classes = []
        owner = obj.__code__.co_qualname.split('.<locals>.')[-1].rsplit('.', 1)
        if len(owner) == 2 and isinstance(g.get(owner[0]), type):
            classes.append(g[owner[0]])
        if cls_ctx is not None:
            classes.append(cls_ctx)
        cells = []
        for cell in obj.__closure__ or ():
            try:
                cells.append(cell.cell_contents)
            except ValueError:
                continue
        modules = []
        for c in cells:
            if isinstance(c, (types.FunctionType, OptionalSection)):
                stack.append((c, None))
            elif isinstance(c, types.ModuleType):
                modules.append(c)
            elif not isinstance(c, (int, str, bytes, float, tuple, list, dict, set, type(None))):
                classes.append(type(c))
        package = module if obj.__globals__.get('__path__') else module.rpartition('.')[0]
        for code in _codes(obj.__code__):
            for name in code.co_names:
                if (module, name) in tainted_globals:
                    found.extend((f'{module}.{name}', v, why) for v, why in tainted_globals[(module, name)][:2])
                target = g.get(name)
                if target is None:
                    # a function-local `from . import name`
                    target = sys.modules.get(f'{package}.{name}')
                if isinstance(target, (types.FunctionType, OptionalSection)):
                    stack.append((target, None))
                elif isinstance(target, type):
                    classes.append(target)
                    stack.append((getattr(target, '__init__', None), target))
                elif isinstance(target, types.ModuleType):
                    modules.append(target)
                elif target is not None and type(target).__module__.startswith(PACKAGE):
                    classes.append(type(target))
            names = set(code.co_names)
            for m in modules:
                mname = getattr(m, '__name__', '')
                for name in names:
                    if (mname, name) in tainted_globals:
                        found.extend((f'{mname}.{name}', v, why) for v, why in tainted_globals[(mname, name)][:2])
                    attr = getattr(m, name, None) if mname.startswith(PACKAGE) else None
                    if isinstance(attr, (types.FunctionType, OptionalSection)):
                        stack.append((attr, None))
                    elif isinstance(attr, type):
                        classes.append(attr)
            for cls in classes:
                if not cls.__module__.startswith(PACKAGE):
                    continue
                for name in names:
                    attr = cls.__dict__.get(name)
                    if attr is None:
                        for base in cls.__mro__[1:]:
                            attr = base.__dict__.get(name)
                            if attr is not None:
                                break
                    if attr is not None:
                        stack.append((attr, cls))
                    if (cls.__module__, cls.__name__) in tainted_globals and name in cls.__dict__:
                        found.extend((f'{cls.__module__}.{cls.__name__}.{name}', v, why)
                                     for v, why in tainted_globals[(cls.__module__, cls.__name__)][:1])
    return found


def _codes(code):
    yield code
    for const in code.co_consts:
        if hasattr(const, 'co_names'):
            yield from _codes(const)


def unavailable_tables() -> dict:
    """{table or record class: reason} of the fmdb tables whose root, vtable or getter did not
    resolve on this build (the snapshot and fm_db_* tools refuse exactly those)."""
    from . import database
    from .fmdb import tables
    out = {}
    for kind, (root, vtable, _name) in database.TABLES.items():
        bad = [v for v in (root, vtable) if isinstance(v, Unresolved)]
        if bad:
            out[f'table {kind}'] = '; '.join(f'{b.pinned:#x}: {b.reason}' for b in bad)
    for vtable, (cls, getter, _primary) in tables.CLASSES.items():
        bad = [v for v in (vtable, getter) if isinstance(v, Unresolved)]
        if bad:
            out[f'class {cls}'] = '; '.join(f'{b.pinned:#x}: {b.reason}' for b in bad)
    return out


def report(tools: dict | None = None) -> dict:
    """The build section of fm_status / fm_coverage."""
    out = {'state': ACTIVE['state'], 'build': ACTIVE.get('version'), 'plugin_sha256': ACTIVE.get('sha256'),
           'pinned_build': PINNED_VERSION, 'address_map': ACTIVE.get('map')}
    if ACTIVE.get('installed_sha256') and ACTIVE['installed_sha256'] != ACTIVE.get('sha256'):
        out['installed_plugin_sha256'] = ACTIVE['installed_sha256']
    if ACTIVE.get('error'):
        out['error'] = ACTIVE['error']
    if ACTIVE['state'] == 'unsupported':
        out['action'] = (f'No address map for the installed build. Run: PYTHONPATH=. python {UPDATE_COMMAND} '
                         f'--installed, then restart the MCP server.')
    if MAP is None:
        return out
    values = MAP['values']
    out['addresses'] = {'total': len(values), 'resolved': sum(1 for e in values.values() if e['value'] is not None)}
    out['verified'] = MAP.get('verified')
    unresolved = sorted((k, e.get('detail', '')) for k, e in values.items() if e['value'] is None)
    out['unresolved'] = [{'pinned': k, 'why': why} for k, why in unresolved[:40]]
    if MAP.get('disabled'):
        out['disabled_decoders'] = MAP['disabled']
    if MAP.get('disabled_managers'):
        out['disabled_managers'] = MAP['disabled_managers']
    if MAP.get('withheld'):
        out['withheld_fields'] = {m: sorted(p) for m, p in MAP['withheld'].items()}
    if MAP.get('unavailable', {}).get('tables'):
        out['unavailable_tables'] = MAP['unavailable']['tables']
    if tools is not None:
        missing = unavailable_tools(tools)
        out['unavailable_tools'] = missing
        partial = partial_tools(tools)
        if partial:
            out['partial_tools'] = partial
        replaced = partial_tools(tools, checks=True)
        if replaced:
            # the whole result is returned; only how the native code is checked differs here
            out['replaced_checks'] = replaced
        out['available_tools'] = len([t for t in tools if t not in missing])
    return out
