"""On-disk cache for UI handler results (fm_ui_read, fm_get_board_confidence, recipes).

A UI handler computation emulates shipped game code on copied memory and can take
seconds to tens of seconds; its answer only changes when the game moves on. Entries are
JSON files under

    <FMCP_CACHE_DIR or /Volumes/4TB Private/Offloaded/Agent Work/fmcp-source-cache>
        /fmdb/<save key>/ui/<game date>/<kind>-<digest>.json

keyed by (save key, game date, kind, inputs). `kind` names what was computed
('handler:114', 'board_confidence', 'recipe:inbox', ...) and `inputs` is any JSON value
(UI_RECORD fields, keys, arguments). An entry is served only when the save key, game
date, save count, plugin build and inputs all match; writing an entry for a new game
date removes the other dates of that save. Every entry records when it was computed
(UTC wall clock and game date), and `fresh=True` in the tools bypasses it.

The save key is the snapshot lane's (`engine.save_key`): slug of the save name plus the
career's creation identity, so both lanes share `<root>/fmdb/<save key>/`.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

DEFAULT_CACHE = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmcp-source-cache')
VERSION = 1


def cache_root() -> Path:
    """`$FMCP_CACHE_DIR/fmdb`, defaulting to the external-disk source cache."""
    env = os.environ.get('FMCP_CACHE_DIR')
    return (Path(env) if env else DEFAULT_CACHE) / 'fmdb'


def save_key(name: str, created: str, created_version: int) -> str:
    """Stable directory name for one career (same formula as the snapshot lane's engine)."""
    slug = re.sub(r'[^A-Za-z0-9]+', '-', name).strip('-').lower()[:48] or 'career'
    digest = hashlib.sha256(f'{name}\0{created}\0{created_version}'.encode()).hexdigest()[:10]
    return f'{slug}-{created}-{digest}'


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, default=str)


def entry_name(kind: str, inputs) -> str:
    slug = re.sub(r'[^A-Za-z0-9]+', '-', kind).strip('-').lower()[:40] or 'entry'
    digest = hashlib.sha256(f'{kind}\0{canonical(inputs)}'.encode()).hexdigest()[:20]
    return f'{slug}-{digest}.json'


def _valid_date(game_date: str) -> str:
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', game_date or ''):
        raise ValueError(f'game date must be YYYY-MM-DD, got {game_date!r}')
    return game_date


class UiCache:
    """Entries of one save on one game date."""

    def __init__(self, save_key: str, game_date: str, *, save_count: int | None = None,
                 build: str | None = None, root: Path | None = None):
        if not save_key or '/' in save_key or save_key.startswith('.'):
            raise ValueError('invalid save key')
        self.save_key, self.game_date = save_key, _valid_date(game_date)
        self.save_count, self.build = save_count, build
        self.dir = Path(root or cache_root()) / save_key / 'ui'

    def path(self, kind: str, inputs) -> Path:
        return self.dir / self.game_date / entry_name(kind, inputs)

    def get(self, kind: str, inputs) -> dict | None:
        """The stored entry, or None when absent, unreadable or for another state."""
        path = self.path(kind, inputs)
        try:
            entry = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        if (entry.get('version') != VERSION or entry.get('save_key') != self.save_key
                or entry.get('game_date') != self.game_date or entry.get('kind') != kind
                or canonical(entry.get('inputs')) != canonical(inputs)
                or entry.get('save_count') != self.save_count or entry.get('build') != self.build):
            return None
        entry['age_seconds'] = round(max(0.0, time.time() - entry.get('computed_at_unix', 0)), 1)
        return entry

    def entry(self, kind: str, inputs, payload: dict, *, computed_at: float | None = None) -> dict:
        """The entry `put` would write (also used for answers that must not be cached)."""
        stamp = time.time() if computed_at is None else computed_at
        entry = dict(payload)
        entry.update({
            'version': VERSION, 'save_key': self.save_key, 'game_date': self.game_date,
            'save_count': self.save_count, 'build': self.build, 'kind': kind, 'inputs': inputs,
            'computed_at': datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec='seconds'),
            'computed_at_unix': stamp,
        })
        return entry

    def put(self, kind: str, inputs, payload: dict, *, computed_at: float | None = None) -> dict:
        """Write an entry atomically; drops this save's entries for other game dates."""
        entry = self.entry(kind, inputs, payload, computed_at=computed_at)
        path = self.path(kind, inputs)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f'.tmp{os.getpid()}')
        tmp.write_text(json.dumps(entry, ensure_ascii=False, default=str))
        os.replace(tmp, path)
        self.prune()
        return entry

    def prune(self) -> list[str]:
        """Remove entries of this save for game dates other than the current one."""
        removed = []
        if not self.dir.is_dir():
            return removed
        for child in self.dir.iterdir():
            if child.is_dir() and child.name != self.game_date and re.fullmatch(r'\d{4}-\d{2}-\d{2}', child.name):
                shutil.rmtree(child, ignore_errors=True)
                removed.append(child.name)
        return removed

    def drop(self, kind: str, inputs) -> None:
        try:
            self.path(kind, inputs).unlink()
        except FileNotFoundError:
            pass


