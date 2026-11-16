"""Differential test: generic reader (PropertyVM) against the existing hand-proven tools, live.

Usage:
  PYTHONPATH=. python scripts/fmdb_oracle.py [--players 100] [--clubs 50] [--competitions 50]
      [--stadiums 50] [--cities 50] [--currencies 0] [--staff 50] [--seed 1] [--no-managed]
      [--samples player,club,...] [--out out/fmdb-oracle/report.json] [--markdown docs/fmdb/ORACLE.md]

`--currencies 0` means every currency record. Each sampled record is read through the existing
tool (a `Bridge` method) and through `PropertyVM.get_property`; `fm_live_mcp/fmdb/oracle_map.py`
says which tool JSON path pairs with which FourCC and rule. A record whose comparison
mismatches is re-read once (tool and generic) before the mismatch is recorded.

Record handles: the tools take opaque references minted by their finder tools. To compare a
random record the harness registers a reference for it in the Bridge's own reference table,
using the same decoders the finders use, then calls the public `get_*` tool. Only the
handle is forged; every compared value comes from the tool's normal path.
Strictly read-only: no writes, no UI.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import random
import re
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parent.parent

from fm_live_mcp.fmdb import oracle_map as om  # noqa: E402
from fm_live_mcp.fmdb.vm import Unavailable  # noqa: E402

PERSON_PRIMARY = {'ACTUAL_PLAYER': 0x388, 'ACTUAL_PLAYER_AND_NON_PLAYER': 0x480}
STAFF_PRIMARY = {'ACTUAL_NON_PLAYER': 0x208, 'HUMAN_NON_PLAYER': 0x548, 'ACTUAL_PLAYER_AND_NON_PLAYER': 0x480}
MAX_EXAMPLES = 5


# ---------------------------------------------------------------------------------------
# Live session
# ---------------------------------------------------------------------------------------

class Live:
    """Bridge + VM + catalog, with record sampling and handle registration."""

    def __init__(self):
        from fm_live_mcp import database, players, world
        from fm_live_mcp.fmdb import catalog, tables
        from fm_live_mcp.fmdb.image import PluginImage
        from fm_live_mcp.fmdb.live import open_live
        from fm_live_mcp.fmdb.vm import PropertyVM
        self.database, self.players, self.world, self.tables = database, players, world, tables
        self.session = open_live()
        self.bridge = self.session.bridge
        self.sid = self.bridge.session
        self.read = self.session.reader.read
        self.base = self.session.base
        self.image = PluginImage.load(self.session.plugin_path)
        self.vm = PropertyVM(self.session.reader, self.base, self.image,
                             file_resolver=self.session.file_resolver())
        self.catalog = catalog.load_catalog_for_plugin(self.session.plugin_path)
        self._entries = {}
        self._classes = {}
        self._uid = {}
        self.vm_calls = 0

    def close(self):
        self.session.close()

    # -- environment ----------------------------------------------------------------
    def process(self):
        return self.bridge._current(self.sid)

    def layout(self):
        return self.bridge._player_layout(self.process())

    def snapshot(self):
        return self.bridge._world_state(self.process(), self.layout())[0]

    def game_date(self):
        return self.bridge.get_save(self.sid)['save']['current_date']

    def table_entries(self, kind):
        if kind not in self._entries:
            self._entries[kind] = self.tables.entries(self.read, self.base, kind)
        return self._entries[kind]

    # -- generic reader ---------------------------------------------------------------
    def prop(self, address, code):
        self.vm_calls += 1
        if code.startswith('x:'):          # extras.DERIVED field (native getter slot / proven layout)
            from fm_live_mcp.fmdb import extras
            return extras.read_derived(self.vm, address, code[2:])
        return self.vm.get_property(address, code)

    def uid_index(self, kind):
        if kind not in self._uid:
            self._uid[kind] = self.tables.unique_id_index(self.read, self.base, kind)
        return self._uid[kind]

    # -- sampling ---------------------------------------------------------------------
    def pick(self, kind, count, rng, classes=None):
        """Random table indices (all of them when count <= 0); the class filter is applied lazily."""
        entries = self.table_entries(kind)
        pool = [i for i, p in enumerate(entries) if p]
        rng.shuffle(pool)
        out = []
        for i in pool:
            if classes and self.tables.class_of(self.read, self.base, entries[i])[0] not in classes:
                continue
            out.append(i)
            if 0 < count == len(out):
                break
        return out

    # -- handle registration --------------------------------------------------------------
    def register(self, sample, index):
        """Register a tool reference for table entry `index`; returns (ref, generic record address)."""
        with self.bridge.lock, self.bridge._read_scope(self.sid):
            return self._register(sample, index)

    def _register(self, sample, index):
        b = self.bridge
        base, tables = self.base, self.layout()
        snapshot = self.snapshot()
        ref = secrets.token_urlsafe(12)
        if sample == 'player':
            person = self.table_entries('people')[index]
            cls = self.tables.class_of(self.read, base, person)[0]
            primary = person - PERSON_PRIMARY[cls]
            _, identity = self.players.decode(snapshot, primary, tables)
            b.player_refs[ref] = {'address': primary, 'identity': identity, 'tables': tables, 'world_bound': True,
                                  'database_index': index}
            return ref, person
        if sample == 'staff':
            person = self.table_entries('people')[index]
            cls = self.tables.class_of(self.read, base, person)[0]
            primary = person - STAFF_PRIMARY[cls]
            from fm_live_mcp import staff as staff_module
            _, identity = staff_module.decode(snapshot, base, primary)
            b.staff_refs[ref] = {'address': primary, 'identity': identity, 'tables': tables, 'world_bound': True,
                                 'database_index': index}
            return ref, person
        address = self.table_entries({'club': 'clubs', 'competition': 'competitions', 'stadium': 'stadiums',
                                      'city': 'cities', 'currency': 'currencies'}[sample])[index]
        if sample == 'club':
            _, identity = self.world.club(snapshot, base, address)
            b.club_refs[ref] = {'address': address, 'identity': identity, 'tables': tables, 'world_bound': True,
                                'database_index': index}
        elif sample == 'competition':
            from fm_live_mcp import competitions
            row = competitions.by_index(snapshot, base, index, include_context=True)
            b.competition_refs[ref] = {'tables': tables, 'database_index': index, 'address': address,
                                       'native_id': row['native_id'], 'random_id': row.get('random_id')}
        else:
            module = importlib.import_module({'stadium': 'fm_live_mcp.stadiums', 'city': 'fm_live_mcp.cities',
                                              'currency': 'fm_live_mcp.currencies'}[sample])
            _, binding = module.by_index(snapshot, base, index)
            getattr(b, f'{sample}_refs')[ref] = {**binding, 'tables': tables}
        return ref, address

    def managed_players(self):
        """Managed-squad subjects: (ref, person address) from the tool's own roster refs."""
        squad = self.bridge.get_managed_squad(self.sid)
        out = []
        with self.bridge.lock, self.bridge._read_scope(self.sid):
            tables = self.layout()
            for row in squad['players']:
                binding = self.bridge.player_refs[row['player_ref']]
                offset = self.players.person_offset(self.read, binding['address'], tables)
                out.append((row['player_ref'], binding['address'] + offset))
        return out

    # -- tool calls -------------------------------------------------------------------------
    def call(self, call: om.Call, ref):
        kwargs = call.arguments()
        kwargs[call.ref_kwarg] = ref
        if ':' in call.method:
            module, _, name = call.method.partition(':')
            fn = getattr(importlib.import_module(module), name)
            result = fn(self.bridge, self.sid, **kwargs)
        else:
            result = getattr(self.bridge, call.method)(self.sid, **kwargs)
        return om.get_path(result, call.root)


