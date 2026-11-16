"""Two-build emulation comparison of pi-fm's tactic writer (the evidence behind the tactic writer's
27.0.1 reviews in fmdb/data/address_overrides.json; docs/GAME_UPDATE.md, "The tactic writer").

    # 1. the .tac payloads of the templates (the codec's Python, which has zstandard)
    <codec python> scripts/adviser_two_build.py extract --templates <Tactics folder> --tacs DIR
    # 2. each build (the reader's Python, which has unicorn), chosen by the environment:
    FMCP_ADDRESS_BOOK=off PI_FM_NATIVE_BINARY=<pinned plugin in its app bundle tree> \
        python scripts/adviser_two_build.py run --tacs DIR --out pinned.json [--request R.json] [--limit N] [--targets]
    FMCP_ADDRESS_MAP=<map> PI_FM_NATIVE_BINARY=<installed plugin> \
        python scripts/adviser_two_build.py run --tacs DIR --out mapped.json [...]
    # 3. compare
    python scripts/adviser_two_build.py compare pinned.json mapped.json

`run` loads the writer's modules the way production does (fm_live_mcp.adviser_book: rewritten for a
mapped build, as written for the pinned one) and, for every payload, records what the writer
consumes from the game's code: the three loader stages (acceptance, cursor, names, mentality,
flags, negative controls), the 22 typed records, team flags, phase correspondence, the
serializer's output, the legal roles per slot with the stored word of each, the player-instruction availability matrix,
the current-role profiles, every legal single-slot role change (records and serialization after
each), the team-instruction commands, the player-instruction setters; on one creator the legal
roles (and their stored words) of each of the 26 canonical positions in both phases; the request given with
--request; and with --targets the specific-position marking setter for every target.

The serializer's bytes 11..14 are the game version the writer stamps (27.0.0: 1b000000, 27.0.1:
1b000100); the tactic writer keeps the source's (fm_tactic_native_authoring._preserve_header), so
serializations are compared with the source's bytes there and the stamps reported apart.

The source-identity guards (role catalog NATIVE_GUARDS, team NATIVE_SPANS, the English and
metadata hashes) are bypassed here on both builds alike: the point is to compare what the game's
code does, which is the evidence those guards' reviews rest on.
"""
import argparse, hashlib, importlib.util, json, os, struct, sys, time, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PI = ROOT / 'adviser/pi'


def load():
    os.environ.setdefault('PI_FM_TACTIC_READER_ROOT', str(ROOT))
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(PI))
    from fm_live_mcp import adviser_book
    adviser_book.install(PI)
    import fm_tactic_native_authoring as native
    import fm_tactic_role_catalog as cat
    import fm_tactic_team_instructions as team
    # bypass the source-identity guards on both builds alike (see the module docstring)
    cat.verify_native = lambda creator: None
    team.verify_sources = lambda creator: None
    native.verify_assets = lambda: cat.catalog()
    return adviser_book, native, cat, team


def legal_with_words(cat, creator, phase, slot):
    """The legal roles at one record and the stored word the writer would write for each."""
    legal = cat.legal_roles(creator, phase, slot)
    return legal | {'stored_words': {
        role: f'{cat.validate_role_request(creator, phase, slot, role)["native_word"]:016x}'
        for role in legal['legal_roles']}}


def hx(b):
    return b.hex() if isinstance(b, (bytes, bytearray)) else b


def safe(fn, *a, **k):
    try:
        return {'ok': fn(*a, **k)}
    except Exception as exc:  # noqa: BLE001
        return {'error': f'{type(exc).__name__}: {exc}'[:300]}


HEADERS = set()


def ser(native, c, payload):
    """sha256 of the serializer's output with the source's bytes 11..14 kept (as the writer
    delivers it); the raw header bytes the game's writer stamped are collected in HEADERS."""
    raw = c.serialize()
    HEADERS.add(raw[:16].hex())
    return hashlib.sha256(native._preserve_header(raw, payload)).hexdigest()


def state(native, c, payload):
    return {'records': c.records(), 'team_flags': bytes(c.uc.mem_read(native.CREATOR + 0xE0, 16)).hex(),
            'mentality': c.uc.mem_read(native.CREATOR + 0x105, 1)[0],
            'serialization': ser(native, c, payload)}