def describe(entry: dict | None, *, hit: bool) -> dict:
    """The `cache` block every tool answer carries."""
    if not entry:
        return {'hit': False}
    out = {'hit': hit, 'computed_at': entry.get('computed_at'), 'computed_for_game_date': entry.get('game_date')}
    if not hit and not entry.get('stored', True):
        out['stored'] = False
        out['note'] = 'Not cached: the computation did not complete (budget or input failure).'
    if hit:
        out['age_seconds'] = entry.get('age_seconds')
        out['note'] = ('Served from the on-disk cache for this save and game date; pass fresh=true to '
                       'recompute from current game memory.')
    return out


# =========================================================================== version 2
# Screen answers keyed by what was asked (object identity), valid for as long as the bytes the
# computation read are unchanged, instead of for one game date (docs/fmdb/UI_FAST.md).
#
#     <root>/fmdb/<save key>/ui2/<kind>-<digest>.json   answer, validity, when computed
#     <root>/fmdb/<save key>/ui2/<kind>-<digest>.rs     its read set (zlib)
#
# validity modes:
#   'forever'   the object cannot change (a news item's subject and body): served without a check;
#   'read_set'  served when every live page the computation read still has the recorded
#               fingerprint (`check_read_set`) and every game file it read is unmodified;
#               page addresses only mean something inside the process that was read, so another
#               game process never validates.
# A read set lists 4 KiB live pages. For a page the running game keeps changing (a "watched"
# page) it also holds which 8-byte words were read, and only those are fingerprinted.
import struct
import zlib
from dataclasses import dataclass, field

FP_VERSION = 2
PAGE = 4096
FULL_MASK = (0xFFFF_FFFF_FFFF_FFFF,) * 8
RUN_PAGES = 256


@dataclass
class ReadSet:
    process: list                               # [pid, start time]: the address space
    pages: list                                 # sorted page addresses
    hashes: list                                # fingerprint per page (of the masked words)
    masks: dict = field(default_factory=dict)   # watched page -> 8 x u64 (bit per 8-byte word read)
    files: list = field(default_factory=list)   # [path, size, mtime_ns] of game files read
    words: dict = field(default_factory=dict)   # watched page -> the masked words as read (u64 each, in order)

    def to_bytes(self) -> bytes:
        head = json.dumps({'process': self.process, 'files': self.files, 'pages': len(self.pages),
                           'masked': len(self.masks),
                           'words': {str(p): w.hex() for p, w in self.words.items()}}).encode()
        masked = sorted(self.masks)
        index = {p: i for i, p in enumerate(self.pages)}
        body = b''.join((
            struct.pack(f'<{len(self.pages)}Q', *self.pages), struct.pack(f'<{len(self.hashes)}Q', *self.hashes),
            struct.pack(f'<{len(masked)}I', *(index[p] for p in masked)),
            b''.join(struct.pack('<8Q', *self.masks[p]) for p in masked)))
        return zlib.compress(struct.pack('<I', len(head)) + head + body, 1)

    @classmethod
    def from_bytes(cls, data: bytes) -> 'ReadSet':
        raw = zlib.decompress(data)
        size, = struct.unpack_from('<I', raw)
        head = json.loads(raw[4:4 + size])
        n, m, at = head['pages'], head['masked'], 4 + size
        pages = list(struct.unpack_from(f'<{n}Q', raw, at))
        hashes = list(struct.unpack_from(f'<{n}Q', raw, at + 8 * n))
        at += 16 * n
        which = struct.unpack_from(f'<{m}I', raw, at)
        at += 4 * m
        masks = {pages[i]: struct.unpack_from('<8Q', raw, at + 64 * k) for k, i in enumerate(which)}
        words = {int(p): bytes.fromhex(w) for p, w in (head.get('words') or {}).items()}
        return cls(head['process'], pages, hashes, masks, [list(f) for f in head['files']], words)