class LiveContext(om.Context):
    def __init__(self, live: Live):
        self.live = live

    @staticmethod
    def _ref(ref):
        if getattr(ref, 'unique_id', None) is None or getattr(ref, 'table', None) is None:
            raise LookupError(f'not a record reference: {ref!r}')
        return ref

    def resolve_uid(self, ref):
        return self._ref(ref).unique_id

    def resolve_name(self, ref, kind):
        ref = self._ref(ref)
        table, code = om.REF_KINDS[kind]
        hit = self.live.uid_index(table).get(ref.unique_id)
        if hit is None:
            note = ' (reserve or youth team record; the editor schema has no team-to-club link)' \
                if ref.table == 'Ttea' and ref.unique_id >= 2_000_000_000 else ''
            raise LookupError(f'{ref.table} {ref.unique_id} not found in {table}{note}')
        result = self.live.prop(hit[1], code)
        if isinstance(result.value, Unavailable):
            raise LookupError(f'name unavailable: {result.value.reason}')
        return result.value or ''

    def resolve_index_name(self, kind, index):
        table, code = om.REF_KINDS[kind]
        entries = self.live.table_entries(table)
        if not 0 <= index < len(entries) or not entries[index]:
            raise LookupError(f'{table} index {index} out of range')
        result = self.live.prop(entries[index], code)
        if isinstance(result.value, Unavailable):
            raise LookupError(f'name unavailable: {result.value.reason}')
        return result.value or ''

    def enum_label(self, rtype, code, value):
        catalog = self.live.catalog
        fld = catalog.field(rtype, code)
        if fld is None:
            return None
        labels = fld.enum
        if labels is None and fld.enum_ref:
            labels = catalog.enums.get(fld.enum_ref)
        return (labels or {}).get(value)