def run(out_path, tacs, request=None, limit=0, targets=False):
    t0 = time.time()
    ab, native, cat, team = load()
    data = cat.catalog()
    out = {'adviser_state': ab.state(), 'payloads': {}, 'canonical_positions': None, 'acceptance': None}
    index = json.loads((tacs / 'index.json').read_text())
    for entry in index[:limit or len(index)]:
        if 'tac' not in entry:
            continue
        payload = (tacs / entry['tac']).read_bytes()
        res = {'template': entry['template']}
        res['validate'] = safe(native.core.validate_payload, payload, controls=True)
        try:
            c = native.NativeCreator(payload)
        except Exception as exc:  # noqa: BLE001
            res['creator'] = f'{type(exc).__name__}: {exc}'[:300]
            out['payloads'][entry['tac']] = res
            continue
        res['loaded'] = {k: v for k, v in c.loaded.items() if k not in ('actual_instructions', 'heap_bytes')}
        res['loaded_instructions'] = c.loaded.get('actual_instructions')
        raw = c.serialize()
        res['serializer_raw_sha256'] = hashlib.sha256(raw).hexdigest()
        res['serializer_header_hex'] = raw[:16].hex()
        res['serializer_equals_source_after_header'] = native._preserve_header(raw, payload) == payload
        res['serializer_raw_equals_source'] = raw == payload
        res['state'] = state(native, c, payload)
        res['phase_correspondence'] = safe(native._phase_correspondence, c)
        res['legal'] = [safe(legal_with_words, cat, c, r['phase'], r['slot']) for r in c.records()]
        def avail(r, o):
            got = safe(cat.instruction_availability, c, r['phase'], r['slot'], o)
            return [got['ok']['native_available'], got['ok']['native_state']] if 'ok' in got else got['error']
        res['availability'] = {f'{r["phase"]}/{r["slot"]}': [avail(r, o) for o in range(1, 43)] for r in c.records()}
        res['current'] = [safe(native.current_instructions, c, r['phase'], r['slot']) for r in c.records()]
        # every legal single-slot role change, applied in sequence on one creator per slot
        changes = {}
        for legal in res['legal']:
            if 'ok' not in legal:
                continue
            phase, slot = legal['ok']['phase'], legal['ok']['position_index']
            cc = native.NativeCreator(payload)
            seq = []
            for choice in legal['ok']['legal_roles']:
                r = safe(native._set_roles, cc, [{'phase': phase, 'position_index': slot, 'role': choice}])
                seq.append({'choice': choice,
                            'result': 'ok' if 'ok' in r else r['error'],
                            'record': next(x for x in cc.records() if x['phase'] == phase and x['slot'] == slot),
                            'serialization': ser(native, cc, payload)})
            changes[f'{phase}/{slot}'] = seq
        res['role_changes'] = changes
        # team instruction commands: each option alone, then the acceptance set
        tc = native.NativeCreator(payload)
        teams = {}
        for oid, name in team.OPTION_NAMES.items():
            if oid == 41:
                continue
            r = safe(team.apply_team_instructions, tc, [name])
            teams[name] = r.get('error') or bytes(tc.uc.mem_read(native.CREATOR + 0xE0, 16)).hex()
        r = safe(team.apply_team_instructions, tc, ['Pass Into Space', 'Play Through Press', 'Low Crosses',
                                                   'Work Ball Into Box', 'Focus Play Through The Middle',
                                                   'Narrower', 'Counter', 'Mid Block', 'Counter-Press'])
        teams['acceptance set'] = r.get('error') or bytes(tc.uc.mem_read(native.CREATOR + 0xE0, 16)).hex()
        teams['serialization'] = ser(native, tc, payload)
        res['team'] = teams
        # player-instruction setters: every available option per slot, one at a time, after a reset
        pis = {}
        pc = native.NativeCreator(payload)
        names = {r['native_option']: r['metadata_name'] for r in data['player_instructions']}
        for rec in pc.records():
            key = f'{rec["phase"]}/{rec["slot"]}'
            avail = res['availability'][key]
            prow = []
            for o in range(1, 43):
                if o in (34, 35) or not (isinstance(avail[o - 1], list) and avail[o - 1][0]):
                    continue
                r = safe(native._set_player_instructions, pc, [{'phase': rec['phase'], 'position_index': rec['slot'],
                                                                'instructions': [names[o]]}], data)
                prow.append([o, 'ok' if 'ok' in r else r['error'],
                            native.current_instructions(pc, rec['phase'], rec['slot'])['stored_bits']])
            pis[key] = prow
        pis['serialization'] = ser(native, pc, payload)
        res['player_instructions'] = pis
        res['seconds'] = round(time.time() - t0)
        out['payloads'][entry['tac']] = res
        print(entry['template'], res['seconds'], 's', flush=True)
    # legal roles and their stored words for every canonical position, both phases
    first = next(r for r in index if 'tac' in r)
    c = native.NativeCreator((tacs / first['tac']).read_bytes())
    canon = {}
    for phase, base in native.PHASE_OFFSETS.items():
        pointer = native.CREATOR + base + 72 * 1
        saved = bytes(c.uc.mem_read(pointer, 72))
        for pos in data['positions']:
            c.uc.mem_write(pointer, struct.pack('<I', pos['native_mask']))
            canon[f'{phase}/{pos["compiled_english_name"] or "+".join(pos["metadata_mask_components"])}'] = \
                safe(legal_with_words, cat, c, phase, 1).get('ok', {}).get('stored_words') or 'error'
        c.uc.mem_write(pointer, saved)
    out['canonical_positions'] = canon
    # the request given with --request, on its template
    if request is not None:
        out['acceptance'] = authored(native, index, tacs, request)
    if targets:
        out['targets'] = marking_targets(native, cat, data, index, tacs, limit)
    out['writer_headers'] = sorted(HEADERS)
    out['seconds'] = round(time.time() - t0)
    Path(out_path).write_text(json.dumps(out, indent=0, default=hx))
    print('done', out['seconds'], 's')