def masked_words(data: bytes, mask) -> bytes:
    """The 8-byte words of one 4 KiB page selected by `mask` (8 x u64), concatenated in order."""
    out = []
    for group, bits in enumerate(mask):
        while bits:
            low = bits & -bits
            index = (group << 6) + low.bit_length() - 1
            out.append(data[8 * index:8 * index + 8])
            bits ^= low
    return b''.join(out)


def changed_words(page: int, mask, before: bytes, data: bytes) -> list:
    """Addresses of the masked words of `page` whose bytes differ between `before`
    (masked_words of the earlier read) and the page bytes `data`."""
    now = masked_words(data, mask)
    if len(now) != len(before):
        return [page]
    out, k = [], 0
    for group, bits in enumerate(mask):
        while bits:
            low = bits & -bits
            index = (group << 6) + low.bit_length() - 1
            if now[8 * k:8 * k + 8] != before[8 * k:8 * k + 8]:
                out.append(page + 8 * index)
            k += 1
            bits ^= low
    return out


def clear_words(masks: dict, words) -> int:
    """Clear the bits of `words` (absolute addresses) in `masks` ({page: 8 x u64}); returns how many."""
    cleared = 0
    for word in words:
        page, index = word & ~(PAGE - 1), (word & (PAGE - 1)) >> 3
        if page in masks and (masks[page][index >> 6] >> (index & 63)) & 1:
            groups = list(masks[page])
            groups[index >> 6] &= ~(1 << (index & 63))
            masks[page] = tuple(groups)
            cleared += 1
    return cleared


def page_runs(pages, cap=RUN_PAGES):
    """[(address, byte length)] covering sorted page addresses, consecutive pages merged."""
    runs, start, count = [], None, 0
    for page in pages:
        if start is not None and page == start + count * PAGE and count < cap:
            count += 1
            continue
        if start is not None:
            runs.append((start, count * PAGE))
        start, count = page, 1
    if start is not None:
        runs.append((start, count * PAGE))
    return runs


def file_stamp(path) -> list:
    try:
        st = os.stat(path)
    except OSError:
        return [str(path), -1, -1]
    return [str(path), st.st_size, st.st_mtime_ns]


def check_read_set(read_set: ReadSet, read_many, hash_masked, process) -> dict:
    """Read every page of the set from the game again and compare fingerprints.

    `read_many([(address, length)]) -> [(status, bytes | None)]` (LiveMemory.read_many_status),
    `hash_masked(data, masks) -> [u64 per page]` (ui_fastvm.hash_masked). Returns
    {'ok', 'reason', 'changed': [page], 'data': {page: bytes} (what was just read, for the
    emulator), 'pages', 'seconds'}."""
    started = time.perf_counter()
    out = {'ok': False, 'reason': None, 'changed': [], 'data': {}, 'pages': len(read_set.pages), 'seconds': 0.0}
    if list(read_set.process) != list(process):
        out['reason'] = 'another game process'
        return out
    for stamp in read_set.files:
        if file_stamp(stamp[0]) != list(stamp):
            out['reason'] = f'game file changed: {Path(stamp[0]).name}'
            break
    runs = page_runs(read_set.pages)
    chunks, unreadable = [], set()
    for (address, length), (_, data) in zip(runs, read_many(runs) if runs else ()):
        if data is None or len(data) != length:
            unreadable.update(range(address, address + length, PAGE))
            data = bytes(length)
        chunks.append(data)
    blob = b''.join(chunks)
    masks = [read_set.masks.get(page, FULL_MASK) for page in read_set.pages]
    hashes = hash_masked(blob, masks) if read_set.pages else []
    words = []
    for i, page in enumerate(read_set.pages):
        if page not in unreadable:
            out['data'][page] = blob[i * PAGE:(i + 1) * PAGE]
        if page in unreadable or hashes[i] != read_set.hashes[i]:
            out['changed'].append(page)
            if words is not None and page not in unreadable and page in read_set.masks and page in read_set.words:
                words += changed_words(page, read_set.masks[page], read_set.words[page], out['data'][page])
            else:
                words = None                  # a whole page or an unreadable one: the words are not known
    # the exact words that changed, when every changed page is read by word (None: not known)
    out['changed_words'] = words if out['changed'] else []
    if out['changed'] and not out['reason']:
        out['reason'] = f'{len(out["changed"])} of {len(read_set.pages)} pages read have changed'
    out['ok'] = out['reason'] is None
    out['seconds'] = round(time.perf_counter() - started, 4)
    return out