# ---------------------------------------------------------------------------------------
# Comparison engine
# ---------------------------------------------------------------------------------------

def generic_value(result):
    """('value', v) | ('unavailable', reason) | ('unclaimed', reason) for a PropertyResult."""
    if isinstance(result.value, Unavailable):
        return 'unavailable', result.value.reason
    if result.kind == 'null' and not result.handled:
        return 'unclaimed', 'getter did not claim the key'
    return 'value', result.value


def show(value):
    if isinstance(value, (bytes, bytearray)):
        return f'blob:{bytes(value).hex()}'
    if hasattr(value, 'iso'):
        return value.iso
    if hasattr(value, 'unique_id'):
        return f'{value.table}:{value.unique_id}'
    if isinstance(value, float):
        return f'{value!r}'
    return value if isinstance(value, (int, str, bool, type(None), list, dict)) else repr(value)


def evaluate(live: Live, ctx: om.Context, entry: om.Entry, address: int, doc_by_call: dict):
    """Returns (status, tool_value, generic_display, detail)."""
    doc = doc_by_call.get(entry.call)
    tool = om.MISSING
    if isinstance(doc, Exception):
        tool = om.MISSING
    elif doc is not None:
        tool = om.get_path(doc, entry.path)
    target = address
    if entry.via:
        ref = live.prop(address, entry.via)
        state, value = generic_value(ref)
        if state != 'value':
            return 'generic_unavailable', None if tool is om.MISSING else tool, None, f'via {entry.via}: {value}'
        if value is None:
            return ('match' if tool in (om.MISSING, None) else 'mismatch'), (None if tool is om.MISSING else tool), \
                None, f'via {entry.via} null'
        try:
            kind = om.REF_FOURCC_KIND[value.table]
            hit = live.uid_index(om.REF_KINDS[kind][0]).get(value.unique_id)
        except (KeyError, AttributeError):
            return 'generic_unavailable', None, None, f'via {entry.via}: unresolved reference {value!r}'
        if hit is None:
            return 'generic_unavailable', None, None, f'via {entry.via}: {value!r} not in table'
        target = hit[1]
    gen, unavailable, unclaimed = {}, [], []
    for code in entry.codes:
        state, value = generic_value(live.prop(target, code))
        if state == 'unavailable':
            unavailable.append(f'{code}: {value}')
        elif state == 'unclaimed':
            unclaimed.append(code)
            value = None
        gen[code] = value
    tool_none = tool is om.MISSING or tool is None
    if unavailable:
        return 'generic_unavailable', None if tool is om.MISSING else tool, None, '; '.join(unavailable)
    if unclaimed:
        if tool_none:
            return 'match', None, None, 'tool absent and the getter does not claim the key'
        return 'generic_unavailable', tool, None, f'{",".join(unclaimed)}: getter did not claim the key'
    display = {c: show(v) for c, v in gen.items()}
    shown = next(iter(display.values())) if len(display) == 1 else display
    if tool_none:
        values = list(gen.values())
        absent = all(v is None or v == '' or v == {} or v == [] for v in values)
        if absent:
            return 'match', None, shown, 'both absent'
        if (entry.param('none_if_negative') and len(values) == 1 and isinstance(values[0], (int, float))
                and not isinstance(values[0], bool) and values[0] < 0):
            return 'match', None, shown, 'tool null for negative native code'
        if entry.rule in ('unset', 'date_unset', 'empty_as_null'):
            ok, detail = om.compare(entry, tool if tool is not om.MISSING else None, gen, ctx)
            return ('match' if ok else 'mismatch'), None, shown, detail
        return 'tool_unavailable', None, shown, 'tool field absent' if tool is om.MISSING else 'tool value null'
    try:
        ok, detail = om.compare(entry, tool, gen, ctx)
    except LookupError as exc:
        return 'generic_unavailable', tool, shown, f'resolution: {exc}'
    except (TypeError, ValueError) as exc:
        return 'mismatch', tool, shown, f'rule error: {exc}'
    return ('match' if ok else 'mismatch'), tool, shown, detail


