"""Make the reader address a new Football Manager 27 build: one command after a game update.

    PYTHONPATH=. python scripts/fm_update_build.py --installed            # the Steam install, no game needed
    PYTHONPATH=. python scripts/fm_update_build.py <plugin binary>        # any build of game_plugin
    PYTHONPATH=. python scripts/fm_update_build.py --installed --live     # then, with that build running

Static part (no game, about 2 to 4 minutes):
  1. Preserve the build's files under fmdb-runtime-research/builds/<version>/ (plugin,
     GameAssembly.dylib, global-metadata.dat, Info.plist, the .fmf data files).
  2. Resolve the fmdb core's named anchors and every address literal of the reader on the new
     plugin from the preserved pinned build (fmdb/build_update.py, fmdb/address_map.py), and the
     native code guards next to them. Writes the anchor file `<sha256>.json` and the address map
     `<sha256>.addresses.json` to $FMCP_CACHE_DIR/fmdb/anchors/.
  3. Load the whole server with that map in a subprocess (every module must import) and list
     the tools and tables each unresolved address disables.
  4. Re-derive what else is per build: functions changed between the builds, import list and the
     VM's modelled externals, operator-new allocation sizes per class, the editor.fmf schema,
     the UI handler registry, the UI registration function in GameAssembly, the front end of the
     new build (`<sha256>.ui_frontend.json.gz`: translation ids, data collections, the property
     registry, record schemas, views and the screen-parameter globals of fmdb/ui_params.py, read
     from the app's GameAssembly.dylib, global-metadata.dat, plugin and asset bundles by
     scripts/fmdb_ui_frontend.py), save routes (fmdb/persist.py), and the fingerprint index of the
     new build (so the next patch can start from it).
  5. Write the report: `<sha256>.update-report.json` next to the map, and a summary on stdout.

Live part (`--live`, the game of that build running; strictly read-only):
  live type scan (table roots and singletons) and a second derivation with it, then, with the map
  applied: fmdb_vm_check.py, fmdb_oracle.py on a sample (the decoder self-check: a hand-built
  field that disagrees with the generic getter and has no recorded finding is withheld on this
  build), fmdb_snapshot_check.py, the live tests, and with `--plans` the plan re-derivation
  (fmdb_snapshot.py, about 40 minutes). Results go into the map's `verified` and `withheld`.

The address book (fm_live_mcp/address_book.py) loads the map at the next server start.
"""
from __future__ import annotations

import os
os.environ['FMCP_ADDRESS_BOOK'] = 'off'      # derive from the pinned numbers, never from a loaded map

import argparse  # noqa: E402
import gzip  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402
import plistlib  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fm_live_mcp import address_book, players  # noqa: E402
from fm_live_mcp.fmdb import (address_census, address_map, adviser_update, anchors, build_update,  # noqa: E402
                              platform_model)

