"""Bounded common-PERSON suffix witnesses, never certified population records.

The supported wire subset is source/global 3754, raw64 direct references,
three ordinary (marker-zero) name references and the modern CE96F0 body.
The caller supplies a checked component and same-component name layout.
"""
from dataclasses import dataclass
import copy
import re
import struct


@dataclass(frozen=True)
class SearchBudget:
    lookback_bytes: int = 8192
    max_scan_bytes: int = 8 * 1024**3
    max_identity_hits: int = 500_000
    max_suffix_attempts: int = 2_000_000
    max_witnesses: int = 4096
    max_text_bytes: int = 8192
    max_requested_indices: int = 256
    max_name_bytes: int = 1024 * 1024


SCOPE = {
    "placement": "common_body_suffix_candidate_only",
    "certified_person_record": False,
    "wire_profile": "source3754_global3754_minor9_raw64",
    "wire_profile_is_conditional": True,
    "presence_profile": "CEA86C_pointer_presence_normalized_0_or_1",
    "future_or_legacy_writers": "outside_supported_subset",
    "name_transport": "three_i32_indices_with_zero_markers",
    "excluded": ["inline_name_transports", "whole_person_body", "continuous_table_membership"],
}
_PREFIX = re.compile(rb'(?=(?:(?:.{3}\x00|\xff{4})\x00){3})', re.DOTALL)
_KNOWN_WRITER_TAGS = frozenset((1, 2, 3, 16, 17))


class _Incomplete(Exception):
    pass


class _BudgetStop(Exception):
    pass


def _common_end(data, start, limit, budget):
    """Consume only byte geometry; retain references and text as opaque bytes."""
    at = start + 15

    def take(n):
        nonlocal at
        if n < 0 or n > limit - at:
            raise _Incomplete
        old = at
        at += n
        return old

    def number(fmt):
        return struct.unpack_from('<' + fmt, data, take(struct.calcsize('<' + fmt)))[0]

    def text():
        n = number('I')
        if n > limit - at:
            raise _Incomplete
        if n > budget.max_text_bytes:
            raise _BudgetStop
        take(n)

    text()
    take(14 + 8 + 8 + 8)
    marker = number('B')
    # Paired CEA86C writer: CEACF4/F8 vs CEAD30 emits exactly1 or0;
    # CEAD58..64 CSETNE similarly normalizes the later +08 presence byte.
    # The reader alone is more permissive; this is the declared writer subset.
    if marker not in (0, 1):
        raise _Incomplete
    if marker == 1:
        n = number('B')
        if n > 125:  # Native first collection limit, not an offline work cap.
            raise _Incomplete
        take(n * 16)
        count = number('i')
        if count < 0:
            # 14CD9BC branches on bit31 to failure at14CD96C/990.
            raise _Incomplete
        take(count * 7)
        take(3)
        take(number('B') * 8)
        take(1)
    marker = number('B')
    # Paired CEA86C writer: CEACF4/F8 vs CEAD30 emits exactly1 or0;
    # CEAD58..64 CSETNE similarly normalizes the later +08 presence byte.
    # The reader alone is more permissive; this is the declared writer subset.
    if marker not in (0, 1):
        raise _Incomplete
    if marker == 1:
        count = number('b')  # Native signed <=0 executes zero iterations.
        for _ in range(max(0, count)):
            take(1)
            text()
            take(4)
    return at


def _raw_name(value, limit):
    if isinstance(value, dict):
        raw_hex = value.get('raw_hex')
        if not isinstance(raw_hex, str):
            raise ValueError('Raw name mapping requires raw_hex')
        if len(raw_hex) > limit * 2:
            return {'state': 'budget', 'raw_hex': None, 'text': None}, 0, True
        raw = bytes.fromhex(raw_hex)
    elif isinstance(value, bytes):
        raw = value
    elif isinstance(value, str):
        if len(value) > limit:
            return {'state': 'budget', 'raw_hex': None, 'text': None}, 0, True
        raw = value.encode('utf-8')
    else:
        raise TypeError('Name lookup must return bytes, str or raw_hex mapping')
    if len(raw) > limit:
        return {'state': 'budget', 'raw_hex': None, 'text': None}, 0, True
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = None
    return {"raw_hex": raw.hex(), "text": text}, len(raw), False


