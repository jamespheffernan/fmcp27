"""Checked original name vectors and a unique structural late-name candidate.

The early C8/D0/D8 anchor is reached sequentially through native-backed table
readers. Late indexed strings are discovered over every remaining byte offset;
this does not establish a sequential route through supplemental TEAM/CLUB data
or prove the following PERSON factory/reference globals. The caller pins the
supplied read-only buffer and keeps it alive for the returned layout's lifetime.
"""
from array import array
from dataclasses import dataclass, field
import re
import struct

from . import (
    saved_club_records, saved_database, saved_database_header,
    saved_database_tables, saved_region_tables, saved_squad_tables,
)
from .saved_component_stream import Reader, MAX_RAW_SIZE

NAMESPACES = ('first', 'second', 'common')
MAX_NAME_ROWS = saved_region_tables.MAX_NAME_ROWS
MAX_PERSON_ROWS = 2_000_000
MAX_CANDIDATES = 4096
MAX_ROW_WORK = 12_000_000
MAX_TEXT_BYTES = 8192
_U32 = struct.Struct('<I')
_PAIR = struct.Struct('<II')


class _Limit(ValueError):
    """An incomplete search must not be treated as a rejected candidate."""


class _Source:
    """Non-owning bounded read adapter; no exported mmap views are retained."""
    def __init__(self, data):
        self.data, self.offset = data, 0

    def read(self, amount):
        if amount < 0:
            raise ValueError('Invalid saved-name source read')
        start = self.offset
        self.offset = min(len(self.data), start + amount)
        return bytes(self.data[start:self.offset])


@dataclass(frozen=True)
class NameLayout:
    person_count: int
    person_offset: int
    person_flags: int
    early_offset: int
    early_end: int
    overlay_offset: int
    _counts: tuple[int, int, int] = field(repr=False)
    _offsets: tuple[array, array, array] = field(repr=False)
    _data: object = field(repr=False, compare=False)
    base_currency_code: str | None = None

    @property
    def person_records_offset(self):
        return self.person_offset + 5

    @property
    def name_counts(self):
        return dict(zip(NAMESPACES, self._counts, strict=True))

    @property
    def provenance(self):
        return {
            'early_names': 'sequential native-backed header and complete tables',
            'late_names': 'unique complete structural three-vector conjunction',
            'person_header': 'structural candidate; intervening supplement route unproved',
            'source_identity': 'caller-pinned same-file read-only buffer',
            'reference_globals': 'unproved',
        }

    def lookup_raw(self, namespace, index):
        if namespace not in NAMESPACES:
            raise ValueError('Unknown saved-name namespace')
        if type(index) is not int or index < -1:
            raise ValueError('Invalid saved-name index')
        if index == -1:
            return None
        slot = NAMESPACES.index(namespace)
        if index >= self._counts[slot]:
            raise ValueError('Saved-name index outside checked original vector')
        at = self._offsets[slot][index]
        try:
            size = _U32.unpack_from(self._data, at - 4)[0]
            if size > MAX_TEXT_BYTES:
                raise ValueError('Saved-name lookup response byte budget exhausted')
            if size > len(self._data) - at:
                raise ValueError('Saved-name bytes changed or exceed bounds')
            raw = bytes(self._data[at:at + size])
        except (BufferError, TypeError, struct.error) as error:
            raise ValueError('Saved-name buffer is unavailable') from error
        return raw

    def lookup(self, namespace, index):
        raw = self.lookup_raw(namespace, index)
        if raw is None:
            return None
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError('Stored saved-name bytes are not supported UTF-8') from error


def _early_names(data):
    reader = Reader(_Source(data), len(data))
    saved_database_header.read_header(reader)
    saved_database_tables.reach_clubs(reader)
    saved_database.skip_table(reader, 'CLUB', saved_club_records.read_club)
    base_currency_count = 0
    base_currency = None

    def capture_currency(row):
        nonlocal base_currency_count, base_currency
        # Count identity matches before checking their name or rate. A malformed
        # duplicate must not turn a nonunique identity into a verified context.
        if row['native_id'] == 86:
            base_currency_count += 1
            if base_currency_count == 1:
                base_currency = row

    saved_squad_tables.reach_names_after_clubs(
        reader, read_currency_context=capture_currency)
    start = reader.offset
    counts = saved_region_tables.skip_name_tables(reader)
    code = None
    if base_currency_count == 1:
        currency = base_currency
        rate = currency['exchange_rate']
        if (currency['name'] == 'United Kingdom Pound' and
                rate['state'] == 'stored' and rate['value'] == 1.0):
            code = 'GBP'
    return start, reader.offset, counts, code


