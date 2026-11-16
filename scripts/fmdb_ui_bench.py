"""Time every shaped UI tool against the running game: cold, warm and cached.

For each tool of `ui_tools.py` the function behind the MCP tool is called three times:

* cold: a new emulator (no copied pages, no translated code), `fresh=True`;
* warm: the same emulator again, `fresh=True` (recomputed from current game memory);
* cached: `fresh=False` (served from the cache when its validity check passes).

Wall and CPU seconds of this process are printed per call (CPU excludes the memory-reader
helper process). `FMDB_UI_VM=classic` measures the Python-hooked reference emulator.

  PYTHONPATH=. python scripts/fmdb_ui_bench.py [--tools board,inbox] [--json out.json] [--repeat-cached 3]

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


def tool_table(bridge, sid, ui_tools):
    from fm_live_mcp.fmdb import ui_recipes_more as more, ui_recipes_news as news
    from fm_live_mcp.fmdb import ui_recipes_person as person, ui_recipes_screens as screens

    def recipe(kind, fn, kwargs=None, pass_read=False):
        return lambda fresh: ui_tools.recipe_read(bridge, sid, kind, fn, dict(kwargs or {}), fresh,
                                                  pass_read=pass_read)

    def first_player():
        session = ui_tools.session_for(bridge, sid)
        from fm_live_mcp import world
        record, _ = world.loaded(world.ReadSet(session.read), session.base)
        team = record['coaches'][0]['team_address']
        primary = world.vector(session.read, team + 0x38, 512)[0]
        index = session.table_index('people', person.person_object(session.read, primary, session.base))
        if index is None:
            from fm_live_mcp.fmdb import tables
            index = tables.entries(session.read, session.base, 'people').index(primary)
        return (1 << 24) | index
    player = {}

    def player_status(fresh):
        if 'id' not in player:
            player['id'] = first_player()
        if hasattr(ui_tools, 'player_status'):
            return ui_tools.player_status(bridge, sid, player['id'], fresh)
        return ui_tools.recipe_read(bridge, sid, 'player_status', person.player_status,
                                    {'player': player['id']}, fresh, pass_read=True)

    def inbox(fresh):
        if hasattr(ui_tools, 'inbox'):
            return ui_tools.inbox(bridge, sid, 50, False, None, fresh)
        return ui_tools.recipe_read(bridge, sid, 'inbox', news.inbox, {'limit': 50, 'unread_only': False}, fresh)

    def inbox_body(fresh):
        if not hasattr(ui_tools, 'inbox'):
            return None
        listed = ui_tools.inbox(bridge, sid, 50, False, None, False)
        unid = listed['result'][0]['unid']
        return ui_tools.inbox(bridge, sid, 50, False, [unid], fresh)

    table = [
        ('fm_get_board_confidence', lambda fresh: ui_tools.board_confidence(bridge, sid, None, fresh)),
        ('fm_get_inbox (50 items)', inbox),
        ('fm_get_inbox (one body)', inbox_body),
        ('fm_get_calendar (60 days)', recipe('calendar', news.calendar, {'team': None, 'days': 60})),
        ('fm_get_player_status', player_status),
        ('fm_get_club_vision', recipe('club_vision', person.club_vision, {'club': None}, True)),
        ('fm_get_club_vision_progress', recipe('club_vision_progress', screens.club_vision_progress,
                                               {'club': None}, True)),
        ('fm_get_squad_happiness (none)', recipe('squad_happiness', screens.squad_happiness,
                                                 {'club': None, 'reasons': 'none'}, True)),
        ('fm_get_squad_happiness (unhappy)', recipe('squad_happiness', screens.squad_happiness,
                                                    {'club': None, 'reasons': 'unhappy'}, True)),
        ('fm_get_squad_happiness (all)', recipe('squad_happiness', screens.squad_happiness,
                                                {'club': None, 'reasons': 'all'}, True)),
    ]
    for tool_name, kind, _ in ui_tools.MORE_SCREENS:
        fn = getattr(more, kind, None)
        if callable(fn):
            table.append((tool_name, recipe(kind, fn)))
    table.append(('fm_get_league_table', recipe('league_table', more.league_table, {'competition': None})))
    table.append(('fm_ui_read 114 (guarded)',
                  lambda fresh: ui_tools.ui_read(bridge, sid, 114, {'Ttea': 'managed_team'}, None, fresh)))
    return table


def timed(fn, *args):
    wall, cpu = time.perf_counter(), time.process_time()
    try:
        out = fn(*args)
        error = None
    except Exception as exc:  # noqa: BLE001 - a failing tool is a row of the table
        out, error = None, f'{type(exc).__name__}: {exc}'[:200]
    return round(time.perf_counter() - wall, 3), round(time.process_time() - cpu, 3), out, error


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--tools', help='comma-separated substrings of tool names')
    ap.add_argument('--json')
    ap.add_argument('--repeat-cached', type=int, default=2)
    args = ap.parse_args(argv)
    if not os.environ.get('FMCP_CACHE_DIR'):
        raise SystemExit('set FMCP_CACHE_DIR to a scratch directory')
    from fm_live_mcp.bridge import Bridge
    from fm_live_mcp.fmdb import ui_tools
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    rows = []
    try:
        wanted = [w for w in (args.tools or '').split(',') if w]
        vm_kind = None
        for name, call in tool_table(bridge, sid, ui_tools):
            if wanted and not any(w in name for w in wanted):
                continue
            session = ui_tools.session_for(bridge, sid)
            session._vms.clear()                       # cold: a new emulator
            cold = timed(call, True)
            if cold[2] is None and cold[3] is None:
                continue
            warm = timed(call, True)
            cached = min((timed(call, False) for _ in range(max(1, args.repeat_cached))), key=lambda r: r[0])
            vms = [entry['vm'] for entry in session._vms.values()]
            vm_kind = type(vms[0]).__name__ if vms else vm_kind
            hit = (cached[2] or {}).get('cache', {}).get('hit') if isinstance(cached[2], dict) else None
            row = {'tool': name, 'cold': cold[:2], 'warm': warm[:2], 'cached': cached[:2], 'cached_hit': hit,
                   'error': cold[3] or warm[3] or cached[3], 'load': round(os.getloadavg()[0], 1)}
            rows.append(row)
            print(f"{name:34s} cold {cold[0]:7.2f}/{cold[1]:6.2f}  warm {warm[0]:7.2f}/{warm[1]:6.2f}  "
                  f"cached {cached[0]:6.3f}/{cached[1]:6.3f} hit={hit} load {row['load']}"
                  + (f"  ERROR {row['error']}" if row['error'] else ''), flush=True)
        print('emulator:', vm_kind, '(wall/CPU seconds)')
    finally:
        bridge.detach()
    if args.json:
        Path(args.json).write_text(json.dumps({'vm': vm_kind, 'rows': rows}, indent=1))


if __name__ == '__main__':
    main()