BUILDS = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research/builds')
APP = Path.home() / 'Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app'
PLUGIN_IN_APP = Path('Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin')
LIVE_TESTS = ['tests/test_fmdb_live.py', 'tests/test_fmdb_snapshot_live.py', 'tests/test_bridge.py']


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('plugin', nargs='?', help='game_plugin binary of the new build')
    ap.add_argument('--installed', action='store_true', help='the plugin of the Steam install')
    ap.add_argument('--reference', help=f'pinned plugin (default {BUILDS}/{players.VERSION}/game_plugin)')
    ap.add_argument('--builds', default=str(BUILDS), help='where each build\'s files are preserved')
    ap.add_argument('--no-preserve', action='store_true')
    ap.add_argument('--strict', action='store_true',
                    help='refuse the same-address shortcut (default when the plugin is the pinned one)')
    ap.add_argument('--out', help='output directory (default $FMCP_CACHE_DIR/fmdb/anchors)')
    ap.add_argument('--skip-diff', action='store_true', help='skip the whole-binary function diff')
    ap.add_argument('--skip-extras', action='store_true', help='skip step 4 except the import check')
    ap.add_argument('--ship-index', action='store_true',
                    help='also write the new fingerprint index into fm_live_mcp/fmdb/data/')
    ap.add_argument('--live', action='store_true', help='the game of this build is running: live part')
    ap.add_argument('--pid', type=int)
    ap.add_argument('--plans', action='store_true', help='with --live: re-derive the direct read plans (~40 min)')
    ap.add_argument('--adviser-census', action='store_true',
                    help="rebuild the tactic writer's address census (fmdb/data/adviser_census.json.gz) on the "
                         'pinned plugin and stop')
    args = ap.parse_args(argv)
    started = time.time()
    if args.adviser_census:
        return write_adviser_census(Path(args.reference) if args.reference else
                                    Path(args.builds) / players.VERSION / 'game_plugin')
    plugin = Path(args.plugin) if args.plugin else (APP / PLUGIN_IN_APP if args.installed else None)
    if plugin is None or not plugin.is_file():
        ap.error('name a plugin binary or pass --installed')
    reference_path = Path(args.reference) if args.reference else Path(args.builds) / players.VERSION / 'game_plugin'
    if not reference_path.is_file():
        print(f'The pinned build\'s plugin is not at {reference_path}. Every update resolves the pinned '
              f'addresses from it; restore it from a backup (it is build {players.VERSION}).')
        return 2
    out_dir = Path(args.out) if args.out else address_book.cache_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'plugin': str(plugin), 'steps': {}}

    step = _step(report)
    with step('load'):
        target = platform_model.load_binary(plugin)
        reference = platform_model.load_binary(reference_path)
        version = _version(plugin)
        report.update(sha256=target.sha256, version=version, reference_sha256=reference.sha256)
        print(f'build {version} plugin {target.sha256[:16]}; pinned {players.VERSION} {reference.sha256[:16]}')
        if reference.sha256 != players.SHA256:
            print('  the reference is not the pinned plugin: refusing')
            return 2
    strict = args.strict or target.sha256 == reference.sha256
    if not args.no_preserve and version and target.sha256 != reference.sha256:
        with step('preserve'):
            report['preserved'] = preserve(plugin, version, Path(args.builds))

    typed = None
    if args.live:
        with step('live type scan'):
            typed = live_scan(target, args.pid)
            report['live_scan'] = len(typed) if typed is not None else 'skipped: game of this build not running'
    with step('derive'):
        derived = build_update.derive_all(target, reference, strict=strict, typed=typed)
        doc = build_update.map_document(target, reference, derived, strict=strict, live=typed is not None,
                                        version=version)
        rows = anchors.compare(derived['named'], same_build=target.sha256 == players.SHA256)
        anchor_doc = anchors.anchor_document(target, derived['named'], live=typed is not None, rows=rows)
        anchor_path = out_dir / f'{target.sha256}.json'
        anchor_path.write_text(json.dumps(anchor_doc, indent=1))
        explained = build_update.explain(derived, reference)
        report['addresses'] = explained
        report['named_anchors'] = {'resolved': len([n for n in derived['want'] if n in derived['named']]),
                                   'total': len(derived['want']),
                                   'missing_required': doc['missing_required_anchors']}
        report['guards'] = derived['guards']['stats']
        doc['disabled_managers'] = build_update.manager_checks(target, reference, derived['values'])
        report['disabled_managers'] = doc['disabled_managers']
        if target.sha256 == reference.sha256:
            # an anchor the fmdb compare calls 'equivalent' (vm.RETURN_TRUE_RVA: any shipped
            # `mov w0,#1; ret` serves) is not a wrong value
            equivalent = {derived['want'][n] for n, (verdict, _a, _v) in rows.items() if verdict == 'equivalent'}
            wrong = [k for k, e in doc['values'].items()
                     if e['value'] is not None and e['value'] != int(k, 16) and int(k, 16) not in equivalent]
            report['wrong_on_pinned_build'] = wrong
            report['equivalent_on_pinned_build'] = sorted(f'{v:#x}' for v in equivalent if isinstance(v, int))
    with step('tactic writer'):
        # pi-fm's tactic writer (adviser/pi): its census resolved with the same function match,
        # its guards, the build facts it checks, and the functions that refuse on this build
        doc['adviser'] = adviser_update.derive(
            target, reference, plugin, app=_app_of(plugin), strict=strict,
            functions=getattr(address_map.derive, 'functions', None))
        report['adviser'] = adviser_report(doc['adviser'])
    map_path = out_dir / f'{target.sha256}.addresses.json'
    map_path.write_text(json.dumps(doc, indent=0))
    print(f'  wrote {map_path}')

    with step('import check'):
        check = import_check(map_path)
        report['import_check'] = check
        doc['verified']['checks']['import'] = check.get('ok', False)
        doc['unavailable'] = {'tools': check.get('tools', {}), 'tables': check.get('tables', {})}
        map_path.write_text(json.dumps(doc, indent=0))

    extras.match = derived.get('match')
    if not args.skip_extras:
        with step('extras'):
            report['extras'] = extras(target, reference, plugin, reference_path, version, args, explained)
        english = report['extras'].get('english_template') or {}
        if english.get('verified') and target.sha256 != reference.sha256:
            doc['english_template'] = english          # the address book re-binds the compiled English
            map_path.write_text(json.dumps(doc, indent=0))
    if args.live and typed is not None:
        with step('live checks'):
            report['live'] = live_checks(target, map_path, doc, args)
            map_path.write_text(json.dumps(doc, indent=0))
    report['seconds'] = round(time.time() - started)
    report_path = out_dir / f'{target.sha256}.update-report.json'
    report_path.write_text(json.dumps(report, indent=1, default=str))
    summary(report, doc, map_path, report_path)
    return 0 if doc['verified']['checks'].get('import') else 1


