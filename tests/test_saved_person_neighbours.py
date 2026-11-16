import copy
import struct
from types import SimpleNamespace

import pytest

from fm_live_mcp.saved_person_neighbours import NeighbourBudget, corroborate_candidates


def common():
    return b''.join(struct.pack('<iB', n, 0) for n in (1, 2, -1)) + bytes(4 + 38 + 2)


def regular(index, first=100, second=200):
    return b'\x02PFX!' + common() + bytes(8) + struct.pack('<III', index, first, second)


def compact(index, selector=2, first=0, second=999):
    return (b'\x10' + bytes([selector]) + (bytes(4) if selector == 0 else b'') + bytes(4 + 8) +
            struct.pack('<III', index, first, second))


def make_source(*records):
    data = struct.pack('<IB', 100, 1) + b''.join(records)
    layout = SimpleNamespace(person_count=100, person_offset=0,
                             name_counts=dict(first=10, second=10, common=10),
                             lookup=lambda *_: b'unimportant')
    starts = []
    at = 5
    for record in records:
        starts.append(at)
        at += len(record)
    return data, layout, starts


def candidate(start, index, first=100, second=200):
    at = start + 5
    end = at + len(common())
    return {'common_start': at, 'common_end': end, 'identity_offset': end + 8,
            'end': end + 20, 'identity': {'stored_index': index,
                                        'native_id_word': first, 'secondary_word': second},
            'names': [{'text': 'Name is not evidence'}], 'name_indices': [1, 2, -1]}


def row(index, *candidates, complete=True):
    return {'person_index': index, 'state': 'ambiguous', 'candidates': list(candidates),
            'search_complete': complete, 'budget_reasons': []}


def probe(data, start, upper):
    if data[start:start + 5] != b'\x02PFX!' or start + 5 > upper:
        return None
    return {'start': start, 'end': start + 5, 'state': 'typed_prefix_stopped',
            'native_reader': 'checked_test_profile', 'complete_person': False}


def test_two_independent_compact_neighbours_rank_true_geometry_and_keep_alternative():
    data, layout, starts = make_source(regular(7, 42, 42), compact(6), regular(7), compact(8))
    false, true = candidate(starts[0], 7, 42, 42), candidate(starts[2], 7)
    inputs = [row(7, false, true)]
    result, = corroborate_candidates(data, layout, inputs, neighbour_rows=[row(6), row(8)])
    assert len(result['candidates']) == 2
    assert result['candidates'][0]['common_start'] == true['common_start']
    evidence = result['candidates'][0]['neighbour_evidence']
    assert evidence['tier'] == 'two_typed_neighbour_boundaries'
    assert evidence['preceding'][0]['person_index'] == 6
    assert evidence['following'][0]['person_index'] == 8
    assert any(p['kind'] == 'native_compact16' for p in evidence['preceding'])
    assert not evidence['certified_person_record']
    assert result['neighbour_corroboration']['state'] == 'unique_strongest_local_witness'
    assert 'neighbour_evidence' not in inputs[0]['candidates'][0]


@pytest.mark.parametrize('selector', [0, 1, 2, 3])
def test_compact_selector_branches_without_id_equality(selector):
    data, layout, starts = make_source(compact(6, selector), regular(7, 0, 77), compact(8, selector))
    result, = corroborate_candidates(data, layout, [row(7, candidate(starts[1], 7, 0, 77))],
                                     neighbour_rows=[row(6), row(8)])
    assert result['candidates'][0]['neighbour_evidence']['tier_order'] == 4


def test_two_common_neighbours_need_independent_typed_probes_to_strengthen():
    data, layout, starts = make_source(regular(6), regular(7), regular(8))
    target = [row(7, candidate(starts[1], 7))]
    neighbours = [row(6, candidate(starts[0], 6)), row(8, candidate(starts[2], 8))]
    plain, = corroborate_candidates(data, layout, target, neighbour_rows=neighbours)
    typed, = corroborate_candidates(data, layout, target, neighbour_rows=neighbours, prefix_probe=probe)
    assert plain['candidates'][0]['neighbour_evidence']['tier_order'] == 2
    assert plain['neighbour_corroboration']['preferred_geometries'] == []
    assert typed['candidates'][0]['neighbour_evidence']['tier_order'] == 4
    assert typed['candidates'][0]['neighbour_evidence']['following'][0]['next_prefix']['start'] == target[0]['candidates'][0]['end']


def test_target_cannot_corroborate_itself():
    data, layout, starts = make_source(regular(7))
    target = row(7, candidate(starts[0], 7))
    result, = corroborate_candidates(data, layout, [target], neighbour_rows=[target], prefix_probe=probe)
    assert result['candidates'][0]['neighbour_evidence']['tier_order'] == 0
    assert result['neighbour_corroboration']['preferred_geometries'] == []


def test_false_neighbour_ordinal_and_reversed_boundaries_are_rejected():
    data, layout, starts = make_source(regular(8), regular(7), regular(6))
    neighbours = [row(6, candidate(starts[0], 6)), row(8, candidate(starts[2], 8))]
    result, = corroborate_candidates(data, layout, [row(7, candidate(starts[1], 7))],
                                     neighbour_rows=neighbours, prefix_probe=probe)
    assert result['candidates'][0]['neighbour_evidence']['tier_order'] == 0


def test_missing_and_truncated_compact_neighbour_is_not_empty_membership():
    data, layout, starts = make_source(compact(6), regular(7), compact(8))
    result, = corroborate_candidates(data[:-1], layout, [row(7, candidate(starts[1], 7))],
                                     neighbour_rows=[row(6), row(8)])
    evidence = result['candidates'][0]['neighbour_evidence']
    assert evidence['tier_order'] == 1 and not evidence['following']
    assert result['neighbour_corroboration']['certified_person_record'] is False


