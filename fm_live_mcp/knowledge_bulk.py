"""Bulk manager-visible knowledge engine (fog of war) for hundreds to thousands of players.

Same answers as ``fm_get_manager_visible_attributes`` (``knowledge_manager_visible``),
computed once per player instead of once per (player, field) cell:

* Setup happens once per call: private journalled bridge, world/coach/HUMAN context,
  the forbidden attribute-byte intervals over every primary record, the selected
  HUMAN's FOW owner record and both report vectors.
* Per player, the approved typed source (the same overlay composition as the tool)
  computes the field-independent knowledge inputs once: the upstream PERSON_UI report,
  the own-club context branch, the category byte, the reciprocal FOW node score, the
  contextual K and the range inputs (age, assessor judging bytes).
* Per field, H is the pure threshold comparison of those inputs (``field_state``), and the
  visible value is the pure native Range projection of the field's getter.

Firewall: every stored attribute byte (primary+0x148..0x18d) is forbidden. A byte is read
only as an exact one-byte region after ``BulkJournal.authorize_cell`` recomputed that cell's
H from the journal-registered knowledge record and found it 1 or 2. Any journal error poisons
the call and no partial result is returned. The call ends with one final context check, a
consistency check of overlapping read shapes and one physical fence that re-reads every
consumed region (attribute grants included) and compares it with the first read. Inside the
call, the per-source lifetime/verify callbacks reduce to the kernel process-incarnation check:
every repeated read is served from the journal, so the per-cell world re-reads of the tool
could never observe a change; the final fence is what detects one.

Players may be given as database PERSON indices (int), ``('ordinal', n)`` positions in the
native all_actual PLAYER vector, ``('address', primary)`` or existing ``player_ref`` strings.
"""
from bisect import bisect_left, bisect_right
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import random
import secrets
import struct
import time

from . import (assessment_people, bridge as bridge_module, database, live_transfer_offers, players,
               prepared_tactics_source, world)
from . import knowledge_attribute_thresholds as attribute_thresholds
from . import knowledge_context_score as core
from . import knowledge_field_catalog as catalog
from . import knowledge_field_firewall as firewall
from . import knowledge_generation_transport as generation
from . import knowledge_inputs as inputs_module
from . import knowledge_manager_visible as km
from . import knowledge_native_scope as scope
from . import knowledge_passing_range as ranges
from . import knowledge_relation_fixes as relation_fixes
from . import knowledge_search_population_source as population
from . import knowledge_structural_operand as structural
from . import knowledge_transfer_predicate as transfer
from . import knowledge_used_range_overlay as used_range
from .bridge import BridgeError

ALL_FIELDS = tuple(range(len(catalog.FIELDS)))
STATES = km.STATES
# Ability slots of original H (dispatcher 0x14e98e4): constant (low, exact) pairs,
# independent of the player category. Evidence knowledge-perceived-ability-20261110.
ABILITY_SLOTS = {0x62: (21, 71), 0x63: (21, 100)}
MAX_PLAYERS = 20_000
# Journal budgets for one bulk call (the tool keeps its own smaller ones).
JOURNAL_REGIONS = 8_000_000
JOURNAL_BYTES = 1024 * 1024 * 1024
PHYSICAL_READS = 60_000_000
PHYSICAL_BYTES = 4 * 1024 * 1024 * 1024
SOURCE_ERRORS = (core.SourceUnavailable, ValueError)


class Rejected(BridgeError):
    pass


# --------------------------------------------------------------------------- pure functions

def threshold_state(low, high, score):
    """Original H threshold branch: 2 if score >= exact, 1 if score >= low, else 0."""
    if not low or not high:
        return 0
    if type(score) is not int or not -128 <= score <= 127:
        raise ValueError('H score must be a signed byte')
    return 2 if score >= high else int(score >= low)


def combined_score(reciprocal, context_k, report=None):
    """H's score: signed8(max(reciprocal node, K)), then max with the selected report byte."""
    score = core._signed(max(reciprocal, context_k), 8)
    if report is not None:
        score = max(score, report)
    return score


def field_state(knowledge, field):
    """(H state, failure detail) for one native field from per-player knowledge inputs.

    State is None exactly when the tool reports ``unavailable_source`` for that cell.
    """
    if knowledge['failure'] is not None:
        return None, knowledge['failure']
    if knowledge['own_context']:
        return 2, None
    low, high = attribute_thresholds.thresholds(field, knowledge['category'])
    if not low or not high:
        return 0, None
    if knowledge['score_failure'] is not None:
        return None, knowledge['score_failure']
    return threshold_state(low, high, knowledge['score']), None


def ability_state(knowledge, slot):
    """(H state, failure detail) for ability slot 0x62 (CA stars) or 0x63 (PA stars)."""
    low, high = ABILITY_SLOTS[slot]
    if knowledge['failure'] is not None:
        return None, knowledge['failure']
    if knowledge['own_context']:
        return 2, None
    if knowledge['score_failure'] is not None:
        return None, knowledge['score_failure']
    return threshold_state(low, high, knowledge['score']), None


def cell_value(field, state, getter, knowledge):
    """The permitted visible value for a known cell (state 1 or 2), as the tool returns it."""
    try:
        if state == 2:
            projection = ranges.native_attribute_projection(getter, 2, native_field_id=field)
        else:
            if knowledge['range_failure'] is not None:
                return dict(state='unavailable', reason='unavailable_source', detail=knowledge['range_failure'])
            projection = ranges.native_attribute_projection(
                getter, 1, native_field_id=field, age=knowledge['age'],
                person_index=knowledge['person_index'], private_knowledge_score=knowledge['score'],
                assessor_bytes=knowledge['assessor_bytes'])
    except ValueError as exc:
        return dict(state='unavailable', reason='unavailable_source', detail=str(exc)[:200])
    permitted = ranges.permitted_passing_value(projection)
    if permitted['state'] == 'unavailable':
        return {'state': 'unavailable', 'reason': 'unsupported_native_projection'}
    return permitted


def winning_sources(knowledge):
    """Which inputs produced H's score: own_club, node, context, report (ties all listed)."""
    if knowledge['failure'] is not None:
        return []
    if knowledge['own_context']:
        return ['own_club']
    if knowledge['score'] is None:
        return []
    score = knowledge['score']
    out = []
    if knowledge['context_k'] is not None and core._signed(knowledge['context_k'], 8) == score:
        out.append('context')
    if knowledge['node_present'] and knowledge['reciprocal'] == score:
        out.append('node')
    if knowledge['report'] is not None and knowledge['report'] == score:
        out.append('report')
    return out


def lowest_thresholds(category):
    """Smallest range and exact thresholds over all 47 fields for a category byte."""
    pairs = [attribute_thresholds.thresholds(field, category) for field in ALL_FIELDS]
    pairs = [pair for pair in pairs if pair[0] and pair[1]]
    if not pairs:
        return None, None
    return min(low for low, _ in pairs), min(high for _, high in pairs)


# --------------------------------------------------------------------------- journal

