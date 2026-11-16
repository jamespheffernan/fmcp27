"""Which plugin build the fmdb modules address, and the switch to another build's anchors.

The modules carry the RVAs of build 27.0.0.2493426 as constants (tables.CLASSES,
database.TABLES, players.RVA, world.*, vm.*, ui_vm.*, ui_recipes_*, extras.PLAYER_SLOTS).
For another build, `scripts/fmdb_rebase.py <plugin> --live` writes an anchor file
(`$FMCP_CACHE_DIR/fmdb/anchors/<sha256>.json`, see anchors.py) and `activate(plugin)`
rebinds those module constants from it. Every consumer reads the constants through the
module at call time, so nothing else changes.

What is deliberately NOT rebound: `players.VERSION` and `players.SHA256`. They gate the
168 hand-built tools through the Bridge, which keep their own 1,000+ pinned addresses and
must stay refused on a build they were not checked on. On another build only the fmdb
engine (`Engine.open_build`) runs, and every direct plan is re-derived and verified for that
build (the plan cache is keyed by plugin sha256).

An anchor file that lacks one of the REQUIRED anchors is refused as a whole; optional
anchors that are missing (UI recipe helpers, native extras slots) are set to None, which
makes exactly those features refuse.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .. import database, players, world
from . import anchors, extras, tables, ui_recipes_more, ui_recipes_news, ui_recipes_person, ui_vm, vm

PINNED_SHA256 = players.SHA256
PINNED_VERSION = players.VERSION

REQUIRED_PREFIXES = ('tables.CLASSES.', 'database.TABLES.', 'players.', 'world.', 'vm.')


class BuildError(RuntimeError):
    """The running plugin build cannot be addressed; the message says what to do."""


ACTIVE = {'sha256': PINNED_SHA256, 'version': PINNED_VERSION, 'source': 'pinned', 'missing': []}
_PINNED_STATE = None


def _capture():
    """Every module constant `apply` may rebind (to restore the pinned build)."""
    return {
        (tables, 'CLASSES'): dict(tables.CLASSES), (database, 'TABLES'): dict(database.TABLES),
        (players, 'RVA'): players.RVA, (players, 'STAFF_RVA'): players.STAFF_RVA,
        (world, 'GAME_ROOT'): world.GAME_ROOT, (world, 'SAVE_ROOT'): world.SAVE_ROOT,
        (world, 'CURRENT_DATE'): world.CURRENT_DATE, (world, 'TYPES'): dict(world.TYPES),
        **{(vm, n): getattr(vm, n) for n in ('VARIANT_REGISTRY_RVA', 'APP_GLOBAL_RVA', 'APP_BYPASS_ORIGINAL_RVA',
                                             'RETURN_TRUE_RVA', 'INTERCEPTORS', 'THREAD_FLAG_RVA',
                                             'THREAD_MAIN_RVA', 'THREAD_OTHER_RVA', 'TLV_REFUSED')},
        **{(ui_vm, n): getattr(ui_vm, n) for n in ('FACTORY_VTABLE_RVA', 'UI_HANDLER_BASE_VTABLE_RVA', 'INTERCEPTS',
                                                   'THREAD_FLAG_RVA', 'THREAD_MAIN_RVA', 'THREAD_OTHER_RVA',
                                                   'TLV_REFUSED')},
        **{(ui_recipes_person, n): getattr(ui_recipes_person, n)
           for n in ('BAG_INSERT_RVA', 'PARAM_LOOKUP_RVA', 'PARAM_HOOK_RVA', 'PARAM_FOUND_RVA', 'INT32_VARIANT_RVA',
                     'VISION_OWNER', 'VISION_FILTER', 'VISION_FLAG')},
        **{(ui_recipes_more, n): getattr(ui_recipes_more, n) for n in ('PARAM_LOOKUP_RVA', 'INT32_VARIANT_RVA')},
        **{(ui_recipes_news, n): getattr(ui_recipes_news, n)
           for n in ('NEWS_MANAGER_RVA', 'RESOLVE_RVA', 'SI_DATE_TRAITS_RVA')},
        (extras, 'PLAYER_SLOTS'): dict(extras.PLAYER_SLOTS), (extras, 'PRIMARY'): dict(extras.PRIMARY),
    }


def plugin_sha256(path) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def values(doc: dict) -> dict:
    """{anchor name: value} of an anchor document (lists back to tuples)."""
    out = {}
    for name, entry in doc['anchors'].items():
        v = entry['value']
        out[name] = tuple(v) if isinstance(v, list) else v
    return out


def missing_required(found: dict) -> list:
    return sorted(n for n in anchors.pinned() if n.startswith(REQUIRED_PREFIXES) and found.get(n) is None)


def apply(found: dict, *, sha256: str, version: str | None, source: str):
    """Rebind the module constants to `found` ({anchor name: value}, names as anchors.pinned())."""
    global _PINNED_STATE
    missing = missing_required(found)
    if missing:
        raise BuildError(f'anchor set for plugin {sha256[:12]} lacks {len(missing)} required anchors '
                         f'({", ".join(missing[:6])}{"..." if len(missing) > 6 else ""}); run '
                         'scripts/fmdb_rebase.py <plugin> --live with this build running')
    if _PINNED_STATE is None:
        _PINNED_STATE = _capture()
    pinned_state = _PINNED_STATE
    get = found.get
    classes = {}
    for _rva, (cls, _getter, primary) in pinned_state[(tables, 'CLASSES')].items():
        classes[get(f'tables.CLASSES.{cls}.vtable')] = (
            cls, get(f'tables.CLASSES.{cls}.getter'),
            None if primary is None else get(f'tables.CLASSES.{cls}.primary'))
    tables.CLASSES = classes
    database.TABLES = {kind: (get(f'database.TABLES.{kind}.root'), get(f'database.TABLES.{kind}.vtable'), name)
                       for kind, (_r, _v, name) in pinned_state[(database, 'TABLES')].items()}
    players.RVA = tuple(get(f'players.RVA[{i}]') for i in range(3))
    players.STAFF_RVA = tuple(get(f'players.STAFF_RVA[{i}]') for i in range(3))
    for name in ('GAME_ROOT', 'SAVE_ROOT', 'CURRENT_DATE'):
        setattr(world, name, get(f'world.{name}'))
    world.TYPES = {kind: (get(f'world.TYPES.{kind}'), name)
                   for kind, (_v, name) in pinned_state[(world, 'TYPES')].items()}
    for name in ('VARIANT_REGISTRY_RVA', 'APP_GLOBAL_RVA', 'APP_BYPASS_ORIGINAL_RVA', 'RETURN_TRUE_RVA',
                 'THREAD_FLAG_RVA', 'THREAD_MAIN_RVA', 'THREAD_OTHER_RVA'):
        setattr(vm, name, get(f'vm.{name}'))
    vm.INTERCEPTORS = tuple(get(f'vm.INTERCEPTORS.{rtti}') for _g, rtti, _s, _o in pinned_state[(vm, 'INTERCEPTORS')]
                            if get(f'vm.INTERCEPTORS.{rtti}') is not None)
    labels = [label for _d, label in sorted(pinned_state[(vm, 'TLV_REFUSED')].items())]
    vm.TLV_REFUSED = {get(f'vm.TLV_REFUSED[{i}]'): label for i, label in enumerate(labels)
                      if get(f'vm.TLV_REFUSED[{i}]') is not None}
    ui_vm.FACTORY_VTABLE_RVA = get('ui_vm.FACTORY_VTABLE_RVA')
    ui_vm.UI_HANDLER_BASE_VTABLE_RVA = get('ui_vm.UI_HANDLER_BASE_VTABLE_RVA')
    ui_vm.INTERCEPTS = {get(f'ui_vm.INTERCEPTS.{label}'): (label, fn)
                        for _r, (label, fn) in pinned_state[(ui_vm, 'INTERCEPTS')].items()
                        if get(f'ui_vm.INTERCEPTS.{label}') is not None}
    for name in ('THREAD_FLAG_RVA', 'THREAD_MAIN_RVA', 'THREAD_OTHER_RVA', 'TLV_REFUSED'):
        setattr(ui_vm, name, getattr(vm, name))       # ui_vm imported these names from vm
    for module in (ui_recipes_person, ui_recipes_more, ui_recipes_news):
        short = module.__name__.rsplit('.', 1)[1]
        for (mod, name) in pinned_state:
            if mod is module:
                setattr(module, name, get(f'{short}.{name}'))
    extras.PLAYER_SLOTS = {slot: (get(f'extras.PLAYER_SLOTS.{slot}.regular'),
                                  get(f'extras.PLAYER_SLOTS.{slot}.virtual') if virtual is not None else None)
                           for slot, (_r, virtual) in pinned_state[(extras, 'PLAYER_SLOTS')].items()}
    extras.PRIMARY = {name: offset for _, (name, _, offset) in tables.CLASSES.items() if offset is not None}
    optional_missing = sorted(n for n in anchors.pinned() if found.get(n) is None)
    ACTIVE.update(sha256=sha256, version=version, source=source, missing=optional_missing)
    return ACTIVE


def restore_pinned():
    """Put the pinned build's constants back (after `apply`)."""
    if _PINNED_STATE is None:
        return ACTIVE
    for (module, name), value in _PINNED_STATE.items():
        setattr(module, name, value)
    ACTIVE.update(sha256=PINNED_SHA256, version=PINNED_VERSION, source='pinned', missing=[])
    return ACTIVE


def activate(plugin_path, *, directory: Path | None = None) -> dict:
    """Address the build at `plugin_path`: the pinned constants for the pinned build, else the
    anchor file for that plugin's sha256 (BuildError when there is none)."""
    sha = plugin_sha256(plugin_path)
    if sha == ACTIVE['sha256']:
        return ACTIVE
    if sha == PINNED_SHA256:
        return restore_pinned()
    doc = anchors.load_anchor_file(sha, directory)
    if doc is None:
        raise BuildError(f'Plugin build {sha[:12]} is not the pinned {PINNED_VERSION} and has no anchor file. '
                         f'With that build running, run: scripts/fmdb_rebase.py "{plugin_path}" --live')
    return apply(values(doc), sha256=sha, version=doc.get('version'), source=f'anchors:{doc.get("version")}')


def is_pinned() -> bool:
    return ACTIVE['sha256'] == PINNED_SHA256