def authored(native, index, tacs, request):
    req = json.loads(Path(request).read_text())
    acc = next(r for r in index if r['template'] == Path(req['template_path']).name)
    payload = (tacs / acc['tac']).read_bytes()
    try:
        output, receipt = native.author(payload, req['native_authoring'])
        return {'output_sha256': hashlib.sha256(output).hexdigest(), 'bytes': len(output),
                             'records': receipt['native_records'], 'team_flags': receipt['native_team_flags_hex'],
                             'roles': [{k: r[k] for k in ('phase', 'position_index', 'before_word', 'after_word', 'changed')}
                                       for r in receipt['roles']],
                             'team': receipt['team_instructions']['selected_native_option_ids'],
                             'current': receipt['current_role_instructions'],
                             'phase_correspondence': receipt['phase_correspondence']['after']}
    except Exception as exc:  # noqa: BLE001
        return {'error': f'{type(exc).__name__}: {exc}', 'trace': traceback.format_exc()[-1500:]}


def compare(a_path, b_path):
    a, b = json.loads(Path(a_path).read_text()), json.loads(Path(b_path).read_text())
    diffs, counts = [], {}

    def walk(x, y, path):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y)):
                walk(x.get(k), y.get(k), f'{path}.{k}')
        elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
            for i, (p, q) in enumerate(zip(x, y)):
                walk(p, q, f'{path}[{i}]')
        else:
            counts['leaves'] = counts.get('leaves', 0) + 1
            if x != y:
                diffs.append((path, x, y))
    skip = {'adviser_state', 'seconds', 'writer_headers'}
    print('writer headers:', a.get('writer_headers'), '|', b.get('writer_headers'))
    info = {'seconds', 'loaded_instructions', 'actual_instructions', 'heap_bytes', 'serializer_raw_sha256',
            'serializer_header_hex', 'serializer_raw_equals_source'}
    for side, doc in (('A', a), ('B', b)):
        heads = {p.get('serializer_header_hex', '')[22:30] for p in doc['payloads'].values()}
        raw_eq = sum(1 for p in doc['payloads'].values() if p.get('serializer_raw_equals_source'))
        print(f'{side}: writer bytes 11..14 {sorted(heads)}; raw serialization equals source in {raw_eq} of {len(doc["payloads"])}')

    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k not in info}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    a, b = strip(a), strip(b)
    walk({k: v for k, v in a.items() if k not in skip}, {k: v for k, v in b.items() if k not in skip}, '')
    print('compared leaves:', counts.get('leaves'), 'differences:', len(diffs))
    for path, x, y in diffs[:200]:
        print(' ', path, '|', json.dumps(x)[:160], '|', json.dumps(y)[:160])
    return diffs


