"""Live-gated read-order check (skipped unless FM27 runs): one emulator per order reads board
confidence, 20 player statuses, the calendar and the club vision; two orders must agree.

Earlier lanes saw (a) a 'write to shipped code' failure on a long-lived emulator after many
reads and (b) values that depended on the read order. This test pins both: every family is
read in the same long-lived VM, forwards and backwards, and the answers are compared after
dropping timings. Slow: about 3-6 minutes per order.
"""
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fmdb_ui_live import _live_available  # noqa: E402

pytestmark = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')
PLAYERS = 20
VOLATILE = {'seconds', 'rng_uses', '_meta', 'timing', 'data_seconds', 'request_params_used', 'build_seconds',
            'input_seconds'}


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _families(session, vm, players):
    from fm_live_mcp.fmdb import ui_handlers, variant, ui_recipes_news as N, ui_recipes_person as P
    from fm_live_mcp.fmdb.ui_handlers import plain_text
    read = session.reader.read
    team = N.viewer(vm).team

    def board():
        reading = ui_handlers.team_confidence(vm, team)
        return {'inputs': reading.inputs,
                'values': {r.code: plain_text(variant.to_json(r.value)) for r in reading.readings}}

    def player(pid):
        out = P.player_status(vm, pid, read=read)
        return {k: out.get(k) for k in ('fields', 'contract', 'squad_screen_band', 'failed_data_keys')}

    def calendar():
        return [_strip(variant.to_json(row)) for row in N.calendar(vm, days=60)]

    def vision():
        out = P.club_vision(vm, read=read)
        return {k: out.get(k) for k in ('fields', 'objectives', 'board_members')}

    return board, player, calendar, vision


def _read_all(order, players):
    sys.path.insert(0, str(ROOT / 'scripts'))
    from fmdb_ui_read import open_vm
    session, memory, vm = open_vm()
    try:
        board, player, calendar, vision = _families(session, vm, players)
        out = {}
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
        return _strip(out)
    finally:
        memory.close()
        session.close()


def _squad(n):
    sys.path.insert(0, str(ROOT / 'scripts'))
    from fmdb_ui_read import open_vm, managed_team
    from fm_live_mcp import world, players as P
    from fm_live_mcp.fmdb import ui_recipes_person as UP
    session, memory, vm = open_vm()
    try:
        read = session.reader.read
        team = managed_team(session)
        roster = [p for p in world.vector(read, team + 0x38, 512)
                  if struct.unpack('<Q', read(p, 8))[0] == session.base + P.RVA[0]]
        return [UP.person_id(vm, read, p) for p in roster[:n]]
    finally:
        memory.close()
        session.close()


def _differences(a, b, path=''):
    if type(a) is not type(b):
        return [f'{path}: {a!r:.120} != {b!r:.120}']
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(f'{path}/{k}: only in {"first" if k in a else "second"} order')
            else:
                out += _differences(a[k], b[k], f'{path}/{k}')
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [f'{path}: {len(a)} items != {len(b)} items']
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += _differences(x, y, f'{path}[{i}]')
        return out
    return [] if a == b else [f'{path}: {a!r:.120} != {b!r:.120}']


def test_read_order_does_not_change_answers():
    players = _squad(PLAYERS)
    assert len(players) == PLAYERS
    forward = _read_all(('board', 'players', 'calendar', 'vision'), players)
    backward = _read_all(('vision', 'calendar', 'players', 'board'), players)
    diff = _differences(forward, backward)
    assert not diff, f'{len(diff)} differences, first: {diff[:10]}'
    # The families must also have produced data (not two identical failures).
    assert all(str(s).startswith('ok') for s in forward['board']['inputs'].values())
    assert forward['board']['values']['4zmg']
    assert all(p['fields'].get('name') for p in forward['players'].values())
    assert any(row.get('kind') == 'fixture' for row in forward['calendar'])
    assert forward['vision']['objectives']['board']['actionable']