class BulkJournal:
    """Consumed-byte journal with the attribute-byte firewall and one final fence.

    Rules carried over from ``knowledge_field_firewall``: every read is checked against the
    forbidden intervals unless it is an exactly granted one-byte attribute region; a grant
    needs H 1 or 2 recomputed here from the registered knowledge record; any error poisons
    the journal for good. Overlapping read shapes are checked for byte consistency once at
    the end (no per-page buffers), before the fence.
    """

    def __init__(self, physical, bridge):
        self.physical, self.bridge = physical, bridge
        self.observed = {}
        self.permissions = {}
        self.knowledge = {}
        self.unique_bytes = self.physical_bytes = self.physical_reads = 0
        self.phase = 0
        self.phase_counts = {0: 0, 1: 0}
        self.first_failure = None
        self.authorized_attribute_physical_reads = 0
        self.fenced_regions = 0
        self._forbidden = firewall.Intervals()
        self.source_type = None

    @property
    def forbidden(self):
        return self._forbidden

    @forbidden.setter
    def forbidden(self, intervals):
        for key in self.observed:
            if intervals.intersects(*key) and key not in self.permissions:
                raise ValueError('Attribute byte consumed before forbidden geometry binding')
        self._forbidden = intervals

    def poison(self, error):
        if self.first_failure is None:
            self.first_failure = dict(type=type(error).__name__, error=str(error))

    def healthy(self):
        if self.first_failure is not None:
            raise ValueError('Field capture journal was poisoned: ' + self.first_failure['error'])

    def __call__(self, address, size):
        return self.read(address, size)

    def _geometry(self, address, size):
        if (type(address) is not int or type(size) is not int
                or not 4096 <= address < address + size < 1 << 64 or not 0 < size <= firewall.READ_BYTES):
            raise ValueError('Invalid physical read geometry')
        if self._forbidden.intersects(address, size) and (address, size) not in self.permissions:
            raise ValueError('Unpermitted raw attribute byte/block is forbidden')

    def physical_read(self, address, size):
        try:
            self.healthy()
            self._geometry(address, size)
            if self.physical_reads >= PHYSICAL_READS or self.physical_bytes + size > PHYSICAL_BYTES:
                raise ValueError('Physical audit budget exhausted before read; no partial source accepted')
            self.physical_reads += 1
            self.physical_bytes += size
            self.phase_counts[self.phase] += 1
            raw = self.physical(address, size)
            if type(raw) is not bytes or len(raw) != size:
                raise ValueError('Incomplete physical read')
            if self._forbidden.intersects(address, size):
                self.authorized_attribute_physical_reads += 1
            return raw
        except Exception as exc:
            self.poison(exc)
            raise

    def read(self, address, size):
        cached = self.observed.get((address, size))
        if cached is not None and self.first_failure is None:
            return cached
        try:
            self.healthy()
            self._geometry(address, size)
            if len(self.observed) >= JOURNAL_REGIONS or self.unique_bytes + size > JOURNAL_BYTES:
                raise ValueError('Consumed source budget exhausted before read; no partial source accepted')
            raw = self.physical_read(address, size)
            self.observed[(address, size)] = raw
            self.unique_bytes += size
            return raw
        except Exception as exc:
            self.poison(exc)
            raise

    def register(self, source, knowledge):
        """Bind the approved source's knowledge record; grants consult only this copy."""
        try:
            self.healthy()
            if self.source_type is None or not isinstance(source, self.source_type):
                raise ValueError('Only the bulk approved source can register knowledge')
            key = source.subject.primary
            if key in self.knowledge:
                raise ValueError('Knowledge record already registered for this subject')
            self.knowledge[key] = (id(source), deepcopy(knowledge))
        except Exception as exc:
            self.poison(exc)
            raise

    def authorize_cell(self, source, field):
        try:
            self.healthy()
            if self.source_type is None or not isinstance(source, self.source_type):
                raise ValueError('Only the bulk approved source can request a getter grant')
            if (source.bridge is not self.bridge or source.session != self.bridge.session
                    or source.process != self.bridge.process):
                raise ValueError('Getter source process/session differs')
            owner, knowledge = self.knowledge.get(source.subject.primary, (None, None))
            if owner != id(source):
                raise ValueError('Getter requested before the knowledge record was registered')
            state, _ = field_state(knowledge, field)
            if state not in (1, 2):
                raise ValueError('Recomputed H state does not permit this field getter')
            meta = catalog.field(field)
            address = source.subject.primary + meta['primary_offset']
            if not self._forbidden.intersects(address, 1):
                raise ValueError('Getter primary was not bound to the forbidden attribute geometry')
            self.permissions[(address, 1)] = (field, state)
            return address
        except Exception as exc:
            self.poison(exc)
            raise

    def verify_overlaps(self):
        """Overlapping read shapes must agree byte for byte (checked once, in address order)."""
        try:
            self.healthy()
            span_start, span = None, bytearray()
            for (address, size), raw in sorted(self.observed.items()):
                end = span_start + len(span) if span_start is not None else None
                if span_start is None or address >= end:
                    span_start, span = address, bytearray(raw)
                    continue
                overlap = min(end, address + size) - address
                if span[address - span_start:address - span_start + overlap] != raw[:overlap]:
                    raise ValueError('Conflicting consumed bytes across overlapping read shapes')
                if address + size > end:
                    span.extend(raw[overlap:])
        except Exception as exc:
            self.poison(exc)
            raise

    def verify(self):
        """One physical fence: every consumed region is read again and must be unchanged.

        Regions that share one 4 KiB page are re-read with a single read spanning them when
        that span touches no forbidden attribute interval (a page is mapped as a whole, and
        non-attribute bytes are not hidden); granted attribute bytes and page-crossing
        regions are re-read one by one.
        """
        try:
            self.healthy()
            self.phase = 1
            pages, singles = {}, []
            for key in self.observed:
                address, size = key
                page = address & ~4095
                if (address + size - 1) & ~4095 != page or self._forbidden.intersects(address, size):
                    singles.append(key)
                else:
                    pages.setdefault(page, []).append(key)
            for keys in pages.values():
                low = min(a for a, _ in keys)
                high = max(a + n for a, n in keys)
                if len(keys) == 1 or self._forbidden.intersects(low, high - low):
                    singles.extend(keys)
                    continue
                raw = self.physical_read(low, high - low)
                for address, size in keys:
                    if raw[address - low:address - low + size] != self.observed[(address, size)]:
                        raise ValueError(f'Consumed byte changed at final physical fence ({address:#x}, {size})')
                self.fenced_regions += len(keys)
            for address, size in singles:
                if self.physical_read(address, size) != self.observed[(address, size)]:
                    raise ValueError(f'Consumed byte changed at final physical fence ({address:#x}, {size})')
                self.fenced_regions += 1
            if self.fenced_regions != len(self.observed):
                raise ValueError('Final fence did not cover every consumed region')
        except Exception as exc:
            self.poison(exc)
            raise

    def record(self):
        self.healthy()
        digest = hashlib.sha256()
        for (address, size), raw in sorted(self.observed.items()):
            digest.update(struct.pack('<QI', address, size))
            digest.update(raw)
        return dict(region_count=len(self.observed), consumed_bytes=self.unique_bytes,
                    sha256=digest.hexdigest(), physical_reads=self.physical_reads,
                    physical_bytes=self.physical_bytes, physical_phase_counts=dict(self.phase_counts),
                    final_fence_passes=1, fenced_regions=self.fenced_regions,
                    overlapping_read_shapes_consistent=True,
                    forbidden_attribute_intervals=len(self._forbidden.ranges),
                    authorized_attribute_bytes=len(self.permissions),
                    authorized_attribute_physical_reads=self.authorized_attribute_physical_reads,
                    unpermitted_attribute_bytes_read=False, no_journal_failure_swallowed=True,
                    bounds=dict(regions=JOURNAL_REGIONS, bytes=JOURNAL_BYTES, per_read=firewall.READ_BYTES),
                    physical_bounds=dict(reads=PHYSICAL_READS, bytes=PHYSICAL_BYTES))


class PagedJournal(BulkJournal):
    """BulkJournal over a page cache (``knowledge_inputs.PageSource``), with input recording.

    The forbidden-interval check, the grant rule and the poison rule are those of BulkJournal:
    the engine obtains bytes only through ``read``, and ``read`` refuses a forbidden byte that
    has no grant. What differs is the transport. Pages arrive whole through the fast reader, so
    a region is a slice of a page held once for the whole call; the final fence reads every
    touched page again in one batch and compares each consumed region with it. Every read is
    also appended to the current input collector (``inputs``), which is how a player's consumed
    regions are known afterwards.
    """

    def __init__(self, source, bridge):
        super().__init__(source.read, bridge)
        self.source = source
        self.inputs = inputs_module.Inputs()
        self.memos = {}
        self.memo_hits = self.memo_misses = 0
        self.checked = ()            # span blobs a Verifier compared (fenced like consumed regions)

    def memo(self, key, compute, firewall=False):
        """``compute()`` once per call for ``key``; later uses get the same value or exception.

        Sound inside one call because the journal serves a region's first bytes to every later
        read: a function of its arguments and of memory returns the same thing each time.
        The inputs it consumed are recorded once and attached to every user: copied into the
        user's own inputs, or, with ``firewall``, kept as an outcome group the user refers to
        by key and outcome (so a change of those bytes that leaves the outcome unchanged does
        not reach the user's fingerprint)."""
        hit = self.memos.get(key)
        inputs = self.inputs
        if hit is None:
            self.memo_misses += 1
            # Always recorded in full, even when the first user is inside a suspended section:
            # a later user of the same key may be a tracked one.
            suspended, inputs._suspended = inputs._suspended, 0
            collector = inputs.push()
            try:
                try:
                    outcome = (True, compute())
                except SOURCE_ERRORS as exc:
                    outcome = (False, exc)
            finally:
                inputs.pop()
                if suspended:
                    inputs._suspended = suspended
                    inputs.sink = inputs_module._discard
            if firewall:
                inputs.groups[key] = (inputs_module.outcome_digest(outcome), collector)
                hit = (outcome, None, None, None)
            else:
                hit = (outcome, tuple(dict.fromkeys(collector.log)), tuple(collector.derived),
                       tuple(dict.fromkeys(collector.groups)))
            self.memos[key] = hit
        else:
            self.memo_hits += 1
        if not inputs._suspended:
            current = inputs.stack[-1]
            if hit[1] is None:
                current.groups.append(key)
            else:
                if hit[1]:
                    current.log.extend(hit[1])
                if hit[2]:
                    current.derived.extend(hit[2])
                if hit[3]:
                    current.groups.extend(hit[3])
        ok, value = hit[0]
        if ok:
            return value
        raise type(value)(*value.args)

    def read(self, address, size):
        key = (address, size)
        self.inputs.sink(key)
        cached = self.observed.get(key)
        if cached is not None and self.first_failure is None:
            return cached
        try:
            self.healthy()
            self._geometry(address, size)
            if len(self.observed) >= JOURNAL_REGIONS or self.unique_bytes + size > JOURNAL_BYTES:
                raise ValueError('Consumed source budget exhausted before read; no partial source accepted')
            # A first read is a slice of a cached page (the page fetch is the physical read).
            raw = self.physical(address, size)
            if type(raw) is not bytes or len(raw) != size:
                raise ValueError('Incomplete physical read')
            if key in self.permissions:
                self.authorized_attribute_physical_reads += 1
            self.observed[key] = raw
            self.unique_bytes += size
            return raw
        except Exception as exc:
            self.poison(exc)
            raise

    def record(self):
        self.healthy()
        source = self.source
        digest = None
        if RECORD_DIGEST:
            h = hashlib.sha256()
            for (address, size), raw in sorted(self.observed.items()):
                h.update(struct.pack('<QI', address, size))
                h.update(raw)
            digest = h.hexdigest()
        return dict(region_count=len(self.observed), consumed_bytes=self.unique_bytes, sha256=digest,
                    physical_reads=source.fetches, physical_bytes=source.pages_read * source.page_size,
                    pages=len(source.pages()), final_fence_passes=1, fenced_regions=self.fenced_regions,
                    fence_changed_pages=getattr(self, 'fence_changed_pages', None),
                    overlapping_read_shapes_consistent=True,
                    forbidden_attribute_intervals=len(self._forbidden.ranges),
                    authorized_attribute_bytes=len(self.permissions),
                    authorized_attribute_physical_reads=self.authorized_attribute_physical_reads,
                    unpermitted_attribute_bytes_read=False, no_journal_failure_swallowed=True,
                    memo=dict(hits=self.memo_hits, misses=self.memo_misses),
                    bounds=dict(regions=JOURNAL_REGIONS, bytes=JOURNAL_BYTES, per_read=firewall.READ_BYTES))

    def verify_overlaps(self):
        """Every region is a slice of the one copy of its page held for the call, so two read
        shapes covering the same byte cannot disagree; there is nothing to compare."""
        self.healthy()

    def verify(self):
        """One physical fence: every touched page is read again (one batched read) and every
        consumed region must hold the bytes it held when first read."""
        try:
            self.healthy()
            self.phase = 1
            source = self.source
            cached = source.pages()
            fresh = source.fresh()
            size, mask = source.page_size, source.mask
            changed = {base for base, raw in fresh.items() if raw != cached[base]}
            self.fence_pages = len(fresh)
            if changed:
                slice_pages = inputs_module.slice_pages
                for (address, length), raw in self.observed.items():
                    base = address & mask
                    if base in changed or ((address + length - 1) & mask) in changed \
                            or (address + length - 1) & mask != base and any(
                                b in changed for b in range(base, address + length, size)):
                        if slice_pages(fresh, size, address, length) != raw:
                            raise ValueError(
                                f'Consumed byte changed at final physical fence ({address:#x}, {length})')
                for blob in self.checked:
                    for start, length in inputs_module._SPAN.iter_unpack(blob):
                        base = start & mask
                        if base in changed or ((start + length - 1) & mask) in changed \
                                or (start + length - 1) & mask != base and any(
                                    b in changed for b in range(base, start + length, size)):
                            if slice_pages(fresh, size, start, length) != slice_pages(cached, size, start, length):
                                raise ValueError(
                                    f'Verified byte changed at final physical fence ({start:#x}, {length})')
            self.fenced_regions = len(self.observed)
            self.fence_pages = len(fresh)
            self.fence_changed_pages = len(changed)
        except Exception as exc:
            self.poison(exc)
            raise


