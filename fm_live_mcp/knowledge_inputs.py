"""Page-cached transport and consumed-input recording for the bulk knowledge engine.

``PageSource`` serves the journal's physical reads from whole pages read in batches through a
``fmdb.memory.MemoryBase`` (``LiveMemory`` on the game, ``SnapshotMemory`` in tests), so one
player's few hundred reads cost dictionary lookups instead of helper round trips.

``Inputs`` records, per player, what the evaluation consumed:

* raw regions: every ``(address, size)`` the journal handed out while that player was evaluated;
* groups: shared pieces of work evaluated once per call (a memoised club, an index over a
  HUMAN-owned vector) with their own regions; a player that uses one holds a reference;
* derived inputs: ``(kind, args) -> outcome`` facts whose raw bytes are deliberately left out
  of the fingerprint because the bytes change without the outcome changing (the game date in
  an age or expiry comparison, the row a lookup found in a large shared vector). ``DERIVED``
  maps each kind to the function that recomputes the outcome from memory.

A stored fingerprint is valid while every raw region still holds the same bytes, every group is
valid and every derived input recomputes to the same outcome. The evaluation is a deterministic
function of the bytes it reads through the journal (its first read address is fixed by the
call's context; every later address follows from bytes already read), so a valid fingerprint
means a re-evaluation would read the same bytes and return the same row.
"""
from __future__ import annotations

import hashlib
import struct

PAGE = 16384
READAHEAD = 3        # extra pages fetched after a faulting page, in the same round trip


class PageSource:
    """Whole-page cache over a MemoryBase; ``read`` is the journal's physical read."""

    def __init__(self, memory, *, page_size=None, readahead=None):
        self.memory = memory
        self.page_size = page_size or getattr(memory, 'page_size', PAGE)
        self.mask = ~(self.page_size - 1)
        self.readahead = READAHEAD if readahead is None else readahead
        self._pages = {}
        self._used = set()        # bases of pages a read was served from (what the fence re-reads)
        self.fetches = 0          # batched reads issued
        self.pages_read = 0

    def _fault(self, bases):
        """Read the missing pages of ``bases`` (an unreadable one raises) and, in the same round
        trip, the next ``readahead`` pages after them when they are readable: records of one
        kind sit next to each other, and a round trip costs far more than a page."""
        size = self.page_size
        bases = sorted(b for b in set(bases) if b not in self._pages)
        if not bases:
            return
        wanted = list(bases)
        last = bases[-1]
        for k in range(1, self.readahead + 1):
            extra = last + k * size
            if extra not in self._pages:
                wanted.append(extra)
        self.fetches += 1
        required = set(bases)
        for base, raw in zip(wanted, self.memory.read_many([(b, size) for b in wanted])):
            if type(raw) is not bytes or len(raw) != size:
                if base in required:
                    raise ValueError(f'Unreadable page at {base:#x}')
                continue
            self._pages[base] = raw
            self.pages_read += 1

    def prefetch(self, regions):
        """Fault in every page of ``regions`` with one batched read; unreadable pages are left
        for the read that needs them (which then raises)."""
        size, mask = self.page_size, self.mask
        wanted = set()
        for address, length in regions:
            if address >= 4096 and length > 0:
                wanted.update(range(address & mask, address + length, size))
        missing = sorted(b for b in wanted if b not in self._pages)
        if not missing:
            return 0
        self.fetches += 1
        got = 0
        for base, raw in zip(missing, self.memory.read_many([(b, size) for b in missing])):
            if type(raw) is bytes and len(raw) == size:
                self._pages[base] = raw
                got += 1
        self.pages_read += got
        return got

    def read(self, address, size):
        base = address & self.mask
        page = self._pages.get(base)
        offset = address - base
        if page is not None and offset + size <= self.page_size:
            self._used.add(base)
            return page[offset:offset + size]
        last = (address + size - 1) & self.mask
        self._fault(range(base, last + 1, self.page_size))
        self._used.update(range(base, last + 1, self.page_size))
        if base == last:
            return self._pages[base][offset:offset + size]
        data = b''.join(self._pages[b] for b in range(base, last + 1, self.page_size))
        return data[offset:offset + size]

    def pages(self):
        return self._pages

    def fresh(self, bases=None):
        """{page base: bytes} of every page a read was served from, read again from memory now
        (one batched read), not from the cache."""
        bases = sorted(self._used if bases is None else bases)
        size = self.page_size
        out = {}
        self.fetches += 1
        self.pages_read += len(bases)
        for base, raw in zip(bases, self.memory.read_many([(b, size) for b in bases])):
            if type(raw) is not bytes or len(raw) != size:
                raise ValueError(f'Unreadable page at {base:#x}')
            out[base] = raw
        return out