def write_adviser_census(reference_path: Path) -> int:
    """Rebuild the tactic writer's census on the pinned plugin (after editing adviser/pi/fm_tactic*)."""
    reference = platform_model.load_binary(reference_path)
    if reference.sha256 != players.SHA256:
        print(f'{reference_path} is not the pinned plugin')
        return 2
    doc = adviser_update.build_census(reference)
    address_census.save(doc, adviser_update.adviser_book.CENSUS_PATH)
    n = sum(1 for e in doc['files'].values() for row in e.values() if row['d'] == 'A')
    print(f'adviser census: {n} address values in {len(doc["files"])} files; mixed {doc["mixed"]}')
    return 0


def adviser_report(sec: dict) -> dict:
    """The tactic writer's part of the update report: counts, unresolved, refusing functions."""
    unresolved = {}
    for rel, entry in adviser_update.adviser_book.census()['files'].items():
        for key, row in entry.items():
            res = sec['per_file'].get(rel, {}).get(key) or sec['values'].get(key) or {}
            if row['d'] == 'A' and res.get('value') is None:
                unresolved[f'{rel}:{key}'] = res.get('detail') or res.get('method')
    ident = sec['identity']
    return {**sec['summary'], 'unresolved': unresolved,
            'changed_guards': [{k: s[k] for k in ('file', 'address', 'new', 'length', 'verdict')}
                               for s in sec['guards'].get('spans') or ()],
            'reviewed_guards': sec['guards'].get('reviewed') or [],
            'english': {k: v for k, v in ident['english'].items() if k != 'team'} | {'team': ident['english'].get('team')},
            'metadata': ident['metadata'], 'slice_offset': ident['slice_offset']}


# --------------------------------------------------------------------------- steps
class _step:
    def __init__(self, report):
        self.report = report

    def __call__(self, name):
        self.name = name
        return self

    def __enter__(self):
        self.t = time.time()
        print(f'[{self.name}]', flush=True)

    def __exit__(self, *exc):
        self.report['steps'][self.name] = round(time.time() - self.t, 1)
        return False


def _version(plugin: Path) -> str | None:
    for parent in plugin.parents:
        if parent.name == 'Contents' and parent.parent.suffix == '.app':
            return plistlib.loads((parent / 'Info.plist').read_bytes()).get('CFBundleShortVersionString')
    plist = plugin.with_name('Info.plist')          # a preserved build directory
    if plist.exists():
        return plistlib.loads(plist.read_bytes()).get('CFBundleShortVersionString')
    return None


def _app_of(plugin: Path) -> Path | None:
    for parent in plugin.parents:
        if parent.suffix == '.app':
            return parent
    return None


def preserve(plugin: Path, version: str, builds: Path) -> dict:
    """Copy the build's files once (read-only source; never touches the game's files)."""
    dest = builds / version
    app = _app_of(plugin)
    if app is None:
        return {'skipped': 'not inside an app bundle'}
    files = {'game_plugin': plugin, 'GameAssembly.dylib': app / 'Contents/Frameworks/GameAssembly.dylib',
             'global-metadata.dat': app / 'Contents/Resources/Data/il2cpp_data/Metadata/global-metadata.dat',
             'Info.plist': app / 'Contents/Info.plist',
             'plugin-Info.plist': plugin.parents[1] / 'Info.plist'}
    dest.mkdir(parents=True, exist_ok=True)
    done = {}
    for name, src in files.items():
        if src.is_file() and not (dest / name).exists():
            shutil.copy2(src, dest / name)
            done[name] = src.stat().st_size
    # the front end's asset bundles (about 14 MB), so a later build's front end can be compared
    # with this one from files (scripts/fmdb_ui_frontend.py reads them)
    bundles = app / 'Contents/Resources/Data/StreamingAssets/aa/StandaloneOSX'
    for name in FRONT_END_BUNDLES:
        src = bundles / name
        if src.is_file() and not (dest / 'bundles' / name).exists():
            (dest / 'bundles').mkdir(exist_ok=True)
            shutil.copy2(src, dest / 'bundles' / name)
            done[f'bundles/{name}'] = src.stat().st_size
    data = plugin.parents[1] / 'Resources/shared/data'
    if data.is_dir():
        (dest / 'fmf').mkdir(exist_ok=True)
        for f in sorted(data.glob('*.fmf')):
            if not (dest / 'fmf' / f.name).exists():
                shutil.copy2(f, dest / 'fmf' / f.name)
                done[f'fmf/{f.name}'] = f.stat().st_size
    return {'directory': str(dest), 'copied': done}


def live_scan(target, pid):
    memory, base = platform_model.open_process(target, pid)
    if memory is None:
        print(f'  live scan skipped: {base}')
        return None
    try:
        return anchors.scan_live_globals(target, memory.read, base, memory.read_many)
    finally:
        memory.close()


