"""One attached game process for the fmdb query layer.

`Engine` bundles everything the snapshot and the tools need for one running FM27:

* the existing Bridge build/identity check (pinned version, plugin SHA256, loaded
  Mach-O UUID); a different build fails closed;
* a `LiveMemory` (batched scatter reads through `fm_fast_reader`) with its page cache;
* the editor catalog parsed from the plugin's own `editor.fmf`;
* a `PropertyVM` that reads through the LiveMemory page cache (`fresh()` drops both
  caches when current bytes are needed);
* a lock so MCP tool threads serialise;
* the save identity and current game date (`world.loaded`: save name, save count,
  CURRENT_DATE at plugin RVA 0x56B1DB8).

Everything here is read-only against the game: no memory writes, no in-process calls.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import struct
import threading

from .. import database, players, world
from . import tables

DEFAULT_CACHE = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmcp-source-cache')
VM_PAGE = 4096
VM_PAGE_LIMIT = 3000


def cache_root() -> Path:
    """`$FMCP_CACHE_DIR/fmdb`, defaulting to the external-disk source cache."""
    env = os.environ.get('FMCP_CACHE_DIR')
    return (Path(env) if env else DEFAULT_CACHE) / 'fmdb'


def _arm64_header(path) -> bytes:
    """First 16 KiB of the ARM64 slice of a (possibly fat) Mach-O file."""
    with Path(path).open('rb') as stream:
        head = stream.read(4096)
        offset = 0
        if head[:4] == b'\xca\xfe\xba\xbe':
            for i in range(struct.unpack_from('>I', head, 4)[0]):
                cpu, _, off, _, _ = struct.unpack_from('>IIIII', head, 8 + 20 * i)
                if cpu == 0x0100000C:
                    offset = off
        stream.seek(offset)
        return stream.read(16384)


class EngineError(RuntimeError):
    """The engine cannot serve the request; the message says what to do next."""


# Free space required before writing into the cache. A snapshot build writes a new file of about
# 250 MB next to the old one and then renames it; a knowledge build grows its store to about
# 300 MB; the background fill only rewrites pages of the existing snapshot in small transactions.
MIN_FREE_BUILD = 1024 ** 3           # 1 GiB: snapshot and knowledge builds
MIN_FREE_FILL = 256 * 1024 ** 2      # 256 MiB: background fill, on-demand column emulation


class CacheSpaceError(EngineError):
    """Not enough free space in the cache directory; nothing was written."""


def free_bytes(path) -> int:
    """Free bytes on the volume holding `path` (or its nearest existing parent). On an APFS
    volume with a quota this is what the quota leaves, which is what writes can use."""
    import shutil
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def require_space(path, minimum: int, what: str):
    """Refuse (CacheSpaceError naming the path, free space and threshold) below `minimum`."""
    free = free_bytes(path)
    if free < minimum:
        raise CacheSpaceError(
            f'{what} refused: {free / 1024 ** 2:.0f} MiB free at {path}, need at least '
            f'{minimum / 1024 ** 2:.0f} MiB. Free space on that volume or set FMCP_CACHE_DIR to a cache '
            'directory on a disk with room. Existing snapshots stay readable.')
    return free


def is_disk_full(exc) -> bool:
    import errno
    text = str(exc).lower()
    return getattr(exc, 'errno', None) == errno.ENOSPC or 'disk is full' in text or 'no space left' in text


def save_key(name: str, created: str, created_version: int) -> str:
    """Stable directory name for one career: slug of the save name + creation identity."""
    slug = re.sub(r'[^A-Za-z0-9]+', '-', name).strip('-').lower()[:48] or 'career'
    digest = hashlib.sha256(f'{name}\0{created}\0{created_version}'.encode()).hexdigest()[:10]
    return f'{slug}-{created}-{digest}'


class _VMReader:
    """`read(address, length)` for the PropertyVM, served from the LiveMemory page cache."""

    def __init__(self, memory):
        self.memory = memory

    def read(self, address, length):
        return self.memory.cached_read(address, length)


@dataclass
class SaveInfo:
    save_name: str
    save_key: str
    save_count: int
    created_date: str
    game_date: str
    managed_clubs: tuple          # club record addresses of the active human managers
    coaches: tuple                # ({'name', 'club'}, ...)
    managed_teams: tuple = ()     # team record addresses of the active human managers

    def public(self):
        return {'save_name': self.save_name, 'save_key': self.save_key, 'save_count': self.save_count,
                'created_date': self.created_date, 'game_date': self.game_date,
                'coaches': [dict(c) for c in self.coaches]}


class Engine:
    """Live process + catalog + VM for one attached FM27 (see module docstring)."""

    def __init__(self, *, pid: int, executable: str | None, base: int, plugin_path: Path,
                 memory=None, catalog=None, image=None, process_key=None):
        from .catalog import load_catalog_for_plugin
        from .image import PluginImage
        from .memory import LiveMemory
        from . import build
        self.pid, self.base, self.plugin_path = pid, base, Path(plugin_path)
        self.process_key = process_key or (pid, executable)
        self.memory = memory if memory is not None else LiveMemory(pid, expected_executable=executable,
                                                                          max_cache_pages=32768)
        # the pinned build verifies its sha256 in PluginImage.load; another build was checked
        # against its anchor file by build.activate (Engine.open_build)
        self.image = image if image is not None else PluginImage.load(self.plugin_path, verify=build.is_pinned())
        self.catalog = catalog if catalog is not None else load_catalog_for_plugin(self.plugin_path)
        self.plugin_sha256 = build.ACTIVE['sha256']
        self.build = build.ACTIVE['version']
        self.lock = threading.RLock()
        self._vm = None
        self._tracked_vm = None
        self._entries = {}

    # ------------------------------------------------------------------ opening
    @classmethod
    def from_bridge(cls, bridge, session_id, existing: 'Engine | None' = None) -> 'Engine':
        """Run the Bridge's pinned-build check for this MCP session; reuse `existing` when
        it belongs to the same process and plugin base, else open a new engine."""
        try:
            with bridge.lock:
                process = bridge._current(session_id)        # session known; same pid, executable and start time
                if existing is not None and existing.process_key == (process.pid, process.executable,
                                                                     process.started):
                    # The plugin image of a running process does not change, so the layout check
                    # that opened `existing` holds for as long as the process identity does. It
                    # costs 0.5 s of helper processes and used to run for every statement.
                    return existing
                with bridge._read_scope(session_id):
                    layout = bridge._player_layout(process)
                plugin_path = Path(bridge.plugin_identity[0][0])
        except Exception as exc:  # noqa: BLE001 - BridgeError and verification failures
            raise EngineError(f'{exc}') from exc
        base = layout[0] - players.RVA[0]
        key = (process.pid, process.executable, process.started)
        if existing is not None and existing.process_key == key and existing.base == base \
                and existing.plugin_path == plugin_path:
            return existing
        if existing is not None:
            existing.close()
        return cls(pid=process.pid, executable=process.executable, base=base,
                   plugin_path=plugin_path, process_key=key)

    @classmethod
    def open(cls, pid: int | None = None) -> 'Engine':
        """Standalone (scripts, live tests): attach a private Bridge, check the build, open."""
        from ..bridge import Bridge
        bridge = Bridge()
        session = bridge.attach(pid)['session_id']
        engine = cls.from_bridge(bridge, session)
        engine._bridge = bridge
        engine._session = session
        return engine

    @classmethod
    def open_build(cls, pid: int | None = None) -> 'Engine':
        """Standalone open for ANY plugin build that has an anchor file (scripts/fmdb_rebase.py):
        no Bridge (its gate keeps the hand-built tools on the pinned build); the plugin is the one
        inside the running app, its load address the region with the same Mach-O UUID, and the
        fmdb constants come from `build.activate`. The pinned build works here too."""
        from . import build
        from .memory import LiveMemory, find_fm_process
        process = find_fm_process()
        if process is None or (pid is not None and process.pid != pid):
            raise EngineError('No running Football Manager process to attach to.')
        plugin = Path(process.executable).resolve().parent.parent / 'PlugIns' / 'game_plugin.bundle' / \
            'Contents' / 'MacOS' / 'game_plugin'
        try:
            build.activate(plugin)
        except build.BuildError as exc:
            raise EngineError(str(exc)) from exc
        memory = LiveMemory(process.pid, expected_executable=process.executable, max_cache_pages=32768)
        uuid = players.macho_uuid(_arm64_header(plugin))
        base = None
        for region in memory.regions():
            if region.protection & 4:
                try:
                    if players.macho_uuid(memory.read(region.start, 16384)) == uuid:
                        base = region.start
                        break
                except Exception:  # noqa: BLE001 - not a Mach-O header
                    continue
        if base is None:
            memory.close()
            raise EngineError('The running game has not loaded the plugin found in its app bundle.')
        return cls(pid=process.pid, executable=process.executable, base=base, plugin_path=plugin, memory=memory,
                   process_key=(process.pid, process.executable, process.started))

    def close(self):
        try:
            self.memory.close()
        except Exception:  # noqa: BLE001
            pass
        # ui_recipes_news.open_vm keeps a UI VM with a memory reader process of its own on the
        # engine; it outlived the engine (a leaked fm_fast_reader per closed engine).
        vm = self.__dict__.pop('_ui_news_vm', None)
        reader = getattr(vm, 'reader', None)
        if reader is not None and reader is not self.memory:
            try:
                reader.close()
            except Exception:  # noqa: BLE001
                pass
        bridge = getattr(self, '_bridge', None)
        if bridge is not None:
            bridge.detach()

    # ------------------------------------------------------------------ memory
    def read(self, address: int, length: int) -> bytes:
        """Uncached read (current bytes)."""
        return self.memory.read(address, length)

    def read_many(self, requests):
        return self.memory.read_many(requests)

    def cached_read(self, address, length):
        return self.memory.cached_read(address, length)

    def windows(self, addresses, length):
        """Fixed-stride bulk read (MemoryBase.windows)."""
        return self.memory.windows(addresses, length)

    def prefetch(self, records, before=0x400, after=0x800):
        """Fault the pages around many records into the page cache with one batched read."""
        fetch = getattr(self.memory, 'prefetch', None)
        if fetch is not None and records:
            try:
                fetch([(r - before, before + after) for r in records if r])
            except Exception:  # noqa: BLE001 - prefetch is only an optimisation
                pass

    def file_resolver(self):
        """fd -> path for the game's open files (read-only `lsof`, cached per descriptor), so
        getters that read translated names from `languages.fmf` answer instead of refusing."""
        if getattr(self, '_file_resolver', None) is None:
            from .ui_vm import lsof_resolver
            self._file_resolver = lsof_resolver(self.pid)
        return self._file_resolver

    @property
    def vm(self):
        if self._vm is None:
            from . import fastvm
            if fastvm.available():
                cls = fastvm.FastVM
            else:
                from .vm import PropertyVM as cls
            self._vm = cls(_VMReader(self.memory), self.base, self.image, file_resolver=self.file_resolver())
        return self._vm

    @property
    def tracked_vm(self):
        """The VM on-demand cells are computed with: a FastVM that records which words of live
        memory each call read (`fastvm.TrackingFastVM`), or None when the accelerator with read
        tracking is not built. Separate from `vm`, whose loads keep Unicorn's fast path."""
        if self._tracked_vm is None:
            from . import fastvm
            if not fastvm.tracks_reads():
                return None
            self._tracked_vm = fastvm.TrackingFastVM(_VMReader(self.memory), self.base, self.image,
                                                     file_resolver=self.file_resolver())
        return self._tracked_vm

    def new_vm(self, **kwargs):
        """A separate PropertyVM (e.g. for load tracing, which slows every call it hooks)."""
        from .vm import PropertyVM
        kwargs.setdefault('file_resolver', self.file_resolver())
        return PropertyVM(_VMReader(self.memory), self.base, self.image, **kwargs)

    def plan_tracer(self):
        """A load-tracing PlanTracer on its own VM (tracing hooks slow every call they see)."""
        from .bulkplans import PlanTracer
        return PlanTracer(self.new_vm(budget=500_000))

    def fresh(self):
        """Drop cached pages so later reads and VM calls see current game memory."""
        self.memory.invalidate()
        self._entries.clear()
        self._vm = None
        if self._tracked_vm is not None:
            self._tracked_vm.invalidate()

    def refresh_memory(self):
        """As `fresh`, keeping the VM instances and their translated code: the page cache is
        dropped and each VM forgets its copied live pages (a new memory generation)."""
        self.memory.invalidate()
        self._entries.clear()
        for vm in (self._vm, self._tracked_vm):
            if vm is not None:
                forget = getattr(vm, 'invalidate', None)
                if forget is not None and hasattr(vm, 'drop_live_pages'):
                    forget()
                elif vm is self._vm:
                    self._vm = None             # PropertyVM: a new instance is the cheap way

    def get_property(self, record: int, code: str):
        """One getter call on the main VM. The VM keeps every faulted page mapped and Unicorn's
        mapping cost grows with the number of regions, so bulk loops drop the VM's page map
        (not the LiveMemory cache) by starting a new VM every VM_PAGE_LIMIT pages.

        `x:<name>` codes are `extras.DERIVED` fields (native getter slots, e.g.
        `x:condition_stored`, `x:injuries`), read with `extras.read_derived`."""
        vm = self.vm
        drop = getattr(vm, 'drop_live_pages', None)
        if drop is not None:
            # FastVM: copied pages live in one pool; dropping them keeps the instance and its code
            from .fastvm import LIVE_PAGE_LIMIT
            if len(vm.live_pages) > LIVE_PAGE_LIMIT:
                drop()
        elif len(vm.live_pages) > VM_PAGE_LIMIT:
            # a fresh VM is far cheaper than vm.invalidate(): Unicorn rebuilds its memory topology
            # on every single-page unmap
            self._vm = None
            vm = self.vm
        if isinstance(code, str) and code.startswith('x:'):
            from .extras import read_derived
            return read_derived(vm, record, code[2:])
        return vm.get_property(record, code)

    # ------------------------------------------------------------------ world
    def save_info(self) -> SaveInfo:
        """Save identity and current game date, read uncached."""
        reader = world.ReadSet(self.read)
        try:
            record, identity = world.loaded(reader, self.base)
            reader.verify()
        except ValueError as exc:
            raise EngineError(f'Loaded career not readable: {exc}. Load a career in FM27 and retry.') from exc
        clubs = tuple(binding[5] for binding in identity[6])
        return SaveInfo(record['name'], save_key(record['name'], record['created_date'], record['created_version']),
                        record['save_count'], record['created_date'], record['current_date'], clubs,
                        tuple({'name': c['name'], 'club': c['club']} for c in record['coaches']),
                        tuple(binding[4] for binding in identity[6]))

    def game_date(self) -> str:
        return world.packed_date(self.read(self.base + world.CURRENT_DATE, 4))

    # ------------------------------------------------------------------ tables
    def table_info(self, kind: str) -> dict:
        """Vector header of one live table (start, count, identity), read uncached."""
        return database.table(self.read, self.base, kind)

    def table_entries(self, kind: str) -> tuple[list[int], tuple]:
        """(record pointers, header identity) of a live table, one bulk read."""
        info = self.table_info(kind)
        n = info['count']
        data = self.read(info['start'], n * 8) if n else b''
        return list(struct.unpack(f'<{n}Q', data)), info['identity']

    def class_name(self, vtable_rva: int) -> str:
        entry = tables.CLASSES.get(vtable_rva)
        if entry:
            return entry[0]
        name = self.vm.rtti_name(self.base + vtable_rva)
        return (name or f'vtable@{vtable_rva:#x}').lstrip('0123456789').replace('N2db', '') \
            if name else f'vtable@{vtable_rva:#x}'