class Tally:
    def __init__(self):
        self.fields = {}
        self.records = Counter()
        self.tool_errors = Counter()
        self.recovered = Counter()

    def add(self, entry, status, label, tool, gen, detail):
        row = self.fields.setdefault(entry.key, {
            'family': entry.family, 'field': entry.field, 'call': entry.call, 'path': entry.path,
            'rtype': entry.rtype, 'codes': list(entry.codes), 'rule': entry.rule,
            'sample': entry.sample_family, 'via': entry.via,
            **{s: 0 for s in om.STATUSES}, 'examples': [], 'generic_reasons': {}})
        row[status] += 1
        if status == 'mismatch' and len(row['examples']) < MAX_EXAMPLES:
            row['examples'].append({'record': label, 'tool': show(tool), 'generic': gen, 'detail': detail})
        if status == 'generic_unavailable':
            reason = (detail or '').split(':', 1)[-1].strip()[:80] or 'unknown'
            row['generic_reasons'][reason] = row['generic_reasons'].get(reason, 0) + 1


def run_subject(live, ctx, tally, sample, ref, address, label, entries, retry=True):
    calls = sorted({e.call for e in entries})
    docs = {}
    for key in calls:
        try:
            docs[key] = live.call(om.CALLS[key], ref)
        except Exception as exc:  # noqa: BLE001 - tool refusal is data
            docs[key] = exc
            tally.tool_errors[f'{key}: {type(exc).__name__}: {str(exc)[:100]}'] += 1
    first = {e.key: evaluate(live, ctx, e, address, docs) for e in entries}
    redo = [e for e in entries if first[e.key][0] == 'mismatch']
    final = dict(first)
    if redo and retry:
        live.vm.invalidate()
        for key in {e.call for e in redo}:
            try:
                docs[key] = live.call(om.CALLS[key], ref)
            except Exception as exc:  # noqa: BLE001
                docs[key] = exc
        for e in redo:
            second = evaluate(live, ctx, e, address, docs)
            final[e.key] = second
            if second[0] == 'match':
                tally.recovered[e.key] += 1
    for e in entries:
        status, tool, gen, detail = final[e.key]
        tally.add(e, status, label, tool, gen, detail)
    tally.records[sample] += 1