class _JournalRead(world.ReadSet):
    """Shared world read for every source in the call. The journal already records each
    consumed region and the final fence rechecks it, so this keeps no second copy."""

    def __call__(self, address, length):
        data = self.read(address, length)
        if len(data) != length:
            raise ValueError('Incomplete world read')
        return data

    def verify(self):
        return None


def _bulk_bridge_type(helper):
    Base = km._journal_bridge(helper)

    class BulkBridge(Base):
        def __init__(self):
            self.world_cache = None
            self.page_source = None
            super().__init__()

        def _read_memory(self, process, address, length):
            if self.journal is None:
                self.journal_process = process
                if self.page_source is not None:
                    self.journal = PagedJournal(self.page_source, self)
                else:
                    physical = lambda a, n: bridge_module.Bridge._read_memory(self, self.journal_process, a, n)
                    self.journal = BulkJournal(physical, self)
            if process is not self.journal_process and process != self.journal_process:
                raise ValueError('Physical process identity changed')
            return self.journal.read(address, length)

        def _world_state(self, process, tables):
            if self.world_cache is None:
                return super()._world_state(process, tables)
            cached_process, cached_tables, read, save, identity = self.world_cache
            if process != cached_process or tables != cached_tables:
                raise ValueError('Bulk world context process/layout changed')
            return read, deepcopy(save), deepcopy(identity)

    return BulkBridge


# --------------------------------------------------------------------------- approved source

class _CallIndex:
    """Per-call indexes over HUMAN-owned vectors, built once with the approved source's readers.

    Each lookup reproduces exactly what the per-subject scan of the tool returns or raises.
    """

    def __init__(self):
        self.primary = None      # (rows, keys) or exception
        self.alternate = None    # (first position by UID, error position, error, entries)
        self.owner_nodes = None  # (set of nodes before first error, error) or exception


def _source_type(journal, call_index):
    class BulkBase(km.Approved):
        # The tool's per-cell world re-reads are served from the journal, so they cannot see
        # a change; the call's final context check and physical fence do. Process identity
        # stays checked here through the kernel incarnation token.
        def lifetime(self):
            process = self.bridge._current(self.session)
            if process != self.process or self.bridge.plugin_identity != self.plugin:
                raise core.SourceUnavailable('Bridge process/plugin/save/date/selected coach changed')
            return self._lifetime_identity

        def verify(self):
            self.lifetime()

        # ---- report selection over the per-call index (same semantics as the tool)
        def _primary_reports(self):
            if call_index.primary is None:
                try:
                    start, count = self._assessment_bounds(self.human + 0x110)
                    rows, keys = [], []
                    for i in range(count):
                        row = self.ptr(start + 8 * i)
                        if not row:
                            raise core.SourceUnavailable('Null sorted relation assessment slot')
                        person = self.ptr(row)
                        key = struct.unpack('<i', self.read(person + 8, 4))[0] if person else 0
                        rows.append(row)
                        keys.append(key)
                    if keys != sorted(keys):
                        raise core.SourceUnavailable('Relation assessment subject-index range is not sorted')
                    call_index.primary = (rows, keys)
                except SOURCE_ERRORS as exc:
                    call_index.primary = exc
            if isinstance(call_index.primary, Exception):
                exc = call_index.primary
                raise type(exc)(*exc.args)
            return call_index.primary

        def _report_rows(self, target):
            rows, keys = self._primary_reports()
            return rows[bisect_left(keys, target):bisect_right(keys, target)]

        def _relation_club_assessment(self):
            for row in self._report_rows(self.subject.person.identity[0]):
                person = self.reader.resolve_placeholder(self.ptr(row))
                if not person:
                    continue
                if person != self.subject.person.address:
                    raise core.SourceUnavailable('Relation assessment subject changed')
                assessor = self.ptr(row + 8)
                if not assessor:
                    continue
                club = self.generic_eligible_club(assessor)
                if club is None:
                    continue
                owner = self.generic_eligible_club(self.owner.person.address)
                if club == owner or self.reader.parent(club.address) == (owner.address if owner else 0):
                    return row
            return None

        def _alternate_reports(self):
            if call_index.alternate is None:
                try:
                    start, count = self._assessment_bounds(self.human + 0x128)
                except SOURCE_ERRORS as exc:
                    call_index.alternate = exc
                else:
                    first, entries, error_at, error = {}, [], None, None
                    for position, i in enumerate(range(count - 1, -1, -1)):
                        try:
                            row = self.ptr(start + 8 * i)
                            if not row:
                                continue
                            person = self.ptr(row)
                            if not person:
                                continue
                            uid = self.u32(person + 0xc)
                        except SOURCE_ERRORS as exc:
                            error_at, error = position, exc
                            break
                        entries.append((row, person))
                        first.setdefault(uid, (position, row, person))
                    call_index.alternate = (first, error_at, error)
            if isinstance(call_index.alternate, Exception):
                exc = call_index.alternate
                raise type(exc)(*exc.args)
            return call_index.alternate

        def _alternate_lookup(self, uid):
            """(row, person) of the first usable alternate entry for a raw UID, else None;
            raises the scan's error when the scan stopped before reaching one."""
            first, error_at, error = self._alternate_reports()
            hit = first.get(uid)
            if hit is not None and (error_at is None or hit[0] < error_at):
                return hit[1], hit[2]
            if error_at is not None:
                raise type(error)(*error.args)
            return None

        def ui_report(self):
            row = self._relation_club_assessment()
            if row is not None:
                self.ptr(row + 8)
                return row
            hit = self._alternate_lookup(self.subject.person.identity[1])
            if hit is not None:
                row, person = hit
                if person != self.subject.person.address:
                    raise core.SourceUnavailable('UI alternate assessment UID is ambiguous')
                self.ptr(row + 8)
                return row
            return None

        # ---- reciprocal node with the owner vector indexed once
        def _owner_nodes(self):
            if call_index.owner_nodes is None:
                try:
                    own_start, own_count = self._reciprocal_used_bounds(self.fow_record)
                except SOURCE_ERRORS as exc:
                    call_index.owner_nodes = exc
                else:
                    nodes, error = [], None
                    for j in range(own_count):
                        try:
                            nodes.append(self.knowledge_node(own_start + 8 * j))
                        except SOURCE_ERRORS as exc:
                            error = exc
                            break
                    call_index.owner_nodes = (set(nodes), error, nodes, self.fow_record)
            if isinstance(call_index.owner_nodes, Exception):
                exc = call_index.owner_nodes
                raise type(exc)(*exc.args)
            if call_index.owner_nodes[3] != self.fow_record:
                raise ValueError('FOW owner record changed within the call')
            return call_index.owner_nodes

        def _owner_node_check(self, row):
            nodes, error, _, _ = self._owner_nodes()
            if row not in nodes:
                if error is not None:
                    raise type(error)(*error.args)
                raise core.SourceUnavailable('Reciprocal node not in selected FOW owner vector')

        def reciprocal_score(self):
            self.ordinary_primary()
            start, count = self._reciprocal_used_bounds(self.subject.primary + 0xc8)
            owner_uid = self.owner.person.identity[1]
            self._node_present = False
            for i in range(count - 1, -1, -1):
                row = self.knowledge_node(start + 8 * i, required=True)
                if self.u32(row + 4) != owner_uid:
                    continue
                if self.u32(row) != self.subject.person.identity[0]:
                    raise core.SourceUnavailable('Reciprocal node subject ordinal changed')
                self._owner_node_check(row)
                self._node_present = True
                return core._signed(self.u8(row + 8), 8)
            return 0

        # ---- per-player knowledge inputs (field independent)
        def knowledge(self, fields, *, want_score=False):
            """UiCallerSource.state + SelectorSource.state with the field-dependent threshold
            comparison left out; every branch and exception order is kept."""
            k = dict(failure=None, own_context=False, category=None, score=None, score_failure=None,
                     reciprocal=None, node_present=False, context_k=None, context_k_failure=None,
                     report_present=False, report=None, person_index=self.subject.person.identity[0],
                     age=None, assessor_bytes=None, range_failure=None, range_inputs=False)
            try:
                selected = self.ui_report()
                candidate = self.own_candidate()
                self.ordinary_primary()
                candidate = self.apply_auxiliary(candidate)
                self.assessment_selected = True
                self.assessment_record = None
                if candidate:
                    k['own_context'] = True
                else:
                    self.route(self.ptr(self.subject.primary), 0x518, 0xd5c4bc)
                    k['category'] = self.u8(self.subject.primary + 0x268)
            except SOURCE_ERRORS as exc:
                k['failure'] = str(exc)[:200]
                return k
            self.assessment_record = selected
            self.assessment_selected = True
            k['report_present'] = selected is not None
            needs = want_score or (not k['own_context'] and any(
                all(attribute_thresholds.thresholds(field, k['category'])) for field in fields))
            if not needs:
                return k
            try:
                stored = self.reciprocal_score()
                k['reciprocal'], k['node_present'] = stored, self._node_present
                result = core.evaluate(self)
                k['context_k'] = result.score
                if result.score is None:
                    k['context_k_failure'] = str(result.reason)[:200]
                    raise core.SourceUnavailable('Required contextual K unavailable: ' + str(result.reason))
                score = core._signed(max(stored, result.score), 8)
                if selected is not None:
                    k['report'] = core._signed(self.u8(selected + 0x3f), 8)
                    score = max(score, k['report'])
                k['score'] = score
            except SOURCE_ERRORS as exc:
                k['score_failure'] = str(exc)[:200]
            return k

        def range_inputs(self, k):
            """State-1 projection inputs, in the tool's evaluation order (age, then assessor)."""
            k['range_inputs'] = True
            try:
                k['age'] = self.native_age(self.subject)
                k['assessor_bytes'] = self.assessor_bytes()
            except SOURCE_ERRORS as exc:
                k['range_failure'] = str(exc)[:200]

        def getter_value(self, field):
            journal.authorize_cell(self, field)
            meta = catalog.field(field)
            self.ordinary_primary()
            self.route(self.ptr(self.subject.primary), 0xf0, 0xd19eb0)
            mode = self.u8(self.subject.primary + 0x270)
            stored = self.u8(self.subject.primary + meta['primary_offset'])
            return ranges.passing_getter(stored, mode)

    return BulkBase


