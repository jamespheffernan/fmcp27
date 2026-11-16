"""Same answers with and without the free-list models (ui_vm.FREE_LIST_SITES).

Two differentials, both on one frozen copy of live memory (pages copied from the game once and
then served unchanged to both runs), so a difference can only come from the models:

* handlers: scripts/fmdb_ui_vm_check.py with its reference emulator replaced by the accelerated
  emulator with the models off (FMDB_UI_FREE_LISTS=0): every handler type of the sweep, every
  input transfer and every client key, compared field by field as that script does.
* recipes: every shaped screen tool of scripts/fmdb_ui_bench.py through the function behind the
  MCP tool (`fresh=true`), once with the models and once without, each on a new emulator; the
  answers are compared as JSON with timing, cache and instruction-count fields left out.

  PYTHONPATH=. python scripts/fmdb_ui_freelist_check.py handlers [fmdb_ui_vm_check options]
  PYTHONPATH=. python scripts/fmdb_ui_freelist_check.py recipes [--tools board,inbox] [--out file.json]

Read-only against the game. Uses FMCP_CACHE_DIR (set it to a scratch directory).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

VOLATILE = {'cache', 'seconds', 'elapsed_s', 'timing', 'instructions', 'insns', 'computed_at', 'computed_at_unix',
            'age_seconds', 'checked_at', 'served_without_second_read', 'read_set', 'emulator', 'vm', 'stats', 'cpu_s', 'wall_s',
            'ms', 'cpu_seconds', 'list_cpu_seconds'}


class _ModelsOff:
    def __enter__(self):
        self.old = os.environ.get('FMDB_UI_FREE_LISTS')
        os.environ['FMDB_UI_FREE_LISTS'] = '0'

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop('FMDB_UI_FREE_LISTS', None)
        else:
            os.environ['FMDB_UI_FREE_LISTS'] = self.old


def handlers(argv):
    from fm_live_mcp.fmdb import ui_vm
    import fmdb_ui_vm_check as check

    # --control: both runs with the models (on) or both without (off), to see what differs by itself
    control = None
    if '--control' in argv:
        at = argv.index('--control')
        control, argv = argv[at + 1], argv[:at] + argv[at + 2:]

    def without_models(cls, *args, **kwargs):
        if control == 'on':
            return ui_vm.UiHandlerVM(*args, **kwargs)
        with _ModelsOff():
            vm = ui_vm.UiHandlerVM(*args, **kwargs)
        assert not vm.free_list_sites
        return vm
    ui_vm.UiHandlerVM.classic = classmethod(without_models)
    if control == 'off':
        os.environ['FMDB_UI_FREE_LISTS'] = '0'
    if '--out' not in argv:
        argv = list(argv) + ['--out', str(ROOT / 'out' / 'fmdb-ui-freelist-check')]
    return check.main(argv)


def scrub(value, path=''):
    """The answer without fields that differ between two computations of the same bytes."""
    if isinstance(value, dict):
        return {k: scrub(v, f'{path}.{k}') for k, v in sorted(value.items()) if k not in VOLATILE}
    if isinstance(value, list):
        return [scrub(v, path) for v in value]
    if isinstance(value, str) and ' insns)' in value:          # 'ok (data, server 131189515 insns)'
        return value.split(' insns)')[0].rsplit(' ', 1)[0] + ' insns)'
    return value


def diff(a, b, path='', out=None, cap=20):
    out = [] if out is None else out
    if len(out) >= cap:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            diff(a.get(k, '<absent>'), b.get(k, '<absent>'), f'{path}.{k}', out, cap)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f'{path}[{i}]', out, cap)
    elif a != b:
        out.append((path, str(a)[:160], str(b)[:160]))
    return out


def recipes(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--tools', help='comma-separated substrings of tool names')
    ap.add_argument('--out', default=str(ROOT / 'out' / 'fmdb-ui-freelist-check' / 'recipes.json'))
    args = ap.parse_args(argv)
    if not os.environ.get('FMCP_CACHE_DIR'):
        raise SystemExit('set FMCP_CACHE_DIR to a scratch directory')
    from fm_live_mcp.bridge import Bridge
    from fm_live_mcp.fmdb import ui_tools
    import fmdb_ui_bench as bench
    from fmdb_ui_vm_check import FrozenReader
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    session = ui_tools.session_for(bridge, sid)
    frozen = FrozenReader(session.memory)
    frozen.close = lambda: None
    session.memory = frozen
    wanted = [w for w in (args.tools or '').split(',') if w]
    rows, totals = [], {'tools': 0, 'same': 0, 'different': 0, 'errors': 0}
    try:
        for name, call in bench.tool_table(bridge, sid, ui_tools):
            if wanted and not any(w in name for w in wanted):
                continue
            answers, cost, sites = {}, {}, {}
            for kind in ('on', 'off'):
                session._vms.clear()
                t0, c0 = time.perf_counter(), time.process_time()
                try:
                    if kind == 'off':
                        with _ModelsOff():
                            out = call(True)
                    else:
                        out = call(True)
                    answers[kind] = scrub(json.loads(json.dumps(out, default=str)))
                except Exception as exc:  # noqa: BLE001 - a failing tool is compared by its error
                    answers[kind] = {'error': f'{type(exc).__name__}: {exc}'[:300]}
                cost[kind] = (round(time.perf_counter() - t0, 2), round(time.process_time() - c0, 2))
                vms = [entry['vm'] for entry in session._vms.values()]
                sites[kind] = sum(sum(n for k, n in getattr(v, 'intercepted', {}).items()
                                      if k not in ('pool_alloc', 'pool_free', 'fixed_pool_alloc')) for v in vms)
            differences = diff(answers['on'], answers['off'])
            error = 'error' in answers['on'] or 'error' in answers['off']
            totals['tools'] += 1
            totals['different' if differences else 'same'] += 1
            totals['errors'] += error
            rows.append({'tool': name, 'different': len(differences), 'differences': differences,
                         'site_calls_on': sites['on'], 'site_calls_off': sites['off'], 'wall_cpu_s': cost,
                         'error': answers['on'].get('error') if error else None})
            print(f"{name:34s} {'DIFFERENT' if differences else 'same':9s} site calls {sites['on']:7d} / "
                  f"{sites['off']:d}  on {cost['on'][0]:6.2f}s off {cost['off'][0]:6.2f}s"
                  + (f"  ERROR {rows[-1]['error']}" if error else ''), flush=True)
            for d in differences[:3]:
                print('     ', d, flush=True)
    finally:
        bridge.detach()
    summary = {'totals': totals, 'load': round(os.getloadavg()[0], 1), 'rows': rows}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(totals), 'load', summary['load'])
    return 1 if totals['different'] else 0


if __name__ == '__main__':
    mode, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ('recipes', [])
    sys.exit(handlers(rest) if mode == 'handlers' else recipes(rest))
