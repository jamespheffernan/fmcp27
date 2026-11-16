"""Profile UI handler reads on the running game: where the time of one screen goes.

Three representative reads (board confidence, inbox items, one player status), each on a
fresh emulator (cold) and again on the same emulator (warm). For every read the script
prints wall and CPU seconds, the phase split (handler construction, server input
computation, serialised transfer, per-key reads) and an exclusive-time split by mechanism
(emulation, page faults and mapping, baseline commit/restore, external models by name,
pool-allocator intercepts, value decoding, game-file reads).

  PYTHONPATH=. python scripts/fmdb_ui_profile.py [--vm classic|fast] [--reads board,inbox,player]
      [--inbox-unids 1,2] [--cprofile] [--json out.json]

Read-only against the game: shipped code runs in this process on copied bytes.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class Probe:
    """Exclusive wall time per label: a label's time excludes labelled calls nested in it."""

    def __init__(self):
        self.time, self.calls, self.stack, self.incl = Counter(), Counter(), [], Counter()

    def wrap(self, obj, name, label):
        fn = getattr(obj, name, None)
        if fn is None:
            return
        probe = self

        def wrapped(*args, **kwargs):
            key = label(*args) if callable(label) else label
            started = time.perf_counter()
            probe.stack.append(0.0)
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - started
                children = probe.stack.pop()
                probe.time[key] += elapsed - children
                probe.calls[key] += 1
                probe.incl[key] += elapsed
                if probe.stack:
                    probe.stack[-1] += elapsed
        setattr(obj, name, wrapped)

    def take(self):
        out = {k: (round(self.incl[k] if k.startswith('phase:') else self.time[k], 4), self.calls[k])
               for k in self.time}
        self.time, self.calls, self.incl = Counter(), Counter(), Counter()
        return out


def instrument(vm, probe):
    from fm_live_mcp.fmdb import ui_vm
    probe.wrap(vm, 'build', 'phase:build')
    probe.wrap(vm, 'server_value', 'phase:server_value')
    probe.wrap(vm, 'feed', 'phase:feed')
    probe.wrap(vm, 'get', 'phase:get')
    probe.wrap(vm, 'get_property', 'phase:get_property')
    probe.wrap(vm, 'call', 'call(other)')
    probe.wrap(vm, '_fault_in', 'fault_in')
    probe.wrap(vm, 'commit', 'commit')
    probe.wrap(vm, '_restore', 'restore')
    probe.wrap(vm, 'decode', 'decode')
    probe.wrap(vm, '_external', lambda name: 'ext:' + name)
    if not hasattr(vm, '_source'):
        probe.wrap(vm.uc, 'emu_start', 'emulate')
        probe.wrap(vm.uc, 'mem_map', 'mem_map')
    lib = getattr(vm, '_lib', None)
    if lib is not None and hasattr(lib, 'fm_accel_run'):
        class Lib:
            def __init__(self, inner):
                self.__dict__['_inner'] = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)
        proxy = Lib(lib)
        proxy.fm_accel_run = lib.fm_accel_run
        probe.wrap(proxy, 'fm_accel_run', 'emulate')
        vm._lib = proxy
    source = getattr(vm, '_source', vm.reader)
    for holder in (source, getattr(source, 'inner', None)):
        if holder is not None and hasattr(holder, 'read_many_status') and 'read_many_status' not in vars(holder):
            probe.wrap(holder, 'read_many_status', 'game_read')
            probe.wrap(holder, 'read', 'game_read')
            break
    return vm


PHASES = ('phase:build', 'phase:server_value', 'phase:feed', 'phase:get', 'phase:get_property', 'call(other)')


def run(label, fn, vm, probe, out):
    probe.take()
    stubbed0 = Counter(vm.stubbed)
    intercepted0 = Counter(getattr(vm, 'intercepted', ()))
    files0 = getattr(vm, 'bytes_from_files', 0)
    pages0 = len(vm.live_pages)
    wall, cpu = time.perf_counter(), time.process_time()
    result = fn()
    wall, cpu = time.perf_counter() - wall, time.process_time() - cpu
    split = probe.take()
    ext = {k[4:]: v for k, v in split.items() if k.startswith('ext:')}
    mech = {k: v for k, v in split.items() if not k.startswith(('ext:', 'phase:'))}
    phases = {k[6:]: v for k, v in split.items() if k.startswith('phase:')}
    mech['external_models'] = (round(sum(v[0] for v in ext.values()), 4), sum(v[1] for v in ext.values()))
    row = {
        'read': label, 'wall_s': round(wall, 3), 'cpu_s': round(cpu, 3),
        'phases_inclusive_s': phases,
        'exclusive_s': dict(sorted(mech.items(), key=lambda kv: -kv[1][0])),
        'externals_top': dict(sorted(ext.items(), key=lambda kv: -kv[1][0])[:8]),
        'external_calls': dict((Counter(vm.stubbed) - stubbed0).most_common(8)),
        'intercepts': dict(Counter(getattr(vm, 'intercepted', ())) - intercepted0),
        'bytes_from_game_files': getattr(vm, 'bytes_from_files', 0) - files0,
        'live_pages_added': len(vm.live_pages) - pages0,
        'vm': vm.vm_stats() if hasattr(vm, 'vm_stats') else None,
    }
    out.append(row)
    print(f'\n== {label}: wall {wall:.2f} s, cpu {cpu:.2f} s, +{row["live_pages_added"]} live pages, '
          f'{row["bytes_from_game_files"]} file bytes')
    print('   phases (inclusive): ' + ', '.join(f'{k} {v[0]:.3f}s/{v[1]}' for k, v in phases.items()))
    for key, (seconds, calls) in row['exclusive_s'].items():
        print(f'   {key:22s} {seconds:8.3f} s  {calls:8d} calls')
    if row['externals_top']:
        print('   externals: ' + ', '.join(f'{k} {v[0]:.3f}s/{v[1]}' for k, v in row['externals_top'].items()))
    if row['intercepts']:
        print('   intercepts: ' + ', '.join(f'{k} {v}' for k, v in row['intercepts'].items()))
    return result