# --------------------------------------------------------------------------- capture

def _bridge_and_session(bridge_or_session):
    if isinstance(bridge_or_session, tuple) and len(bridge_or_session) == 2:
        bridge, session_id = bridge_or_session
    else:
        bridge, session_id = bridge_or_session, getattr(bridge_or_session, 'session', None)
    if not isinstance(bridge, bridge_module.Bridge) or type(session_id) is not str or not session_id:
        raise BridgeError('Pass an attached Bridge or (bridge, session_id).')
    return bridge, session_id


def _validate_keys(player_keys):
    if type(player_keys) not in (list, tuple) or not 1 <= len(player_keys) <= MAX_PLAYERS:
        raise BridgeError(f'Supply 1 through {MAX_PLAYERS} player keys.')
    seen = set()
    for key in player_keys:
        ok = ((type(key) is int and key >= 0)
              or (type(key) is str and key)
              or (type(key) is tuple and len(key) == 2 and key[0] in ('ordinal', 'address')
                  and type(key[1]) is int and key[1] >= 0))
        if not ok:
            raise BridgeError('Player keys are PERSON indices, player_ref strings, '
                              "('ordinal', n) or ('address', primary).")
        if key in seen:
            raise BridgeError('Player keys must be distinct.')
        seen.add(key)
    return list(player_keys)


# Paged engine: also hash every consumed region into the journal record (comparison runs only;
# sorting and hashing several million regions costs seconds on a whole save).
RECORD_DIGEST = False
ENGINES = ('paged', 'journal')
# 'paged': page-cached fast reader, input recording (default). 'journal': one helper round trip
# per region, the first bulk engine; kept as the comparison path.
DEFAULT_ENGINE = 'paged'
# Test seam: callable(process) -> fmdb.memory.MemoryBase used by the paged engine.
MEMORY_FACTORY = None


def _open_memory(process):
    if MEMORY_FACTORY is not None:
        return MEMORY_FACTORY(process)
    from .fmdb.memory import LiveMemory
    return LiveMemory(process.pid, expected_executable=process.executable)


# Per-process-incarnation facts that cannot change while that incarnation lives: the helper's
# loaded-image answer, the plugin's on-disk identity by file stamp, and the forbidden attribute
# geometry by the bytes of the primary vectors it was built from. Keyed by the kernel token.
_SESSION = {}


def _session(token):
    key = generation.token(token)
    if key not in _SESSION:
        _SESSION.clear()
        _SESSION[key] = dict(images={}, plugin=None, intervals=None)
    return _SESSION[key]


def _forbidden_intervals(journal, base, cache):
    """``firewall.attribute_intervals`` with the sorted geometry reused while the three primary
    vectors hold the same bytes (they are read in full either way)."""
    digest = hashlib.blake2b(digest_size=16)
    for rva in firewall.PRIMARY_VECTOR_RVAS:
        header = journal(base + rva, 24)
        digest.update(header)
        start, end, cap = struct.unpack('<QQQ', header)
        if (start, end, cap) == (0, 0, 0):
            continue
        if (start < 4096 or any(v % 8 for v in (start, end, cap)) or not start <= end <= cap
                or cap - start > 16_000_000):
            raise ValueError('Invalid native primary vector geometry/budget')
        for offset in range(start, end, firewall.READ_BYTES):
            digest.update(journal(offset, min(firewall.READ_BYTES, end - offset)))
    key = digest.digest()
    if cache['intervals'] is None or cache['intervals'][0] != key:
        cache['intervals'] = (key, firewall.attribute_intervals(journal, base, players))
    intervals = cache['intervals'][1]
    for address, size in journal.observed:
        if intervals.intersects(address, size):
            raise ValueError('Attribute payload consumed before interval binding')
    return intervals


def _require_forbidden(journal, primary):
    """A subject's attribute block must lie inside the bound forbidden geometry."""
    start, end = primary + firewall.ATTRIBUTE_BLOCK_START, primary + firewall.ATTRIBUTE_BLOCK_END
    intervals = journal.forbidden
    index = bisect_right(intervals.starts, start) - 1
    if index < 0 or intervals.ranges[index][1] < end:
        journal.forbidden = firewall.Intervals(list(intervals.ranges) + [(start, end)])


class Plan:
    """Incremental request for the paged engine: fingerprints stored by an earlier call.

    ``context`` is that call's ``inputs['context']``; ``players`` maps a PERSON index to its
    stored fingerprint and ``groups`` an encoded group key to its stored record. Players whose
    fingerprint still holds are not evaluated; the result lists them under ``inputs['kept']``.
    """

    def __init__(self, context=None, players=None, groups=None):
        self.context, self.players, self.groups = context, players or {}, groups or {}


