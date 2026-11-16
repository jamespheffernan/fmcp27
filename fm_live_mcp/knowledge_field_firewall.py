"""Attribute-byte firewall for Manager-visible attribute reads.

Package form of the reviewed evidence code (lane commit 268c3a2):
``collect_field.py`` Intervals/Journal/SegmentedStream/attribute_intervals and
``field_authorization.py``. The rules are unchanged:

* every stored attribute byte of every primary record is a forbidden interval;
* a forbidden byte may be read only as an exact one-byte region that the
  approved source authorised after recomputing the native H state (1 or 2);
* any journal error poisons the capture permanently, even if a caller swallows
  the exception, so a failed read can never yield a partial answer;
* two complete physical fences re-read every consumed region at the end.

One deliberate difference from the evidence journal: a region already read in
this capture is served from the journal instead of being read from the game
again. The evidence journal re-read every region on every call, about 5 million
physical reads for 28 players of which 16,228 were distinct. Repeated regions
are still checked against the forbidden intervals on every call, and the two
final fences read each distinct region from the game again and compare it with
the first read, so a changed byte still rejects the whole capture.
"""
from bisect import bisect_left
from copy import deepcopy
import hashlib
import json
import struct

READ_BYTES = 16384
JOURNAL_BYTES = 16 * 1024 * 1024
JOURNAL_REGIONS = 131_072
PHYSICAL_BYTES = 512 * 1024 * 1024
PHYSICAL_READS = 20_000_000
ALIAS_PAGE_LIMIT = 32768
STREAM_REQUESTS = 90_000
STREAM_BYTES = 60 * 1024 * 1024
PRIMARY_VECTOR_RVAS = (0x56d2e18, 0x56d2e30, 0x56d2e48)
ATTRIBUTE_BLOCK_START = 0x148
ATTRIBUTE_BLOCK_END = 0x18d
AUDIT_HEADER = struct.Struct('<QIIQ')  # address, size, phase, one-based sequence; then raw bytes


class Intervals:
    """Sorted disjoint forbidden intervals; every bounded read costs O(log n)."""

    def __init__(self, intervals=()):
        merged = []
        for start, end in sorted(intervals):
            if type(start) is not int or type(end) is not int or not 4096 <= start < end < 1 << 64:
                raise ValueError('Invalid forbidden interval')
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        self.ranges = tuple(merged)
        self.starts = tuple(a for a, _ in merged)

    def intersects(self, address, size):
        index = bisect_left(self.starts, address)
        return bool((index and self.ranges[index - 1][1] > address) or
                    (index < len(self.ranges) and self.ranges[index][0] < address + size))


class Journal:
    """Consumed-byte journal over the physical reader.

    ``audit`` is an optional binary stream that receives every physical read
    (header, then bytes); the public tool passes none.
    """

    def __init__(self, physical, audit=None):
        self.physical, self.audit = physical, audit
        self.observed = {}
        self.unique_bytes = self.physical_bytes = self.physical_reads = 0
        self.phase = 0
        self.forbidden = Intervals()
        self.phase_counts = {0: 0, 1: 0, 2: 0}

    @property
    def forbidden(self):
        return self._forbidden

    @forbidden.setter
    def forbidden(self, intervals):
        # Invariant behind the repeated-read fast path: a region already in the journal
        # was admitted under the intervals then in force, and no later set of intervals
        # may cover it (except an exactly authorised one-byte attribute getter).
        allowed = getattr(self, 'permissions', {})
        for key in self.observed:
            if intervals.intersects(*key) and key not in allowed:
                raise ValueError('Attribute byte consumed before forbidden geometry binding')
        self._forbidden = intervals

    def __call__(self, address, size):
        return self.read(address, size)

    def _geometry(self, address, size):
        if (type(address) is not int or type(size) is not int
                or not 4096 <= address < address + size < 1 << 64 or not 0 < size <= READ_BYTES):
            raise ValueError('Invalid physical read geometry')
        if self.forbidden.intersects(address, size):
            raise ValueError('Raw player attribute payload is forbidden')

    def physical_read(self, address, size):
        self._geometry(address, size)
        if self.physical_reads >= PHYSICAL_READS or self.physical_bytes + size > PHYSICAL_BYTES:
            raise ValueError('Physical audit budget exhausted before read; no partial source accepted')
        self.physical_reads += 1
        self.physical_bytes += size
        self.phase_counts[self.phase] += 1
        if self.audit is not None:
            # An attempted read is recorded before it can fail.
            self.audit.write(AUDIT_HEADER.pack(address, size, self.phase, self.physical_reads))
        raw = self.physical(address, size)
        if type(raw) is not bytes:
            raise ValueError('Invalid physical bytes')
        if self.audit is not None:
            self.audit.write(raw)
        if len(raw) != size:
            raise ValueError('Incomplete physical read')
        return raw

    def read(self, address, size):
        cached = self.observed.get((address, size))
        if cached is not None:
            return cached
        self._geometry(address, size)
        key = (address, size)
        if len(self.observed) >= JOURNAL_REGIONS or self.unique_bytes + size > JOURNAL_BYTES:
            raise ValueError('Consumed source budget exhausted before read; no partial source accepted')
        raw = self.physical_read(address, size)
        self.observed[key] = raw
        self.unique_bytes += size
        return raw

    def verify(self, phase):
        if phase not in (1, 2):
            raise ValueError('Unknown physical fence phase')
        self.phase = phase
        for (address, size), expected in self.observed.items():
            if self.physical_read(address, size) != expected:
                raise ValueError('Consumed byte changed at final physical fence')

    def record(self):
        rows = [dict(address=hex(a), size=n, rawhex=raw.hex()) for (a, n), raw in sorted(self.observed.items())]
        encoded = json.dumps(rows, separators=(',', ':'), ensure_ascii=True).encode()
        return dict(region_count=len(rows), consumed_bytes=self.unique_bytes,
                    sha256=hashlib.sha256(encoded).hexdigest(), truncated=False,
                    physical_reads=self.physical_reads, physical_bytes=self.physical_bytes,
                    physical_phase_counts=dict(self.phase_counts), final_fence_passes=2,
                    forbidden_attribute_intervals=len(self.forbidden.ranges),
                    bounds=dict(bytes=JOURNAL_BYTES, regions=JOURNAL_REGIONS, per_read=READ_BYTES),
                    physical_bounds=dict(bytes=PHYSICAL_BYTES, reads=PHYSICAL_READS),
                    repeated_regions_served_from_journal=True)


