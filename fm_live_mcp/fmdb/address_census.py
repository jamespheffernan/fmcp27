"""Which integer literals under fm_live_mcp/ are plugin addresses, and which merely fall in range.

The reader's hand-built tools, the knowledge engine and parts of the fmdb core carry plugin RVAs
of build 27.0.0.2493426 as plain integer literals. On another build the address book
(`fm_live_mcp/address_book.py`) rewrites exactly the literals this census marks as addresses,
by (file, value). A number that only falls inside the image range (a row budget of 100000, a
template id, a 0x400_0000 size limit) must be left alone, so every in-range literal gets one
of two decisions:

  A  an address: rewritten to the build's address, or made to refuse when it does not resolve
  C  a coincidence: left as written

How a site is decided (first matching rule; `RULES` names them in the census file):

  override    an explicit entry in `data/address_overrides.json` (by file and value, or for a
              value in every file), each with a reason
  vtable      the value is a vtable address point of the pinned build (RTTI)
  typeinfo    the value is a type_info object
  guard       the literal sits in a tuple with code bytes or a sha256 (the native-span and
              native-guard tables): whatever its spelling, it is an address
  round       a power of two, or a decimal literal that is a multiple of 1,000: a size, a
              budget or a limit
  function    the start of a function (LC_FUNCTION_STARTS)
  xref        a data address that code of the pinned build references (ADRP pairs)
  code-hex    an instruction address written in hex (call sites, return addresses, patch points)
  code-dec    an instruction address written in decimal outside a guard: an id or a count
  data-hex    a data address written in hex that no code references directly (a field of a
              global, a free-list head)
  data-dec    the same in decimal: a coincidence
  section     the start or end of a section (text bounds used as range checks)
  text-const  an address in __TEXT outside __text (constant tables, jump tables, stubs) in hex
  outside     not 4-aligned in code, or in __LINKEDIT: not an address

The census file (`data/address_census.json.gz`) records, per file and value, the decision, the
rule, the pinned-build kind and the enclosing scopes of every occurrence (function qualnames,
or the module-level names a table is assigned to), which is what `fm_status` uses to say which
tools a missing address disables. It describes the source tree, not a build: rebuild it with
`scripts/fmdb_rebase.py <pinned plugin> --census --write` after adding a literal address, and
`tests/test_address_book.py` fails while the tree has an in-range literal the census lacks.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
DATA = Path(__file__).with_name('data')
CENSUS_PATH = DATA / 'address_census.json.gz'
OVERRIDES_PATH = DATA / 'address_overrides.json'
CENSUS_FORMAT = 'fmcp-address-census/1'
LOW = 0x10000
# The first code address of the plugin (the same on 27.0.0 and 27.0.1; smaller values are inside
# the Mach-O header). Below LOW a literal is an address only as the address of a native guard:
# the game's static initialisers sit there, and four guards check them (the entity setup row
# and the playback event row write their own field offsets at 0xD6C4..0xE204). They were left
# at their pinned values on 27.0.1, so the frame tool and the playback events refused (found
# on a live match, 12 November 2026).
CODE_START = 0x55F0

GROUPS = ('fmdb', 'knowledge', 'hand-built')


def group_of(rel: str) -> str:
    """fmdb core, knowledge engine or hand-built tools (the census groups)."""
    if rel.startswith('fmdb/'):
        return 'fmdb'
    return 'knowledge' if 'knowledge' in rel else 'hand-built'


# --------------------------------------------------------------------------- scanning
def _scopes(tree):
    """{node: scope} for every node: 'module:<names>' for module-level statements (the names
    they assign), 'class:<Name>' for class bodies, else the qualname of the enclosing function."""
    out = {}

    def targets(stmt):
        names = []
        nodes = stmt.targets if isinstance(stmt, ast.Assign) else [getattr(stmt, 'target', None)]
        for t in nodes:
            for n in ast.walk(t) if t is not None else ():
                if isinstance(n, ast.Name):
                    names.append(n.id)
        return names

    def outer(node, scope, qual):
        out[node] = scope
        visit(node, scope, qual)

    def visit(node, scope, qual):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[child] = scope
                for sub in [*child.decorator_list, child.args, *([child.returns] if child.returns else [])]:
                    outer(sub, scope, qual)
                name = qual + child.name
                for stmt in child.body:
                    outer(stmt, name, name + '.<locals>.')
            elif isinstance(child, ast.ClassDef):
                out[child] = scope
                name = qual + child.name
                body_scope = f'class:{name}' if scope.startswith('module:') else scope
                for sub in [*child.decorator_list, *child.bases, *child.keywords]:
                    outer(sub, scope, qual)
                for stmt in child.body:
                    outer(stmt, body_scope, name + '.')
            else:
                s = scope
                if scope == 'module:' and isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    s = 'module:' + ','.join(targets(child))
                outer(child, s, qual)

    visit(tree, 'module:', '')
    return out


def _is_guard_sibling(node) -> bool:
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bytes):
            return True
        if isinstance(v, str) and len(v) >= 8 and len(v) % 2 == 0 and all(c in '0123456789abcdefABCDEF' for c in v):
            return True                     # a sha256, or code bytes written as hex
        return False
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'fromhex':
        return True
    return False


_BIT_OPS = (ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift)


def _terminal(node) -> str:
    """The last name of an operand: `engine` for `engine`, `base` for `self.base`, '' otherwise."""
    while isinstance(node, (ast.BinOp, ast.Subscript, ast.Call)):
        node = node.left if isinstance(node, ast.BinOp) else (node.value if isinstance(node, ast.Subscript) else node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ''


def literal_sites(source: str, image_end: int):
    """[(value, line, col, spelling, scope, features)] of every int literal in [LOW, image_end),
    and of every guard address in [CODE_START, LOW).

    features: 'guard' (a sibling holds code bytes or a sha256), 'base' / 'offset' (added to an
    operand whose name says it is the image base / to any other operand), 'bits' (an operand of
    a bitwise operator), 'mask' (assigned to a name containing MASK)."""
    tree = ast.parse(source)
    lines = source.splitlines()
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    scopes = _scopes(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and type(node.value) is int and CODE_START <= node.value < image_end:
            text = lines[node.lineno - 1][node.col_offset:node.end_col_offset] if node.lineno == node.end_lineno else ''
            spelling = 'hex' if text.lower().startswith('0x') else 'dec'
            parent = parents.get(node)
            features = set()
            if isinstance(parent, ast.Tuple) and any(_is_guard_sibling(e) for e in parent.elts if e is not node):
                features.add('guard')
            if isinstance(parent, ast.Dict) and node in parent.keys and \
                    _is_guard_sibling(parent.values[parent.keys.index(node)]):
                features.add('guard')
            if node.value < LOW and not ('guard' in features and spelling == 'hex'):
                continue
            if isinstance(parent, ast.BinOp) and isinstance(parent.op, (ast.Add, ast.Sub)):
                other = parent.right if parent.left is node else parent.left
                name = _terminal(other).lower()
                if isinstance(other, ast.Constant) and isinstance(parent.op, ast.Sub) and parent.left is node:
                    pass                            # ADDRESS - 8: still the address itself
                elif 'base' in name:
                    features.add('base')
                elif name:
                    features.add('offset')
            if isinstance(parent, ast.BinOp) and isinstance(parent.op, _BIT_OPS):
                features.add('bits')
            scope = scopes.get(node, 'module:')
            if 'MASK' in scope.upper() and scope.startswith('module:'):
                features.add('mask')
            if isinstance(parent, ast.Tuple):
                for e in parent.elts:
                    if e is not node and isinstance(e, ast.Constant) and type(e.value) is int and \
                            LOW <= e.value < image_end:
                        features.add(f'with:{e.value:#x}')
            out.append((node.value, node.lineno, node.col_offset, spelling, scope, frozenset(features)))
    return out


def scan(root: Path = PACKAGE, image_end: int = 0x58F4000, files=None):
    """{relative file: [site]} for every .py under `root` (docstrings and comments are not literals),
    or for the listed `files` (paths relative to `root`)."""
    out = {}
    paths = sorted(Path(root).rglob('*.py')) if files is None else [Path(root) / f for f in files]
    for path in paths:
        try:
            source = path.read_text()
            sites = literal_sites(source, image_end)
        except (SyntaxError, UnicodeDecodeError):
            continue
        if sites:
            out[str(path.relative_to(root))] = sites
    return out


# --------------------------------------------------------------------------- deciding
def section_bounds(binary) -> dict:
    """{RVA: 'segment,section,start|end'} of every section start and end outside __LINKEDIT."""
    cached = getattr(binary, '_section_bounds', None)
    if cached is not None:
        return cached
    out = binary._section_bounds = {}
    for seg in binary.image.segments:
        if seg.name == '__LINKEDIT':
            continue
        for name, (start, size, *_rest) in seg.sections.items():
            out.setdefault(start + size, f'{seg.name},{name},end')
            out[start] = f'{seg.name},{name},start'
        out.setdefault(seg.vmaddr, f'{seg.name},,start')
        out.setdefault(seg.vmaddr + seg.vmsize, f'{seg.name},,end')
    return out


def kind_of(binary, rva) -> str:
    """vtable | typeinfo | function | code | xref | data | stub | text-const | section | outside."""
    if binary.class_name(rva):
        return 'vtable'
    if binary.typeinfo_at(rva):
        return 'typeinfo'
    if rva in section_bounds(binary) and not (binary.is_code(rva) and binary.function_of(rva)[0] == rva):
        return 'section'
    if binary.is_code(rva):
        if rva % 4:
            return 'outside'
        bounds = binary.function_of(rva)
        return 'function' if bounds and bounds[0] == rva else 'code'
    seg = binary.image.segment_for(rva)
    if seg is None or seg.name == '__LINKEDIT':
        return 'outside'
    if seg.name == '__TEXT':
        if rva in binary.image.stubs:
            return 'stub'
        return 'xref' if binary.refs.get(rva) else 'text-const'
    return 'xref' if binary.refs.get(rva) else 'data'


def _round(value: int, spelling: str) -> bool:
    return value & (value - 1) == 0 or (spelling == 'dec' and value % 1000 == 0)


# Offline save-file parsers name the native deserialiser each reader was derived from by its
# address; the number is a label there (registry keys, error details), never read from the game.
LABEL_PACKAGES = ('person_wire/', '_saved_offers/', '_saved_league/')


def decide(kind: str, value: int, spelling: str, features: frozenset, rel: str = '') -> tuple[str, str]:
    """(A|C, rule) for one site from its pinned-build kind, how it is written and where it sits."""
    if rel.startswith(LABEL_PACKAGES):
        return 'C', 'label'
    if kind in ('vtable', 'typeinfo'):
        return 'A', kind
    if 'guard' in features and kind != 'outside':
        return 'A', 'guard'
    if _round(value, spelling):
        return 'C', 'round'
    if 'bits' in features or 'mask' in features:
        return 'C', 'mask'
    if 'offset' in features and kind not in ('function', 'xref', 'stub'):
        return 'C', 'offset'
    if kind in ('function', 'xref', 'stub'):
        return 'A', kind
    if kind == 'section':
        return 'A', 'section'
    if kind == 'code':
        return ('A', 'code-hex') if spelling == 'hex' else ('C', 'code-dec')
    if kind == 'data':
        return ('A', 'data-hex') if spelling == 'hex' else ('C', 'data-dec')
    if kind == 'text-const':
        return ('A', 'text-const') if spelling == 'hex' else ('C', 'text-const-dec')
    return 'C', 'outside'


def load_overrides() -> dict:
    """{file or '*': {hex value: {'decision': A|C, 'why': ...}}}"""
    if not OVERRIDES_PATH.exists():
        return {}
    return json.loads(OVERRIDES_PATH.read_text())['overrides']


def build(binary, root: Path = PACKAGE, only=None) -> dict:
    """The census document of the source tree under `root`, classified on `binary` (pinned).

    A value used as an offset from a non-base operand anywhere (`engine + 0x15370`) and never
    added to the image base is a struct offset in every file (rule `offset`). A value decided
    both ways inside one file is reported in `mixed` and needs an override. With `only` (paths
    relative to `root`) only those files are scanned; the census then records each file's sha256
    under `sources`, and the adviser's import rewrite refuses a file whose text differs."""
    image_end = binary.image_end()
    if getattr(binary, 'text_start', CODE_START) != CODE_START:
        raise ValueError(f'code starts at {binary.text_start:#x}, not CODE_START {CODE_START:#x}')
    overrides = load_overrides()
    scanned = scan(root, image_end, only)
    adds = defaultdict(set)
    for sites in scanned.values():
        for value, _l, _c, _s, _scope, features in sites:
            adds[value] |= features & {'base', 'offset'}
    files, mixed = {}, []
    for rel, sites in scanned.items():
        entry = {}
        for value, line, col, spelling, scope, features in sites:
            key = f'{value:#x}'
            kind = kind_of(binary, value)
            rule_over = overrides.get(rel, {}).get(key) or overrides.get('*', {}).get(key)
            if rule_over:
                decision, rule = rule_over['decision'], 'override:' + rule_over.get('method', 'listed')
                if rule_over.get('of'):
                    entry.setdefault(key, {'d': decision, 'rule': rule, 'kind': kind, 'sites': []})['of'] = rule_over['of']
            elif adds[value] == {'offset'} and 'guard' not in features and \
                    kind in ('code', 'data', 'text-const', 'section', 'outside') and not rel.startswith(LABEL_PACKAGES):
                decision, rule = 'C', 'offset'
            else:
                decision, rule = decide(kind, value, spelling, features, rel)
            row = entry.setdefault(key, {'d': decision, 'rule': rule, 'kind': kind, 'sites': []})
            if kind in ('data', 'xref'):
                partners = sorted(f[5:] for f in features if f.startswith('with:') and
                                  binary.class_name(int(f[5:], 16)))
                if partners:
                    row['with'] = sorted(set(row.get('with', [])) | set(partners))
            if row['d'] != decision:
                mixed.append((rel, key, row['rule'], rule))
                if decision == 'A':
                    row.update(d='A', rule=rule)
            row['sites'].append([line, col, scope])
        files[rel] = entry
    doc = {'format': CENSUS_FORMAT, 'pinned_sha256': binary.sha256, 'image_end': image_end, 'files': files,
           'mixed': mixed}
    if only is not None:
        import hashlib
        doc['sources'] = {str(f): hashlib.sha256((Path(root) / f).read_bytes()).hexdigest() for f in only}
    return doc