def slice_pages(pages, page_size, address, size):
    """Bytes of one region from a {base: bytes} page map (None when a page is missing)."""
    base = address & ~(page_size - 1)
    offset = address - base
    page = pages.get(base)
    if page is None:
        return None
    if offset + size <= page_size:
        return page[offset:offset + size]
    out = bytearray(page[offset:])
    while len(out) < size:
        base += page_size
        page = pages.get(base)
        if page is None:
            return None
        out += page[:size - len(out)]
    return bytes(out)


# --------------------------------------------------------------------------- recording

class Collector:
    """Inputs consumed by one unit of work (a player, or a shared group)."""

    __slots__ = ('log', 'groups', 'derived')

    def __init__(self):
        self.log = []          # (address, size) in read order, repeats included
        self.groups = []       # keys of outcome groups used
        self.derived = []      # (kind, args, outcome) facts


def _discard(key):
    return None


def outcome_digest(outcome):
    """Stable digest of a memoised outcome: (True, value) or (False, exception)."""
    ok, value = outcome
    text = repr(value) if ok else repr((type(value).__name__, value.args))
    return hashlib.blake2b((('1' if ok else '0') + text).encode(), digest_size=8).hexdigest()


class Inputs:
    """Collector stack for one bulk call. ``sink`` is the bound ``append`` of the current log."""

    def __init__(self):
        self.root = Collector()            # call-wide context reads (set-up, final checks)
        self.stack = [self.root]
        self.sink = self.root.log.append
        self.groups = {}                   # key -> (outcome digest, Collector)
        self.players = {}                  # player key -> Collector (finished)
        self._suspended = 0

    def push(self, collector=None):
        collector = collector or Collector()
        self.stack.append(collector)
        if not self._suspended:
            self.sink = collector.log.append
        return collector

    def pop(self):
        collector = self.stack.pop()
        if not self._suspended:
            self.sink = self.stack[-1].log.append
        return collector

    def derive(self, kind, args, outcome):
        self.stack[-1].derived.append((kind, args, outcome))

    def suspend(self):
        """Reads until ``resume`` are journalled and fenced but not recorded as raw inputs;
        the caller records a derived fact that stands for them."""
        self._suspended += 1
        self.sink = _discard

    def resume(self):
        self._suspended -= 1
        if not self._suspended:
            self.sink = self.stack[-1].log.append


def call_memo(read):
    """The paged bulk journal's ``memo`` behind a read source, or None anywhere else.

    Source modules use it to run a per-call constant (a pinned-code guard) once per call."""
    probe = read
    for _ in range(4):
        memo = getattr(probe, 'call_memo', None)
        if memo is not None:
            return memo
        probe = getattr(probe, 'read', None)
        if probe is None:
            return None
    return None


def merge_regions(regions):
    """Sorted disjoint [start, end) spans covering exactly the bytes of ``regions``."""
    spans = []
    for address, size in sorted(set(regions)):
        if spans and address <= spans[-1][1]:
            if address + size > spans[-1][1]:
                spans[-1][1] = address + size
        else:
            spans.append([address, address + size])
    return spans


_SPAN = struct.Struct('<QI')


def pack_spans(spans):
    return b''.join(_SPAN.pack(start, end - start) for start, end in spans)