def open_vm(kind):
    from fm_live_mcp.fmdb.image import PluginImage
    from fm_live_mcp.fmdb.live import open_live
    from fm_live_mcp.fmdb.memory import LiveMemory
    from fm_live_mcp.fmdb import ui_vm
    session = open_live()
    image = PluginImage.load(session.plugin_path)

    def make():
        memory = LiveMemory(session.pid)
        cls = ui_vm.UiHandlerVM.classic if kind == 'classic' else ui_vm.UiHandlerVM
        vm = cls(memory, session.base, image, file_resolver=ui_vm.lsof_resolver(session.pid), rng='copy')
        vm.fast()
        return vm
    return session, make


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--vm', default=os.environ.get('FMDB_UI_VM', 'auto'))
    ap.add_argument('--reads', default='board,inbox,player')
    ap.add_argument('--inbox-unids', default='')
    ap.add_argument('--inbox-scan', type=int, default=0, help='time the newest N items and list them')
    ap.add_argument('--player', default='')
    ap.add_argument('--cprofile', action='store_true')
    ap.add_argument('--json')
    args = ap.parse_args(argv)
    from fm_live_mcp.fmdb import ui_handlers, ui_recipes_news as N, ui_recipes_person as P
    session, make = open_vm(args.vm)
    read = session.reader.read
    out = []
    reads = args.reads.split(',')
    try:
        probe = Probe()
        vm = instrument(make(), probe)
        print(f'vm class {type(vm).__name__}; load {os.getloadavg()[0]:.1f}')
        view = N.viewer(vm)
        if args.cprofile:
            import cProfile
            import pstats
            profile = cProfile.Profile()
            profile.enable()
        if 'board' in reads:
            run('board confidence (cold)', lambda: ui_handlers.team_confidence(vm, view.team), vm, probe, out)
            run('board confidence (warm, same emulator)', lambda: ui_handlers.team_confidence(vm, view.team),
                vm, probe, out)
        if 'inbox' in reads:
            vm = instrument(make(), probe)
            entries = N.inbox_entries(vm, view.human)
            if args.inbox_scan:
                rows = []
                for entry in entries[:args.inbox_scan]:
                    t0, c0 = time.perf_counter(), time.process_time()
                    N.news_item(vm, view.person_index, entry.unid)
                    rows.append((time.perf_counter() - t0, time.process_time() - c0, entry.unid, entry.news_class))
                probe.take()
                for wall, cpu, unid, cls in sorted(rows, reverse=True)[:12]:
                    print(f'   item {unid} {cls}: wall {wall:.2f} cpu {cpu:.2f}')
                print('   median wall', sorted(r[0] for r in rows)[len(rows) // 2])
                vm = instrument(make(), probe)
            wanted = [int(u) for u in args.inbox_unids.split(',') if u] or [entries[0].unid]
            for unid in wanted:
                entry = next(e for e in entries if e.unid == unid)
                run(f'inbox item {unid} {entry.news_class} (first on this emulator)',
                    lambda: N.news_item(vm, view.person_index, unid), vm, probe, out)
                run(f'inbox item {unid} (again)', lambda: N.news_item(vm, view.person_index, unid), vm, probe, out)
        if 'player' in reads:
            vm = instrument(make(), probe)
            from fm_live_mcp.fmdb.ui_recipes_screens import club_players
            from fm_live_mcp import world
            if args.player:
                pid = int(args.player, 0)
            else:
                club = world.pointer(read, view.team + 0x30)
                pid = P.person_id(vm, read, club_players(read, club)[0][1])
                probe.take()
            run(f'player status {pid:#x} (cold)', lambda: P.player_status(vm, pid, read=read), vm, probe, out)
            run(f'player status {pid:#x} (warm)', lambda: P.player_status(vm, pid, read=read), vm, probe, out)
        if args.cprofile:
            profile.disable()
            stats = pstats.Stats(profile)
            stats.sort_stats('tottime').print_stats(28)
    finally:
        session.close()
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1, default=str))


if __name__ == '__main__':
    main()
