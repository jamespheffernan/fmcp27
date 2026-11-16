"""Check that FastUiHandlerVM gives the same answers as the Python-hooked UiHandlerVM.

The UI counterpart of scripts/fmdb_vm_check.py. For every handler type of the sweep
(scripts/fmdb_ui_sweep.py: each buildable factory type and each class DATABASE_RECORD
dispatches to, with the same UI_RECORD bindings and profiles) both emulators build the
handler, transfer its inputs and read every client key through `ui_recipes_more.KeyReader`.
Both read the same frozen copy of live memory (pages are copied from the game once, on first
use by either, and then served to both), so any difference is a difference between the
emulators. Compared per handler: client/server class or build error (reason); per input: the
transfer status (value kind or stop reason); per key: status, value kind, decoded value,
protocol, server keys, stop reason, failed server keys and the number of random draws.

Not compared: instruction counts (the reference does not count in fast() mode), timings,
backtraces and the `detail` of a refusal (the accelerated VM names the 1 KiB block Unicorn
asked for; see fastvm.py).

  PYTHONPATH=. python scripts/fmdb_ui_vm_check.py [--types 114,70] [--max-keys N]
      [--profiles first|all] [--limit 1000000000] [--out out/fmdb-ui-vm-check]

Read-only against the game: shipped code runs in this process on copied bytes.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

PAGE16 = 0x4000


class FrozenReader:
    """Live memory copied once per 16 KiB page and then served unchanged (to both emulators)."""

    def __init__(self, memory):
        self.memory, self.pid = memory, memory.pid
        self.pages, self.bad = {}, {}

    def _need(self, bases):
        missing = [b for b in bases if b not in self.pages and b not in self.bad]
        if missing:
            for base, (status, data) in zip(missing, self.memory.read_many_status([(b, PAGE16) for b in missing])):
                if data is None or len(data) != PAGE16:
                    self.bad[base] = status
                else:
                    self.pages[base] = data

    def _get(self, address, length):
        first, last = address & ~(PAGE16 - 1), (address + max(length, 1) - 1) & ~(PAGE16 - 1)
        bases = range(first, last + 1, PAGE16)
        self._need(bases)
        for base in bases:
            if base in self.bad:
                return self.bad[base], None
        if first == last:
            return 0, self.pages[first][address - first:address - first + length]
        data = b''.join(self.pages[b] for b in bases)
        return 0, data[address - first:address - first + length]

    def read(self, address, length):
        from fm_live_mcp.fmdb.memory import MemoryReadError, status_name
        status, data = self._get(address, length)
        if data is None:
            raise MemoryReadError(f'cannot read {length} bytes at {address:#x}: {status_name(status)}', status)
        return data

    def read_many_status(self, requests):
        bases = set()
        for address, length in requests:
            bases.update(range(address & ~(PAGE16 - 1), address + max(length, 1), PAGE16))
        self._need(sorted(bases))
        return [self._get(address, length) for address, length in requests]

    def thaw(self):
        self.pages.clear()
        self.bad.clear()


_HEX = re.compile(r'0x[0-9a-fA-F]+')


def norm_status(text):
    """Transfer status without instruction counts, backtrace and addresses."""
    text = str(text)
    text = re.sub(r', server \d+ insns\)', ')', text)
    text = re.sub(r' after \d+ insns.*', '', text, flags=re.S)
    return _HEX.sub('0x_', text).strip()


def norm_reason(text):
    text = re.sub(r' after \d+ insns.*', '', str(text or ''), flags=re.S)
    return _HEX.sub('0x_', text).strip()


def comparable(result):
    """The parts of a sweep `attempt` result both emulators must agree on."""
    out = {'client': result.get('client'), 'server': result.get('server'),
           'build_error': norm_reason(result['build_error']) if result.get('build_error') else None,
           'inputs': {k: norm_status(v) for k, v in (result.get('inputs') or {}).items()}, 'keys': {}}
    for code, row in (result.get('keys') or {}).items():
        out['keys'][code] = {
            'status': row.get('status'), 'kind': row.get('kind'), 'value': row.get('value'),
            'protocol': row.get('protocol'), 'server_keys': row.get('server_keys'),
            'reason': norm_reason(row['reason']) if row.get('reason') else None,
            'failed': {k: norm_reason(v) for k, v in (row.get('failed') or {}).items()},
            'rng_uses': row.get('rng_uses', 0), 'params': row.get('params')}
    return out


def compare(a, b):
    """[(where, classic, fast)] for every difference."""
    diffs = []
    for field in ('client', 'server', 'build_error'):
        if a[field] != b[field]:
            diffs.append((field, a[field], b[field]))
    for name in sorted(set(a['inputs']) | set(b['inputs'])):
        if a['inputs'].get(name) != b['inputs'].get(name):
            diffs.append((f'input {name}', a['inputs'].get(name), b['inputs'].get(name)))
    for code in sorted(set(a['keys']) | set(b['keys'])):
        x, y = a['keys'].get(code), b['keys'].get(code)
        if x != y:
            fields = [f for f in (x or y) if (x or {}).get(f) != (y or {}).get(f)]
            diffs.append((f'key {code} [{",".join(fields)}]', {f: (x or {}).get(f) for f in fields},
                          {f: (y or {}).get(f) for f in fields}))
    return diffs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--types', help='comma-separated job ids (e.g. 114,70,28:PERSON_UI_HANDLER)')
    ap.add_argument('--max-keys', type=int, default=0)
    ap.add_argument('--profiles', choices=('first', 'all'), default='first')
    ap.add_argument('--limit', type=int, default=1_000_000_000, help='instructions per call (0: none)')
    ap.add_argument('--out', default=str(ROOT / 'out' / 'fmdb-ui-vm-check'))
    ap.add_argument('--resume', action='store_true')
    args = ap.parse_args(argv)
    import fmdb_ui_sweep as sweep
    from fm_live_mcp.fmdb import ui_registry
    from fm_live_mcp.fmdb.image import PluginImage
    from fm_live_mcp.fmdb.live import open_live
    from fm_live_mcp.fmdb.memory import LiveMemory
    from fm_live_mcp.fmdb.ui_handlers import input_keys
    from fm_live_mcp.fmdb.ui_recipes_more import install_param_trace
    from fm_live_mcp.fmdb.ui_vm import UiHandlerVM, lsof_resolver

    out_dir = Path(args.out)
    (out_dir / 'types').mkdir(parents=True, exist_ok=True)
    reg = ui_registry.default()
    session = open_live()
    image = PluginImage.load(session.plugin_path)
    memory = LiveMemory(session.pid)
    frozen = FrozenReader(memory)
    resolver = lsof_resolver(session.pid)

    def make(kind):
        build = UiHandlerVM.classic if kind == 'classic' else UiHandlerVM
        vm = build(frozen, session.base, image, file_resolver=resolver, rng='copy')
        vm.fast()
        if args.limit:
            vm.limit_instructions(args.limit)
        install_param_trace(vm)
        return vm

    try:
        if type(make('fast')).__name__ != 'FastUiHandlerVM':
            raise SystemExit('the UI accelerator library is not available (scripts/build_ui_accel.sh)')
        started = time.time()
        vm = make('fast')
        bindings = sweep.collect_bindings(session, vm)
        tables = sweep.dref_classes_with(vm) if hasattr(sweep, 'dref_classes_with') else None
        if tables is None:
            from fm_live_mcp.fmdb.vm import _Stop
            tables = {}
            for table in range(0x3B):
                try:
                    h = vm.build(28, {'dref': table << 24}, server=True)
                    tables[table] = {'client': h.client_class, 'server': h.server_class}
                except _Stop as stop:
                    tables[table] = {'error': stop.reason}
        del vm
        (out_dir / 'bindings.json').write_text(json.dumps(bindings, indent=1, default=str))
        wanted = set(args.types.split(',')) if args.types else None
        ctx, profs = sweep.context(bindings), sweep.profiles(bindings)
        totals = Counter()
        seconds = Counter()
        for job_id, number, client_class, keys, table in sweep.jobs(reg, tables):
            if wanted and job_id not in wanted:
                continue
            path = out_dir / 'types' / (job_id.replace(':', '_') + '.json')
            if args.resume and path.exists():
                row = json.loads(path.read_text())
            else:
                if args.max_keys:
                    keys = keys[:args.max_keys]
                if table is not None:
                    which = sweep.DREF_OBJECTS.get(client_class)
                    dref = bindings.get(which) if which and bindings.get(which) else table << 24
                    records = [('dref', dict(ctx, dref=dref))]
                else:
                    row_ = reg.types[number]
                    fourccs = set(input_keys(reg, client_class))
                    server = reg.classes.get(row_.get('server') or '')
                    if server:
                        fourccs |= set(server.slots.get('2', {}).get('fourccs', ()))
                    names = sweep.relevant_profiles(fourccs, profs)
                    if args.profiles == 'first':
                        names = names[:1]
                    records = [(name, dict(ctx, **profs[name])) for name in names]
                row = {'job': job_id, 'class': client_class, 'records': []}
                frozen.thaw()
                for name, record in records:
                    results, cost = {}, {}
                    for kind in ('classic', 'fast'):
                        vm = make(kind)
                        t0, c0 = time.perf_counter(), time.process_time()
                        results[kind] = sweep.attempt(
                            vm, number if table is None else 28, record, keys, deadline=time.time() + 86400,
                            call_us=3_600_000_000, reg=reg, dref_class=client_class if table is not None else None,
                            inputs=client_class not in sweep.NO_INPUTS)
                        cost[kind] = (round(time.perf_counter() - t0, 2), round(time.process_time() - c0, 2))
                        del vm
                    a, b = comparable(results['classic']), comparable(results['fast'])
                    diffs = compare(a, b)
                    cells = 1 + len(a['inputs']) + len(a['keys'])
                    row['records'].append({
                        'profile': name, 'cells': cells, 'inputs': len(a['inputs']), 'keys': len(a['keys']),
                        'counts': results['fast'].get('counts'), 'different': len(diffs),
                        'differences': [list(map(lambda v: json.loads(json.dumps(v, default=str)), d))
                                        for d in diffs[:40]],
                        'wall_cpu_s': cost})
                path.write_text(json.dumps(row, indent=1, default=str))
            for rec in row['records']:
                totals['handlers'] += 1
                totals['cells'] += rec['cells']
                totals['inputs'] += rec['inputs']
                totals['keys'] += rec['keys']
                totals['different'] += rec['different']
                totals['handlers_different'] += bool(rec['different'])
                for kind in ('classic', 'fast'):
                    seconds[kind + '_wall'] += rec['wall_cpu_s'][kind][0]
                    seconds[kind + '_cpu'] += rec['wall_cpu_s'][kind][1]
                mark = 'DIFFERENT' if rec['different'] else 'same'
                print(f"{row['job']:34s} {rec['profile']:16s} {rec['cells']:5d} cells {mark:9s} "
                      f"classic {rec['wall_cpu_s']['classic'][0]:7.1f}s fast {rec['wall_cpu_s']['fast'][0]:6.1f}s",
                      flush=True)
                for d in rec['differences'][:3]:
                    print('     ', json.dumps(d, default=str)[:300], flush=True)
        summary = {'totals': dict(totals), 'seconds': {k: round(v, 1) for k, v in seconds.items()},
                   'limit': args.limit, 'profiles': args.profiles, 'game_date': bindings.get('game_date'),
                   'elapsed_s': round(time.time() - started, 1), 'load': os.getloadavg()[0]}
        (out_dir / 'summary.json').write_text(json.dumps(summary, indent=1))
        print(json.dumps(summary))
        return 1 if totals['different'] else 0
    finally:
        memory.close()
        session.close()


if __name__ == '__main__':
    sys.exit(main())