def marking_targets(native, cat, data, index, tacs, limit):
    """mark_specific_position for each of the 25 non-goalkeeper targets on every out-of-possession
    slot where PI 35 is available ('ok' includes the writer's own accessor checks)."""
    targets = [p['compiled_english_name'] or '+'.join(p['metadata_mask_components'])
               for p in data['positions'] if p['native_mask'] != 1]
    out = {}
    for entry in index[:limit or len(index)]:
        payload = (tacs / entry['tac']).read_bytes()
        c = native.NativeCreator(payload)
        rows = {}
        for rec in c.records():
            if rec['phase'] != 'out_of_possession':
                continue
            if not cat.instruction_availability(c, rec['phase'], rec['slot'], 35)['native_available']:
                rows[str(rec['slot'])] = 'PI35 unavailable'
                continue
            got = []
            for name in targets:
                r = safe(native._set_player_instructions, c, [{
                    'phase': 'out_of_possession', 'position_index': rec['slot'], 'instructions': [],
                    'mark_specific_position': name}], data)
                # 'ok' includes the writer's own checks: the target accessor returns the mask and the
                # specific-player mode is cleared (fm_tactic_native_authoring._set_player_instructions)
                got.append([name, 'ok' if 'ok' in r else r['error'][:160],
                            native.current_instructions(c, 'out_of_possession', rec['slot'])['stored_bits'],
                            hashlib.sha256(native._preserve_header(c.serialize(), payload)).hexdigest()])
            rows[str(rec['slot'])] = got
        out[entry['tac']] = rows
    return out


def extract(templates, tacs):
    """The .tac member of every .fmf in `templates` (read-only) into `tacs`, with index.json."""
    os.environ.setdefault('PI_FM_TACTIC_READER_ROOT', str(ROOT))
    spec = importlib.util.spec_from_file_location('writer_for_two_build', PI / 'fm-tactic-files.py')
    writer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(writer)
    tacs.mkdir(parents=True, exist_ok=True)
    index = []
    for path in sorted(Path(templates).glob('*.fmf')):
        try:
            _p, _blob, members = writer.read_template(str(path))
        except Exception as exc:  # noqa: BLE001
            index.append({'template': path.name, 'error': f'{type(exc).__name__}: {exc}'})
            continue
        tac = members['.tac']
        name = hashlib.sha256(tac).hexdigest()[:16] + '.tac'
        (tacs / name).write_bytes(tac)
        index.append({'template': path.name, 'tac': name, 'tac_sha256': hashlib.sha256(tac).hexdigest(),
                      'bytes': len(tac), 'major': tac[11]})
    (tacs / 'index.json').write_text(json.dumps(index, indent=1))
    return index


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('extract')
    e.add_argument('--templates', required=True)
    e.add_argument('--tacs', required=True)
    r = sub.add_parser('run')
    r.add_argument('--tacs', required=True)
    r.add_argument('--out', required=True)
    r.add_argument('--request')
    r.add_argument('--limit', type=int, default=0)
    r.add_argument('--targets', action='store_true')
    c = sub.add_parser('compare')
    c.add_argument('a')
    c.add_argument('b')
    args = ap.parse_args(argv)
    if args.cmd == 'extract':
        index = extract(Path(args.templates), Path(args.tacs))
        print(len(index), 'templates')
    elif args.cmd == 'run':
        run(args.out, Path(args.tacs), args.request, args.limit, args.targets)
    else:
        return 1 if compare(args.a, args.b) else 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
