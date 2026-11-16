"""Sweep every buildable UI handler type against the running game and record what it shows.

For each factory type (and each class the DATABASE_RECORD type 28 dispatches to by the
dref's table type) the sweep builds the handler with UI_RECORD bindings taken from the
loaded career (managed human, team, club, a squad player, a scouted player, a scout, the
managed league, the Champions League, the next and the last fixture, a news item, today's
date), transfers the client's inputs (slot 17), and reads every client key with
`ui_recipes_more.KeyReader` (cached inputs, declared server keys via slots 14/16, direct
keys via slot 13; screen parameters a getter asks for through 0x77E228 are recorded).

Each type runs in a fresh emulator (copied live memory) with a per-call and a per-type time
budget. Results go to out/fmdb-ui-sweep/types/<id>.json (one file per type, so a crash or
restart resumes) and are merged into out/fmdb-ui-sweep/sweep.json; --markdown writes the
docs/fmdb/UI_SWEEP.md table body.

  PYTHONPATH=. python scripts/fmdb_ui_sweep.py [--types 9,50] [--budget 120] [--merge-only]

Read-only against the game: shipped code runs in this process on copied bytes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
import json
import os
from pathlib import Path
import struct
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fm_live_mcp.fmdb import ui_registry, variant  # noqa: E402
from fm_live_mcp.fmdb.ui_handlers import input_keys, plain_text  # noqa: E402
from fm_live_mcp.fmdb.ui_vm import object_id  # noqa: E402
from fm_live_mcp.fmdb.vm import Unavailable, _Stop  # noqa: E402

# FMDB_UI_SWEEP_OUT: another output folder (e.g. a salted RNG run, docs/fmdb/REFUSALS.md)
OUT = Path(os.environ.get('FMDB_UI_SWEEP_OUT') or ROOT / 'out' / 'fmdb-ui-sweep')
VALUE_CHARS = 1500
QUICK_KEYS = 14

CONTEXT_KEYS = ('Hhum', 'huma', 'PbPY', 'Ttea', 'Team', 'team', 'Teal', 'iyrZ', 'club', 'Club')
DATE_KEYS = ('fdte', 'date', 'fxdt', 'nMzT', 'dcnt', 'CqMA', 'day ')
PERSON_KEYS = ('Pers', 'pers', 'plyr', 'dref')
FIXTURE_KEYS = ('fhmT', 'fawT', 'fdte', 'home', 'away', 'fixt', 'Topp')


# ---------------------------------------------------------------------- live bindings
def open_vm(session):
    from fm_live_mcp.fmdb.image import PluginImage
    from fm_live_mcp.fmdb.memory import LiveMemory
    from fm_live_mcp.fmdb.ui_vm import UiHandlerVM, lsof_resolver
    from fm_live_mcp.fmdb.ui_recipes_more import install_param_trace
    if not hasattr(session, '_sweep_image'):
        session._sweep_image = PluginImage.load(session.plugin_path)
    memory = LiveMemory(session.pid)
    vm = UiHandlerVM(memory, session.base, session._sweep_image, file_resolver=lsof_resolver(session.pid),
                     rng='copy')
    vm.rng_salt = int(os.environ.get('FMDB_RNG_SALT', '0'))   # sensitivity run (REFUSALS.md "RNG")
    vm.fast()
    install_param_trace(vm)
    return vm, memory


def collect_bindings(session, vm) -> dict:
    """Named objects of the loaded career and the UI ids/values that stand for them."""
    from fm_live_mcp import world, players
    from fm_live_mcp.fmdb import ui_recipes_news as N, ui_recipes_person as P
    read = session.reader.read
    view = N.viewer(vm)
    today = date.fromisoformat(view.current_date)
    human_pid = object_id(1, view.person_index)
    team = view.team
    team_id = vm.object_ref(team)
    club = world.pointer(read, team + 0x30)
    club_id = vm.object_ref(club)
    roster = world.vector(read, team + 0x38, 512)
    squad = [p for p in roster if struct.unpack('<Q', read(p, 8))[0] == session.base + players.RVA[0]]
    player = P.person_id(vm, read, squad[0])
    scouted = scout = None
    begin, end = struct.unpack('<QQ', read(view.human + 0x110, 16))
    for i in range(min((end - begin) // 8, 400)):
        row = struct.unpack('<Q', read(begin + 8 * i, 8))[0]
        target = struct.unpack('<Q', read(row, 8))[0] if row else 0
        if target and vm.object_ref(target) >> 24 == 1 and vm.object_ref(target) not in (player,):
            scouted = vm.object_ref(target)
            break
    if scouted:
        try:
            rep = P.scout_report(vm, scouted, human_pid)
            scout = rep['summary'].get('scout_id')
        except _Stop:
            scout = None
    rows = N.calendar(vm, days=28, start=today - timedelta(days=14), fixture_details=False)
    fixtures = [r for r in rows if r['kind'] == 'fixture' and (r.get('team') or {}).get('id') == team_id]
    past = [r for r in fixtures if r['date'] < today.isoformat()]
    future = [r for r in fixtures if r['date'] >= today.isoformat()]

    def fixture(row):
        if row is None:
            return None
        mine, theirs = row['team']['id'], row['opponent']['id']
        home, away = (mine, theirs) if row.get('is_home') else (theirs, mine)
        ref = row.get('fixture_ref') or {}
        dcnt = ref.get('dcnt')
        payload = N.si_date(date.fromisoformat(dcnt.iso), dcnt.low) if dcnt is not None else N.si_date(
            date.fromisoformat(row['date']))
        return {'home': home, 'away': away, 'si_date': payload, 'ref': ref.get('dref'),
                'competition': row['competition']['id'], 'competition_name': row['competition']['name'],
                'date': row['date'], 'label': f"{row['team']['name']} v {row['opponent']['name']}"}
    nxt = fixture(future[0] if future else None)
    last = fixture(past[-1] if past else None)
    league = next((r['competition']['id'] for r in fixtures if r['competition']['name'] == 'Premier League'), None)
    ucl = next((r['competition']['id'] for r in fixtures if 'Champions League' in r['competition']['name']), None)
    entries = N.inbox_entries(vm, view.human)
    news = entries[0].unid if entries else None
    focus = None
    try:
        from fm_live_mcp.fmdb.ui_recipes_more import open_handler
        reader = open_handler(vm, 97, {'iyrZ': team_id, 'PbPY': human_pid, 'Hhum': human_pid})
        focuses = reader.get('twli').value
        if isinstance(focuses, list) and focuses:
            focus = focuses[0].get('rfid')
    except _Stop:
        focus = None
    return {'game_date': view.current_date, 'human_person_index': view.person_index, 'human': human_pid,
            'team': team_id, 'club': club_id, 'player': player, 'scouted_player': scouted, 'scout': scout,
            'league': league, 'ucl': ucl, 'next_fixture': nxt, 'last_fixture': last, 'news_unid': news,
            'recruitment_focus': focus,
            'today_si': N.si_date(today)}


def profiles(b: dict) -> dict:
    """Profile name -> UI_RECORD fields (on top of the context fields)."""
    out = {'none': {}}

    def person(pid):
        return {k: pid for k in PERSON_KEYS}
    if b.get('player'):
        out['squad_player'] = person(b['player'])
    if b.get('scouted_player'):
        out['scouted_player'] = person(b['scouted_player'])
    if b.get('scout'):
        out['staff'] = person(b['scout'])
    out['team'] = {'dref': b['team']}
    out['club'] = {'dref': b['club']}
    if b.get('league'):
        out['league'] = {'comp': b['league'], 'dref': b['league']}
    if b.get('ucl'):
        out['ucl'] = {'comp': b['ucl'], 'dref': b['ucl']}
    for name in ('next_fixture', 'last_fixture'):
        f = b.get(name)
        if f:
            out[name] = {'fhmT': f['home'], 'fawT': f['away'], 'fdte': f['si_date'], 'home': f['home'],
                         'away': f['away'], 'fixt': f['ref'] or 0, 'comp': f['competition'],
                         'Topp': f['away'] if f['home'] == b['team'] else f['home']}
    if b.get('news_unid') is not None:
        out['news'] = {'unid': b['news_unid'], 'huma': b['human_person_index']}
    if b.get('recruitment_focus') is not None:
        out['recruitment_focus'] = {'rfid': b['recruitment_focus']}
    return out


def context(b: dict) -> dict:
    ctx = {'Hhum': b['human'], 'huma': b['human_person_index'], 'PbPY': b['human'], 'Ttea': b['team'],
           'Team': b['team'], 'team': b['team'], 'Teal': b['team'], 'iyrZ': b['team'], 'club': b['club'],
           'Club': b['club']}
    ctx.update({k: b['today_si'] for k in DATE_KEYS})
    return ctx


def relevant_profiles(fourccs: set, names) -> list:
    out = []
    for name in names:
        if name == 'none':
            continue
        if name in ('squad_player', 'scouted_player', 'staff') and fourccs & set(PERSON_KEYS):
            out.append(name)
        elif name in ('team', 'club') and 'dref' in fourccs:
            out.append(name)
        elif name in ('league', 'ucl') and fourccs & {'comp', 'dref'}:
            out.append(name)
        elif name in ('next_fixture', 'last_fixture') and fourccs & set(FIXTURE_KEYS):
            out.append(name)
        elif name == 'news' and 'unid' in fourccs:
            out.append(name)
        elif name == 'recruitment_focus' and 'rfid' in fourccs:
            out.append(name)
    return out or ['none']


# ---------------------------------------------------------------------- one attempt
def _short(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= VALUE_CHARS:
        return value
    return {'truncated': text[:VALUE_CHARS]}


def attempt(vm, handler_type, record, keys, *, deadline, call_us, reg, dref_class=None, inputs=True):
    from fm_live_mcp.fmdb.ui_recipes_more import KeyReader
    started, rng0 = time.perf_counter(), vm.rng_uses
    vm.timeout_us = call_us
    out = {'record': {k: v for k, v in record.items()}, 'keys': {}, 'inputs': {}}
    try:
        handler = vm.build(handler_type, record)
    except _Stop as stop:
        out.update(build_error=f'{stop.reason} {stop.detail or ""}'.strip(), seconds=time.perf_counter() - started,
                   rng_uses=vm.rng_uses - rng0)
        return out
    out['client'], out['server'] = handler.client_class, handler.server_class
    if dref_class and handler.client_class != dref_class:
        out['build_error'] = f'built {handler.client_class}, expected {dref_class}'
        return out
    if handler.server and inputs:
        for key in input_keys(reg, handler.client_class):
            if time.time() > deadline:
                out['inputs'][key] = 'skipped: type budget'
                continue
            out['inputs'][key] = vm.transfer(handler, key)
    reader = KeyReader(vm, handler, reg)
    reader.inputs = inputs
    for code in keys:
        if time.time() > deadline:
            out['keys'][code] = {'label': reg.label(code), 'status': 'skipped'}
            continue
        try:
            r = reader.get(code)
        except Exception as exc:  # noqa: BLE001 - one key must not stop the sweep
            out['keys'][code] = {'label': reg.label(code), 'status': 'unavailable',
                                 'reason': f'reader error: {type(exc).__name__}: {exc}'}
            vm.reset_to_last()
            continue
        row = {'label': r.label, 'status': r.status, 'protocol': r.protocol, 'ms': round(r.seconds * 1000, 1)}
        if r.server_keys:
            row['server_keys'] = list(r.server_keys)
        if r.failed:
            row['failed'] = r.failed
        if r.params_read:
            row['params'] = [hex(p) for p in r.params_read]
        if r.rng_uses:
            row['rng_uses'] = r.rng_uses
        if isinstance(r.value, Unavailable):
            row['reason'] = r.value.reason
            if r.value.detail:
                row['detail'] = str(r.value.detail)[:400]
        else:
            row['kind'] = r.kind
            full = plain_text(variant.to_json(r.value))
            row['value'] = _short(full)
            if isinstance(full, str) and full in GAME_NO_DATA_TEXTS:
                row['status'] = 'unset'          # the getter's own "nothing for this object" text
                row['game_text'] = full
            note_nested(out.setdefault('nested', {}), full, code, reg)
        out['keys'][code] = row
    out['seconds'] = round(time.perf_counter() - started, 2)
    out['rng_uses'] = vm.rng_uses - rng0
    out['counts'] = dict(Counter(row['status'] for row in out['keys'].values()))
    return out


def note_nested(found: dict, value, parent: str, reg, depth=0):
    """Record the registry FourCCs that occur as fields of records inside a returned value
    (the front end's FM.UI.*Reference classes read them from those records):
    found[code] = [parent key, 'value' | 'unset'], 'value' once any record holds data."""
    if depth > 8:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str) and len(k) == 4 and k != parent and reg.label(k) is not None:
                st = 'unset' if v in (None, '', [], {}) else 'value'
                cur = found.get(k)
                if cur is None or (cur[1] != 'value' and st == 'value'):
                    found[k] = [parent, st]
            note_nested(found, v, parent, reg, depth + 1)
    elif isinstance(value, list):
        for v in value[:200]:
            note_nested(found, v, parent, reg, depth + 1)


def first_blocker(result) -> str | None:
    if result.get('build_error'):
        return 'build: ' + result['build_error']
    reasons = Counter()
    for key, status in (result.get('inputs') or {}).items():
        if not str(status).startswith('ok'):
            reasons['input ' + _reason(str(status))] += 1
    for row in (result.get('keys') or {}).values():
        if row.get('status') == 'unavailable':
            reasons[_reason(row.get('reason', ''))] += 1
        elif row.get('params') and row.get('status') == 'unset':
            reasons['needs screen parameter ' + ','.join(row['params'])] += 1
    if result.get('counts', {}).get('value'):
        return reasons.most_common(1)[0][0] if reasons else None
    if reasons:
        return reasons.most_common(1)[0][0]
    return 'every key unset (no binding produced data)'


def _reason(text: str) -> str:
    import re
    text = re.sub(r'after \d+ insns.*', '', text)
    text = re.sub(r'server key \S+: ', '', text)
    text = re.sub(r'\b0x[0-9a-f]{9,}\b', '0x…', text)
    text = text.replace('unavailable: ', '')
    return text.strip()[:160]


# ---------------------------------------------------------------------- one type
def sweep_type(session, bindings, number, client_class, keys, *, budget, call_us, reg, dref=None):
    vm, memory = open_vm(session)
    try:
        started = time.time()
        deadline = started + budget
        ctx = context(bindings)
        profs = profiles(bindings)
        if dref is not None:
            # DATABASE_RECORD class: the dref selects class and object.
            tried = {}
            record = dict(ctx, dref=dref)
            best = attempt(vm, 28, record, keys, deadline=deadline, call_us=call_us, reg=reg,
                           dref_class=client_class, inputs=client_class not in NO_INPUTS)
            best['profile'] = 'dref'
        else:
            row = reg.types[number]
            fourccs = set(input_keys(reg, client_class))
            server = reg.classes.get(row.get('server') or '')
            if server:
                fourccs |= set(server.slots.get('2', {}).get('fourccs', ()))
            names = relevant_profiles(fourccs, profs)
            tried = {}
            best = None
            if len(names) > 1 and len(keys) > QUICK_KEYS:
                quick_deadline = started + budget / 3
                for name in names:
                    res = attempt(vm, number, dict(ctx, **profs[name]), keys[:QUICK_KEYS],
                                  deadline=min(deadline, quick_deadline), call_us=call_us, reg=reg)
                    tried[name] = res.get('counts', {}) if not res.get('build_error') else {'build_error': res['build_error']}
                names = sorted(names, key=lambda n: -tried[n].get('value', 0))[:1]
            for name in names:
                res = attempt(vm, number, dict(ctx, **profs[name]), keys, deadline=deadline, call_us=call_us, reg=reg)
                res['profile'] = name
                tried[name] = res.get('counts', {}) if not res.get('build_error') else {'build_error': res['build_error']}
                if best is None or res.get('counts', {}).get('value', 0) > best.get('counts', {}).get('value', 0):
                    best = res
        best['profiles_tried'] = tried
        best['type'] = number
        best['class'] = client_class
        best['key_count'] = len(keys)
        best['first_blocker'] = first_blocker(best)
        best['wall_seconds'] = round(time.time() - started, 2)
        best['vm_pages'] = len(vm.live_pages)
        return best
    finally:
        memory.close()


def dref_classes(session, reg):
    """Client class the DATABASE_RECORD factory case builds for each table type."""
    vm, memory = open_vm(session)
    try:
        out = {}
        for table in range(0x3B):
            try:
                h = vm.build(28, {'dref': table << 24}, server=True)
                out[table] = {'client': h.client_class, 'server': h.server_class}
            except _Stop as stop:
                out[table] = {'error': stop.reason}
        return out
    finally:
        memory.close()


# Classes whose slot-17 inputs are skipped (TEAM_UI_HANDLER without inputs read fewer keys in
# the time budget: 144 against 178 values; its dynamics and medical keys need none).
NO_INPUTS = set()
DREF_OBJECTS = {'PERSON_UI_HANDLER': 'player', 'CLUB_UI_HANDLER': 'club', 'TEAM_UI_HANDLER': 'team',
                'COMPETITION_UI_HANDLER': 'league'}


# ---------------------------------------------------------------------- driver
def jobs(reg, tables):
    out = []
    for number, row in sorted(reg.types.items()):
        if not row.get('client'):
            continue
        cls = reg.classes.get(row['client'])
        out.append((str(number), number, row['client'], list(cls.keys(4)) if cls else [], None))
    seen = set()
    for table, row in sorted(tables.items(), key=lambda kv: int(kv[0])):
        cls = row.get('client')
        if not cls or cls in seen or cls == 'DATABASE_RECORD_UI_HANDLER':
            continue
        seen.add(cls)
        c = reg.classes.get(cls)
        out.append((f'28:{cls}', 28, cls, list(c.keys(4)) if c else [], int(table)))
    return out


def merge(path=OUT):
    rows = []
    for f in sorted((path / 'types').glob('*.json')):
        rows.append(json.loads(f.read_text()))
    meta = json.loads((path / 'bindings.json').read_text()) if (path / 'bindings.json').exists() else {}
    tables = json.loads((path / 'dref_tables.json').read_text()) if (path / 'dref_tables.json').exists() else {}
    totals = Counter()
    blockers = Counter()
    for r in rows:
        c = r.get('counts') or {}
        if r.get('base_job'):           # round-2 pass of a first-pass job: counted on its own
            totals['round2_jobs'] += 1
            continue
        if r.get('crashed'):
            totals['crashed'] += 1
        elif r.get('build_error'):
            totals['build_failed'] += 1
        elif c.get('value'):
            totals['values'] += 1
        elif not r.get('key_count'):
            totals['no_keys'] += 1
        else:
            totals['nothing'] += 1
        if r.get('first_blocker') and not c.get('value'):
            blockers[r['first_blocker']] += 1
    sweep = {'bindings': meta, 'dref_tables': tables, 'totals': dict(totals),
             'blockers_where_nothing_read': blockers.most_common(), 'types': rows}
    (path / 'sweep.json').write_text(json.dumps(sweep, indent=1, ensure_ascii=False, default=str))
    return sweep


# ---------------------------------------------------------------------- markdown table
# Usefulness to a manager: category order, then values read. Matched against the class name.
CATEGORIES = (
    ('scouting', ('RECRUITMENT_FOCUS', 'SCOUTING_INFO', 'SCOUT_', 'SCOUTING_CENTRE', 'PLAYER_REPORT', 'DOF_',
                  'PERSON_SEARCH', 'UPCOMING_COMPETITIONS_TO_SCOUT')),
    ('transfers and contracts', ('TRANSFER_', 'CLUB_TRANSFER_CLAUSES', 'SET_TRANSFER_STATUS', 'BUY_OR_SELL',
                                 'CONTRACT', 'TRADE_OFFER', 'HIRE_INTERMEDIARY', 'PRE_CONTRACT', 'NEGOTIATE_')),
    ('squad and players', ('28:PERSON', '28:TEAM', 'SQUAD_', 'MENTORING', 'PLAYER_FORM', 'INDUCTION',
                           'TEAM_SQUAD_SELECTION', 'NATIONAL_SQUAD')),
    ('training', ('TRAINING',)),
    ('board, club and finances', ('28:CLUB', 'TEAM_CONFIDENCE', 'CLUB_VISION', 'ADJUST_SEASON', 'CLUB_BUDGET',
                                  'CLUB_COLLECTIVE', 'SALARY_CAP', 'CODE_OF_CONDUCT')),
    ('matches and competitions', ('FIXTURE', 'MATCH', 'COMPETITION', 'CALENDAR', 'CUP_TIE', 'FRIENDLY',
                                  'TACTIC', 'SET_PIECE', 'STADIUM')),
    ('news and conversations', ('NEWS', 'PRESS_CONFERENCE', 'CONVERSATION', 'STAFF_MEETING', 'TEAM_TALK',
                                'INTERACTION')),
    ('world database', ('NATION', 'CONTINENT', 'AWARD', 'LANGUAGE', 'AGREEMENT', 'DB_SUMMARY', 'CITY')),
)
NOISE = ('SpeakTo', 'Debug', 'Dropdown', 'Can', 'Is', 'Has', 'Should', 'Show', 'Options', 'Tooltip')


def category(job, cls):
    name = job if job.startswith('28:') else cls
    for index, (title, needles) in enumerate(CATEGORIES):
        if any(n in name for n in needles):
            return index, title
    return len(CATEGORIES), 'game, editor and online'


def shows(result, limit=7):
    """One line from the labels of the keys that returned values."""
    labels = []
    for code, row in (result.get('keys') or {}).items():
        label = row.get('label') or code
        if row.get('status') == 'value' and not label.startswith(NOISE) and label not in labels:
            labels.append(label)
    if not labels:
        return ''
    text = ', '.join(labels[:limit])
    return text + (f' (+{len(labels) - limit} more)' if len(labels) > limit else '')


def markdown_table(sweep) -> str:
    rows = []
    for r in sweep['types']:
        if r.get('base_job'):
            continue
        c = r.get('counts') or {}
        index, title = category(r.get('job', ''), r.get('class') or '')
        rows.append((index, -c.get('value', 0), r.get('job', ''), title, r))
    rows.sort(key=lambda x: (x[0], x[1], x[2]))
    out = ['| # | Type | Class | Binding | Value / unset / unavailable | s | RNG | Shows (or first blocker) |',
           '|---|---|---|---|---|---|---|---|']
    current = None
    for n, (index, _, job, title, r) in enumerate(rows, 1):
        if title != current:
            out.append(f'| | **{title}** | | | | | | |')
            current = title
        c = r.get('counts') or {}
        text = shows(r) or ''
        blocker = r.get('first_blocker')
        if not c.get('value'):
            text = f'nothing: {blocker}' if blocker else 'nothing'
        elif blocker:
            text += f'. Blocker: {blocker}'
        cls = (r.get('class') or '').replace('_UI_HANDLER', '')
        out.append(f"| {n} | {job} | {cls} | {r.get('profile') or '-'} | {c.get('value', 0)} / {c.get('unset', 0)} / "
                   f"{c.get('unavailable', 0)} | {r.get('wall_seconds', '-')} | {r.get('rng_uses') or 0} | "
                   f"{text.replace('|', '/')} |")
    return '\n'.join(out) + '\n'


# ---------------------------------------------------------------------- round 2 (docs/fmdb/UI_ROUND2.md)
# A second pass over every job of the first: the keys that did not return a value are read again
# under every other binding that fits the handler (all relevant profiles, the manager, more squad
# players, the opponent, other competitions), and keys whose getter read a screen parameter are
# read with the parameter values `ui_params.assignments` proposes. Values of list and record keys
# are walked for the FourCCs of the records they hold (`note_nested`). Output: one
# types/<job>@r2.json per job with the keys tried there; `merge` and the ledger take, per key, the
# best status over all files.
R2_SUFFIX = '@r2'
R2_PERSONS = 8          # squad players tried by PERSON_UI_HANDLER besides the manager and scouts
R2_PARAM_TRIES = 6


def collect_round2_bindings(session, vm, b: dict) -> dict:
    """Bindings of the first pass plus more squad players, the next opponent (team and club) and
    every competition the managed team plays in within 60 days."""
    from fm_live_mcp import world, players
    from fm_live_mcp.fmdb import ui_recipes_news as N, ui_recipes_person as P
    from fm_live_mcp.fmdb.ui_recipes_more import open_handler
    read = session.reader.read
    view = N.viewer(vm)
    out = dict(b)
    roster = world.vector(read, view.team + 0x38, 512)
    squad = [p for p in roster if struct.unpack('<Q', read(p, 8))[0] == session.base + players.RVA[0]]
    out['squad'] = [P.person_id(vm, read, p) for p in squad]
    nxt = b.get('next_fixture') or {}
    if nxt:
        out['opponent_team'] = nxt['away'] if nxt['home'] == b['team'] else nxt['home']
    today = date.fromisoformat(view.current_date)
    rows = N.calendar(vm, days=60, start=today - timedelta(days=30), fixture_details=False)
    comps = []
    for r in rows:
        if r.get('kind') == 'fixture' and r['competition']['id'] not in comps:
            comps.append(r['competition']['id'])
    out['competitions'] = comps
    if out.get('opponent_team'):
        reg = ui_registry.default()
        code = next((c for c in reg.classes['TEAM_UI_HANDLER'].keys(4) if reg.label(c) == 'Club'), None)
        if code:
            try:
                reader = open_handler(vm, 28, dict(context(b), dref=out['opponent_team']), inputs=False)
                v = variant.to_json(reader.get(code).value)
                ref = v.get('dref') if isinstance(v, dict) else v
                if isinstance(ref, int) and ref >> 24 == 3:
                    out['opponent_club'] = ref
            except Exception:  # noqa: BLE001 - optional binding
                pass
    return out


def round2_profiles(job: str, cls: str, number: int, reg, b: dict, base_profile) -> dict:
    """{profile name: record fields} to try after the first pass (its own profile excluded)."""
    profs = profiles(b)
    out = {}
    if job.startswith('28:'):
        if cls == 'PERSON_UI_HANDLER':
            people = [('human', b.get('human')), ('scouted_player', b.get('scouted_player')), ('staff', b.get('scout'))]
            people += [(f'squad{i}', pid) for i, pid in enumerate((b.get('squad') or [])[1:R2_PERSONS + 1], 1)]
            for name, pid in people:
                if pid:
                    out[name] = {'dref': pid}
            last = profs.get('last_fixture')
            if last and b.get('player'):
                out['squad_player+last_fixture'] = dict(last, dref=b['player'])
        elif cls == 'TEAM_UI_HANDLER' and b.get('opponent_team'):
            out['opponent_team'] = {'dref': b['opponent_team']}
        elif cls == 'CLUB_UI_HANDLER' and b.get('opponent_club'):
            out['opponent_club'] = {'dref': b['opponent_club']}
        elif cls == 'COMPETITION_UI_HANDLER':
            for comp in b.get('competitions') or []:
                if comp != b.get('league'):
                    out[f'competition_{comp:#x}'] = {'dref': comp, 'comp': comp}
        return out
    fourccs = set(input_keys(reg, cls))
    row = reg.types.get(number) or {}
    server = reg.classes.get(row.get('server') or '')
    if server:
        fourccs |= set(server.slots.get('2', {}).get('fourccs', ()))
    names = [n for n in profs if n != base_profile]
    for name in names:
        out[name] = profs[name]
    if fourccs & set(PERSON_KEYS):
        out['human'] = {k: b['human'] for k in PERSON_KEYS}
        if b.get('opponent_team'):
            out['opponent_team'] = {'dref': b['opponent_team'], 'Topp': b['opponent_team']}
    for comp in (b.get('competitions') or [])[:4]:
        if fourccs & {'comp'} and comp not in (b.get('league'), b.get('ucl')):
            out[f'competition_{comp:#x}'] = {'comp': comp, 'dref': comp}
    return out


def attempt_params(vm, handler_type, record, tries: dict, *, deadline, call_us, reg, inputs=True):
    """Read keys with parameter sets: tries {code: [{rva: int}, ...]} -> {code: row}; the first set
    with which the getter returns data wins (row['params_given'] names it)."""
    from fm_live_mcp.fmdb import ui_params
    from fm_live_mcp.fmdb.ui_recipes_more import KeyReader
    vm.timeout_us = call_us
    out = {}
    try:
        handler = vm.build(handler_type, record)
    except _Stop as stop:
        return {code: {'status': 'unavailable', 'reason': f'build: {stop.reason}'} for code in tries}
    if handler.server and inputs:
        for key in input_keys(reg, handler.client_class):
            vm.transfer(handler, key)
    reader = KeyReader(vm, handler, reg)
    reader.inputs = inputs
    for code, sets in tries.items():
        best = None
        for params in sets:
            if time.time() > deadline:
                break
            try:
                r = reader.get(code, params=params)
            except Exception as exc:  # noqa: BLE001
                vm.reset_to_last()
                best = best or {'label': reg.label(code), 'status': 'unavailable', 'reason': f'reader error: {exc}'}
                continue
            row = {'label': r.label, 'status': r.status, 'protocol': r.protocol, 'ms': round(r.seconds * 1000, 1),
                   'params_given': [dict(p, value=params[int(p['rva'], 16)]) for p in ui_params.describe(params)]}
            if r.params_read:
                row['params'] = [hex(p) for p in r.params_read]
            if isinstance(r.value, Unavailable):
                row['reason'] = r.value.reason
            else:
                row['kind'] = r.kind
                full = plain_text(variant.to_json(r.value))
                row['value'] = _short(full)
            if r.status == 'value':
                best = row
                break
            if best is None or (best['status'] == 'unavailable' and r.status == 'unset'):
                best = row
        if best:
            out[code] = best
    return out


def round2_job(session, b, base: dict, reg, *, budget, call_us):
    """Second pass of one first-pass job (see the section comment)."""
    from fm_live_mcp.fmdb import ui_params
    job, cls, number = base['job'], base.get('class'), base.get('type')
    started = time.time()
    deadline = started + budget
    keys = base.get('keys') or {}
    todo = [c for c, r in keys.items() if r.get('status') != 'value']
    containers = [c for c, r in keys.items() if r.get('status') == 'value' and r.get('kind') in ('list', 'record')]
    result = {'job': job + R2_SUFFIX, 'base_job': job, 'type': number, 'class': cls, 'server': base.get('server'),
              'keys': {}, 'nested': {}, 'profiles_tried': {}, 'key_count': len(todo)}
    if base.get('build_error') or not (todo or containers):
        result['skipped'] = base.get('build_error') or 'nothing left to read'
        result['wall_seconds'] = 0
        result['counts'] = {}
        return result
    record0 = base.get('record') or {}
    dref_class = cls if job.startswith('28:') else None
    vm, memory = open_vm(session)
    try:
        # 1. the first-pass binding again: containers (nested fields) and parameter reads
        if containers:
            res = attempt(vm, number, record0, containers, deadline=deadline, call_us=call_us, reg=reg,
                          dref_class=dref_class)
            for k, v in (res.get('nested') or {}).items():
                result['nested'].setdefault(k, v + [base.get('profile')])
        tries = {}
        for code in todo:
            params = [int(p, 16) for p in keys[code].get('params') or []]
            sets = ui_params.assignments(params, b, limit=R2_PARAM_TRIES) if params else []
            if sets:
                tries[code] = sets
        if tries:
            rows = attempt_params(vm, number, record0, tries, deadline=deadline, call_us=call_us, reg=reg)
            for code, row in rows.items():
                row['profile'] = base.get('profile')
                result['keys'][code] = row
            result['profiles_tried'][f"{base.get('profile')}+params"] = dict(Counter(r['status'] for r in rows.values()))
        # 2. every other binding, on the keys still without a value
        for name, fields in round2_profiles(job, cls, number, reg, b, base.get('profile')).items():
            left = [c for c in todo if (result['keys'].get(c) or {}).get('status') != 'value']
            if not left or time.time() > deadline:
                break
            rec = dict(context(b), **fields)
            res = attempt(vm, number, rec, left, deadline=deadline, call_us=call_us, reg=reg, dref_class=dref_class)
            if res.get('build_error'):
                result['profiles_tried'][name] = {'build_error': res['build_error']}
                continue
            result['profiles_tried'][name] = res.get('counts', {})
            for code, row in res['keys'].items():
                cur = result['keys'].get(code)
                if row.get('status') == 'skipped':
                    continue
                if cur is None or (row['status'] == 'value' and cur['status'] != 'value'):
                    row['profile'] = name
                    row['record'] = fields
                    result['keys'][code] = row
            for k, v in (res.get('nested') or {}).items():
                cur = result['nested'].get(k)
                if cur is None or (cur[1] != 'value' and v[1] == 'value'):
                    result['nested'][k] = v + [name]
        result['counts'] = dict(Counter(r['status'] for r in result['keys'].values()))
        result['wall_seconds'] = round(time.time() - started, 2)
        result['rng_uses'] = vm.rng_uses
        return result
    finally:
        memory.close()


# Keys no handler class claims by an immediate in its get_property (the ledger's "no plugin handler")
# are properties of the front end's record classes (FM.UI.<Name>Reference, ui_frontend `records`).
# get_property dispatches through helper functions the immediate scan does not attribute to the
# class, so the handler of the record a property belongs to is asked for it directly: the class
# whose name matches the record class (PersonReference -> PERSON_UI_HANDLER), the aliases below,
# and for the rest a few hosts that answer most shared keys.
R2X_SUFFIX = '@r2x'
RECORD_ALIASES = {'FM.UI.CompReference': 'COMPETITION_UI_HANDLER',
                  'FM.UI.CharacterSettingsReference': 'PERSON_UI_HANDLER',
                  'FM.UI.ManagerPersonaReference': 'PERSON_UI_HANDLER',
                  'FM.UI.ManagerHistoryRecordReference': 'PERSON_UI_HANDLER',
                  'FM.UI.PlayerInjuryReference': 'PERSON_UI_HANDLER',
                  'FM.UI.WorkPermitReference': 'PERSON_UI_HANDLER',
                  'FM.UI.PromiseReference': 'PERSON_UI_HANDLER',
                  'FM.UI.PlayerTargetReference': 'PERSON_UI_HANDLER',
                  'FM.UI.SupporterProfileReference': 'CLUB_UI_HANDLER',
                  'FM.UI.FFPDetailsReference': 'CLUB_UI_HANDLER',
                  'FM.UI.FinanceWagesDataReference': 'CLUB_UI_HANDLER',
                  'FM.UI.LeagueSpecificDataReference': 'COMPETITION_UI_HANDLER',
                  'FM.UI.SeasonSummaryCompetitionReference': 'COMPETITION_UI_HANDLER',
                  'FM.UI.TacticReference': 'TEAM_UI_HANDLER',
                  'FM.UI.TeamCurrentInjuryDataReference': 'TEAM_UI_HANDLER'}
FALLBACK_HOSTS = ('PERSON_UI_HANDLER', 'TEAM_UI_HANDLER', 'CLUB_UI_HANDLER', 'COMPETITION_UI_HANDLER',
                  'GAME_UI_HANDLER', 'APPLICATION_UI_HANDLER')
# Text the game's getters return when they have nothing for the object: counted as unset.
GAME_NO_DATA_TEXTS = ('Failed to get data',)


def _record_handler(name: str) -> str:
    import re
    short = re.sub('Reference$', '', name.split('.')[-1])
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', short).upper() + '_UI_HANDLER'


def unclaimed_keys_by_host(reg) -> dict:
    """{handler class: [codes]}: every registry key no class claims, assigned to the handler of
    its front-end record class (name match or RECORD_ALIASES) or, failing that, to every
    FALLBACK_HOSTS class."""
    from fm_live_mcp.fmdb import ui_frontend
    claimed = set()
    for hc in reg.classes.values():
        try:
            claimed.update(hc.keys(4))
        except Exception:  # noqa: BLE001
            continue
    unclaimed = set(reg.labels) - claimed
    records = (ui_frontend.load_table().get('records') or {})
    out = {}
    homeless = set(unclaimed)
    for row in records.values():
        cls = row.get('class') or ''
        props = set(row.get('properties') or ()) & unclaimed
        if not props:
            continue
        host = RECORD_ALIASES.get(cls) or _record_handler(cls)
        if host in reg.classes:
            out.setdefault(host, set()).update(props)
            homeless -= props
    for host in FALLBACK_HOSTS:
        out.setdefault(host, set()).update(homeless)
    result = {k: sorted(v) for k, v in out.items()}
    result['_fallback'] = sorted(homeless)
    return result


def keep_extra_row(code, row, fallback: set) -> bool:
    """A fallback host does not own the key: only a value it returns is evidence; its unset
    answers say nothing about the key and are not recorded."""
    return row.get('status') == 'value' or code not in fallback


def run_round2_extra(session, reg, *, budget, call_us, wanted=None, redo=False, log=print):
    """Ask each first-pass job's handler for the unclaimed keys assigned to its class
    (unclaimed_keys_by_host) under the first-pass binding; PERSON also on the manager.
    Output: types/<job>@r2x.json."""
    hosts = unclaimed_keys_by_host(reg)
    fallback = set(hosts.pop('_fallback'))
    b = json.loads((OUT / 'bindings_r2.json').read_text())
    for f in sorted((OUT / 'types').glob('*.json')):
        if '@' in f.stem:
            continue
        base = json.loads(f.read_text())
        job, cls = base.get('job'), base.get('class')
        extra = hosts.get(cls)
        if not extra or base.get('build_error') or (wanted and job not in wanted):
            continue
        target = OUT / 'types' / (f.stem + R2X_SUFFIX + '.json')
        if target.exists() and not redo:
            continue
        log(f'{time.strftime("%H:%M:%S")} r2x {job} extra={len(extra)}', flush=True)
        started = time.time()
        result = {'job': job + R2X_SUFFIX, 'base_job': job, 'type': base.get('type'), 'class': cls,
                  'server': base.get('server'), 'keys': {}, 'nested': {}, 'profiles_tried': {}, 'extra_keys': True,
                  'key_count': len(extra)}
        records = [(base.get('profile'), base.get('record') or {})]
        if cls == 'PERSON_UI_HANDLER':
            records.append(('human', dict(context(b), dref=b['human'])))
        vm, memory = open_vm(session)
        try:
            for name, rec in records:
                left = [c for c in extra if (result['keys'].get(c) or {}).get('status') != 'value']
                res = attempt(vm, base.get('type'), rec, left, deadline=started + budget, call_us=call_us, reg=reg,
                              dref_class=cls if job.startswith('28:') else None)
                if res.get('build_error'):
                    result['profiles_tried'][name] = {'build_error': res['build_error']}
                    continue
                result['profiles_tried'][name] = res.get('counts', {})
                for code, row in res['keys'].items():
                    if row.get('status') == 'skipped':
                        continue
                    cur = result['keys'].get(code)
                    if cur is None or (row['status'] == 'value' and cur['status'] != 'value'):
                        row['profile'] = name
                        result['keys'][code] = row
                for k, v in (res.get('nested') or {}).items():
                    cur = result['nested'].get(k)
                    if cur is None or (cur[1] != 'value' and v[1] == 'value'):
                        result['nested'][k] = v + [name]
        except Exception as exc:  # noqa: BLE001
            result['error'] = f'{type(exc).__name__}: {exc}'
        finally:
            memory.close()
        result['keys'] = {c: r for c, r in result['keys'].items() if keep_extra_row(c, r, fallback)}
        result['counts'] = dict(Counter(r['status'] for r in result['keys'].values()))
        result['wall_seconds'] = round(time.time() - started, 2)
        target.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str))
        log(f'   -> {result["counts"]} {result["wall_seconds"]}s {result.get("error") or ""}', flush=True)


def run_round2(session, reg, *, budget, call_us, wanted=None, redo=False, log=print):
    bpath = OUT / 'bindings_r2.json'
    if bpath.exists() and not redo:
        b = json.loads(bpath.read_text())
    else:
        base_b = json.loads((OUT / 'bindings.json').read_text())
        vm, memory = open_vm(session)
        try:
            b = collect_round2_bindings(session, vm, base_b)
        finally:
            memory.close()
        bpath.write_text(json.dumps(b, indent=1, default=str))
    marker = OUT / 'in_progress_r2'
    for f in sorted((OUT / 'types').glob('*.json')):
        if R2_SUFFIX in f.stem:
            continue
        base = json.loads(f.read_text())
        job = base.get('job')
        if wanted and job not in wanted:
            continue
        target = OUT / 'types' / (f.stem + R2_SUFFIX + '.json')
        if target.exists() and not redo:
            continue
        if marker.exists() and marker.read_text() == job and not redo:
            target.write_text(json.dumps({'job': job + R2_SUFFIX, 'base_job': job, 'class': base.get('class'),
                                          'type': base.get('type'), 'crashed': True, 'keys': {}}))
            marker.unlink()
            continue
        marker.write_text(job)
        log(f'{time.strftime("%H:%M:%S")} r2 {job}', flush=True)
        try:
            result = round2_job(session, b, base, reg, budget=budget, call_us=call_us)
        except Exception as exc:  # noqa: BLE001
            result = {'job': job + R2_SUFFIX, 'base_job': job, 'class': base.get('class'), 'type': base.get('type'),
                      'keys': {}, 'error': f'{type(exc).__name__}: {exc}', 'traceback': traceback.format_exc()[-1500:]}
        target.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str))
        marker.unlink()
        nv = sum(1 for r in result.get('keys', {}).values() if r.get('status') == 'value')
        nn = sum(1 for v in result.get('nested', {}).values() if v[1] == 'value')
        log(f'   -> new values {nv}, nested fields with data {nn}, {result.get("wall_seconds")}s '
            f'{result.get("profiles_tried")} {result.get("error") or ""}', flush=True)


# ---------------------------------------------------------------------- compiled-out keys (static)
RETURN_TRUE_STUB = 0x8665C       # `mov w0, #1; ret`: the release build's body of debug-only cases
ROUND2_DATA = ROOT / 'fm_live_mcp' / 'fmdb' / 'data' / 'ui_round2.json.gz'


def _case_target_kind(words, start, pc, depth=0):
    """Walk the code a key case branches to: 'stub' when it reaches RETURN_TRUE_STUB with no call
    and no store on the way (stack-guard compares are passed), else 'code' (or 'ret')."""
    for _ in range(48):
        i = (pc - start) // 4
        if i < 0 or i >= len(words):
            return 'code'
        w = words[i]
        if (w & 0xFC000000) == 0x94000000 or (w & 0xFFFFFC1F) == 0xD63F0000:       # bl / blr
            return 'code'
        if (w & 0xFC000000) == 0x14000000:                                          # b
            off = w & 0x3FFFFFF
            off -= (1 << 26) if off >> 25 else 0
            t = pc + 4 * off
            if t == RETURN_TRUE_STUB:
                return 'stub'
            return _case_target_kind(words, start, t, depth + 1) if depth < 3 else 'code'
        if w == 0xD65F03C0:                                                         # ret
            return 'ret'
        if (w & 0xFFFFFC1F) == 0xD61F0000:                                          # br
            return 'code'
        if (w & 0x0A000000) == 0x08000000 and not (w >> 22) & 1 and (w >> 5) & 31 != 31:  # store, base != sp
            return 'code'
        pc += 4
    return 'code'


def compiled_out_scan(image, codes) -> dict:
    """{code: [case address, ...]} for registry keys whose every `mov/movk wN, key; cmp; b.eq|b.ne`
    case in the plugin text leads to RETURN_TRUE_STUB: the get_property case exists and is empty
    in this build (DebugPersonName 'adJf' at 0x37F290 is one)."""
    start, end = image.text_range
    data = image.file_bytes(start, end - start)
    words = struct.unpack(f'<{len(data) // 4}I', data[:len(data) // 4 * 4])
    want = {}
    for c in codes:
        v = int.from_bytes(c.encode('latin-1'), 'big')
        want[(v & 0xFFFF, v >> 16)] = c
    found = {}
    for i in range(len(words) - 4):
        w0, w1 = words[i], words[i + 1]
        if (w0 & 0xFFE00000) != 0x52800000 or (w1 & 0xFFE00000) != 0x72A00000 or (w0 & 31) != (w1 & 31):
            continue
        code = want.get(((w0 >> 5) & 0xFFFF, (w1 >> 5) & 0xFFFF))
        if not code:
            continue
        for j in range(2, 5):
            w = words[i + j]
            pc = start + 4 * (i + j)
            if (w & 0xFF000010) == 0x54000000:                                      # b.cond
                cond = w & 0xF
                off = (w >> 5) & 0x7FFFF
                off -= (1 << 19) if off >> 18 else 0
                if cond == 0:
                    found.setdefault(code, []).append((start + 4 * i, _case_target_kind(words, start, pc + 4 * off)))
                elif cond == 1:
                    found.setdefault(code, []).append((start + 4 * i, _case_target_kind(words, start, pc + 4)))
                break
            if (w & 0xFC000000) == 0x14000000:
                break
    return {c: [hex(a) for a, _ in cases] for c, cases in sorted(found.items())
            if all(kind == 'stub' for _, kind in cases)}


def write_round2_data(session_or_none=None):
    import gzip
    from fm_live_mcp.fmdb.image import PluginImage
    from fm_live_mcp.fmdb.live import open_live
    reg = ui_registry.default()
    if session_or_none is None:
        session = open_live()
        path = session.plugin_path
        session.close()
    else:
        path = session_or_none.plugin_path
    image = PluginImage.load(path)
    stubs = compiled_out_scan(image, list(reg.labels))
    data = {}
    if ROUND2_DATA.exists():
        with gzip.open(ROUND2_DATA, 'rt') as f:
            data = json.load(f)
    data['compiled_out'] = stubs
    data['compiled_out_stub'] = hex(RETURN_TRUE_STUB)
    with gzip.open(ROUND2_DATA, 'wt') as f:
        json.dump(data, f, sort_keys=True)
    return stubs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--round2', action='store_true', help='second pass over the first-pass results (UI_ROUND2.md)')
    ap.add_argument('--compiled-out', action='store_true', help='static scan for keys compiled out of the build')
    ap.add_argument('--round2-extra', action='store_true', help='ask handlers for the keys no class claims')
    ap.add_argument('--types', help='comma-separated job ids (e.g. 9,50,28:COMPETITION_UI_HANDLER)')
    ap.add_argument('--budget', type=float, default=120.0, help='seconds per type')
    ap.add_argument('--call-seconds', type=float, default=15.0, help='per emulated call')
    ap.add_argument('--redo', action='store_true', help='recompute types already on disk')
    ap.add_argument('--rebind', action='store_true', help='recollect bindings and dref classes')
    ap.add_argument('--merge-only', action='store_true')
    ap.add_argument('--markdown', help='write the docs table for the merged sweep to this file')
    args = ap.parse_args(argv)
    (OUT / 'types').mkdir(parents=True, exist_ok=True)
    if args.compiled_out:
        stubs = write_round2_data()
        print(json.dumps({'compiled_out': len(stubs), 'file': str(ROUND2_DATA)}))
        return
    if args.merge_only or args.markdown:
        sweep = merge()
        if args.markdown:
            Path(args.markdown).write_text(markdown_table(sweep))
        print(json.dumps({'totals': sweep['totals'], 'blockers': sweep['blockers_where_nothing_read'][:10]}))
        return
    from fm_live_mcp.fmdb.live import open_live
    reg = ui_registry.default()
    session = open_live()
    try:
        if args.round2_extra:
            run_round2_extra(session, reg, budget=args.budget, call_us=int(args.call_seconds * 1e6),
                             wanted=set(args.types.split(',')) if args.types else None, redo=args.redo)
            sweep = merge()
            print(json.dumps({'totals': sweep['totals']}))
            return
        if args.round2:
            run_round2(session, reg, budget=args.budget, call_us=int(args.call_seconds * 1e6),
                       wanted=set(args.types.split(',')) if args.types else None, redo=args.redo)
            sweep = merge()
            print(json.dumps({'totals': sweep['totals']}))
            return
        bpath = OUT / 'bindings.json'
        if bpath.exists() and not args.rebind:
            bindings = json.loads(bpath.read_text())
        else:
            vm, memory = open_vm(session)
            try:
                bindings = collect_bindings(session, vm)
            finally:
                memory.close()
            bpath.write_text(json.dumps(bindings, indent=1, default=str))
        tpath = OUT / 'dref_tables.json'
        if tpath.exists() and not args.rebind:
            tables = json.loads(tpath.read_text())
        else:
            tables = {str(k): v for k, v in dref_classes(session, reg).items()}
            tpath.write_text(json.dumps(tables, indent=1))
        wanted = set(args.types.split(',')) if args.types else None
        marker = OUT / 'in_progress'
        for job, number, cls, keys, table in jobs(reg, tables):
            if wanted and job not in wanted:
                continue
            target = OUT / 'types' / (job.replace(':', '_') + '.json')
            if target.exists() and not args.redo:
                continue
            if marker.exists() and marker.read_text() == job and not args.redo:
                # The previous run died inside this job (emulator crash): record and skip.
                target.write_text(json.dumps({'type': number, 'class': cls, 'job': job, 'crashed': True,
                                              'key_count': len(keys),
                                              'first_blocker': 'emulator process crashed'}))
                marker.unlink()
                continue
            marker.write_text(job)
            print(f'{time.strftime("%H:%M:%S")} {job} {cls} keys={len(keys)}', flush=True)
            dref = None
            if table is not None:
                obj = DREF_OBJECTS.get(cls)
                dref = bindings.get(obj) if obj else (table << 24)
            try:
                result = sweep_type(session, bindings, number, cls, keys, budget=args.budget,
                                    call_us=int(args.call_seconds * 1e6), reg=reg, dref=dref)
            except Exception as exc:  # noqa: BLE001
                result = {'type': number, 'class': cls, 'key_count': len(keys),
                          'build_error': f'sweep error {type(exc).__name__}: {exc}',
                          'traceback': traceback.format_exc()[-1500:]}
                result['first_blocker'] = first_blocker(result)
            result['job'] = job
            target.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str))
            marker.unlink()
            c = result.get('counts') or {}
            print(f'   -> {result.get("profile")} {c} {result.get("wall_seconds")}s rng={result.get("rng_uses")} '
                  f'blocker={result.get("first_blocker")}', flush=True)
        sweep = merge()
        print(json.dumps({'totals': sweep['totals'], 'blockers': sweep['blockers_where_nothing_read'][:10]}))
    finally:
        session.close()


if __name__ == '__main__':
    main()
