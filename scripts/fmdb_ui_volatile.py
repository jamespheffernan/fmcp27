"""Which bytes keep invalidating a cached UI answer, and which shipped code reads them.

A screen answer is stored with the read set of its computation (ui_cache.ReadSet). This
diagnostic computes one recipe repeatedly on one emulator, compares the live pages of its read
set between rounds and, for every 8-byte word that the computation read and that changed,
records the program counter and link register of the loads (FastUiHandlerVM.debug_word).

  PYTHONPATH=. python scripts/fmdb_ui_volatile.py [--recipe player_status|training|club_vision|board]
      [--rounds 4] [--pause 5]

Read-only against the game.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PAGE = 4096


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--recipe', default='player_status')
    ap.add_argument('--rounds', type=int, default=4)
    ap.add_argument('--pause', type=float, default=5.0)
    args = ap.parse_args(argv)
    from fm_live_mcp import world
    from fm_live_mcp.fmdb import ui_handlers, ui_recipes_more as M, ui_recipes_news as N, ui_recipes_person as P
    from fm_live_mcp.fmdb import ui_vm
    from fm_live_mcp.fmdb.image import PluginImage
    from fm_live_mcp.fmdb.live import open_live
    from fm_live_mcp.fmdb.memory import LiveMemory
    from fm_live_mcp.fmdb.ui_recipes_screens import club_players
    session = open_live()
    try:
        memory = LiveMemory(session.pid)
        vm = ui_vm.UiHandlerVM(memory, session.base, PluginImage.load(session.plugin_path),
                               file_resolver=ui_vm.lsof_resolver(session.pid), rng='copy')
        vm.fast()
        view = N.viewer(vm)
        read = vm.reader.read
        club = world.pointer(read, view.team + 0x30)
        player = P.person_id(vm, read, club_players(read, club)[0][1])
        recipes = {'player_status': lambda: P.player_status(vm, player, read=read),
                   'training': lambda: M.training(vm), 'club_vision': lambda: P.club_vision(vm, read=read),
                   'board': lambda: ui_handlers.team_confidence(vm, view.team)}
        run = recipes[args.recipe]
        volatile, culprits = set(), Counter()
        for round_ in range(args.rounds):
            vm.begin_read()
            vm.watch(volatile)
            vm.trace_begin()
            run()
            pages, masks = vm.read_set()
            vm.trace_end()
            seen = {p: vm.live_read(p, PAGE) for p in pages}
            time.sleep(args.pause)
            now = dict(zip(pages, (d for _, d in memory.read_many_status([(p, PAGE) for p in pages]))))
            changed = [p for p in pages if now[p] is not None and now[p] != seen[p]]
            words = []
            for p in changed:
                mask = masks.get(p)
                for w in range(512):
                    if seen[p][8 * w:8 * w + 8] != now[p][8 * w:8 * w + 8] and (
                            mask is None or (mask[w >> 6] >> (w & 63)) & 1):
                        words.append((p + 8 * w, mask is not None, seen[p][8 * w:8 * w + 8].hex(),
                                      now[p][8 * w:8 * w + 8].hex()))
            read_words = [w for w in words if w[1]]
            print(f'round {round_}: {len(pages)} pages, {len(masks)} by word, {len(changed)} changed in '
                  f'{args.pause:.0f} s; changed words that were read: {len(read_words)} '
                  f'(+{len(words) - len(read_words)} on pages not yet watched)', flush=True)
            for address, _, before, after in read_words[:6]:
                vm.reset()
                vm.watch(volatile | {address & ~(PAGE - 1)})
                vm.debug_word(address)
                run()
                hits = Counter(vm.debug_hits())
                vm.debug_word(0)
                rva = address - session.base
                where = f'plugin+{rva:#x}' if 0 <= rva < 0x8000000 else 'heap'
                print(f'   {address:#x} ({where}) {before} -> {after}; loads: '
                      + (', '.join(f'pc {pc:#x} lr {lr:#x} x{n}' for (pc, lr), n in hits.most_common(4))
                         or 'by a model or vm.reader'), flush=True)
                for (pc, lr), n in hits.items():
                    culprits[(pc, lr)] += 1
            volatile.update(changed)
        print('loads of changing words by (pc, lr):',
              ', '.join(f'{pc:#x}/{lr:#x} x{n}' for (pc, lr), n in culprits.most_common(8)) or 'none')
    finally:
        session.close()


if __name__ == '__main__':
    main()