def _capture(main, session_id, keys, fields, coach_name, mode, on_progress, native=False, engine=None,
             plan=None):
    engine = engine or DEFAULT_ENGINE
    if engine not in ENGINES:
        raise Rejected(f'Unknown knowledge engine {engine!r}')
    memory = None
    started = time.monotonic()
    timings = {}
    process = main._current(session_id)
    bindings = {}
    for key in keys:
        if type(key) is str:
            binding = main.player_refs.get(key)
            if type(binding) is not dict:
                raise Rejected('Unknown or expired player reference')
            bindings[key] = deepcopy(binding)
    relation_fixes.RECEIPTS.clear()
    bridge = _bulk_bridge_type(main.helper)()
    original_stream = scope.ReadStream
    if original_stream is not bridge_module.ReadStream:
        raise Rejected('Private stream transport changed')
    result = None
    try:
        intended = bridge_module.process_info(process.pid)
        if intended is None or intended != process:
            raise Rejected('The game process changed since fm_attach')
        kernel = generation.KernelIdentity()
        baseline = kernel(process.pid)
        cache = None
        if engine == 'paged':
            memory = _open_memory(process)
            generation.require_generation(kernel(process.pid), baseline)
            bridge.page_source = inputs_module.PageSource(memory)
            cache = _session(baseline)
        sid = bridge.attach(pid=process.pid)['session_id']
        generation.require_generation(kernel(process.pid), baseline)
        if bridge.process != process:
            raise Rejected('Intended attachment process changed')
        stream_type = generation.bound_stream_type(firewall.SegmentedStream, kernel, baseline)
        scope.ReadStream = lambda helper, pid: stream_type(bridge, bridge_module.ReadStream, helper, pid)
        bridge.fast_checks = (kernel, baseline)
        if engine == 'paged':
            # Inside the call the kernel incarnation token stands for the `ps` process check and
            # the helper's loaded-image answer is asked once per incarnation.
            bridge.image_cache = cache['images']
            bridge.kernel_identity, bridge.kernel_baseline = kernel, baseline
            if cache['plugin'] is not None:
                bridge.plugin_identity = cache['plugin']   # re-validated against the file stamp
            try:
                result = _read_all_paged(bridge, sid, keys, bindings, fields, coach_name, mode, on_progress,
                                         timings, native, plan, baseline, cache)
            finally:
                bridge.image_cache = None
                bridge.kernel_identity = bridge.kernel_baseline = None
            intended = bridge_module.process_info(process.pid)
            if intended is None or intended != process:
                raise Rejected('The game process changed during the capture')
        else:
            result = _read_all(bridge, sid, keys, bindings, fields, coach_name, mode, on_progress, timings,
                               native)
        if memory is not None:
            generation.require_generation(kernel(process.pid), baseline)
    finally:
        scope.ReadStream = original_stream
        if memory is not None:
            memory.close()
        try:
            detach = bridge.detach()
        except Exception as exc:
            raise Rejected(f'Private bridge detach failed: {exc}') from exc
        if detach != {'detached': True}:
            raise Rejected('Private bridge detach was not verified')
        if any(not row['closed'] for row in bridge.transport_segments):
            raise Rejected('Native port closure was not verified')
    for segment in bridge.transport_segments:
        checks = segment.get('kernel_generation_checks', {})
        if (segment.get('kernel_generation_errors')
                or set(checks) != {'before_lazy_port_open', 'after_first_physical_read', 'before_port_close'}):
            raise Rejected('Incomplete kernel generation receipt')
        for observed in checks.values():
            generation.require_generation(observed, baseline)
    result['cost'] = dict(seconds=round(time.monotonic() - started, 2),
                          phases={k: round(v, 2) for k, v in timings.items()},
                          distinct_regions=result['journal']['region_count'],
                          physical_reads=result['journal']['physical_reads'],
                          native_ports=len(bridge.transport_segments))
    return result


def _context(bridge, sid, process, tables, plugin, base, coach_name):
    now = bridge._current(sid)
    layout = bridge._player_layout(now)
    if now != process or layout != tables or bridge.plugin_identity != plugin:
        raise ValueError('Process/plugin/session/layout changed')
    read, save, identity = bridge._world_state(now, layout)
    coach = deepcopy(bridge._select_coach(save, coach_name))
    team, human = prepared_tactics_source._team_and_human(read, base, coach)
    read.verify()
    return dict(save=deepcopy(save), world=deepcopy(identity), coach=coach, team=team, human=human)


def _read_all(bridge, sid, keys, bindings, fields, coach_name, mode, on_progress, timings, native=False):
    t0 = time.monotonic()
    with bridge.lock, scope.collection_stream(bridge, sid):
        process = deepcopy(bridge._current(sid))
        tables = bridge._player_layout(process)
        base = tables[0] - players.RVA[0]
        plugin = deepcopy(bridge.plugin_identity)
        before = _context(bridge, sid, process, tables, plugin, base, coach_name)
        journal = bridge.journal
        journal.forbidden = firewall.attribute_intervals(journal, base, players)
        read = journal
        people = database.table(read, base, 'people')
        assessment_people.verify_native(read, base)
        population.verify_native(read, base)
        ordinal_cache = []

        def ordinals():
            if not ordinal_cache:
                ordinal_cache.append(all_actual_primaries(read, base))
            return ordinal_cache[0]

        subjects = [_subject(read, base, tables, people, key, bindings.get(key), ordinals) for key in keys]
        intervals = list(journal.forbidden.ranges)
        for row in subjects:
            if row.get('person') is not None:
                intervals.append((row['primary'] + firewall.ATTRIBUTE_BLOCK_START,
                                  row['primary'] + firewall.ATTRIBUTE_BLOCK_END))
        journal.forbidden = firewall.Intervals(intervals)
        extra = _population_seeds(bridge, read, base, before, people, tables) if mode == 'population' else None
    timings['setup'] = time.monotonic() - t0
    call_index = _CallIndex()
    BulkBase = _source_type(journal, call_index)
    journal.source_type = BulkBase
    native_operands, native_verify = None, None
    if native:
        # Optional: refused relation-mask / transfer-predicate branches answered by the
        # original functions in the emulator (knowledge_native). Off by default.
        from . import knowledge_native
        from .fmdb.image import PluginImage
        native_operands = knowledge_native.NativeOperands(journal, base, PluginImage.load(plugin[0][0]))
        native_verify = {} if native == 'verify' else None
    receipts_total = 0
    bridge.image_cache = {}
    bridge.kernel_identity, bridge.kernel_baseline = bridge.fast_checks
    t1 = time.monotonic()
    try:
        with bridge.lock, scope.collection_stream(bridge, sid):
            # One shared world read for every source in the evaluation.
            world_read, save, identity = bridge._world_state(process, tables)
            if save != before['save'] or identity != before['world']:
                raise ValueError('Selected context changed before evaluation')
            bridge.world_cache = (process, tables, _JournalRead(world_read.read), save, identity)
            for done, row in enumerate(subjects, 1):
                receipts = {}
                Controlled = structural.source_type(BulkBase, transfer, live_transfer_offers, journal, receipts)
                if native_operands is not None:
                    # Outermost: only a refusal raised before the structural extension runs
                    # is answered natively; every Python-answered operand path is untouched.
                    Controlled = knowledge_native.source_type(Controlled, native_operands, verify=native_verify)
                _evaluate(bridge, sid, Controlled, journal, row, fields, coach_name, mode)
                receipts_total += len(receipts)
                journal.healthy()
                if on_progress is not None:
                    on_progress(done, len(subjects))
    finally:
        if native_operands is not None:
            native_operands.close()
        bridge.world_cache = None
        bridge.image_cache = None
        bridge.kernel_identity = bridge.kernel_baseline = None
    timings['evaluate'] = time.monotonic() - t1
    t2 = time.monotonic()
    with bridge.lock, scope.collection_stream(bridge, sid):
        after = _context(bridge, sid, process, tables, plugin, base, coach_name)
        if after != before:
            raise ValueError('Selected context changed during the capture')
        if bridge._current(sid) != process or bridge.world_identity != before['world'] \
                or bridge.plugin_identity != plugin:
            raise ValueError('Final world/plugin/process differs')
        for snapshot in bridge.snapshots:
            snapshot.verify()
        journal.verify_overlaps()
        journal.verify()
        if players.disk_uuid(Path(plugin[0][0])) != plugin[1]:
            raise ValueError('Full plugin disk fingerprint changed')
        record = journal.record()
    timings['final_fence'] = time.monotonic() - t2
    out = dict(before=before, subjects=subjects, journal=record, structural_receipts=receipts_total,
               population=extra)
    if native_operands is not None:
        out['native'] = dict(calls=dict(native_operands.calls), refusals=dict(native_operands.refusals),
                             verify=native_verify)
    return out


def context_key(before, base, plugin, people, token):
    """What every fingerprint of a call is relative to: the process incarnation, the plugin, the
    loaded save, the selected coach and the people table. The game date and the save counters
    are not part of it; a player's own date facts carry the date."""
    save = {k: v for k, v in before['save'].items() if k in ('name', 'created_date', 'created_version')}
    return json.loads(json.dumps(dict(
        process=list(generation.token(token)), base=base, plugin=[list(plugin[0]), plugin[1]],
        save=save, world=before['world'], coach=before['coach'], team=before['team'], human=before['human'],
        people=[people['start'], people['root'], people['header']], people_count=people['count']),
        default=list))


def context_holds(stored, now):
    """Fingerprints taken under ``stored`` are usable under ``now``: everything equal, except
    that the people table may have grown. A fingerprinted evaluation passed every `index <
    count` check it made (rows with a failure get no fingerprint), growth keeps those true, and
    the two places where the count decides something else record it as a fact
    (`people_count`). The end pointer of the table is left out of the byte ranges for the
    same reason."""
    if not isinstance(stored, dict) or not isinstance(now, dict):
        return False
    a = {k: v for k, v in stored.items() if k != 'people_count'}
    b = {k: v for k, v in now.items() if k != 'people_count'}
    return a == b and type(stored.get('people_count')) is int and now['people_count'] >= stored['people_count']


def fingerprintable(row):
    """Only a row without any failure gets a fingerprint; the others are evaluated every time."""
    k = row.get('knowledge')
    if row.get('person') is None or k is None:
        return False
    if any(k.get(name) is not None for name in ('failure', 'score_failure', 'range_failure', 'context_k_failure')):
        return False
    return all(cell.get('state') != 'unavailable' for cell in row.get('fields', ()))