def journal_type(base_type, approved_source_type, catalog):
    """Journal that authorises exact one-byte attribute getters and poisons on any error."""

    class FieldJournal(base_type):
        def __init__(self, physical, audit, bridge):
            super().__init__(physical, audit)
            self.bridge = bridge
            self.permissions = {}
            self.authorization_receipts = []
            self.authorized_attribute_physical_reads = 0
            self.first_failure = None
            self.alias_pages = {}

        def poison(self, error):
            if self.first_failure is None:
                self.first_failure = dict(type=type(error).__name__, error=str(error))

        def healthy(self):
            if self.first_failure is not None:
                raise ValueError('Field capture journal was poisoned: ' + self.first_failure['error'])

        def _geometry(self, address, size):
            if (type(address) is not int or type(size) is not int
                    or not 4096 <= address < address + size < 1 << 64 or not 0 < size <= READ_BYTES):
                raise ValueError('Invalid physical read geometry')
            if self.forbidden.intersects(address, size) and (address, size) not in self.permissions:
                raise ValueError('Unpermitted raw attribute byte/block is forbidden')

        def physical_read(self, address, size):
            try:
                self.healthy()
                raw = super().physical_read(address, size)
                if self.forbidden.intersects(address, size):
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
                new = (address, size) not in self.observed
                if new:
                    pages = range(address & ~4095, (address + size - 1 & ~4095) + 4096, 4096)
                    if len(self.alias_pages) + sum(p not in self.alias_pages for p in pages) > ALIAS_PAGE_LIMIT:
                        raise ValueError('Consumed alias-page budget exhausted before read')
                raw = super().read(address, size)
                if new:
                    for offset, byte in enumerate(raw):
                        at = address + offset
                        page, index = at & ~4095, at & 4095
                        buffers = self.alias_pages.get(page)
                        if buffers is None:
                            buffers = (bytearray(4096), bytearray(4096))
                            self.alias_pages[page] = buffers
                        data, known = buffers
                        if known[index] and data[index] != byte:
                            raise ValueError('Conflicting consumed bytes across overlapping read shapes')
                        data[index] = byte
                        known[index] = 1
                return raw
            except Exception as exc:
                self.poison(exc)
                raise

        def verify(self, phase):
            try:
                self.healthy()
                return super().verify(phase)
            except Exception as exc:
                self.poison(exc)
                raise

        def authorize(self, source, expected_decision):
            try:
                self.healthy()
                if not isinstance(source, approved_source_type):
                    raise ValueError('Only the approved typed field source can request a getter grant')
                if (source.bridge is not self.bridge or source.session != self.bridge.session
                        or source.process != self.bridge.process):
                    raise ValueError('Getter source process/session differs')
                if expected_decision is None:
                    raise ValueError('Getter requested before a permitted-state evaluation')
                field = catalog.field(source.field)
                if source.field_metadata != field or source._lifetime_identity[-1] != source.field:
                    raise ValueError('Getter field metadata/lifetime binding differs')
                # Call the pinned approved implementation directly. An expected
                # state supplied by the wrapper is never sufficient authority.
                actual = approved_source_type.state(source)
                if (actual != expected_decision or type(actual) is not tuple or len(actual) != 3
                        or type(actual[0]) is not int or actual[0] not in (1, 2)):
                    raise ValueError('Fresh native H state does not permit this field getter')
                address = source.subject.primary + field['primary_offset']
                if not self.forbidden.intersects(address, 1):
                    raise ValueError('Getter primary was not bound to the forbidden attribute geometry')
                receipt = dict(address=hex(address), size=1, native_field_id=source.field,
                               compiled_name=field['compiled_name'], native_H_state=actual[0],
                               observer_identity=source.owner.person.identity,
                               subject_identity=source.subject.person.identity,
                               current_date=source.save['current_date'],
                               session_identity_sha256=hashlib.sha256(source.session.encode()).hexdigest(),
                               source_lifetime_sha256=hashlib.sha256(repr(source._lifetime_identity).encode()).hexdigest(),
                               authority='fresh_pinned_source_H_state_recomputed_before_exact_one_byte_getter')
                self.permissions[(address, 1)] = deepcopy(receipt)
                self.authorization_receipts.append(receipt)
            except Exception as exc:
                self.poison(exc)
                raise

        def record(self):
            self.healthy()
            result = super().record()
            result.update(authorized_attribute_bytes=len(self.permissions),
                          authorized_attribute_physical_reads=self.authorized_attribute_physical_reads,
                          field_authorization_receipts=deepcopy(self.authorization_receipts),
                          no_journal_failure_swallowed=True, unpermitted_attribute_bytes_read=False,
                          consumed_alias_pages=len(self.alias_pages), consumed_alias_page_bound=ALIAS_PAGE_LIMIT,
                          overlapping_read_shapes_consistent=True)
            return result

    return FieldJournal


