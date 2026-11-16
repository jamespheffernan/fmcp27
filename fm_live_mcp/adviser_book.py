"""pi-fm's tactic writer on the installed game build: the adviser's half of the address book.

The tactic writer (`adviser/pi/fm-tactic-files.py` and its siblings `fm_tactic_*.py`) runs the
game's own tactic code under Unicorn. Its source carries the plugin addresses, guard hashes and
build identity of 27.0.0.2493426, like the reader. On that build nothing here does anything.

On a build whose address map (scripts/fm_update_build.py) has an `adviser` section, the tactic
files are compiled through the same kind of rewrite the reader's modules get
(`address_book.py`): the literals the adviser census (`fmdb/data/adviser_census.json.gz`) marks
as addresses become that build's addresses (or `Unresolved`, which refuses where it is used);
guard hashes and bytes become the new build's where the code is the same under masking or was
reviewed (`fmdb/data/address_overrides.json`), including the length of a reviewed span; and the
build facts that are not addresses become the new build's where the update verified them:

  * the plugin's sha256 (the map is derived for that plugin, so every identity gate accepts
    exactly it) and the file offset of its arm64 slice (read from the Mach-O fat header);
  * the language template `example.ltf` (sha256), only when every English text the writer
    carries was found unchanged in the new file under the same text id;
  * `global-metadata.dat` (sha256), only when every metadata enum the role catalog names has
    the same members and values in the new file.

A function the update found unusable on the build (a guard over code that changed and was not
reviewed, or an address that did not resolve) is made to refuse at its first line, naming the
build and the code; everything else keeps working (`unavailable()` lists them).

The files are rewritten only when their text is the text the census was taken from (sha256 per
file in the census); otherwise nothing is rewritten and the writer's own identity checks refuse
the build, as before. Nothing here reads the game's memory or writes a file.
"""
from __future__ import annotations

import ast
import gzip
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys

from . import address_book

ADVISER_DIR = 'adviser/pi'
CENSUS_PATH = Path(__file__).resolve().parent / 'fmdb' / 'data' / 'adviser_census.json.gz'
# The tactic writer's files (relative to the repository root), as the census scans them.
FILES = ('adviser/pi/fm-tactic-files.py', 'adviser/pi/fm_tactic_native_core.py',
         'adviser/pi/fm_tactic_native_authoring.py', 'adviser/pi/fm_tactic_role_catalog.py',
         'adviser/pi/fm_tactic_team_instructions.py', 'adviser/pi/fm_tactic_position_records.py')
MODULES = {Path(f).stem: f for f in FILES if '-' not in Path(f).stem}
PINNED_SLICE_OFFSET = 0x5ED4000      # arm64 slice of the pinned plugin's fat file
_CENSUS: dict | None = None
_STATE: dict | None = None


class AdviserBuildError(RuntimeError):
    """The tactic writer cannot be bound to the running build."""


def census() -> dict:
    global _CENSUS
    if _CENSUS is None:
        _CENSUS = json.loads(gzip.decompress(CENSUS_PATH.read_bytes()))
    return _CENSUS


def section() -> dict | None:
    """The adviser section of the loaded address map, or None."""
    return (address_book.MAP or {}).get('adviser') if address_book.ACTIVE['state'] == 'mapped' else None


def state() -> dict:
    """{'state': 'pinned' | 'mapped' | 'unsupported', 'version', 'plugin_sha256', 'reason'}."""
    global _STATE
    if _STATE is not None:
        return _STATE
    active = address_book.ACTIVE
    if active['state'] == 'pinned':
        _STATE = {'state': 'pinned', 'version': active['version'], 'plugin_sha256': active['sha256'], 'reason': None}
    elif active['state'] == 'mapped' and section() is not None:
        _STATE = {'state': 'mapped', 'version': active['version'], 'plugin_sha256': active['sha256'], 'reason': None}
    elif active['state'] == 'mapped':
        _STATE = {'state': 'unsupported', 'version': active['version'], 'plugin_sha256': active['sha256'],
                  'reason': (f'the address map of {address_book.build_label()} has no tactic-writer section; '
                             f'run PYTHONPATH=. python {address_book.UPDATE_COMMAND} --installed')}
    else:
        _STATE = {'state': 'unsupported', 'version': active.get('version'), 'plugin_sha256': active.get('sha256'),
                  'reason': address_book.refusal(active.get('version'), active.get('sha256'))}
    return _STATE