def _env(map_path=None):
    env = dict(os.environ)
    env.pop('FMCP_ADDRESS_BOOK', None)
    env['PYTHONPATH'] = str(ROOT)
    env.setdefault('FMCP_NO_BACKGROUND_FILL', '1')
    if map_path is not None:
        env['FMCP_ADDRESS_MAP'] = str(map_path)
    return env


IMPORT_CHECK = r'''
import json, sys, pkgutil, importlib, traceback
import fm_live_mcp
from fm_live_mcp import address_book as ab
failed = {}
for m in pkgutil.walk_packages(fm_live_mcp.__path__, 'fm_live_mcp.'):
    if m.name.endswith('.__main__'):
        continue
    try:
        importlib.import_module(m.name)
    except BaseException as exc:
        failed[m.name] = f'{type(exc).__name__}: {exc}'[:300]
tools, tables = {}, {}
try:
    from fm_live_mcp import server
    fns = ab.tool_functions(server.mcp)
    tools = ab.unavailable_tools(fns)
    tables = ab.unavailable_tables()
    count = len(fns)
except BaseException as exc:
    failed['fm_live_mcp.server'] = f'{type(exc).__name__}: {exc}'[:300]
    count = 0
stats = {}
for counts in ab._REWRITTEN.values():
    for k, v in counts.items():
        stats[k] = stats.get(k, 0) + v
print(json.dumps({'ok': not failed and ab.ACTIVE['state'] == 'mapped', 'state': ab.ACTIVE['state'],
                  'error': ab.ACTIVE.get('error'), 'failed_imports': failed, 'tool_count': count,
                  'tools': tools, 'tables': tables, 'rewritten_modules': len(ab._REWRITTEN), 'rewrites': stats}))
'''


def import_check(map_path: Path) -> dict:
    """Import every module of the package with the map applied, in a fresh interpreter."""
    proc = subprocess.run([sys.executable, '-c', IMPORT_CHECK], cwd=ROOT, env=_env(map_path),
                          capture_output=True, text=True, timeout=900)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {'ok': False, 'stderr': proc.stderr[-2000:]}


def extras(target, reference, plugin, reference_path, version, args, explained) -> dict:
    out = {}
    out_dir = Path(args.out) if args.out else address_book.cache_dir()
    t = time.time()
    if not args.skip_diff:
        from fm_live_mcp.fmdb import address_map
        out['functions'] = address_map.function_diff(target, reference)
        out['functions']['seconds'] = round(time.time() - t)
    out['imports'] = build_update.imports_diff(target, reference)
    match = getattr(extras, 'match', None)
    if match is not None:
        t2 = time.time()
        out['structure_changes'] = build_update.structure_changes(match, address_census.load())
        out['structure_changes']['seconds'] = round(time.time() - t2)
        out['emulated_functions'] = build_update.emulated_functions(match)
    out['allocation_sizes'] = build_update.allocation_diff(target, reference)
    old_fmf = reference_path.with_name('fmf') / 'editor.fmf'
    new_fmf = plugin.parents[1] / 'Resources/shared/data/editor.fmf'
    if not new_fmf.exists() and version:
        new_fmf = Path(args.builds) / version / 'fmf' / 'editor.fmf'
    try:
        out['editor_fmf'] = build_update.editor_diff(new_fmf, old_fmf) if new_fmf.exists() and old_fmf.exists() \
            else {'skipped': f'editor.fmf not found ({new_fmf})'}
    except Exception as exc:  # noqa: BLE001
        out['editor_fmf'] = {'error': f'{type(exc).__name__}: {exc}'}
    out['per_build_modules'] = {m: explained['modules'].get(m, {'unresolved': 0})
                                for m in ('fmdb/ui_params.py', 'fmdb/persist.py', 'fmdb/ui_vm.py',
                                          'fmdb/match_rating.py', 'fmdb/mgr_walk_people.py')}
    ga = (_app_of(plugin) / 'Contents/Frameworks/GameAssembly.dylib') if _app_of(plugin) else \
        plugin.with_name('GameAssembly.dylib')
    if ga.is_file():
        anchor = anchors.registry_function(platform_model.load_binary(ga))
        out['ui_registration_function'] = anchor.public() if anchor else 'not found'
    # the front end of the new build: translation ids, data collections, the property registry,
    # record schemas, views and the screen-parameter globals (scripts/fmdb_ui_frontend.py)
    t3 = time.time()
    out['front_end'] = front_end(plugin, target, reference, out_dir)
    out['front_end']['seconds'] = round(time.time() - t3, 1)
    # the English language template the compiled concern and promise texts are bound to
    t4 = time.time()
    app = _app_of(plugin)
    out['english_template'] = build_update.english_template(app) if app else {'skipped': 'no fm.app'}
    out['english_template']['seconds'] = round(time.time() - t4, 1)
    # the UI handler registry built from the new plugin (its key/label list is the pinned one with
    # the keys the new build's front end added, removed or relabelled)
    reg_out = out_dir / f'{target.sha256}.ui_registry.json.gz'
    proc = subprocess.run([sys.executable, 'scripts/fmdb_ui_registry_build.py', '--plugin', str(plugin),
                           '--out', str(reg_out)], cwd=ROOT, env=_env(), capture_output=True, text=True,
                          timeout=900)
    if proc.returncode == 0 and reg_out.exists():
        new = json.loads(gzip.decompress(reg_out.read_bytes()))
        old = json.loads(gzip.decompress((ROOT / 'fm_live_mcp/fmdb/data/ui_registry.json.gz').read_bytes()))
        match = getattr(extras, 'match', None)
        if match is not None and target.sha256 != reference.sha256:
            # the shipped registry was built on a live game and is more complete than a static
            # build: translate it slot by slot through the function match instead
            built = new
            new, out['ui_registry_translation'] = translate_registry(old, match, target.sha256)
            out['ui_registry_translation']['static_build_classes'] = len(built.get('classes', {}))
        carried = carry_handler_types(new, old, match)
        if carried:
            out['ui_handler_types'] = carried
        out['ui_registry_keys'] = registry_keys(new, old, out['front_end'])
        reg_out.write_bytes(gzip.compress(json.dumps(new, separators=(',', ':')).encode(), 9))
        out['ui_registry'] = {'path': str(reg_out), 'classes': len(new.get('classes', {})),
                              'pinned_classes': len(old.get('classes', {})),
                              'classes_added': sorted(set(new.get('classes', {})) - set(old.get('classes', {})))[:40],
                              'classes_removed': sorted(set(old.get('classes', {})) - set(new.get('classes', {})))[:40]}
    else:
        out['ui_registry'] = {'error': (proc.stderr or proc.stdout)[-800:]}
    # the fingerprint index of the new build (named anchors at their new values + literal entries)
    index_path = out_dir / f'anchors-reference-{target.sha256}.json.gz'
    if target.sha256 != reference.sha256:
        doc = json.loads((out_dir / f'{target.sha256}.addresses.json').read_text())
        values = {f'literal.{int(k, 16):#x}': e['value'] for k, e in doc['values'].items() if e['value'] is not None}
        index = anchors.reference_index(target, values)
        index_path.write_bytes(gzip.compress(json.dumps(index, separators=(',', ':')).encode(), 9))
        out['fingerprint_index'] = {'path': str(index_path), 'entries': len(index)}
        if args.ship_index:
            shipped = anchors.reference_path(target.sha256)
            shutil.copy2(index_path, shipped)
            out['fingerprint_index']['shipped'] = str(shipped)
    out['seconds'] = round(time.time() - t)
    return out