class ScreenCache:
    """Entries of one save, keyed by (kind, identity)."""

    def __init__(self, save_key: str, *, build: str | None = None, root: Path | None = None):
        if not save_key or '/' in save_key or save_key.startswith('.'):
            raise ValueError('invalid save key')
        self.save_key, self.build = save_key, build
        self.dir = Path(root or cache_root()) / save_key / 'ui2'

    def path(self, kind: str, identity) -> Path:
        return self.dir / entry_name(kind, identity)

    def get(self, kind: str, identity) -> dict | None:
        path = self.path(kind, identity)
        try:
            entry = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        if (entry.get('version') != FP_VERSION or entry.get('save_key') != self.save_key
                or entry.get('kind') != kind or canonical(entry.get('inputs')) != canonical(identity)
                or entry.get('build') != self.build):
            return None
        entry['age_seconds'] = round(max(0.0, time.time() - entry.get('computed_at_unix', 0)), 1)
        return entry

    def read_set(self, kind: str, identity) -> ReadSet | None:
        try:
            return ReadSet.from_bytes(self.path(kind, identity).with_suffix('.rs').read_bytes())
        except (OSError, ValueError, KeyError, struct.error, zlib.error):
            return None

    def entry(self, kind: str, identity, payload: dict, validity: dict) -> dict:
        stamp = time.time()
        entry = dict(payload)
        entry.update({'version': FP_VERSION, 'save_key': self.save_key, 'build': self.build, 'kind': kind,
                      'inputs': identity, 'validity': validity,
                      'computed_at': datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec='seconds'),
                      'computed_at_unix': stamp})
        return entry

    def put(self, kind: str, identity, payload: dict, validity: dict, read_set: ReadSet | None = None) -> dict:
        entry = self.entry(kind, identity, payload, validity)
        path = self.path(kind, identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        sidecar = path.with_suffix('.rs')
        if read_set is not None:
            tmp = sidecar.with_suffix(f'.rs.tmp{os.getpid()}')
            tmp.write_bytes(read_set.to_bytes())
            os.replace(tmp, sidecar)
        else:
            sidecar.unlink(missing_ok=True)
        tmp = path.with_suffix(f'.tmp{os.getpid()}')
        tmp.write_text(json.dumps(entry, ensure_ascii=False, default=str))
        os.replace(tmp, path)
        return entry

    def drop(self, kind: str, identity) -> None:
        path = self.path(kind, identity)
        path.unlink(missing_ok=True)
        path.with_suffix('.rs').unlink(missing_ok=True)

    def prune_process(self, process) -> int:
        """Remove read-set entries of other game processes (their page addresses are dead)."""
        removed = 0
        if not self.dir.is_dir():
            return removed
        for sidecar in self.dir.glob('*.rs'):
            try:
                raw = zlib.decompress(sidecar.read_bytes())
                size, = struct.unpack_from('<I', raw)
                same = list(json.loads(raw[4:4 + size])['process']) == list(process)
            except (OSError, ValueError, KeyError, struct.error, zlib.error):
                same = False
            if not same:
                sidecar.unlink(missing_ok=True)
                sidecar.with_suffix('.json').unlink(missing_ok=True)
                removed += 1
        return removed


def describe_checked(entry: dict, *, hit: bool, check: dict | None = None, note: str | None = None) -> dict:
    """The `cache` block of an answer served from or stored in a ScreenCache."""
    mode = (entry.get('validity') or {}).get('mode')
    out = {'hit': hit, 'computed_at': entry.get('computed_at'), 'valid_while': {
        'forever': 'always: the object does not change once created',
        'read_set': 'the game memory and files this computation read are unchanged',
    }.get(mode, mode)}
    if entry.get('game_date'):
        out['computed_for_game_date'] = entry['game_date']
    if not entry.get('stored', True):
        out['stored'] = False
        out['note'] = 'Not cached: the computation did not complete (budget or input failure).'
    if hit:
        out['age_seconds'] = entry.get('age_seconds')
    if check is not None:
        out['check'] = {'pages_read_again': check['pages'], 'seconds': check['seconds'],
                        'result': 'unchanged' if check['ok'] else check['reason']}
    if note:
        out['note'] = note
    return out
