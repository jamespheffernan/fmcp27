"""Corroborate local PERSON suffix witnesses with distinct adjacent ordinals.

Physical ordering is an explicit source-order hypothesis. Neither a suffix nor
an adjacent packet certifies continuous membership in the whole PERSON table.
Names and identity-word equality never affect ranking. Native compact16 grammar:
15C48E8, source3754/body1/read_base1; selector0 adds u32, selectors1..3 do not;
then u32+8 raw bytes+12 canonical identity bytes. Other tags remain unsupported.
"""
import copy
from dataclasses import dataclass
import struct

from . import saved_person_candidates as suffix
from .saved_player_wire_prefix import prefix_probe as _native_prefix_probe


@dataclass(frozen=True)
class NeighbourBudget:
    max_record_bytes: int = 65536
    max_scan_bytes: int = 8 * 1024**3
    max_identity_hits: int = 100000
    max_neighbour_indices: int = 128
    max_packets_per_side: int = 64
    max_prefix_probes: int = 4096
    max_local_suffix_attempts: int = 200000
    max_local_packets: int = 4096


_TIERS = (
    'uncorroborated', 'one_ordered_neighbour', 'two_ordered_common_neighbours',
    'two_ordered_neighbours_with_typed_packet', 'two_typed_neighbour_boundaries',
    'five_ordered_ordinals_with_typed_neighbours',
)


def _compact(data, start, ordinal, lower, upper):
    if start < lower or start >= upper or data[start] != 16:
        return None
    at = start + 1
    if at >= upper or data[at] not in (0, 1, 2, 3):
        return None
    selector = data[at]
    end = at + 1 + (4 if selector == 0 else 0) + 4 + 8 + 12
    if end > upper:
        return None
    identity_at = end - 12
    if struct.unpack_from('<I', data, identity_at)[0] != ordinal:
        return None
    return {'person_index': ordinal, 'kind': 'native_compact16', 'start': start,
            'suffix_start': start, 'identity_offset': identity_at, 'end': end,
            'complete_local_packet': True, 'native_reader': '0x15C48E8'}


def _common_packet(data, layout, candidate, ordinal):
    """Recheck neighbour bytes; never use a target as its own neighbour."""
    try:
        start, end = candidate['common_start'], candidate['common_end']
        identity_at, stop = candidate['identity_offset'], candidate['end']
        if any(type(n) is not int for n in (start, end, identity_at, stop)):
            return None
        if not layout.person_offset + 5 <= start < end <= identity_at < stop <= len(data):
            return None
        if identity_at != end + 8 or stop != identity_at + 12:
            return None
        values = struct.unpack_from('<iBiBiB', data, start)
        if values[1::2] != (0, 0, 0):
            return None
        for ns, value in zip(('first', 'second', 'common'), values[::2]):
            if value < -1 or value >= layout.name_counts[ns]:
                return None
        if suffix._common_end(data, start, end, suffix.SearchBudget()) != end:
            return None
        actual = struct.unpack_from('<III', data, identity_at)
        if actual[0] != ordinal:
            return None
        reported = candidate.get('identity')
        if reported is not None and not isinstance(reported, dict):
            return None
        if reported is not None and any(reported.get(key) != value for key, value in zip(
                ('stored_index', 'native_id_word', 'secondary_word'), actual)):
            return None
        if 'name_indices' in candidate and tuple(candidate['name_indices']) != values[::2]:
            return None
    except (KeyError, ValueError, struct.error, suffix._Incomplete, suffix._BudgetStop):
        return None
    return {'person_index': ordinal, 'kind': 'common_suffix', 'start': None,
            'suffix_start': start, 'identity_offset': identity_at, 'end': stop,
            'complete_local_packet': False, 'native_reader': '0xCE96F0',
            'wire_profile': suffix.SCOPE['wire_profile']}