FRONT_END_PACKAGES = ('capstone', 'UnityPy')
FRONT_END_BUNDLES = ('ui-visualtreeassets_assets_gameworldvisualtreeassetpreload.bundle',
                     'ui-visualtreeassets_assets_globalvisualtreeassetpreload.bundle',
                     'ui-tableviews_assets_all.bundle', 'ui-tablefactories_assets_all.bundle',
                     'ui-datacollections_assets_all.bundle')


def _front_end_command(app: Path, out: Path, offline: bool = True) -> list | None:
    """The extractor needs capstone and UnityPy: this interpreter when it has them, else `uv run`
    with them (from uv's cache first), else None."""
    import importlib.util
    script = ['scripts/fmdb_ui_frontend.py', '--app', str(app), '--out', str(out)]
    if all(importlib.util.find_spec(p) for p in FRONT_END_PACKAGES):
        return [sys.executable, *script]
    uv = shutil.which('uv')
    if uv is None:
        return None
    return [uv, 'run', *(['--offline'] if offline else []), '--no-project', '--python', sys.executable,
            *[x for p in FRONT_END_PACKAGES for x in ('--with', p)], 'python', *script]


def front_end(plugin: Path, target, reference, out_dir: Path) -> dict:
    """Extract the new build's front-end table (scripts/fmdb_ui_frontend.py --app) into
    `<sha256>.ui_frontend.json.gz` next to the map, which `ui_frontend.table()` loads for that
    build, and report what differs from the shipped table of the pinned build."""
    from fm_live_mcp.fmdb import ui_frontend
    if target.sha256 == reference.sha256:
        return {'skipped': 'the pinned build: the shipped table is its front end'}
    app = _app_of(plugin)
    if app is None:
        return {'skipped': 'the plugin is not inside an fm.app (the front end is read from the app: '
                           'GameAssembly.dylib, global-metadata.dat and the ui-* asset bundles)'}
    dest = out_dir / f'{target.sha256}.ui_frontend.json.gz'
    proc = None
    for offline in (True, False):
        cmd = _front_end_command(app, dest, offline)
        if cmd is None:
            return {'error': 'needs capstone and UnityPy (pip) or uv; the screen tools use the pinned build\'s '
                             'front end with a note until this runs'}
        proc = subprocess.run(cmd, cwd=ROOT, env=_env(), capture_output=True, text=True, timeout=1800)
        if proc.returncode == 0 or cmd[0] == sys.executable:
            break
    if proc.returncode != 0 or not dest.exists():
        return {'error': (proc.stderr or proc.stdout)[-800:]}
    new = ui_frontend.load_table(dest)
    if new.get('build', {}).get('plugin_sha256') not in (None, target.sha256):
        dest.unlink()
        return {'error': f'the app\'s plugin is not the one updated ({new["build"]["plugin_sha256"][:12]})'}
    diff = ui_frontend.diff_tables(ui_frontend.load_table(ui_frontend.DATA), new)
    counts = {k: len(new.get(k) or {}) for k in ('registry', 'records', 'views', 'tables', 'data_collections',
                                                   'plugin_params')}
    return {'path': str(dest), 'counts': counts, 'bundles': new.get('build', {}).get('bundles', True) is not None,
            'diff': diff}


