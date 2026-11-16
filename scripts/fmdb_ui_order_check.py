"""Read-order check on frozen memory: two emulators read the same screens in opposite orders.

tests/test_fmdb_ui_stability_live.py compares two orders read from the running game at
different moments, so it can only pass while the game does not change. This script freezes
live memory (pages are copied once, on first use, and then served to both emulators; see
fmdb_ui_vm_check.FrozenReader) and compares board confidence, N player statuses, the calendar
and the club vision read forwards on one emulator and backwards on another. The accelerated
emulator starts new page generations on the way (every 5 s), so this also checks that a
generation change inside a long session does not change answers.

  PYTHONPATH=. python scripts/fmdb_ui_order_check.py [--players 20] [--vm fast|classic]

Read-only against the game.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--players', type=int, default=20)
    ap.add_argument('--vm', default='fast')
    args = ap.parse_args(argv)
    from types import SimpleNamespace
    from fmdb_ui_vm_check import FrozenReader
    from test_fmdb_ui_stability_live import _families, _strip, _differences
    from fm_live_mcp import world, players as P
    from fm_live_mcp.fmdb import ui_recipes_person as UP
    from fm_live_mcp.fmdb.image import PluginImage
    from fm_live_mcp.fmdb.live import open_live
    from fm_live_mcp.fmdb.memory import LiveMemory
    from fm_live_mcp.fmdb.ui_vm import UiHandlerVM, lsof_resolver
    session = open_live()
    memory = LiveMemory(session.pid)
    try:
        frozen = FrozenReader(memory)
        image = PluginImage.load(session.plugin_path)
        resolver = lsof_resolver(session.pid)
        fake = SimpleNamespace(reader=frozen, base=session.base, pid=session.pid, plugin_path=session.plugin_path)

        def make():
            build = UiHandlerVM.classic if args.vm == 'classic' else UiHandlerVM
            vm = build(frozen, session.base, image, file_resolver=resolver, rng='copy')
            vm.fast()
            return vm
        vm = make()
        record, _ = world.loaded(world.ReadSet(frozen.read), session.base)
        team = record['coaches'][0]['team_address']
        roster = [p for p in world.vector(frozen.read, team + 0x38, 512)
                  if struct.unpack('<Q', frozen.read(p, 8))[0] == session.base + P.RVA[0]]
        players = [UP.person_id(vm, frozen.read, p) for p in roster[:args.players]]

        def read_all(order):
            vm = make()
            board, player, calendar, vision = _families(fake, vm, players)
            out, started, cpu = {}, time.perf_counter(), time.process_time()
            for family in order:
                if family == 'board':
                    out['board'] = board()
                elif family == 'players':
                    ids = players if order[0] == 'board' else list(reversed(players))
                    out['players'] = {pid: player(pid) for pid in ids}
                elif family == 'calendar':
                    out['calendar'] = calendar()
                elif family == 'vision':
                    out['vision'] = vision()
            print(f'{type(vm).__name__} order {"/".join(order)}: {time.perf_counter() - started:.1f} s wall, '
                  f'{time.process_time() - cpu:.1f} s CPU, generations {getattr(vm, "generations", "-")}', flush=True)
            return _strip(out)
        forward = read_all(('board', 'players', 'calendar', 'vision'))
        backward = read_all(('vision', 'calendar', 'players', 'board'))
        diff = _differences(forward, backward)
        leaves = sum(1 for _ in _walk(forward))
        print(f'{leaves} leaves compared, {len(diff)} different', *diff[:8], sep='\n   ')
        return 1 if diff else 0
    finally:
        memory.close()
        session.close()


def _walk(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)
    else:
        yield value


if __name__ == '__main__':
    sys.exit(main())