def _conjunction(data, start, counts, work):
    at = start
    vectors = []
    for count in counts:
        if at + 4 > len(data) or _U32.unpack_from(data, at)[0] != count:
            raise ValueError('Indexed saved-name cardinality mismatch')
        at += 4
        if count * 8 > len(data) - at:
            raise ValueError('Truncated indexed saved-name population')
        offsets = array('I')
        for ordinal in range(count):
            work[0] += 1
            if work[0] > MAX_ROW_WORK:
                raise _Limit('Saved-name validation work budget exhausted')
            if at + 8 > len(data):
                raise ValueError('Truncated indexed saved-name row')
            stored, size = _PAIR.unpack_from(data, at)
            at += 8
            if stored != ordinal:
                raise ValueError('Indexed saved-name original ordinal mismatch')
            if size > len(data) - at:
                raise ValueError('Saved-name string exceeds component extent')
            offsets.append(at)
            at += size
        vectors.append(offsets)
    if at + 5 > len(data):
        raise ValueError('Truncated candidate PERSON header')
    person_count = _U32.unpack_from(data, at)[0]
    flags = data[at + 4]
    if person_count > len(data) - at - 5:
        raise ValueError('Candidate PERSON slots exceed component extent')
    return at, person_count, flags, tuple(vectors)


def locate(data):
    """Locate one complete same-file conjunction, failing closed on ambiguity.

    No filename, count, offset or external source receipt is assumed. Every
    early and late original ordinal is checked. Work-limit failures abort the
    entire search rather than discarding a potentially viable native encoding.
    Opaque native strings are checked physically; UTF-8 is interpreted on lookup.
    """
    try:
        view = memoryview(data)
    except TypeError as error:
        raise ValueError('Supply a read-only saved database buffer') from error
    try:
        if not view.readonly or not view.c_contiguous or view.ndim != 1 or view.itemsize != 1 or view.format != 'B':
            raise ValueError('Supply a contiguous read-only saved database buffer')
        size = view.nbytes
    finally:
        view.release()
    if not 12 <= size <= MAX_RAW_SIZE:
        raise ValueError('Saved database extent exceeds supported bounds')
    early, early_end, counts, base_currency_code = _early_names(data)
    if len(counts) != 3 or any(not 0 <= count <= MAX_NAME_ROWS for count in counts):
        raise ValueError('Unsupported original saved-name cardinalities')
    #Index0 is required by the exhaustive order check and cheaply removes most
    #unrelated count words. Empty first vectors have no row0 to include here.
    needle = struct.pack('<I', counts[0]) + (bytes(4) if counts[0] else b'')
    pattern = re.compile(re.escape(needle))
    work = [sum(counts)]
    attempts = 0
    selected = None
    position = early_end
    while True:
        match = pattern.search(data, position)
        if match is None:
            break
        #Advance one byte, not match.end(): overlapping starts also count.
        position = match.start() + 1
        attempts += 1
        if attempts > MAX_CANDIDATES:
            raise _Limit('Saved-name candidate search budget exhausted')
        try:
            person_at, count, flags, offsets = _conjunction(data, match.start(), counts, work)
        except _Limit:
            raise
        except ValueError:
            continue
        if selected is not None:
            raise ValueError('Ambiguous complete saved-name conjunctions')
        selected = NameLayout(count, person_at, flags, early, early_end,
                              match.start(), tuple(counts), offsets, data,
                              base_currency_code=base_currency_code)
    if selected is None:
        raise ValueError('No complete same-file saved-name conjunction')
    #Unknown flags/offline population bounds do not eliminate a competing full
    #name conjunction. Apply them only after exhaustive physical uniqueness.
    if selected.person_flags & ~1:
        raise ValueError('Unsupported candidate PERSON flags')
    if selected.person_count > MAX_PERSON_ROWS:
        raise _Limit('Candidate PERSON population exceeds supported bounds')
    return selected