def save(doc: dict, path: Path = CENSUS_PATH) -> Path:
    path.write_bytes(gzip.compress(json.dumps(doc, separators=(',', ':'), sort_keys=True).encode(), 9))
    return path


_CACHE = {}


def load(path: Path = CENSUS_PATH) -> dict | None:
    if path in _CACHE:
        return _CACHE[path]
    if not path.exists():
        return None
    doc = json.loads(gzip.decompress(path.read_bytes()))
    _CACHE[path] = doc
    return doc


def addresses(doc: dict) -> dict:
    """{pinned value: [(file, scope)]} of every literal the census marks as an address."""
    out = defaultdict(list)
    for rel, entry in doc['files'].items():
        for key, row in entry.items():
            if row['d'] == 'A':
                for _line, _col, scope in row['sites']:
                    out[int(key, 16)].append((rel, scope))
    return dict(out)


def summary(doc: dict) -> dict:
    """Per group: sites and distinct values by decision and rule."""
    out = {g: {'values': Counter(), 'sites': Counter(), 'rules': Counter()} for g in GROUPS}
    seen = defaultdict(set)
    for rel, entry in doc['files'].items():
        g = group_of(rel)
        for key, row in entry.items():
            out[g]['sites'][row['d']] += len(row['sites'])
            out[g]['rules'][(row['d'], row['rule'])] += len(row['sites'])
            if key not in seen[(g, row['d'])]:
                seen[(g, row['d'])].add(key)
                out[g]['values'][row['d']] += 1
    return out
