"""Native state tables: containers of persisted objects, read by running the game's own save code.

One table per element class that a manager's save function writes many times (see
docs/fmdb/PERSIST.md and `fm_live_mcp/fmdb/persist.py`). The list of tables and their columns
comes from the shipped schema (`data/persist_schema.json.gz`, made by scripts/fmdb_persist.py);
rows come from a fresh emulated save of the owning manager root the first time a statement names
the table (lazy). Each row is one object the save function was given (x0):

* `idx` order of the object in the save, `object` its live address, `parent_object` and
  `parent_class` the object whose save function wrote it, `position` its place among the
  siblings written from the same site, `ref_table` / `ref_idx` the database table and index when
  the object is a record of a live table;
* one column per value field written exactly once per object (`f<n>_<type>`, or the evidence
  label), in the game's write order; the column meaning gives the type, the object offset the
  value came from and how that offset was proven (buffer / load / value; PERSIST.md).

Field names are not in the binary: columns without evidence keep `f<n>`. Manager policy: these
are internal values of the save (`never`, withheld) unless a later lane proves a UI shows them.
"""
from __future__ import annotations

from collections import defaultdict
import re

from . import Column, SourceTable

MIN_INSTANCES = 20               # an element class with at least this many objects gets a table
MIN_FIELDS = 2                   # ... and at least this many value fields written once per object
MAX_TABLES = 80                  # the classes with the most objects first
MAX_COLUMNS = 120


def _schema():
    from .. import persist
    return persist.load_schema()


def _name(text):
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')


def _signed(value):
    if isinstance(value, int) and value >= 1 << 63:
        return value - (1 << 64)
    return value


def _value(data):
    if len(data) in (1, 2, 4, 8):
        return _signed(int.from_bytes(data, 'little'))
    return data.hex()


def plan() -> list[dict]:
    """[{table, root, function, class, fields}] from the shipped schema."""
    out, used = [], set()
    from .. import persist
    candidates = []
    for root in _schema().get('roots', []):
        for f in root.get('functions', []):
            single = [x for x in f['fields'] if x['kind'] == 'value' and x['per_instance'][1] == 1]
            short = (f.get('class') or '').split('::')[-1]
            if short in persist.TABLE_OF_CLASS:
                continue    # a database record written as a reference (its unique id): the table has it
            if f.get('instances', 0) >= MIN_INSTANCES and f.get('class') and len(single) >= MIN_FIELDS:
                candidates.append((root, f))
    candidates.sort(key=lambda rf: -rf[1]['instances'])
    for root, f in candidates[:MAX_TABLES]:
        if True:
            cls = f.get('class')
            base = 'native_' + (_name(cls.split('::')[-1]) if cls else 'fn_' + f['function'][2:])
            name = base if base not in used else f"{base}_{_name(root['root'])}"
            if name in used:
                name = f"{name}_{f['function'][2:]}"
            used.add(name)
            fields = [x for x in f['fields'] if x['kind'] == 'value' and x['per_instance'][1] == 1][:MAX_COLUMNS]
            out.append({'table': name, 'root': root['root'], 'function': f['function'], 'class': cls,
                        'instances': f['instances'], 'fields': fields})
    return out


def _column(field):
    label = field.get('name') or f"field_{field['n']}"
    col = label if field.get('label_source') else f"f{field['n']}_{field['type'].replace('[', '').replace(']', '')}"
    sql = 'INTEGER' if field['type'] in ('u8', 'u16', 'u32', 'u64') else 'TEXT'
    where = field.get('offset')
    meaning = (f"{field['type']} written by save site {field['site']}"
               + (f", object offset {where} ({field.get('offset_source')})" if where else ', offset not proven')
               + (f", label from {field['label_source']}" if field.get('label_source') else ''))
    return Column(_name(col), sql, meaning)


def _rows(engine, spec):
    from .. import persist
    rec = persist.record(engine, persist.find_route(spec['root']), provenance=False)
    an = persist.Analysis(engine, rec)
    fn = int(spec['function'], 16)
    keys = [persist.key_of(f) for f in spec['fields']]
    position = defaultdict(int)
    rows = []
    for i, call in enumerate(an.by_fn.get(fn, ())):
        first = {}
        for key, entry in an.keys_of(call):
            if key[0] == 'w' and key not in first:
                first[key] = entry.data
        parent = rec.calls[call.parent] if call.parent is not None else None
        slot = (call.parent, call.site)
        pos = position[slot]
        position[slot] += 1
        cls = rec.classes.get(call.id)
        ref = persist._ref(engine, None, cls, call.obj) or {}
        rows.append((i, f'{call.obj:#x}', f'{parent.obj:#x}' if parent else None,
                     rec.classes.get(parent.id) if parent else None, pos, cls, ref.get('table'), ref.get('idx'),
                     *[_value(first[k]) if k in first else None for k in keys]))
    return rows


def tables(engine) -> list[SourceTable]:
    out = []
    for spec in plan():
        cols = [Column('idx', 'INTEGER', 'order of the object in the emulated save'),
                Column('object', 'TEXT', 'live address of the object (x0 of its save function)'),
                Column('parent_object', 'TEXT', 'object whose save function wrote this one'),
                Column('parent_class', 'TEXT', 'RTTI class of the parent object'),
                Column('position', 'INTEGER', 'place among the objects written from the same site of the parent'),
                Column('class', 'TEXT', 'RTTI class of the object'),
                Column('ref_table', 'TEXT', 'database table when the object is a record of a live table'),
                Column('ref_idx', 'INTEGER', 'idx in ref_table')]
        seen = {c.name for c in cols}
        for f in spec['fields']:
            c = _column(f)
            if c.name in seen:
                c.name = f"{c.name}_{f['n']}"
            seen.add(c.name)
            cols.append(c)
        out.append(SourceTable(
            name=spec['table'],
            description=(f"persisted {spec['class'] or 'objects'} written by save function {spec['function']} "
                         f"of {spec['root']} ({spec['instances']} at schema build)"),
            columns=cols, rows=(lambda s=spec: _rows(engine, s)), mode='lazy', invalidation='game_date',
            cost_note=f"one emulated save of {spec['root']} (seconds to a minute; persist.record caches 120 s)",
            source_note=("the game's own save code emulated on copied live memory with a recording stream "
                         "(docs/fmdb/PERSIST.md); values are the bytes it writes"),
            manager={'scope': 'never'}))
    return out