def unpack_spans(blob):
    return [(start, start + size) for start, size in _SPAN.iter_unpack(blob)]


def digest_spans(spans, read):
    """blake2b-128 over the bytes of each span, in order. ``read(address, size)`` -> bytes or None;
    a span that cannot be read gives None (the fingerprint is then invalid)."""
    h = hashlib.blake2b(digest_size=16)
    for start, end in spans:
        raw = read(start, end - start)
        if raw is None:
            return None
        h.update(raw)
    return h.digest()


# --------------------------------------------------------------------------- stored form

def encode_value(value):
    """JSON-able form of a memo key element or outcome (canonical records are tagged lists)."""
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) in (tuple, list):
        return [encode_value(v) for v in value]
    name = type(value).__name__
    if name == 'Ref':
        return ['<Ref>', value.address, value.kind, list(value.identity)]
    if name == 'Person':
        return ['<Person>', encode_value(value.person), value.primary]
    if name == 'RelationRow':
        return ['<Row>', value.address]
    raise TypeError(f'Unsupported memo key element {name}')


def decode_value(value):
    if type(value) is not list:
        return value
    if value and type(value[0]) is str and value[0].startswith('<'):
        from . import knowledge_context_score as core
        tag = value[0]
        if tag == '<Ref>':
            return core.Ref(value[1], value[2], tuple(value[3]))
        if tag == '<Person>':
            return core.Person(decode_value(value[1]), value[2])
        if tag == '<Row>':
            return core.RelationRow(value[1])
    return tuple(decode_value(v) for v in value)


def encode_key(key):
    import json
    return json.dumps(encode_value(key), separators=(',', ':'))


def decode_key(text):
    import json
    return decode_value(json.loads(text))


def _facts(derived):
    """Distinct (kind, args, outcome) facts in first-use order, JSON-able."""
    out, seen = [], set()
    for kind, args, outcome in derived:
        item = (kind, tuple(args), repr(outcome))
        if item not in seen:
            seen.add(item)
            out.append([kind, list(args), outcome])
    return out


class Fingerprints:
    """Storable fingerprints for the players and outcome groups of one finished call.

    A fingerprint is: ``spans`` (packed disjoint byte ranges, exactly the bytes consumed, code
    of the game binary left out because the process identity pins it), ``digest`` of those
    bytes as the call read them, ``groups`` [[key, outcome digest]] and ``facts``
    [[kind, args, outcome]]. Regions consumed by at least ``share`` of the call's players are
    moved into one common group per call, so each player's own fingerprint stays small.
    """

    def __init__(self, inputs, page_source, *, code=(0, 0), share=0.2, minimum=4, rewrite=None):
        self.inputs, self.source, self.code = inputs, page_source, code
        self.rewrite = rewrite or {}       # {region: the part of it that is an input}
        self.share, self.minimum = share, minimum
        self.common_key = None
        self._common = frozenset()

    def _regions(self, log):
        low, high = self.code
        regions = {r for r in log if not low <= r[0] < high}
        for whole, part in self.rewrite.items():
            if whole in regions:
                regions.discard(whole)
                regions.add(part)
        return regions

    def _pack(self, regions):
        spans = merge_regions(regions)
        return pack_spans(spans), digest_spans(spans, self.source.read)

    def _groups(self, collector):
        groups = self.inputs.groups
        return [[encode_key(key), groups[key][0]] for key in dict.fromkeys(collector.groups)]

    def players(self, collectors):
        """{player key: fingerprint} for {player key: Collector}; also fixes the common group."""
        sets = {key: self._regions(c.log) for key, c in collectors.items()}
        if len(sets) >= self.minimum:
            from collections import Counter
            counts = Counter()
            for regions in sets.values():
                counts.update(regions)
            threshold = max(self.minimum, self.share * len(sets))
            self._common = frozenset(r for r, n in counts.items() if n >= threshold)
        common_ref = None
        if self._common:
            blob, digest = self._pack(self._common)
            self.common_key = encode_key(('common', digest.hex()))
            self.common_record = dict(spans=blob, digest=digest, groups=[], facts=[], outcome='common')
            common_ref = [self.common_key, 'common']
        out = {}
        for key, collector in collectors.items():
            regions = sets[key]
            shared = bool(self._common) and not self._common.isdisjoint(regions)
            blob, digest = self._pack(regions - self._common if shared else regions)
            groups = self._groups(collector)
            if shared:
                groups.append(common_ref)
            out[key] = dict(spans=blob, digest=digest, groups=groups, facts=_facts(collector.derived))
        return out

    def groups(self):
        """{encoded key: fingerprint + outcome} for every outcome group of the call."""
        out = {}
        for key, (outcome, collector) in self.inputs.groups.items():
            blob, digest = self._pack(self._regions(collector.log))
            out[encode_key(key)] = dict(spans=blob, digest=digest, groups=self._groups(collector),
                                        facts=_facts(collector.derived), outcome=outcome)
        if self.common_key is not None:
            out[self.common_key] = self.common_record
        return out