def run(args) -> dict:
    started = time.time()
    live = Live()
    try:
        ctx = LiveContext(live)
        rng = random.Random(args.seed)
        tally = Tally()
        meta = {'seed': args.seed, 'started': datetime.now(timezone.utc).isoformat(),
                'game_date_start': live.game_date(), 'sizes': {}, 'sample_indices': {}}
        wanted = set(args.samples.split(',')) if args.samples else set(om.SAMPLES)
        plan = []
        if 'player' in wanted:
            if not args.no_managed:
                for ref, person in live.managed_players()[:getattr(args, 'managed_limit', None)]:
                    plan.append(('player', ref, person, 'managed squad'))
            for index in live.pick('people', args.players, rng, classes={'ACTUAL_PLAYER', 'ACTUAL_PLAYER_AND_NON_PLAYER'}):
                plan.append(('player', index, None, 'random'))
        if 'staff' in wanted:
            for index in live.pick('people', args.staff, rng,
                                   classes={'ACTUAL_NON_PLAYER', 'HUMAN_NON_PLAYER', 'ACTUAL_PLAYER_AND_NON_PLAYER'}):
                plan.append(('staff', index, None, 'random'))
        if 'club' in wanted and not args.no_managed:
            clubs_table = live.table_entries('clubs')
            for address in live.tables.managed(live.read, live.base)[0]:
                plan.append(('club', clubs_table.index(address), None, 'random'))
        for sample, kind, count, classes in (('club', 'clubs', args.clubs, {'CLUB'}),
                                             ('competition', 'competitions', args.competitions, None),
                                             ('stadium', 'stadiums', args.stadiums, None),
                                             ('city', 'cities', args.cities, None),
                                             ('currency', 'currencies', args.currencies, None)):
            if sample in wanted:
                for index in live.pick(kind, count, rng, classes):
                    plan.append((sample, index, None, 'random'))
        by_sample = {s: [e for e in om.ENTRIES if e.sample_family == s] for s in om.SAMPLES}
        done = Counter()
        for sample, handle, person, origin in plan:
            entries = by_sample[sample]
            try:
                if origin == 'managed squad':
                    ref, address, index = handle, person, None
                else:
                    ref, address = live.register(sample, handle)
                    index = handle
            except Exception as exc:  # noqa: BLE001
                tally.tool_errors[f'register {sample}: {type(exc).__name__}: {str(exc)[:100]}'] += 1
                continue
            label = f'{sample}[{index}]' if index is not None else f'{sample} managed {address:#x}'
            run_subject(live, ctx, tally, sample, ref, address, label, entries)
            done[sample] += 1
            if sum(done.values()) % 50 == 0:
                live.vm.invalidate()          # drop cached live pages so long runs do not read stale memory
            meta['sample_indices'].setdefault(sample, []).append(index if index is not None else f'managed:{address:#x}')
            if sum(done.values()) % 25 == 0:
                print(f'  {dict(done)}  vm calls {live.vm_calls}', file=sys.stderr, flush=True)
        meta['sizes'] = dict(done)
        meta['game_date_end'] = live.game_date()
        meta['elapsed_seconds'] = round(time.time() - started, 1)
        meta['vm_calls'] = live.vm_calls
        meta['plugin'] = str(live.session.plugin_path)
        return build_report(tally, meta)
    finally:
        live.close()


def build_report(tally: Tally, meta: dict) -> dict:
    fields = {}
    for key, row in tally.fields.items():
        row = dict(row)
        row['recovered_on_retry'] = tally.recovered.get(key, 0)
        finding = om.FINDINGS.get(key) or om.FINDINGS.get(row['family'] + '.*')
        row['finding'] = {'class': finding[0], 'reading': finding[1]} if finding else None
        fields[key] = row
    families = {}
    for row in fields.values():
        fam = families.setdefault(row['family'], {s: 0 for s in om.STATUSES})
        for s in om.STATUSES:
            fam[s] += row[s]
    return {'meta': meta, 'tool_errors': dict(tally.tool_errors), 'families': families, 'fields': fields,
            'unmapped': [u.__dict__ for u in om.UNMAPPED], 'tool_gaps': [g.__dict__ for g in om.TOOL_GAPS]}


def refresh_findings(report: dict) -> None:
    """Re-apply FINDINGS, UNMAPPED and TOOL_GAPS from the map to a stored report."""
    for key, row in report['fields'].items():
        finding = om.FINDINGS.get(key) or om.FINDINGS.get(row['family'] + '.*')
        row['finding'] = {'class': finding[0], 'reading': finding[1]} if finding else None
    report['unmapped'] = [u.__dict__ for u in om.UNMAPPED]
    report['tool_gaps'] = [g.__dict__ for g in om.TOOL_GAPS]


# ---------------------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------------------

def pct(row):
    compared = row['match'] + row['mismatch']
    return f"{100 * row['match'] / compared:.1f}%" if compared else '-'