def search_candidates(data, layout, person_indices, *, budget=None):
    """Return one ordered result per requested index, including duplicates.

    ``layout`` provides person_count, person_offset, name_counts and
    lookup(namespace, index), where namespace is first/second/common. No numeric-ID equality,
    nonzero-ID rule, text plausibility or unknown next tag rejects a witness.
    Budgets limit work and explicitly make a result incomplete, never absent.
    bytes and mmap support find without copying the component.
    """
    budget = SearchBudget() if budget is None else budget
    if not isinstance(budget, SearchBudget):
        raise TypeError('budget must be SearchBudget')
    for field in budget.__dataclass_fields__:
        if type(getattr(budget, field)) is not int or getattr(budget, field) < 0:
            raise ValueError('budget fields must be nonnegative integers')
    if type(layout.person_count) is not int or not 0 <= layout.person_count <= 0xFFFFFFFF:
        raise ValueError('invalid declared PERSON count')
    requested = []
    for index in person_indices:
        if len(requested) >= budget.max_requested_indices:
            raise ValueError('requested index budget exceeded')
        if type(index) is not int or not 0 <= index < layout.person_count:
            raise ValueError('PERSON index outside declared population')
        requested.append(index)
    if type(layout.person_offset) is not int or not 0 <= layout.person_offset <= len(data) - 5:
        raise ValueError('invalid PERSON table offset')
    namespaces = ('first', 'second', 'common')
    counts = tuple(layout.name_counts[ns] for ns in namespaces)
    if len(counts) != 3 or any(type(n) is not int or n < 0 for n in counts):
        raise ValueError('three checked name counts required')
    if not hasattr(data, 'find'):
        raise TypeError('data must support bounded find (bytes or mmap)')
    if struct.unpack_from('<I', data, layout.person_offset)[0] != layout.person_count:
        raise ValueError('PERSON header count does not match layout')
    prefix_pattern = _PREFIX if all(n <= 1 << 24 for n in counts) else re.compile(rb'(?=(?:.{4}\x00){3})', re.DOTALL)
    lookup = getattr(layout, 'lookup_raw', layout.lookup)
    unique = list(dict.fromkeys(requested))
    reasons = {index: set() for index in unique}
    hits = {index: 0 for index in unique}
    candidates = {index: [] for index in unique}
    bases = {}
    scan_used = attempts = 0
    for index in unique:
        position = layout.person_offset + 13
        needle = struct.pack('<I', index)
        while position + 12 <= len(data):
            available = min(len(data) - position, budget.max_scan_bytes - scan_used)
            if available < 4:
                reasons[index].add('scan_bytes')
                break
            stop = position + available
            found = data.find(needle, position, stop)
            scan_used += stop - position if found < 0 else found - position + 4
            if found < 0:
                if stop < len(data):
                    reasons[index].add('scan_bytes')
                break
            position = found + 1
            if found + 12 > len(data):
                continue
            if len(bases) >= budget.max_identity_hits:
                reasons[index].add('identity_hits')
                break
            bases[found - 8] = index
            hits[index] += 1
    # Merge overlapping reverse windows, so repeated ID occurrences do not cause
    # the same bytes to be parsed thousands of times. Storage is hit-budgeted.
    windows = []
    for base in sorted(bases):
        lower = max(layout.person_offset + 6, base - budget.lookback_bytes)
        if windows and lower <= windows[-1][1]:
            windows[-1][1] = max(windows[-1][1], base)
        else:
            windows.append([lower, base])
    global_reasons = set()
    witness_count = 0
    name_bytes = 0
    for lower, upper in windows:
        if upper - lower > budget.max_scan_bytes - scan_used:
            global_reasons.add('scan_bytes')
            break
        scan_used += upper - lower
        for match in prefix_pattern.finditer(data, lower, upper):
            if attempts >= budget.max_suffix_attempts:
                global_reasons.add('suffix_attempts')
                break
            attempts += 1
            start = match.start()
            a, am, b, bm, c, cm = struct.unpack_from('<iBiBiB', data, start)
            indices = (a, b, c)
            if any(n < -1 or n >= count for n, count in zip(indices, counts)):
                continue
            try:
                end = _common_end(data, start, min(upper, start + budget.lookback_bytes), budget)
            except _BudgetStop:
                global_reasons.add('text_bytes')
                continue
            except _Incomplete:
                continue
            index = bases.get(end)
            if index is None or end - start > budget.lookback_bytes:
                continue
            if witness_count >= budget.max_witnesses:
                global_reasons.add('witnesses')
                break
            found = end + 8
            primary, secondary = struct.unpack_from('<II', data, found + 4)
            next_offset = found + 12
            tag = struct.unpack_from('<b', data, next_offset)[0] if next_offset < len(data) else None
            names = []
            for ns, n in enumerate(indices):
                if n == -1:
                    names.append(None)
                    continue
                limit = min(budget.max_text_bytes, budget.max_name_bytes - name_bytes)
                name, consumed, stopped = _raw_name(lookup(namespaces[ns], n), limit)
                if stopped:
                    reasons[index].add('name_output_bytes')
                names.append(name)
                name_bytes += consumed
            candidates[index].append({
                'common_start': start, 'common_end': end,
                'identity_offset': found, 'end': next_offset,
                'canonical_opaque8_hex': bytes(data[end:found]).hex(),
                'identity': {'stored_index': index, 'native_id_word': primary, 'secondary_word': secondary},
                'name_indices': list(indices), 'name_markers': [0, 0, 0], 'names': names,
                'next_tag': tag, 'known_paired_writer_next_tag': tag in _KNOWN_WRITER_TAGS,
                'identity_words_equal': primary == secondary,
                'zero_identity_word': primary == 0 or secondary == 0,
                'evidence_scope': dict(SCOPE),
            })
            witness_count += 1
        if global_reasons & {'suffix_attempts', 'witnesses'}:
            break
    results = {}
    for index in unique:
        why = reasons[index] | global_reasons
        witnesses = candidates[index]
        state = 'budget' if why else ('missing' if not witnesses else 'witnessed' if len(witnesses) == 1 else 'ambiguous')
        results[index] = {'person_index': index, 'state': state, 'candidates': witnesses,
                          'search_complete': not why, 'budget_reasons': sorted(why),
                          'identity_hits': hits[index], 'shared_suffix_attempts': attempts,
                          'evidence_scope': {**SCOPE, 'lookback_bytes': budget.lookback_bytes,
                                             'missing_means': 'no_witness_in_supported_subset',
                                             'layout_provenance': getattr(layout, 'provenance', None)}}
    # Independent objects prevent callers mutating a duplicate request's result.
    return [copy.deepcopy(results[index]) for index in requested]