def registry_keys(new: dict, old: dict, front: dict) -> dict:
    """The key/label list of the new build's UI registry: the pinned list (recovered from the
    pinned GameAssembly) changed by what the new build's front end added, removed or relabelled
    relative to the pinned build's (`front_end`). Without a front-end diff the pinned list stays."""
    diff = (front or {}).get('diff')
    if not diff:
        return {'source': 'pinned list kept (no front-end table of this build)', 'keys': len(new['keys'])}
    keys = dict(old['keys'])
    reg = diff['registry']
    if reg['added_count'] > len(reg['added']) or reg['removed_count'] > len(reg['removed']):
        table = json.loads(gzip.decompress(Path(front['path']).read_bytes()))['registry']
        pinned = json.loads(gzip.decompress((ROOT / 'fm_live_mcp/fmdb/data/ui_frontend.json.gz').read_bytes()))['registry']
        added = {k: table[k] for k in set(table) - set(pinned)}
        removed = set(pinned) - set(table)
    else:
        added, removed = reg['added'], set(reg['removed'])

    def fourcc(key):
        # the front-end table writes a key that is not printable as '0x%08x'; the UI registry keeps
        # the four characters
        if len(key) == 10 and key.startswith('0x'):
            return int(key, 16).to_bytes(4, 'big').decode('latin1')
        return key
    added = {fourcc(k): v for k, v in added.items()}
    removed = {fourcc(k) for k in removed}
    for k in removed:
        keys.pop(k, None)
    keys.update(added)
    for k, (_a, b) in reg['relabelled'].items():
        keys[fourcc(k)] = b
    new['keys'] = keys
    new['keys_from'] = 'pinned list with the front-end registry changes of this build (scripts/fm_update_build.py)'
    return {'source': 'pinned list with this build\'s front-end registry changes', 'keys': len(keys),
            'added': sorted(added), 'removed': sorted(removed), 'relabelled': sorted(reg['relabelled'])}


def translate_registry(old: dict, match, sha256: str) -> tuple[dict, dict]:
    """The pinned UI registry carried to the new build: every handler class by its vtable (RTTI
    name and subobject offset), every slot function from the new vtable. A slot keeps what the
    pinned registry recorded about it (the keys it materialises, the keys it declares) only when
    its function is the match of the pinned one and its masked code is unchanged; otherwise the
    slot keeps only its function and says why (`changed`). Classes whose vtable has no
    counterpart are left out and counted."""
    from fm_live_mcp.fmdb import address_map
    r, t = match.r, match.t
    classes, stats = {}, {'classes': 0, 'classes_missing': [], 'slots': 0, 'slots_unchanged': 0,
                          'slots_changed': 0, 'slots_mismatched': 0}
    for name, row in old['classes'].items():
        vt = row['vtable']
        cls = r.class_name(vt)
        hit = address_map._vtable_like(r, t, vt, cls) if cls else None
        if hit is None:
            stats['classes_missing'].append(name)
            continue
        slots = {}
        for slot, entry in row['slots'].items():
            fn = t.slot(hit.value, int(slot))
            stats['slots'] += 1
            if fn is None or match.fwd.get(entry['fn']) != fn:
                stats['slots_mismatched'] += 1
                slots[slot] = {'fn': fn, 'changed': 'the slot function is not the match of the pinned one'}
            elif match.R.fp[entry['fn']] == match.T.fp[fn]:
                stats['slots_unchanged'] += 1
                slots[slot] = {**entry, 'fn': fn}
            else:
                stats['slots_changed'] += 1
                slots[slot] = {'fn': fn, 'changed': f'code differs from the pinned build ({match.how[entry["fn"]][0]} '
                                                     f'match, similarity {match.how[entry["fn"]][1]})'}
        classes[name] = {**row, 'vtable': hit.value, 'slots': slots}
        stats['classes'] += 1
    stats['classes_missing'] = stats['classes_missing'][:40]
    doc = {'build': sha256, 'keys': old['keys'], 'classes': classes, 'types': {},
           'translated_from': old.get('build')}
    return doc, stats