def _read_all_paged(bridge, sid, keys, bindings, fields, coach_name, mode, on_progress, timings, native,
                    plan, token, cache):
    """The paged call: set-up, verification of stored fingerprints, evaluation of the players
    that need it, one final context check and fence, then the new fingerprints."""
    from . import knowledge_fast
    from . import knowledge_search_admission as age_module
    t0 = time.monotonic()
    with bridge.lock, scope.collection_stream(bridge, sid):
        process = deepcopy(bridge._current(sid))
        tables = bridge._player_layout(process)
        base = tables[0] - players.RVA[0]
        plugin = deepcopy(bridge.plugin_identity)
        before = _context(bridge, sid, process, tables, plugin, base, coach_name)
        cache['plugin'] = plugin
        journal = bridge.journal
        inputs = journal.inputs
        journal.forbidden = _forbidden_intervals(journal, base, cache)
        read = journal
        people = database.table(read, base, 'people')
        assessment_people.verify_native(read, base)
        population.verify_native(read, base)
        ordinal_cache = []

        def ordinals():
            if not ordinal_cache:
                ordinal_cache.append(all_actual_primaries(read, base))
            return ordinal_cache[0]

        extra = _population_seeds(bridge, read, base, before, people, tables) if mode == 'population' else None
    context = context_key(before, base, plugin, people, token)
    timings['setup'] = time.monotonic() - t0
    call_index = _CallIndex()
    Plain = _source_type(journal, call_index)
    BulkBase = knowledge_fast.source_type(Plain, journal)
    journal.source_type = BulkBase
    native_operands, native_verify = None, None
    if native:
        from . import knowledge_native
        from .fmdb.image import PluginImage
        native_operands = knowledge_native.NativeOperands(journal, base, lambda: PluginImage.load(plugin[0][0]))
        native_verify = {} if native == 'verify' else None
    receipts_total = 0
    subjects, kept, collectors, stats = [], [], {}, dict(verified=0, kept=0, groups_recomputed=0)
    verifier = None
    t1 = time.monotonic()
    try:
        with bridge.lock, scope.collection_stream(bridge, sid):
            world_read, save, identity = bridge._world_state(process, tables)
            if save != before['save'] or identity != before['world']:
                raise ValueError('Selected context changed before evaluation')
            bridge.world_cache = (process, tables, knowledge_fast.direct_read(journal), save, identity)
            # One source class for the call; `receipts` is emptied per player, which is what a
            # fresh class with a fresh dict per player amounted to.
            receipts = {}
            Controlled = structural.source_type(BulkBase, transfer, live_transfer_offers, journal, receipts)
            if native_operands is not None:
                # Outermost: only a refusal raised before the structural extension runs is
                # answered natively; every Python-answered operand path is untouched.
                Controlled = knowledge_native.source_type(Controlled, native_operands, verify=native_verify)
            factory = knowledge_fast.SourceFactory(Controlled, bridge, sid, coach_name, fields[0], journal)

            def resolve(key):
                collector = inputs.push()
                try:
                    row = _subject(read, base, tables, people, key, bindings.get(key), ordinals)
                finally:
                    inputs.pop()
                if row.get('person') is not None:
                    _require_forbidden(journal, row['primary'])
                return row, collector

            todo = list(keys)
            stored = plan.players if plan is not None and context_holds(plan.context, context) else {}
            candidates = [key for key in keys if type(key) is int and key in stored]
            if candidates:
                tv = time.monotonic()
                anchor = None
                inputs.push()                   # verification reads belong to no player
                try:
                    for key in candidates[:64]:
                        row, _ = resolve(key)
                        if row.get('person') is None:
                            continue
                        try:
                            anchor = factory(row['person'], tuple(row['subject_identity']))
                            break
                        except core.SourceUnavailable:
                            continue
                    if anchor is not None:
                        verifier = _verifier(journal, anchor, Plain, plan.groups, age_module)
                        wanted, seen = [], set()
                        for key in candidates:
                            wanted.append(stored[key]['spans'])
                            for group, _ in stored[key]['groups']:
                                if group not in seen:
                                    seen.add(group)
                                    if group in plan.groups:
                                        wanted.append(plan.groups[group]['spans'])
                        verifier.prefetch(wanted)
                        valid = {key for key in candidates if verifier.fingerprint_ok(stored[key])}
                        kept = [key for key in keys if key in valid]
                        todo = [key for key in keys if key not in valid]
                        reasons = {}
                        for key in candidates:
                            if key not in valid:
                                reason = verifier.why(stored[key])
                                reasons[reason] = reasons.get(reason, 0) + 1
                        stats.update(verified=len(candidates), kept=len(kept),
                                     groups_recomputed=verifier.recomputed,
                                     groups_kept=len(verifier.kept_groups), invalid=reasons)
                finally:
                    inputs.pop()
                timings['verify'] = time.monotonic() - tv
            for done, key in enumerate(todo, 1):
                row, collector = resolve(key)
                subjects.append(row)
                receipts.clear()
                inputs.push(collector)
                try:
                    _evaluate(bridge, sid, factory, journal, row, fields, coach_name, mode)
                finally:
                    inputs.pop()
                if type(key) is int and fingerprintable(row):
                    collectors[key] = collector
                receipts_total += len(receipts)
                journal.healthy()
                if on_progress is not None:
                    on_progress(done, len(todo))
    finally:
        if native_operands is not None:
            native_operands.close()
        bridge.world_cache = None
    timings['evaluate'] = time.monotonic() - t1 - timings.get('verify', 0.0)
    t2 = time.monotonic()
    with bridge.lock, scope.collection_stream(bridge, sid):
        after = _context(bridge, sid, process, tables, plugin, base, coach_name)
        if after != before:
            raise ValueError('Selected context changed during the capture')
        if bridge._current(sid) != process or bridge.world_identity != before['world'] \
                or bridge.plugin_identity != plugin:
            raise ValueError('Final world/plugin/process differs')
        for snapshot in bridge.snapshots:
            snapshot.verify()
        if verifier is not None:
            journal.checked = verifier.checked
        journal.verify_overlaps()
        journal.verify()
        # The plugin file was hashed when its identity was bound; an unchanged file stamp
        # (device, inode, size, mtime) stands for that hash here.
        stat = Path(plugin[0][0]).stat()
        if (plugin[0][0], stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) != tuple(plugin[0]):
            raise ValueError('Full plugin disk fingerprint changed')
        record = journal.record()
    timings['final_fence'] = time.monotonic() - t2
    out = dict(before=before, subjects=subjects, journal=record, structural_receipts=receipts_total,
               population=extra)
    if plan is not None:
        t3 = time.monotonic()
        prints = inputs_module.Fingerprints(
            inputs, journal.source, code=(base + relation_fixes.TEXT[0], base + relation_fixes.TEXT[1]),
            rewrite={(people['header'], 24): (people['header'], 8)})
        out['inputs'] = dict(context=context, kept=kept, players=prints.players(collectors),
                             groups=prints.groups(), stats=stats)
        timings['fingerprints'] = time.monotonic() - t3
    if native_operands is not None:
        out['native'] = dict(calls=dict(native_operands.calls), refusals=dict(native_operands.refusals),
                             verify=native_verify)
    return out


def _verifier(journal, anchor, plain, groups, age_module):
    """Verifier bound to one constructed source: date facts from its context, outcome groups
    through its (memoised, recording) methods."""
    inputs = journal.inputs
    indexes = dict(primary_reports='_primary_reports', alternate_reports='_alternate_reports',
                   owner_nodes='_owner_nodes')
    unknown = object()

    def facts(kind, args):
        today = anchor.context.today.parts
        if kind == 'date_le':
            return tuple(args) <= today
        if kind == 'date_lt':
            return tuple(args) < today
        if kind == 'date_since_gt':
            return plain.days_since_exceeds(anchor, args[0], args[1], args[2])
        if kind == 'date_raw':
            return list(today)
        if kind == 'people_count':
            return anchor.people['count']
        if kind == 'age':
            from . import knowledge_fast
            inputs.suspend()
            try:
                try:
                    outcome = (True, plain._age_from_birth(anchor, age_module.NativeDate(args[0], args[1])))
                except SOURCE_ERRORS as exc:
                    outcome = (False, exc)
            finally:
                inputs.resume()
            return knowledge_fast.fact_outcome(outcome)
        return unknown

    def recompute(text):
        try:
            key = inputs_module.decode_key(text)
        except (ValueError, TypeError, core.SourceUnavailable):
            return None
        kind = key[0]
        try:
            if kind == 'index' and key[1] in indexes:
                getattr(anchor, indexes[key[1]])()
            elif kind == 'report_rows':
                anchor._report_rows(key[1])
            elif kind == 'alternate_report':
                anchor._alternate_lookup(key[1])
            elif kind == 'owner_node':
                anchor._owner_node_check(key[1])
            elif kind == 'recent_nodes':
                anchor._recent_nodes(key[1], key[2], key[3])
            elif kind == 'op' and key[1] in ('next_fixture', 'game_team98'):
                anchor._operand(key[1], *key[2:])
            elif kind == 'op' and key[1] == 'club_score':
                # the operand checks that it is asked about the bound subject
                bound, anchor.subject = anchor.subject, key[4]
                try:
                    anchor._operand('club_score', key[2], key[3], 14, 45, key[4])
                finally:
                    anchor.subject = bound
            else:
                return None
        except SOURCE_ERRORS:
            pass
        record = inputs.groups.get(key)
        return record[0] if record is not None else None

    return inputs_module.Verifier(journal.source, groups, facts, recompute)