def source_type(approved_source_type, journal):
    """Approved source whose getter is granted only by ``journal.authorize``."""

    class ObservedFieldSource(approved_source_type):
        _latest_decision = None

        def state(self):
            self._latest_decision = None
            result = super().state()
            self._latest_decision = result
            return result

        def getter(self):
            journal.authorize(self, self._latest_decision)
            return super().getter()

    return ObservedFieldSource


def attribute_intervals(read, base, players):
    """Forbidden interval of every primary record's stored attribute block."""
    intervals = []
    for rva in PRIMARY_VECTOR_RVAS:
        start, end, cap = struct.unpack('<QQQ', read(base + rva, 24))
        if (start, end, cap) == (0, 0, 0):
            continue
        if (start < 4096 or any(v % 8 for v in (start, end, cap)) or not start <= end <= cap
                or cap - start > 16_000_000):
            raise ValueError('Invalid native primary vector geometry/budget')
        for offset in range(start, end, READ_BYTES):
            raw = read(offset, min(READ_BYTES, end - offset))
            for primary, in struct.iter_unpack('<Q', raw):
                if primary:
                    if primary < 4096 or primary % 8:
                        raise ValueError('Invalid native primary pointer')
                    intervals.append((primary + ATTRIBUTE_BLOCK_START,
                                      primary + ATTRIBUTE_BLOCK_START + max(players.ATTRIBUTES.values()) + 1))
    result = Intervals(intervals)
    for address, size in read.observed:
        if result.intersects(address, size):
            raise ValueError('Attribute payload consumed before interval binding')
    return result


class SegmentedStream:
    """Explicit task-port segments below both unchanged native helper limits."""

    def __init__(self, bridge, reader_type, helper, pid):
        self.bridge, self.reader_type, self.helper, self.pid = bridge, reader_type, helper, pid
        self.process, self.session = deepcopy(bridge.process), bridge.session
        self.reader = None
        self.requests = self.bytes = 0
        self.closed = False

    def read(self, address, length):
        if self.closed:
            raise ValueError('Segmented stream is closed')
        if (self.bridge.process != self.process or self.bridge.session != self.session
                or self.process.pid != self.pid or self.bridge.helper != self.helper):
            raise ValueError('Segmented transport process/session/helper binding changed')
        if (type(address) is not int or type(length) is not int
                or not 0 < address < 2 ** 64 - length or not 1 <= length <= READ_BYTES):
            raise ValueError('Invalid segmented read geometry')
        if self.reader is not None and (self.requests >= STREAM_REQUESTS or self.bytes + length > STREAM_BYTES):
            self._close_segment()
        if self.reader is None:
            self.reader = self.reader_type(self.helper, self.pid)
            self.requests = self.bytes = 0
            self.digest = hashlib.sha256()
            self.segment = dict(ordinal=len(self.bridge.transport_segments) + 1, pid=self.pid,
                                helper=str(self.helper), process_started=self.process.started,
                                session_identity_sha256=hashlib.sha256(self.session.encode()).hexdigest(),
                                requests=0, bytes=0, closed=False)
            self.bridge.transport_segments.append(self.segment)
        self.requests += 1
        self.bytes += length
        self.segment.update(requests=self.requests, bytes=self.bytes)
        self.digest.update(struct.pack('<QI', address, length))
        raw = self.reader.read(address, length)
        self.digest.update(raw)
        return raw

    def _close_segment(self):
        reader, self.reader = self.reader, None
        if reader is not None:
            reader.close()
            self.segment['closed'] = True
            self.segment['requests_and_raw_sha256'] = self.digest.hexdigest()

    def close(self):
        self.closed = True
        self._close_segment()