def test_fabricated_target_extent_is_not_ranked():
    data, layout, starts = make_source(compact(6), regular(7), compact(8))
    bad = candidate(starts[1], 7)
    bad['identity_offset'] += 1
    result, = corroborate_candidates(data, layout, [row(7, bad)], neighbour_rows=[row(6), row(8)])
    assert not result['candidates'][0]['neighbour_evidence']['target_bytes_rechecked']
    assert result['candidates'][0]['neighbour_evidence']['tier_order'] == 0


@pytest.mark.parametrize('budget,reason', [
    (NeighbourBudget(max_scan_bytes=0), 'neighbour_scan_bytes'),
    (NeighbourBudget(max_identity_hits=0), 'neighbour_identity_hits'),
    (NeighbourBudget(max_neighbour_indices=0), 'neighbour_indices'),
    (NeighbourBudget(max_packets_per_side=0), 'neighbour_packets'),
])
def test_budgets_and_windows_explicit(budget, reason):
    data, layout, starts = make_source(compact(6), regular(7), compact(8))
    result, = corroborate_candidates(data, layout, [row(7, candidate(starts[1], 7))],
                                     neighbour_rows=[row(6), row(8)], budget=budget)
    state = result['neighbour_corroboration']
    assert not state['search_complete'] and reason in state['budget_reasons']
    assert state['state'] == 'incomplete_neighbour_corroboration'


def test_prefix_budget_cannot_be_reported_as_complete():
    data, layout, starts = make_source(regular(6), regular(7), regular(8))
    neighbours = [row(6, candidate(starts[0], 6)), row(8, candidate(starts[2], 8))]
    result, = corroborate_candidates(data, layout, [row(7, candidate(starts[1], 7))],
                                     neighbour_rows=neighbours, prefix_probe=probe,
                                     budget=NeighbourBudget(max_prefix_probes=0))
    assert 'prefix_probes' in result['neighbour_corroboration']['budget_reasons']
    assert result['neighbour_corroboration']['state'] == 'incomplete_neighbour_corroboration'


def test_forged_probe_extent_cannot_strengthen():
    data, layout, starts = make_source(regular(6), regular(7), regular(8))
    neighbours = [row(6, candidate(starts[0], 6)), row(8, candidate(starts[2], 8))]
    def invalid(data, start, upper):
        return {'start': start, 'end': upper + 1, 'state': 'typed_prefix_stopped', 'native_reader': 'bad'}
    result, = corroborate_candidates(data, layout, [row(7, candidate(starts[1], 7))],
                                     neighbour_rows=neighbours, prefix_probe=invalid)
    assert result['candidates'][0]['neighbour_evidence']['tier_order'] == 2


def test_competing_equal_tiers_stay_ambiguous():
    records = [compact(6), regular(7), compact(8), compact(6), regular(7), compact(8)]
    data, layout, starts = make_source(*records)
    result, = corroborate_candidates(data, layout,
        [row(7, candidate(starts[1], 7), candidate(starts[4], 7))], neighbour_rows=[row(6), row(8)])
    assert result['neighbour_corroboration']['state'] == 'competing_strongest_local_witnesses'
    assert len(result['neighbour_corroboration']['preferred_geometries']) == 2


def test_separate_default_suffix_search_and_duplicate_requests():
    data, layout, starts = make_source(regular(6), regular(7), regular(8))
    target = row(7, candidate(starts[1], 7))
    results = corroborate_candidates(data, layout, [target, copy.deepcopy(target)], prefix_probe=probe)
    assert results[0]['candidates'][0]['neighbour_evidence']['tier_order'] == 4
    results[0]['candidates'].clear()
    assert results[1]['candidates']


def test_unsupported_record_window_is_distinct_from_missing_neighbour():
    data, layout, starts = make_source(compact(6), regular(7), compact(8))
    result, = corroborate_candidates(data, layout, [row(7, candidate(starts[1], 7))],
                                     neighbour_rows=[row(6), row(8)],
                                     budget=NeighbourBudget(max_record_bytes=0))
    evidence = result['candidates'][0]['neighbour_evidence']
    assert evidence['tier_order'] == 0
    assert result['neighbour_corroboration']['local_record_window_bytes'] == 0


def test_second_neighbours_break_synthetic_tie_without_removing_alternative():
    records = [regular(5), regular(6), regular(7), regular(8), regular(9),
               regular(6), regular(7), regular(8)]
    data, layout, starts = make_source(*records)
    targets = [row(7, candidate(starts[2], 7), candidate(starts[6], 7))]
    result, = corroborate_candidates(data, layout, targets, prefix_probe=probe)
    assert result['neighbour_corroboration']['second_neighbour_state'] == 'bounded_second_neighbours_checked'
    assert result['candidates'][0]['common_start'] == starts[2] + 5
    assert result['candidates'][0]['neighbour_evidence']['tier_order'] == 5
    assert result['candidates'][1]['neighbour_evidence']['tier_order'] == 4
    assert len(result['candidates']) == 2
    assert len(result['neighbour_corroboration']['preferred_geometries']) == 1
    for state in result['candidates'][0]['neighbour_evidence']['second_neighbours']['searches'].values():
        assert state['scope'] == 'bounded_physical_windows'


def test_target_incomplete_budget_is_not_erased_by_strong_neighbours():
    data, layout, starts = make_source(compact(6), regular(7), compact(8))
    result, = corroborate_candidates(data, layout,
        [row(7, candidate(starts[1], 7), complete=False)])
    assert result['neighbour_corroboration']['state'] == 'incomplete_neighbour_corroboration'
    assert 'target_suffix_search_incomplete' in result['neighbour_corroboration']['budget_reasons']