class Verifier:
    """Decides which stored fingerprints still hold on the memory of the current call.

    ``facts(kind, args)`` recomputes a derived fact; ``recompute(key text)`` recomputes an
    outcome group through the engine and returns its new outcome digest (None when it cannot).
    Every byte range compared here is kept (``checked``) so the call's final fence can confirm
    it did not change before the call ended.
    """

    def __init__(self, page_source, groups, facts, recompute):
        self.source, self.stored = page_source, groups
        self.facts_fn, self.recompute = facts, recompute
        self.outcomes = {}            # key text -> outcome digest now (None: unknown)
        self.fact_cache = {}
        self.checked = []             # packed span blobs compared against the call's pages
        self.recomputed = 0
        self.kept_groups = set()

    def prefetch(self, blobs):
        regions = []
        for blob in blobs:
            regions.extend((start, size) for start, size in _SPAN.iter_unpack(blob))
        return self.source.prefetch(regions)

    def spans_ok(self, blob, digest):
        try:
            now = digest_spans(unpack_spans(blob), self.source.read)
        except ValueError:
            return False
        self.checked.append(blob)
        return now == digest

    def facts_ok(self, facts):
        for kind, args, outcome in facts:
            key = (kind, repr(args))
            if key not in self.fact_cache:
                self.fact_cache[key] = self.facts_fn(kind, args)
            if self.fact_cache[key] != outcome:
                return False
        return True

    def group(self, key):
        """Current outcome digest of a stored or recomputed group."""
        if key in self.outcomes:
            return self.outcomes[key]
        self.outcomes[key] = None                 # cycle guard
        record = self.stored.get(key)
        outcome = None
        if record is not None and self.fingerprint_ok(record):
            outcome = record['outcome']
            self.kept_groups.add(key)
        elif self.recompute is not None:
            outcome = self.recompute(key)
            self.recomputed += 1
        self.outcomes[key] = outcome
        return outcome

    def fingerprint_ok(self, record):
        return (self.spans_ok(record['spans'], record['digest']) and self.facts_ok(record['facts'])
                and all(self.group(key) == outcome for key, outcome in record['groups']))

    def why(self, record):
        """The first reason a fingerprint does not hold: 'bytes', 'fact:<kind>' or
        'group:<kind>' (for reporting what made rows change)."""
        try:
            if digest_spans(unpack_spans(record['spans']), self.source.read) != record['digest']:
                return 'bytes'
        except ValueError:
            return 'bytes'
        for kind, args, outcome in record['facts']:
            if self.fact_cache.get((kind, repr(args))) != outcome:
                return 'fact:' + kind
        for key, outcome in record['groups']:
            if self.outcomes.get(key) != outcome:
                try:
                    decoded = decode_key(key)
                    kind = decoded[1] if decoded[0] == 'op' else decoded[0]
                except (ValueError, TypeError):
                    kind = '?'
                return 'group:' + str(kind)
        return 'unknown'