def corroborate_candidates(data, layout, rows, *, budget=None, neighbour_rows=None,
                           prefix_probe=None, suffix_budget=None):
    """Return copies, ranked by explicit independent neighbour evidence.

    prefix_probe(data,start,upper) returns a positive checked
    native prefix packet with keys start,end,state,native_reader;
    state is typed_prefix_stopped or complete. Its end must not cross the
    independently witnessed suffix start. It must decode bytes from start and
    must not accept a candidate/name as input. The default uses the checked
    native regular-player prefix; pass False to disable prefix corroboration.
    Optional neighbour_rows must come from a separate same-component suffix
    search; all their bytes/ordinals are rechecked. Without them, scan index±1.
    """
    if prefix_probe is None:
        prefix_probe = _native_prefix_probe
    elif prefix_probe is False:
        prefix_probe = None
    budget = NeighbourBudget() if budget is None else budget
    if not isinstance(budget, NeighbourBudget) or any(
            type(getattr(budget, key)) is not int or getattr(budget, key) < 0
            for key in budget.__dataclass_fields__):
        raise ValueError('Invalid neighbour budget')
    result = copy.deepcopy(list(rows))
    indices = []
    for row in result:
        index = row['person_index']
        if type(index) is not int or not 0 <= index < layout.person_count:
            raise ValueError('Invalid target PERSON ordinal')
        indices.extend(n for n in (index - 1, index + 1) if 0 <= n < layout.person_count)
    needed = list(dict.fromkeys(indices))
    reasons = set()
    if len(needed) > budget.max_neighbour_indices:
        reasons.add('neighbour_indices')
        needed = needed[:budget.max_neighbour_indices]
    packets = {index: [] for index in needed}
    searches = {}
    windows = {index: [] for index in needed}
    lower = layout.person_offset + 5
    for row in result:
        for candidate in row.get('candidates', []):
            target = _common_packet(data, layout, candidate, row['person_index'])
            if target is None:
                continue
            for index, low, high in (
                    (row['person_index'] - 1,
                     target['end'] - budget.max_record_bytes - 12, target['suffix_start']),
                    (row['person_index'] + 1,
                     target['end'], target['end'] + budget.max_record_bytes)):
                if index in windows:
                    low, high = max(lower, low), min(len(data), high)
                    if low < high:
                        windows[index].append((low, high))
    if neighbour_rows is not None:
        for row in neighbour_rows:
            index = row.get('person_index')
            if index not in packets:
                continue
            # Supplied packets are still byte-checked and subject to the same
            # physical window when attached to a target below.
            for candidate in row.get('candidates', []):
                packet = _common_packet(data, layout, candidate, index)
                if packet is not None:
                    packets[index].append(packet)
    scanned = hits = attempts = packet_count = 0
    local_limits = suffix.SearchBudget() if suffix_budget is None else suffix_budget

    def local_packets(index, ranges):
        nonlocal scanned, hits, attempts, packet_count
        merged = []
        for low, high in sorted(ranges):
            if merged and low <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], high)
            else:
                merged.append([low, high])
        found_packets = []
        needle = struct.pack('<I', index)
        complete = True
        for low, high in merged:
            position = low
            while position + 4 <= high:
                allowance = min(high - position, budget.max_scan_bytes - scanned)
                if allowance < 4:
                    reasons.add('neighbour_scan_bytes')
                    complete = False
                    break
                stop = position + allowance
                identity_at = data.find(needle, position, stop)
                scanned += stop - position if identity_at < 0 else identity_at - position + 4
                if identity_at < 0:
                    if stop < high:
                        reasons.add('neighbour_scan_bytes')
                        complete = False
                    break
                position = identity_at + 1
                if hits >= budget.max_identity_hits:
                    reasons.add('neighbour_identity_hits')
                    complete = False
                    break
                hits += 1
                if identity_at + 12 > len(data):
                    continue
                options = []
                for distance in (14, 18):
                    packet = _compact(data, identity_at - distance, index, lower, len(data))
                    if packet is not None and packet['identity_offset'] == identity_at:
                        options.append(packet)
                common_end = identity_at - 8
                lookback = max(lower, common_end - local_limits.lookback_bytes)
                # Reverse geometry is shared with the candidate reader; this
                # window is a declared lookback, not an invented table header.
                if common_end > lookback:
                    for match in suffix._PREFIX.finditer(data, lookback, common_end):
                        if attempts >= budget.max_local_suffix_attempts:
                            reasons.add('neighbour_suffix_attempts')
                            complete = False
                            break
                        attempts += 1
                        packet = _common_packet(data, layout, {
                            'common_start': match.start(), 'common_end': common_end,
                            'identity_offset': identity_at, 'end': identity_at + 12}, index)
                        if packet is not None:
                            options.append(packet)
                for packet in options:
                    if packet_count >= budget.max_local_packets:
                        reasons.add('neighbour_packets')
                        complete = False
                        break
                    packet_count += 1
                    found_packets.append(packet)
                if not complete:
                    break
        return found_packets, {'search_complete': complete, 'scope': 'bounded_physical_windows',
                               'identity_windows': merged,
                               'suffix_lookback_bytes': local_limits.lookback_bytes,
                               'budget_reasons': sorted(reasons)}

    for index in needed:
        found, scope = local_packets(index, windows[index])
        packets[index].extend(found)
        searches[index] = scope
    for index in packets:
        unique = {(p['kind'], p['suffix_start'], p['identity_offset'], p['end']): p
                  for p in packets[index]}
        packets[index] = sorted(unique.values(), key=lambda p: (p['end'], p['suffix_start']))
    probes = 0
    probe_cache = {}

    def probe(start, ordinal, suffix_start):
        nonlocal probes
        key = (start, ordinal)
        if key in probe_cache:
            cached = probe_cache[key]
            return cached if cached is not None and cached['end'] <= suffix_start else None
        if prefix_probe is None:
            return None
        if probes >= budget.max_prefix_probes:
            reasons.add('prefix_probes')
            return None
        if start < lower or not start < suffix_start <= len(data):
            return None
        probes += 1
        upper = min(len(data), start + budget.max_record_bytes)
        try:
            packet = prefix_probe(data, start, upper)
        except (ValueError, struct.error):
            packet = None
        if not isinstance(packet, dict):
            return None
        packet = dict(packet)
        packet.setdefault('state', packet.get('status'))
        packet.setdefault('end', packet.get('parsed_end'))
        if (packet.get('start') != start or
                packet.get('state') not in ('typed_prefix_stopped', 'complete') or
                not packet.get('native_reader') or type(packet.get('end')) is not int or
                not start < packet['end'] <= upper):
            return None
        if 'budget' in str(packet.get('stop_reason', '')):
            reasons.add('typed_prefix_work_budget')
        probe_cache[key] = copy.deepcopy(packet)
        return probe_cache[key] if packet['end'] <= suffix_start else None

    for row in result:
        index = row['person_index']
        local_reasons = set(reasons)
        if not row.get('search_complete', False):
            local_reasons.add('target_suffix_search_incomplete')
        neighbour_scope = {str(n): searches.get(n, {'search_complete': False,
                           'budget_reasons': ['neighbour_not_searched']})
                           for n in (index - 1, index + 1) if 0 <= n < layout.person_count}
        for state in neighbour_scope.values():
            if not state['search_complete']:
                local_reasons.add('neighbour_suffix_search_incomplete')
        for candidate in row.get('candidates', []):
            target = _common_packet(data, layout, candidate, index)
            evidence = {'tier': _TIERS[0], 'tier_order': 0, 'preceding': [], 'following': [],
                        'certified_person_record': False,
                        'ordering_basis': 'distinct stored ordinals index-1/index/index+1 in physical order',
                        'table_membership': 'not_certified', 'target_bytes_rechecked': target is not None,
                        'unsupported_windows': []}
            if target is not None:
                prev = [p for p in packets.get(index - 1, [])
                        if p['end'] <= target['suffix_start'] and
                        target['end'] - p['end'] <= budget.max_record_bytes]
                following = [p for p in packets.get(index + 1, [])
                             if target['end'] <= p['suffix_start'] and
                             p['end'] - target['end'] <= budget.max_record_bytes and
                             (p['kind'] != 'native_compact16' or p['start'] == target['end'])]
                if any(p['end'] <= target['suffix_start'] and
                       target['end'] - p['end'] > budget.max_record_bytes
                       for p in packets.get(index - 1, [])) and not prev:
                    evidence['unsupported_windows'].append('preceding_record_window')
                if any(target['end'] <= p['suffix_start'] and
                       p['end'] - target['end'] > budget.max_record_bytes
                       for p in packets.get(index + 1, [])) and not following:
                    evidence['unsupported_windows'].append('following_record_window')
                for side, options in (('preceding', prev), ('following', following)):
                    if len(options) > budget.max_packets_per_side:
                        local_reasons.add('neighbour_packets')
                    for packet in options[:budget.max_packets_per_side]:
                        item = copy.deepcopy(packet)
                        if side == 'preceding':
                            item['target_prefix'] = probe(packet['end'], index, target['suffix_start'])
                            item['typed_boundary'] = (packet['kind'] == 'native_compact16' or
                                                      item['target_prefix'] is not None)
                        else:
                            item['next_prefix'] = (None if packet['kind'] == 'native_compact16' else
                                                   probe(target['end'], index + 1, packet['suffix_start']))
                            item['typed_boundary'] = (packet['kind'] == 'native_compact16' or
                                                      item['next_prefix'] is not None)
                        evidence[side].append(item)
                left, right = evidence['preceding'], evidence['following']
                left_typed = any(p['typed_boundary'] for p in left)
                right_typed = any(p['typed_boundary'] for p in right)
                tier = (4 if left and right and left_typed and right_typed else
                        3 if left and right and (left_typed or right_typed) else
                        2 if left and right else 1 if left or right else 0)
                evidence.update(tier=_TIERS[tier], tier_order=tier,
                                independent_preceding_count=len({(p['identity_offset'], p['end']) for p in prev}),
                                independent_following_count=len({(p['identity_offset'], p['end']) for p in following}),
                                preceding_packet_options=len(prev), following_packet_options=len(following))
            candidate['neighbour_evidence'] = evidence
        top_tier = max((c['neighbour_evidence']['tier_order'] for c in row['candidates']), default=0)
        tied = [c for c in row['candidates'] if c['neighbour_evidence']['tier_order'] == top_tier]
        geometries = {(c['common_start'], c['identity_offset']) for c in tied}
        second_state = 'not_needed_unique_or_insufficient_typed_tier'
        if top_tier >= 3 and len(geometries) > 1:
            second_state = 'bounded_second_neighbours_checked'
            for candidate in tied:
                evidence = candidate['neighbour_evidence']
                target = _common_packet(data, layout, candidate, index)
                outer = {}
                scopes = {}
                for ordinal, low, high in (
                        (index - 2, target['end'] - 2 * budget.max_record_bytes - 12,
                         target['suffix_start']),
                        (index + 2, target['end'], target['end'] + 2 * budget.max_record_bytes)):
                    if not 0 <= ordinal < layout.person_count:
                        outer[ordinal] = []
                        continue
                    low, high = max(lower, low), min(len(data), high)
                    found, scope = local_packets(ordinal, [(low, high)] if low < high else [])
                    outer[ordinal] = found
                    scopes[str(ordinal)] = scope
                links = {'preceding': [], 'following': []}
                for side, ordinal in (('preceding', index - 2), ('following', index + 2)):
                    for packet in outer.get(ordinal, []):
                        compatible = []
                        for inner in evidence[side]:
                            if side == 'preceding':
                                valid = (packet['end'] <= inner['suffix_start'] and
                                         inner['end'] - packet['end'] <= budget.max_record_bytes and
                                         (inner['kind'] != 'native_compact16' or
                                          packet['end'] == inner['start']))
                            else:
                                valid = (inner['end'] <= packet['suffix_start'] and
                                         packet['end'] - inner['end'] <= budget.max_record_bytes and
                                         (packet['kind'] != 'native_compact16' or
                                          inner['end'] == packet['start']))
                            if valid:
                                compatible.append(inner)
                        if compatible:
                            links[side].append({'outer': packet,
                                                'inner_identity_offsets': sorted({p['identity_offset'] for p in compatible}),
                                                'inner_typed': any(p['typed_boundary'] for p in compatible)})
                    if len(links[side]) > budget.max_packets_per_side:
                        local_reasons.add('second_neighbour_links')
                        links[side] = links[side][:budget.max_packets_per_side]
                evidence['second_neighbours'] = {'searches': scopes, **links,
                    'basis': 'five distinct stored ordinals in physical order; compact seams exact'}
                if (links['preceding'] and links['following'] and
                        any(p['inner_typed'] for side in links.values() for p in side)):
                    evidence.update(tier=_TIERS[5], tier_order=5)
        row['candidates'].sort(key=lambda c: (-c['neighbour_evidence']['tier_order'],
                                              c['common_start'], c['identity_offset']))
        strongest = max((c['neighbour_evidence']['tier_order'] for c in row['candidates']), default=0)
        preferred = sorted({(c['common_start'], c['identity_offset']) for c in row['candidates']
                            if c['neighbour_evidence']['tier_order'] == strongest and strongest >= 3})
        row['neighbour_corroboration'] = {
            'state': ('unique_strongest_local_witness' if len(preferred) == 1 else
                      'competing_strongest_local_witnesses' if preferred else 'insufficient_typed_neighbours'),
            'strongest_tier': _TIERS[strongest], 'second_neighbour_state': second_state,
            'preferred_geometries': [{'common_start': a, 'identity_offset': b} for a, b in preferred],
            'alternatives_retained': len(row['candidates']), 'neighbour_searches': neighbour_scope,
            'budget_reasons': sorted(local_reasons | reasons),
            'search_complete': not local_reasons and not reasons,
            'certified_person_record': False,
            'source_order_hypothesis': 'canonical stored ordinal order; not a continuous table walk',
            'unsupported': ['inline-name suffixes', 'unparsed regular-player remainder', 'other typed body profiles'],
            'local_record_window_bytes': budget.max_record_bytes,
        }
    for row in result:
        state = row['neighbour_corroboration']
        state['budget_reasons'] = sorted(set(state['budget_reasons']) | reasons)
        if state['budget_reasons']:
            state['search_complete'] = False
            state['state'] = 'incomplete_neighbour_corroboration'
    return result