def carry_handler_types(new: dict, old: dict, match) -> str | None:
    """The handler types (type id -> client/server class, filled by emulating
    GAME_UI_HANDLER_FACTORY on a live game) carried from the pinned registry into the new
    build's, when the proof holds without the game: both factory functions (client and server
    slot of the factory vtable) have the same masked code on both builds and call the matched
    counterparts of the same functions in the same order, and every class a type names exists
    in the new registry. Returns what was done, or None."""
    if new.get('types') or not old.get('types') or match is None:
        return None
    from fm_live_mcp.fmdb import ui_vm
    r, t = match.r, match.t
    ref_vt = r.vtable(r.type_key('N11game_plugin23GAME_UI_HANDLER_FACTORYE'), 0)
    new_vt = t.vtable(t.type_key('N11game_plugin23GAME_UI_HANDLER_FACTORYE'), 0)
    if ref_vt is None or new_vt is None:
        return 'not carried: the factory vtable was not found'
    for slot in (ui_vm.CLIENT_FACTORY_SLOT, ui_vm.SERVER_FACTORY_SLOT):
        a, b = r.slot(ref_vt, slot), t.slot(new_vt, slot)
        if a is None or b is None or match.fwd.get(a) != b or match.R.fp[a] != match.T.fp[b]:
            return f'not carried: factory slot {slot} changed'
        mine = [('import', r.image.stubs[c]) if c in r.image.stubs else match.fwd.get(c) for c in r.callees(a)]
        theirs = [('import', t.image.stubs[c]) if c in t.image.stubs else c for c in t.callees(b)]
        if mine != theirs:
            return f'not carried: factory slot {slot} calls other functions'
    names = set(new.get('classes', {}))
    missing = {row.get(k) for row in old['types'].values() for k in ('client', 'server')} - names - {None}
    if missing:
        return f'not carried: {len(missing)} classes the types name are absent ({sorted(missing)[:3]})'
    new['types'] = old['types']
    new['types_from'] = (f'pinned build {old.get("build", "")[:12]}: both factory functions unchanged and calling '
                         f'the matched functions in the same order')
    return f'{len(old["types"])} handler types carried from the pinned build (factory unchanged)'


def live_checks(target, map_path, doc, args) -> dict:
    """The checks that prove the map on the running build (read-only), with the map applied."""
    work = address_book.cache_dir().parent.parent / 'work'
    work.mkdir(parents=True, exist_ok=True)
    oracle_out = work / f'oracle-{target.sha256[:12]}.json'
    snap_out = work / f'snapshot-check-{target.sha256[:12]}.json'
    commands = {
        'vm_check': [sys.executable, 'scripts/fmdb_vm_check.py', '--records', '6'],
        'oracle': [sys.executable, 'scripts/fmdb_oracle.py', '--players', '40', '--clubs', '20', '--competitions', '10',
                   '--stadiums', '10', '--cities', '10', '--currencies', '5', '--staff', '20', '--out', str(oracle_out)],
        'snapshot_check': [sys.executable, 'scripts/fmdb_snapshot_check.py', '--rows', '100', '--json', str(snap_out)],
        'live_tests': [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *LIVE_TESTS],
    }
    if args.plans:
        commands = {'plans': [sys.executable, 'scripts/fmdb_snapshot.py'], **commands}
    out = {}
    for name, cmd in commands.items():
        t = time.time()
        proc = subprocess.run(cmd, cwd=ROOT, env=_env(map_path), capture_output=True, text=True, timeout=4 * 3600)
        out[name] = {'returncode': proc.returncode, 'seconds': round(time.time() - t),
                     'tail': (proc.stdout + proc.stderr)[-12000:]}
        doc['verified']['checks'][name] = proc.returncode == 0
        print(f'  {name}: exit {proc.returncode} ({out[name]["seconds"]}s)', flush=True)
    if oracle_out.exists():
        doc['withheld'] = withheld_fields(json.loads(oracle_out.read_text()))
        out['withheld_fields'] = sum(len(v) for v in doc['withheld'].values())
    doc['verified']['live'] = True
    return out


def withheld_fields(report: dict) -> dict:
    """The decoder self-check: {Bridge method or module:function: {json path: reason}} for every
    hand-built field that disagreed with the generic getter on this build and has no recorded
    finding (a disagreement the pinned build already showed and explained)."""
    from fm_live_mcp.fmdb import oracle_map as om
    out = {}
    for key, row in report.get('fields', {}).items():
        if not row.get('mismatch') or row.get('finding'):
            continue
        call = om.CALLS.get(row['call'])
        if call is None:
            continue
        sample = row.get('examples', [{}])[:1]
        out.setdefault(call.method, {})[row['path']] = (
            f'disagrees with the generic getter on {row["mismatch"]} sampled records on this build '
            f'(oracle field {key}; e.g. {json.dumps(sample, default=str)[:160]})')
    return out