def render_markdown(report: dict) -> str:
    meta = report['meta']
    lines = ['# Differential oracle: generic reader against the existing tools', '',
             f"Generated by `scripts/fmdb_oracle.py`. Game date {meta['game_date_start']}"
             + (f" (end {meta['game_date_end']})" if meta.get('game_date_end') != meta['game_date_start'] else '')
             + f"; seed {meta['seed']}; records per sample {meta['sizes']}; {meta['elapsed_seconds']} s; "
             f"{meta['vm_calls']:,} VM calls.", '',
             'Statuses per (record, field): `match`; `mismatch`; `generic-unavailable` (the VM could not produce a value, or '
             'the getter did not claim the key); `tool-unavailable` (tool field absent or null while the generic reader has a '
             'value). A tool null against a generic null counts as a match. A mismatching record is re-read once before it is '
             'recorded.', '']
    totals = {s: 0 for s in om.STATUSES}
    for fam in report['families'].values():
        for s in om.STATUSES:
            totals[s] += fam[s]
    lines += ['## Method', '',
              'For each sampled record the harness calls the existing tool (a `Bridge` method; the call and JSON path are in '
              '`fm_live_mcp/fmdb/oracle_map.py`) and reads the mapped editor code through `PropertyVM.get_property` '
              '(database view, reader thread). Tool references for random records are minted by registering the record in the '
              "Bridge's own reference table with the same decoders the finders use; every compared value then comes from the "
              "tool's normal `get_*` path. Reads are not atomic: a mismatching record is re-read (tool and VM, pages dropped) "
              'once before it is recorded, and the count recovered by that retry is kept in `report.json`. Random samples are '
              'seeded.', '', 'Rules:', '']
    lines += [f'* `{name}`: {doc}' for name, doc in om.RULE_DOC.items()]
    lines.append('')
    counts = Counter(r['family'] for r in report['fields'].values())
    lines += ['## Agreement by family', '', '| family | fields | match | mismatch | generic-unavail. | tool-unavail. | agreement |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for name, fam in report['families'].items():
        lines.append(f"| {om.FAMILY_TITLES.get(name, name)} (`{name}`) | {counts[name]} | {fam['match']} | {fam['mismatch']} | "
                     f"{fam['generic_unavailable']} | {fam['tool_unavailable']} | {pct(fam)} |")
    lines.append(f"| **all** | {len(report['fields'])} | {totals['match']} | {totals['mismatch']} | {totals['generic_unavailable']} | "
                 f"{totals['tool_unavailable']} | {pct(totals)} |")
    lines.append('')
    perfect = [k for k, r in report['fields'].items() if r['mismatch'] == 0 and r['match'] > 0
               and r['generic_unavailable'] == 0 and r['tool_unavailable'] == 0]
    lines += [f"{len(report['fields'])} mapped fields; {len(perfect)} at 100% agreement with every record compared "
              "(no unavailable results).", '']
    lines += ['## Fields', '']
    for name in report['families']:
        rows = [r for r in report['fields'].values() if r['family'] == name]
        lines += [f"### {om.FAMILY_TITLES.get(name, name)}", '',
                  '| field | tool path | code | rule | match | mismatch | gen-unavail. | tool-unavail. |',
                  '|---|---|---|---|---:|---:|---:|---:|']
        for r in rows:
            via = f" via `{r['via']}`" if r['via'] else ''
            lines.append(f"| {r['field']} | `{r['call']}:{r['path']}` | `{'+'.join(r['codes'])}`{via} | {r['rule']} | "
                         f"{r['match']} | {r['mismatch']} | {r['generic_unavailable']} | {r['tool_unavailable']} |")
        lines.append('')
    bad = [r for r in report['fields'].values() if r['mismatch']]
    lines += ['## Mismatches', '']
    if not bad:
        lines += ['None.', '']
    groups = {}
    for r in bad:
        finding = r['finding'] or {'class': 'undetermined', 'reading': 'Not yet analysed.'}
        groups.setdefault((finding['class'], finding['reading']), []).append(r)
    for number, ((klass, reading), rows) in enumerate(groups.items(), 1):
        lines += [f'### M{number}. {klass}', '', reading, '']
        lines += ['| field | mismatches / compared | examples (record: tool value, generic value) |', '|---|---:|---|']
        for r in rows:
            examples = '; '.join(f"{ex['record']}: `{ex['tool']}`, `{ex['generic']}`" + (f" ({ex['detail']})" if ex['detail'] else '')
                                 for ex in r['examples'])
            lines.append(f"| `{r['family']}.{r['field']}` | {r['mismatch']} / {r['match'] + r['mismatch']} | "
                         f"{examples.replace('|', '/')} |")
        lines.append('')
    unavailable = [r for r in report['fields'].values() if r['generic_unavailable']]
    lines += ['## Generic reader unavailable', '']
    if not unavailable:
        lines += ['None.', '']
    else:
        lines += ['| field | count | reasons |', '|---|---:|---|']
        for r in unavailable:
            merged = {}
            for reason, count in r['generic_reasons'].items():
                key = re.sub(r'\d{4,}', 'N', reason)
                merged[key] = merged.get(key, 0) + count
            reasons = '; '.join(f'{k} ({v})' for k, v in sorted(merged.items(), key=lambda kv: -kv[1])[:3])
            lines.append(f"| `{r['family']}.{r['field']}` | {r['generic_unavailable']} | {reasons} |")
        lines.append('')
    tool_missing = [r for r in report['fields'].values() if r['tool_unavailable']]
    lines += ['## Tool unavailable', '']
    if not tool_missing:
        lines += ['None.', '']
    else:
        lines += ['| field | count | why |', '|---|---:|---|']
        lines += [f"| `{r['family']}.{r['field']}` | {r['tool_unavailable']} | "
                  f"{om.TOOL_UNAVAILABLE.get(r['family'] + '.' + r['field'], om.TOOL_UNAVAILABLE.get(r['family'] + '.*', ''))} |"
                  for r in tool_missing]
        lines.append('')
    lines += ['## Hand-built tool fields without an established editor code', '']
    if report['unmapped']:
        lines += ['| family | field | tool | tried | reason |', '|---|---|---|---|---|']
        lines += [f"| {u['family']} | {u['field']} | {u['tool']} | {u['tried']} | {u['reason']} |"
                  for u in report['unmapped']]
    else:
        lines.append('None.')
    lines += ['', '## Generic fields the existing tools do not expose', '']
    if report['tool_gaps']:
        lines += ['| family | code | name | note |', '|---|---|---|---|']
        lines += [f"| {g['family']} | `{g['code']}` | {g['name']} | {g['reason']} |" for g in report['tool_gaps']]
    else:
        lines.append('None.')
    if report['tool_errors']:
        lines += ['', '## Tool errors during the run', '']
        lines += [f'* {k}: {v}' for k, v in report['tool_errors'].items()]
    lines += ['', '## Limits of this comparison', '',
              '* Both readers read live memory; neither is an independent ground truth. Agreement shows two decoders reach the '
              'same value; disagreement is classified from the code paths, not from the game UI. No UI comparison was made.',
              '* Families outside the list above are not compared: languages, local regions, weather, injuries as records, media '
              'sources, stadium changes, fixtures, stages, standings, registrations, tactics, training, transfers, match data.',
              '* The sample is a seeded random draw from one save (Newcastle United, December 2030): the managed squad plus random '
              'records. Rare shapes (negative potential, dynamic expiry, basic contracts, virtual players) are barely or not '
              'sampled, and virtual players are not sampled at all (the tools support them only partially).',
              '* The record handle for random records is registered in the Bridge reference table by the harness (see Method); '
              'the tools\' own finder-to-ref path was used only for the managed squad.',
              '* `Pcjo`, `injr`, `Papr` and `DELE` are not editor fields; they were taken from the tools\' own research notes or '
              'found by case variation and kept only where they agree with the tool on the sample.',
              '* `staff.contract.club_name` shows no mismatch in the full run but the live test sample hit the same B-team case '
              'as `player.club.*` (a staff member at `Les Voltigeurs de Châteaubriant 2`), so it is not pinned.',
              '* Float comparisons are bit-exact on float32.']
    return '\n'.join(lines) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--players', type=int, default=100)
    ap.add_argument('--clubs', type=int, default=50)
    ap.add_argument('--competitions', type=int, default=50)
    ap.add_argument('--stadiums', type=int, default=50)
    ap.add_argument('--cities', type=int, default=50)
    ap.add_argument('--currencies', type=int, default=0, help='0 = all')
    ap.add_argument('--staff', type=int, default=50)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--no-managed', action='store_true')
    ap.add_argument('--managed-limit', type=int, default=None, help='use only the first N managed-squad players')
    ap.add_argument('--samples', default='')
    ap.add_argument('--out', default=str(ROOT / 'out/fmdb-oracle/report.json'))
    ap.add_argument('--markdown', default='')
    ap.add_argument('--from-report', default='', help='re-render --markdown from an existing report.json (no game access)')
    args = ap.parse_args(argv)
    if args.from_report:
        report = json.loads(Path(args.from_report).read_text())
        refresh_findings(report)
        Path(args.markdown).write_text(render_markdown(report))
        return 0
    report = run(args)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1, default=str))
    if args.markdown:
        Path(args.markdown).write_text(render_markdown(report))
    totals = {s: sum(f[s] for f in report['families'].values()) for s in om.STATUSES}
    print(json.dumps({'sizes': report['meta']['sizes'], 'totals': totals, 'tool_errors': report['tool_errors']}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