def rel_of(path) -> str:
    return f'{ADVISER_DIR}/{Path(path).name}'


def _source_matches(rel: str, source: bytes) -> bool:
    return census().get('sources', {}).get(rel) == hashlib.sha256(source).hexdigest()


def unavailable() -> dict:
    """{file: {function qualname: reason}} of the writer's functions that refuse on this build."""
    sec = section()
    return {} if sec is None else {rel: dict(fns) for rel, fns in (sec.get('disabled') or {}).items()}


# --------------------------------------------------------------------------- the rewrite
def _address(pinned: int):
    sec = section() or {}
    entry = (sec.get('values') or {}).get(f'{pinned:#x}') or {}
    return address_book.Unresolved(pinned, f'tactic writer: {entry.get("detail") or entry.get("method") or "not resolved"}')


def _refuse(qualname: str, reason: str):
    raise address_book.UnresolvedAddress(
        f'pi-fm tactic writer: {qualname} is unavailable on game build {address_book.build_label()}: {reason}')


def identity(sec: dict) -> dict:
    """{pinned constant: this build's constant} of the verified build facts."""
    out = {}
    ident = sec.get('identity') or {}
    plugin = ident.get('plugin') or {}
    if plugin.get('sha256'):
        out[plugin['pinned_sha256']] = plugin['sha256']
    slice_ = ident.get('slice_offset') or {}
    if slice_.get('value') is not None:
        out[slice_['pinned']] = slice_['value']
    for fact in ('english', 'metadata'):
        row = ident.get(fact) or {}
        if row.get('verified') and row.get('sha256'):
            out[row['pinned_sha256']] = row['sha256']
    return out


class _Rewriter(ast.NodeTransformer):
    def __init__(self, sec: dict, rel: str, counts: dict):
        self.rows = census()['files'].get(rel, {})
        self.values = sec.get('values') or {}
        self.per_file = (sec.get('per_file') or {}).get(rel, {})
        self.guards = ((sec.get('guards') or {}).get('files') or {}).get(rel, {})
        self.lengths = ((sec.get('guards') or {}).get('lengths') or {}).get(rel, {})
        self.image_end = census()['image_end']
        self.identity = identity(sec)
        self.counts = counts

    def visit_Tuple(self, node):
        # (address, length, sha256) of a span whose reviewed length differs on this build
        length = None
        if len(node.elts) >= 3 and isinstance(node.elts[1], ast.Constant) and type(node.elts[1].value) is int:
            sha = next((e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
                        and e.value in self.lengths), None)
            if sha is not None:
                length = self.lengths[sha]
        self.generic_visit(node)
        if length is not None:
            node.elts[1] = ast.copy_location(ast.Constant(length), node.elts[1])
            self.counts['lengths'] += 1
        return node

    def visit_Constant(self, node):
        v = node.value
        if type(v) is int and v in self.identity:
            self.counts['identity'] += 1
            return ast.copy_location(ast.Constant(self.identity[v]), node)
        if type(v) is int and 0 <= v < self.image_end:
            row = self.rows.get(f'{v:#x}')
            if row is None or row['d'] != 'A':
                return node
            entry = self.per_file.get(f'{v:#x}') or self.values.get(f'{v:#x}') or {}
            new = entry.get('value')
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