def summary(report, doc, map_path, report_path):
    a = report['addresses']
    print('\n== summary')
    for g, c in sorted(a['groups'].items()):
        total = c.get('resolved', 0) + c.get('unresolved', 0)
        print(f'  {g:10} {c.get("resolved", 0)} of {total} address literals resolved')
    print(f'  named fmdb anchors: {report["named_anchors"]["resolved"]} of {report["named_anchors"]["total"]}; '
          f'missing required: {len(report["named_anchors"]["missing_required"])}')
    print(f'  methods: {a["methods"]}')
    print(f'  native guards: {report["guards"]}')
    adviser = report.get('adviser')
    if adviser:
        print(f'  tactic writer: {adviser["resolved"]} of {adviser["address_sites"]} address sites; '
              f'English {"verified" if adviser["english_verified"] else "NOT verified"}, metadata '
              f'{"verified" if adviser["metadata_verified"] else "NOT verified"}; '
              f'{sum(len(v) for v in adviser["disabled"].values())} function(s) refuse on this build')
    print(f'  manager walkers disabled by the static self-check: {report["disabled_managers"] or "none"}')
    ic = report['import_check']
    print(f'  import check: ok={ic.get("ok")} failed imports={len(ic.get("failed_imports", {}))} '
          f'tools={ic.get("tool_count")} unavailable tools={len(ic.get("tools", {}))} '
          f'unavailable tables={len(ic.get("tables", {}))}')
    for name, reasons in list(ic.get('tools', {}).items())[:25]:
        print(f'    {name}: {reasons[0]}')
    for key, u in list(a['unresolved'].items())[:40]:
        print(f'  unresolved {key}: {u["was"]}; {u["why"]}; used at {u["uses"][0]}')
    if 'wrong_on_pinned_build' in report:
        print(f'  values that differ from the pinned numbers on the pinned build: {len(report["wrong_on_pinned_build"])}')
    ex = report.get('extras', {})
    if 'functions' in ex:
        f = ex['functions']
        print(f'  functions: {f["unchanged"]} of {f["pinned_functions"]} pinned functions unchanged; '
              f'{f["changed_or_removed"]} changed or removed; {f["new_or_changed"]} new or changed')
    if 'imports' in ex:
        print(f'  imports: +{len(ex["imports"]["added"])} -{len(ex["imports"]["removed"])}; modelled externals '
              f'no longer imported {ex["imports"]["modelled_no_longer_imported"]}')
    if 'structure_changes' in ex:
        sc = ex['structure_changes']
        print(f'  structure offsets: {sc["candidates"]} changed loads/stores/adds in matched functions, '
              f'{sc["confirmed"]} confirmed by alignment; {len(sc["in_functions_the_source_names"])} inside '
              f'functions the source names ({sum(1 for c in sc["in_functions_the_source_names"] if c["confirmed"])} '
              f'confirmed)')
    if 'ui_handler_types' in ex:
        print(f'  UI handler types: {ex["ui_handler_types"]}')
    fe = ex.get('front_end') or {}
    if 'diff' in fe:
        d = fe['diff']
        print(f'  front end: {fe["path"]} ({fe.get("seconds")}s); registry +{d["registry"]["added_count"]} '
              f'-{d["registry"]["removed_count"]} relabelled {len(d["registry"]["relabelled"])}; data collections '
              f'changed {len(d["data_collections"]["changed"])} (translation ids +{d["data_collections"]["translation_ids"]["added"]} '
              f'-{d["data_collections"]["translation_ids"]["removed"]}); records changed {d["records"]["changed_count"]}, '
              f'views changed {d["views"]["changed_count"]}; screen parameters +{len(d["plugin_params"]["added"])} '
              f'-{len(d["plugin_params"]["removed"])}')
    elif fe:
        print(f'  front end: {fe.get("skipped") or fe.get("error")}')
    if 'emulated_functions' in ex:
        print('  functions the emulator calls by address: ' + '; '.join(
            f'{k} {v["functions"]} ({v.get("unchanged", 0)} unchanged, {v.get("changed", 0)} changed, '
            f'{v.get("unmatched", 0)} unmatched)' for k, v in ex['emulated_functions'].items()))
    if 'allocation_sizes' in ex:
        print(f'  allocation sizes changed: {ex["allocation_sizes"]["changed"]} classes '
              f'({len(ex["allocation_sizes"]["changed_db_records"])} db records)')
    if 'editor_fmf' in ex:
        e = ex['editor_fmf']
        print('  editor.fmf: ' + ('unchanged' if e.get('same_file') else
                                  json.dumps({k: (len(v) if isinstance(v, (list, dict)) else v)
                                              for k, v in e.items()})))
    print(f'  steps (s): {report["steps"]}; total {report["seconds"]}s')
    print(f'  map: {map_path}\n  report: {report_path}')


if __name__ == '__main__':
    sys.exit(main())