def _subject(read, base, tables, people, key, binding, ordinals):
    """Resolve one key; player_refs go through the tool's own resolver unchanged."""
    if type(key) is str:
        row = km._subject(read, base, tables, people, key, binding)
        row['key'] = key
        return row
    row = dict(key=key, person=None, primary=None)
    try:
        primary, _ = _primary_for_key(read, base, people, key, ordinals)
    except IndexError:
        row['reason'] = 'key_outside_native_vector'
        return row
    if primary is None:
        row['reason'] = 'not_a_player_record'
        return row
    table = players.u64(read(primary, 8))
    if table == base + world.TYPES['virtual_player'][0]:
        row.update(record_kind='virtual', reason='unsupported_record_kind_compact_or_generated')
        return row
    if table not in (base + players.RVA[0], base + players.STAFF_RVA[0]):
        row['reason'] = 'not_a_player_record'
        return row
    try:
        ordinary = population._base_identity(read, base, people, primary)
    except population.SourceUnavailable:
        row['reason'] = 'unsupported_all_actual_source_family'
        return row
    except ValueError as exc:
        row.update(reason='identity_rejected', detail=str(exc)[:200])
        return row
    person = ordinary['person']
    _, index, uid, secondary = struct.unpack('<QIII', read(person, 20))
    expected = dict(database_index=index, native_id=uid, random_id=None if secondary == uid else secondary)
    if ordinary['native_identity'] != expected or not uid:
        row.update(reason='identity_rejected', detail='Canonical ordinary identity changed')
        return row
    row.update(person=person, primary=primary, record_kind=ordinary['record_kind'],
               subject_identity=(index, uid, secondary), native_identity=expected)
    return row


def _unavailable_row(row, fields, value):
    row['fields'] = [dict(native_field_id=f, name=catalog.FIELDS[f][0], **value) for f in fields]


def _evaluate(bridge, sid, Controlled, journal, row, fields, coach_name, mode):
    if row.get('person') is None:
        value = dict(state='unavailable', reason=row['reason'])
        if 'detail' in row:
            value['detail'] = row['detail']
        row['knowledge'] = None
        if mode == 'cells':
            _unavailable_row(row, fields, value)
        return
    try:
        if isinstance(Controlled, type):
            source = Controlled(bridge, sid, row['person'], tuple(row['subject_identity']), coach_name, fields[0])
        else:       # paged engine: knowledge_fast.SourceFactory
            source = Controlled(row['person'], tuple(row['subject_identity']))
    except core.SourceUnavailable as exc:
        detail = str(exc)[:200]
        row['knowledge'] = dict(failure=detail, own_context=False, category=None, score=None,
                                score_failure=None, reciprocal=None, node_present=False, context_k=None,
                                context_k_failure=None, report_present=False, report=None,
                                person_index=row['subject_identity'][0], range_failure=None)
        if mode == 'cells':
            _unavailable_row(row, fields, dict(state='unavailable', reason='unavailable_source', detail=detail))
        return
    knowledge = source.knowledge(fields, want_score=(mode != 'cells'))
    states = {field: field_state(knowledge, field) for field in fields}
    if mode == 'cells' and any(state == 1 for state, _ in states.values()):
        source.range_inputs(knowledge)
    journal.register(source, knowledge)
    row['knowledge'] = knowledge
    if mode == 'cells':
        values = []
        for field in fields:
            state, detail = states[field]
            if state is None:
                value = dict(state='unavailable', reason='unavailable_source', detail=detail)
            elif state == 0:
                value = {'state': 'unknown'}
            else:
                value = cell_value(field, state, source.getter_value(field), knowledge)
            values.append(dict(native_field_id=field, name=catalog.FIELDS[field][0], **value))
        row['fields'] = values
    source.verify()


# --------------------------------------------------------------------------- key helpers

def all_actual_primaries(read, base):
    """The native all_actual PLAYER primary vector (Player Search base source)."""
    start, count = population._bounds(read, base + population.BASE_VECTORS['all_actual'],
                                      population.SOURCE_LIMIT)
    return population._values(read, start, count)


def _primary_for_key(read, base, people, key, ordinals):
    """(primary address or None, record kind or None) for a non-ref key."""
    if type(key) is int:
        if not 0 <= key < people['count']:
            raise IndexError('PERSON index outside the live people table')
        person = world.pointer(read, people['start'] + key * 8)
        try:
            primary, _, public, _, _ = assessment_people._person(read, base, people, person)
        except ValueError:
            return None, None
        return primary, public['record_kind']
    if key[0] == 'ordinal':
        primary = ordinals()[key[1]]
        return (primary or None), None
    return key[1], None


def bind_player_refs(bridge, session_id, keys):
    """Publish ordinary player_refs for PERSON indices, all_actual ordinals or primaries.

    Regression helper for comparing with the existing tool. Uses the same roster
    decode and binding as the ranking tools. Non-player or compact records map to None.
    """
    out, pending = {}, {}
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        snapshot, _, _ = bridge._world_state(process, tables)
        base = tables[0] - players.RVA[0]
        people = database.table(snapshot, base, 'people')
        cache = []

        def ordinals():
            if not cache:
                cache.append(all_actual_primaries(snapshot, base))
            return cache[0]
        for key in keys:
            primary, _ = _primary_for_key(snapshot, base, people, key, ordinals)
            table = players.u64(snapshot(primary, 8)) if primary else 0
            if table not in (base + players.RVA[0], base + players.STAFF_RVA[0]):
                out[key] = None
                continue
            player, token = bridge._roster_player(snapshot, primary, tables, False, {},
                                                  profile_policy='available')
            pending[key] = bridge._player_binding(primary, player, token, tables, 'available')
        snapshot.verify()
    for key, binding in pending.items():
        ref = secrets.token_urlsafe(12)
        bridge.player_refs[ref] = binding
        out[key] = ref
    return out


# --------------------------------------------------------------------------- public API

def _field_ids(fields):
    if fields is None or fields == 'all' or fields == ALL_FIELDS:
        return ALL_FIELDS
    return km.field_ids(list(fields))


def _run(bridge_or_session, player_keys, fields, coach_name, mode, on_progress, native=False, engine=None,
         plan=None):
    bridge, session_id = _bridge_and_session(bridge_or_session)
    keys = _validate_keys(player_keys) if player_keys is not None else []
    if coach_name is not None and (type(coach_name) is not str or not 1 <= len(coach_name) <= 256):
        raise BridgeError('coach_name must be a name returned by fm_get_save.')
    if on_progress is not None and not callable(on_progress):
        raise BridgeError('on_progress must be callable.')
    try:
        with bridge.lock:
            return _capture(bridge, session_id, keys, fields, coach_name, mode, on_progress, native, engine,
                            plan)
    except (ValueError, IndexError, KeyError, TypeError, AssertionError, BridgeError, OSError) as exc:
        raise BridgeError(f'Bulk knowledge query rejected; no partial result returned: {exc}') from exc


def _header(raw, session_id):
    before = raw['before']
    return dict(session_id=session_id, observed_at=datetime.now(timezone.utc).isoformat(),
                save=dict(name=before['save']['name'], current_date=before['save']['current_date']),
                coach=before['coach']['name'], club=before['coach']['club'],
                cost=raw['cost'], game_writes=False,
                firewall=dict(forbidden_attribute_intervals=raw['journal']['forbidden_attribute_intervals'],
                              attribute_bytes_authorised=raw['journal']['authorized_attribute_bytes'],
                              unpermitted_attribute_bytes_read=False,
                              final_physical_fences=raw['journal']['final_fence_passes'],
                              distinct_regions=raw['journal']['region_count']))


def _identity_fields(row):
    out = dict(key=row['key'], record_kind=row.get('record_kind'), native_identity=row.get('native_identity'))
    if type(row['key']) is str:
        out.update(player_ref=row['key'], name=row.get('name'), display_name=row.get('display_name'))
    return out


def visible_attributes_bulk(bridge_or_session, player_keys, fields=ALL_FIELDS, *, coach_name=None,
                            on_progress=None, native=False):
    """Manager-visible attribute cells for many players.

    Each player row carries ``fields`` in the tool's exact cell shape (exact/range/unknown/
    unavailable) plus ``state_counts``. ``bridge_or_session`` is an attached Bridge or
    ``(bridge, session_id)``. ``on_progress(done, total)`` is called after each player.
    ``native=True`` answers the refused relation-mask and transfer-predicate branches of K with
    the original functions in the emulator (``knowledge_native``); ``'verify'`` also runs them
    where Python answered and counts agreements. Default off: outputs are those of the tool.
    """
    ids = _field_ids(fields)
    bridge, session_id = _bridge_and_session(bridge_or_session)
    raw = _run((bridge, session_id), player_keys, ids, coach_name, 'cells', on_progress, native)
    out = []
    for row in raw['subjects']:
        entry = _identity_fields(row)
        entry['fields'] = row['fields']
        entry['state_counts'] = {s: sum(f['state'] == s for f in row['fields']) for s in STATES}
        out.append(entry)
    states = [f['state'] for row in raw['subjects'] for f in row['fields']]
    result = _header(raw, session_id)
    result.update(view='manager_visible_attributes_bulk', players=out, count=len(out),
                  fields=[catalog.FIELDS[f][0] for f in ids],
                  state_counts={s: states.count(s) for s in STATES},
                  cells_per_second=round(len(states) / max(raw['cost']['seconds'], 1e-9), 1))
    if 'native' in raw:
        result['native_operands'] = raw['native']
    return result