def rewrite(tree: ast.AST, rel: str, sec: dict | None = None) -> dict:
    """Rewrite one adviser file's tree for the loaded build; returns the counts."""
    sec = sec if sec is not None else section()
    counts = {'addresses': 0, 'unresolved': 0, 'guards': 0, 'lengths': 0, 'identity': 0, 'disabled': 0}
    _Rewriter(sec, rel, counts).visit(tree)
    disabled = (sec.get('disabled') or {}).get(rel) or {}
    for qualname, fn in address_book._functions(tree):
        if qualname in disabled:
            call = ast.parse(f'__fmcp_adviser_refuse__({qualname!r}, {disabled[qualname]!r})').body[0]
            ast.copy_location(call, fn.body[0])
            fn.body.insert(0, call)
            counts['disabled'] += 1
    ast.fix_missing_locations(tree)
    return counts


REWRITTEN: dict = {}


def compile_file(path) -> object:
    """The code object of an adviser file for the loaded build (rewritten when mapped)."""
    path = Path(path)
    rel = rel_of(path)
    source = path.read_bytes()
    tree = ast.parse(source, str(path))
    st = state()
    if st['state'] == 'mapped':
        if not _source_matches(rel, source):
            raise AdviserBuildError(
                f'{rel} differs from the text the adviser census was taken from; the tactic writer cannot be '
                f'bound to game build {address_book.build_label()} (rebuild the census: '
                f'scripts/fm_update_build.py --adviser-census)')
        REWRITTEN[rel] = rewrite(tree, rel)
    return compile(tree, str(path), 'exec', dont_inherit=True)


def _prepare(namespace: dict) -> None:
    namespace['__fmcp_address__'] = _address
    namespace['__fmcp_adviser_refuse__'] = _refuse
    namespace['__fmcp_adviser__'] = state()['state']


class _Loader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        return compile_file(self.path)

    def set_data(self, *_args, **_kwargs):
        return None                         # never cache rewritten bytecode next to the source

    def exec_module(self, module):
        _prepare(module.__dict__)
        super().exec_module(module)


class _Finder(importlib.abc.MetaPathFinder):
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in MODULES:
            return None
        origin = self.directory / f'{fullname}.py'
        if not origin.is_file():
            return None
        return importlib.util.spec_from_file_location(fullname, origin, loader=_Loader(fullname, str(origin)))


def source_loader(name: str, path) -> importlib.machinery.SourceFileLoader:
    """A loader for an adviser file loaded by path (`importlib.util.spec_from_file_location`): the
    rewriting loader on a mapped build, the plain one otherwise."""
    if state()['state'] == 'mapped':
        return _Loader(name, str(path))
    return importlib.machinery.SourceFileLoader(name, str(path))


def install(directory) -> None:
    """Load the writer's sibling modules (by name) from `directory` through the rewrite."""
    if state()['state'] != 'mapped':
        return
    if not any(isinstance(f, _Finder) for f in sys.meta_path):
        sys.meta_path.insert(0, _Finder(directory))


def rerun_as_main(path, namespace: dict) -> bool:
    """Run the script at `path` again, rewritten for the loaded build, as `__main__`; True when it
    ran (the caller then stops). On the pinned build, an unsupported build, or inside the
    rewritten run itself, returns False and the script continues as written."""
    if namespace.get('__fmcp_adviser__') or state()['state'] != 'mapped':
        return False
    path = Path(path).resolve()
    install(path.parent)
    try:
        code = compile_file(path)
    except AdviserBuildError as exc:
        print(json.dumps({'error': str(exc), 'type': type(exc).__name__}), file=sys.stderr)
        raise SystemExit(1) from exc
    main = {'__name__': '__main__', '__file__': str(path), '__builtins__': namespace['__builtins__'],
            '__spec__': None, '__package__': None, '__doc__': namespace.get('__doc__')}
    _prepare(main)
    exec(code, main)                        # noqa: S102 - the writer's own file, rewritten for this build
    return True
