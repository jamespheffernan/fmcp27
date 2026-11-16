"""`fm_native_schema` and `fm_native_read`: persisted native state through the game's own save code."""
from __future__ import annotations

from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from . import persist

NOTE = ('Values are the bytes the game\'s own save code writes for the object, emulated on copied live memory '
        '(nothing is written to the game or to a file). Field names are not in the binary: a field is named only from '
        'evidence (label_source: rtti, decoder:<module>); otherwise field_<n> with its type and the object offset '
        'it was read from (offset_source: buffer = save code wrote straight from the object, load = the stored '
        'value came from that load, value = the same bytes sit at that offset on every instance). '
        'caller<k>+0x.. is an offset in the object of the k-th enclosing save function.')


def native_schema(root=None, search=None, limit=60) -> dict[str, Any]:
    data = persist.load_schema()
    roots = data.get('roots', [])
    out = {'note': NOTE, 'built_at': data.get('built_at'), 'game_date': data.get('game_date'),
           'build': data.get('build')}
    if root is None and search is None:
        out['roots'] = [{k: r.get(k) for k in ('root', 'root_class', 'status', 'refusal', 'writes', 'bytes',
                                               'fast_seconds')} | {'functions': len(r.get('functions', []))}
                        for r in roots]
        classes = {}
        for r in roots:
            for f in r.get('functions', []):
                if f.get('class'):
                    classes.setdefault(f['class'], []).append({'root': r['root'], 'function': f['function'],
                                                               'instances': f['instances']})
        out['classes'] = dict(sorted(classes.items()))
        return out
    want = (root or '').strip()
    term = (search or '').lower()
    hits = []
    for r in roots:
        if want and want not in (r['root'], r.get('root_class')):
            continue
        for f in r.get('functions', []):
            if term and term not in (f.get('class') or '').lower() and term not in f['function'] and \
                    not any(term in (x.get('name') or '') for x in f['fields']):
                continue
            hits.append({'root': r['root'], **f})
    out['functions'] = hits[:limit]
    out['matched'] = len(hits)
    if want:
        r = next((r for r in roots if r['root'] == want), None)
        if r:
            out.update({k: r.get(k) for k in ('root_class', 'status', 'refusal', 'writes', 'bytes', 'fast_seconds',
                                              'provenance')})
    return out


def native_read(engine, cls, key=None, depth=4, limit=400) -> dict[str, Any]:
    """`cls`: a save root (fm_native_schema roots) or a persisted class; `key`: for a class, the object
    address (0x...) or its position among the class's objects in the root's save (0 = first)."""
    with engine.lock:
        try:
            route = persist.find_route(cls)
        except persist.PersistError:
            route = None
        if route is not None and key is None:
            out = persist.dump(engine, cls, depth=depth, limit=limit)
        else:
            address = _instance(engine, cls, key)
            out = persist.dump(engine, cls, address, depth=depth, limit=limit)
    out['note'] = NOTE
    return out


def _instance(engine, cls, key):
    if isinstance(key, str) and key.lower().startswith('0x'):
        return int(key, 16)
    position = int(key or 0)
    function = persist.function_for_class(engine, cls)
    data = persist.load_schema()
    for r in data.get('roots', []):
        if any(f['function'] == f'{function:#x}' for f in r.get('functions', [])):
            rec = persist.record(engine, persist.find_route(r['root']), provenance=False)
            objs = [c.obj for c in rec.calls if c.function == function]
            if not 0 <= position < len(objs):
                raise persist.PersistError(f'{cls}: position {position} outside 0..{len(objs) - 1}')
            return objs[position]
    raise persist.PersistError(f'{cls}: no save root writes it')


def register_persist_tools(mcp, bridge):
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @mcp.tool(annotations=read_only)
    def fm_native_schema(
        session_id: str,
        root: Annotated[str | None, Field(min_length=2, max_length=96)] = None,
        search: Annotated[str | None, Field(min_length=2, max_length=96)] = None,
        limit: Annotated[int, Field(ge=1, le=400)] = 60,
    ) -> dict[str, Any]:
        """Persisted native state as the game's own save code writes it: the save roots (managers the save walker hands to their save functions), and for each save function its class, how many objects it wrote and the ordered field list (type, how often per object, object offset and how it was proven, element class of nested objects, label and its evidence). No filters: the roots and every persisted class with its save function. root (e.g. "INJURY_MANAGER") or search (class, function or label) narrow the list. Reads the packaged schema; never touches the game."""
        try:
            return native_schema(root=root, search=search, limit=limit)
        except persist.PersistError as exc:
            raise ValueError(str(exc)) from exc

    @mcp.tool(annotations=read_only)
    def fm_native_read(
        session_id: str,
        cls: Annotated[str, Field(min_length=2, max_length=96)],
        key: Annotated[str | None, Field(min_length=1, max_length=24)] = None,
        depth: Annotated[int, Field(ge=0, le=12)] = 4,
        limit: Annotated[int, Field(ge=1, le=20000)] = 400,
    ) -> dict[str, Any]:
        """Read one persisted native object by running the game's own save code for it on copied live memory (read-only). cls is a save root from fm_native_schema (e.g. "CONTRACT_MANAGER": the whole manager in save order) or a persisted class (e.g. "db::ACTUAL_PLAYER", "INJURY"); key, for a class, is the object address ("0x...") or its position among that class's objects (0 = first). Returns the ordered typed field list with nested objects expanded to depth, references to database records as table/idx, object offsets with their proof, the save function, streams and status (refusal with the exact cause). limit caps the fields returned."""
        from .tools import engine_for
        try:
            return native_read(engine_for(bridge, session_id), cls, key, depth, limit)
        except persist.PersistError as exc:
            raise ValueError(str(exc)) from exc

    return ['fm_native_schema', 'fm_native_read']