def _summary(row):
    entry = _identity_fields(row)
    k = row.get('knowledge')
    if k is None:
        entry.update(state='unavailable', reason=row.get('reason'), detail=row.get('detail'))
        return entry
    counts = dict(exact=0, range=0, unknown=0, unavailable=0)
    for field in ALL_FIELDS:
        state, _ = field_state(k, field)
        counts[{None: 'unavailable', 0: 'unknown', 1: 'range', 2: 'exact'}[state]] += 1
    ability = {}
    for slot, name in ((0x62, 'current_ability'), (0x63, 'potential_ability')):
        state, detail = ability_state(k, slot)
        ability[name] = dict(slot=hex(slot), h_state=state, **({'detail': detail} if state is None else {}))
    low, exact = lowest_thresholds(k['category']) if k['category'] is not None else (None, None)
    entry.update(state='available' if k['failure'] is None else 'unavailable',
                 failure=k['failure'], own_club_context=k['own_context'], category_byte=k['category'],
                 context_k=k['context_k'], context_k_failure=k['context_k_failure'],
                 node_present=k['node_present'], node_score=k['reciprocal'] if k['node_present'] else None,
                 report_present=k['report_present'], report_score=k['report'],
                 h_score=k['score'], h_score_failure=k['score_failure'],
                 winning_sources=winning_sources(k),
                 lowest_range_threshold=low, lowest_exact_threshold=exact,
                 field_state_counts=counts, any_exact=counts['exact'] > 0,
                 any_range=counts['range'] > 0, any_known=counts['exact'] + counts['range'] > 0,
                 all_unknown=counts['unknown'] == len(ALL_FIELDS), star_gates=ability)
    return entry


def player_knowledge_summary(bridge_or_session, player_keys, *, coach_name=None, on_progress=None,
                             native=False):
    """Per player the scalar knowledge facts; reads no attribute byte at all.

    K, the reciprocal node score, the selected report score, the own-club flag, the category
    byte, the winning source(s) of H's score, how many of the 47 fields would be exact,
    range, unknown or unavailable, and the H states of the CA/PA star gates (0x62, 0x63).
    Unlike the cell path, K is evaluated even when every field's H ignores it (own-club,
    zero thresholds), so ``context_k`` can be reported; H itself is unchanged.
    """
    bridge, session_id = _bridge_and_session(bridge_or_session)
    raw = _run((bridge, session_id), player_keys, ALL_FIELDS, coach_name, 'summary', on_progress, native)
    result = _header(raw, session_id)
    rows = [_summary(row) for row in raw['subjects']]
    result.update(view='manager_knowledge_summary', players=rows, count=len(rows))
    if 'native' in raw:
        result['native_operands'] = raw['native']
    return result


# --------------------------------------------------------------------------- population

def _person_index(read, base, people, person):
    _, _, public, _, _ = assessment_people._person(read, base, people, person)
    return public['native_identity']['database_index'], public['record_kind']


def _population_seeds(bridge, read, base, before, people, tables):
    """Candidate PERSON indices from the HUMAN's FOW owner record, both report vectors and
    the selected club's team rosters. Reads no attribute byte."""
    human = before['human']
    reader = transfer._Reader(read, base)
    seeds = dict(fow_nodes=set(), fow_nodes_other_owner=0, report_primary=set(), report_alternate=set(),
                 own_club_rosters=set())
    # FOW owner record (FOG_OF_WAR_MANAGER at RVA 0x56a8430, indexed by HUMAN+0x3e4).
    manager = reader.ptr(base + 0x56a8430)
    prepared_tactics_source._typed(read, base, manager, 0x55f5d80, b'18FOG_OF_WAR_MANAGER')
    index = struct.unpack('<i', read(human + 0x3e4, 4))[0]
    start, count = reader.bounds(manager + 0x18, 8, 4096)
    if not 0 <= index < count:
        raise ValueError('Selected HUMAN FOW ordinal is invalid')
    record = reader.ptr(start + 8 * index)
    if not record or reader.ptr(record + 0x18) != human + 0x548:
        raise ValueError('FOW owner record PERSON differs from selected HUMAN')
    owner_uid = struct.unpack('<I', read(human + 0x548 + 0xc, 4))[0]
    node_start, node_count = reader.bounds(record, 8, used_range.CAPACITY_LIMIT)
    node_scores = {}
    for j in range(node_count):
        node = players.u64(read(node_start + 8 * j, 8))
        if not node:
            continue
        subject, owner, score = struct.unpack('<IIb', read(node, 9))
        if owner != owner_uid:
            seeds['fow_nodes_other_owner'] += 1
            continue
        seeds['fow_nodes'].add(subject)
        node_scores[subject] = score
    prefetch = getattr(getattr(read, 'source', None), 'prefetch', None)
    for offset, name in ((0x110, 'report_primary'), (0x128, 'report_alternate')):
        start, count = reader.bounds(human + offset, 8, 2_000_000)
        if prefetch is not None and count:
            # Page-cached journal: fetch the rows' pages, then the PERSON pages they point at,
            # in two batched reads instead of one round trip per first touch.
            prefetch([(start, 8 * count)])
            rows = [players.u64(read.source.read(start + 8 * i, 8)) for i in range(count)]
            prefetch([(row, 16) for row in rows if row >= 4096])
            people_at = [players.u64(read.source.read(row, 8)) for row in rows if row >= 4096]
            prefetch([(person, 32) for person in people_at if person >= 4096])
        for i in range(count):
            row = reader.ptr(start + 8 * i)
            if not row:
                continue
            person = reader.ptr(row)
            if not person:
                continue
            if offset == 0x110:
                person = reader.resolve_placeholder(person)
                if not person:
                    continue
            try:
                index, _ = _person_index(read, base, people, person)
            except ValueError:
                continue
            seeds[name].add(index)
    club = world.pointer(read, before['coach']['team_address'] + 0x30)
    start, count = reader.bounds(club + 0x18, 8, 4096)
    for t in range(count):
        team = reader.ptr(start + 8 * t)
        if not team:
            continue
        for primary in world.vector(read, team + 0x38, 512):
            table = players.u64(read(primary, 8))
            if table not in (base + players.RVA[0], base + players.STAFF_RVA[0]):
                continue
            offset = players.person_offset(read, primary, tables)
            index, _ = _person_index(read, base, people, primary + offset)
            seeds['own_club_rosters'].add(index)
    seeds['fow_node_scores'] = node_scores
    seeds['fow_owner_vector_used_slots'] = node_count
    return seeds


def known_population(bridge_or_session, *, coach_name=None, evaluate=True, on_progress=None):
    """Enumerate the players the selected manager has knowledge of, without a field scan.

    Seeds: PERSON ordinals named by the HUMAN's FOW owner record nodes, the subjects of both
    report vectors (HUMAN+0x110 resolved through placeholders, HUMAN+0x128 raw) and every
    player on the selected club's team rosters. With ``evaluate`` the knowledge summary
    (no attribute byte) runs over the seed union and each definition is counted; that is a
    second capture, so a game that advances between the two can differ slightly.

    Contextual K (nation, league, reputation, club relations) also reaches players outside
    these seeds; counting them needs a summary pass over the all_actual vector (see
    ``random_ordinals`` for a sampled estimate).
    """
    bridge, session_id = _bridge_and_session(bridge_or_session)
    raw = _run((bridge, session_id), None, ALL_FIELDS, coach_name, 'population', None)
    seeds = raw['population']
    union = sorted(seeds['fow_nodes'] | seeds['report_primary'] | seeds['report_alternate']
                   | seeds['own_club_rosters'])
    result = _header(raw, session_id)
    result.update(view='manager_known_population',
                  seed_counts=dict(fow_nodes=len(seeds['fow_nodes']),
                                   fow_nodes_other_owner=seeds['fow_nodes_other_owner'],
                                   fow_owner_vector_used_slots=seeds['fow_owner_vector_used_slots'],
                                   report_primary=len(seeds['report_primary']),
                                   report_alternate=len(seeds['report_alternate']),
                                   own_club_rosters=len(seeds['own_club_rosters']),
                                   union=len(union)),
                  seeds={k: sorted(v) for k, v in seeds.items() if isinstance(v, set)},
                  union=union)
    if evaluate and union:
        summary = player_knowledge_summary((bridge, session_id), union, coach_name=coach_name,
                                           on_progress=on_progress)
        result['summary_cost'] = summary['cost']
        result['definitions'] = population_definitions(summary['players'])
        result['players'] = summary['players']
    return result


def population_definitions(rows):
    """Counts of each supported definition of 'known' over evaluated summary rows."""
    available = [r for r in rows if r.get('state') == 'available']
    count = lambda pred: sum(1 for r in available if pred(r))
    return dict(
        evaluated=len(rows), unavailable=len(rows) - len(available),
        node_present=count(lambda r: r['node_present']),
        report_present=count(lambda r: r['report_present']),
        own_club_context=count(lambda r: r['own_club_context']),
        any_field_range_or_exact=count(lambda r: r['any_known']),
        any_field_exact=count(lambda r: r['any_exact']),
        all_fields_unknown=count(lambda r: r['all_unknown']),
        h_score_unavailable=count(lambda r: r['h_score'] is None and not r['own_club_context']),
        ca_star_gate_known=count(lambda r: (r['star_gates']['current_ability']['h_state'] or 0) >= 1),
        ca_star_gate_exact=count(lambda r: r['star_gates']['current_ability']['h_state'] == 2))


def random_ordinals(bridge_or_session, count, seed=20261111):
    """Deterministic sample of all_actual ordinals (for population estimates)."""
    bridge, session_id = _bridge_and_session(bridge_or_session)
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        snapshot, _, _ = bridge._world_state(process, tables)
        primaries = all_actual_primaries(snapshot, tables[0] - players.RVA[0])
        snapshot.verify()
    rng = random.Random(seed)
    picks = rng.sample(range(len(primaries)), min(count, len(primaries)))
    return [('ordinal', o) for o in sorted(picks)], len(primaries)
